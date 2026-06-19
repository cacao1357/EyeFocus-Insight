"""
analyzer/focus.py — 专注度分析器 (v4.13)

v4.13: 评分算法重构
  - 窗口 30s→15s，响应更快
  - 新增相对眨眼评分（对比个人基线，非绝对阈值）
  - EMA 平滑（快速下降 α=0.4，慢速恢复 α=0.15）— 阶梯式响应
  - 头部得分平滑化（渐变替代二元）
  - 混合分权重：眼70% + 头20% + 视线10%
  - 人脸丢失 → 冻结分数
"""

import logging
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, List, Optional

import numpy as np

from storage.models import FocusRecord

logger = logging.getLogger("eyefocus.analyzer")


# ═══════════════════════════════════════════════════
# FocusLevel 三档
# ═══════════════════════════════════════════════════

class FocusLevel(Enum):
    FOCUSED = "focused"
    NORMAL = "normal"
    DISTRACTED = "distracted"


FOCUS_LEVEL_LABELS = {
    FocusLevel.FOCUSED: "专注",
    FocusLevel.NORMAL: "一般",
    FocusLevel.DISTRACTED: "分心",
}

# v4.13: 窗口 15s，阈值对应缩小
FOCUSED_MAX_DEVIATION_SECS = 3      # ≤3 秒偏差 → FOCUSED
DISTRACTED_MIN_DEVIATION_SECS = 8   # ≥8 秒偏差 → DISTRACTED


@dataclass
class FocusResult:
    """专注度分析结果"""
    focus_level: FocusLevel = FocusLevel.NORMAL
    eye_openness: float = 1.0
    eye_stability: float = 1.0
    blink_rate: float = 0.0
    is_attentive: bool = True
    # 向后兼容（旧代码读 .focus_score 不崩溃）
    focus_score: float = 50.0
    eye_score: float = 50.0
    head_score: float = 50.0
    gaze_score: float = 50.0
    # v4.13: 人脸丢失标志（调用方可据此跳过UI更新）
    face_lost: bool = False


class KalmanFilter1D:
    """一维卡尔曼滤波器"""

    def __init__(self, process_variance: float = 0.001, measurement_variance: float = 0.1):
        self.process_variance = process_variance
        self.measurement_variance = measurement_variance
        self.estimate: Optional[float] = None
        self.estimation_error = 1.0

    def update(self, measurement: float) -> float:
        if self.estimate is None:
            self.estimate = measurement
            return self.estimate
        self.estimation_error += self.process_variance
        kalman_gain = self.estimation_error / (self.estimation_error + self.measurement_variance)
        self.estimate += kalman_gain * (measurement - self.estimate)
        self.estimation_error *= (1 - kalman_gain)
        return self.estimate

    def reset(self) -> None:
        self.estimate = None
        self.estimation_error = 1.0


class FocusAnalyzer:
    """专注度分析器 (v4.13)

    15s 滑动窗口 + 相对眨眼评分 + EMA 阶梯平滑。

    眼部得分 = 睁眼度×35% + 稳定性×35% + 相对眨眼×30%
    综合分   = 眼部×70% + 头部×20% + 视线×10%
    """

    # 头部舒适区（在此角度内不扣分）
    _COMFORT_YAW = 18.0
    _COMFORT_PITCH = 22.0

    # v4.13: 混合分权重（头部提升至20%，转头/低头是分心强信号）
    _EYE_BLEND = 0.70
    _HEAD_BLEND = 0.20
    _GAZE_BLEND = 0.10

    # v4.13: 头部惩罚缩放（平滑过渡，舒适区→32°/40°满分惩罚）
    _YAW_SCALE = 20.0
    _PITCH_SCALE = 25.0

    # v4.39: 最小舒适角（避免 baseline_std 太小导致过度敏感）
    _MIN_COMFORT_YAW = 8.0
    _MIN_COMFORT_PITCH = 10.0

    # v4.13: EMA 平滑系数
    _EMA_FAST = 0.40   # 下降快（分心时迅速反应）
    _EMA_SLOW = 0.20   # v4.14: 0.15→0.20 恢复稍快

    # v4.13: 相对眨眼基线参数
    _BLINK_BASELINE_COLLECT_SECS = 120.0  # 前2分钟收集基线样本
    _BLINK_BASELINE_ADAPT_INTERVAL = 30.0  # 每30秒缓慢自适应
    _BLINK_BASELINE_ADAPT_RATE = 0.02      # v4.14: 0.03→0.02 更稳定

    # v4.14: EAR 自动基线
    _EAR_AUTO_COLLECT_SECS = 120.0
    _EAR_AUTO_MIN_SAMPLES = 30
    _EAR_AUTO_MIN_VALUE = 0.18
    _EAR_AUTO_DIFF_THRESHOLD = 0.15

    # v4.14: 会话衰减
    _DECAY_FREE_MINUTES = 30.0
    _DECAY_RATE_PER_MINUTE = 0.00167
    _DECAY_FLOOR = 0.85

    # ── v4.35: 动态权重场景阈值 ──
    _BRIGHT_LOW = 80.0        # 低于此认为低光
    _YAW_EXTREME = 25.0       # 超过此认为极端角度
    _PITCH_EXTREME = 30.0

    def __init__(
        self,
        baseline_ear: float = 0.25,
        baseline_yaw_std: float = 3.0,
        baseline_pitch_std: float = 3.0,
        eye_weight: float = 0.35,
        head_weight: float = 0.30,
        gaze_weight: float = 0.35,
        window_size: float = 15.0,       # v4.13: 15s 窗口
        fps: float = 30.0,
        enable_kalman: bool = False,
        adjustment_factor: float = 1.0,  # v4.35: 校准调整因子
    ):
        self.baseline_ear = baseline_ear
        self.baseline_yaw_std = baseline_yaw_std
        self.baseline_pitch_std = baseline_pitch_std
        self.window_size = window_size
        self.fps = fps
        self._adjustment_factor: float = adjustment_factor

        self._max_samples = int(window_size)
        self._window_samples: Deque[float] = deque(maxlen=self._max_samples)
        self._last_sample_second: int = -1

        self._blink_detector = None
        self._current_level = FocusLevel.NORMAL
        self._face_lost_start_time: Optional[float] = None

        # v4.13: EMA 平滑
        self._ema_score: Optional[float] = None

        # v4.13: 人脸丢失时保存的最后分数
        self._last_eye_score: float = 50.0
        self._last_head_score: float = 50.0
        self._last_gaze_score: float = 50.0
        self._last_focus_score: float = 50.0
        self._last_openness: float = 1.0
        self._last_stability: float = 1.0

        # v4.13: 相对眨眼基线
        self._blink_baseline: Optional[float] = None
        self._blink_baseline_samples: List[float] = []
        self._blink_baseline_ready: bool = False
        self._blink_baseline_start_time: Optional[float] = None
        self._blink_baseline_update_time: float = 0.0

        # v4.14: EAR 自动基线
        self._ear_auto_samples: List[float] = []
        self._ear_auto_start_time: Optional[float] = None
        self._ear_auto_applied: bool = False

        # v4.14: 会话衰减
        self._session_start_time: Optional[float] = None

    def set_blink_detector(self, blink_detector) -> None:
        self._blink_detector = blink_detector

    def set_baseline(
        self,
        ear: float,
        yaw_std: Optional[float] = None,
        pitch_std: Optional[float] = None,
    ) -> None:
        self.baseline_ear = ear
        if yaw_std is not None:
            self.baseline_yaw_std = yaw_std
        if pitch_std is not None:
            self.baseline_pitch_std = pitch_std
        self._window_samples.clear()
        self._last_sample_second = -1
        # v4.13: 重置 EMA、眨眼基线、冻结分数
        self._ema_score = None
        self._blink_baseline = None
        self._blink_baseline_samples.clear()
        self._blink_baseline_ready = False
        self._blink_baseline_start_time = None
        self._last_eye_score = 50.0
        self._last_head_score = 50.0
        self._last_gaze_score = 50.0
        self._last_focus_score = 50.0
        self._last_openness = 1.0
        self._last_stability = 1.0
        self._current_level = FocusLevel.NORMAL
        # v4.14: 已手动校准 → 跳过自动EAR采集
        self._ear_auto_applied = True
        self._ear_auto_samples.clear()
        logger.info("专注度基线已更新: EAR=%.4f", ear)

    def _get_head_comfort(self):
        """v4.39: 基于用户校准基线计算个性化头部舒适区。

        舒适角 = 默认值 × (用户std / 3.0)，clamp 到最小值防止过度敏感。
        无校准数据时回退到类常量。
        """
        if self.baseline_yaw_std and self.baseline_yaw_std > 0:
            comfort_yaw = max(self._MIN_COMFORT_YAW,
                            self._COMFORT_YAW * self.baseline_yaw_std / 3.0)
            yaw_scale = max(10.0, self._YAW_SCALE * self.baseline_yaw_std / 3.0)
        else:
            comfort_yaw = self._COMFORT_YAW
            yaw_scale = self._YAW_SCALE
        if self.baseline_pitch_std and self.baseline_pitch_std > 0:
            comfort_pitch = max(self._MIN_COMFORT_PITCH,
                              self._COMFORT_PITCH * self.baseline_pitch_std / 3.0)
            pitch_scale = max(12.0, self._PITCH_SCALE * self.baseline_pitch_std / 3.0)
        else:
            comfort_pitch = self._COMFORT_PITCH
            pitch_scale = self._PITCH_SCALE
        return comfort_yaw, comfort_pitch, yaw_scale, pitch_scale

    def analyze(
        self,
        ear: float,
        yaw: float = 0.0,
        pitch: float = 0.0,
        gaze_score: float = 100.0,
        brightness: float = 128.0,
        face_detected: bool = True,
    ) -> FocusResult:
        current_time = time.time()

        # ── 人脸丢失：冻结最后分数 ──
        if not face_detected:
            return self._handle_face_lost(current_time)

        self._face_lost_start_time = None

        # ── 采样（每秒一次）──
        current_second = int(current_time)
        if current_second != self._last_sample_second:
            self._last_sample_second = current_second
            self._window_samples.append(ear)

        # ── 睁眼度 ──
        if self.baseline_ear > 0:
            openness = min(1.0, max(0.0, ear / self.baseline_ear))
        else:
            openness = 0.5

        # ── 稳定性 + FocusLevel ──
        stability, level = self._compute_window_level(
            yaw=yaw, pitch=pitch, gaze_score=gaze_score)
        self._current_level = level

        # ── v4.14: EAR 自动基线采集 ──
        self._collect_ear_auto_baseline(ear)

        # ── 相对眨眼评分 (v4.13) ──
        blink_rate = self._get_blink_rate()
        self._update_blink_baseline(blink_rate)
        blink_score = self._compute_relative_blink_score(blink_rate)

        # v4.14: 眼部得分 = 睁眼度×25% + 稳定性×25% + 相对眨眼×50%
        eye_score = round(
            openness * 0.25 * 100
            + stability * 0.25 * 100
            + blink_score * 0.50,
            1,
        )

        # ── 头部分数 (v4.39: 个性化舒适角) ──
        comfort_yaw, comfort_pitch, yaw_scale, pitch_scale = self._get_head_comfort()
        yaw_excess = max(0.0, abs(yaw) - comfort_yaw)
        pitch_excess = max(0.0, abs(pitch) - comfort_pitch)
        head_penalty = min(
            1.0,
            max(yaw_excess / yaw_scale, pitch_excess / pitch_scale),
        )
        head_score = round(100.0 * (1.0 - head_penalty), 1)

        # ── v4.35: 动态权重混合（基于光照/姿态置信度） ──
        eye_w, head_w, gaze_w = self._compute_dynamic_weights(brightness, yaw, pitch)
        raw_focus = round(
            eye_score * eye_w
            + head_score * head_w
            + gaze_score * gaze_w,
            1,
        )

        # ── EMA 平滑（阶梯式响应）──
        if self._ema_score is None:
            self._ema_score = raw_focus
        else:
            if raw_focus < self._ema_score:
                alpha = self._EMA_FAST   # 分心 → 快速下降
            else:
                alpha = self._EMA_SLOW   # 恢复 → 慢速回升
            self._ema_score = alpha * raw_focus + (1 - alpha) * self._ema_score

        smooth_focus = round(self._ema_score, 1)

        # ── v4.14: 会话衰减 ──
        decay = self._compute_session_decay()
        smooth_focus = round(smooth_focus * decay, 1)

        # ── 保存最后分数（供人脸丢失冻结用）──
        self._last_eye_score = eye_score
        self._last_head_score = head_score
        self._last_gaze_score = gaze_score
        self._last_focus_score = smooth_focus
        self._last_openness = openness
        self._last_stability = stability

        return FocusResult(
            focus_level=level,
            eye_openness=round(openness, 2),
            eye_stability=round(stability, 2),
            blink_rate=blink_rate,
            is_attentive=(level == FocusLevel.FOCUSED),
            focus_score=smooth_focus,
            eye_score=eye_score,
            head_score=head_score,
            gaze_score=gaze_score,
            face_lost=False,
        )

    # ═══════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════

    def set_adjustment_factor(self, factor: float) -> None:
        """v4.35: 设置校准调整因子，影响偏差检测灵敏度"""
        self._adjustment_factor = max(0.7, min(1.3, float(factor)))

    # ── v4.35: 动态权重 ──

    def _compute_dynamic_weights(self, brightness: float,
                                 yaw: float, pitch: float) -> tuple[float, float, float]:
        """根据环境/姿态置信度动态调整 eye/head/gaze 混合权重

        正常:        eye=0.70  head=0.20  gaze=0.10
        低光照:      eye-0.20  head+0.15  gaze+0.05
        极端角度:    eye+0.10  head-0.15  gaze+0.05
        低光+极端:   eye-0.10  head+0.00  gaze+0.10

        Returns:
            (eye_w, head_w, gaze_w) 总和为 1.0
        """
        ew, hw, gw = self._EYE_BLEND, self._HEAD_BLEND, self._GAZE_BLEND

        low_light = brightness < self._BRIGHT_LOW
        extreme_angle = abs(yaw) > self._YAW_EXTREME or abs(pitch) > self._PITCH_EXTREME

        if low_light and extreme_angle:
            ew, hw, gw = 0.60, 0.20, 0.20
        elif low_light:
            ew, hw, gw = 0.50, 0.35, 0.15
        elif extreme_angle:
            ew, hw, gw = 0.80, 0.05, 0.15
        # else keep defaults

        # 硬边界
        ew = max(0.30, min(0.85, ew))
        hw = max(0.05, min(0.50, hw))
        gw = max(0.05, min(0.30, gw))
        total = ew + hw + gw
        return (ew / total, hw / total, gw / total)

    def _compute_window_level(self, yaw: float = 0.0, pitch: float = 0.0,
                              gaze_score: float = 100.0) -> tuple[float, FocusLevel]:
        """v4.13: 15s 窗口统计（FOCUSED≤3, DISTRACTED≥8）

        v4.34: 多信号门控 — EAR 偏离≥8s 时，若视线+头部均正常则降为 NORMAL。
        仅眨眼频繁但注视屏幕 + 头姿稳定 ≠ 分心。
        v4.35: 偏差阈值受 adjustment_factor 调控 — factor<1.0 时更宽容（检测器过敏感）。
        """
        if len(self._window_samples) < 3:
            return 1.0, FocusLevel.NORMAL

        if self.baseline_ear <= 0:
            return 0.5, FocusLevel.NORMAL

        # v4.35: 偏差阈值 = 0.15 / adjustment_factor, clamp [0.10, 0.25]
        dev_threshold = max(0.10, min(0.25, 0.15 / max(0.7, self._adjustment_factor)))

        deviated = 0
        for ear_val in self._window_samples:
            # 只惩罚闭眼（EAR 低于基线一定比例）
            deviation = max(0, self.baseline_ear - ear_val) / self.baseline_ear
            if deviation > dev_threshold:
                deviated += 1

        total = len(self._window_samples)
        stability = 1.0 - (deviated / total)

        if deviated <= FOCUSED_MAX_DEVIATION_SECS:
            level = FocusLevel.FOCUSED
        elif deviated >= DISTRACTED_MIN_DEVIATION_SECS:
            # v4.34: 多信号门控 — 视线注视 + 头部稳定时，高频眨眼不视为分心
            comfort_yaw, comfort_pitch, yaw_scale, pitch_scale = self._get_head_comfort()
            yaw_excess = max(0.0, abs(yaw) - comfort_yaw)
            pitch_excess = max(0.0, abs(pitch) - comfort_pitch)
            head_penalty = min(1.0, max(
                yaw_excess / yaw_scale, pitch_excess / pitch_scale))
            head_ok = (100.0 * (1.0 - head_penalty)) >= 50
            gaze_ok = gaze_score >= 50
            if gaze_ok and head_ok:
                level = FocusLevel.NORMAL
            else:
                level = FocusLevel.DISTRACTED
        else:
            level = FocusLevel.NORMAL

        return stability, level

    def _handle_face_lost(self, current_time: float) -> FocusResult:
        """v4.13: 人脸丢失时冻结最后分数，不做衰减"""
        # 跟踪丢失起始时间（用于日志）
        if self._face_lost_start_time is None:
            self._face_lost_start_time = current_time
        # 返回冻结的最后分数，不归零
        return FocusResult(
            focus_level=self._current_level,
            eye_openness=self._last_openness,
            eye_stability=self._last_stability,
            blink_rate=self._get_blink_rate(),
            is_attentive=(self._current_level == FocusLevel.FOCUSED),
            focus_score=self._last_focus_score,
            eye_score=self._last_eye_score,
            head_score=self._last_head_score,
            gaze_score=self._last_gaze_score,
            face_lost=True,
        )

    def _get_blink_rate(self) -> float:
        if self._blink_detector:
            rate, _ = self._blink_detector.get_blink_rate(window_seconds=60.0)
            return round(rate, 1)
        return 0.0

    # ── v4.14: EAR 自动基线 ──

    def _collect_ear_auto_baseline(self, ear: float) -> None:
        """前2分钟自动采集EAR样本，建立个人基线（无需用户配合校准）。"""
        if self._ear_auto_applied:
            return
        now = time.time()
        if self._ear_auto_start_time is None:
            self._ear_auto_start_time = now

        elapsed = now - self._ear_auto_start_time
        if elapsed < self._EAR_AUTO_COLLECT_SECS:
            if ear > self._EAR_AUTO_MIN_VALUE:
                self._ear_auto_samples.append(ear)
        elif not self._ear_auto_applied and len(self._ear_auto_samples) >= self._EAR_AUTO_MIN_SAMPLES:
            auto_ear = float(np.median(self._ear_auto_samples))
            diff = abs(auto_ear - 0.25) / 0.25  # 与默认值0.25的差异
            if diff > self._EAR_AUTO_DIFF_THRESHOLD and auto_ear > self._EAR_AUTO_MIN_VALUE:
                self.baseline_ear = auto_ear
                logger.info(
                    "EAR 自动基线已建立: %.4f (默认0.25, 差异%.0f%%, n=%d)",
                    auto_ear, diff * 100, len(self._ear_auto_samples),
                )
            self._ear_auto_applied = True
            self._ear_auto_samples.clear()  # 释放内存

    def set_session_start(self, t: float) -> None:
        """v4.14: 设置会话开始时间（用于衰减计算）。"""
        self._session_start_time = t

    def _compute_session_decay(self) -> float:
        """v4.14: 计算会话衰减因子。

        前30分钟无衰减，之后线性衰减至地板值85%。
        模拟长时间工作导致的自然注意力下降。
        """
        if self._session_start_time is None:
            return 1.0
        elapsed_min = (time.time() - self._session_start_time) / 60.0
        if elapsed_min <= self._DECAY_FREE_MINUTES:
            return 1.0
        excess = elapsed_min - self._DECAY_FREE_MINUTES
        decay = 1.0 - excess * self._DECAY_RATE_PER_MINUTE
        return max(self._DECAY_FLOOR, decay)

    # ── v4.13: 相对眨眼基线 ──

    def _update_blink_baseline(self, rate: float) -> None:
        """前2分钟收集样本建立个人基线，之后每30秒缓慢自适应"""
        now = time.time()
        if self._blink_baseline_start_time is None:
            self._blink_baseline_start_time = now

        elapsed = now - self._blink_baseline_start_time

        if elapsed < self._BLINK_BASELINE_COLLECT_SECS:
            # 初期：收集非零样本
            if rate > 0:
                self._blink_baseline_samples.append(rate)
        elif not self._blink_baseline_ready:
            # 首次建立基线
            if self._blink_baseline_samples:
                self._blink_baseline = float(np.median(self._blink_baseline_samples))
            else:
                # 前2分钟无眨眼样本 → 使用人群默认值
                self._blink_baseline = 12.0
            # 确保基线不低于合理值
            if self._blink_baseline < 3.0:
                self._blink_baseline = 12.0
            self._blink_baseline_ready = True
            self._blink_baseline_update_time = now
            logger.info(
                "眨眼基线已建立: %.1f 次/分 (n=%d)",
                self._blink_baseline,
                len(self._blink_baseline_samples),
            )

        # 缓慢自适应（每30秒）
        if self._blink_baseline_ready and self._blink_baseline is not None:
            if now - self._blink_baseline_update_time >= self._BLINK_BASELINE_ADAPT_INTERVAL:
                self._blink_baseline = (
                    self._blink_baseline * (1 - self._BLINK_BASELINE_ADAPT_RATE)
                    + rate * self._BLINK_BASELINE_ADAPT_RATE
                )
                self._blink_baseline_update_time = now

    def _compute_relative_blink_score(self, blink_rate: float) -> float:
        """相对于个人基线的眨眼评分

        映射:
          ratio ≤ 1.0 (正常/偏低) → 100 分
          1.0 < ratio ≤ 2.0         → 100 → 20 (线性递减)
          ratio > 2.0                → 20 → 5  (缓慢递减，底线5分)
        """
        if not self._blink_baseline_ready or self._blink_baseline is None:
            return 100.0  # 基线未就绪，不扣分

        if self._blink_baseline <= 0 or blink_rate <= 0:
            return 100.0

        ratio = blink_rate / self._blink_baseline

        if ratio <= 1.0:
            return 100.0
        elif ratio <= 2.0:
            return 100.0 - (ratio - 1.0) * 80.0
        else:
            return max(5.0, 20.0 - (ratio - 2.0) * 10.0)

    # ── 窗口摘要（向后兼容）──

    def get_window_summary(self) -> Optional[FocusRecord]:
        if not self._window_samples:
            return None
        samples = list(self._window_samples)
        avg_ear = float(np.mean(samples))
        openness = (
            min(1.0, max(0.0, avg_ear / self.baseline_ear))
            if self.baseline_ear > 0
            else 0.5
        )
        stability = 0.6
        blink_rate = self._get_blink_rate()
        blink_score = self._compute_relative_blink_score(blink_rate)
        eye_score = round(
            openness * 0.25 * 100 + stability * 0.25 * 100 + blink_score * 0.50,
            1,
        )
        focus_score = round(
            eye_score * self._EYE_BLEND
            + 50.0 * self._HEAD_BLEND
            + 50.0 * self._GAZE_BLEND,
            1,
        )
        return FocusRecord(
            session_id="",
            window_start=0.0,
            window_end=float(len(samples)),
            focus_score=focus_score,
            eye_score=eye_score,
            head_score=50.0,
            gaze_score=50.0,
            blink_rate=blink_rate,
            avg_ear=avg_ear,
            avg_yaw=0.0,
            avg_pitch=0.0,
        )

    def reset(self) -> None:
        self._window_samples.clear()
        self._last_sample_second = -1
        self._face_lost_start_time = None
        self._current_level = FocusLevel.NORMAL
        # v4.13: 重置 EMA、眨眼基线、冻结分数
        self._ema_score = None
        self._blink_baseline = None
        self._blink_baseline_samples.clear()
        self._blink_baseline_ready = False
        self._blink_baseline_start_time = None
        self._last_eye_score = 50.0
        self._last_head_score = 50.0
        self._last_gaze_score = 50.0
        self._last_focus_score = 50.0
        self._last_openness = 1.0
        self._last_stability = 1.0
        # v4.14: 重置 EAR 自动基线 + 会话衰减
        self._ear_auto_samples.clear()
        self._ear_auto_start_time = None
        self._ear_auto_applied = False
        self._session_start_time = None

    def get_stats(self) -> dict:
        return {
            "baseline_ear": self.baseline_ear,
            "window_size": self.window_size,
            "window_samples": len(self._window_samples),
            "current_level": self._current_level.value if self._current_level else "none",
            "blink_baseline": self._blink_baseline,
            "blink_baseline_ready": self._blink_baseline_ready,
            "ema_score": self._ema_score,
        }


# ── v4.17: 分心原因分解 ──

def compute_distraction_causes(focus_result: FocusResult) -> dict:
    """分解专注度下降源。

    从 FocusResult 的 eye_score/head_score/gaze_score 推算
    各因素在总分下降中的贡献占比。

    v4.34: FocusLevel 由 _compute_window_level() 多信号门控决定 —
    EAR 偏离是主要触发源，但仅当视线或头姿也指示不专注时才判 DISTRACTED。
    本函数按比例报告三个子分数，无论哪个信号触发了等级变化。

    Returns:
        {"眨眼异常": float%, "头部偏移": float%, "视线偏离": float%}
        总分高时返回 None（不分心则无原因）
    """
    if focus_result is None:
        return {}
    # v4.18: None 安全
    fs = focus_result.focus_score or 0.0
    if fs >= 60:
        return {}

    eye_s = focus_result.eye_score if focus_result.eye_score is not None else 50.0
    head_s = focus_result.head_score if focus_result.head_score is not None else 50.0
    gaze_s = focus_result.gaze_score if focus_result.gaze_score is not None else 50.0

    # 期望值：正常专注时眼≈90, 头≈100, 视线≈100
    eye_drop = max(0.0, 90.0 - eye_s)
    head_drop = max(0.0, 100.0 - head_s)
    gaze_drop = max(0.0, 100.0 - gaze_s)

    total = eye_drop + head_drop + gaze_drop
    if total < 1.0:
        return {}

    return {
        "眨眼异常": round(eye_drop / total * 100, 0),
        "头部偏移": round(head_drop / total * 100, 0),
        "视线偏离": round(gaze_drop / total * 100, 0),
    }


def create_focus_analyzer(baseline_ear: float = 0.25) -> FocusAnalyzer:
    """工厂函数：创建专注度分析器（支持 YAML 配置覆盖）"""
    from config import get_yaml_value
    return FocusAnalyzer(
        baseline_ear=baseline_ear,
        window_size=get_yaml_value("focus", "window_size", default=15.0),
    )

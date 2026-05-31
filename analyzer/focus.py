"""
analyzer/focus.py — 专注度评分算法

提供 FocusAnalyzer 类，综合眼部、头部姿态、视线等因素
计算专注度评分（0-100 分）。

评分权重：
- 眼部专注 (eye_score): 35% — EAR 是否在正常范围
- 头部姿态 (head_score): 30% — 是否正视屏幕
- 视线方向 (gaze_score): 35% — 视线是否聚焦
"""

import logging
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

import numpy as np

from storage.models import FocusRecord

logger = logging.getLogger("eyefocus.analyzer")


# 默认配置
DEFAULT_FPS = 30.0
DEFAULT_WINDOW_SIZE = 5.0  # 秒
DEFAULT_EYE_WEIGHT = 0.35
DEFAULT_HEAD_WEIGHT = 0.30
DEFAULT_GAZE_WEIGHT = 0.35


@dataclass
class FocusResult:
    """专注度分析结果"""
    focus_score: float  # 综合专注度 0-100
    eye_score: float  # 眼部专注度 0-100
    head_score: float  # 头部姿态分数 0-100
    gaze_score: float  # 视线分数 0-100
    blink_rate: float  # 眨眼频率 (次/分钟)
    is_attentive: bool  # 是否专注（focus_score >= 60）


class KalmanFilter1D:
    """一维卡尔曼滤波器

    用于平滑专注度评分输出，减少抖动。
    """

    def __init__(self, process_variance: float = 0.001, measurement_variance: float = 0.1):
        self.process_variance = process_variance
        self.measurement_variance = measurement_variance
        self.estimate = 0.0
        self.estimation_error = 1.0

    def update(self, measurement: float) -> float:
        """更新滤波器状态

        Args:
            measurement: 当前测量值

        Returns:
            平滑后的估计值
        """
        # 预测
        self.estimation_error += self.process_variance

        # 更新
        kalman_gain = self.estimation_error / (self.estimation_error + self.measurement_variance)
        self.estimate += kalman_gain * (measurement - self.estimate)
        self.estimation_error *= (1 - kalman_gain)

        return self.estimate

    def reset(self) -> None:
        """重置滤波器"""
        self.estimate = 0.0
        self.estimation_error = 1.0


class FocusAnalyzer:
    """专注度分析器

    使用方法：
        analyzer = FocusAnalyzer(baseline_ear=0.25)
        result = analyzer.analyze(ear=0.24, yaw=2.0, pitch=-5.0, gaze_score=85.0)
    """

    def __init__(
        self,
        baseline_ear: float = 0.25,
        baseline_yaw_std: float = 3.0,
        baseline_pitch_std: float = 3.0,
        eye_weight: float = DEFAULT_EYE_WEIGHT,
        head_weight: float = DEFAULT_HEAD_WEIGHT,
        gaze_weight: float = DEFAULT_GAZE_WEIGHT,
        window_size: float = DEFAULT_WINDOW_SIZE,
        fps: float = DEFAULT_FPS,
        enable_kalman: bool = True,
    ):
        """初始化专注度分析器

        Args:
            baseline_ear: 基线 EAR 均值
            baseline_yaw_std: 基线偏航角标准差
            baseline_pitch_std: 基线俯仰角标准差
            eye_weight: 眼部权重
            head_weight: 头部姿态权重
            gaze_weight: 视线权重
            window_size: 滑动窗口大小（秒）
            fps: 帧率
            enable_kalman: 是否启用卡尔曼滤波
        """
        self.baseline_ear = baseline_ear
        self.baseline_yaw_std = baseline_yaw_std
        self.baseline_pitch_std = baseline_pitch_std
        self.eye_weight = eye_weight
        self.head_weight = head_weight
        self.gaze_weight = gaze_weight
        self.window_size = window_size
        self.fps = fps
        self.enable_kalman = enable_kalman

        # 确保权重和为 1
        total = eye_weight + head_weight + gaze_weight
        if abs(total - 1.0) > 1e-6:
            self.eye_weight /= total
            self.head_weight /= total
            self.gaze_weight /= total

        # 滑动窗口
        self._window_frames = int(window_size * fps)
        self._recent_data: Deque[dict] = deque(maxlen=self._window_frames)

        # 眨眼检测器引用
        self._blink_detector = None

        # 卡尔曼滤波器
        self._kalman = KalmanFilter1D() if enable_kalman else None
        self._last_focus_score = 0.0

        # EAR 阈值（基于基线）
        self._ear_low_thresh = baseline_ear * 0.7
        self._ear_high_thresh = baseline_ear * 1.3

    def set_blink_detector(self, blink_detector) -> None:
        """设置眨眼检测器引用

        Args:
            blink_detector: EyeAspectDetector 实例
        """
        self._blink_detector = blink_detector

    def set_baseline(
        self,
        ear: float,
        yaw_std: Optional[float] = None,
        pitch_std: Optional[float] = None,
    ) -> None:
        """更新基线值

        Args:
            ear: 基线 EAR 均值
            yaw_std: 基线偏航角标准差
            pitch_std: 基线俯仰角标准差
        """
        self.baseline_ear = ear
        if yaw_std is not None:
            self.baseline_yaw_std = yaw_std
        if pitch_std is not None:
            self.baseline_pitch_std = pitch_std

        # 重新计算阈值
        self._ear_low_thresh = ear * 0.7
        self._ear_high_thresh = ear * 1.3

        # 重置卡尔曼滤波器
        if self._kalman:
            self._kalman.reset()

        logger.info("专注度基线已更新: EAR=%.4f, YAW_std=%.2f, PITCH_std=%.2f",
                    ear, yaw_std, pitch_std)

    def analyze(
        self,
        ear: float,
        yaw: float,
        pitch: float,
        gaze_score: float = 100.0,
        brightness: float = 128.0,
        face_detected: bool = True,
    ) -> FocusResult:
        """分析单帧专注度

        Args:
            ear: 当前 EAR 值
            yaw: 偏航角（度）
            pitch: 俯仰角（度）
            gaze_score: 视线聚焦分数 (0-100)
            brightness: 帧亮度 (0-255)
            face_detected: 人脸是否检测到

        Returns:
            FocusResult 对象
        """
        if not face_detected:
            # 人脸丢失，大幅降低专注度
            raw_score = 0.0
            eye_score = 0.0
            head_score = 0.0
            gaze_score = 0.0
        else:
            # 计算各项分数
            eye_score = self._compute_eye_score(ear)
            head_score = self._compute_head_score(yaw, pitch)
            gaze_score = max(0.0, min(100.0, gaze_score))

            # 综合评分
            raw_score = (
                eye_score * self.eye_weight
                + head_score * self.head_weight
                + gaze_score * self.gaze_weight
            )

        # 卡尔曼滤波平滑
        if self._kalman and face_detected:
            focus_score = self._kalman.update(raw_score)
        else:
            focus_score = raw_score

        focus_score = max(0.0, min(100.0, focus_score))
        self._last_focus_score = focus_score

        # 记录到窗口
        self._recent_data.append({
            "ear": ear,
            "yaw": yaw,
            "pitch": pitch,
            "gaze_score": gaze_score,
            "focus_score": focus_score,
        })

        # 获取眨眼频率
        blink_rate = 0.0
        if self._blink_detector:
            blink_rate, _ = self._blink_detector.get_blink_rate(window_seconds=60.0)

        return FocusResult(
            focus_score=round(focus_score, 1),
            eye_score=round(eye_score, 1),
            head_score=round(head_score, 1),
            gaze_score=round(gaze_score, 1),
            blink_rate=round(blink_rate, 1),
            is_attentive=focus_score >= 60.0,
        )

    def _compute_eye_score(self, ear: float) -> float:
        """计算眼部专注分数

        EAR 在基线附近得高分，过低（眨眼/疲劳）或过高（异常）得低分。
        """
        if ear < 0.05:
            # 闭眼状态
            return 0.0

        # 计算与基线的偏差
        deviation = abs(ear - self.baseline_ear) / self.baseline_ear

        if deviation <= 0.1:
            # 偏差 10% 以内，得满分
            return 100.0
        elif deviation <= 0.3:
            # 偏差 10%-30%，线性衰减
            return 100.0 - (deviation - 0.1) / 0.2 * 50.0
        elif deviation <= 0.5:
            # 偏差 30%-50%，继续衰减
            return 50.0 - (deviation - 0.3) / 0.2 * 40.0
        else:
            # 偏差超过 50%，得低分
            return max(0.0, 10.0 - (deviation - 0.5) * 10.0)

    def _compute_head_score(self, yaw: float, pitch: float) -> float:
        """计算头部姿态分数

        头部姿态越稳定，分数越高。
        """
        # 使用基线标准差作为参考计算偏离度
        yaw_deviation = abs(yaw) / max(self.baseline_yaw_std * 3, 1.0)
        pitch_deviation = abs(pitch) / max(self.baseline_pitch_std * 3, 1.0)

        yaw_score = max(0.0, 100.0 - yaw_deviation * 50.0)
        pitch_score = max(0.0, 100.0 - pitch_deviation * 50.0)

        # 使用较小的分数（最差维度决定分数）
        return min(yaw_score, pitch_score)

    def get_window_summary(self) -> Optional[FocusRecord]:
        """获取滑动窗口内的专注度汇总

        Returns:
            FocusRecord 对象，或 None（如果窗口为空）
        """
        if not self._recent_data:
            return None

        focus_scores = [d["focus_score"] for d in self._recent_data]
        eye_scores = [self._compute_eye_score(d["ear"]) for d in self._recent_data]
        head_scores = [self._compute_head_score(d["yaw"], d["pitch"]) for d in self._recent_data]
        gaze_scores = [d["gaze_score"] for d in self._recent_data]

        # 计算窗口时间范围
        window_duration = len(self._recent_data) / self.fps
        window_start = 0.0  # 相对时间
        window_end = window_duration

        # 获取眨眼频率
        blink_rate = 0.0
        if self._blink_detector:
            blink_rate, _ = self._blink_detector.get_blink_rate(window_seconds=window_duration)

        return FocusRecord(
            session_id="",  # 调用者填充
            window_start=window_start,
            window_end=window_end,
            focus_score=float(np.mean(focus_scores)),
            eye_score=float(np.mean(eye_scores)),
            head_score=float(np.mean(head_scores)),
            gaze_score=float(np.mean(gaze_scores)),
            blink_rate=blink_rate,
            avg_ear=float(np.mean([d["ear"] for d in self._recent_data])),
            avg_yaw=float(np.mean([d["yaw"] for d in self._recent_data])),
            avg_pitch=float(np.mean([d["pitch"] for d in self._recent_data])),
        )

    def reset(self) -> None:
        """重置分析器状态"""
        self._recent_data.clear()
        if self._kalman:
            self._kalman.reset()
        self._last_focus_score = 0.0

    def get_stats(self) -> dict:
        """获取分析统计信息"""
        return {
            "baseline_ear": self.baseline_ear,
            "baseline_yaw_std": self.baseline_yaw_std,
            "baseline_pitch_std": self.baseline_pitch_std,
            "window_size": self.window_size,
            "window_frames": self._window_frames,
            "current_focus_score": self._last_focus_score,
            "kalman_enabled": self.enable_kalman,
        }


def create_focus_analyzer(baseline_ear: float = 0.25) -> FocusAnalyzer:
    """工厂函数：创建专注度分析器"""
    return FocusAnalyzer(baseline_ear=baseline_ear)

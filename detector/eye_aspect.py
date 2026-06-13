"""
detector/eye_aspect.py — EAR 眨眼检测算法

提供 EyeAspectDetector 类，实现：
- EAR (Eye Aspect Ratio) 计算
- 眨眼事件检测（基于个人基线的动态阈值）
- 眯眼 vs 眨眼区分（时间窗口 400ms）
- 多信号融合眨眼置信度（头部姿态 + 面部稳定性）

参考: Soukupová & Čech (2016) Real-Time Eye Blink Detection
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("eyefocus.detector")


# 默认 EAR 阈值配置
DEFAULT_EAR_THRESHOLD = 0.26  # 眨眼阈值（固定fallback）
DEFAULT_EAR_MIN = 0.08  # EAR 最小值（眼睛闭合）
DEFAULT_SQUINT_VS_BLINK_THRESHOLD = 0.4  # 秒，<此时间为眨眼，>=此时间为眯眼
DEFAULT_BLINK_CONFIRM_FRAMES = 2  # 连续低于阈值才确认为眨眼

# 眯眼 vs 眨眼区分参数
SQUINT_THRESHOLD_SECONDS = 0.4  # 400ms

# 多信号融合置信度参数
DEFAULT_CONFIDENCE_THRESHOLD_HIGH = 0.6  # 置信度 > 0.6 才计入眨眼
DEFAULT_CONFIDENCE_THRESHOLD_LOW = 0.3  # 置信度 < 0.3 忽略


@dataclass
class BlinkEvent:
    """眨眼事件"""
    start_frame: int
    end_frame: int
    start_time: float
    end_time: float
    duration: float  # 秒
    ear_nadir: float  # 眨眼时的最小 EAR
    is_confirmed: bool = True  # 是否通过置信度验证


@dataclass
class EyeAspectResult:
    """眼部检测结果"""
    ear_left: float
    ear_right: float
    ear_avg: float
    is_blink: bool  # 当前帧是否处于眨眼状态
    left_open: bool
    right_open: bool


class EyeAspectDetector:
    """EAR 眨眼检测器

    使用眼睛纵横比 (Eye Aspect Ratio) 检测眨眼。
    EAR = (|p2-p6| + |p3-p5|) / (2 * |p1-p4|)

    特性：
    - 基于个人基线的动态阈值（set_baseline）
    - 眯眼 vs 眨眼区分（时间窗口）
    - 多信号融合眨眼置信度（头部姿态 + 面部稳定性）

    使用方法：
        detector = EyeAspectDetector()
        detector.set_baseline(0.35)  # 设置个人基线 EAR
        result = detector.compute(landmarks)  # landmarks: (478, 2) 关键点
    """

    # MediaPipe 人脸关键点索引（左手系）
    LEFT_EYE_INDICES = (33, 160, 158, 133, 153, 144)
    RIGHT_EYE_INDICES = (362, 385, 387, 263, 380, 373)

    def __init__(
        self,
        ear_threshold: float = DEFAULT_EAR_THRESHOLD,
        ear_min: float = DEFAULT_EAR_MIN,
        squint_threshold: float = SQUINT_THRESHOLD_SECONDS,
        confirm_frames: int = DEFAULT_BLINK_CONFIRM_FRAMES,
        baseline_ear: Optional[float] = None,
        fps: float = 30.0,
    ):
        """初始化 EAR 检测器

        Args:
            ear_threshold: EAR 眨眼阈值（固定 fallback）
            ear_min: EAR 最小值，用于判断眼睛是否完全闭合
            squint_threshold: 眯眼阈值（秒），>= 此时间为眯眼
            confirm_frames: 确认眨眼的连续帧数
            baseline_ear: 个人基线 EAR（用于动态阈值）
            fps: 帧率（用于计算时长）
        """
        self.ear_threshold = ear_threshold
        self.ear_min = ear_min
        self.squint_threshold = squint_threshold
        self.confirm_frames = confirm_frames
        self.fps = fps

        # 个人基线（用于动态阈值）
        self._baseline_ear: Optional[float] = baseline_ear
        self._has_baseline: bool = baseline_ear is not None
        # P0: 校准 adjustment 因子（基于眨眼计数校准的检测误差补偿, 默认 1.0 无调整）
        self._adjustment_factor: float = 1.0
        if self._has_baseline:
            self.ear_threshold = baseline_ear * 0.75 * self._adjustment_factor

        # 眨眼检测状态
        self._blink_frames: Deque[bool] = deque(maxlen=30)
        self._recent_ears: Deque[float] = deque(maxlen=30)

        # 眨眼事件记录
        self._blink_events: Deque[BlinkEvent] = deque(maxlen=5000)
        self._current_blink_start: Optional[int] = None
        self._current_blink_start_time: Optional[float] = None
        self._current_blink_ear_nadir: float = float('inf')
        self._current_ear: float = 0.0  # 当前帧 EAR 值，用于回调

        # 眯眼 vs 眨眼区分：记录闭眼持续时间
        self._eye_closed_start_time: Optional[float] = None

        # 帧计数
        self._frame_count: int = 0

        # 会话开始时间（用于绝对时间戳）
        self._session_start_time: Optional[float] = None  # DEPRECATED: 使用绝对时间戳后不再需要

        # 多信号融合：头部姿态和面部稳定性
        self._head_pose_weight: float = 1.0  # 1.0=正常，0.5=异常
        self._face_stability_weight: float = 1.0  # 1.0=稳定，0.3=晃动

        # BUG FIX: 初始化 _blinks_in_progress
        self._blinks_in_progress: int = 0

    def set_baseline(self, ear: float) -> None:
        """设置个人基线 EAR，动态更新眨眼阈值

        眨眼阈值 = baseline_ear × 0.75 × adjustment_factor
        睁眼判定 = EAR > baseline_ear × 0.90

        Args:
            ear: 个人基线 EAR 均值
        """
        self._baseline_ear = ear
        self._has_baseline = True
        # 动态阈值：眨眼阈值 = 基线 × 0.75 × adjustment_factor (P0)
        self.ear_threshold = ear * 0.75 * self._adjustment_factor
        logger.info("EAR 动态阈值已更新: %.4f (基线=%.4f, factor=%.3f)",
                    self.ear_threshold, ear, self._adjustment_factor)

    def set_adjustment_factor(self, factor: float) -> None:
        """P0: 设置校准 adjustment 因子 (基于眨眼计数校准的检测误差补偿)。

        实际眨眼阈值 = baseline_ear × 0.75 × factor
        factor = 1.0 表示无调整; calibration/blink_count.py:122 clamp 到 [0.7, 1.3]
        若 set_baseline 还没调, 此处仅保存 factor 待下次 set_baseline 时生效。

        Args:
            factor: 调整因子, 通常 0.7-1.3 范围
        """
        # M-11: 缺上界修复, 改为 clamp [0.7, 1.3] (匹配 docstring 声明)
        self._adjustment_factor = max(0.7, min(1.3, float(factor)))
        if self._has_baseline:
            self.ear_threshold = self._baseline_ear * 0.75 * self._adjustment_factor
            logger.info("EAR 阈值 adjustment 已应用: %.4f (factor=%.3f)",
                        self.ear_threshold, self._adjustment_factor)

    def set_head_pose_weight(self, weight: float) -> None:
        """设置头部姿态置信度权重

        Args:
            weight: 1.0=姿态正常, 0.5=姿态异常
        """
        self._head_pose_weight = max(0.0, min(1.0, weight))

    def set_face_stability_weight(self, weight: float) -> None:
        """设置面部稳定性置信度权重

        Args:
            weight: 1.0=面部稳定, 0.3=面部晃动
        """
        self._face_stability_weight = max(0.0, min(1.0, weight))

    def get_current_ear(self) -> float:
        """获取当前 EAR 值（用于校准回调）"""
        return self._current_ear

    @property
    def blink_threshold(self) -> float:
        """获取当前眨眼阈值"""
        return self.ear_threshold

    @property
    def open_threshold(self) -> float:
        """获取睁眼判定阈值（基线 × 0.90）"""
        if self._baseline_ear is not None:
            return self._baseline_ear * 0.90
        return self.ear_threshold * 1.15  # fallback: 固定阈值的 ~1.15 倍

    def compute(self, landmarks: np.ndarray) -> EyeAspectResult:
        """计算单帧 EAR 值

        Args:
            landmarks: MediaPipe 人脸关键点 (478, 2) 像素坐标

        Returns:
            EyeAspectResult 对象
        """
        self._frame_count += 1

        # 提取左右眼关键点
        left_eye = np.array([landmarks[i] for i in self.LEFT_EYE_INDICES])
        right_eye = np.array([landmarks[i] for i in self.RIGHT_EYE_INDICES])

        # 计算 EAR
        ear_left = self._calculate_ear(left_eye)
        ear_right = self._calculate_ear(right_eye)
        ear_avg = (ear_left + ear_right) / 2.0

        # 更新历史
        self._recent_ears.append(ear_avg)
        self._current_ear = ear_avg  # 保存当前 EAR 值供回调使用

        # 检测眨眼（使用动态阈值）
        is_blink = ear_avg < self.ear_threshold
        left_open = ear_left >= self.ear_min
        right_open = ear_right >= self.ear_min

        # 更新眨眼检测状态机
        self._update_blink_state(is_blink, ear_avg)

        return EyeAspectResult(
            ear_left=ear_left,
            ear_right=ear_right,
            ear_avg=ear_avg,
            is_blink=is_blink,
            left_open=left_open,
            right_open=right_open,
        )

    def _calculate_ear(self, eye_points: np.ndarray) -> float:
        """计算单眼的 EAR 值

        Args:
            eye_points: 6 个关键点 (6, 2) 坐标

        Returns:
            EAR 值
        """
        p1, p2, p3, p4, p5, p6 = eye_points

        # 计算垂直距离
        a = np.linalg.norm(p2 - p6)
        b = np.linalg.norm(p3 - p5)

        # 计算水平距离
        c = np.linalg.norm(p1 - p4)

        if c < 1e-6:
            return 0.0

        return float((a + b) / (2.0 * c))

    def _compute_blink_confidence(self) -> float:
        """计算眨眼置信度（多信号融合）

        confidence = base_conf × head_pose_weight × face_stability_weight

        Returns:
            置信度 0.0 - 1.0
        """
        base_conf = 1.0
        confidence = base_conf * self._head_pose_weight * self._face_stability_weight
        return max(0.0, min(1.0, confidence))

    def _classify_eye_event(self, duration_seconds: float) -> bool:
        """分类眼睑事件：眨眼 vs 眯眼

        Args:
            duration_seconds: 眼睑闭合持续时间（秒）

        Returns:
            True=眨眼, False=眯眼
        """
        # < 400ms = 眨眼，>= 400ms = 眯眼
        return duration_seconds < SQUINT_THRESHOLD_SECONDS

    def _update_blink_state(self, is_blink: bool, ear_avg: float) -> None:
        """更新眨眼检测状态机

        状态转移：
        开眼 -> 闭眼（眨眼/眯眼开始）-> 开眼（眨眼/眯眼结束）

        眯眼 vs 眨眼区分：
        - 闭眼 < 400ms → 判定为眨眼
        - 闭眼 >= 400ms → 判定为眯眼（不计入眨眼事件）

        多信号融合：
        - confidence > 0.6 → 计入眨眼事件
        - confidence < 0.3 → 忽略
        """
        self._blink_frames.append(is_blink)

        # 闭眼开始
        if is_blink and self._current_blink_start is None:
            self._current_blink_start = self._frame_count
            self._current_blink_start_time = time.time()  # 绝对时间戳
            self._current_blink_ear_nadir = float('inf')
            self._eye_closed_start_time = self._current_blink_start_time

        # 更新 EAR 最低值
        if self._current_blink_start is not None and ear_avg < self._current_blink_ear_nadir:
            self._current_blink_ear_nadir = ear_avg

        # 睁眼结束
        elif not is_blink and self._current_blink_start is not None:
            # 确认眨眼（至少连续 N 帧低于阈值）
            recent_blinks = list(self._blink_frames)[-self.confirm_frames:]
            if sum(recent_blinks) >= 1:  # 至少 1 帧确认
                blink_end = self._frame_count
                blink_start = self._current_blink_start
                duration = (blink_end - blink_start) / self.fps

                # 计算闭眼持续时间
                eye_closed_duration = duration

                # 眯眼 vs 眨眼分类
                is_blink_classified = self._classify_eye_event(eye_closed_duration)

                # 多信号融合置信度
                confidence = self._compute_blink_confidence()

                # 获取 EAR 最低值
                window_start = max(0, len(self._recent_ears) - self.confirm_frames - 1)
                window_ears = list(self._recent_ears)[window_start:]
                ear_nadir = min(window_ears) if window_ears else ear_avg

                # 判定规则
                should_record = False

                if is_blink_classified:
                    # 眨眼事件：置信度 > 0.4 才计入（降低阈值以提高召回率）
                    if confidence > 0.4:  # 降低阈值从 0.6 到 0.4
                        should_record = True
                        logger.debug(
                            "眨眼事件(确认): start=%d, end=%d, duration=%.3fs, nadir=%.4f, conf=%.2f",
                            blink_start, blink_end, duration, ear_nadir, confidence
                        )
                    else:
                        logger.debug(
                            "眨眼事件(低置信度%.2f跳过): start=%d, end=%d, duration=%.3fs",
                            confidence, blink_start, blink_end, duration
                        )
                else:
                    # 眯眼事件：不计入眨眼，单独统计
                    logger.debug(
                        "眯眼事件(跳过): duration=%.3fs >= %.3fs",
                        eye_closed_duration, SQUINT_THRESHOLD_SECONDS
                    )

                if should_record:
                    event = BlinkEvent(
                        start_frame=blink_start,
                        end_frame=blink_end,
                        start_time=self._current_blink_start_time,
                        end_time=self._current_blink_start_time + duration,
                        duration=duration,
                        ear_nadir=ear_nadir,
                        is_confirmed=True,
                    )
                    self._blink_events.append(event)
                elif is_blink_classified and confidence >= DEFAULT_CONFIDENCE_THRESHOLD_LOW:
                    # 可疑眨眼：置信度在 [0.3, 0.6] 之间，标记但不计入主要统计
                    event = BlinkEvent(
                        start_frame=blink_start,
                        end_frame=blink_end,
                        start_time=self._current_blink_start_time,
                        end_time=self._current_blink_start_time + duration,
                        duration=duration,
                        ear_nadir=ear_nadir,
                        is_confirmed=False,
                    )
                    self._blink_events.append(event)

            self._current_blink_start = None
            self._current_blink_start_time = None
            self._current_blink_ear_nadir = float('inf')
            self._eye_closed_start_time = None

    def get_closure_type(self) -> str:
        """返回当前眼睛闭合类型 (v4.6)

        基于闭眼持续时长区分快眨眼与疲劳长闭眼。

        Returns:
            "open"      — 睁眼（无闭合进行中）
            "blink"     — 正在快眨眼 (<0.4s, 正常生理)
            "prolonged" — 正在长闭眼 (≥0.5s, 疲劳信号)
        """
        if self._current_blink_start_time is None:
            return "open"

        import time
        duration = time.time() - self._current_blink_start_time

        # v4.6.1: prolonged 阈值 0.5→0.8s（排除长眨眼）
        if duration >= 0.8:
            return "prolonged"
        elif duration < 0.4:
            return "blink"
        else:
            return "open"  # 0.4~0.8s 灰色地带，不触发疲劳

    def get_blink_rate(
        self,
        window_seconds: float = 60.0,
        current_time: Optional[float] = None,
    ) -> Tuple[float, int]:
        """计算眨眼频率（次/分钟）

        Args:
            window_seconds: 统计窗口大小（秒）
            current_time: 当前时间戳（秒），默认为最后一个眨眼的结束时间

        Returns:
            (blink_rate, blink_count) 元组
        """
        if not self._blink_events:
            return 0.0, 0

        if current_time is None:
            current_time = (
                self._blink_events[-1].end_time if self._blink_events else 0.0
            )

        # 筛选窗口内的眨眼（只计入确认的眨眼）
        window_start = current_time - window_seconds
        recent_blinks = [
            e for e in self._blink_events
            if e.is_confirmed and window_start <= e.end_time <= current_time
        ]

        blink_count = len(recent_blinks)

        # 计算实际窗口时长
        if recent_blinks:
            actual_window = current_time - min(e.start_time for e in recent_blinks)
            actual_window = max(actual_window, 1.0)  # 至少 1 秒
            blink_rate = (blink_count / actual_window) * 60.0
        else:
            blink_rate = 0.0

        return blink_rate, blink_count

    def get_blink_events(
        self,
        since_time: Optional[float] = None,
    ) -> List[BlinkEvent]:
        """获取眨眼事件列表

        Args:
            since_time: 只返回此时间之后的眨眼事件

        Returns:
            BlinkEvent 列表
        """
        if since_time is None:
            return list(self._blink_events)

        return [e for e in self._blink_events if e.end_time >= since_time]

    def calibrate_threshold(
        self,
        calibration_ears: List[float],
        percentile: float = 10.0,
    ) -> float:
        """基于校准数据自动标定 EAR 阈值

        使用校准期间采集的 EAR 值，计算指定百分位作为眨眼阈值。

        Args:
            calibration_ears: 校准期间的 EAR 均值列表
            percentile: 百分位（默认 10%）

        Returns:
            新的 EAR 阈值
        """
        if not calibration_ears:
            logger.warning("校准数据为空，使用默认阈值")
            return self.ear_threshold

        ear_array = np.array(calibration_ears)
        new_threshold = float(np.percentile(ear_array, percentile))

        # 确保阈值在合理范围内
        new_threshold = np.clip(new_threshold, 0.15, 0.30)

        self.ear_threshold = new_threshold
        logger.info("EAR 阈值已更新为: %.4f (百分位: %.1f%%)", new_threshold, percentile)

        return new_threshold

    def reset(self) -> None:
        """重置检测器状态"""
        self._blink_frames.clear()
        self._recent_ears.clear()
        self._blink_events.clear()
        self._current_blink_start = None
        self._current_blink_start_time = None
        self._current_blink_ear_nadir = float('inf')
        self._eye_closed_start_time = None
        self._blinks_in_progress = 0
        self._frame_count = 0
        self._session_start_time = None
        self._head_pose_weight = 1.0
        self._face_stability_weight = 1.0
        self._current_ear = 0.0
        # 重置基线
        self._has_baseline = False
        self._baseline_ear = None
        # P0: 重置 adjustment 因子
        self._adjustment_factor = 1.0
        # 恢复默认阈值
        self.ear_threshold = DEFAULT_EAR_THRESHOLD

    def get_stats(self) -> dict:
        """获取检测统计信息"""
        confirmed = sum(1 for e in self._blink_events if e.is_confirmed)
        suspicious = sum(1 for e in self._blink_events if not e.is_confirmed)
        return {
            "ear_threshold": self.ear_threshold,
            "open_threshold": self.open_threshold,
            "baseline_ear": self._baseline_ear,
            "has_baseline": self._has_baseline,
            "frame_count": self._frame_count,
            "total_blinks": len(self._blink_events),
            "confirmed_blinks": confirmed,
            "suspicious_blinks": suspicious,
            "blinks_in_progress": self._blinks_in_progress,
            "recent_ear_mean": float(np.mean(list(self._recent_ears))) if self._recent_ears else 0.0,
            "recent_ear_std": float(np.std(list(self._recent_ears))) if self._recent_ears else 0.0,
            "head_pose_weight": self._head_pose_weight,
            "face_stability_weight": self._face_stability_weight,
            "adjustment_factor": self._adjustment_factor,  # P0: 新增
        }


def create_eye_aspect_detector(
    ear_threshold: Optional[float] = None,
    ear_min: Optional[float] = None,
    baseline_ear: Optional[float] = None,
) -> EyeAspectDetector:
    """工厂函数：从 config 加载参数创建检测器

    Args:
        ear_threshold: EAR 眨眼阈值（可选）
        ear_min: EAR 最小值（可选）
        baseline_ear: 个人基线 EAR（可选，设置后自动计算动态阈值）
    """
    from config import EYE

    detector = EyeAspectDetector(
        ear_threshold=ear_threshold or DEFAULT_EAR_THRESHOLD,
        ear_min=ear_min or EYE.ear_min,
        baseline_ear=baseline_ear,
    )
    return detector

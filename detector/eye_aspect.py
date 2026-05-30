"""
detector/eye_aspect.py — EAR 眨眼检测算法

提供 EyeAspectDetector 类，实现：
- EAR (Eye Aspect Ratio) 计算
- 眨眼事件检测
- 眨眼频率统计（滑动窗口）
- 个体化阈值标定

参考: Soukupová & Čech (2016) Real-Time Eye Blink Detection
"""

import logging
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("eyefocus.detector")


# 默认 EAR 阈值配置
DEFAULT_EAR_THRESHOLD = 0.21  # 通用阈值
DEFAULT_EAR_MIN = 0.08  # EAR 最小值（眼睛闭合）
DEFAULT_BLINK_DURATION_THRESHOLD = 0.3  # 秒，低于此时间为眨眼
DEFAULT_BLINK_CONFIRM_FRAMES = 2  # 连续低于阈值才确认为眨眼


@dataclass
class BlinkEvent:
    """眨眼事件"""
    start_frame: int
    end_frame: int
    start_time: float
    end_time: float
    duration: float  # 秒
    ear_nadir: float  # 眨眼时的最小 EAR


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

    使用方法：
        detector = EyeAspectDetector()
        result = detector.compute(landmarks)  # landmarks: (478, 2) 关键点
    """

    # MediaPipe 人脸关键点索引（左手系）
    LEFT_EYE_INDICES = (33, 160, 158, 133, 153, 144)
    RIGHT_EYE_INDICES = (362, 385, 387, 263, 380, 373)

    def __init__(
        self,
        ear_threshold: float = DEFAULT_EAR_THRESHOLD,
        ear_min: float = DEFAULT_EAR_MIN,
        blink_duration_thresh: float = DEFAULT_BLINK_DURATION_THRESHOLD,
        confirm_frames: int = DEFAULT_BLINK_CONFIRM_FRAMES,
        enable_adaptive_threshold: bool = False,
        adaptive_window_size: int = 30,
    ):
        """初始化 EAR 检测器

        Args:
            ear_threshold: EAR 眨眼阈值，低于此值认为是眨眼
            ear_min: EAR 最小值，用于判断眼睛是否完全闭合
            blink_duration_thresh: 眨眼持续时间阈值（秒）
            confirm_frames: 确认眨眼的连续帧数
            enable_adaptive_threshold: 是否启用自适应阈值
            adaptive_window_size: 自适应阈值窗口大小（帧数）
        """
        self.ear_threshold = ear_threshold
        self.ear_min = ear_min
        self.blink_duration_thresh = blink_duration_thresh
        self.confirm_frames = confirm_frames
        self.enable_adaptive_threshold = enable_adaptive_threshold
        self.adaptive_window_size = adaptive_window_size

        # 眨眼检测状态
        self._blink_frames: Deque[bool] = deque(maxlen=adaptive_window_size)
        self._recent_ears: Deque[float] = deque(maxlen=adaptive_window_size)

        # 眨眼事件记录
        self._blink_events: List[BlinkEvent] = []
        self._current_blink_start: Optional[int] = None
        self._current_blink_start_time: Optional[float] = None
        self._blinks_in_progress: int = 0

        # 帧计数
        self._frame_count: int = 0

        # 自适应阈值
        self._adaptive_threshold: Optional[float] = None

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

        # 检测眨眼
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

    def _update_blink_state(self, is_blink: bool, ear_avg: float) -> None:
        """更新眨眼检测状态机

        状态转移：
        开眼 -> 闭眼（眨眼开始）-> 开眼（眨眼结束）
        """
        self._blink_frames.append(is_blink)

        # 闭眼开始
        if is_blink and self._current_blink_start is None:
            self._current_blink_start = self._frame_count
            self._current_blink_start_time = (self._frame_count - 1) / 30.0  # 假设 30 FPS
            self._blinks_in_progress += 1

        # 睁眼结束
        elif not is_blink and self._current_blink_start is not None:
            # 确认眨眼（至少连续 N 帧低于阈值）
            recent_blinks = list(self._blink_frames)[-self.confirm_frames:]
            if sum(recent_blinks) >= 1:  # 至少 1 帧确认
                blink_end = self._frame_count
                blink_start = self._current_blink_start
                duration = (blink_end - blink_start) / 30.0  # 假设 30 FPS

                # 获取 EAR 最低值
                window_start = max(0, len(self._recent_ears) - self.confirm_frames - 1)
                window_ears = list(self._recent_ears)[window_start:]
                ear_nadir = min(window_ears) if window_ears else ear_avg

                # 过滤过长的"闭眼"（可能是注意力转移而非眨眼）
                if duration < self.blink_duration_thresh * 3:
                    event = BlinkEvent(
                        start_frame=blink_start,
                        end_frame=blink_end,
                        start_time=self._current_blink_start_time,
                        end_time=self._current_blink_start_time + duration,
                        duration=duration,
                        ear_nadir=ear_nadir,
                    )
                    self._blink_events.append(event)
                    logger.debug(
                        "眨眼事件: start=%d, end=%d, duration=%.3fs, nadir=%.4f",
                        blink_start, blink_end, duration, ear_nadir
                    )

            self._current_blink_start = None
            self._current_blink_start_time = None

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

        # 筛选窗口内的眨眼
        window_start = current_time - window_seconds
        recent_blinks = [
            e for e in self._blink_events
            if window_start <= e.end_time <= current_time
        ]

        blink_count = len(recent_blinks)

        # 计算实际窗口时长
        if recent_blinks:
            actual_window = current_time - max(e.start_time for e in recent_blinks)
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
        self._blinks_in_progress = 0
        self._frame_count = 0
        self._adaptive_threshold = None

    def get_stats(self) -> dict:
        """获取检测统计信息"""
        return {
            "ear_threshold": self.ear_threshold,
            "frame_count": self._frame_count,
            "total_blinks": len(self._blink_events),
            "blinks_in_progress": self._blinks_in_progress,
            "recent_ear_mean": float(np.mean(list(self._recent_ears))) if self._recent_ears else 0.0,
            "recent_ear_std": float(np.std(list(self._recent_ears))) if self._recent_ears else 0.0,
        }


def create_eye_aspect_detector(
    ear_threshold: Optional[float] = None,
    ear_min: Optional[float] = None,
) -> EyeAspectDetector:
    """工厂函数：从 config 加载参数创建检测器"""
    from config import EYE

    return EyeAspectDetector(
        ear_threshold=ear_threshold or EYE.ear_min * 2.5,  # 经验公式
        ear_min=ear_min or EYE.ear_min,
    )

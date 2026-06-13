"""
analyzer/focus.py — 专注度分析器 (v4.6)

v4.6: 从 0-100 精细分数改为 FocusLevel 三档。
诚实面对 EAR 信号精度上限：6 个眼部关键点 → 1 个浮点数
只能可靠判断"眼睛是否正常睁开"，无法支持 100 级精度。
"""

import logging
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Optional

import numpy as np

from storage.models import FocusRecord

logger = logging.getLogger("eyefocus.analyzer")


# ═══════════════════════════════════════════════════
# v4.6: FocusLevel 三档（替代 0-100 分数）
# ═══════════════════════════════════════════════════

class FocusLevel(Enum):
    FOCUSED = "focused"        # 专注：眼睛稳定睁开
    NORMAL = "normal"          # 一般：偶尔偏离
    DISTRACTED = "distracted"  # 分心：频繁闭眼或脸部丢失


FOCUS_LEVEL_LABELS = {
    FocusLevel.FOCUSED: "专注",
    FocusLevel.NORMAL: "一般",
    FocusLevel.DISTRACTED: "分心",
}

FOCUSED_MAX_DEVIATION_SECS = 5     # ≤5 秒偏差 → FOCUSED
DISTRACTED_MIN_DEVIATION_SECS = 15  # ≥15 秒偏差 → DISTRACTED


@dataclass
class FocusResult:
    """专注度分析结果 (v4.6: 三档等级替代 0-100 分数)"""
    focus_level: FocusLevel = FocusLevel.NORMAL
    eye_openness: float = 1.0     # 0-1, 当前睁眼程度
    eye_stability: float = 1.0    # 0-1, 30s 窗口稳定性
    blink_rate: float = 0.0
    is_attentive: bool = True
    # 向后兼容 (旧代码读 .focus_score 不崩溃)
    focus_score: float = 50.0
    eye_score: float = 50.0
    head_score: float = 50.0
    gaze_score: float = 50.0


class KalmanFilter1D:
    """一维卡尔曼滤波器 (保留，供其他模块使用)"""

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
    """专注度分析器 (v4.6)

    从单一 EAR 信号做 30s 滑动窗口统计，输出 FocusLevel 三档。
    诚实面对信号精度上限，不强行算出 0-100 分数。
    """

    def __init__(
        self,
        baseline_ear: float = 0.25,
        baseline_yaw_std: float = 3.0,
        baseline_pitch_std: float = 3.0,
        eye_weight: float = 0.35,
        head_weight: float = 0.30,
        gaze_weight: float = 0.35,
        window_size: float = 30.0,
        fps: float = 30.0,
        enable_kalman: bool = False,
    ):
        self.baseline_ear = baseline_ear
        self.baseline_yaw_std = baseline_yaw_std
        self.baseline_pitch_std = baseline_pitch_std
        self.window_size = window_size
        self.fps = fps

        self._max_samples = int(window_size)
        self._window_samples: Deque[float] = deque(maxlen=self._max_samples)
        self._last_sample_second: int = -1

        self._blink_detector = None
        self._current_level = FocusLevel.NORMAL
        self._face_lost_start_time: Optional[float] = None

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
        logger.info("专注度基线已更新: EAR=%.4f", ear)

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

        if not face_detected:
            level = self._handle_face_lost(current_time)
            return FocusResult(
                focus_level=level,
                eye_openness=0.0,
                eye_stability=0.0,
                blink_rate=self._get_blink_rate(),
                is_attentive=(level == FocusLevel.FOCUSED),
                focus_score=self._level_to_score(level),
            )

        self._face_lost_start_time = None

        current_second = int(current_time)
        if current_second != self._last_sample_second:
            self._last_sample_second = current_second
            self._window_samples.append(ear)

        if self.baseline_ear > 0:
            openness = min(1.0, max(0.0, ear / self.baseline_ear))
        else:
            openness = 0.5

        stability, level = self._compute_window_level()
        self._current_level = level

        return FocusResult(
            focus_level=level,
            eye_openness=round(openness, 2),
            eye_stability=round(stability, 2),
            blink_rate=self._get_blink_rate(),
            is_attentive=(level == FocusLevel.FOCUSED),
            focus_score=self._level_to_score(level),
        )

    def _compute_window_level(self) -> tuple[float, FocusLevel]:
        if len(self._window_samples) < 3:
            return 1.0, FocusLevel.NORMAL

        if self.baseline_ear <= 0:
            return 0.5, FocusLevel.NORMAL

        deviated = 0
        for ear_val in self._window_samples:
            deviation = abs(ear_val - self.baseline_ear) / self.baseline_ear
            if deviation > 0.15:
                deviated += 1

        total = len(self._window_samples)
        stability = 1.0 - (deviated / total)

        if deviated <= FOCUSED_MAX_DEVIATION_SECS:
            level = FocusLevel.FOCUSED
        elif deviated >= DISTRACTED_MIN_DEVIATION_SECS:
            level = FocusLevel.DISTRACTED
        else:
            level = FocusLevel.NORMAL

        return stability, level

    def _handle_face_lost(self, current_time: float) -> FocusLevel:
        if self._face_lost_start_time is None:
            self._face_lost_start_time = current_time
        lost = current_time - self._face_lost_start_time
        if lost < 2.0:
            return self._current_level
        elif lost < 10.0:
            return FocusLevel.NORMAL
        else:
            return FocusLevel.DISTRACTED

    def _get_blink_rate(self) -> float:
        if self._blink_detector:
            rate, _ = self._blink_detector.get_blink_rate(window_seconds=60.0)
            return round(rate, 1)
        return 0.0

    @staticmethod
    def _level_to_score(level: FocusLevel) -> float:
        return {FocusLevel.FOCUSED: 85.0, FocusLevel.NORMAL: 55.0, FocusLevel.DISTRACTED: 25.0}.get(level, 50.0)

    def get_window_summary(self) -> Optional[FocusRecord]:
        if not self._window_samples:
            return None
        samples = list(self._window_samples)
        return FocusRecord(
            session_id="",
            window_start=0.0,
            window_end=float(len(samples)),
            focus_score=self._level_to_score(self._current_level),
            eye_score=50.0, head_score=50.0, gaze_score=50.0,
            blink_rate=self._get_blink_rate(),
            avg_ear=float(np.mean(samples)),
            avg_yaw=0.0, avg_pitch=0.0,
        )

    def reset(self) -> None:
        self._window_samples.clear()
        self._last_sample_second = -1
        self._face_lost_start_time = None
        self._current_level = FocusLevel.NORMAL

    def get_stats(self) -> dict:
        return {
            "baseline_ear": self.baseline_ear,
            "window_size": self.window_size,
            "window_samples": len(self._window_samples),
            "current_level": self._current_level.value if self._current_level else "none",
        }


def create_focus_analyzer(baseline_ear: float = 0.25) -> FocusAnalyzer:
    """工厂函数：创建专注度分析器（支持 YAML 配置覆盖）"""
    from config import get_yaml_value
    return FocusAnalyzer(
        baseline_ear=baseline_ear,
        window_size=get_yaml_value("focus", "window_size", default=30.0),
    )

"""
analyzer/fatigue.py — 疲劳分析模块 (v4.6)

v4.6: 从 PERCLOS + LOW/MEDIUM/HIGH 改为 FatigueIndicator 三档。
只统计长闭眼事件 (>0.5s, 疲劳信号)，忽略正常眨眼 (<0.4s)。
3 分钟滚动窗口平滑，趋势优先。
"""

import logging
import math
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Optional, Tuple

import numpy as np

from storage.models import FatigueLevel, FatigueRecord

logger = logging.getLogger("eyefocus.analyzer")


# ═══════════════════════════════════════════════════
# v4.6: FatigueIndicator (替代 0-100 分数 + LOW/MEDIUM/HIGH)
# ═══════════════════════════════════════════════════

class FatigueIndicator(Enum):
    RESTED = "rested"          # 清醒：长闭眼少
    ATTENTION = "attention"    # 关注：长闭眼增多
    TIRED = "tired"            # 需休息：长闭眼频繁


FATIGUE_LABELS = {
    FatigueIndicator.RESTED: "清醒",
    FatigueIndicator.ATTENTION: "关注",
    FatigueIndicator.TIRED: "休息",
}

# 3 分钟窗口阈值 (v4.6.1: 根据 11min 实测调优)
RESTED_MAX_CLOSURES = 3       # ≤3 次长闭眼 → 清醒
TIRED_MIN_CLOSURES = 15       # ≥15 次长闭眼 → 需休息 (v4.30: 8→15 降误报)

# EMA 时间常数（秒）— 分数反映分钟级趋势而非秒级波动
_EMA_TAU = 120.0  # 2 分钟半衰期


@dataclass
class FatigueAnalysisResult:
    """疲劳分析结果 (v4.6)"""
    fatigue_indicator: FatigueIndicator = FatigueIndicator.RESTED
    prolonged_closures_3min: int = 0   # 近 3 分钟长闭眼次数
    blink_rate: float = 0.0
    # 向后兼容
    fatigue_level: FatigueLevel = FatigueLevel.LOW
    fatigue_score: float = 0.0
    avg_ear_nadir: float = 0.0
    head_stability: float = 100.0
    cumulative_fatigue: float = 0.0
    perclos: float = 0.0
    sustained_medium_seconds: float = 0.0
    sustained_high_seconds: float = 0.0


class FatigueAnalyzer:
    """疲劳分析器 (v4.6)

    基于长闭眼事件 (>0.5s) 的 3 分钟滚动计数。
    区分正常快眨眼和疲劳长闭眼，用趋势替代瞬时值。

    使用方法：
        analyzer = FatigueAnalyzer()
        analyzer.start()
        result = analyzer.analyze(closure_type="open", blink_rate=12.0)
    """

    def __init__(
        self,
        baseline_blink_rate: float = 15.0,
        blink_multiplier_low: float = 1.3,
        blink_multiplier_high: float = 1.8,
        head_stability_thresh: float = 70.0,
        window_size: int = 30,
        perclos_window: float = 180.0,   # v4.6: 3min 窗口
        perclos_threshold_mild: float = 8.0,
        perclos_threshold_severe: float = 10.0,
        sustained_duration: float = 15.0,
    ):
        self.baseline_blink_rate = baseline_blink_rate
        self.blink_multiplier_low = blink_multiplier_low
        self.blink_multiplier_high = blink_multiplier_high
        self.head_stability_thresh = head_stability_thresh
        self.window_size = window_size
        self.perclos_window = perclos_window
        self.perclos_threshold_mild = perclos_threshold_mild
        self.perclos_threshold_severe = perclos_threshold_severe
        self.sustained_duration = sustained_duration

        self._cumulative_fatigue: float = 0.0
        self._fatigue_history: Deque[float] = deque(maxlen=100)
        self._recent_ear_nadirs: Deque[float] = deque(maxlen=window_size)
        self._recent_head_stabilities: Deque[float] = deque(maxlen=window_size)
        self._last_blink_rate: float = 0.0
        self._last_analysis_time: Optional[float] = None

        # v4.6: 长闭眼事件时间戳 (deque, maxlen=100)
        self._prolonged_events: Deque[float] = deque(maxlen=100)
        self._was_prolonged: bool = False  # 去重：同一事件不重复计数

        self._medium_onset_time: Optional[float] = None
        self._high_onset_time: Optional[float] = None
        self._start_time: Optional[float] = None
        self._last_ema_time: Optional[float] = None  # v4.30: 时间基 EMA 时间戳

    def start(self) -> None:
        self._start_time = time.time()
        self._cumulative_fatigue = 0.0
        self._fatigue_history.clear()
        self._recent_ear_nadirs.clear()
        self._recent_head_stabilities.clear()
        self._last_blink_rate = 0.0
        self._prolonged_events.clear()
        self._was_prolonged = False
        self._last_analysis_time = time.time()
        self._last_ema_time = None

    def set_baseline_blink_rate(self, baseline_blink_rate: float) -> None:
        self.baseline_blink_rate = baseline_blink_rate
        logger.info("疲劳基线眨眼频率已更新: %.1f 次/分钟", baseline_blink_rate)

    def analyze(
        self,
        closure_type: str = "open",
        blink_rate: float = 0.0,
        ear_nadir: Optional[float] = None,
        head_stability: Optional[float] = None,
        avg_ear: Optional[float] = None,
        blink_flag: bool = False,
    ) -> FatigueAnalysisResult:
        """分析疲劳等级 (v4.6)

        Args:
            closure_type: EyeAspectDetector.get_closure_type() — "open"/"blink"/"prolonged"
            blink_rate: 眨眼频率 (次/分钟)
            (其他参数保留用于向后兼容)
        """
        current_time = time.time()

        self._last_blink_rate = blink_rate
        self._last_analysis_time = current_time

        if ear_nadir is not None:
            self._recent_ear_nadirs.append(ear_nadir)
        if head_stability is not None:
            self._recent_head_stabilities.append(head_stability)

        # v4.6: 只计数长闭眼事件（>0.5s），忽略快眨眼
        if closure_type == "prolonged":
            if not self._was_prolonged:
                self._prolonged_events.append(current_time)
                self._was_prolonged = True
        else:
            self._was_prolonged = False

        # 清理 3 分钟窗口外的旧事件
        cutoff = current_time - self.perclos_window
        while self._prolonged_events and self._prolonged_events[0] < cutoff:
            self._prolonged_events.popleft()

        prolonged_count = len(self._prolonged_events)

        # 累积疲劳（v4.35: 连续分数映射 + 时间基 EMA）
        indicator = self._indicator_from_count(prolonged_count)
        score = self._indicator_to_score(indicator, prolonged_count)
        if self._last_ema_time is not None:
            dt = max(0.0, current_time - self._last_ema_time)
            alpha = 1.0 - math.exp(-dt / _EMA_TAU)
            self._cumulative_fatigue = (1.0 - alpha) * self._cumulative_fatigue + alpha * score
        else:
            self._cumulative_fatigue = score
        self._last_ema_time = current_time
        self._fatigue_history.append(score)

        return FatigueAnalysisResult(
            fatigue_indicator=indicator,
            prolonged_closures_3min=prolonged_count,
            blink_rate=blink_rate,
            fatigue_level=self._indicator_to_legacy_level(indicator),
            fatigue_score=score,
            avg_ear_nadir=float(np.mean(self._recent_ear_nadirs)) if self._recent_ear_nadirs else 0.0,
            head_stability=float(np.mean(self._recent_head_stabilities)) if self._recent_head_stabilities else 100.0,
            cumulative_fatigue=self._cumulative_fatigue,
            perclos=0.0,
            sustained_medium_seconds=0.0,
            sustained_high_seconds=0.0,
        )

    @staticmethod
    def _indicator_from_count(count: int) -> FatigueIndicator:
        if count <= RESTED_MAX_CLOSURES:
            return FatigueIndicator.RESTED
        elif count >= TIRED_MIN_CLOSURES:
            return FatigueIndicator.TIRED
        else:
            return FatigueIndicator.ATTENTION

    @staticmethod
    def _indicator_to_score(indicator: FatigueIndicator, count: int = 0) -> float:
        """v4.35: 连续分数映射（替代 3 级跳变）

        锚点: (0次→5分) (3→20) (8→40) (15→70) (25→95)
        中间值线性插值，疲劳曲线不再阶梯状。
        """
        if count <= 0:
            bases = {FatigueIndicator.RESTED: 10.0, FatigueIndicator.ATTENTION: 40.0, FatigueIndicator.TIRED: 80.0}
            return bases.get(indicator, 20.0)

        anchors = [(0, 5.0), (3, 20.0), (8, 40.0), (15, 70.0), (25, 95.0)]
        if count >= anchors[-1][0]:
            return anchors[-1][1]
        for i in range(len(anchors) - 1):
            lo_c, lo_s = anchors[i]
            hi_c, hi_s = anchors[i + 1]
            if lo_c <= count < hi_c:
                ratio = (count - lo_c) / (hi_c - lo_c) if hi_c != lo_c else 0.0
                return round(lo_s + ratio * (hi_s - lo_s), 1)
        return 5.0

    @staticmethod
    def _indicator_to_legacy_level(indicator: FatigueIndicator) -> FatigueLevel:
        return {FatigueIndicator.RESTED: FatigueLevel.LOW, FatigueIndicator.ATTENTION: FatigueLevel.MEDIUM, FatigueIndicator.TIRED: FatigueLevel.HIGH}.get(indicator, FatigueLevel.LOW)

    def get_record(self, session_id: str = "", timestamp: Optional[float] = None) -> Optional[FatigueRecord]:
        if timestamp is None:
            timestamp = self._last_analysis_time
        if self._last_analysis_time is None:
            return None
        return FatigueRecord(
            session_id=session_id,
            timestamp=timestamp,
            blink_rate=self._last_blink_rate,
            avg_ear_nadir=float(np.mean(self._recent_ear_nadirs)) if self._recent_ear_nadirs else 0.0,
            head_stability=float(np.mean(self._recent_head_stabilities)) if self._recent_head_stabilities else 100.0,
            cumulative_fatigue_score=self._cumulative_fatigue,
            fatigue_level=self._indicator_to_legacy_level(self._indicator_from_count(len(self._prolonged_events))),
        )

    def reset(self) -> None:
        self._cumulative_fatigue = 0.0
        self._fatigue_history.clear()
        self._recent_ear_nadirs.clear()
        self._recent_head_stabilities.clear()
        self._last_blink_rate = 0.0
        self._prolonged_events.clear()
        self._was_prolonged = False
        self._medium_onset_time = None
        self._high_onset_time = None
        self._start_time = None
        self._last_analysis_time = None
        self._last_ema_time = None

    def get_stats(self) -> dict:
        return {
            "cumulative_fatigue": self._cumulative_fatigue,
            "baseline_blink_rate": self.baseline_blink_rate,
            "last_blink_rate": self._last_blink_rate,
            "avg_ear_nadir": float(np.mean(self._recent_ear_nadirs)) if self._recent_ear_nadirs else 0.0,
            "avg_head_stability": float(np.mean(self._recent_head_stabilities)) if self._recent_head_stabilities else 100.0,
            "prolonged_closures": len(self._prolonged_events),
            "history_size": len(self._fatigue_history),
        }


def create_fatigue_analyzer(baseline_blink_rate: float = 15.0) -> FatigueAnalyzer:
    """工厂函数"""
    from config import get_yaml_value
    return FatigueAnalyzer(
        baseline_blink_rate=baseline_blink_rate,
        perclos_window=get_yaml_value("fatigue", "perclos_window", default=180.0),
        perclos_threshold_mild=get_yaml_value("fatigue", "perclos_threshold_mild", default=8.0),
    )

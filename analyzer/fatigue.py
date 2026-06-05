"""
analyzer/fatigue.py — 疲劳分析模块

提供 FatigueAnalyzer 类，基于眨眼频率和 PERCLOS
判断用户疲劳等级（正常/轻度/重度）。

疲劳分级方案（基于 PROJECT_PLAN.md）：
- 正常: 眨眼率 < 基线×1.3 AND PERCLOS < 5%
- 轻度: 眨眼率 ≥ 基线×1.3 OR PERCLOS ≥ 5% (持续 15 秒以上)
- 重度: 眨眼率 ≥ 基线×1.8 OR PERCLOS ≥ 10% (持续 15 秒以上)

输入依赖：
- 眨眼检测器 (EyeAspectDetector) 提供眨眼频率和 blink_flag
- 头部姿态数据来自 FaceMeshDetector
"""

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

import numpy as np

from storage.models import FatigueLevel, FatigueRecord

logger = logging.getLogger("eyefocus.analyzer")


# 默认配置
DEFAULT_BLINK_MULTIPLIER_LOW = 1.3   # 眨眼频率相对基线的倍数阈值（轻微疲劳）
DEFAULT_BLINK_MULTIPLIER_HIGH = 1.8  # 眨眼频率相对基线的倍数阈值（明显疲劳）
DEFAULT_HEAD_STABILITY_THRESHOLD = 70.0  # 头部稳定性分数阈值
DEFAULT_WINDOW_SIZE = 30  # 统计窗口帧数
DEFAULT_PERCLOS_WINDOW = 60.0  # PERCLOS 统计窗口（秒）
DEFAULT_PERCLOS_THRESHOLD_MILD = 5.0   # PERCLOS 轻度阈值（百分比）
DEFAULT_PERCLOS_THRESHOLD_SEVERE = 10.0  # PERCLOS 重度阈值（百分比）
DEFAULT_SUSTAINED_DURATION = 15.0  # 条件持续触发时长（秒）


@dataclass
class FatigueAnalysisResult:
    """疲劳分析结果"""
    fatigue_level: FatigueLevel
    fatigue_score: float  # 0-100，数值越高越疲劳
    blink_rate: float  # 眨眼频率 (次/分钟)
    avg_ear_nadir: float  # 平均 EAR 谷值（闭眼深度）
    head_stability: float  # 头部稳定性 0-100
    cumulative_fatigue: float  # 累积疲劳分数 0-100
    perclos: float = 0.0  # PERCLOS 闭眼时长占比 (%)
    sustained_medium_seconds: float = 0.0  # 中度疲劳条件持续秒数
    sustained_high_seconds: float = 0.0  # 重度疲劳条件持续秒数


class FatigueAnalyzer:
    """疲劳分析器

    基于个人基线的相对变化判定疲劳等级。

    使用方法：
        analyzer = FatigueAnalyzer(baseline_blink_rate=15.0)
        analyzer.set_baseline_blink_rate(18.0)  # 可随时更新基线
        result = analyzer.analyze(blink_rate=22.0, ear_nadir=0.08, head_stability=85.0)
    """

    def __init__(
        self,
        baseline_blink_rate: float = 15.0,
        blink_multiplier_low: float = DEFAULT_BLINK_MULTIPLIER_LOW,
        blink_multiplier_high: float = DEFAULT_BLINK_MULTIPLIER_HIGH,
        head_stability_thresh: float = DEFAULT_HEAD_STABILITY_THRESHOLD,
        window_size: int = DEFAULT_WINDOW_SIZE,
        perclos_window: float = DEFAULT_PERCLOS_WINDOW,
        perclos_threshold_mild: float = DEFAULT_PERCLOS_THRESHOLD_MILD,
        perclos_threshold_severe: float = DEFAULT_PERCLOS_THRESHOLD_SEVERE,
        sustained_duration: float = DEFAULT_SUSTAINED_DURATION,
    ):
        """初始化疲劳分析器

        Args:
            baseline_blink_rate: 个人基线眨眼频率（次/分钟）
            blink_multiplier_low: 轻微疲劳倍数（默认 1.3x）
            blink_multiplier_high: 明显疲劳倍数（默认 1.8x）
            head_stability_thresh: 头部稳定性阈值
            window_size: 统计窗口大小
            perclos_window: PERCLOS 统计窗口（秒）
            perclos_threshold_mild: PERCLOS 轻度阈值（%）
            perclos_threshold_severe: PERCLOS 重度阈值（%）
            sustained_duration: 条件持续触发时长（秒）
        """
        self.baseline_blink_rate = baseline_blink_rate
        self.blink_multiplier_low = blink_multiplier_low
        self.blink_multiplier_high = blink_multiplier_high
        self.head_stability_thresh = head_stability_thresh
        self.window_size = window_size
        self.perclos_window = perclos_window
        self.perclos_threshold_mild = perclos_threshold_mild
        self.perclos_threshold_severe = perclos_threshold_severe
        self.sustained_duration = sustained_duration

        # 累积疲劳分数
        self._cumulative_fatigue: float = 0.0
        self._fatigue_history: Deque[float] = deque(maxlen=100)

        # 最近分析结果
        self._recent_ear_nadirs: Deque[float] = deque(maxlen=window_size)
        self._recent_head_stabilities: Deque[float] = deque(maxlen=window_size)
        self._last_blink_rate: float = 0.0

        # PERCLOS 追踪：记录每帧的闭眼状态和时间戳
        # (timestamp, is_closed) 元组的时间序列
        self._perclos_history: Deque[tuple[float, bool]] = deque(maxlen=1000)

        # 持续时间追踪（秒）
        self._medium_onset_time: Optional[float] = None  # 中度疲劳条件首次满足时间
        self._high_onset_time: Optional[float] = None   # 重度疲劳条件首次满足时间

        # 时间追踪
        self._start_time: Optional[float] = None
        self._last_analysis_time: Optional[float] = None

    def start(self) -> None:
        """开始疲劳追踪"""
        self._start_time = time.time()
        self._last_analysis_time = self._start_time
        self._cumulative_fatigue = 0.0
        self._fatigue_history.clear()
        self._perclos_history.clear()
        self._medium_onset_time = None
        self._high_onset_time = None
        # M-01: 清空 EAR/head 滑动窗口 + 上次眨眼率, 避免跨 session 复用实例时
        # 上 session 残留数据污染新 session 开头几秒的 avg_ear_nadir/avg_head_stability
        self._recent_ear_nadirs.clear()
        self._recent_head_stabilities.clear()
        self._last_blink_rate = 0.0
        logger.info("疲劳分析开始追踪")

    def set_baseline_blink_rate(self, baseline_blink_rate: float) -> None:
        """设置个人基线眨眼频率

        Args:
            baseline_blink_rate: 个人正常状态下的眨眼频率（次/分钟）
        """
        self.baseline_blink_rate = baseline_blink_rate
        logger.info("疲劳基线眨眼频率已更新: %.1f 次/分钟", baseline_blink_rate)

    def analyze(
        self,
        blink_rate: float,
        ear_nadir: Optional[float] = None,
        head_stability: Optional[float] = None,
        avg_ear: Optional[float] = None,
        blink_flag: bool = False,
    ) -> FatigueAnalysisResult:
        """分析当前疲劳等级

        Args:
            blink_rate: 眨眼频率 (次/分钟)
            ear_nadir: EAR 最低值（闭眼时）
            head_stability: 头部稳定性分数 (0-100)
            avg_ear: 平均 EAR 值
            blink_flag: 当前帧是否处于闭眼状态（眨眼期间为 True）

        Returns:
            FatigueAnalysisResult 对象
        """
        current_time = time.time()
        self._last_blink_rate = blink_rate
        self._last_analysis_time = current_time

        if ear_nadir is not None:
            self._recent_ear_nadirs.append(ear_nadir)
        if head_stability is not None:
            self._recent_head_stabilities.append(head_stability)

        # 记录 PERCLOS 数据（当前帧的闭眼状态）
        self._perclos_history.append((current_time, blink_flag))

        # 计算 PERCLOS
        perclos = self._compute_perclos(current_time)

        # 计算平均 EAR 谷值
        avg_ear_nadir = float(np.mean(self._recent_ear_nadirs)) if self._recent_ear_nadirs else 0.1

        # 计算平均头部稳定性
        avg_head_stability = float(np.mean(self._recent_head_stabilities)) if self._recent_head_stabilities else 100.0

        # 计算疲劳分数
        fatigue_score = self._compute_fatigue_score(
            blink_rate=blink_rate,
            ear_nadir=avg_ear_nadir,
            head_stability=avg_head_stability,
            perclos=perclos,
        )

        # 累积疲劳（指数移动平均）
        if self._fatigue_history:
            self._cumulative_fatigue = (
                0.95 * self._cumulative_fatigue + 0.05 * fatigue_score
            )
        else:
            self._cumulative_fatigue = fatigue_score

        self._fatigue_history.append(fatigue_score)

        # 计算眨眼频率倍数
        multiplier = 0.0
        if self.baseline_blink_rate > 0 and blink_rate > 0:
            multiplier = blink_rate / self.baseline_blink_rate

        # 更新持续时间追踪
        sustained_medium, sustained_high = self._update_sustained_tracking(
            current_time=current_time,
            multiplier=multiplier,
            perclos=perclos,
        )

        # 确定疲劳等级
        fatigue_level = self._determine_fatigue_level(
            blink_rate=blink_rate,
            head_stability=avg_head_stability,
            perclos=perclos,
            sustained_medium=sustained_medium,
            sustained_high=sustained_high,
        )

        return FatigueAnalysisResult(
            fatigue_level=fatigue_level,
            fatigue_score=fatigue_score,
            blink_rate=blink_rate,
            avg_ear_nadir=avg_ear_nadir,
            head_stability=avg_head_stability,
            cumulative_fatigue=self._cumulative_fatigue,
            perclos=perclos,
            sustained_medium_seconds=sustained_medium,
            sustained_high_seconds=sustained_high,
        )

    def _compute_fatigue_score(
        self,
        blink_rate: float,
        ear_nadir: float,
        head_stability: float,
        perclos: float = 0.0,
    ) -> float:
        """计算疲劳分数 (0-100)

        基于眨眼频率相对基线的倍数、闭眼深度、头部稳定性和 PERCLOS
        """
        # 眨眼频率分数 (0-30) — 基于基线的相对变化
        if self.baseline_blink_rate <= 0:
            blink_score = 0.0
        else:
            multiplier = blink_rate / self.baseline_blink_rate

            if multiplier <= 1.0:
                # 眨眼频率未增加，得 0 分
                blink_score = 0.0
            elif multiplier <= self.blink_multiplier_low:
                # 眨眼频率增加 0-30%，线性增长到 15 分
                blink_score = (multiplier - 1.0) / (self.blink_multiplier_low - 1.0) * 15.0
            elif multiplier <= self.blink_multiplier_high:
                # 眨眼频率增加 30-80%，线性增长到 30 分
                blink_score = 15.0 + (multiplier - self.blink_multiplier_low) / (
                    self.blink_multiplier_high - self.blink_multiplier_low
                ) * 15.0
            else:
                # 眨眼频率增加超过 80%，满分 30 分
                blink_score = min(30.0, 30.0 + (multiplier - self.blink_multiplier_high) * 5.0)

        # 闭眼深度分数 (0-20)
        # EAR 越低（闭眼越深），疲劳分数越高
        if ear_nadir >= 0.15:
            eye_score = 0.0
        elif ear_nadir >= 0.08:
            eye_score = (0.15 - ear_nadir) / 0.07 * 20.0
        else:
            eye_score = 20.0

        # 头部稳定性分数 (0-20)
        if head_stability >= self.head_stability_thresh:
            head_score = 0.0
        else:
            head_score = (self.head_stability_thresh - head_stability) / self.head_stability_thresh * 20.0

        # PERCLOS 分数 (0-30)
        # PERCLOS 越高，疲劳分数越高
        perclos_score = min(30.0, perclos * 3.0)  # 10% PERCLOS = 30分满分

        return min(100.0, blink_score + eye_score + head_score + perclos_score)

    def _determine_fatigue_level(
        self,
        blink_rate: float,
        head_stability: float,
        perclos: float = 0.0,
        sustained_medium: float = 0.0,
        sustained_high: float = 0.0,
    ) -> FatigueLevel:
        """确定疲劳等级

        基于 PROJECT_PLAN.md 定义：
        - 正常: 眨眼率 < 基线×1.3 AND PERCLOS < 5%
        - 轻度: 眨眼率 ≥ 基线×1.3 OR PERCLOS ≥ 5% (持续 15 秒以上)
        - 重度: 眨眼率 ≥ 基线×1.8 OR PERCLOS ≥ 10% (持续 15 秒以上)

        注意：头部稳定性不再作为独立条件，仅作为辅助参考
        """
        if self.baseline_blink_rate <= 0:
            return FatigueLevel.LOW

        multiplier = blink_rate / self.baseline_blink_rate

        # 重度疲劳条件（持续 15 秒以上）
        if sustained_high >= self.sustained_duration:
            return FatigueLevel.HIGH

        # 中度疲劳条件（持续 15 秒以上）
        if sustained_medium >= self.sustained_duration:
            return FatigueLevel.MEDIUM

        # 正常状态
        if multiplier < self.blink_multiplier_low and perclos < self.perclos_threshold_mild:
            return FatigueLevel.LOW

        # 轻度疲劳（暂态，不满足持续时间）
        if multiplier >= self.blink_multiplier_low or perclos >= self.perclos_threshold_mild:
            return FatigueLevel.MEDIUM

        # 重度疲劳（暂态，不满足持续时间）
        if multiplier >= self.blink_multiplier_high or perclos >= self.perclos_threshold_severe:
            return FatigueLevel.HIGH

        return FatigueLevel.LOW

    def _compute_perclos(self, current_time: float) -> float:
        """计算 PERCLOS（闭眼时长占比）

        PERCLOS = 最近 60 秒内闭眼(blink_flag=1)总时长 / 60

        Args:
            current_time: 当前时间戳

        Returns:
            PERCLOS 百分比 (0-100)
        """
        if not self._perclos_history:
            return 0.0

        # 只保留最近 perclos_window 秒内的数据
        window_start = current_time - self.perclos_window

        # 清理过期数据
        while self._perclos_history and self._perclos_history[0][0] < window_start:
            self._perclos_history.popleft()

        if len(self._perclos_history) < 2:
            return 0.0

        # 转换为列表以便切片
        history_list = list(self._perclos_history)

        # 计算闭眼时长
        closed_time = 0.0
        prev_time = history_list[0][0]
        prev_closed = history_list[0][1]

        for ts, is_closed in history_list[1:]:
            if prev_closed:
                closed_time += ts - prev_time
            prev_time = ts
            prev_closed = is_closed

        # M-02: 末帧仍闭眼时, 把从最后帧到 current_time 的时长计入 closed_time
        if prev_closed and current_time > prev_time:
            closed_time += current_time - prev_time

        # 计算 PERCLOS 百分比
        total_time = self._perclos_history[-1][0] - self._perclos_history[0][0]
        if total_time <= 0:
            return 0.0

        return (closed_time / self.perclos_window) * 100.0

    @staticmethod
    def _compute_sustained(
        medium_onset: Optional[float],
        high_onset: Optional[float],
        current_time: float,
        multiplier: float,
        perclos: float,
        blink_multiplier_low: float,
        blink_multiplier_high: float,
        perclos_threshold_mild: float,
        perclos_threshold_severe: float,
    ) -> tuple[Optional[float], Optional[float], float, float]:
        """纯函数: 计算持续时间追踪 (无副作用, 不修改输入)

        Args:
            medium_onset: 当前 _medium_onset_time 状态
            high_onset: 当前 _high_onset_time 状态
            current_time: 当前时间戳
            multiplier: 眨眼频率相对基线的倍数
            perclos: 当前 PERCLOS 值 (%)
            blink_multiplier_low: 中度疲劳眨眼倍数阈值
            blink_multiplier_high: 重度疲劳眨眼倍数阈值
            perclos_threshold_mild: 中度疲劳 PERCLOS 阈值 (%)
            perclos_threshold_severe: 重度疲劳 PERCLOS 阈值 (%)

        Returns:
            (new_medium_onset, new_high_onset, sustained_medium_seconds, sustained_high_seconds)
        """
        # 中度疲劳条件：眨眼率 ≥ 基线×1.3 OR PERCLOS ≥ 5%
        medium_condition = (multiplier >= blink_multiplier_low) or (
            perclos >= perclos_threshold_mild
        )

        # 重度疲劳条件：眨眼率 ≥ 基线×1.8 OR PERCLOS ≥ 10%
        high_condition = (multiplier >= blink_multiplier_high) or (
            perclos >= perclos_threshold_severe
        )

        # 计算中度疲劳持续时间 (新 onset, 不写入 self)
        if medium_condition:
            new_medium_onset = medium_onset if medium_onset is not None else current_time
            sustained_medium = current_time - new_medium_onset
        else:
            new_medium_onset = None
            sustained_medium = 0.0

        # 计算重度疲劳持续时间 (新 onset, 不写入 self)
        if high_condition:
            new_high_onset = high_onset if high_onset is not None else current_time
            sustained_high = current_time - new_high_onset
        else:
            new_high_onset = None
            sustained_high = 0.0

        return new_medium_onset, new_high_onset, sustained_medium, sustained_high

    def _update_sustained_tracking(
        self,
        current_time: float,
        multiplier: float,
        perclos: float,
    ) -> tuple[float, float]:
        """更新持续时间追踪 (in-place wrapper, 委托给纯函数 _compute_sustained)

        Args:
            current_time: 当前时间戳
            multiplier: 眨眼频率相对基线的倍数
            perclos: 当前 PERCLOS 值 (%)

        Returns:
            (sustained_medium_seconds, sustained_high_seconds)
        """
        new_m, new_h, sustained_medium, sustained_high = self._compute_sustained(
            self._medium_onset_time,
            self._high_onset_time,
            current_time,
            multiplier,
            perclos,
            self.blink_multiplier_low,
            self.blink_multiplier_high,
            self.perclos_threshold_mild,
            self.perclos_threshold_severe,
        )
        self._medium_onset_time = new_m
        self._high_onset_time = new_h
        return sustained_medium, sustained_high

    def get_record(self, session_id: str, timestamp: float) -> Optional[FatigueRecord]:
        """获取疲劳记录

        Args:
            session_id: 会话 ID
            timestamp: 时间戳（秒）

        Returns:
            FatigueRecord 对象
        """
        if not self._fatigue_history:
            return None

        current_time = timestamp
        perclos = self._compute_perclos(current_time) if self._perclos_history else 0.0

        # 计算持续时间 (H-04: 调纯函数 _compute_sustained, 不修改 self 状态)
        sustained_medium = 0.0
        sustained_high = 0.0
        if self._last_analysis_time is not None:
            _, _, sustained_medium, sustained_high = self._compute_sustained(
                self._medium_onset_time,
                self._high_onset_time,
                current_time,
                self._last_blink_rate / self.baseline_blink_rate if self.baseline_blink_rate > 0 else 0.0,
                perclos,
                self.blink_multiplier_low,
                self.blink_multiplier_high,
                self.perclos_threshold_mild,
                self.perclos_threshold_severe,
            )

        return FatigueRecord(
            session_id=session_id,
            timestamp=timestamp,
            fatigue_level=self._determine_fatigue_level(
                blink_rate=self._last_blink_rate,
                head_stability=float(np.mean(self._recent_head_stabilities)) if self._recent_head_stabilities else 100.0,
                perclos=perclos,
                sustained_medium=sustained_medium,
                sustained_high=sustained_high,
            ),
            blink_rate=self._last_blink_rate,
            avg_ear_nadir=float(np.mean(self._recent_ear_nadirs)) if self._recent_ear_nadirs else 0.1,
            head_stability=float(np.mean(self._recent_head_stabilities)) if self._recent_head_stabilities else 100.0,
            cumulative_fatigue_score=self._cumulative_fatigue,
        )

    def reset(self) -> None:
        """重置分析器状态"""
        self._cumulative_fatigue = 0.0
        self._fatigue_history.clear()
        self._recent_ear_nadirs.clear()
        self._recent_head_stabilities.clear()
        self._perclos_history.clear()
        self._medium_onset_time = None
        self._high_onset_time = None
        self._start_time = None
        self._last_analysis_time = None
        self._last_blink_rate = 0.0

    def get_stats(self) -> dict:
        """获取分析统计信息"""
        multiplier = 0.0
        if self.baseline_blink_rate > 0 and self._last_blink_rate > 0:
            multiplier = self._last_blink_rate / self.baseline_blink_rate

        current_time = self._last_analysis_time or time.time()
        perclos = self._compute_perclos(current_time) if self._perclos_history else 0.0

        return {
            "cumulative_fatigue": self._cumulative_fatigue,
            "baseline_blink_rate": self.baseline_blink_rate,
            "last_blink_rate": self._last_blink_rate,
            "blink_multiplier": multiplier,
            "avg_ear_nadir": float(np.mean(self._recent_ear_nadirs)) if self._recent_ear_nadirs else 0.0,
            "avg_head_stability": float(np.mean(self._recent_head_stabilities)) if self._recent_head_stabilities else 100.0,
            "perclos": perclos,
            "history_size": len(self._fatigue_history),
            "blink_multiplier_thresholds": {
                "low": self.blink_multiplier_low,
                "high": self.blink_multiplier_high,
            },
            "perclos_thresholds": {
                "mild": self.perclos_threshold_mild,
                "severe": self.perclos_threshold_severe,
            },
            "sustained_duration": self.sustained_duration,
        }


def create_fatigue_analyzer(baseline_blink_rate: float = 15.0) -> FatigueAnalyzer:
    """工厂函数：创建疲劳分析器（支持 YAML 配置覆盖）"""
    from config import get_yaml_value
    return FatigueAnalyzer(
        baseline_blink_rate=baseline_blink_rate,
        perclos_window=get_yaml_value("fatigue", "perclos_window", default=30.0),
        perclos_threshold_mild=get_yaml_value("fatigue", "perclos_threshold_mild", default=5.0),
    )

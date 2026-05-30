"""
analyzer/fatigue.py — 疲劳分析模块（启发式）

提供 FatigueAnalyzer 类，基于眨眼频率和头部姿态
判断用户疲劳等级（低/中/高）。

疲劳分级方案（启发式）：
- 低疲劳：眨眼频率正常（< 20次/分钟）+ 头部姿态稳定
- 中疲劳：眨眼频率升高（20-30次/分钟）或头部姿态偏移
- 高疲劳：眨眼频率持续偏高（> 30次/分钟）+ 闭眼时长增加

输入依赖：
- 眨眼检测器 (EyeAspectDetector) 提供眨眼频率
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


@dataclass
class FatigueAnalysisResult:
    """疲劳分析结果"""
    fatigue_level: FatigueLevel
    fatigue_score: float  # 0-100，数值越高越疲劳
    blink_rate: float  # 眨眼频率 (次/分钟)
    avg_ear_nadir: float  # 平均 EAR 谷值（闭眼深度）
    head_stability: float  # 头部稳定性 0-100
    cumulative_fatigue: float  # 累积疲劳分数 0-100


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
    ):
        """初始化疲劳分析器

        Args:
            baseline_blink_rate: 个人基线眨眼频率（次/分钟）
            blink_multiplier_low: 轻微疲劳倍数（默认 1.3x）
            blink_multiplier_high: 明显疲劳倍数（默认 1.8x）
            head_stability_thresh: 头部稳定性阈值
            window_size: 统计窗口大小
        """
        self.baseline_blink_rate = baseline_blink_rate
        self.blink_multiplier_low = blink_multiplier_low
        self.blink_multiplier_high = blink_multiplier_high
        self.head_stability_thresh = head_stability_thresh
        self.window_size = window_size

        # 累积疲劳分数
        self._cumulative_fatigue: float = 0.0
        self._fatigue_history: Deque[float] = deque(maxlen=100)

        # 最近分析结果
        self._recent_ear_nadirs: Deque[float] = deque(maxlen=window_size)
        self._recent_head_stabilities: Deque[float] = deque(maxlen=window_size)
        self._last_blink_rate: float = 0.0

        # 时间追踪
        self._start_time: Optional[float] = None
        self._last_analysis_time: Optional[float] = None

    def start(self) -> None:
        """开始疲劳追踪"""
        self._start_time = time.time()
        self._last_analysis_time = self._start_time
        self._cumulative_fatigue = 0.0
        self._fatigue_history.clear()
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
    ) -> FatigueAnalysisResult:
        """分析当前疲劳等级

        Args:
            blink_rate: 眨眼频率 (次/分钟)
            ear_nadir: EAR 最低值（闭眼时）
            head_stability: 头部稳定性分数 (0-100)
            avg_ear: 平均 EAR 值

        Returns:
            FatigueAnalysisResult 对象
        """
        self._last_blink_rate = blink_rate

        if ear_nadir is not None:
            self._recent_ear_nadirs.append(ear_nadir)
        if head_stability is not None:
            self._recent_head_stabilities.append(head_stability)

        # 计算平均 EAR 谷值
        avg_ear_nadir = float(np.mean(self._recent_ear_nadirs)) if self._recent_ear_nadirs else 0.1

        # 计算平均头部稳定性
        avg_head_stability = float(np.mean(self._recent_head_stabilities)) if self._recent_head_stabilities else 100.0

        # 计算疲劳分数
        fatigue_score = self._compute_fatigue_score(
            blink_rate=blink_rate,
            ear_nadir=avg_ear_nadir,
            head_stability=avg_head_stability,
        )

        # 累积疲劳（指数移动平均）
        if self._fatigue_history:
            self._cumulative_fatigue = (
                0.95 * self._cumulative_fatigue + 0.05 * fatigue_score
            )
        else:
            self._cumulative_fatigue = fatigue_score

        self._fatigue_history.append(fatigue_score)

        # 确定疲劳等级
        fatigue_level = self._determine_fatigue_level(
            blink_rate=blink_rate,
            head_stability=avg_head_stability,
        )

        return FatigueAnalysisResult(
            fatigue_level=fatigue_level,
            fatigue_score=fatigue_score,
            blink_rate=blink_rate,
            avg_ear_nadir=avg_ear_nadir,
            head_stability=avg_head_stability,
            cumulative_fatigue=self._cumulative_fatigue,
        )

    def _compute_fatigue_score(
        self,
        blink_rate: float,
        ear_nadir: float,
        head_stability: float,
    ) -> float:
        """计算疲劳分数 (0-100)

        基于眨眼频率相对基线的倍数、闭眼深度和头部稳定性
        """
        # 眨眼频率分数 (0-40) — 基于基线的相对变化
        if self.baseline_blink_rate <= 0:
            blink_score = 0.0
        else:
            multiplier = blink_rate / self.baseline_blink_rate

            if multiplier <= 1.0:
                # 眨眼频率未增加，得 0 分
                blink_score = 0.0
            elif multiplier <= self.blink_multiplier_low:
                # 眨眼频率增加 0-30%，线性增长到 20 分
                blink_score = (multiplier - 1.0) / (self.blink_multiplier_low - 1.0) * 20.0
            elif multiplier <= self.blink_multiplier_high:
                # 眨眼频率增加 30-80%，线性增长到 40 分
                blink_score = 20.0 + (multiplier - self.blink_multiplier_low) / (
                    self.blink_multiplier_high - self.blink_multiplier_low
                ) * 20.0
            else:
                # 眨眼频率增加超过 80%，满分 40 分
                blink_score = min(40.0, 40.0 + (multiplier - self.blink_multiplier_high) * 10.0)

        # 闭眼深度分数 (0-30)
        # EAR 越低（闭眼越深），疲劳分数越高
        if ear_nadir >= 0.15:
            eye_score = 0.0
        elif ear_nadir >= 0.08:
            eye_score = (0.15 - ear_nadir) / 0.07 * 30.0
        else:
            eye_score = 30.0

        # 头部稳定性分数 (0-30)
        if head_stability >= self.head_stability_thresh:
            head_score = 0.0
        else:
            head_score = (self.head_stability_thresh - head_stability) / self.head_stability_thresh * 30.0

        return min(100.0, blink_score + eye_score + head_score)

    def _determine_fatigue_level(
        self,
        blink_rate: float,
        head_stability: float,
    ) -> FatigueLevel:
        """确定疲劳等级

        基于眨眼频率相对基线的倍数判定疲劳等级。
        """
        if self.baseline_blink_rate <= 0:
            return FatigueLevel.LOW

        multiplier = blink_rate / self.baseline_blink_rate

        # 高疲劳条件
        if multiplier >= self.blink_multiplier_high and head_stability < self.head_stability_thresh:
            return FatigueLevel.HIGH

        # 中疲劳条件
        if multiplier >= self.blink_multiplier_low or head_stability < self.head_stability_thresh:
            return FatigueLevel.MEDIUM

        # 低疲劳
        return FatigueLevel.LOW

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

        return FatigueRecord(
            session_id=session_id,
            timestamp=timestamp,
            fatigue_level=self._determine_fatigue_level(
                self._last_blink_rate,
                float(np.mean(self._recent_head_stabilities)) if self._recent_head_stabilities else 100.0
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
        self._start_time = None
        self._last_analysis_time = None
        self._last_blink_rate = 0.0

    def get_stats(self) -> dict:
        """获取分析统计信息"""
        multiplier = 0.0
        if self.baseline_blink_rate > 0 and self._last_blink_rate > 0:
            multiplier = self._last_blink_rate / self.baseline_blink_rate

        return {
            "cumulative_fatigue": self._cumulative_fatigue,
            "baseline_blink_rate": self.baseline_blink_rate,
            "last_blink_rate": self._last_blink_rate,
            "blink_multiplier": multiplier,
            "avg_ear_nadir": float(np.mean(self._recent_ear_nadirs)) if self._recent_ear_nadirs else 0.0,
            "avg_head_stability": float(np.mean(self._recent_head_stabilities)) if self._recent_head_stabilities else 100.0,
            "history_size": len(self._fatigue_history),
            "blink_multiplier_thresholds": {
                "low": self.blink_multiplier_low,
                "high": self.blink_multiplier_high,
            },
        }


def create_fatigue_analyzer(baseline_blink_rate: float = 15.0) -> FatigueAnalyzer:
    """工厂函数：创建疲劳分析器

    Args:
        baseline_blink_rate: 个人基线眨眼频率（次/分钟）
    """
    return FatigueAnalyzer(baseline_blink_rate=baseline_blink_rate)

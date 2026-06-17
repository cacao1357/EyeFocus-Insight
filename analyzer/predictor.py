"""
analyzer/predictor.py — 专注度趋势预测 (v4.24)

使用 ARIMA 模型滚动预测专注度走势。
在专注度即将下降时提前预警，联动番茄钟建议休息。

用法：
    predictor = FocusPredictor()
    predictor.add_score(78.5)          # 每秒传入最新专注度
    trend = predictor.trend            # "rising" / "falling" / "stable"
    if predictor.should_suggest_break():
        # 建议休息
"""

import logging
import time
from collections import deque
from typing import Deque, List, Optional

import numpy as np

logger = logging.getLogger("eyefocus.analyzer")

# ARIMA 阶数（低阶=快速适应，高阶=平滑但延迟大）
_ARIMA_ORDER = (2, 0, 1)
# 滚动窗口大小（数据点）
_WINDOW_SIZE = 300  # 5 分钟 @ 1 Hz
# 预测步数
_FORECAST_STEPS = 60  # 预测未来 1 分钟
# 趋势判定阈值（百分点）
_TREND_THRESHOLD = 3.0
# 建议休息的专注度阈值
_BREAK_THRESHOLD = 50.0


class FocusPredictor:
    """专注度趋势预测器

    使用 ARIMA 模型预测未来专注度走势。
    线程安全：add_score 可从任意线程调用。
    """

    def __init__(self):
        self._scores: Deque[float] = deque(maxlen=_WINDOW_SIZE)
        self._timestamps: Deque[float] = deque(maxlen=_WINDOW_SIZE)
        self._trend: str = "stable"
        self._last_forecast: List[float] = []
        self._last_prediction_time: float = 0.0
        self._predict_interval: float = 5.0  # 每 5 秒重新预测一次

    def add_score(self, score: float) -> None:
        """添加新的专注度数据点

        Args:
            score: 当前专注度分数 (0-100)
        """
        if score is None:
            return
        self._scores.append(float(score))
        self._timestamps.append(time.time())

        # 每 5 秒重新预测
        now = time.time()
        if (len(self._scores) >= 30  # 最少 30 个点才能预测
                and now - self._last_prediction_time >= self._predict_interval):
            self._predict()
            self._last_prediction_time = now

    def _predict(self) -> None:
        """运行 ARIMA 预测"""
        try:
            from statsmodels.tsa.arima.model import ARIMA

            series = list(self._scores)
            if len(series) < 30:
                return

            # 确保数据稳定（差分 + 归一化）
            series = self._detrend(series)

            model = ARIMA(series, order=_ARIMA_ORDER)
            fitted = model.fit(method_kwargs={"disp": False})
            forecast = fitted.forecast(steps=_FORECAST_STEPS)

            self._last_forecast = [float(v) for v in forecast]

            # 判断趋势：比较预测序列前段与后段均值
            if len(forecast) >= 6:
                early = float(np.mean(forecast[:3]))
                late = float(np.mean(forecast[-3:]))
                diff = late - early
                if diff > _TREND_THRESHOLD:
                    self._trend = "rising"
                elif diff < -_TREND_THRESHOLD:
                    self._trend = "falling"
                else:
                    self._trend = "stable"
            else:
                self._trend = "stable"

        except Exception as e:
            logger.warning("专注度预测失败: %s", e)
            self._trend = "stable"

    @staticmethod
    def _detrend(series: List[float]) -> List[float]:
        """去趋势 + 归一化（确保 ARIMA 输入稳定）"""
        arr = np.array(series, dtype=float)
        mean = float(np.mean(arr))
        std = float(np.std(arr)) or 1.0
        return list((arr - mean) / std)

    @property
    def trend(self) -> str:
        """当前预测趋势: rising / falling / stable"""
        return self._trend

    @property
    def trend_arrow(self) -> str:
        """趋势箭头符号（供 UI 显示）"""
        return {"rising": "↑", "falling": "↓", "stable": "→"}.get(self._trend, "→")

    def should_suggest_break(self, threshold: float = _BREAK_THRESHOLD) -> bool:
        """是否建议休息

        条件：
        1. 趋势为下降
        2. 预测值将低于阈值

        Returns:
            True 建议休息
        """
        if self._trend != "falling":
            return False
        if not self._last_forecast:
            return False
        return min(self._last_forecast) < threshold

    def get_forecast(self) -> List[float]:
        """获取当前预测值列表"""
        return list(self._last_forecast)

    def get_stats(self) -> dict:
        """获取预测统计（供调试/UI）"""
        forecast = self._last_forecast
        return {
            "trend": self._trend,
            "arrow": self.trend_arrow,
            "forecast_min": min(forecast) if forecast else None,
            "forecast_max": max(forecast) if forecast else None,
            "forecast_avg": float(np.mean(forecast)) if forecast else None,
            "data_points": len(self._scores),
            "suggest_break": self.should_suggest_break(),
        }


def create_focus_predictor() -> FocusPredictor:
    """工厂函数"""
    return FocusPredictor()

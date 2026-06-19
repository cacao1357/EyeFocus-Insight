"""analyzer/insights/temporal.py — 时序分解与高效时段分析 (v4.1)

对聚合到小时的专注度时序进行 STL 分解，提取日内模式和高低效时段。

降级策略：
  - statsmodels 未安装 → 降级到 histogram 方案（不报错）
  - 数据不足（< 7 天）→ histogram 方案
  - 分解失败 → histogram 方案
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("eyefocus.insights.temporal")


@dataclass
class TemporalResult:
    """时序分解结果。"""
    detected: bool
    n_days: int                        # 覆盖天数
    method: str                        # "stl" / "histogram"
    # 高效时段（列表，如 ["09-11", "15-16"]）
    peak_hours: List[str]
    # 低效时段
    low_hours: List[str]
    # 日内模式：24h 均值
    hourly_pattern: List[float]
    # 星期模式（可选）
    daily_pattern: List[float] = field(default_factory=list)


def _try_import_statsmodels():
    """尝试导入 statsmodels。"""
    try:
        from statsmodels.tsa.seasonal import STL
        return STL
    except ImportError:
        logger.warning("statsmodels 未安装，STL 分解不可用，降级到 histogram")
        return None


def _build_hourly_series(db, session_ids: List[str]) -> Optional[pd.Series]:
    """从 focus_records 构建按小时聚合的专注度时序。

    Args:
        db: DatabaseManager
        session_ids: 要分析的 session_id 列表

    Returns:
        pd.Series 按小时 index，或 None
    """
    all_data = []
    for sid in session_ids:
        with db.get_cursor() as cur:
            cur.execute("""
                SELECT window_start, focus_score
                FROM focus_records
                WHERE session_id = ? AND focus_score IS NOT NULL
                ORDER BY window_start
            """, (sid,))
            for row in cur.fetchall():
                all_data.append((row["window_start"], row["focus_score"]))

    if not all_data:
        return None

    df = pd.DataFrame(all_data, columns=["ts", "focus"])
    df["ts"] = pd.to_datetime(df["ts"], unit="s")
    df.set_index("ts", inplace=True)
    # 按小时聚合
    hourly = df.resample("1h").mean()
    return hourly["focus"]


def _histogram_analysis(hourly: pd.Series) -> TemporalResult:
    """基于直方图的高/低效时段分析（降级方案）。"""
    if len(hourly) < 6:
        return TemporalResult(detected=False, n_days=0, method="histogram",
                              peak_hours=[], low_hours=[], hourly_pattern=[])

    # 生成 24h 均值模式
    hourly_idx = hourly.index.hour
    hourly_pattern = []
    for h in range(24):
        mask = hourly_idx == h
        vals = hourly[mask].dropna()
        hourly_pattern.append(float(vals.mean()) if len(vals) > 0 else 0.0)

    arr = np.array(hourly_pattern)
    if arr.max() - arr.min() < 5:
        return TemporalResult(detected=False, n_days=len(hourly) / 24,
                              method="histogram", peak_hours=[], low_hours=[],
                              hourly_pattern=hourly_pattern)

    threshold_high = np.percentile(arr[arr > 0], 80) if np.any(arr > 0) else 60
    threshold_low = np.percentile(arr[arr > 0], 20) if np.any(arr > 0) else 40

    peak_hours = _merge_consecutive([h for h in range(24)
                                     if hourly_pattern[h] >= threshold_high and hourly_pattern[h] > 0])
    low_hours = _merge_consecutive([h for h in range(24)
                                    if hourly_pattern[h] <= threshold_low and hourly_pattern[h] > 0])

    n_days = max(1, int(len(hourly) / 24))
    return TemporalResult(
        detected=True,
        n_days=n_days,
        method="histogram",
        peak_hours=peak_hours,
        low_hours=low_hours,
        hourly_pattern=[round(v, 1) for v in hourly_pattern],
    )


def _merge_consecutive(hours: List[int]) -> List[str]:
    """将连续小时合并为范围表示，如 [9,10,11] → ["09-11"]。"""
    if not hours:
        return []
    hours = sorted(set(hours))
    ranges = []
    start = hours[0]
    end = hours[0]
    for h in hours[1:]:
        if h == end + 1:
            end = h
        else:
            ranges.append(f"{start:02d}-{end:02d}" if start != end else f"{start:02d}")
            start = end = h
    ranges.append(f"{start:02d}-{end:02d}" if start != end else f"{start:02d}")
    return ranges


def analyze_temporal(db, session_ids: List[str]) -> TemporalResult:
    """运行时序分析。

    Args:
        db: DatabaseManager 实例
        session_ids: 要分析的 session_id 列表

    Returns:
        TemporalResult
    """
    if not session_ids:
        return TemporalResult(detected=False, n_days=0, method="histogram",
                              peak_hours=[], low_hours=[], hourly_pattern=[])

    hourly = _build_hourly_series(db, session_ids)
    if hourly is None or len(hourly) < 6:
        return TemporalResult(detected=False, n_days=0, method="histogram",
                              peak_hours=[], low_hours=[], hourly_pattern=[])

    # 尝试 STL
    STL = _try_import_statsmodels()
    n_days = len(hourly) / 24

    if STL is not None and n_days >= 7:
        try:
            # STL 需要至少 2 个周期
            period = 24  # 24h 周期
            if len(hourly) >= period * 2:
                stl = STL(hourly.fillna(method="ffill").values,
                         period=period,
                         robust=True).fit()
                # 从趋势+残差中提取模式
                trend = stl.trend
                seasonal = stl.seasonal

                # 取最后一个完整周期的季节性模式 + 趋势为日内模式
                if len(seasonal) >= period:
                    # 日内模式 = 趋势均值 + 季节性
                    trend_mean = np.mean(trend[-period:]) if len(trend) >= period else np.mean(trend)
                    intraday = seasonal[-period:] + trend_mean
                else:
                    intraday = seasonal[:period]

                intraday = np.clip(intraday, 0, 100)
                hourly_pattern = [float(v) for v in intraday]

                threshold_high = np.percentile(hourly_pattern, 70)
                threshold_low = np.percentile(hourly_pattern, 30)

                peak_hours = _merge_consecutive([h for h in range(24)
                                                 if hourly_pattern[h] >= threshold_high])
                low_hours = _merge_consecutive([h for h in range(24)
                                                if hourly_pattern[h] <= threshold_low])

                return TemporalResult(
                    detected=True,
                    n_days=max(1, int(n_days)),
                    method="stl",
                    peak_hours=peak_hours,
                    low_hours=low_hours,
                    hourly_pattern=[round(v, 1) for v in hourly_pattern],
                )

        except Exception as e:
            logger.warning("STL 分解失败，降级到 histogram: %s", e)

    # 降级到 histogram
    return _histogram_analysis(hourly)

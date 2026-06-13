"""analyzer/insights/changepoint.py — PELT 变点检测 (v4.1)

检测专注度时序中的关键转折点（专注度突降/回升时刻）。

方法：PELT（Pruned Exact Linear Time）
依赖：ruptures >= 1.1（pip 离线包）

降级策略：
  - ruptures 未安装 → 返回 None（不报错）
  - 数据点不足 → 返回 None
  - 检测失败 → 返回 None（try/except 隔离）
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger("eyefocus.insights.changepoint")


@dataclass
class ChangepointResult:
    """变点检测结果。"""
    detected: bool                       # 是否检测到变点
    change_indices: List[int]            # 变点位置（数据索引）
    change_timestamps: List[float]        # 变点时间戳
    segment_means: List[float]           # 各段均值
    n_changepoints: int                  # 变点数量
    penalty: float = 10.0                # 使用的 penalty 值
    # 以下字段只在有关键变点时填充
    earliest_drop_time: Optional[float] = None   # 最早下降段起始时间
    earliest_drop_pre_mean: Optional[float] = None  # 下降前均值
    earliest_drop_post_mean: Optional[float] = None # 下降后均值
    recovery_count: int = 0              # 回升变点数量


@dataclass
class FocusTimeSeries:
    """专注度时序输入。"""
    timestamps: List[float]      # Unix 时间戳
    values: List[float]          # 对应的 focus_score
    session_id: str = ""


def _try_import_ruptures():
    """尝试导入 ruptures，失败时不报错。"""
    try:
        import ruptures as rpt
        return rpt
    except ImportError:
        logger.warning("ruptures 未安装，变点检测不可用")
        return None


def detect_changepoints(series: FocusTimeSeries,
                        penalty: Optional[float] = None,
                        min_segment_length: int = 5) -> ChangepointResult:
    """对专注度时序运行 PELT 变点检测。

    Args:
        series: 专注度时序
        penalty: PELT penalty 参数（自动估计为 std(values) * 2.5）
        min_segment_length: 最短段长

    Returns:
        ChangepointResult（检测失败时 detected=False 且其余字段为默认值）
    """
    rpt = _try_import_ruptures()
    if rpt is None:
        return ChangepointResult(detected=False, change_indices=[], change_timestamps=[],
                                  segment_means=[], n_changepoints=0)

    values = np.array(series.values, dtype=float)
    n = len(values)

    if n < min_segment_length * 3:
        logger.debug("数据点不足（%d），跳过变点检测", n)
        return ChangepointResult(detected=False, change_indices=[], change_timestamps=[],
                                  segment_means=[], n_changepoints=0)

    try:
        if penalty is None:
            # 自动估计 penalty：信号标准差 × 2.5，至少 5.0
            penalty = max(5.0, float(np.std(values)) * 2.5)

        # PELT 检测
        algo = rpt.Pelt(model="rbf", min_size=min_segment_length).fit(values)
        result = algo.predict(pen=penalty)

        # 过滤：去掉首尾边界（ruptures 可能包含 0 和 n）
        change_pts = sorted(set(result) - {0, n})
        # 再按最小段长过滤
        filtered = []
        prev = 0
        for cp in change_pts:
            if cp - prev >= min_segment_length:
                filtered.append(cp)
                prev = cp

        if not filtered:
            return ChangepointResult(detected=False, change_indices=[], change_timestamps=[],
                                      segment_means=[], n_changepoints=0)

        # 计算各段均值
        segments = []
        prev = 0
        for cp in filtered:
            segments.append(float(np.mean(values[prev:cp])))
            prev = cp
        segments.append(float(np.mean(values[prev:])))  # 末段

        # 映射到时间戳
        timestamps_arr = np.array(series.timestamps)
        change_ts = [float(timestamps_arr[min(cp, len(timestamps_arr) - 1)]) for cp in filtered]

        # 找最早的下降段（段均值比前一段低 > 10%）
        earliest_drop_time = None
        earliest_drop_pre = None
        earliest_drop_post = None
        recovery_count = 0
        for i in range(1, len(segments)):
            if segments[i] < segments[i - 1] * 0.9:
                if earliest_drop_time is None:
                    earliest_drop_time = change_ts[i - 1] if i - 1 < len(change_ts) else None
                    earliest_drop_pre = segments[i - 1]
                    earliest_drop_post = segments[i]
            elif segments[i] > segments[i - 1] * 1.1 and i > 1:
                recovery_count += 1

        return ChangepointResult(
            detected=True,
            change_indices=filtered,
            change_timestamps=change_ts,
            segment_means=[round(s, 2) for s in segments],
            n_changepoints=len(filtered),
            penalty=round(penalty, 2),
            earliest_drop_time=earliest_drop_time,
            earliest_drop_pre_mean=round(earliest_drop_pre, 2) if earliest_drop_pre else None,
            earliest_drop_post_mean=round(earliest_drop_post, 2) if earliest_drop_post else None,
            recovery_count=recovery_count,
        )

    except Exception as e:
        logger.warning("PELT 变点检测失败: %s", e)
        return ChangepointResult(detected=False, change_indices=[], change_timestamps=[],
                                  segment_means=[], n_changepoints=0)

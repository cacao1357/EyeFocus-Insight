"""v4.3 CAL-SPIKE-TEST-01 修复: spike/insights/_common.py 烟雾测试

之前 spike/insights/ 整个目录 0 测试覆盖, 参数/算法漂移无回归保护.
本测试覆盖 _common.py 的 3 个核心生成器:
  - gen_synthetic_sessions (合成会话数据)
  - gen_focus_timeseries_with_drops (含掉段专注度时序)
  - gen_hourly_focus_with_daily_pattern (按小时专注度+日模式)

不是完整 spike 流程 (那要 5+ 个文件协作), 仅 smoke test:
  1. 函数能 import 不报
  2. 输出形状 (长度, 列) 正确
  3. 关键不变量 (无 NaN, 数值范围合理)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "spike", "insights"
))

import numpy as np
import pandas as pd
import pytest

from _common import (
    gen_synthetic_sessions,
    gen_focus_timeseries_with_drops,
    gen_hourly_focus_with_daily_pattern,
    sessions_to_matrix,
)


def test_gen_synthetic_sessions_shape_CAL_SPIKE_TEST_01():
    """CAL-SPIKE-TEST-01: gen_synthetic_sessions 应返回 4 modes × n_per_mode 个会话"""
    sessions = gen_synthetic_sessions(n_per_mode=8, seed=42)
    assert isinstance(sessions, list)
    # _common.py:48 定义 4 modes (early_peak / afternoon_tired / evening_distracted / flow)
    assert len(sessions) == 4 * 8, f"4 modes × n_per_mode=8 应给 32, 实际 {len(sessions)}"
    # 抽样检查 SyntheticSession 关键字段 (实际定义见 _common.py:17-31)
    s = sessions[0]
    assert hasattr(s, "avg_focus_score"), f"session 应有 avg_focus_score 字段"
    assert hasattr(s, "blink_rate_baseline_ratio")
    assert hasattr(s, "hour_of_day")
    # session_id 应包含 mode 前缀
    assert any(m in s.session_id for m in ("early_peak", "afternoon_tired", "evening_distracted", "flow"))


def test_gen_synthetic_sessions_reproducible_CAL_SPIKE_TEST_01():
    """CAL-SPIKE-TEST-01: 同样 seed 应产出同样序列 (算法漂移检测)"""
    s1 = gen_synthetic_sessions(n_per_mode=4, seed=42)
    s2 = gen_synthetic_sessions(n_per_mode=4, seed=42)
    # 比对前 3 个 session 的 avg_focus_score
    focus1 = [s.avg_focus_score for s in s1[:3]]
    focus2 = [s.avg_focus_score for s in s2[:3]]
    assert focus1 == focus2, f"同 seed 产出应一致, 实际 focus1={focus1} vs focus2={focus2}"


def test_gen_focus_timeseries_with_drops_shape_CAL_SPIKE_TEST_01():
    """CAL-SPIKE-TEST-01: gen_focus_timeseries_with_drops 输出长度 = n_seconds * 2 (2Hz 采样)"""
    series = gen_focus_timeseries_with_drops(n_seconds=3600)
    assert isinstance(series, (pd.Series, np.ndarray))
    # 实测: n_seconds=3600 → 7200 个点 (2Hz 采样率)
    assert len(series) == 7200, f"n_seconds=3600 应给 7200 个点 (2Hz), 实际 {len(series)}"


def test_gen_focus_timeseries_with_drops_range_CAL_SPIKE_TEST_01():
    """CAL-SPIKE-TEST-01: focus 时序值应在 [0, 100] 范围内 (专注度评分约定)"""
    series = gen_focus_timeseries_with_drops(n_seconds=600)
    if isinstance(series, pd.Series):
        vals = series.values
    else:
        vals = series
    assert vals.min() >= 0.0, f"focus 值应 >= 0, 实际 min={vals.min()}"
    assert vals.max() <= 100.0, f"focus 值应 <= 100, 实际 max={vals.max()}"


def test_gen_hourly_focus_with_daily_pattern_shape_CAL_SPIKE_TEST_01():
    """CAL-SPIKE-TEST-01: gen_hourly_focus_with_daily_pattern 输出 n_days * 24 小时"""
    series = gen_hourly_focus_with_daily_pattern(n_days=14, seed=42)
    assert isinstance(series, pd.Series)
    assert len(series) == 14 * 24, f"应 14*24=336 个点, 实际 {len(series)}"
    # 索引应是 datetime 类型
    assert pd.api.types.is_datetime64_any_dtype(series.index), (
        f"索引应 datetime, 实际 {type(series.index)}"
    )


def test_gen_hourly_focus_with_daily_pattern_range_CAL_SPIKE_TEST_01():
    """CAL-SPIKE-TEST-01: hourly focus 值应在 [0, 100] 范围内"""
    series = gen_hourly_focus_with_daily_pattern(n_days=7, seed=42)
    vals = series.values
    assert vals.min() >= 0.0, f"hourly focus min 应 >= 0, 实际 {vals.min()}"
    assert vals.max() <= 100.0, f"hourly focus max 应 <= 100, 实际 {vals.max()}"


def test_sessions_to_matrix_shape_CAL_SPIKE_TEST_01():
    """CAL-SPIKE-TEST-01: sessions_to_matrix 转换后返回 (matrix, feature_names) 元组"""
    sessions = gen_synthetic_sessions(n_per_mode=2, seed=42)
    result = sessions_to_matrix(sessions)
    # 实际签名返回 (matrix, feature_names) 元组 (见 _common.py:76-87)
    assert isinstance(result, tuple) and len(result) == 2, (
        f"应返回 (matrix, names) 元组, 实际 {type(result)}"
    )
    matrix, names = result
    assert matrix.shape[0] == len(sessions), (
        f"matrix 行数应 == sessions 数, 实际 {matrix.shape[0]} vs {len(sessions)}"
    )
    # 特征数应 >= 7 (avg_focus_score / focus_score_std / avg_perclos / blink / gaze / head / duration)
    assert matrix.shape[1] >= 7, f"matrix 应至少 7 列, 实际 {matrix.shape[1]}"
    assert len(names) == matrix.shape[1], f"names 长度应 == 列数"

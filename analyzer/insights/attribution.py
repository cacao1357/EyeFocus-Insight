"""analyzer/insights/attribution.py — 关联分析引擎 (v4.1)

使用统计检验（t-test / ANOVA）分析各因素与专注度的关联。
最终输出至少 1 条 p < 0.05 + Cohen's d > 0.3 的发现。

降级策略：
  - scipy 未安装 → 返回空列表
  - 数据不足 → 跳过特定检验
  - 所有检验无显著发现 → 返回空列表（不报错）
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger("eyefocus.insights.attribution")


@dataclass
class AttributionFinding:
    """单条关联发现。"""
    factor_name: str                    # 因子名（中文）
    test_type: str                      # "t-test" / "ANOVA" / "correlation"
    p_value: float                      # p 值
    effect_size: float                  # Cohen's d 或 eta-squared
    direction: str                      # 关联方向描述
    summary: str                        # 一句话总结


def _try_import_scipy():
    """尝试导入 scipy.stats。"""
    try:
        from scipy import stats as _stats
        return _stats
    except ImportError:
        logger.warning("scipy 未安装，关联分析不可用")
        return None


def _cohens_d(x: np.ndarray, y: np.ndarray) -> float:
    """计算 Cohen's d。"""
    n1, n2 = len(x), len(y)
    s1, s2 = np.var(x, ddof=1), np.var(y, ddof=1)
    pooled = np.sqrt(((n1 - 1) * s1 + (n2 - 1) * s2) / (n1 + n2 - 2))
    if pooled < 1e-8:
        return 0.0
    return (np.mean(x) - np.mean(y)) / pooled


def _analyze_time_of_day(X_hour: np.ndarray, y: np.ndarray) -> Optional[AttributionFinding]:
    """分析时段（上下午）与专注度的关联（t-test）。"""
    stats = _try_import_scipy()
    if stats is None:
        return None

    # 上午 (6-12) vs 下午 (12-18) vs 晚上 (18-24)
    morning = y[(X_hour >= 6) & (X_hour < 12)]
    afternoon = y[(X_hour >= 12) & (X_hour < 18)]
    evening = y[(X_hour >= 18) | (X_hour < 6)]

    if len(morning) < 3 or len(afternoon) < 3:
        return None

    try:
        t_stat, p_val = stats.ttest_ind(morning, afternoon, equal_var=False)
        d = _cohens_d(morning, afternoon)
        if p_val < 0.05 and abs(d) > 0.3:
            better = "上午" if np.mean(morning) > np.mean(afternoon) else "下午"
            return AttributionFinding(
                factor_name="时段（上下午）",
                test_type="t-test",
                p_value=round(p_val, 4),
                effect_size=round(abs(d), 3),
                direction=f"{better}专注度更高",
                summary=f"上下午专注度差异显著 (p={p_val:.3f}, d={abs(d):.2f})，{better}表现更好",
            )
    except Exception as e:
        logger.debug("时段 t-test 失败: %s", e)

    return None


def _analyze_duration(X_dur: np.ndarray, y: np.ndarray) -> Optional[AttributionFinding]:
    """分析会话时长与专注度的相关。"""
    stats = _try_import_scipy()
    if stats is None or len(X_dur) < 10:
        return None

    try:
        r, p_val = stats.pearsonr(X_dur, y)
        if p_val < 0.05 and abs(r) > 0.3:
            direction = "长时间会话专注度更高" if r > 0 else "短时间会话专注度更高"
            return AttributionFinding(
                factor_name="会话时长",
                test_type="correlation",
                p_value=round(p_val, 4),
                effect_size=round(abs(r), 3),
                direction=direction,
                summary=f"会话时长与专注度相关 (r={r:.2f}, p={p_val:.3f})",
            )
    except Exception as e:
        logger.debug("时长相关性分析失败: %s", e)

    return None


def _analyze_blink_vs_focus(X_blink: np.ndarray, y: np.ndarray) -> Optional[AttributionFinding]:
    """分析眨眼频率与专注度的关联。"""
    stats = _try_import_scipy()
    if stats is None or len(X_blink) < 10:
        return None

    try:
        r, p_val = stats.pearsonr(X_blink, y)
        if p_val < 0.05 and abs(r) > 0.2:
            direction = "眨眼频率正常时专注度更高" if r < 0 else "眨眼频率高时专注度更高"
            return AttributionFinding(
                factor_name="眨眼频率",
                test_type="correlation",
                p_value=round(p_val, 4),
                effect_size=round(abs(r), 3),
                direction=direction,
                summary=f"眨眼频率与专注度相关 (r={r:.2f}, p={p_val:.3f})",
            )
    except Exception as e:
        logger.debug("眨眼-专注度分析失败: %s", e)

    return None


def _analyze_gaze_away(X_gaze: np.ndarray, y: np.ndarray) -> Optional[AttributionFinding]:
    """分析视线偏离与专注度的关联。"""
    stats = _try_import_scipy()
    if stats is None or len(X_gaze) < 5:
        return None

    # 二分：高偏离 vs 低偏离
    median = np.median(X_gaze)
    high = y[X_gaze > median]
    low = y[X_gaze <= median]

    if len(high) < 3 or len(low) < 3:
        return None

    try:
        t_stat, p_val = stats.ttest_ind(high, low, equal_var=False)
        d = _cohens_d(low, high)
        if p_val < 0.05 and abs(d) > 0.3:
            return AttributionFinding(
                factor_name="视线偏离",
                test_type="t-test",
                p_value=round(p_val, 4),
                effect_size=round(abs(d), 3),
                direction="视线偏离少时专注度更高",
                summary=f"视线偏离程度与专注度显著相关 (p={p_val:.3f}, d={abs(d):.2f})",
            )
    except Exception as e:
        logger.debug("视线偏离分析失败: %s", e)

    return None


def analyze_attributions(features, X: np.ndarray,
                         feature_names: List[str]) -> List[AttributionFinding]:
    """运行完整的关联分析 pipeline。

    Args:
        features: SessionFeatures 列表
        X: 特征矩阵 (n, m)
        feature_names: 特征名列表

    Returns:
        AttributionFinding 列表（至少 1 条 p<0.05+d>0.3 的发现时非空）
    """
    if len(features) < 5:
        logger.debug("session 数不足，跳过关联分析")
        return []

    stats = _try_import_scipy()
    if stats is None:
        return []

    # y = avg_focus_score
    y = X[:, feature_names.index("avg_focus_score")]

    findings = []

    # 时段
    hour_idx = feature_names.index("hour_of_day")
    finding = _analyze_time_of_day(X[:, hour_idx], y)
    if finding:
        findings.append(finding)

    # 时长
    dur_idx = feature_names.index("duration_minutes")
    finding = _analyze_duration(X[:, dur_idx], y)
    if finding:
        findings.append(finding)

    # 眨眼频率比
    blink_idx = feature_names.index("blink_rate_ratio")
    finding = _analyze_blink_vs_focus(X[:, blink_idx], y)
    if finding:
        findings.append(finding)

    # 视线偏离
    gaze_idx = feature_names.index("gaze_away_ratio")
    finding = _analyze_gaze_away(X[:, gaze_idx], y)
    if finding:
        findings.append(finding)

    # 疲劳
    fatigue_idx = feature_names.index("fatigue_severe_ratio")
    finding = _analyze_gaze_away(X[:, fatigue_idx], y)
    if finding:
        findings.append(
            AttributionFinding(
                factor_name="疲劳程度",
                test_type=finding.test_type,
                p_value=finding.p_value,
                effect_size=finding.effect_size,
                direction="疲劳度低时专注度更高",
                summary=finding.summary.replace("视线偏离", "疲劳程度"),
            )
        )

    return findings

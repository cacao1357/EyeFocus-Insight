"""analyzer/insights/anomaly.py — 异常检测与归因 (v4.1)

基于 IsolationForest 检测异常 session，并输出 top-3 因子（z-score 归因）。

降级策略：
  - sklearn 未安装 → 返回空结果
  - session 数 < 5 → 跳过
  - 检测失败 → 返回空结果
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger("eyefocus.insights.anomaly")


@dataclass
class AnomalyResult:
    """异常检测结果。"""
    detected: bool                      # 是否检测到异常（整体）
    n_sessions: int                     # 输入 session 总数
    anomaly_count: int                  # 异常 session 数
    anomaly_sessions: List[str]         # 异常 session_id 列表
    anomaly_scores: List[float]         # 异常分数（越小越异常）
    top_factors: List[str]              # top-3 因子（中文描述）


@dataclass
class FactorAttribution:
    """单因子的归因信息。"""
    feature_name: str
    z_score: float            # 偏离均值的 z-score
    direction: str            # "偏高" / "偏低"
    chinese_label: str        # 中文标签


# 特征中文名映射
FEATURE_CN = {
    "avg_focus_score": "平均专注度",
    "focus_score_std": "专注度波动",
    "avg_perclos": "PERCLOS",
    "blink_rate_ratio": "眨眼频率比",
    "gaze_away_ratio": "视线偏离比",
    "head_movement": "头部运动",
    "duration_minutes": "会话时长",
    "hour_of_day": "时段",
    "fatigue_severe_ratio": "重度疲劳比",
    "light_dark_ratio": "暗光比",
}


def _try_import_sklearn():
    """尝试导入 sklearn，失败时不报错。"""
    try:
        from sklearn.ensemble import IsolationForest
        return IsolationForest
    except ImportError:
        logger.warning("sklearn 未安装，异常检测不可用")
        return None


def _compute_z_scores(X: np.ndarray, feature_names: List[str],
                      anomaly_indices: np.ndarray) -> List[FactorAttribution]:
    """对异常 session 计算各特征的 z-score 归因。

    Args:
        X: 特征矩阵 (n, m)
        feature_names: 特征名列表
        anomaly_indices: 异常样本的行索引

    Returns:
        每个异常 session 的 top factor 列表
    """
    if len(anomaly_indices) == 0:
        return []

    means = np.mean(X, axis=0)
    stds = np.std(X, axis=0) + 1e-8

    attributions = []
    for idx in anomaly_indices:
        x = X[idx]
        z_scores = (x - means) / stds

        # 为每个特征计算归因
        factors = []
        for j, name in enumerate(feature_names):
            cn = FEATURE_CN.get(name, name)
            z = float(z_scores[j])
            if abs(z) > 0.5:  # 只保留有意义的偏离
                direction = "偏高" if z > 0 else "偏低"
                factors.append(FactorAttribution(
                    feature_name=name,
                    z_score=round(z, 2),
                    direction=direction,
                    chinese_label=f"{cn}{direction}(z={z:.1f})",
                ))

        # 按 |z-score| 排序取 top-3
        factors.sort(key=lambda f: abs(f.z_score), reverse=True)
        attributions.extend(factors[:3])

    return attributions


def detect_anomalies(X: np.ndarray, feature_names: List[str],
                     session_ids: List[str],
                     contamination: float = 0.1,
                     random_state: int = 42) -> AnomalyResult:
    """基于 IsolationForest 检测异常 session。

    Args:
        X: 特征矩阵 (n_sessions, n_features)
        feature_names: 特征名列表
        session_ids: session_id 列表（与 X 的行一一对应）
        contamination: 预期异常比例（默认 10%）
        random_state: 随机种子

    Returns:
        AnomalyResult
    """
    IsolationForest = _try_import_sklearn()
    if IsolationForest is None:
        return AnomalyResult(detected=False, n_sessions=0, anomaly_count=0,
                              anomaly_sessions=[], anomaly_scores=[], top_factors=[])

    n = X.shape[0]
    if n < 5:
        logger.debug("session 数不足（%d），跳过异常检测", n)
        return AnomalyResult(detected=False, n_sessions=n, anomaly_count=0,
                              anomaly_sessions=[], anomaly_scores=[], top_factors=[])

    try:
        model = IsolationForest(contamination=contamination,
                                random_state=random_state,
                                n_estimators=100)
        preds = model.fit_predict(X)
        scores = model.decision_function(X)

        # preds: -1 = anomaly, 1 = normal
        anomaly_mask = preds == -1
        anomaly_indices = np.where(anomaly_mask)[0]

        anomaly_sessions = [session_ids[i] for i in anomaly_indices]
        anomaly_scores_vals = [float(scores[i]) for i in anomaly_indices]

        # z-score 归因
        factors = _compute_z_scores(X, feature_names, anomaly_indices)

        # 合并成 top-3 全局因子（去重取最高 |z|）
        seen = set()
        top_factors = []
        for f in factors:
            key = f.feature_name
            if key not in seen:
                seen.add(key)
                top_factors.append(f.chinese_label)
            if len(top_factors) >= 3:
                break

        return AnomalyResult(
            detected=len(anomaly_indices) > 0,
            n_sessions=n,
            anomaly_count=int(len(anomaly_indices)),
            anomaly_sessions=anomaly_sessions,
            anomaly_scores=[round(s, 4) for s in anomaly_scores_vals],
            top_factors=top_factors,
        )

    except Exception as e:
        logger.warning("IsolationForest 异常检测失败: %s", e)
        return AnomalyResult(detected=False, n_sessions=n, anomaly_count=0,
                              anomaly_sessions=[], anomaly_scores=[], top_factors=[])

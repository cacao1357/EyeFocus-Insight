"""analyzer/insights/patterns.py — 聚类工作模式分析 (v4.1)

基于 KMeans + StandardScaler 自动识别用户的工作模式。
使用 silhouette 系数自动选择最佳 k。

降级策略：
  - sklearn 未安装 → 返回 None
  - session 数 < n_clusters × 2 → 跳过
  - 检测失败 → 返回 None
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("eyefocus.insights.patterns")


@dataclass
class PatternResult:
    """聚类结果。"""
    detected: bool
    n_sessions: int
    n_clusters: int                    # 最终选出的 k
    silhouette: float                  # 轮廓系数
    labels: List[int]                  # 每个 session 的聚类标签
    cluster_sizes: List[int]           # 各簇大小
    cluster_centers: List[List[float]]  # 各簇中心（标准化的）
    best_k: int                        # 对齐度最高的 k
    k_evaluation: Dict[str, dict]      # 各 k 的评估指标
    # 简化的标签描述
    pattern_labels: Dict[int, str] = field(default_factory=dict)


# 自动标签描述
PATTERN_NAMES = {
    0: "高效模式",
    1: "常规模式",
    2: "低效模式",
    3: "分心模式",
    4: "疲劳模式",
    5: "短时模式",
}


def _try_import_sklearn():
    """尝试导入 sklearn 聚类相关组件。"""
    try:
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
        from sklearn.metrics import silhouette_score
        return KMeans, StandardScaler, silhouette_score
    except ImportError:
        logger.warning("sklearn 未安装，聚类分析不可用")
        return None, None, None


def _evaluate_k(X_scaled: np.ndarray, k_range: Tuple[int, int],
                random_state: int, session_ids: List[str]) -> dict:
    """评估各 k 值，返回 silhouette 和标签。"""
    KMeans, StandardScaler, silhouette_score = _try_import_sklearn()
    if KMeans is None:
        return {"error": "sklearn not available"}

    results = {}
    for k in range(k_range[0], k_range[1] + 1):
        model = KMeans(n_clusters=k, n_init=10, random_state=random_state)
        labels = model.fit_predict(X_scaled)
        sc = float(silhouette_score(X_scaled, labels))
        results[str(k)] = {
            "silhouette": round(sc, 4),
            "labels": [int(l) for l in labels],
            "inertia": float(model.inertia_),
        }
    return results


def analyze_patterns(X: np.ndarray, feature_names: List[str],
                     session_ids: List[str],
                     target_k: int = 4,
                     k_range: Tuple[int, int] = (2, 6),
                     silhouette_threshold: float = 0.25,
                     random_state: int = 42) -> PatternResult:
    """运行聚类分析。

    Args:
        X: 特征矩阵 (n_sessions, n_features)
        feature_names: 特征名列表
        session_ids: session_id 列表
        target_k: 目标聚类数
        k_range: 评估的 k 范围
        silhouette_threshold: silhouette 门禁
        random_state: 随机种子

    Returns:
        PatternResult
    """
    KMeans, StandardScaler, silhouette_score = _try_import_sklearn()
    if KMeans is None:
        return PatternResult(detected=False, n_sessions=0, n_clusters=0,
                              silhouette=0.0, labels=[], cluster_sizes=[],
                              cluster_centers=[], best_k=0, k_evaluation={})

    n = X.shape[0]
    if n < k_range[0] * 2:
        logger.debug("session 数不足（%d），跳过聚类分析", n)
        return PatternResult(detected=False, n_sessions=n, n_clusters=0,
                              silhouette=0.0, labels=[], cluster_sizes=[],
                              cluster_centers=[], best_k=0, k_evaluation={})

    try:
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # 评估各 k
        eval_results = _evaluate_k(X_scaled, k_range, random_state, session_ids)

        # 选最佳 k：优先 silhouette 最高的
        k_scores = {}
        for k_str, v in eval_results.items():
            k_scores[int(k_str)] = v["silhouette"]
        best_k_by_sil = max(k_scores, key=k_scores.get)

        # 使用 target_k 或 best_k（如果 best_k 的 silhouette 显著更好）
        use_k = target_k
        if k_scores.get(use_k, 0) < silhouette_threshold and k_scores.get(best_k_by_sil, 0) > silhouette_threshold:
            use_k = best_k_by_sil

        # 最终模型
        model = KMeans(n_clusters=use_k, n_init=10, random_state=random_state)
        labels = model.fit_predict(X_scaled)
        silhouette = float(silhouette_score(X_scaled, labels))

        # 整理结果
        cluster_sizes = [int(np.sum(labels == i)) for i in range(use_k)]
        cluster_centers = [model.cluster_centers_[i].tolist() for i in range(use_k)]

        # 按簇大小排序，给标签名
        sorted_clusters = sorted(range(use_k), key=lambda i: cluster_sizes[i], reverse=True)
        pattern_labels = {}
        for rank, c in enumerate(sorted_clusters):
            name = PATTERN_NAMES.get(rank, f"模式{rank + 1}")
            pattern_labels[int(c)] = f"{name}({cluster_sizes[c]}次)"

        # k_evaluation 简化（只保留数值，不保留 labels 数组）
        k_eval_simple = {}
        for k_str, v in eval_results.items():
            k_eval_simple[k_str] = {
                "silhouette": v["silhouette"],
                "inertia": v["inertia"],
            }

        return PatternResult(
            detected=silhouette > silhouette_threshold,
            n_sessions=n,
            n_clusters=use_k,
            silhouette=round(silhouette, 4),
            labels=[int(l) for l in labels],
            cluster_sizes=cluster_sizes,
            cluster_centers=cluster_centers,
            best_k=best_k_by_sil,
            k_evaluation=k_eval_simple,
            pattern_labels=pattern_labels,
        )

    except Exception as e:
        logger.warning("KMeans 聚类分析失败: %s", e)
        return PatternResult(detected=False, n_sessions=n, n_clusters=0,
                              silhouette=0.0, labels=[], cluster_sizes=[],
                              cluster_centers=[], best_k=0, k_evaluation={})

"""analyzer/insights/ — 离线分析子系统 (v4.1)

基于 SQLite 历史会话数据，在会话结束时一次性运行，生成：
  - 聚类工作模式（KMeans + silhouette）
  - 变点检测（PELT）
  - 异常检测（IsolationForest + 归因）
  - 时序分解（STL + histogram 降级）
  - 关联分析（t-test + ANOVA + Cohen's d）

用法：
    from analyzer.insights import run_pipeline
    result = run_pipeline(db_manager, session_id)
"""

from analyzer.insights.pipeline import InsightsPipeline, run_pipeline, InsightsResult
from analyzer.insights.features import SessionFeatures, extract_session_features, features_to_matrix

__all__ = [
    "InsightsPipeline",
    "InsightsResult",
    "SessionFeatures",
    "extract_session_features",
    "features_to_matrix",
    "run_pipeline",
]

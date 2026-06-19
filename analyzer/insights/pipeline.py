"""analyzer/insights/pipeline.py — Insights Pipeline 编排引擎 (v4.1)

在会话结束时一次性运行，按顺序执行 5 个分析方法：
  1. features: 提取特征 → (features, X, names)
  2. patterns: 聚类工作模式 (KMeans + silhouette)
  3. changepoint: 变点检测 (PELT)
  4. anomaly: 异常检测 (IsolationForest + z-score)
  5. temporal: 时序分解 (STL / histogram)
  6. attribution: 关联分析 (t-test + ANOVA)

每个方法独立 try/except，失败不阻断后续。
总体性能预算 < 10s。
"""
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

from storage.db import DatabaseManager

logger = logging.getLogger("eyefocus.insights.pipeline")


@dataclass
class InsightsResult:
    """Pipeline 完整输出结果。

    每个字段可能是 None（对应方法未运行或失败），
    调用方需处理 None 情况。
    """
    # 元数据
    n_sessions: int = 0
    total_duration_ms: float = 0.0
    n_features: int = 0
    session_ids: List[str] = field(default_factory=list)

    # 各方法结果
    patterns_result: Optional[dict] = None         # 聚类
    changepoint_result: Optional[dict] = None       # 变点检测
    anomaly_result: Optional[dict] = None           # 异常检测
    temporal_result: Optional[dict] = None           # 时序分解
    attribution_findings: Optional[list] = None     # 关联发现

    # 方法运行状态
    methods_status: dict = field(default_factory=dict)  # {name: "ok"/"skip"/"fail"}


class InsightsPipeline:
    """离线分析 Pipeline。

    用法：
        pipeline = InsightsPipeline(db)
        result = pipeline.run(session_id)  # 当前 session 参与分析
        或
        result = pipeline.run_all()        # 分析全量历史 session
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._features_module = None
        self._patterns_module = None
        self._changepoint_module = None
        self._anomaly_module = None
        self._temporal_module = None
        self._attribution_module = None

    def _lazy_import(self):
        """惰性导入各子模块（避免 import 期全量加载）。"""
        if self._features_module is None:
            from analyzer.insights import features as _f
            self._features_module = _f
        if self._patterns_module is None:
            from analyzer.insights import patterns as _p
            self._patterns_module = _p
        if self._changepoint_module is None:
            from analyzer.insights import changepoint as _c
            self._changepoint_module = _c
        if self._anomaly_module is None:
            from analyzer.insights import anomaly as _a
            self._anomaly_module = _a
        if self._temporal_module is None:
            from analyzer.insights import temporal as _t
            self._temporal_module = _t
        if self._attribution_module is None:
            from analyzer.insights import attribution as _at
            self._attribution_module = _at

    def run(self, session_id: str) -> InsightsResult:
        """运行完整 pipeline（分析所有历史 sessions，包含当前 session）。

        Args:
            session_id: 当前结束的 session_id（参与特征提取，报告会聚焦该 session）

        Returns:
            InsightsResult
        """
        return self._run(session_ids=[session_id])

    def run_all(self) -> InsightsResult:
        """运行完整 pipeline（分析所有历史 session）。"""
        return self._run(session_ids=None)

    def _run(self, session_ids: Optional[List[str]] = None) -> InsightsResult:
        """核心执行方法。"""
        t0 = time.time()
        self._lazy_import()
        status = {}
        result = InsightsResult()

        # ── Phase 1: 特征提取 ──
        features_list = []
        X = None
        feature_names = []
        try:
            if session_ids:
                # 只提取指定 session
                features_list = []
                for sid in session_ids:
                    sf = self._features_module.extract_session_features(self.db, sid)
                    if sf is not None:
                        features_list.append(sf)
                if features_list:
                    X, feature_names = self._features_module.features_to_matrix(features_list)
            else:
                features_list, X, feature_names = self._features_module.extract_all_sessions(self.db)

            if X is None or X.shape[0] < 2:
                status["features"] = "skip: insufficient data"
                logger.info("特征提取: 数据不足，跳过后续分析")
            else:
                status["features"] = f"ok: {X.shape[0]} sessions × {X.shape[1]} features"
                logger.info("特征提取: %s", status["features"])

            result.n_sessions = X.shape[0] if X is not None and X.size > 0 else 0
            result.n_features = X.shape[1] if X is not None and X.size > 0 else 0
            result.session_ids = [f.session_id for f in features_list]

        except Exception as e:
            status["features"] = f"fail: {e}"
            logger.error("特征提取失败: %s", e)

        # ── 只有特征提取成功后才运行后续方法 ──
        if X is not None and X.shape[0] >= 2:
            all_sids = result.session_ids

            # Phase 2: 聚类
            try:
                pr = self._patterns_module.analyze_patterns(X, feature_names, all_sids)
                if pr.detected:
                    result.patterns_result = {
                        "n_clusters": pr.n_clusters,
                        "silhouette": pr.silhouette,
                        "cluster_sizes": pr.cluster_sizes,
                        "pattern_labels": pr.pattern_labels,
                        "k_evaluation": pr.k_evaluation,
                    }
                    status["patterns"] = f"ok: k={pr.n_clusters}, silhouette={pr.silhouette:.3f}"
                else:
                    status["patterns"] = "skip: no patterns detected"
                logger.info("聚类分析: %s", status["patterns"])
            except Exception as e:
                status["patterns"] = f"fail: {e}"
                logger.error("聚类分析失败: %s", e)

            # Phase 3: 变点检测（只在有当前 session 的 focus_records 时运行）
            try:
                # 取最新 session 的 focus_records 做变点检测
                latest_sid = all_sids[-1] if all_sids else None
                if latest_sid:
                    from analyzer.insights.changepoint import FocusTimeSeries
                    with self.db.get_cursor() as cur:
                        cur.execute("""
                            SELECT window_start, focus_score
                            FROM focus_records
                            WHERE session_id = ? AND focus_score IS NOT NULL
                            ORDER BY window_start
                        """, (latest_sid,))
                        rows = cur.fetchall()
                    if len(rows) >= 15:
                        ts = [r["window_start"] for r in rows]
                        vals = [r["focus_score"] for r in rows]
                        series = FocusTimeSeries(timestamps=ts, values=vals, session_id=latest_sid)
                        cr = self._changepoint_module.detect_changepoints(series)
                        if cr.detected:
                            result.changepoint_result = {
                                "n_changepoints": cr.n_changepoints,
                                "segment_means": cr.segment_means,
                                "earliest_drop_time": cr.earliest_drop_time,
                                "recovery_count": cr.recovery_count,
                                "penalty": cr.penalty,
                            }
                            status["changepoint"] = f"ok: {cr.n_changepoints} points"
                        else:
                            status["changepoint"] = "skip: no changepoints detected"
                    else:
                        status["changepoint"] = f"skip: {len(rows)} records < 15"
                else:
                    status["changepoint"] = "skip: no sessions"
                logger.info("变点检测: %s", status["changepoint"])
            except Exception as e:
                status["changepoint"] = f"fail: {e}"
                logger.error("变点检测失败: %s", e)

            # Phase 4: 异常检测
            try:
                ar = self._anomaly_module.detect_anomalies(X, feature_names, all_sids)
                if ar.detected:
                    result.anomaly_result = {
                        "n_sessions": ar.n_sessions,
                        "anomaly_count": ar.anomaly_count,
                        "anomaly_sessions": ar.anomaly_sessions[:5],  # top 5
                        "anomaly_scores": ar.anomaly_scores[:5],
                        "top_factors": ar.top_factors,
                    }
                    status["anomaly"] = f"ok: {ar.anomaly_count} anomalies"
                else:
                    status["anomaly"] = "skip: no anomalies detected"
                logger.info("异常检测: %s", status["anomaly"])
            except Exception as e:
                status["anomaly"] = f"fail: {e}"
                logger.error("异常检测失败: %s", e)

            # Phase 5: 时序分解
            try:
                tr = self._temporal_module.analyze_temporal(self.db, all_sids)
                if tr.detected:
                    result.temporal_result = {
                        "n_days": tr.n_days,
                        "method": tr.method,
                        "peak_hours": tr.peak_hours,
                        "low_hours": tr.low_hours,
                        "hourly_pattern": tr.hourly_pattern[:24],
                    }
                    status["temporal"] = f"ok: {tr.method}, {len(tr.peak_hours)} peak periods"
                else:
                    status["temporal"] = "skip: insufficient data"
                logger.info("时序分解: %s", status["temporal"])
            except Exception as e:
                status["temporal"] = f"fail: {e}"
                logger.error("时序分解失败: %s", e)

            # Phase 6: 关联分析
            try:
                findings = self._attribution_module.analyze_attributions(
                    features_list, X, feature_names)
                if findings:
                    result.attribution_findings = [
                        {
                            "factor": f.factor_name,
                            "test_type": f.test_type,
                            "p_value": f.p_value,
                            "effect_size": f.effect_size,
                            "direction": f.direction,
                            "summary": f.summary,
                        }
                        for f in findings
                    ]
                    status["attribution"] = f"ok: {len(findings)} findings"
                else:
                    status["attribution"] = "skip: no significant findings"
                logger.info("关联分析: %s", status["attribution"])
            except Exception as e:
                status["attribution"] = f"fail: {e}"
                logger.error("关联分析失败: %s", e)

        # 汇总
        elapsed = (time.time() - t0) * 1000
        result.total_duration_ms = round(elapsed, 1)
        result.methods_status = status

        logger.info("Insights Pipeline 完成: %.1fms, n_sessions=%d",
                     elapsed, result.n_sessions)
        return result


def run_pipeline(db: DatabaseManager, session_id: Optional[str] = None) -> InsightsResult:
    """便捷入口：创建 pipeline 并运行。

    Args:
        db: DatabaseManager 实例
        session_id: 当前结束的 session_id（为 None 时分析所有历史）

    Returns:
        InsightsResult
    """
    pipeline = InsightsPipeline(db)
    if session_id:
        return pipeline.run(session_id)
    return pipeline.run_all()

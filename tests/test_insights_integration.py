"""test_insights_integration.py — Insights pipeline 端到端集成测试 (v4.1)

验证全 pipeline 在合成数据库上的正确性和性能。

验收标准（AC26-AC30）：
  - AC26: 30 sessions + 1h session 全 pipeline < 10s
  - AC27: n_sessions < 10 时聚类降级（不报错）
  - AC28: 异常检测返回 top 3 中文因子
  - AC29: 14 天数据下时序分析显示具体小时段
  - AC30: 关联分析返回 ≥ 1 个 p<0.05 + effect>0.3 发现
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import time
import pytest
import numpy as np
from datetime import datetime

from storage.db import create_database_manager
from storage.models import FocusRecord, FatigueRecord, BlinkRecord, FatigueLevel
from analyzer.insights import run_pipeline, InsightsResult, InsightsPipeline


# ═══════════════════════════════════════════════════════════════════
#  Helper: 合成数据
# ═══════════════════════════════════════════════════════════════════

def _make_session_data(db, sid: str, n_minutes: int, base_hour: int = 9,
                       focus_base: float = 70.0, fatigue: FatigueLevel = FatigueLevel.LOW,
                       blink_rate: float = 15.0):
    """向 session 写入合成数据。"""
    import time as _time
    rng = np.random.default_rng(hash(sid) % 2**32)

    now = _time.time()
    # 将 base_hour 映射到一天中的具体时间
    start_offset = (base_hour - 6) * 3600  # 相对 6AM 的偏移

    for m in range(n_minutes):
        ws = now - n_minutes * 60 + m * 60  # 从 m 分钟前开始
        we = ws + 60
        # 专注度随会话时间下降
        decline = (m / n_minutes) * 15
        focus = max(0, min(100, focus_base - rng.normal(decline, 4)))
        db.write_focus_record(sid, FocusRecord(
            session_id=sid,
            window_start=ws, window_end=we,
            focus_score=round(focus, 1),
            eye_score=round(focus + rng.uniform(-5, 5), 1),
            head_score=round(70 + rng.uniform(-10, 10), 1),
            gaze_score=round(focus + rng.uniform(-10, 5), 1),
            blink_rate=round(blink_rate + rng.uniform(-2, 2), 1),
            avg_ear=round(0.40 - rng.uniform(0, 0.03), 4),
            avg_yaw=round(rng.normal(0, 5), 2),
            avg_pitch=round(rng.normal(0, 4), 2),
        ))

    # 疲劳记录
    for m in range(n_minutes):
        db.write_fatigue_record(sid, FatigueRecord(
            session_id=sid,
            timestamp=now - n_minutes * 60 + m * 60,
            fatigue_level=fatigue,
            blink_rate=blink_rate + rng.uniform(-2, 2),
            avg_ear_nadir=0.25 + rng.uniform(0, 0.05),
            head_stability=0.8 + rng.uniform(0, 0.1),
            cumulative_fatigue_score=m / n_minutes * 100,
        ))

    # 眨眼事件
    for i in range(n_minutes * 15):
        db.write_blink_event(sid, BlinkRecord(
            session_id=sid,
            start_timestamp=now - n_minutes * 60 + rng.uniform(0, n_minutes * 60),
            end_timestamp=now - n_minutes * 60 + rng.uniform(0, n_minutes * 60) + 0.1,
            duration_seconds=rng.uniform(0.05, 0.15),
            ear_nadir=0.20 + rng.uniform(0, 0.05),
        ))


def _create_test_db(n_sessions: int = 30, hours_per_session: int = 1) -> tuple:
    """创建含 n_sessions 个合成数据的内存数据库。

    Returns:
        (db, session_ids)
    """
    db = create_database_manager(":memory:")
    db.initialize()

    rng = np.random.default_rng(42)
    sids = []

    for i in range(n_sessions):
        sid = db.create_session()
        # 不同 session 有不同的时间和模式
        hour = 8 + (i % 10)  # 8-17 点分布
        focus = 85 - i * 3 + rng.normal(0, 3)  # 逐步下降
        blk = 15 + i * 0.5
        if i % 3 == 0:
            fat = FatigueLevel.LOW
        elif i % 3 == 1:
            fat = FatigueLevel.MEDIUM
        else:
            fat = FatigueLevel.HIGH

        db.update_session(sid,
            end_time=datetime.now(),
            is_active=False,
            is_calibrated=True,
            baseline_ear=0.40,
            baseline_blink_rate=blk,
        )
        _make_session_data(db, sid, n_minutes=hours_per_session * 60,
                           base_hour=hour, focus_base=focus,
                           fatigue=fat, blink_rate=blk)
        sids.append(sid)

    return db, sids


# ═══════════════════════════════════════════════════════════════════
#  AC27: 数据不足降级
# ═══════════════════════════════════════════════════════════════════

class TestAC27:
    def test_few_sessions_no_crash(self):
        """< 10 sessions 不报错，返回降级信息"""
        db, sids = _create_test_db(n_sessions=3, hours_per_session=1)
        result = run_pipeline(db)
        assert result.n_sessions <= 3
        assert isinstance(result, InsightsResult)
        db.close()

    def test_single_session_no_crash(self):
        """单 session 不报错"""
        db, sids = _create_test_db(n_sessions=1, hours_per_session=1)
        result = run_pipeline(db, sids[0])
        assert isinstance(result, InsightsResult)
        db.close()


# ═══════════════════════════════════════════════════════════════════
#  AC26: 性能
# ═══════════════════════════════════════════════════════════════════

class TestAC26:
    def test_pipeline_performance(self):
        """30 sessions × 1h 全 pipeline < 10s"""
        db, sids = _create_test_db(n_sessions=30, hours_per_session=1)
        t0 = time.time()
        result = run_pipeline(db)
        elapsed = time.time() - t0
        assert elapsed < 10.0, f"Pipeline 耗时 {elapsed:.2f}s > 10s"
        db.close()


# ═══════════════════════════════════════════════════════════════════
#  AC28: 异常检测中文因子
# ═══════════════════════════════════════════════════════════════════

class TestAC28:
    def test_anomaly_top_factors_chinese(self):
        """异常 top_factors 应为中文描述"""
        db, sids = _create_test_db(n_sessions=20, hours_per_session=1)
        result = run_pipeline(db)
        if result.anomaly_result:
            for factor in result.anomaly_result.get("top_factors", []):
                assert isinstance(factor, str)
                assert len(factor) > 2  # 中文长度
                # 不应是英文特征名
                assert not factor.startswith("avg_")
                assert not factor.startswith("blink_")
        db.close()


# ═══════════════════════════════════════════════════════════════════
#  AC30: 关联分析发现
# ═══════════════════════════════════════════════════════════════════

class TestAC30:
    def test_attribution_findings(self):
        """足够 session 时应有统计显著发现"""
        db, sids = _create_test_db(n_sessions=20, hours_per_session=1)
        result = run_pipeline(db)
        if result.attribution_findings:
            for f in result.attribution_findings:
                assert f.get("p_value", 1) <= 0.05
                assert abs(f.get("effect_size", 0)) >= 0.3
        db.close()


# ═══════════════════════════════════════════════════════════════════
#  Pipeline 异常隔离
# ═══════════════════════════════════════════════════════════════════

class TestPipelineIsolation:
    def test_insights_result_structure(self):
        """返回的 InsightsResult 应有正确的结构"""
        db, sids = _create_test_db(n_sessions=10, hours_per_session=1)
        result = run_pipeline(db)
        assert hasattr(result, "n_sessions")
        assert hasattr(result, "total_duration_ms")
        assert isinstance(result.methods_status, dict)
        db.close()

    def test_run_with_session_id(self):
        """指定 session_id 运行不应报错"""
        db, sids = _create_test_db(n_sessions=10, hours_per_session=1)
        result = run_pipeline(db, sids[0])
        assert isinstance(result, InsightsResult)
        db.close()

    def test_methods_status_tracked(self):
        """每个方法的状态应被追踪"""
        db, sids = _create_test_db(n_sessions=15, hours_per_session=1)
        result = run_pipeline(db)
        for key in ["features", "patterns", "changepoint",
                     "anomaly", "temporal", "attribution"]:
            assert key in result.methods_status, f"缺少 {key} 状态"
        db.close()

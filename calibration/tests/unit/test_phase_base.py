"""测试 Phase ABC 接口契约。"""
import pytest
from calibration.phases.base import Phase, LiveFeedback, PhaseResult


def test_phase_is_abstract():
    with pytest.raises(TypeError):
        Phase()  # type: ignore[abstract]


def test_live_feedback_fields():
    fb = LiveFeedback(
        remaining_sec=3.0,
        sample_count=42,
        quality_hint="采集中，请保持",
    )
    assert fb.remaining_sec == 3.0
    assert fb.sample_count == 42


def test_phase_result_success():
    r = PhaseResult(
        success=True,
        summary={"ear_mean": 0.3, "n": 100},
        failure_reason=None,
        failure_diagnosis=None,
    )
    assert r.success is True
    assert r.summary["ear_mean"] == 0.3


def test_phase_result_failure_with_diagnosis():
    r = PhaseResult(
        success=False,
        summary={},
        failure_reason="ear_min_too_high",
        failure_diagnosis="似乎没有完全闭眼，请用力闭眼后重做",
    )
    assert r.success is False
    assert "闭眼" in r.failure_diagnosis

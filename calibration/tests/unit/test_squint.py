"""测试 SquintPhase — 8s 眯眼采集。"""
import pytest
from calibration.phases.squint import SquintPhase


def test_squint_basic_attrs():
    p = SquintPhase(duration_seconds=8.0, baseline_ear=0.30,
                   baseline_ratio=0.75, ear_min=0.08)
    assert "眯眼" in p.name
    assert "眯眼" in p.tts_intro
    assert p.duration_seconds == 8.0


def test_squint_evaluate_success():
    """眯眼 EAR 在 baseline×0.75 与 ear_min×1.2 之间，应成功。"""
    p = SquintPhase(duration_seconds=8.0, baseline_ear=0.30,
                   baseline_ratio=0.75, ear_min=0.08)
    # baseline=0.30, ear_min=0.08 → 合理眯眼 EAR 在 0.10~0.225
    for i in range(240):
        p.feed_frame(ear=0.18, yaw=0.0, pitch=0.0, timestamp=i / 30.0)
    r = p.evaluate()
    assert r.success is True
    assert r.summary["ear_mid"] == pytest.approx(0.18, abs=0.001)


def test_squint_evaluate_fail_too_open():
    """眯眼 EAR 接近 baseline（没真眯）→ 失败。"""
    p = SquintPhase(duration_seconds=8.0, baseline_ear=0.30,
                   baseline_ratio=0.75, ear_min=0.08)
    for i in range(240):
        p.feed_frame(ear=0.28, yaw=0, pitch=0, timestamp=i / 30.0)
    r = p.evaluate()
    assert r.success is False
    assert r.failure_reason == "squint_too_open"
    assert "眯眼" in r.failure_diagnosis


def test_squint_evaluate_fail_too_closed():
    """眯眼 EAR 接近 ear_min（眼睛闭得过死，没缝）→ 失败。"""
    p = SquintPhase(duration_seconds=8.0, baseline_ear=0.30,
                   baseline_ratio=0.75, ear_min=0.08)
    for i in range(240):
        p.feed_frame(ear=0.085, yaw=0, pitch=0, timestamp=i / 30.0)
    r = p.evaluate()
    assert r.success is False
    assert r.failure_reason == "squint_too_closed"
    assert "一条缝" in r.failure_diagnosis


def test_squint_is_complete():
    p = SquintPhase(duration_seconds=8.0, baseline_ear=0.30,
                   baseline_ratio=0.75, ear_min=0.08)
    assert not p.is_complete(elapsed_sec=7.99)
    assert p.is_complete(elapsed_sec=8.0)


def test_squint_reset():
    p = SquintPhase(duration_seconds=8.0, baseline_ear=0.30,
                   baseline_ratio=0.75, ear_min=0.08)
    for i in range(50):
        p.feed_frame(ear=0.18, yaw=0, pitch=0, timestamp=i / 30.0)
    p.reset()
    r = p.evaluate()
    assert r.success is False  # 重置后无数据


def test_squint_ignores_none():
    p = SquintPhase(duration_seconds=8.0, baseline_ear=0.30,
                   baseline_ratio=0.75, ear_min=0.08)
    for i in range(30):
        p.feed_frame(ear=None, yaw=None, pitch=None, timestamp=i / 30.0)
    for i in range(200):
        p.feed_frame(ear=0.18, yaw=0, pitch=0, timestamp=(30 + i) / 30.0)
    r = p.evaluate()
    assert r.success is True


def test_squint_live_feedback():
    p = SquintPhase(duration_seconds=8.0, baseline_ear=0.30,
                   baseline_ratio=0.75, ear_min=0.08)
    for i in range(50):
        p.feed_frame(ear=0.18, yaw=0, pitch=0, timestamp=i / 30.0)
    fb = p.get_live_feedback(elapsed_sec=2.0)
    assert fb.sample_count == 50
    assert fb.remaining_sec == pytest.approx(6.0, abs=0.01)
    assert "眯眼" in fb.quality_hint

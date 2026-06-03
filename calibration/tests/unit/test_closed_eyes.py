"""测试 ClosedEyesPhase — 5s 闭眼 + 3s 睁眼回升验证。"""
import pytest
from calibration.phases.closed_eyes import ClosedEyesPhase


def test_closed_eyes_basic_attrs():
    p = ClosedEyesPhase(
        closed_duration_seconds=5.0,
        verify_duration_seconds=3.0,
        baseline_ear=0.30,
        min_ratio=0.5,
    )
    assert "闭眼" in p.name
    assert "闭眼" in p.tts_intro
    # 总时长 = 闭眼 + 验证
    assert p.duration_seconds == 8.0


def test_closed_eyes_evaluate_success_low_ear_min():
    """闭眼 EAR 降到 baseline × 0.3，应成功。"""
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    # 闭眼 5s @ 30 fps = 150 帧，EAR 0.09
    for i in range(150):
        p.feed_frame(ear=0.09, yaw=0.0, pitch=0.0, timestamp=i / 30.0)
    # 睁眼 3s = 90 帧，EAR 回升到 0.30
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=0.0, pitch=0.0, timestamp=5.0 + i / 30.0)
    r = p.evaluate()
    assert r.success is True
    assert r.summary["ear_min"] == pytest.approx(0.09, abs=0.001)


def test_closed_eyes_evaluate_fail_ear_min_too_high():
    """闭眼期 ear_min > baseline × 0.5，未真正闭眼，应失败。"""
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    for i in range(150):
        p.feed_frame(ear=0.22, yaw=0.0, pitch=0.0, timestamp=i / 30.0)
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=0.0, pitch=0.0, timestamp=5.0 + i / 30.0)
    r = p.evaluate()
    assert r.success is False
    assert r.failure_reason == "ear_min_too_high"
    assert "闭眼" in r.failure_diagnosis


def test_closed_eyes_is_complete():
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    assert not p.is_complete(elapsed_sec=7.99)
    assert p.is_complete(elapsed_sec=8.0)


def test_closed_eyes_live_feedback_phase_split():
    """前 5s 显示"闭眼中"，后 3s 显示"睁眼验证中"。"""
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    fb1 = p.get_live_feedback(elapsed_sec=2.0)
    assert "闭眼" in fb1.quality_hint
    fb2 = p.get_live_feedback(elapsed_sec=6.0)
    assert "睁眼" in fb2.quality_hint


def test_closed_eyes_ignores_none_frames():
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    for i in range(50):
        p.feed_frame(ear=None, yaw=None, pitch=None, timestamp=i / 30.0)
    for i in range(100):
        p.feed_frame(ear=0.09, yaw=0.0, pitch=0.0, timestamp=(50 + i) / 30.0)
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=0.0, pitch=0.0, timestamp=5.0 + i / 30.0)
    r = p.evaluate()
    assert r.success is True
    assert r.summary["ear_min"] == pytest.approx(0.09, abs=0.001)


def test_closed_eyes_reset():
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    p.feed_frame(ear=0.05, yaw=0, pitch=0, timestamp=0.1)
    p.reset()
    r = p.evaluate()
    # 重置后无数据 → 评估应失败
    assert r.success is False

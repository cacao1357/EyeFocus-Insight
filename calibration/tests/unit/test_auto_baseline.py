"""测试阶段 0 自动基线采集 — 合成 EAR/yaw/pitch 序列。"""
import pytest
from calibration.phases.auto_baseline import AutoBaselinePhase


def _feed_stable_frames(phase, n_frames=210, ear=0.30, yaw=0.5, pitch=1.0, start_t=0.0):
    """合成稳定的 30 fps 数据（7 秒 × 30 = 210 帧）。"""
    for i in range(n_frames):
        phase.feed_frame(ear=ear, yaw=yaw, pitch=pitch, timestamp=start_t + i / 30.0)


def test_auto_baseline_phase_basic_attrs():
    p = AutoBaselinePhase(duration_seconds=7.0)
    assert p.name == "自动基线采集"
    assert p.duration_seconds == 7.0
    assert "睁眼" in p.tts_intro


def test_auto_baseline_collects_samples():
    p = AutoBaselinePhase(duration_seconds=7.0)
    _feed_stable_frames(p, n_frames=210, ear=0.30)
    fb = p.get_live_feedback(elapsed_sec=3.0)
    assert fb.sample_count == 210
    assert fb.remaining_sec == pytest.approx(4.0, abs=0.01)


def test_auto_baseline_ignores_none_ear():
    p = AutoBaselinePhase(duration_seconds=7.0)
    # 100 帧有 ear，10 帧 None（人脸丢失）
    _feed_stable_frames(p, n_frames=100, ear=0.30)
    for i in range(10):
        p.feed_frame(ear=None, yaw=None, pitch=None, timestamp=100.0 + i / 30.0)
    fb = p.get_live_feedback(elapsed_sec=3.5)
    assert fb.sample_count == 100  # None 帧不计入


def test_auto_baseline_complete_after_duration():
    p = AutoBaselinePhase(duration_seconds=7.0)
    assert not p.is_complete(elapsed_sec=6.99)
    assert p.is_complete(elapsed_sec=7.0)
    assert p.is_complete(elapsed_sec=8.0)


def test_auto_baseline_evaluate_success_stable_ear():
    p = AutoBaselinePhase(duration_seconds=7.0)
    _feed_stable_frames(p, n_frames=210, ear=0.30, yaw=0.5, pitch=1.0)
    r = p.evaluate()
    assert r.success is True
    assert r.summary["ear_mean"] == pytest.approx(0.30, abs=0.001)
    assert r.summary["ear_cv"] == pytest.approx(0.0, abs=0.001)
    assert r.summary["yaw_mean"] == pytest.approx(0.5, abs=0.001)
    assert r.summary["pitch_mean"] == pytest.approx(1.0, abs=0.001)
    assert r.summary["face_detected_ratio"] == 1.0


def test_auto_baseline_evaluate_fail_low_face_ratio():
    """face_detected_ratio < 0.7 应失败。"""
    p = AutoBaselinePhase(duration_seconds=7.0)
    for i in range(50):
        p.feed_frame(ear=0.3, yaw=0.0, pitch=0.0, timestamp=i / 30.0)
    for i in range(160):
        p.feed_frame(ear=None, yaw=None, pitch=None, timestamp=(50 + i) / 30.0)
    r = p.evaluate()
    assert r.success is False
    assert r.failure_reason == "face_detected_ratio_low"
    assert "人脸" in r.failure_diagnosis


def test_auto_baseline_evaluate_fail_high_ear_cv():
    """ear_cv > 0.15 应失败（频繁眨眼/动作）。"""
    p = AutoBaselinePhase(duration_seconds=7.0)
    # 交替 EAR 0.30 与 0.10（模拟频繁眨眼）
    for i in range(210):
        ear = 0.30 if i % 2 == 0 else 0.10
        p.feed_frame(ear=ear, yaw=0.0, pitch=0.0, timestamp=i / 30.0)
    r = p.evaluate()
    assert r.success is False
    assert r.failure_reason == "ear_cv_high"
    assert "睁眼" in r.failure_diagnosis


def test_auto_baseline_reset():
    p = AutoBaselinePhase(duration_seconds=7.0)
    _feed_stable_frames(p, n_frames=100)
    p.reset()
    fb = p.get_live_feedback(elapsed_sec=0.0)
    assert fb.sample_count == 0


def test_auto_baseline_evaluate_fail_no_frames():
    """完全没有 feed_frame 调用时应失败（理论不可能，兜底）。"""
    p = AutoBaselinePhase(duration_seconds=7.0)
    r = p.evaluate()
    assert r.success is False
    assert r.failure_reason == "no_frames"
    assert "摄像头" in r.failure_diagnosis

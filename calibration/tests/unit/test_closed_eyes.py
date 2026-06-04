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


# ============ T-CAL-15: 闭眼校准改进 (UX issue #1) ============

def test_closed_eyes_live_feedback_includes_current_ear():
    """T-CAL-15: 屏幕需显示当前 EAR 数值, 用户才能调整闭眼力度。

    修复前: get_live_feedback 只返回 sample_count + quality_hint, 没 EAR 值
    修复后: LiveFeedback 应含 current_ear 字段
    """
    from calibration.phases.base import LiveFeedback
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    p.feed_frame(ear=0.15, yaw=0, pitch=0, timestamp=0.5)
    fb = p.get_live_feedback(elapsed_sec=1.0)
    assert hasattr(fb, 'current_ear'), "LiveFeedback 应有 current_ear 字段"
    assert fb.current_ear == 0.15


def test_closed_eyes_default_min_ratio_relaxed():
    """T-CAL-15: min_ratio 默认 0.5 太严, 实测用户闭眼时 ear_min 多在 0.55-0.65 倍 baseline。

    测试 CalibrationConfig 默认值: closed_eyes_min_ratio 应为 0.6 (而非 0.5)
    """
    from calibration.config import CalibrationConfig
    c = CalibrationConfig()
    assert c.closed_eyes_min_ratio == 0.6, (
        f"T-CAL-15: min_ratio 默认值应为 0.6, 实际 {c.closed_eyes_min_ratio}"
    )


def test_closed_eyes_tts_includes_forceful_hint():
    """T-CAL-15: TTS 需包含"用力闭眼"提示, 用户才会真正闭紧。

    修复前: tts_intro = "请闭眼并保持 5 秒" (模糊)
    修复后: tts_intro 应明确指示用力闭眼
    """
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    assert "用力" in p.tts_intro, (
        f"T-CAL-15: tts_intro 应含'用力'提示, 实际 '{p.tts_intro}'"
    )


def test_closed_eyes_quality_hint_shows_threshold():
    """T-CAL-15: 屏幕 quality_hint 需显示 EAR 阈值, 用户知道要闭到什么程度。

    修复前: "闭眼中，请保持..." (无 EAR 数字)
    修复后: "闭眼中 EAR=0.18 阈值<0.15" (实时数字反馈)
    """
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    p.feed_frame(ear=0.20, yaw=0, pitch=0, timestamp=1.0)
    fb = p.get_live_feedback(elapsed_sec=2.0)
    # 阈值 = 0.30 * 0.5 = 0.15, 当前 EAR=0.20
    assert "0.20" in fb.quality_hint or "0.2" in fb.quality_hint, (
        f"T-CAL-15: quality_hint 应含当前 EAR, 实际 '{fb.quality_hint}'"
    )
    assert "0.15" in fb.quality_hint, (
        f"T-CAL-15: quality_hint 应含阈值, 实际 '{fb.quality_hint}'"
    )


# ============ T-CAL-17: 跨阶段容错 — 失败诊断含数据 ============

def test_closed_eyes_failure_diagnosis_includes_ear_value():
    """T-CAL-17: 阶段失败时诊断信息应含实际 ear_min, 用户能调姿。"""
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    # 闭眼时 EAR 没降到阈值
    for i in range(150):
        p.feed_frame(ear=0.22, yaw=0, pitch=0, timestamp=i / 30.0)
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=0, pitch=0, timestamp=5.0 + i / 30.0)
    r = p.evaluate()
    assert r.success is False
    # 诊断应含 ear_min 实际值 0.22 和阈值 0.15
    assert "0.22" in r.failure_diagnosis, (
        f"T-CAL-17: 失败诊断应含 ear_min 实际值, 实际 '{r.failure_diagnosis}'"
    )
    assert "0.15" in r.failure_diagnosis, (
        f"T-CAL-17: 失败诊断应含阈值, 实际 '{r.failure_diagnosis}'"
    )

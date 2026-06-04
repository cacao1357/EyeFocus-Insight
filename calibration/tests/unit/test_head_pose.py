"""测试 HeadPosePhase — T-CAL-25 拆 4 子阶段 (click-to-advance)。

每个子阶段: 用户转头 → 系统等 4s → 进 PHASE_SUMMARY → 用户点继续 → 下一子阶段。
"""
import pytest
from calibration.phases.head_pose import HeadPosePhase, HeadDirection


def _make_phase(min_degrees=10.0, direction_seconds=4.0):
    """T-CAL-26 默认 12° 阈值。direction_seconds 现在只是 per_direction 时长。"""
    return HeadPosePhase(direction_seconds=direction_seconds, min_degrees=min_degrees)


def test_head_pose_basic_attrs():
    p = _make_phase()
    assert "头部" in p.name
    # T-CAL-25: duration = per_direction * 4 = 16s (4 个子阶段各 4s)
    assert p.duration_seconds == 16.0


def test_head_pose_has_4_sub_phases():
    p = _make_phase()
    assert len(p.sub_phases) == 4
    keywords = ["抬头", "低头", "向左", "向右"]
    for sub, kw in zip(p.sub_phases, keywords):
        assert kw in sub.tts, f"子阶段缺少 '{kw}' TTS"


def test_head_pose_current_sub_phase_default():
    """T-CAL-25: 默认 current_sub_idx=0 (UP)."""
    p = _make_phase()
    assert p._current_sub_idx == 0
    assert p.current_sub_phase(0).direction == HeadDirection.UP


def test_head_pose_advance_sub_phase():
    """T-CAL-25: advance_sub_phase 推进 sub_idx, 返回是否还有下一 sub-phase。"""
    p = _make_phase()
    assert p.advance_sub_phase() is True  # 0 → 1
    assert p._current_sub_idx == 1
    assert p.advance_sub_phase() is True  # 1 → 2
    assert p.advance_sub_phase() is True  # 2 → 3
    assert p.advance_sub_phase() is False  # 3 → 4, 全部完成
    assert p._current_sub_idx == 4


def test_head_pose_evaluate_success_all_directions():
    """T-CAL-25: 4 子阶段各达到 ±12°, 应成功 (需先 advance_sub_phase)。"""
    p = _make_phase(min_degrees=12.0)
    # sub 0: 抬头
    for i in range(120):
        p.feed_frame(ear=0.30, yaw=0, pitch=-15, timestamp=i / 30.0)
    p.advance_sub_phase()
    # sub 1: 低头
    for i in range(120):
        p.feed_frame(ear=0.30, yaw=0, pitch=15, timestamp=i / 30.0)
    p.advance_sub_phase()
    # sub 2: 左转
    for i in range(120):
        p.feed_frame(ear=0.30, yaw=-15, pitch=0, timestamp=i / 30.0)
    p.advance_sub_phase()
    # sub 3: 右转
    for i in range(120):
        p.feed_frame(ear=0.30, yaw=15, pitch=0, timestamp=i / 30.0)
    r = p.evaluate()
    assert r.success is True
    assert r.summary["pitch_up_max"] == -15
    assert r.summary["pitch_down_max"] == 15
    assert r.summary["yaw_left_max"] == -15
    assert r.summary["yaw_right_max"] == 15


def test_head_pose_evaluate_fail_one_direction_insufficient():
    p = _make_phase(min_degrees=12.0)
    for i in range(120): p.feed_frame(ear=0.30, yaw=0, pitch=-5, timestamp=i / 30.0)
    p.advance_sub_phase()
    for i in range(120): p.feed_frame(ear=0.30, yaw=0, pitch=15, timestamp=i / 30.0)
    p.advance_sub_phase()
    for i in range(120): p.feed_frame(ear=0.30, yaw=-15, pitch=0, timestamp=i / 30.0)
    p.advance_sub_phase()
    for i in range(120): p.feed_frame(ear=0.30, yaw=15, pitch=0, timestamp=i / 30.0)
    r = p.evaluate()
    assert r.success is False
    assert r.failure_reason == "head_direction_insufficient"
    assert "抬头" in r.failure_diagnosis


def test_head_pose_live_feedback_includes_current_direction():
    """T-CAL-25: live_feedback 显示当前 sub-phase 方向。"""
    p = _make_phase()
    p.feed_frame(ear=0.30, yaw=15.0, pitch=10.0, timestamp=1.0)
    fb = p.get_live_feedback(elapsed_sec=1.0)
    assert "抬头" in fb.quality_hint
    p.advance_sub_phase()
    p.feed_frame(ear=0.30, yaw=0, pitch=-5, timestamp=5.0)
    fb2 = p.get_live_feedback(elapsed_sec=5.0)
    assert "低头" in fb2.quality_hint


def test_head_pose_is_complete_only_after_all_4_advance():
    """T-CAL-25: is_complete 仅在 4 sub 全 advance 后才 True。"""
    p = _make_phase()
    assert not p.is_complete(elapsed_sec=100.0)  # 即使时间很长, 没 advance 不算完成
    p.advance_sub_phase()
    assert not p.is_complete(elapsed_sec=100.0)
    p.advance_sub_phase()
    assert not p.is_complete(elapsed_sec=100.0)
    p.advance_sub_phase()
    assert not p.is_complete(elapsed_sec=100.0)
    p.advance_sub_phase()  # 第 4 次返回 False (4 ≥ 4)
    assert p.is_complete(elapsed_sec=100.0)


def test_head_pose_reset():
    p = _make_phase()
    p.feed_frame(ear=0.30, yaw=-10, pitch=-10, timestamp=0.1)
    p.reset()
    r = p.evaluate()
    assert r.success is False


# ============ T-CAL-16/22: 实时数值 + stuck 检测 ============

def test_head_pose_live_feedback_includes_yaw_pitch():
    """T-CAL-16/26: 屏幕显示实时 yaw/pitch + 阈值 (T-CAL-26 阈值 12°)。"""
    p = _make_phase(min_degrees=12.0)
    p.feed_frame(ear=0.30, yaw=15.0, pitch=10.0, timestamp=1.0)
    fb = p.get_live_feedback(elapsed_sec=1.0)
    assert fb.current_yaw == 15.0
    assert fb.current_pitch == 10.0
    assert fb.threshold_yaw == 12.0
    assert "15.0" in fb.quality_hint
    assert "10.0" in fb.quality_hint
    assert "12" in fb.quality_hint


def test_head_pose_detects_stuck_head():
    """T-CAL-16: 头部不动 1.5 秒, 应触发 'stuck' 警告。"""
    p = _make_phase(min_degrees=12.0)
    for i in range(50):
        p.feed_frame(ear=0.30, yaw=5.0, pitch=5.0, timestamp=i / 30.0)
    assert p.is_stuck() is True
    fb = p.get_live_feedback(elapsed_sec=1.0)
    assert "未动" in fb.quality_hint or "动" in fb.quality_hint


def test_head_pose_resets_stuck_counter_on_movement():
    p = _make_phase(min_degrees=12.0)
    for i in range(30):
        p.feed_frame(ear=0.30, yaw=5.0, pitch=5.0, timestamp=i / 30.0)
    assert p._stuck_counter == 29
    p.feed_frame(ear=0.30, yaw=20.0, pitch=15.0, timestamp=1.0)
    assert p._stuck_counter == 0
    assert p.is_stuck() is False


# ============ T-CAL-25: 4 sub-phase click-to-advance 设计 ============

def test_head_pose_tts_intro_explains_click_to_advance():
    """T-CAL-25: tts_intro 应说明 '4 个头部动作 + 每完成 1 个点继续'。"""
    p = _make_phase()
    assert "4" in p.tts_intro, f"T-CAL-25: tts_intro 应含 '4', 实际 '{p.tts_intro}'"
    assert "继续" in p.tts_intro, f"T-CAL-25: tts_intro 应含 '继续', 实际 '{p.tts_intro}'"


def test_head_pose_advance_resets_stuck_counter():
    """T-CAL-25: 推进 sub-phase 应重置 stuck 计数 (新方向重头算)。"""
    p = _make_phase(min_degrees=12.0)
    for i in range(50):
        p.feed_frame(ear=0.30, yaw=5.0, pitch=5.0, timestamp=i / 30.0)
    assert p._stuck_counter == 49
    p.advance_sub_phase()
    assert p._stuck_counter == 0

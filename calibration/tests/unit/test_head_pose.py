"""测试 HeadPosePhase — 4 子阶段（抬/低/左/右）各自独立 TTS 指令。"""
import pytest
from calibration.phases.head_pose import HeadPosePhase, HeadDirection


def test_head_pose_basic_attrs():
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    assert "头部" in p.name
    assert p.duration_seconds == 12.0  # 4 × 3


def test_head_pose_has_4_sub_phases():
    """BUG 4 修复：4 个子阶段必须各有独立 TTS 指令。"""
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    assert len(p.sub_phases) == 4
    keywords = ["抬头", "低头", "向左", "向右"]
    for sub, kw in zip(p.sub_phases, keywords):
        assert kw in sub.tts, f"子阶段缺少 '{kw}' TTS"


def test_head_pose_current_sub_phase_by_elapsed():
    """根据 elapsed 切换当前子阶段。"""
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    assert p.current_sub_phase(elapsed_sec=0.5).direction == HeadDirection.UP
    assert p.current_sub_phase(elapsed_sec=3.5).direction == HeadDirection.DOWN
    assert p.current_sub_phase(elapsed_sec=6.5).direction == HeadDirection.LEFT
    assert p.current_sub_phase(elapsed_sec=9.5).direction == HeadDirection.RIGHT


def test_head_pose_evaluate_success_all_directions():
    """4 方向都达到 ±10°，应成功。"""
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    # 抬头 0~3s: pitch = -15
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=0, pitch=-15, timestamp=i / 30.0)
    # 低头 3~6s: pitch = 15
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=0, pitch=15, timestamp=3.0 + i / 30.0)
    # 左转 6~9s: yaw = -15
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=-15, pitch=0, timestamp=6.0 + i / 30.0)
    # 右转 9~12s: yaw = 15
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=15, pitch=0, timestamp=9.0 + i / 30.0)
    r = p.evaluate()
    assert r.success is True
    assert r.summary["pitch_up_max"] == -15
    assert r.summary["pitch_down_max"] == 15
    assert r.summary["yaw_left_max"] == -15
    assert r.summary["yaw_right_max"] == 15


def test_head_pose_evaluate_fail_one_direction_insufficient():
    """某方向 < ±10° → 失败 + 诊断含方向。"""
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=0, pitch=-5, timestamp=i / 30.0)  # 抬头不够
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=0, pitch=15, timestamp=3.0 + i / 30.0)
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=-15, pitch=0, timestamp=6.0 + i / 30.0)
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=15, pitch=0, timestamp=9.0 + i / 30.0)
    r = p.evaluate()
    assert r.success is False
    assert r.failure_reason == "head_direction_insufficient"
    assert "抬头" in r.failure_diagnosis


def test_head_pose_live_feedback_includes_direction_hint():
    """实时反馈应包含当前方向提示。"""
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    fb_up = p.get_live_feedback(elapsed_sec=1.0)
    assert "抬头" in fb_up.quality_hint
    fb_down = p.get_live_feedback(elapsed_sec=4.0)
    assert "低头" in fb_down.quality_hint


def test_head_pose_is_complete():
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    assert not p.is_complete(elapsed_sec=11.99)
    assert p.is_complete(elapsed_sec=12.0)


def test_head_pose_reset():
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    for i in range(30):
        p.feed_frame(ear=0.30, yaw=-10, pitch=-10, timestamp=i / 30.0)
    p.reset()
    r = p.evaluate()
    assert r.success is False  # 无数据


# ============ T-CAL-16: 头部姿态改进 (UX issue #2 + #3) ============

def test_head_pose_tts_intro_mentions_large_amplitude():
    """T-CAL-16: tts_intro 应提示用户'尽量大幅度' (避免幅度不够)。"""
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=20.0)
    assert "幅度" in p.tts_intro, (
        f"T-CAL-16: tts_intro 应含'幅度'提示, 实际 '{p.tts_intro}'"
    )


def test_head_pose_live_feedback_includes_yaw_pitch():
    """T-CAL-16: 屏幕需显示实时 yaw/pitch + 阈值, 用户能调整头部角度。"""
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=20.0)
    p.feed_frame(ear=0.30, yaw=15.0, pitch=10.0, timestamp=1.0)
    fb = p.get_live_feedback(elapsed_sec=1.0)
    assert fb.current_yaw == 15.0
    assert fb.current_pitch == 10.0
    assert fb.threshold_yaw == 20.0
    assert "15.0" in fb.quality_hint
    assert "10.0" in fb.quality_hint
    assert "20" in fb.quality_hint


def test_head_pose_detects_stuck_head():
    """T-CAL-16: 头部不动 1.5 秒, 应触发 'stuck' 警告。"""
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=20.0)
    for i in range(50):
        p.feed_frame(ear=0.30, yaw=5.0, pitch=5.0, timestamp=i / 30.0)
    assert p.is_stuck() is True
    fb = p.get_live_feedback(elapsed_sec=1.0)
    assert "未动" in fb.quality_hint or "动" in fb.quality_hint


def test_head_pose_resets_stuck_counter_on_movement():
    """T-CAL-16: 头部一旦动, stuck 计数应清零。"""
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=20.0)
    for i in range(30):
        p.feed_frame(ear=0.30, yaw=5.0, pitch=5.0, timestamp=i / 30.0)
    # 30 帧: frame 0 不计入 (prev 默认 0 → diff 5 not < 2), frame 1~29 = 29 帧 stuck
    assert p._stuck_counter == 29
    p.feed_frame(ear=0.30, yaw=20.0, pitch=15.0, timestamp=1.0)
    assert p._stuck_counter == 0
    assert p.is_stuck() is False

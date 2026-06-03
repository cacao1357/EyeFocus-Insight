"""测试 BlinkCountPhase — 2 轮 × 15s 眨眼检测 + 用户输入 + 调整因子。"""
import pytest
from calibration.phases.blink_count import BlinkCountPhase, BlinkCountState


def test_blink_count_basic_attrs():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    assert "眨眼" in p.name
    assert p.duration_seconds == 30.0  # 2 × 15


def test_blink_count_initial_state_is_running():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    assert p.current_round == 1
    assert p.state == BlinkCountState.COUNTING


def test_blink_count_detects_30hz_blinks():
    """BUG 1 修复回归：合成 30 fps 序列 + 5 个 200ms 眨眼应全检出。"""
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    # 15s @ 30fps = 450 帧。每 3s 一次 200ms 眨眼 = 5 次
    for frame_idx in range(15 * 30):
        t = frame_idx / 30.0
        if int(t) % 3 == 0 and (t - int(t)) < 0.2:
            ear = 0.10  # 眨眼期 < blink_threshold (0.30*0.75=0.225)
        else:
            ear = 0.30
        p.feed_frame(ear=ear, yaw=0, pitch=0, timestamp=t)
    detected = p.get_round_detected_blinks()
    assert detected == 5, f"BUG 1 回归：期望 5 次眨眼，实际检出 {detected}"


def test_blink_count_round_complete_transitions_to_waiting():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    p.on_round_time_up()
    assert p.state == BlinkCountState.WAITING_INPUT


def test_blink_count_user_input_within_range_advances():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    p.on_round_time_up()
    p.on_user_input(10)
    assert p.state == BlinkCountState.COUNTING
    assert p.current_round == 2


def test_blink_count_user_input_out_of_range_rejected():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    p.on_round_time_up()
    accepted = p.on_user_input(100)  # 超过 max=60
    assert accepted is False
    assert p.state == BlinkCountState.WAITING_INPUT  # 仍在等输入


def test_blink_count_full_2_rounds_completes_phase():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    p.on_round_time_up()
    p.on_user_input(10)
    p.on_round_time_up()
    p.on_user_input(12)
    assert p.state == BlinkCountState.DONE


def test_blink_count_evaluate_with_rounds():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    # 模拟两轮（每轮检测到 8 次，用户报告 10 次）
    for _ in range(2):
        for frame_idx in range(15 * 30):
            t = frame_idx / 30.0
            if int(t) % 2 == 0 and (t - int(t)) < 0.2:
                ear = 0.10
            else:
                ear = 0.30
            p.feed_frame(ear=ear, yaw=0, pitch=0, timestamp=t)
        p.on_round_time_up()
        p.on_user_input(10)
    r = p.evaluate()
    assert r.success is True
    assert len(r.summary["rounds"]) == 2
    assert r.summary["final_adjustment_factor"] == pytest.approx(1.2, abs=0.05)


def test_blink_count_evaluate_no_rounds_default():
    """跳过该阶段（rounds=0）应仍返回 success，blink_rounds 为空。"""
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    # 直接 evaluate（无任何 round complete）
    r = p.evaluate()
    assert r.success is False  # 未跑完 2 轮，应失败


def test_blink_count_reset_clears_state():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    # 推进到 round 2
    p.on_round_time_up()
    p.on_user_input(10)
    assert p.current_round == 2
    p.reset()
    assert p.current_round == 1
    assert p.state == BlinkCountState.COUNTING
    assert p.get_round_detected_blinks() == 0


def test_blink_count_squint_when_eye_closed_too_long():
    """闭眼时长 > 0.4s 算眯眼而非眨眼。"""
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    # 闭眼 0.5s（应算眯眼）
    for frame_idx in range(int(0.5 * 30)):
        p.feed_frame(ear=0.10, yaw=0, pitch=0, timestamp=frame_idx / 30.0)
    p.feed_frame(ear=0.30, yaw=0, pitch=0, timestamp=0.5)
    assert p.get_round_detected_blinks() == 0
    assert p.get_round_detected_squints() == 1


def test_blink_count_ignores_none_ear():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    p.feed_frame(ear=None, yaw=0, pitch=0, timestamp=0.0)
    p.feed_frame(ear=None, yaw=0, pitch=0, timestamp=0.5)
    assert p.get_round_detected_blinks() == 0


def test_blink_count_feed_frame_ignored_when_waiting_input():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    p.on_round_time_up()  # → WAITING_INPUT
    p.feed_frame(ear=0.10, yaw=0, pitch=0, timestamp=15.5)
    assert p.get_round_detected_blinks() == 0


def test_blink_count_live_feedback():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    fb = p.get_live_feedback(elapsed_sec=2.0)
    assert fb.remaining_sec == pytest.approx(13.0, abs=0.01)
    assert "1/2" in fb.quality_hint


def test_blink_count_on_round_time_up_idempotent():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    p.on_round_time_up()
    p.on_round_time_up()  # 已 WAITING_INPUT，no-op
    assert p.state == BlinkCountState.WAITING_INPUT


def test_blink_count_on_user_input_rejected_when_counting():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    # 仍在 COUNTING，on_user_input 应拒绝
    accepted = p.on_user_input(10)
    assert accepted is False
    assert p.state == BlinkCountState.COUNTING


def test_blink_count_is_complete_when_done():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    p.on_round_time_up()
    p.on_user_input(10)
    p.on_round_time_up()
    p.on_user_input(12)
    assert p.is_complete(elapsed_sec=0) is True

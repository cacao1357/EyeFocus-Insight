"""测试 CalibrationFlow 状态机转换（mock cap/face_mesh/audio/input）。"""
import time
import pytest
from unittest.mock import MagicMock, patch

from calibration.flow import CalibrationFlow, FlowState
from calibration.config import CalibrationConfig
from calibration.ui.panel import UIAction


def _make_flow(session_id="test"):
    config = CalibrationConfig(
        auto_baseline_seconds=0.1, closed_eyes_seconds=0.1,
        open_eyes_verify_seconds=0.05, squint_seconds=0.1,
        head_direction_seconds=0.05, blink_round_seconds=0.1,
        audio_enabled=False,  # 测试时禁音频
    )
    flow = CalibrationFlow(session_id=session_id, config=config)
    return flow


def test_flow_initial_state_is_waiting():
    f = _make_flow()
    assert f._state == FlowState.WAITING_TO_START_PHASE
    assert f._current_phase_index == 0


def test_flow_phase_starts_on_proceed():
    f = _make_flow()
    f._handle_action(UIAction.PROCEED, None)
    assert f._state == FlowState.PHASE_RUNNING


def test_flow_cancel_at_any_state_returns_none():
    f = _make_flow()
    f._handle_action(UIAction.CANCEL, None)
    assert f._cancelled is True
    assert f._compute_result() is None


def test_flow_phase_complete_success_transitions_to_summary():
    f = _make_flow()
    f._handle_action(UIAction.PROCEED, None)  # → RUNNING
    # 模拟阶段成功
    f._current_phase = MagicMock()
    f._current_phase.evaluate.return_value = MagicMock(success=True, summary={"ear_mean": 0.3})
    f._on_phase_time_up()
    assert f._state == FlowState.PHASE_SUMMARY_SUCCESS


def test_flow_phase_summary_proceed_advances_to_next_phase():
    f = _make_flow()
    f._state = FlowState.PHASE_SUMMARY_SUCCESS
    f._current_phase_index = 0
    f._handle_action(UIAction.PROCEED, None)
    assert f._current_phase_index == 1
    assert f._state == FlowState.WAITING_TO_START_PHASE


def test_flow_retry_resets_current_phase():
    f = _make_flow()
    f._state = FlowState.PHASE_SUMMARY_FAILED
    f._current_phase = MagicMock()
    f._handle_action(UIAction.RETRY_PHASE, None)
    f._current_phase.reset.assert_called_once()
    assert f._state == FlowState.PHASE_RUNNING


def test_flow_skip_advances_with_default_values():
    f = _make_flow()
    f._state = FlowState.PHASE_SUMMARY_FAILED
    f._current_phase_index = 1
    f._handle_action(UIAction.SKIP_PHASE, None)
    assert f._current_phase_index == 2


def test_flow_after_all_phases_enters_final_summary():
    f = _make_flow()
    f._current_phase_index = 4  # 最后一阶段
    f._state = FlowState.PHASE_SUMMARY_SUCCESS
    f._handle_action(UIAction.PROCEED, None)
    assert f._state == FlowState.FINAL_SUMMARY


def test_flow_final_proceed_marks_accepted_done():
    f = _make_flow()
    f._state = FlowState.FINAL_SUMMARY
    f._handle_action(UIAction.PROCEED, None)
    assert f._done is True
    assert f._user_accepted is True


def test_flow_final_retry_restarts_from_phase_0():
    f = _make_flow()
    f._state = FlowState.FINAL_SUMMARY
    f._handle_action(UIAction.RETRY_PHASE, None)
    assert f._current_phase_index == 0
    assert f._state == FlowState.WAITING_TO_START_PHASE


def test_flow_blink_input_digit_accumulates_buffer():
    f = _make_flow()
    f._state = FlowState.BLINK_INPUT_AWAITING
    f._handle_action(UIAction.DIGIT, "1")
    f._handle_action(UIAction.DIGIT, "5")
    assert f._input_buffer == "15"


# ============ T-CAL-18: 头部姿态子阶段 TTS 切换 ============

def test_head_pose_sub_phase_tts_via_tick_once(monkeypatch):
    """T-CAL-25: 头部姿态 4 个 sub-phase, click-to-advance 模式下, 用户点"继续"才 TTS 下一子阶段。

    真实通过 _handle_action(PROCEED) 验证: advance_sub_phase → 调 TTS 念新方向。
    """
    from calibration.phases.head_pose import HeadPosePhase

    f = _make_flow()
    f._current_phase_index = 3  # 阶段 3 = 头部姿态
    f._current_phase = HeadPosePhase(direction_seconds=3.0, min_degrees=12.0)
    # T-CAL-25: 模拟 _start_phase 已调 (进入 RUNNING, 已念过 tts_intro + idx=0 TTS)
    f._state = FlowState.PHASE_RUNNING
    f._tts = MagicMock()
    tts_calls = []
    f._tts.say.side_effect = lambda msg: tts_calls.append(msg)
    f._start_phase()  # 调 _start_phase 触发 tts_intro + idx=0 TTS

    # 第一次点继续: 应触发 idx=1 TTS '现在低头'
    f._state = FlowState.PHASE_SUMMARY_SUCCESS
    f._handle_action(UIAction.PROCEED, None)
    assert f._current_phase._current_sub_idx == 1
    assert any("现在低头" in c for c in tts_calls), (
        f"T-CAL-25: 第一次 PROCEED 应 TTS '现在低头', 实际 {tts_calls}"
    )

    # 第二次
    f._state = FlowState.PHASE_SUMMARY_SUCCESS
    f._handle_action(UIAction.PROCEED, None)
    assert f._current_phase._current_sub_idx == 2
    assert any("现在向左转" in c for c in tts_calls)

    # 第三次
    f._state = FlowState.PHASE_SUMMARY_SUCCESS
    f._handle_action(UIAction.PROCEED, None)
    assert f._current_phase._current_sub_idx == 3
    assert any("现在向右转" in c for c in tts_calls)

    # 第四次: 4 sub 全 advance, idx=4, evaluate 整体
    f._state = FlowState.PHASE_SUMMARY_SUCCESS
    f._handle_action(UIAction.PROCEED, None)
    assert f._current_phase._current_sub_idx == 4

    # 验证 4 个方向 TTS 都念过 (包括 idx=0 启动时)
    expected_phrases = ["现在抬头", "现在低头", "现在向左转", "现在向右转"]
    for phrase in expected_phrases:
        assert phrase in tts_calls, (
            f"T-CAL-25: 子阶段 '{phrase}' TTS 没念, 实际 tts_calls: {tts_calls}"
        )

    # 验证 4 个子阶段 TTS 都念过
    expected_phrases = ["现在抬头", "现在低头", "现在向左转", "现在向右转"]
    for phrase in expected_phrases:
        assert phrase in tts_calls, (
            f"T-CAL-18: 子阶段 '{phrase}' TTS 没念, 实际 tts_calls: {tts_calls}"
        )


def test_flow_blink_input_backspace_removes_last():
    f = _make_flow()
    f._state = FlowState.BLINK_INPUT_AWAITING
    f._input_buffer = "15"
    f._handle_action(UIAction.BACKSPACE, None)
    assert f._input_buffer == "1"


# ============ build_phase / display / compute_result 覆盖 ============

def test_flow_build_phase_0_auto_baseline():
    f = _make_flow()
    p = f._build_phase(0)
    assert p.name == "自动基线采集"


def test_flow_build_phase_1_closed_eyes():
    f = _make_flow()
    p = f._build_phase(1)
    assert "闭眼" in p.name


def test_flow_build_phase_2_squint():
    f = _make_flow()
    p = f._build_phase(2)
    assert "眯眼" in p.name


def test_flow_build_phase_3_head_pose():
    f = _make_flow()
    p = f._build_phase(3)
    assert "头部" in p.name


def test_flow_build_phase_4_blink_count():
    f = _make_flow()
    p = f._build_phase(4)
    assert "眨眼" in p.name


def test_flow_build_phase_invalid_raises():
    f = _make_flow()
    with pytest.raises(ValueError):
        f._build_phase(99)


def test_flow_get_baseline_ear_default():
    f = _make_flow()
    assert f._get_baseline_ear() == 0.30


def test_flow_get_ear_min_default():
    f = _make_flow()
    assert f._get_ear_min() == 0.08


def test_flow_compute_cqs_no_phases():
    f = _make_flow()
    assert f._compute_cqs() == 0.0


def test_flow_build_final_summary_dict():
    f = _make_flow()
    d = f._build_final_summary_dict()
    assert "EAR 基线" in d
    assert "CQS" in d


def test_flow_compute_result_cancelled_returns_none():
    f = _make_flow()
    f._cancelled = True
    assert f._compute_result() is None


def test_flow_compute_result_not_accepted_returns_none():
    f = _make_flow()
    f._user_accepted = False
    f._done = True
    assert f._compute_result() is None


def test_flow_compute_result_no_baseline_returns_none():
    f = _make_flow()
    f._user_accepted = True
    f._done = True
    # _phase_results[0] is None
    assert f._compute_result() is None


def test_flow_compute_result_with_baseline_success():
    from datetime import datetime
    f = _make_flow()
    f._user_accepted = True
    f._done = True
    f._phase_results[0] = MagicMock(success=True, summary={
        "ear_mean": 0.30, "yaw_mean": 0.0, "pitch_mean": 0.0,
    })
    f._phase_results[1] = MagicMock(success=True, summary={"ear_min": 0.08})
    f._phase_results[2] = MagicMock(success=True, summary={"ear_mid": 0.18})
    f._phase_results[3] = MagicMock(success=True, summary={
        "yaw_left_max": -15, "yaw_right_max": 15,
        "pitch_up_max": -10, "pitch_down_max": 10,
    })
    f._phase_results[4] = MagicMock(success=True, summary={
        "rounds": [], "final_adjustment_factor": 1.0, "baseline_blink_rate": 15.0,
    })
    r = f._compute_result()
    assert r is not None
    assert r.session_id == "test"
    assert r.cqs == 1.0
    assert r.is_accepted is True


def test_flow_build_display_info_in_running():
    f = _make_flow()
    f._state = FlowState.PHASE_RUNNING
    f._current_phase_index = 0
    f._current_phase = f._build_phase(0)
    f._phase_start_time = 0.0
    info = f._build_display_info()
    assert info.state == FlowState.PHASE_RUNNING
    assert info.phase_index == 1
    assert info.phase_name == "自动基线采集"


def test_flow_build_display_info_summary_success():
    f = _make_flow()
    f._state = FlowState.PHASE_SUMMARY_SUCCESS
    f._current_phase_index = 0
    f._current_phase = f._build_phase(0)
    f._phase_results[0] = MagicMock(success=True, summary={
        "ear_mean": 0.30, "ear_cv": 0.05, "sample_count": 100,
    })
    info = f._build_display_info()
    assert info.summary_text != ""


def test_flow_build_display_info_summary_failed():
    f = _make_flow()
    f._state = FlowState.PHASE_SUMMARY_FAILED
    f._current_phase_index = 0
    f._current_phase = f._build_phase(0)
    f._phase_results[0] = MagicMock(success=False, summary={}, failure_diagnosis="人脸未检测")
    info = f._build_display_info()
    assert "人脸未检测" in info.summary_text


def test_flow_on_phase_time_up_no_phase():
    f = _make_flow()
    f._current_phase = None
    f._on_phase_time_up()  # 不应崩


def test_flow_teardown_safety():
    f = _make_flow()
    f._cap = None  # 模拟未启动
    f._teardown()  # 不应崩


def test_flow_extract_metrics_no_detector():
    f = _make_flow()
    f._face_detector = None
    assert f._extract_metrics(None) == (None, None, None)


def test_flow_extract_metrics_detector_returns_not_detected():
    f = _make_flow()
    f._face_detector = MagicMock()
    f._face_detector.detect_from_frame.return_value = MagicMock(
        face_detected=False, landmarks=None, yaw=None, pitch=None
    )
    assert f._extract_metrics(None) == (None, None, None)


def test_flow_advance_past_last_enters_final():
    f = _make_flow()
    f._current_phase_index = 4
    f._state = FlowState.PHASE_SUMMARY_SUCCESS
    f._beep = MagicMock()
    f._tts = MagicMock()
    f._handle_action(UIAction.PROCEED, None)
    assert f._state == FlowState.FINAL_SUMMARY
    f._beep.calibration_complete.assert_called_once()
    f._tts.say.assert_called_with("校准完成")


def test_flow_skip_resets_consecutive_failures():
    f = _make_flow()
    f._consecutive_failures = 3
    f._state = FlowState.PHASE_SUMMARY_FAILED
    f._current_phase_index = 1
    f._handle_action(UIAction.SKIP_PHASE, None)
    assert f._consecutive_failures == 0


def test_flow_retry_increments_consecutive_failures():
    f = _make_flow()
    f._state = FlowState.PHASE_SUMMARY_FAILED
    f._current_phase = MagicMock()
    f._handle_action(UIAction.RETRY_PHASE, None)
    assert f._consecutive_failures == 1


# ============ _handle_blink_input_action / _start_phase / _on_phase_time_up ============

def test_flow_handle_blink_input_submit_with_invalid_int():
    """提交非数字 buffer 不崩（早期 return，不调用 phase）。"""
    f = _make_flow()
    from calibration.phases.blink_count import BlinkCountPhase
    f._state = FlowState.BLINK_INPUT_AWAITING
    f._input_buffer = "abc"
    f._current_phase = BlinkCountPhase(0.1, 1, 0.30, 0.08, 5, 60)
    f._handle_action(UIAction.SUBMIT, None)  # 早 return on ValueError, 不崩
    # buffer 仍是 "abc"（未被清空）


def test_flow_handle_blink_input_submit_accepted_advances():
    f = _make_flow()
    from calibration.phases.blink_count import BlinkCountPhase, BlinkCountState
    f._state = FlowState.BLINK_INPUT_AWAITING
    f._input_buffer = "10"
    f._current_phase = MagicMock(spec=BlinkCountPhase)
    f._current_phase.on_user_input.return_value = True
    f._current_phase.state = BlinkCountState.COUNTING
    f._handle_action(UIAction.SUBMIT, None)
    assert f._input_buffer == ""
    assert f._state == FlowState.PHASE_RUNNING


def test_flow_handle_blink_input_submit_done():
    f = _make_flow()
    from calibration.phases.blink_count import BlinkCountPhase, BlinkCountState
    f._state = FlowState.BLINK_INPUT_AWAITING
    f._input_buffer = "10"
    f._current_phase = MagicMock(spec=BlinkCountPhase)
    f._current_phase.on_user_input.return_value = True
    f._current_phase.state = BlinkCountState.DONE
    f._current_phase.evaluate.return_value = MagicMock(success=True, summary={})
    f._handle_action(UIAction.SUBMIT, None)
    assert f._state == FlowState.PHASE_SUMMARY_SUCCESS


def test_flow_handle_blink_input_submit_rejected():
    f = _make_flow()
    from calibration.phases.blink_count import BlinkCountPhase
    f._state = FlowState.BLINK_INPUT_AWAITING
    f._input_buffer = "999"
    f._current_phase = MagicMock(spec=BlinkCountPhase)
    f._current_phase.on_user_input.return_value = False
    f._handle_action(UIAction.SUBMIT, None)
    # 应留在 BLINK_INPUT_AWAITING


def test_flow_on_phase_time_up_success():
    f = _make_flow()
    f._current_phase = MagicMock()
    f._current_phase.evaluate.return_value = MagicMock(success=True, summary={"ear_mean": 0.3})
    f._beep = MagicMock()
    f._tts = MagicMock()
    f._on_phase_time_up()
    assert f._state == FlowState.PHASE_SUMMARY_SUCCESS
    f._beep.phase_success.assert_called_once()
    assert f._consecutive_failures == 0


def test_flow_on_phase_time_up_failed():
    f = _make_flow()
    f._current_phase = MagicMock()
    f._current_phase.evaluate.return_value = MagicMock(
        success=False, summary={}, failure_diagnosis="闭眼不够"
    )
    f._beep = MagicMock()
    f._tts = MagicMock()
    f._on_phase_time_up()
    assert f._state == FlowState.PHASE_SUMMARY_FAILED
    f._beep.phase_failed.assert_called_once()
    f._tts.say.assert_called_with("闭眼不够")


def test_flow_get_ear_mid_default():
    f = _make_flow()
    # r2 为 None → fallback baseline * 0.75
    assert f._get_ear_mid() == pytest.approx(0.30 * 0.75, abs=0.01)


def test_flow_get_yaw_range_default():
    f = _make_flow()
    assert f._get_yaw_range() == (-15.0, 15.0)


def test_flow_get_pitch_range_default():
    f = _make_flow()
    assert f._get_pitch_range() == (-10.0, 10.0)


def test_flow_handle_action_in_running_state_no_op():
    """RUNNING 状态下非 NONE 也未匹配分支：保持原状态。"""
    f = _make_flow()
    f._state = FlowState.PHASE_RUNNING
    f._handle_action(UIAction.RETRY_PHASE, None)  # RUNNING 不应响应 RETRY
    assert f._state == FlowState.PHASE_RUNNING


# ============ _tick_once 集成（mock camera） ============

def test_flow_tick_once_camera_fail():
    """_cap.read 返回 False 时 tick_once 不崩。"""
    f = _make_flow()
    f._beep = MagicMock()
    f._tts = MagicMock()
    f._panel = MagicMock()
    f._panel.render.return_value = MagicMock()
    f._panel.get_buttons.return_value = []
    f._input = MagicMock()
    f._input.poll.return_value = (UIAction.NONE, None)
    fake_cap = MagicMock()
    fake_cap.read.return_value = (False, None)
    f._cap = fake_cap
    f._face_detector = None
    with patch("cv2.imshow"), patch("cv2.getWindowProperty", return_value=1.0):
        f._tick_once()
    # 应不崩
    assert fake_cap.read.called


def test_flow_extract_metrics_detector_exception():
    f = _make_flow()
    f._face_detector = MagicMock()
    f._face_detector.detect_from_frame.side_effect = Exception("boom")
    assert f._extract_metrics(None) == (None, None, None)


def test_flow_extract_metrics_detected_no_ear():
    """face_detected=True 但没 landmarks/eye_detector → 仍应返回 (None, None, None)。"""
    f = _make_flow()
    f._face_detector = MagicMock()
    f._face_detector.detect_from_frame.return_value = MagicMock(
        face_detected=True, landmarks=None, yaw=None, pitch=None
    )
    f._eye_detector = None  # BUG-6 修复需要, 测试无 eye_detector 场景
    assert f._extract_metrics(None) == (None, None, None)


def test_flow_extract_metrics_with_eye_detector():
    """BUG-6 修复: 有 eye_detector + landmarks 时, ear 应非 None。"""
    f = _make_flow()
    f._face_detector = MagicMock()
    f._face_detector.detect_from_frame.return_value = MagicMock(
        face_detected=True,
        landmarks=MagicMock(),
        yaw=10.0,
        pitch=5.0,
    )
    f._eye_detector = MagicMock()
    f._eye_detector.compute.return_value = MagicMock()
    f._eye_detector.get_current_ear.return_value = 0.3
    ear, yaw, pitch = f._extract_metrics(None)
    assert ear == 0.3
    assert yaw == 10.0
    assert pitch == 5.0

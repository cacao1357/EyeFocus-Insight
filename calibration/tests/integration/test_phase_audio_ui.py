"""集成测试：阶段切换时 UI/音频同步触发。"""
from unittest.mock import MagicMock

from calibration.flow import CalibrationFlow, FlowState
from calibration.config import CalibrationConfig
from calibration.ui.panel import UIAction


def test_phase_start_triggers_tts_intro():
    config = CalibrationConfig(audio_enabled=True, auto_baseline_seconds=0.1)
    f = CalibrationFlow(session_id="t", config=config)
    f._tts = MagicMock()
    f._beep = MagicMock()
    f._handle_action(UIAction.PROCEED, None)
    # 阶段开始应调 TTS + beep
    f._tts.say.assert_called()
    f._beep.phase_start.assert_called_once()


def test_closed_eyes_complete_tts_contains_open_keyword():
    """BUG 3 修复回归：闭眼阶段 tts_complete 必含'睁眼'。"""
    config = CalibrationConfig(audio_enabled=True,
                              auto_baseline_seconds=0.05,
                              closed_eyes_seconds=0.05)
    f = CalibrationFlow(session_id="t", config=config)
    f._tts = MagicMock()
    f._beep = MagicMock()
    # 跳到 closed_eyes 阶段
    f._current_phase_index = 1
    f._current_phase = f._build_phase(1)
    f._state = FlowState.PHASE_RUNNING
    # 模拟时间到
    f._current_phase.evaluate = MagicMock(return_value=MagicMock(success=True, summary={}))
    f._on_phase_time_up()
    # TTS 应念含"睁眼"的话
    all_tts_calls = " ".join(c.args[0] for c in f._tts.say.call_args_list)
    assert "睁眼" in all_tts_calls

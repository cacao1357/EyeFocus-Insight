"""集成测试：取消路径（ESC / 点取消 / 关窗）。"""
from unittest.mock import MagicMock

from calibration.flow import CalibrationFlow, FlowState
from calibration.config import CalibrationConfig
from calibration.ui.panel import UIAction


def test_cancel_at_waiting_returns_none():
    f = CalibrationFlow(session_id="t", config=CalibrationConfig())
    f._handle_action(UIAction.CANCEL, None)
    assert f._cancelled is True
    assert f._compute_result() is None


def test_cancel_at_running_returns_none():
    f = CalibrationFlow(session_id="t", config=CalibrationConfig())
    f._state = FlowState.PHASE_RUNNING
    f._current_phase_index = 2
    f._handle_action(UIAction.CANCEL, None)
    assert f._cancelled is True
    assert f._compute_result() is None


def test_cancel_at_final_summary_returns_none():
    """E1 设计：FINAL_SUMMARY 阶段点'退出'也是 CANCEL = 返回 None。"""
    f = CalibrationFlow(session_id="t", config=CalibrationConfig())
    f._state = FlowState.FINAL_SUMMARY
    f._handle_action(UIAction.CANCEL, None)
    assert f._cancelled is True
    assert f._compute_result() is None

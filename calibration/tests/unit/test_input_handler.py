"""测试 InputHandler — 鼠标 + 键盘（IME 兼容）。"""
import pytest
from unittest.mock import patch
import cv2

from calibration.input_handler import InputHandler
from calibration.ui.panel import Button, UIAction, FlowState


def _make_buttons():
    return [
        Button("开始", (10, 10, 100, 50), UIAction.PROCEED, "primary"),
        Button("0", (200, 70, 50, 40), UIAction.DIGIT, "neutral", digit_value="0"),
        Button("5", (200, 110, 50, 40), UIAction.DIGIT, "neutral", digit_value="5"),
        Button("确认", (300, 100, 100, 40), UIAction.SUBMIT, "primary"),
        Button("取消", (400, 10, 100, 40), UIAction.CANCEL, "danger"),
    ]


def test_mouse_click_hits_proceed_button():
    h = InputHandler.__new__(InputHandler)
    h._buttons = _make_buttons()
    h._panel_y_offset = 0  # 测试场景默认 0
    h._click_buffer = (50, 30)  # 命中"开始"
    with patch("cv2.waitKey", return_value=255):  # 无键盘输入
        action, digit = h.poll(FlowState.WAITING_TO_START_PHASE)
    assert action == UIAction.PROCEED
    assert digit is None


def test_mouse_click_hits_digit_5():
    h = InputHandler.__new__(InputHandler)
    h._buttons = _make_buttons()
    h._panel_y_offset = 0
    h._click_buffer = (220, 125)
    with patch("cv2.waitKey", return_value=255):
        action, digit = h.poll(FlowState.BLINK_INPUT_AWAITING)
    assert action == UIAction.DIGIT
    assert digit == "5"


def test_mouse_click_misses_all_buttons():
    h = InputHandler.__new__(InputHandler)
    h._buttons = _make_buttons()
    h._panel_y_offset = 0
    h._click_buffer = (999, 999)
    with patch("cv2.waitKey", return_value=255):
        action, digit = h.poll(FlowState.WAITING_TO_START_PHASE)
    assert action == UIAction.NONE


def test_keyboard_digit_in_blink_input_state():
    h = InputHandler.__new__(InputHandler)
    h._buttons = []
    h._click_buffer = None
    with patch("cv2.waitKey", return_value=ord('7')):
        action, digit = h.poll(FlowState.BLINK_INPUT_AWAITING)
    assert action == UIAction.DIGIT
    assert digit == "7"


def test_keyboard_digit_ignored_outside_blink_input():
    """非 BLINK_INPUT 状态下，键盘数字键被忽略（IME 兼容设计）。"""
    h = InputHandler.__new__(InputHandler)
    h._buttons = []
    h._click_buffer = None
    with patch("cv2.waitKey", return_value=ord('5')):
        action, digit = h.poll(FlowState.PHASE_RUNNING)
    assert action == UIAction.NONE


def test_keyboard_enter_submits_in_blink_input():
    h = InputHandler.__new__(InputHandler)
    h._buttons = []
    h._click_buffer = None
    with patch("cv2.waitKey", return_value=13):
        action, digit = h.poll(FlowState.BLINK_INPUT_AWAITING)
    assert action == UIAction.SUBMIT


def test_keyboard_backspace_in_blink_input():
    h = InputHandler.__new__(InputHandler)
    h._buttons = []
    h._click_buffer = None
    with patch("cv2.waitKey", return_value=8):
        action, digit = h.poll(FlowState.BLINK_INPUT_AWAITING)
    assert action == UIAction.BACKSPACE


def test_keyboard_esc_works_in_any_state():
    """ESC 是所有状态的紧急取消兜底。"""
    h = InputHandler.__new__(InputHandler)
    h._buttons = []
    h._click_buffer = None
    for state in [FlowState.PHASE_RUNNING, FlowState.WAITING_TO_START_PHASE,
                  FlowState.FINAL_SUMMARY]:
        with patch("cv2.waitKey", return_value=27):
            action, _ = h.poll(state)
        assert action == UIAction.CANCEL, f"ESC 在 {state} 应触发 CANCEL"


def test_mouse_takes_priority_over_keyboard():
    """鼠标点击 vs 键盘同时：鼠标优先（视觉操作更明确）。"""
    h = InputHandler.__new__(InputHandler)
    h._buttons = _make_buttons()
    h._panel_y_offset = 0
    h._click_buffer = (50, 30)  # 点"开始"
    with patch("cv2.waitKey", return_value=27):  # ESC
        action, _ = h.poll(FlowState.WAITING_TO_START_PHASE)
    assert action == UIAction.PROCEED  # 不是 CANCEL


def test_click_buffer_cleared_after_poll():
    h = InputHandler.__new__(InputHandler)
    h._buttons = _make_buttons()
    h._panel_y_offset = 0
    h._click_buffer = (50, 30)
    with patch("cv2.waitKey", return_value=255):
        h.poll(FlowState.WAITING_TO_START_PHASE)
    assert h._click_buffer is None


def test_init_sets_mouse_callback():
    """__init__ 应注册 cv2 mouse callback。"""
    with patch("cv2.setMouseCallback") as mock_cb:
        h = InputHandler("fake_window")
        mock_cb.assert_called_once()
        assert h._window_name == "fake_window"
        assert h._buttons == []
        assert h._click_buffer is None


def test_init_handles_missing_window():
    """窗口未创建时 setMouseCallback 抛 cv2.error — 应被吞掉不崩。"""
    import cv2 as cv2_mod
    with patch("cv2.setMouseCallback", side_effect=cv2_mod.error("no window")):
        h = InputHandler("nonexistent")  # 不应抛异常
        assert h._window_name == "nonexistent"


def test_register_buttons_replaces_list():
    h = InputHandler.__new__(InputHandler)
    h._buttons = _make_buttons()
    new_buttons = [Button("X", (0, 0, 50, 50), UIAction.CANCEL, "danger")]
    h.register_buttons(new_buttons)
    assert h._buttons == new_buttons


def test_on_mouse_left_button_sets_buffer():
    h = InputHandler.__new__(InputHandler)
    h._click_buffer = None
    h._on_mouse(cv2.EVENT_MOUSEMOVE, 100, 50, 0, None)  # MOUSEMOVE 不触发
    assert h._click_buffer is None
    h._on_mouse(cv2.EVENT_LBUTTONUP, 100, 50, 0, None)  # LBUTTONUP 不触发
    assert h._click_buffer is None


def test_on_mouse_left_click_buffers_position():
    h = InputHandler.__new__(InputHandler)
    h._click_buffer = None
    h._on_mouse(cv2.EVENT_LBUTTONDOWN, 123, 456, 0, None)
    assert h._click_buffer == (123, 456)

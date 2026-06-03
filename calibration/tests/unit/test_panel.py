"""测试 panel.render 按状态生成图像 + get_buttons 返回正确数量按钮。"""
import numpy as np
import pytest

from calibration.ui.panel import (
    Panel, Button, UIAction, FlowState, PhaseDisplayInfo,
)


def _make_panel():
    return Panel(width=640, height=240)


def test_render_waiting_to_start_returns_image():
    p = _make_panel()
    info = PhaseDisplayInfo(
        state=FlowState.WAITING_TO_START_PHASE,
        phase_index=1, phase_total=5, phase_name="闭眼校准",
        instruction="请闭眼并保持 5 秒",
    )
    img = p.render(info)
    assert img.shape == (240, 640, 3)
    assert img.dtype == np.uint8


def test_waiting_to_start_has_start_and_cancel_buttons():
    p = _make_panel()
    info = PhaseDisplayInfo(state=FlowState.WAITING_TO_START_PHASE,
                            phase_index=1, phase_total=5,
                            phase_name="X", instruction="Y")
    btns = p.get_buttons(info)
    actions = {b.action for b in btns}
    assert UIAction.PROCEED in actions
    assert UIAction.CANCEL in actions


def test_phase_summary_success_has_3_buttons():
    p = _make_panel()
    info = PhaseDisplayInfo(
        state=FlowState.PHASE_SUMMARY_SUCCESS,
        phase_index=1, phase_total=5, phase_name="X", instruction="",
        summary_text="✓ 完成，138 样本",
    )
    btns = p.get_buttons(info)
    actions = {b.action for b in btns}
    assert {UIAction.PROCEED, UIAction.RETRY_PHASE, UIAction.CANCEL} <= actions


def test_phase_summary_failed_has_3_buttons():
    p = _make_panel()
    info = PhaseDisplayInfo(
        state=FlowState.PHASE_SUMMARY_FAILED,
        phase_index=1, phase_total=5, phase_name="X", instruction="",
        summary_text="✗ 失败：未完全闭眼",
    )
    btns = p.get_buttons(info)
    actions = {b.action for b in btns}
    assert {UIAction.RETRY_PHASE, UIAction.SKIP_PHASE, UIAction.CANCEL} <= actions


def test_blink_input_has_digit_keypad_buttons():
    """BLINK_INPUT_AWAITING 状态有 0-9 + 退格 + 确认 + 取消 = 13 个按钮。"""
    p = _make_panel()
    info = PhaseDisplayInfo(
        state=FlowState.BLINK_INPUT_AWAITING,
        phase_index=4, phase_total=5, phase_name="眨眼", instruction="",
        program_blink_count=12, user_input_buffer="",
    )
    btns = p.get_buttons(info)
    digit_buttons = [b for b in btns if b.action == UIAction.DIGIT]
    assert len(digit_buttons) == 10  # 0-9
    actions = {b.action for b in btns}
    assert UIAction.BACKSPACE in actions
    assert UIAction.SUBMIT in actions
    assert UIAction.CANCEL in actions


def test_blink_input_digit_buttons_have_distinct_values():
    p = _make_panel()
    info = PhaseDisplayInfo(state=FlowState.BLINK_INPUT_AWAITING,
                            phase_index=4, phase_total=5, phase_name="X",
                            instruction="", program_blink_count=10,
                            user_input_buffer="")
    btns = p.get_buttons(info)
    digit_values = {b.digit_value for b in btns if b.action == UIAction.DIGIT}
    assert digit_values == {"0","1","2","3","4","5","6","7","8","9"}


def test_button_contains_hit_test():
    """Button.contains(x, y) 命中测试。"""
    b = Button(label="X", rect=(10, 20, 100, 50), action=UIAction.PROCEED)
    assert b.contains(50, 40) is True
    assert b.contains(5, 40) is False  # x 在 rect 外
    assert b.contains(50, 80) is False  # y 在 rect 外


def test_final_summary_has_3_buttons():
    p = _make_panel()
    info = PhaseDisplayInfo(
        state=FlowState.FINAL_SUMMARY,
        phase_index=5, phase_total=5, phase_name="校准完成", instruction="",
        final_summary={"ear_mean": 0.30, "cqs": 0.85},
    )
    btns = p.get_buttons(info)
    actions = {b.action for b in btns}
    assert UIAction.PROCEED in actions       # 继续 → 主监测
    assert UIAction.RETRY_PHASE in actions   # 重新校准
    assert UIAction.CANCEL in actions        # 退出

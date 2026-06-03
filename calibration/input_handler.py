"""calibration/input_handler.py — 统一鼠标 + 键盘输入

主输入路径：鼠标点击（彻底消除 Windows IME 影响）。
键盘只作可选加速 — BLINK_INPUT_AWAITING 状态收数字/退格/Enter，其他状态仅 ESC。

设计依据：spec §2.7 + 决策 C2 鼠标主导。
"""
from typing import List, Optional, Tuple

import cv2

from calibration.ui.panel import Button, FlowState, UIAction


class InputHandler:
    """每帧调 poll() 获取鼠标/键盘动作。"""

    def __init__(self, window_name: str):
        self._window_name = window_name
        self._buttons: List[Button] = []
        self._click_buffer: Optional[Tuple[int, int]] = None
        try:
            cv2.setMouseCallback(window_name, self._on_mouse)
        except cv2.error:
            # 窗口未创建（测试场景）— 忽略
            pass

    def register_buttons(self, buttons: List[Button]) -> None:
        """每帧由 panel 注册当前可见按钮。"""
        self._buttons = buttons

    def poll(self, state: FlowState) -> Tuple[UIAction, Optional[str]]:
        """返回 (动作, 数字字符)。数字仅 DIGIT 动作时有效。"""
        # 1. 鼠标点击优先
        if self._click_buffer is not None:
            x, y = self._click_buffer
            self._click_buffer = None
            for btn in self._buttons:
                if btn.contains(x, y):
                    if btn.action == UIAction.DIGIT:
                        return (UIAction.DIGIT, btn.digit_value)
                    return (btn.action, None)

        # 2. 键盘（IME 激活时可能收不到，但有就用）
        key = cv2.waitKey(1) & 0xFF

        # ESC 任何状态都触发 CANCEL（兜底）
        if key == 27:
            return (UIAction.CANCEL, None)

        # 仅 BLINK_INPUT_AWAITING 接受数字/退格/Enter
        if state == FlowState.BLINK_INPUT_AWAITING:
            if ord('0') <= key <= ord('9'):
                return (UIAction.DIGIT, chr(key))
            if key == 8:
                return (UIAction.BACKSPACE, None)
            if key == 13:
                return (UIAction.SUBMIT, None)

        return (UIAction.NONE, None)

    def _on_mouse(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self._click_buffer = (x, y)

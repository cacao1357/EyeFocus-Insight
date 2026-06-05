"""calibration/input_handler.py — 统一鼠标 + 键盘输入

主输入路径：鼠标点击（彻底消除 Windows IME 影响）。
键盘只作可选加速 — BLINK_INPUT_AWAITING 状态收数字/退格/Enter，其他状态仅 ESC。

设计依据：spec §2.7 + 决策 C2 鼠标主导。
"""
from typing import Callable, List, Optional, Tuple

import cv2

from calibration.ui.panel import Button, FlowState, UIAction


class InputHandler:
    """每帧调 poll() 获取鼠标/键盘动作。"""

    def __init__(self, window_name: str, panel_y_offset: int = 0):
        """初始化。

        Args:
            window_name: cv2 窗口名
            panel_y_offset: 视频区高度（像素）。cv2 鼠标事件返回 (x, y) 是 composed
                图像坐标（视频在上，panel 在下），需减去此 offset 才能匹配 button.rect
                的 panel 局部坐标。视频 480 + panel 240 = 720 composed。
                BUG-2 修复点。
        """
        self._window_name = window_name
        self._panel_y_offset = panel_y_offset
        self._buttons: List[Button] = []
        self._click_buffer: Optional[Tuple[int, int]] = None
        # v4.4: 回调让 CalibrationFlow 追踪 waitKey 返回时间
        self._on_waitkey_return: Optional[Callable[[], None]] = None
        try:
            cv2.setMouseCallback(window_name, self._on_mouse)
        except cv2.error:
            # 窗口未创建（测试场景）— 忽略
            pass

    def set_waitkey_callback(self, callback: Callable[[], None]) -> None:
        """v4.4: 设置 waitKey 返回后回调, 用于 CalibrationFlow 追踪拖窗口检测"""
        self._on_waitkey_return = callback

    def register_buttons(self, buttons: List[Button]) -> None:
        """每帧由 panel 注册当前可见按钮。"""
        self._buttons = buttons

    def poll(self, state: FlowState) -> Tuple[UIAction, Optional[str]]:
        """返回 (动作, 数字字符)。数字仅 DIGIT 动作时有效。"""
        # 1. 先消费之前累积的 click（来自上一次 waitKey）
        if self._click_buffer is not None:
            x, y = self._click_buffer
            self._click_buffer = None
            # 转换 composed 坐标 → panel 局部坐标（BUG-2 修复）
            panel_y = y - self._panel_y_offset
            for btn in self._buttons:
                if btn.contains(x, panel_y):
                    if btn.action == UIAction.DIGIT:
                        return (UIAction.DIGIT, btn.digit_value)
                    return (btn.action, None)
            # click_buffer 消费完但没命中按钮 — 落到键盘检查（避免 1-tick 延迟）

        # 2. waitKey 排空 OS 事件队列 — 鼠标 click 在这里 set _click_buffer
        key = cv2.waitKey(1) & 0xFF
        # v4.4: 立即更新 _last_waitkey_time (CalibrationFlow 拖窗口检测用)
        if self._on_waitkey_return is not None:
            self._on_waitkey_return()

        # 3. 再次检查 click_buffer（BUG-3 修复：waitKey 期间设置的 click 不能漏）
        if self._click_buffer is not None:
            x, y = self._click_buffer
            self._click_buffer = None
            panel_y = y - self._panel_y_offset
            for btn in self._buttons:
                if btn.contains(x, panel_y):
                    if btn.action == UIAction.DIGIT:
                        return (UIAction.DIGIT, btn.digit_value)
                    return (btn.action, None)

        # 4. ESC 任何状态都触发 CANCEL（兜底）
        if key == 27:
            return (UIAction.CANCEL, None)

        # 5. 仅 BLINK_INPUT_AWAITING 接受数字/退格/Enter
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

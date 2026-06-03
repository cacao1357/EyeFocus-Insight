"""测试 BUG-2 修复：InputHandler 必须知道 panel_y_offset。

BUG-2 根因：cv2.setMouseCallback 返回 (x, y) 是 composed 图像坐标（高度 720
= 视频 480 + 面板 240），但 button.rect 是 panel 局部坐标（高度 240）。
点击 panel 区时 y 多 480，导致 contains() 永远 False → 用户"无法点击"。

修复：InputHandler 知道 panel_y_offset，poll() 转换 click y 再匹配。
"""
import cv2
from unittest.mock import patch

from calibration.input_handler import InputHandler
from calibration.ui.panel import Button, UIAction, FlowState


def _make_handler(panel_offset=480):
    """构造一个不真正注册 cv2 回调的 InputHandler。"""
    with patch("calibration.input_handler.cv2.setMouseCallback"):
        return InputHandler("test_window", panel_y_offset=panel_offset)


def test_click_in_panel_region_hits_button():
    """点击 panel 区（composed y = 480+170=650）应命中 button at panel y=170。"""
    h = _make_handler(panel_offset=480)
    h.register_buttons([Button("开始", (40, 170, 160, 50), UIAction.PROCEED)])

    # 模拟 composed 坐标的点击 (panel 中部 100, 650)
    h._click_buffer = (100, 650)
    with patch("cv2.waitKey", return_value=255):
        action, _ = h.poll(FlowState.WAITING_TO_START_PHASE)
    assert action == UIAction.PROCEED, (
        f"Expected PROCEED, got {action}. "
        "BUG-2: panel y 坐标未转换，composed y=650 ≠ panel y=170"
    )


def test_click_in_video_region_misses_button():
    """点击 video 区（composed y < 480）不应命中 panel 按钮。"""
    h = _make_handler(panel_offset=480)
    h.register_buttons([Button("开始", (40, 170, 160, 50), UIAction.PROCEED)])

    # 模拟 video 区点击 (100, 300) — 完全在视频里
    h._click_buffer = (100, 300)
    with patch("cv2.waitKey", return_value=255):
        action, _ = h.poll(FlowState.WAITING_TO_START_PHASE)
    assert action == UIAction.NONE


def test_click_offset_exact_boundary():
    """精确边界：composed y = panel_y + offset 命中；y-1 漏掉。"""
    h = _make_handler(panel_offset=480)
    h.register_buttons([Button("X", (40, 170, 160, 50), UIAction.PROCEED)])

    # composed y = 170 + 480 = 650 → panel y = 170 → 命中
    h._click_buffer = (100, 650)
    with patch("cv2.waitKey", return_value=255):
        action, _ = h.poll(FlowState.WAITING_TO_START_PHASE)
    assert action == UIAction.PROCEED


def test_no_offset_legacy_behavior():
    """panel_y_offset=0 时行为不变（兼容测试场景）。"""
    h = _make_handler(panel_offset=0)
    h.register_buttons([Button("X", (40, 170, 160, 50), UIAction.PROCEED)])

    h._click_buffer = (100, 170)  # panel-local 直接命中
    with patch("cv2.waitKey", return_value=255):
        action, _ = h.poll(FlowState.WAITING_TO_START_PHASE)
    assert action == UIAction.PROCEED


def test_poll_processes_click_set_during_waitkey():
    """BUG-3 修复：waitKey 期间设置的 click_buffer 必须被处理（1-tick race）。

    真机日志证据：用户点击 (142, 668) 实际在 poll() 进入后才被 waitKey 派发，
    当前实现：poll 入口检查 buffer (None) → 走到 waitKey → 设置 buffer → 返回 NONE
    下一 tick 才消费该 click。

    修复后：poll 必须在 waitKey 之后再检查一次 buffer。
    """
    h = _make_handler(panel_offset=480)
    h.register_buttons([Button("X", (40, 170, 160, 50), UIAction.PROCEED)])

    # 模拟 waitKey 期间用户点击 (composed y=650 → panel y=170)
    def fake_waitkey(delay):
        h._click_buffer = (100, 650)
        return 255
    with patch("cv2.waitKey", side_effect=fake_waitkey):
        action, _ = h.poll(FlowState.WAITING_TO_START_PHASE)
    assert action == UIAction.PROCEED, (
        f"Expected PROCEED, got {action}. "
        "BUG-3: poll() 不处理 waitKey 期间 set 的 click_buffer"
    )

"""calibration/_ime.py — Win32 IME 禁用兜底（失败也无所谓）

仅作锦上添花。主输入路径是鼠标点屏幕键盘，不依赖此函数。

设计依据：spec §2.7 鼠标主导 + IME 可选禁用。
"""
import logging

logger = logging.getLogger("eyefocus.calibration.ime")


def try_disable_ime(window_name: str) -> bool:
    """尝试禁用 IME。失败时返回 False，不抛异常。"""
    try:
        import ctypes
        # cv2 窗口的 HWND 获取在 OpenCV 中不直接暴露，这里只是占位
        # 实际生产可用 ctypes 调 user32.FindWindowW 找窗口，再 imm32.ImmAssociateContext
        # 因平台兼容性差，此函数允许永远 return False
        return False
    except Exception as e:
        logger.warning("IME 禁用失败（不影响主功能）: %s", e)
        return False

"""calibration/ui/layout.py — 上下分屏拼合

将摄像头帧（640×480）与 UI 面板（640×240）用 cv2.vconcat 拼成 640×720。
视频区不被 UI 遮挡（BUG 2 修复点）。

设计依据：spec §2.3 + 决策 L1。
"""
import cv2
import numpy as np


def compose(camera_frame: np.ndarray, panel_img: np.ndarray) -> np.ndarray:
    """拼合视频 + 面板。

    Args:
        camera_frame: shape (480, 640, 3) BGR
        panel_img: shape (h, 640, 3) BGR

    Returns:
        shape (480+h, 640, 3) BGR
    """
    if camera_frame.shape[1] != panel_img.shape[1]:
        raise ValueError(
            f"宽度不匹配：camera {camera_frame.shape[1]} vs panel {panel_img.shape[1]}"
        )
    return cv2.vconcat([camera_frame, panel_img])

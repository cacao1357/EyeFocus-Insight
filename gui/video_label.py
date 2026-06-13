"""
gui/video_label.py — Qt 视频帧显示组件

将 OpenCV (BGR) 帧转换为 QPixmap 并显示在 QLabel 上。
帧通过线程安全队列传递，避免 GIL 竞争。
"""

import logging
from typing import Optional

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

logger = logging.getLogger("eyefocus.gui.qt")


class FrameBuffer:
    """线程安全的单帧缓冲区（替代 queue.Queue 避免不必要的序列化）

    CameraManager 写入帧，Qt 主线程读取最新帧。
    仅保留最新一帧，丢弃过期帧以保持低延迟。
    """

    def __init__(self):
        self._frame: Optional[np.ndarray] = None

    def write(self, frame: np.ndarray) -> None:
        """写入最新帧（CameraManager 线程调用）"""
        self._frame = frame

    def read(self) -> Optional[np.ndarray]:
        """读取最新帧（Qt 主线程调用）"""
        return self._frame

    def clear(self) -> None:
        self._frame = None


class VideoLabel(QLabel):
    """显示摄像头视频帧的 QLabel

    自动缩放保持宽高比，接收 np.ndarray (BGR) 帧。
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #000000;")
        self._frame_size: tuple = (640, 480)

    def display_frame(self, frame: np.ndarray) -> None:
        """显示一帧 OpenCV 图像 (BGR → RGB → QPixmap)

        Args:
            frame: BGR 格式的 numpy 数组
        """
        if frame is None:
            return

        h, w = frame.shape[:2]
        self._frame_size = (w, h)

        # BGR → RGB
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        bytes_per_line = rgb.strides[0]
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)

        # 缩放到 QLabel 尺寸 (保持宽高比)
        pixmap = QPixmap.fromImage(qimg)
        scaled = pixmap.scaled(
            self.size(),
            Qt.KeepAspectRatioByExpanding,  # v4.5.5: 填满区域消除黑边
            Qt.SmoothTransformation,
        )
        self.setPixmap(scaled)

    @property
    def frame_width(self) -> int:
        return self._frame_size[0]

    @property
    def frame_height(self) -> int:
        return self._frame_size[1]

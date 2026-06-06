"""
gui/qt_window.py — EyeFocus Qt 主窗口

替换 OpenCV 的 cv2.imshow + cv2.waitKey 主循环。
使用 QTimer 驱动帧更新，QKeyEvent 处理键盘输入。
"""

import logging
from typing import Optional

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont, QKeyEvent
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from gui.qt_overlay import (
    FocusCircle,
    MinimalOverlay,
    TopStatusBar,
)
from gui.video_label import FrameBuffer, VideoLabel

logger = logging.getLogger("eyefocus.gui.qt")


class KeyHintBar(QWidget):
    """底部常驻快捷键提示"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setStyleSheet("background-color: #1a1a1a; border-top: 1px solid #333;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 2, 12, 2)
        hint = QLabel("[Q]退出  [C]校准  [P]暂停  [Tab]面板")
        hint.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(hint)


class EyeFocusWindow(QMainWindow):
    """EyeFocus Insight Qt 主窗口

    使用 QStackedWidget 切换极简/完整模式。
    帧通过 FrameBuffer 从 CameraManager 接收。
    """

    # 退出信号 — 连接 main.py 的 shutdown
    exit_requested = pyqtSignal()

    def __init__(self, frame_buffer: FrameBuffer, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._frame_buffer = frame_buffer
        self._minimal_mode: bool = True

        self._focus_score: Optional[float] = None
        self._fatigue_level: Optional[str] = None
        self._face_detected: bool = True
        self._eye_detected: bool = True
        self._glasses_str: Optional[str] = None
        self._fps: float = 0.0
        self._mode: str = "MONITORING"

        # ── 窗口设置 ──
        self.setWindowTitle("EyeFocus Insight")
        self.setMinimumSize(640, 480)
        self.resize(800, 600)
        self.setStyleSheet("background-color: #1a1a1a; color: white;")

        # ── 中央组件 ──
        central = QWidget()
        self.setCentralWidget(central)
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # 顶栏 (完整模式才显示)
        self._status_bar = TopStatusBar()
        self._status_bar.hide()
        outer_layout.addWidget(self._status_bar)

        # 视频区域 (video + overlay 叠加)
        self._video_container = QWidget()
        self._video_container.setStyleSheet("background-color: #1a1a1a;")
        video_layout = QVBoxLayout(self._video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)

        self._video_label = VideoLabel()
        video_layout.addWidget(self._video_label)

        outer_layout.addWidget(self._video_container, 1)

        # ── 极简 Overlay (叠加在 video 上方) ──
        self._minimal_overlay = MinimalOverlay(self._video_container)
        self._minimal_overlay.show()

        # ── 完整模式 Overlay (叠加在 video 上方, 默认隐藏) ──
        self._full_overlay = QWidget(self._video_container)
        self._full_overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._full_overlay.setAttribute(Qt.WA_StyledBackground, False)
        self._full_overlay.hide()
        full_layout = QVBoxLayout(self._full_overlay)
        full_layout.setContentsMargins(0, 0, 0, 0)

        # 右下专注度圆环
        self._focus_circle = FocusCircle()
        full_layout.addStretch()
        circle_row = QHBoxLayout()
        circle_row.addStretch()
        circle_row.addWidget(self._focus_circle)
        full_layout.addLayout(circle_row)

        # ── 底栏 ──
        self._key_hints = KeyHintBar()
        outer_layout.addWidget(self._key_hints)

        # ── 帧更新定时器 (~30 FPS) ──
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_frame)
        self._timer.setInterval(33)  # ~30fps

        # FPS 计算
        self._fps_counter = 0
        self._fps_last_time = 0.0

        # 暂停状态
        self._paused: bool = False
        # Q 退出倒计时
        self._quit_pending: bool = False
        self._quit_start: float = 0.0

    # ── 公共 API ──

    def start(self) -> None:
        """启动帧更新定时器"""
        import time
        self._fps_last_time = time.time()
        self._timer.start()

    def stop(self) -> None:
        """停止帧更新"""
        self._timer.stop()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._status_bar.update_data(mode=mode)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def update_data(self, focus_score: Optional[float] = None,
                    fatigue_level: Optional[str] = None,
                    face_detected: bool = True,
                    eye_detected: bool = True,
                    glasses_str: Optional[str] = None,
                    fps: float = 0.0) -> None:
        self._focus_score = focus_score
        self._fatigue_level = fatigue_level
        self._face_detected = face_detected
        self._eye_detected = eye_detected
        self._glasses_str = glasses_str
        self._fps = fps

    def update_data_from_processor(self, frame_processor) -> None:
        """从 FrameProcessor 读取最新分析结果"""
        from gui.overlay import FocusOverlay
        fr = frame_processor.latest_focus_result
        fa = frame_processor.latest_fatigue_result
        face = frame_processor.latest_face_detected
        glasses = frame_processor.latest_glasses_result

        focus_score = None
        fatigue_level = None
        glasses_str = None
        if fr is not None:
            focus_score = fr.focus_score
        if fa is not None:
            level = fa.fatigue_level
            fatigue_level = level.value.upper() if hasattr(level, 'value') else str(level)
        if glasses is not None:
            glasses_str = "ON" if glasses.is_glasses else "OFF"

        self.update_data(
            focus_score=focus_score,
            fatigue_level=fatigue_level,
            face_detected=face,
            eye_detected=frame_processor.latest_face_detected,
            glasses_str=glasses_str,
            fps=frame_processor._app.fps if hasattr(frame_processor, '_app') else 0.0,
        )

    # ── 内部 ──

    def _update_frame(self) -> None:
        """QTimer 回调：读取帧 → 处理 → 显示 → 更新 overlay"""
        import time

        frame = self._frame_buffer.read()
        if frame is not None:
            self._video_label.display_frame(frame)

        # 更新 overlay 数据
        self._update_overlays()

        # FPS
        self._fps_counter += 1
        elapsed = time.time() - self._fps_last_time
        if elapsed >= 1.0:
            self._fps = self._fps_counter / elapsed
            self._fps_counter = 0
            self._fps_last_time = time.time()

        # Q 退出倒计时
        if self._quit_pending:
            if time.time() - self._quit_start > 1.0:
                logger.info("用户退出 (Q auto)")
                self.exit_requested.emit()

    def _update_overlays(self) -> None:
        """更新所有 overlay 组件的显示数据"""
        # 极简模式
        self._minimal_overlay.update_data(
            focus_score=self._focus_score,
            fatigue_level=self._fatigue_level,
            face_detected=self._face_detected,
            eye_detected=self._eye_detected,
        )

        # 完整模式顶栏
        self._status_bar.update_data(
            mode=self._mode,
            focus_score=self._focus_score,
            fatigue_level=self._fatigue_level,
            face_detected=self._face_detected,
            eye_detected=self._eye_detected,
            glasses_str=self._glasses_str,
        )

        # 完整模式圆环
        if self._focus_score is not None:
            self._focus_circle.update_data(self._focus_score, self._fatigue_level)

    def _toggle_mode(self) -> None:
        """Tab 键切换极简/完整模式"""
        self._minimal_mode = not self._minimal_mode
        if self._minimal_mode:
            self._minimal_overlay.show()
            self._full_overlay.hide()
            self._status_bar.hide()
        else:
            self._minimal_overlay.hide()
            self._full_overlay.show()
            self._status_bar.show()

    def resizeEvent(self, event):
        """窗口缩放时同步 overlay 尺寸"""
        super().resizeEvent(event)
        self._minimal_overlay.setGeometry(self._video_label.geometry())
        self._full_overlay.setGeometry(self._video_label.geometry())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """键盘事件处理"""
        key = event.key()

        # Q → 退出
        if key == Qt.Key_Q:
            if self._quit_pending:
                logger.info("用户退出 (Q)")
                self.exit_requested.emit()
            else:
                self._quit_pending = True
                self._quit_start = __import__('time').time()
            return

        # 其他键取消 Q 倒计时
        if self._quit_pending:
            self._quit_pending = False

        if key == Qt.Key_Escape:
            # ESC 由 main.py 的 CalibrationCoordinator 处理
            pass
        elif key == Qt.Key_C:
            # C 由 main.py 处理
            pass
        elif key == Qt.Key_P or key == Qt.Key_Space:
            self._paused = not self._paused
        elif key == Qt.Key_Tab:
            self._toggle_mode()

        super().keyPressEvent(event)

"""
gui/qt_window.py — EyeFocus Qt 主窗口 (v4.5.1)

上下分区布局：
  ┌──────────────┐
  │  摄像头画面   │  60% 高度，纯画面
  ├──────────────┤
  │  渐变过渡带   │  24px
  ├──────────────┤
  │  白色数据面板 │  40% 高度
  │  圆环+卡片   │
  │  [暂停][校准][退出]  │  ← 鼠标按钮
  └──────────────┘

v4.5.1: 缩边距 + 移除键盘操作改为鼠标按钮 + 卡死防护
"""

import os
_qt_plugin_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '.venv312',
                 'Lib', 'site-packages', 'PyQt5', 'Qt5', 'plugins')
)
if os.path.isdir(_qt_plugin_path):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', _qt_plugin_path)

import logging
import time
from typing import Optional

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.qt_overlay import (
    FocusRing,
    GradientDivider,
    StatusCard,
    FATIGUE_EMOJI,
    _get_segoe_font,
)
from gui.video_label import FrameBuffer, VideoLabel

logger = logging.getLogger("eyefocus.gui.qt")


# ═══════════════════════════════════════════════════════════════════
# DataPanel — 白色数据面板（顶部大圆角）
# ═══════════════════════════════════════════════════════════════════

class DataPanel(QWidget):
    """纯白数据面板，顶部 20px 圆角"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(200)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        r = 20.0
        w, h = float(self.width()), float(self.height())
        path = QPainterPath()
        path.moveTo(0, r)
        path.arcTo(0, 0, r * 2, r * 2, 180, -90)
        path.lineTo(w - r, 0)
        path.arcTo(w - r * 2, 0, r * 2, r * 2, 90, -90)
        path.lineTo(w, h)
        path.lineTo(0, h)
        path.closeSubpath()
        painter.fillPath(path, QBrush(QColor("#FFFFFF")))
        painter.end()


# ═══════════════════════════════════════════════════════════════════
# ControlButton — Apple 风格文字按钮
# ═══════════════════════════════════════════════════════════════════

class ControlButton(QPushButton):
    """极简文字按钮：无色背景，彩色文字，hover 微亮"""

    def __init__(self, text: str, color: str = "#8E8E93",
                 parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._color = color
        self.setFont(_get_segoe_font(11))
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setStyleSheet(
            f"QPushButton {{"
            f"  color: {color};"
            f"  background: transparent;"
            f"  border: none;"
            f"  padding: 6px 16px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  color: {color};"
            f"  background: rgba(0,0,0,0.05);"
            f"  border-radius: 6px;"
            f"}}"
            f"QPushButton:pressed {{"
            f"  background: rgba(0,0,0,0.10);"
            f"}}"
        )


# ═══════════════════════════════════════════════════════════════════
# EyeFocusWindow — 主窗口
# ═══════════════════════════════════════════════════════════════════

class EyeFocusWindow(QMainWindow):
    """EyeFocus Insight Qt 主窗口 (v4.5.1)

    垂直布局：摄像头 (60%) → 渐变 → 数据面板 (40%) → 按钮栏。
    纯鼠标操作，帧由 FrameBuffer + QTimer 驱动。
    """

    exit_requested = pyqtSignal()
    calibrate_requested = pyqtSignal()

    def __init__(self, frame_buffer: FrameBuffer, parent: Optional[QWidget] = None,
                 show_calibrate: bool = True):
        super().__init__(parent)
        self._frame_buffer = frame_buffer
        self._show_calibrate = show_calibrate

        # ── 数据状态 ──
        self._focus_score: Optional[float] = None
        self._fatigue_level: Optional[str] = None
        self._focus_duration_minutes: Optional[float] = None
        self._face_detected: bool = False
        self._eye_detected: bool = False
        self._fps: float = 0.0
        self._paused: bool = False

        # ── 卡死防护：帧跳过守卫 ──
        self._frame_busy: bool = False
        self._skip_count: int = 0

        # ── 窗口设置 ──
        self.setWindowTitle("EyeFocus Insight")
        # v4.5.5: 固定窗口大小，不支持缩放（只可最小化/关闭）
        self.setFixedSize(640, 780)
        self.setStyleSheet("background-color: #000000;")

        central = QWidget()
        central.setStyleSheet("background-color: #000000;")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 上半：摄像头画面 (stretch 6) ──
        self._video_container = QWidget()
        self._video_container.setStyleSheet("background-color: #000000;")
        video_layout = QVBoxLayout(self._video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)
        self._video_label = VideoLabel()
        self._video_label.setStyleSheet("background-color: #000000;")
        video_layout.addWidget(self._video_label)
        main_layout.addWidget(self._video_container, 6)

        # ── 下半：白色数据面板 (stretch 4) ──
        self._data_panel = DataPanel()
        panel_layout = QVBoxLayout(self._data_panel)
        panel_layout.setContentsMargins(0, 8, 0, 4)
        panel_layout.setSpacing(0)
        panel_layout.setAlignment(Qt.AlignCenter)

        # 面板内容：左卡片列 + 圆环 + 右卡片列
        content = QHBoxLayout()
        content.setSpacing(20)
        content.setAlignment(Qt.AlignCenter)

        # 左列卡片
        left_col = QVBoxLayout()
        left_col.setSpacing(6)
        left_col.setAlignment(Qt.AlignCenter)

        self._fatigue_card = StatusCard(
            emoji="😊", main_text="LOW", label_text="疲劳", size=100)
        self._duration_card = StatusCard(
            emoji="", main_text="--", label_text="专注时长", size=100)
        left_col.addWidget(self._fatigue_card)
        left_col.addWidget(self._duration_card)
        content.addLayout(left_col)

        # 中心圆环
        self._focus_ring = FocusRing()
        self._focus_ring.setMinimumSize(180, 180)
        content.addWidget(self._focus_ring)

        # 右列卡片
        right_col = QVBoxLayout()
        right_col.setSpacing(6)
        right_col.setAlignment(Qt.AlignCenter)

        self._eye_card = StatusCard(
            emoji="", main_text="正常", label_text="眼睛", size=100)
        self._face_card = StatusCard(
            emoji="", main_text="正常", label_text="人脸", size=100)
        right_col.addWidget(self._eye_card)
        right_col.addWidget(self._face_card)
        content.addLayout(right_col)

        panel_layout.addLayout(content)

        # ── 按钮栏（面板底部） ──
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(8, 4, 8, 8)
        btn_bar.setAlignment(Qt.AlignCenter)

        # 暂停按钮
        self._pause_btn = ControlButton("暂停", "#8E8E93")
        self._pause_btn.clicked.connect(self._on_pause_clicked)
        btn_bar.addWidget(self._pause_btn)

        # 分隔符 + 校准按钮（可选）
        if self._show_calibrate:
            sep = QLabel("·")
            sep.setStyleSheet("color: #D1D1D6; border: none; background: transparent;")
            sep.setFont(_get_segoe_font(11))
            btn_bar.addWidget(sep)

            self._calib_btn = ControlButton("校准", "#007AFF")
            self._calib_btn.clicked.connect(lambda: self.calibrate_requested.emit())
            btn_bar.addWidget(self._calib_btn)
        else:
            self._calib_btn = None

        panel_layout.addLayout(btn_bar)

        main_layout.addWidget(self._data_panel, 4)

        # ── 帧更新定时器 (~30 FPS) ──
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_frame)
        self._timer.setInterval(33)

        self._fps_counter = 0
        self._fps_last_time = 0.0

        # ── Q 退出倒计时（保留作为安全退出方式） ──
    # ── 公共 API ──

    def start(self) -> None:
        self._fps_last_time = time.time()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self._pause_btn.setText("继续" if paused else "暂停")
        # 按钮颜色随暂停状态切换
        if paused:
            self._pause_btn._color = "#34C759"
        else:
            self._pause_btn._color = "#8E8E93"
        self._pause_btn.setStyleSheet(
            self._pause_btn.styleSheet()
            .replace("color: #8E8E93", "color: #34C759" if paused else "color: #8E8E93")
        )

    def is_paused(self) -> bool:
        return self._paused

    def update_data(self,
                    focus_score: Optional[float] = None,
                    fatigue_level: Optional[str] = None,
                    focus_level = None,         # v4.6: FocusLevel enum
                    fatigue_indicator = None,    # v4.6: FatigueIndicator enum
                    focus_duration_minutes: Optional[float] = None,
                    face_detected: bool = False,
                    eye_detected: bool = False,
                    fps: float = 0.0) -> None:
        """更新所有显示数据 (v4.6: 支持新 FocusLevel/FatigueIndicator)"""
        # v4.6: 提取字符串值
        fl_str = focus_level.value if hasattr(focus_level, 'value') else focus_level
        fi_str = fatigue_indicator.value if hasattr(fatigue_indicator, 'value') else fatigue_indicator

        self._focus_duration_minutes = focus_duration_minutes
        self._face_detected = face_detected
        self._eye_detected = eye_detected
        self._fps = fps

        # FocusRing — 优先使用 v4.6 参数
        self._focus_ring.update_data(
            focus_level=fl_str,
            fatigue_indicator=fi_str,
            focus_score=focus_score,       # 向后兼容
            fatigue_level=fatigue_level,   # 向后兼容
        )

        # 疲劳卡片 (v4.6 标签)
        if fi_str:
            card_labels = {"rested": "清醒", "attention": "关注", "tired": "休息"}
            card_status = {"rested": "ok", "attention": "warn", "tired": "error"}
            fi_lower = fi_str.lower() if fi_str else "rested"
            self._fatigue_card.update_data(
                main_text=card_labels.get(fi_lower, fi_str),
                label_text="眼疲劳",
                emoji="",
                status=card_status.get(fi_lower, "ok"),
            )
        elif fatigue_level:
            level = fatigue_level or "LOW"
            level_labels = {"LOW": "清醒", "MEDIUM": "关注", "HIGH": "疲劳"}
            fatigue_status = "ok" if level == "LOW" else ("warn" if level == "MEDIUM" else "error")
            self._fatigue_card.update_data(
                main_text=level_labels.get(level, level),
                label_text="疲劳",
                emoji="",
                status=fatigue_status,
            )
        else:
            self._fatigue_card.update_data(main_text="--", label_text="眼疲劳", status="ok")

        # 专注时长卡片
        if focus_duration_minutes is not None:
            if focus_duration_minutes >= 60:
                h = int(focus_duration_minutes / 60)
                m = int(focus_duration_minutes % 60)
                dur_text = f"{h}h{m}m"
            else:
                dur_text = f"{int(focus_duration_minutes)}m"
        else:
            dur_text = "--"
        self._duration_card.update_data(
            main_text=dur_text,
            label_text="专注时长",
            status="ok",
        )

        # 眼睛卡片
        self._eye_card.update_data(
            main_text="正常" if eye_detected else "闭眼",
            label_text="眼睛",
            status="ok" if eye_detected else "error",
        )

        # 人脸卡片
        self._face_card.update_data(
            main_text="正常" if face_detected else "丢失",
            label_text="人脸",
            status="ok" if face_detected else "error",
        )

    def update_data_from_processor(self, frame_processor, fps: float = 0.0) -> None:
        """从 FrameProcessor 读取最新分析结果（兼容 main.py）"""
        fr = frame_processor.latest_focus_result
        fa = frame_processor.latest_fatigue_result
        face = frame_processor.latest_face_detected

        focus_score = None
        fatigue_level = None
        if fr is not None:
            focus_score = fr.focus_score
        if fa is not None:
            level = fa.fatigue_level
            fatigue_level = level.value.upper() if hasattr(level, 'value') else str(level)

        focus_dur = getattr(frame_processor, 'focus_duration_minutes', None)

        self.update_data(
            focus_score=focus_score,
            fatigue_level=fatigue_level,
            focus_duration_minutes=focus_dur,
            face_detected=face,
            eye_detected=face,
            fps=fps,
        )

    # ── 按钮回调 ──

    def _on_pause_clicked(self) -> None:
        self._paused = not self._paused
        self.set_paused(self._paused)

    # ── 内部 ──

    def _update_frame(self) -> None:
        """QTimer 回调：读帧 → 显示"""
        if self._paused:
            return

        # 卡死防护：上一帧还在处理中，跳过
        if self._frame_busy:
            self._skip_count += 1
            if self._skip_count % 30 == 1:
                logger.debug(f"帧跳过 x{self._skip_count}")
            return
        self._skip_count = 0

        self._frame_busy = True
        try:
            frame = self._frame_buffer.read()
            if frame is not None:
                self._video_label.display_frame(frame)
        finally:
            self._frame_busy = False

        # FPS
        self._fps_counter += 1
        elapsed = time.time() - self._fps_last_time
        if elapsed >= 1.0:
            self._fps = self._fps_counter / elapsed
            self._fps_counter = 0
            self._fps_last_time = time.time()

    # ── 窗口事件 ──

    def closeEvent(self, event):
        """X 按钮关闭窗口"""
        logger.info("窗口关闭 (X)")
        self.exit_requested.emit()
        event.accept()

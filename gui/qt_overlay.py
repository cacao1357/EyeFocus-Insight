"""
gui/qt_overlay.py — Qt 叠加层组件（极简模式 + 完整模式）

作为半透明 QWidget 叠加在 VideoLabel 上方。
使用 QPainter 绘制文字和图形，支持 QSS 样式。

Color theme:
  - Focus High(≥70) : #00dc82
  - Focus Mid(50-70): #ffc107
  - Focus Low(<50)  : #ff4444
  - Fatigue LOW     : #00c853
  - Fatigue MEDIUM  : #ffd600
  - Fatigue HIGH    : #ff1744
  - Background      : #1a1a1a / #2d2d2d
"""

import logging
from typing import Optional

from PyQt5.QtCore import Qt, QRect, QTimer
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QVBoxLayout, QWidget

logger = logging.getLogger("eyefocus.gui.qt")

# ── 颜色常量 ──
C_GREEN = QColor(0, 220, 130)
C_YELLOW = QColor(255, 193, 7)
C_RED = QColor(255, 68, 68)
C_ORANGE = QColor(255, 165, 0)
C_GRAY = QColor(160, 160, 160)
C_DARK = QColor(26, 26, 26)
C_PANEL = QColor(45, 45, 45)
C_WHITE = QColor(255, 255, 255)

FATIGUE_COLORS = {
    "LOW": QColor(0, 200, 83),
    "MEDIUM": QColor(255, 214, 0),
    "HIGH": QColor(255, 23, 68),
}

FOCUS_COLORS = {
    "high": C_GREEN,
    "mid": C_YELLOW,
    "low": C_RED,
}


def _focus_color(score: float) -> QColor:
    if score >= 70:
        return FOCUS_COLORS["high"]
    elif score >= 50:
        return FOCUS_COLORS["mid"]
    return FOCUS_COLORS["low"]


def _fatigue_color(level: Optional[str]) -> QColor:
    return FATIGUE_COLORS.get(level or "LOW", C_GRAY)


# ═══════════════════════════════════════════════════════════════════
# 极简模式
# ═══════════════════════════════════════════════════════════════════

class MinimalOverlay(QWidget):
    """极简模式：居中大号专注度数字 + 底部疲劳横条 + 右下状态"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._focus_score: Optional[float] = None
        self._fatigue_level: Optional[str] = None
        self._face_detected: bool = True
        self._eye_detected: bool = True

        # 大号数字字体
        self._score_font = QFont("Arial", 72, QFont.Bold)
        self._label_font = QFont("Microsoft YaHei", 12)
        self._status_font = QFont("Microsoft YaHei", 10)

    def update_data(self, focus_score: Optional[float] = None,
                    fatigue_level: Optional[str] = None,
                    face_detected: bool = True,
                    eye_detected: bool = True) -> None:
        self._focus_score = focus_score
        self._fatigue_level = fatigue_level
        self._face_detected = face_detected
        self._eye_detected = eye_detected
        self.update()

    def paintEvent(self, event):
        if self._focus_score is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        score_color = _focus_color(self._focus_score)

        # ── 居中大号专注度数字 ──
        painter.setFont(self._score_font)
        score_str = f"{self._focus_score:.0f}"
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(score_str)
        th = fm.height()
        cx = (w - tw) // 2
        cy = h // 2 - th // 2 - 20

        # 阴影
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 100))
        painter.drawText(QRect(cx + 2, cy + 2, tw + 4, th + 4), Qt.AlignCenter, score_str)

        # 主数字
        painter.setPen(score_color)
        painter.drawText(QRect(cx, cy, tw, th), Qt.AlignCenter, score_str)

        # FOCUS 标签
        painter.setFont(self._label_font)
        painter.setPen(C_GRAY)
        painter.drawText(QRect(0, cy - 30, w, 24), Qt.AlignCenter, "FOCUS")

        # ── 底部疲劳横条 ──
        if self._fatigue_level:
            bar_y = h - 60
            bar_h = 16
            f_color = _fatigue_color(self._fatigue_level)

            # 背景
            painter.setPen(Qt.NoPen)
            painter.setBrush(C_PANEL)
            painter.drawRect(0, bar_y, w, bar_h)

            # 填充
            ratios = {"LOW": 0.3, "MEDIUM": 0.6, "HIGH": 1.0}
            fill = ratios.get(self._fatigue_level, 0.3)
            painter.setBrush(f_color)
            painter.drawRect(0, bar_y, int(w * fill), bar_h)

            # 边框
            painter.setPen(QPen(C_GRAY, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(0, bar_y, w, bar_h)

            # 标签
            painter.setFont(self._status_font)
            painter.setPen(f_color)
            painter.drawText(QRect(10, bar_y - 22, 200, 18), Qt.AlignLeft,
                             f"FATIGUE  {self._fatigue_level}")

        # ── 右下人脸/眼状态 ──
        status = f"Face {'✓' if self._face_detected else '✗'}  Eyes {'✓' if self._eye_detected else '✗'}"
        painter.setFont(self._status_font)
        painter.setPen(C_GRAY)
        fm = painter.fontMetrics()
        sw = fm.horizontalAdvance(status)
        painter.drawText(QRect(w - sw - 12, h - 80, sw, 18), Qt.AlignLeft, status)

        painter.end()


# ═══════════════════════════════════════════════════════════════════
# 完整模式
# ═══════════════════════════════════════════════════════════════════

class TopStatusBar(QWidget):
    """顶栏 4 段状态 (MODE + Face/Eye + FOCUS + FATIGUE + GLASSES)"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setStyleSheet("background-color: #2d2d2d; border-bottom: 1px solid #555;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)

        self._mode_label = QLabel("● MONITORING")
        self._mode_label.setStyleSheet("color: #00dc82; font-weight: bold; font-size: 13px;")
        layout.addWidget(self._mode_label)

        self._face_label = QLabel("Face ✓")
        self._face_label.setStyleSheet("color: #00c853; font-size: 11px;")
        layout.addWidget(self._face_label)

        layout.addStretch()

        self._focus_label = QLabel("FOCUS  --")
        self._focus_label.setStyleSheet("color: #00dc82; font-weight: bold; font-size: 14px;")
        layout.addWidget(self._focus_label)

        self._fatigue_label = QLabel("FATIGUE  --")
        self._fatigue_label.setStyleSheet("color: #a0a0a0; font-size: 12px;")
        layout.addWidget(self._fatigue_label)

        self._glasses_label = QLabel("")
        self._glasses_label.setStyleSheet("color: #a0a0a0; font-size: 11px;")
        layout.addWidget(self._glasses_label)

    def update_data(self, mode: str = "MONITORING", focus_score: Optional[float] = None,
                    fatigue_level: Optional[str] = None, face_detected: bool = True,
                    eye_detected: bool = True, glasses_str: Optional[str] = None) -> None:
        mode_colors = {"MONITORING": "#00dc82", "CALIBRATING": "#ffa500",
                       "PAUSED": "#a0a0a0", "INITIALIZING": "#ffc107"}
        self._mode_label.setStyleSheet(
            f"color: {mode_colors.get(mode, '#a0a0a0')}; font-weight: bold; font-size: 13px;")
        self._mode_label.setText(f"● {mode}")

        face_color = "#00c853" if face_detected else "#ff4444"
        self._face_label.setStyleSheet(f"color: {face_color}; font-size: 11px;")
        self._face_label.setText(f"Face {'✓' if face_detected else '✗'}  "
                                 f"Eyes {'✓' if eye_detected else '✗'}")

        if focus_score is not None:
            c = _focus_color(focus_score)
            hex_c = c.name()
            self._focus_label.setStyleSheet(f"color: {hex_c}; font-weight: bold; font-size: 14px;")
            self._focus_label.setText(f"FOCUS  {focus_score:.0f}")

        if fatigue_level is not None:
            c = FATIGUE_COLORS.get(fatigue_level, C_GRAY)
            self._fatigue_label.setStyleSheet(f"color: {c.name()}; font-size: 12px;")
            self._fatigue_label.setText(f"FATIGUE  {fatigue_level}")

        if glasses_str:
            self._glasses_label.setText(f"GLASSES  {glasses_str}")


class FocusCircle(QWidget):
    """专注度圆环 (右下角) — 与 OpenCV 版布局一致但用 QPainter 绘制"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(160, 160)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._focus_score: float = 0
        self._fatigue_level: Optional[str] = None

    def update_data(self, focus_score: float, fatigue_level: Optional[str] = None) -> None:
        self._focus_score = focus_score
        self._fatigue_level = fatigue_level
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        center = self.rect().center()
        radius = 70

        # 背景圆
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(40, 40, 40, 180))
        painter.drawEllipse(center, radius, radius)

        # 边框
        border_color = _focus_color(self._focus_score)
        painter.setPen(QPen(border_color, 8))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(center, radius, radius)

        # 进度弧
        arc_color = _fatigue_color(self._fatigue_level)
        painter.setPen(QPen(arc_color, 8, Qt.SolidLine, Qt.RoundCap))
        start_angle = 90 * 16  # Qt 用 1/16 度, 12点方向为 90°
        span = int(3.6 * self._focus_score * 16)
        painter.drawArc(self.rect().adjusted(8, 8, -8, -8), start_angle, -span)

        # FOCUS 标签
        painter.setPen(C_GRAY)
        small_font = QFont("Microsoft YaHei", 10)
        painter.setFont(small_font)
        painter.drawText(QRect(center.x() - 40, center.y() - 40, 80, 20),
                         Qt.AlignCenter, "FOCUS")

        # 数字
        big_font = QFont("Arial", 24, QFont.Bold)
        painter.setFont(big_font)
        painter.setPen(C_WHITE)
        painter.drawText(QRect(center.x() - 45, center.y() - 15, 90, 40),
                         Qt.AlignCenter, f"{self._focus_score:.0f}")

        # 疲劳等级
        if self._fatigue_level:
            painter.setFont(small_font)
            painter.setPen(_fatigue_color(self._fatigue_level))
            painter.drawText(QRect(center.x() - 40, center.y() + 40, 80, 20),
                             Qt.AlignCenter, self._fatigue_level)

        painter.end()

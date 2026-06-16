"""
gui/qt_overlay.py — Qt 监测界面组件 (v4.5 Apple Health 风格)

新布局组件：
  - FocusRing: Apple Watch 风格专注度圆环 + 疲劳圆点
  - StatusCard: 正方形状态卡片（emoji + 值 + 标签）
  - GradientDivider: 垂直渐变过渡带（#000 → #FFF）

Color theme (Apple 系统色):
  - Focus High(≥70) : #34C759 (green)
  - Focus Mid(50-70): #FF9500 (orange)
  - Focus Low(<50)  : #FF3B30 (red)
  - Background       : #FFFFFF (white panel)
  - Text primary     : #1C1C1E
  - Text secondary   : #8E8E93
  - Border           : #E5E5EA
"""

import logging
from typing import Optional

from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QLinearGradient,
    QPainter,
    QPen,
)
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("eyefocus.gui.qt")

# ═══════════════════════════════════════════════════════════════════
# 颜色常量
# ═══════════════════════════════════════════════════════════════════

C_PANEL_BG = QColor(255, 255, 255)     # #FFFFFF
C_CARD_BORDER = QColor(229, 229, 234)  # #E5E5EA
C_TEXT_PRIMARY = QColor(28, 28, 30)    # #1C1C1E
C_TEXT_SECONDARY = QColor(142, 142, 147)  # #8E8E93
C_RING_BG = QColor(242, 242, 247)      # #F2F2F7
C_DOT_INACTIVE = QColor(209, 209, 214)  # #D1D1D6
C_WHITE = QColor(255, 255, 255)
C_BLACK = QColor(0, 0, 0)
C_HINT_BG = QColor(242, 242, 247)      # #F2F2F7

# 专注度颜色 (Apple 系统色)
C_FOCUS_GREEN = QColor(52, 199, 89)    # #34C759
C_FOCUS_YELLOW = QColor(255, 149, 0)   # #FF9500
C_FOCUS_RED = QColor(255, 59, 48)      # #FF3B30

# 疲劳颜色 (同专注度系统色)
C_FATIGUE_COLORS = {
    "LOW": C_FOCUS_GREEN,
    "MEDIUM": C_FOCUS_YELLOW,
    "HIGH": C_FOCUS_RED,
}

# 疲劳 emoji
FATIGUE_EMOJI = {
    "LOW": "😊",
    "MEDIUM": "😐",
    "HIGH": "😫",
}


def _focus_color(score: float) -> QColor:
    """专注度分数 → 颜色"""
    if score >= 70:
        return C_FOCUS_GREEN
    elif score >= 50:
        return C_FOCUS_YELLOW
    return C_FOCUS_RED


def _fatigue_color(level: Optional[str]) -> QColor:
    """疲劳等级 → 颜色"""
    return C_FATIGUE_COLORS.get(level or "LOW", C_TEXT_SECONDARY)


def _get_segoe_font(size: int, weight: int = QFont.Normal) -> QFont:
    """获取 Segoe UI 字体（Windows 最接近 Apple SF Pro 的系统字体）"""
    font = QFont("Segoe UI", size)
    font.setWeight(weight)
    if weight >= QFont.Bold:
        font.setStyleStrategy(QFont.PreferAntialias)
    return font


# ═══════════════════════════════════════════════════════════════════
# FocusRing — Apple Watch 风格专注度圆环
# ═══════════════════════════════════════════════════════════════════

class FocusRing(QWidget):
    """专注度圆环组件 (v4.6: 三段弧 + 文字替代 0-100 数字)

    Apple Watch 风格：三段彩色弧 + 中心文字 + 底部疲劳圆点。
    """

    # v4.6: 等级→颜色映射
    LEVEL_COLORS = {
        "FOCUSED": C_FOCUS_GREEN, "focused": C_FOCUS_GREEN,
        "NORMAL": C_FOCUS_YELLOW, "normal": C_FOCUS_YELLOW,
        "DISTRACTED": C_FOCUS_RED, "distracted": C_FOCUS_RED,
    }
    LEVEL_SPANS = {"FOCUSED": 360, "focused": 360,
                   "NORMAL": 240, "normal": 240,
                   "DISTRACTED": 120, "distracted": 120}
    LEVEL_LABELS = {"FOCUSED": "专注", "focused": "专注",
                    "NORMAL": "一般", "normal": "一般",
                    "DISTRACTED": "分心", "distracted": "分心"}

    FATIGUE_LABELS_CN = {"RESTED": "清醒", "rested": "清醒",
                          "ATTENTION": "关注", "attention": "关注",
                          "TIRED": "疲劳", "tired": "疲劳"}

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumSize(180, 180)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)

        self._focus_level: Optional[str] = None      # v4.6: FOCUSED/NORMAL/DISTRACTED
        self._fatigue_indicator: Optional[str] = None  # v4.6: RESTED/ATTENTION/TIRED
        # 向后兼容
        self._focus_score: Optional[float] = None
        self._fatigue_level: Optional[str] = None

        self._text_font = _get_segoe_font(20, QFont.Bold)
        self._label_font = _get_segoe_font(11)
        self._dot_font = _get_segoe_font(9)

    def update_data(self,
                    focus_score: Optional[float] = None,
                    fatigue_level: Optional[str] = None,
                    focus_level: Optional[str] = None,
                    fatigue_indicator: Optional[str] = None) -> None:
        """更新数据。优先使用 v4.6 新参数，回退到旧参数。"""
        if focus_level is not None:
            self._focus_level = focus_level
            self._focus_score = None  # 新旧互斥
        elif focus_score is not None:
            self._focus_score = focus_score
            self._focus_level = None

        if fatigue_indicator is not None:
            self._fatigue_indicator = fatigue_indicator
            self._fatigue_level = None
        elif fatigue_level is not None:
            self._fatigue_level = fatigue_level
            self._fatigue_indicator = None

        self.update()

    def _ring_rect(self, w: int, h: int) -> QRectF:
        side = min(w, h) * 0.70
        side = max(side, 120)
        x = (w - side) / 2
        y = (h - side) / 2 - 10
        return QRectF(x, y, side, side)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        ring = self._ring_rect(w, h)
        ring_width = 10.0
        center = ring.center()
        cx, cy = center.x(), center.y()

        # 确定颜色、弧度和中心文字
        if self._focus_level:
            lvl = self._focus_level
            arc_color = self.LEVEL_COLORS.get(lvl, C_TEXT_SECONDARY)
            span_deg = self.LEVEL_SPANS.get(lvl, 240)
            center_text = self.LEVEL_LABELS.get(lvl, "--")
        elif self._focus_score is not None:
            arc_color = _focus_color(self._focus_score)
            span_deg = int((self._focus_score / 100.0) * 360)
            center_text = f"{self._focus_score:.0f}"
        else:
            arc_color = C_TEXT_SECONDARY
            span_deg = 0
            center_text = "--"

        # 背景圆环
        painter.setPen(QPen(C_RING_BG, ring_width, Qt.SolidLine, Qt.RoundCap))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(ring)

        # 进度弧
        if span_deg > 0:
            painter.setPen(QPen(arc_color, ring_width, Qt.SolidLine, Qt.RoundCap))
            span_16 = int(span_deg * 16)
            painter.drawArc(ring, 90 * 16, -span_16)

        # 中心文字
        painter.setFont(self._text_font)
        painter.setPen(QPen(C_TEXT_PRIMARY))
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(center_text)
        th = fm.height()
        painter.drawText(QRectF(cx - tw / 2, cy - th / 2 - 2, tw, th),
                         Qt.AlignCenter, center_text)

        # 底部疲劳圆点 (v4.6: 使用新标签)
        fatigue_key = self._fatigue_indicator or self._fatigue_level
        if fatigue_key:
            dot_labels = {"RESTED": "清醒", "ATTENTION": "关注", "TIRED": "疲劳",
                          "LOW": "清醒", "MEDIUM": "关注", "HIGH": "疲劳"}
        else:
            dot_labels = {"LOW": "低", "MEDIUM": "中", "HIGH": "高"}
        self._draw_fatigue_dots_v46(painter, cx, ring.bottom() + 18, fatigue_key, dot_labels)

        painter.end()

    def _draw_fatigue_dots_v46(self, painter: QPainter, cx: float, y: float,
                                current: Optional[str], labels: dict) -> None:
        dot_r = 5.0
        spacing = 6.0
        keys = list(labels.keys())[:3]
        total_w = 3 * (dot_r * 2) + 2 * spacing
        start_x = cx - total_w / 2

        painter.setFont(self._dot_font)
        for i, key in enumerate(keys):
            dx = start_x + i * (dot_r * 2 + spacing) + dot_r
            if key == current:
                color = C_FATIGUE_COLORS.get("LOW" if "RESTED" in str(key) else
                                             "MEDIUM" if "ATTENTION" in str(key) else "HIGH",
                                             C_DOT_INACTIVE)
            else:
                color = C_DOT_INACTIVE
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QPointF(dx, y), dot_r, dot_r)

    def sizeHint(self):
        return self.minimumSize()


# ═══════════════════════════════════════════════════════════════════
# StatusCard — 正方形状态卡片
# ═══════════════════════════════════════════════════════════════════

class StatusCard(QWidget):
    """正方形状态卡片

    纵向排列：emoji/图标 → 主值 → 标签。
    纯白底 + 浅灰边框 + 大圆角。
    支持 ok / warn / error 三种状态。
    """

    def __init__(self, parent: Optional[QWidget] = None,
                 emoji: str = "", main_text: str = "--",
                 label_text: str = "", status: str = "ok",
                 size: int = 90):
        super().__init__(parent)
        self.setMinimumSize(size, size)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        self._size = size
        self._status = status

        # 白色背景 + 圆角边框
        self.setStyleSheet(
            f"background-color: #FFFFFF;"
            f"border: 1px solid #E5E5EA;"
            f"border-radius: 16px;"
        )

        # 垂直排列
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)

        # Emoji / 图标
        self._emoji_label = QLabel(emoji)
        self._emoji_label.setAlignment(Qt.AlignCenter)
        self._emoji_label.setStyleSheet("border: none; background: transparent;")
        emoji_font = QFont("Segoe UI Emoji", 14)
        self._emoji_label.setFont(emoji_font)
        layout.addWidget(self._emoji_label)

        # 主值
        self._main_label = QLabel(main_text)
        self._main_label.setAlignment(Qt.AlignCenter)
        self._main_label.setStyleSheet("border: none; background: transparent;")
        self._main_label.setFont(_get_segoe_font(16, 600))  # Semibold
        layout.addWidget(self._main_label)

        # 标签
        self._label_label = QLabel(label_text)
        self._label_label.setAlignment(Qt.AlignCenter)
        self._label_label.setStyleSheet("border: none; background: transparent;")
        self._label_label.setFont(_get_segoe_font(10))
        self._label_label.setWordWrap(True)
        layout.addWidget(self._label_label)

    def update_data(self, main_text: str = "--", label_text: str = "",
                    emoji: str = "", status: str = "ok") -> None:
        """更新卡片内容

        Args:
            main_text: 主值文字 (如 "85", "LOW", "✓")
            label_text: 标签文字 (如 "专注度", "疲劳等级")
            emoji: emoji 图标 (如 "😊", "")
            status: "ok" | "warn" | "error" — 控制边框和主值颜色
        """
        self._status = status

        if emoji:
            self._emoji_label.setText(emoji)
            self._emoji_label.show()

        self._main_label.setText(main_text)
        self._label_label.setText(label_text)

        # 状态颜色
        if status == "error":
            border_color = "#FF3B30"
            main_color = "#FF3B30"
        elif status == "warn":
            border_color = "#FF9500"
            main_color = "#FF9500"
        else:
            border_color = "#E5E5EA"
            main_color = "#1C1C1E"

        self._main_label.setStyleSheet(
            f"border: none; background: transparent; color: {main_color};"
        )
        self.setStyleSheet(
            f"background-color: #FFFFFF;"
            f"border: 1px solid {border_color};"
            f"border-radius: 16px;"
        )

    def sizeHint(self):
        return self.minimumSize()


# ═══════════════════════════════════════════════════════════════════
# FocusSparkline — 实时专注度波线 (v4.17)
# ═══════════════════════════════════════════════════════════════════

class FocusSparkline(QWidget):
    """实时专注度趋势波线

    显示最近 N 秒的专注度分数波形。
    曲线颜色从绿→黄→红渐变，模拟 Apple 健康心电图风格。
    """

    def __init__(self, parent: Optional[QWidget] = None, max_points: int = 60):
        super().__init__(parent)
        self._max_points = max_points
        self._scores: list = []  # (score, color_hex) 元组列表
        self.setMinimumHeight(50)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def add_point(self, score: float) -> None:
        """添加一个数据点（每秒调用一次）"""
        color = "#34C759" if score >= 70 else "#FF9500" if score >= 40 else "#FF3B30"
        self._scores.append((score, color))
        if len(self._scores) > self._max_points:
            self._scores.pop(0)
        self.update()

    def paintEvent(self, event):
        if len(self._scores) < 2:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width() - 2
        h = self.height() - 4
        if w <= 0 or h <= 0:
            painter.end()
            return

        margin_l = 4
        plot_w = w - margin_l
        plot_h = h - 2
        n = len(self._scores)

        # 提取分数
        values = [s[0] for s in self._scores]
        min_v, max_v = 0, 100

        def _y(val):
            return plot_h - (val - min_v) / (max_v - min_v) * plot_h

        # 绘制渐变填充区域（路径）
        fill_path = QPainterPath()
        fill_path.moveTo(margin_l, plot_h)
        for i in range(n):
            x = margin_l + (i / (n - 1)) * plot_w
            y = _y(values[i])
            if i == 0:
                fill_path.lineTo(x, y)
            else:
                fill_path.lineTo(x, y)
        fill_path.lineTo(margin_l + plot_w, plot_h)
        fill_path.closeSubpath()

        # 渐变填充
        last_color = self._scores[-1][1] if self._scores else "#34C759"
        lc = QColor(last_color)
        lc.setAlpha(25)
        painter.fillPath(fill_path, QBrush(lc))

        # 绘制波线
        line_path = QPainterPath()
        for i in range(n):
            x = margin_l + (i / (n - 1)) * plot_w
            y = _y(values[i])
            if i == 0:
                line_path.moveTo(x, y)
            else:
                line_path.lineTo(x, y)

        pen = QPen(QColor(last_color), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(line_path)

        # 最新值标签
        last_val = values[-1]
        label_x = margin_l + plot_w
        label_y = _y(last_val)
        painter.setPen(QPen(QColor(last_color)))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(int(label_x - 32), int(label_y - 10), 32, 14,
                         Qt.AlignRight | Qt.AlignBottom, f"{last_val:.0f}")

        painter.end()


# ═══════════════════════════════════════════════════════════════════
# GradientDivider — 垂直渐变过渡带
# ═══════════════════════════════════════════════════════════════════

class GradientDivider(QWidget):
    """摄像头画面（黑）到数据面板（白）的渐变过渡"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, C_BLACK)
        gradient.setColorAt(1.0, C_PANEL_BG)

        painter.fillRect(self.rect(), gradient)
        painter.end()


# ═══════════════════════════════════════════════════════════════════
# DistractionLabel — 分心原因分解标签 (v4.17)
# ═══════════════════════════════════════════════════════════════════

class DistractionLabel(QWidget):
    """分心原因实时分解

    专注度 < 70 时显示各因素百分比：
      分心源：头部偏移 55% | 眨眼异常 30% | 视线偏离 15%
    专注度 ≥ 70 时自动隐藏。
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(
            "color: #8B8680; background: #F5F3F1;"
            "border: 1px solid #E6E2DC; border-radius: 4px;"
            "padding: 3px 8px; font-size: 11px;"
        )
        self._causes = {}
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 2, 16, 2)
        layout.addWidget(self._label)

    def update_causes(self, causes: dict) -> None:
        """更新分心原因显示"""
        self._causes = causes
        if causes:
            parts = [f"{k} {v:.0f}%" for k, v in causes.items() if v > 0]
            self._label.setText(f"分心源：{' | '.join(parts)}")
            self.setVisible(True)
        else:
            self.setVisible(False)

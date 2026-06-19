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
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.qt_overlay import (
    DistractionLabel,
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
        # v4.22: 显式白底（防止系统暗色模式导致透明背景透出黑色）
        self.setAutoFillBackground(True)
        self.setStyleSheet("background-color: #FFFFFF;")

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
    """简约文字按钮：圆角背景，hover 微亮，pressed 加深"""

    def __init__(self, text: str, color: str = "#8B8680",
                 parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._color = color
        self.setFont(_get_segoe_font(12))
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self._update_style(color)

    def _update_style(self, color: str):
        self.setStyleSheet(
            f"QPushButton {{"
            f"  color: {color}; background: transparent;"
            f"  border: 1px solid {color}40;"
            f"  border-radius: 8px; padding: 6px 18px;"
            f"  font-size: 12px; font-weight: 500;"
            f"}}"
            f"QPushButton:hover {{"
            f"  color: {color}; background: {color}15;"
            f"  border-color: {color}70;"
            f"}}"
            f"QPushButton:pressed {{"
            f"  background: {color}25;"
            f"}}"
        )

    def set_color(self, color: str):
        self._color = color
        self._update_style(color)


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
                 show_calibrate: bool = True, enable_tray: bool = True,
                 app_ref=None):
        super().__init__(parent)
        self._frame_buffer = frame_buffer
        self._show_calibrate = show_calibrate
        self._enable_tray = enable_tray
        self._force_exit = False
        self._app = app_ref  # v4.21: 保存 app 引用供菜单使用

        # ── 数据状态 ──
        self._focus_score: Optional[float] = None
        self._fatigue_level: Optional[str] = None
        self._focus_duration_minutes: Optional[float] = None
        self._face_detected: bool = False
        self._eye_detected: bool = False
        self._fps: float = 0.0
        self._paused: bool = False
        self._light_condition: Optional[str] = None  # "DARK"/"NORMAL"/"BRIGHT"

        # ── 卡死防护：帧跳过守卫 ──
        self._frame_busy: bool = False
        self._skip_count: int = 0

        # ── 窗口设置 ──
        self.setWindowTitle("EyeFocus Insight")
        # v4.5.5: 固定窗口大小，不支持缩放（只可最小化/关闭）
        self.setFixedSize(720, 800)
        self.setStyleSheet("background-color: #000000;")

        central = QWidget()
        central.setStyleSheet("background-color: #000000;")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 上半：摄像头画面 (stretch 5) ──
        self._video_container = QWidget()
        self._video_container.setStyleSheet("background-color: #000000;")
        video_layout = QVBoxLayout(self._video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)
        self._video_label = VideoLabel()
        self._video_label.setStyleSheet("background-color: #000000;")
        video_layout.addWidget(self._video_label)
        self._pause_overlay = QLabel("⏸ 已暂停", self._video_container)
        self._pause_overlay.setAlignment(Qt.AlignCenter)
        self._pause_overlay.setStyleSheet(
            "color: white; background: rgba(0,0,0,140);"
            "font-size: 36px; font-weight: bold; border-radius: 12px;"
        )
        self._pause_overlay.setVisible(False)
        main_layout.addWidget(self._video_container, 5)

        # ── 下半：白色数据面板 (stretch 4) ──
        self._data_panel = DataPanel()
        panel_layout = QVBoxLayout(self._data_panel)
        panel_layout.setContentsMargins(16, 14, 16, 8)
        panel_layout.setSpacing(4)

        # ── Row 1: Hero 监测时长 ──
        hero_row = QVBoxLayout()
        hero_row.setSpacing(0)
        hero_row.setAlignment(Qt.AlignCenter)

        self._hero_value = QLabel("--")
        self._hero_value.setAlignment(Qt.AlignCenter)
        self._hero_value.setFont(_get_segoe_font(36, QFont.Light))
        self._hero_value.setStyleSheet("color: #1C1C1E; background: transparent; border: none;")
        hero_row.addWidget(self._hero_value)

        self._hero_unit = QLabel("min")
        self._hero_unit.setAlignment(Qt.AlignCenter)
        self._hero_unit.setFont(_get_segoe_font(13))
        self._hero_unit.setStyleSheet("color: #8E8E93; background: transparent; border: none;")
        hero_row.addWidget(self._hero_unit)

        panel_layout.addLayout(hero_row)

        # ── Row 2: 专注度进度条 ──
        focus_row = QVBoxLayout()
        focus_row.setSpacing(2)

        focus_header = QHBoxLayout()
        focus_header.setContentsMargins(0, 0, 0, 0)

        fl = QLabel("专注度")
        fl.setFont(_get_segoe_font(13))
        fl.setStyleSheet("color: #1C1C1E; background: transparent; border: none;")
        focus_header.addWidget(fl)

        focus_header.addStretch()

        self._focus_bar_value = QLabel("-- / 100")
        self._focus_bar_value.setFont(_get_segoe_font(13))
        self._focus_bar_value.setStyleSheet("color: #8E8E93; background: transparent; border: none;")
        focus_header.addWidget(self._focus_bar_value)

        focus_row.addLayout(focus_header)

        self._focus_bar = QProgressBar()
        self._focus_bar.setRange(0, 100)
        self._focus_bar.setValue(0)
        self._focus_bar.setTextVisible(False)
        self._focus_bar.setFixedHeight(6)
        self._focus_bar.setStyleSheet(
            "QProgressBar {"
            "  background-color: #F2F2F7;"
            "  border: none; border-radius: 3px;"
            "}"
            "QProgressBar::chunk {"
            "  border-radius: 3px;"
            "  background-color: #5A8A6D;"
            "}"
        )
        focus_row.addWidget(self._focus_bar)

        panel_layout.addLayout(focus_row)

        # ── Row 3: 番茄 + 状态（单行） ──
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)
        metrics_row.setContentsMargins(0, 6, 0, 2)

        self._pomodoro_btn = QPushButton("🍅 --")
        self._pomodoro_btn.setFont(_get_segoe_font(16))
        self._pomodoro_btn.setCursor(Qt.PointingHandCursor)
        self._pomodoro_btn.setFlat(True)
        self._pomodoro_btn.setStyleSheet(
            "QPushButton{color:#5A8A6D;background:transparent;border:none;text-align:left;}"
            "QPushButton:hover{color:#4A7A5D;}"
        )
        self._pomodoro_btn.clicked.connect(self._show_pomodoro_menu)
        metrics_row.addWidget(self._pomodoro_btn)

        metrics_row.addStretch()

        self._status_label = QLabel("🟢 正常")
        self._status_label.setFont(_get_segoe_font(14))
        self._status_label.setStyleSheet("color: #5A8A6D; background: transparent; border: none;")
        metrics_row.addWidget(self._status_label)

        panel_layout.addLayout(metrics_row)

        # ── Row 4: Toast 警告（优先级显示1个） ──
        self._toast_label = QLabel("")
        self._toast_label.setAlignment(Qt.AlignCenter)
        style_toast_ok = (
            "color: #5A8A6D; background: #EEF5EF;"
            "border: 1px solid #5A8A6D; border-radius: 6px;"
            "padding: 4px 8px; font-size: 12px; font-weight: 600;"
        )
        style_toast_warn = (
            "color: #C9843A; background: #FAF0E3;"
            "border: 1px solid #C9843A; border-radius: 6px;"
            "padding: 4px 8px; font-size: 12px; font-weight: 600;"
        )
        style_toast_err = (
            "color: #B55C5C; background: #F8E8E8;"
            "border: 1px solid #B55C5C; border-radius: 6px;"
            "padding: 4px 8px; font-size: 12px; font-weight: 600;"
        )
        self._style_toast = {"ok": style_toast_ok, "warn": style_toast_warn, "err": style_toast_err}
        self._toast_label.setVisible(False)
        panel_layout.addWidget(self._toast_label)

        # ── 分心原因 ──
        self._distraction_label = DistractionLabel()
        panel_layout.addWidget(self._distraction_label)

        # ── 游戏化状态 ──
        self._gamification_bar = QLabel("")
        self._gamification_bar.setAlignment(Qt.AlignCenter)
        self._gamification_bar.setStyleSheet(
            "color: #5B4A8C; background: transparent;"
            "border: none; font-size: 12px; padding: 1px 0; font-weight: 500;"
        )
        self._gamification_bar.setVisible(False)
        panel_layout.addWidget(self._gamification_bar)

        # ── Footer ──
        footer_layout = QVBoxLayout()
        footer_layout.setSpacing(6)
        footer_layout.setContentsMargins(0, 4, 0, 0)

        # 校准提示（降级为 footer 小字）
        self._calib_prompt = QLabel("未校准 · 评分仅供参考")
        self._calib_prompt.setAlignment(Qt.AlignCenter)
        self._calib_prompt.setStyleSheet(
            "color: #8E8E93; background: transparent;"
            "border: none; font-size: 11px;"
        )
        self._calib_prompt.setVisible(True)
        footer_layout.addWidget(self._calib_prompt)

        # 按钮栏
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(12)
        btn_bar.setAlignment(Qt.AlignCenter)

        self._pause_btn = ControlButton("⏸ 暂停", "#8B8680")
        self._pause_btn.clicked.connect(self._on_pause_clicked)
        btn_bar.addWidget(self._pause_btn)

        if self._show_calibrate:
            self._calib_btn = ControlButton("⚙ 校准", "#5B4A8C")
            self._calib_btn.clicked.connect(lambda: self.calibrate_requested.emit())
            btn_bar.addWidget(self._calib_btn)
        else:
            self._calib_btn = None

        footer_layout.addLayout(btn_bar)
        panel_layout.addLayout(footer_layout)

        main_layout.addWidget(self._data_panel, 4)

        # ── 帧更新定时器 (~30 FPS) ──
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_frame)
        self._timer.setInterval(33)

        self._fps_counter = 0
        self._fps_last_time = 0.0

        # ── Q 退出倒计时（保留作为安全退出方式） ──

        # ── v4.10: 系统托盘 ──
        self._tray_icon = None
        if self._enable_tray and app_ref is not None:
            from gui.tray import EyeFocusTrayIcon
            self._tray_icon = EyeFocusTrayIcon(parent_window=self, app_ref=app_ref)
            self._tray_icon.show()

    # ── v4.18: 番茄状态 ──

    def _show_pomodoro_menu(self):
        """显示番茄操作菜单"""
        app = getattr(self, '_app', None)
        if app is None:
            return
        pomo = getattr(app, '_pomodoro', None)
        if pomo is None:
            return

        menu = QMenu()
        # 菜单样式：防止继承父窗口黑背景
        menu.setStyleSheet(
            "QMenu { background-color: #FFFFFF; border: 1px solid #D0D0D0; border-radius: 6px; padding: 4px; }"
            "QMenu::item { color: #23201E; padding: 8px 28px; font-size: 13px; }"
            "QMenu::item:selected { background-color: #5B4A8C; color: #FFFFFF; border-radius: 4px; }"
        )
        state = pomo.state

        if state == "IDLE":
            menu.addAction("▶ 开始番茄").triggered.connect(
                lambda: self._pomodoro_action(app, "start"))
        else:
            if getattr(pomo, '_paused', False):
                menu.addAction("▶ 继续").triggered.connect(
                    lambda: self._pomodoro_action(app, "resume"))
            else:
                menu.addAction("⏸ 暂停").triggered.connect(
                    lambda: self._pomodoro_action(app, "pause"))
            menu.addAction("⏹ 停止").triggered.connect(
                lambda: self._pomodoro_action(app, "stop"))

        menu.addSeparator()
        menu.addAction("⚙ 设置时间...").triggered.connect(
            lambda: self._pomodoro_action(app, "settings"))

        menu.exec_(self._pomodoro_btn.mapToGlobal(
            self._pomodoro_btn.rect().bottomLeft()))

    def _pomodoro_action(self, app, action: str):
        """执行番茄操作"""
        try:
            pomo = getattr(app, '_pomodoro', None)
            if pomo is None:
                return
            if action == "start":
                pomo.start()
            elif action == "pause":
                pomo.pause()
            elif action == "resume":
                pomo.resume()
            elif action == "stop":
                pomo.stop()
            elif action == "settings":
                # v4.26: 白底 wrapper 替代 QInputDialog.getInt（系统暗色下黑底）
                from gui.settings_dialog import ask_pomo_int
                work = ask_pomo_int(
                    self, "设置番茄", "工作分钟数 (1-120):",
                    value=pomo._work_minutes, min_val=1, max_val=120)
                if work is None:
                    return
                rest = ask_pomo_int(
                    self, "设置番茄", "休息分钟数 (1-60):",
                    value=pomo._break_minutes, min_val=1, max_val=60)
                if rest is None:
                    return
                pomo.set_duration(work, rest)
            # 同步托盘状态
            if hasattr(self, '_tray_icon') and self._tray_icon is not None:
                st = pomo.state
                if getattr(pomo, '_paused', False):
                    st = "PAUSED"
                self._tray_icon.set_pomodoro_state(st, pomo.count)
        except Exception as e:
            logger.warning("番茄操作失败: %s", e)

    def update_pomodoro(self, status: dict) -> None:
        """更新番茄状态显示"""
        if hasattr(self, '_pomodoro_btn'):
            s = status["state"]
            if s == "IDLE":
                self._pomodoro_btn.setText("🍅 --")
                self._pomodoro_btn.setStyleSheet(
                    "QPushButton{color:#8B8680;background:transparent;border:none;text-align:left;}"
                    "QPushButton:hover{color:#6B6650;}")
            else:
                remaining = status["remaining_sec"]
                tm, ts = divmod(status["total_sec"], 60)
                rm, rs = divmod(remaining, 60)
                time_str = f"{rm:02d}:{rs:02d} / {tm:02d}:{ts:02d}"
                paused = status.get("paused", False)
                if paused:
                    time_str = "⏸ " + time_str
                if s == "WORKING":
                    color = "#5A8A6D"
                    prefix = "🍅"
                else:
                    color = "#C9843A"
                    prefix = "☕"
                self._pomodoro_btn.setText(f"{prefix} {time_str}")
                self._pomodoro_btn.setStyleSheet(
                    f"QPushButton{{color:{color};background:transparent;border:none;text-align:left;}}"
                    f"QPushButton:hover{{color:{color}cc;}}")

    # ── v4.17: 专注度波线（v4.26: 替换为 Hero + 进度条，保留方法兼容） ──

    def update_sparkline(self, focus_score: float) -> None:
        """v4.26: sparkline 已隐藏，只记录不显示"""
        pass

    # ── v4.17: 游戏化 ──

    def update_gamification(self, streak_days: int = 0, today_minutes: float = 0.0,
                            trend_arrow: str = "") -> None:
        """更新游戏化状态显示（专注天数 + 今日时长 + 趋势）"""
        parts = []
        if streak_days > 0:
            fire = "🔥" if streak_days >= 3 else ""
            parts.append(f"{fire}连续 {streak_days} 天")
        if today_minutes > 0:
            parts.append(f"今日 {today_minutes:.0f} 分钟")
        if trend_arrow:
            color = {"↑": "#5A8A6D", "↓": "#B55C5C", "→": "#9E9A96"}.get(trend_arrow, "#9E9A96")
            parts.append(f'<span style="color:{color};font-weight:700;font-size:16px">{trend_arrow}</span>')
        if parts:
            self._gamification_bar.setText(" | ".join(parts))
            self._gamification_bar.setVisible(True)
        else:
            self._gamification_bar.setVisible(False)

    # ── v4.10: 托盘辅助方法 ──

    def toggle_visibility(self):
        """显示/隐藏窗口（由托盘调用）"""
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def toggle_pause(self):
        """切换暂停（由托盘调用）"""
        self._paused = not self._paused
        self.set_paused(self._paused)

    def set_do_not_disturb(self, enabled: bool):
        """设置免打扰模式"""
        if self._tray_icon:
            self._tray_icon.set_do_not_disturb(enabled)

    def show_fatigue_notification(self, message: str = ""):
        """显示疲劳提醒气泡"""
        if self._tray_icon:
            self._tray_icon.show_fatigue_notification(message)

    # ── v4.17: 暂停覆盖层 ──

    def _position_pause_overlay(self):
        """将暂停覆盖层居中定位到摄像头区域"""
        if hasattr(self, '_pause_overlay') and hasattr(self, '_video_container'):
            vw = self._video_container.width()
            vh = self._video_container.height()
            ow, oh = 200, 80
            self._pause_overlay.setGeometry(
                (vw - ow) // 2, (vh - oh) // 2, ow, oh
            )

    def resizeEvent(self, event):
        """窗口大小变化时重定位覆盖层"""
        super().resizeEvent(event)
        try:
            if hasattr(self, '_pause_overlay') and self._pause_overlay.isVisible():
                self._position_pause_overlay()
        except Exception:
            pass  # 布局未就绪时忽略

    # ── v4.17: 键盘快捷键 ──

    def keyPressEvent(self, event):
        """全局快捷键: Space=暂停, R=校准, Esc=隐藏窗口, Q=退出"""
        from PyQt5.QtCore import Qt
        key = event.key()
        if key == Qt.Key_Space:
            self._on_pause_clicked()
        elif key == Qt.Key_R and self._show_calibrate:
            self.calibrate_requested.emit()
        elif key == Qt.Key_Escape:
            self.hide()
            self._toggle_visibility_action_text("显示窗口")
        elif key == Qt.Key_Q and (event.modifiers() & Qt.ControlModifier):
            self._force_exit = True
            self.close()
        else:
            super().keyPressEvent(event)

    def _toggle_visibility_action_text(self, text: str):
        """更新托盘的显示/隐藏菜单文字"""
        if self._tray_icon:
            try:
                acts = self._tray_icon.contextMenu().actions()
                for a in acts:
                    if a.text() in ("显示窗口", "隐藏窗口"):
                        a.setText(text)
                        break
            except Exception:
                pass

    # ── 公共 API ──

    def start(self) -> None:
        self._fps_last_time = time.time()
        self._timer.start()
        # v4.17: 首次显示时定位覆盖层
        if hasattr(self, '_pause_overlay'):
            self._position_pause_overlay()

    def stop(self) -> None:
        self._timer.stop()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self._pause_btn.setText("▶ 继续" if paused else "⏸ 暂停")
        # v4.17: 暂停覆盖层
        if hasattr(self, '_pause_overlay'):
            self._pause_overlay.setVisible(paused)
            if paused:
                self._position_pause_overlay()
        # 按钮颜色随暂停状态切换
        self._pause_btn.set_color("#5A8A6D" if paused else "#8B8680")

    def is_paused(self) -> bool:
        return self._paused

    def show_frame(self, frame: np.ndarray, is_rgb: bool = False) -> None:
        """显示一帧视频画面

        Args:
            frame: 视频帧
            is_rgb: True 时 frame 已是 RGB，跳过颜色转换
        """
        if frame is not None:
            self._video_label.display_frame(frame, is_rgb=is_rgb)

    def _show_toast(self, text: str = "", style: str = "err") -> None:
        """显示 Toast 警告（单行，按优先级只显1个）"""
        if not text:
            self._toast_label.setVisible(False)
            return
        self._toast_label.setText(text)
        self._toast_label.setStyleSheet(self._style_toast.get(style, self._style_toast["err"]))
        self._toast_label.setVisible(True)

    def set_face_lost_warning(self, visible: bool) -> None:
        """人脸丢失 → 通过 Toast 显示"""
        if visible:
            self._show_toast("⚠ 人脸丢失 · 监测已暂停", "err")
        else:
            # 不直接隐藏，让 update_data 或调用者决定下一个 toast
            self._show_toast()

    def set_calibration_prompt(self, visible: bool) -> None:
        """v4.13: 设置校准提示可见性（footer 小字）"""
        if hasattr(self, '_calib_prompt'):
            self._calib_prompt.setVisible(visible)

    def update_data(self,
                    focus_score: Optional[float] = None,
                    fatigue_level: Optional[str] = None,
                    focus_level = None,         # v4.6: FocusLevel enum
                    fatigue_indicator = None,    # v4.6: FatigueIndicator enum
                    focus_duration_minutes: Optional[float] = None,
                    face_detected: bool = False,
                    eye_detected: bool = False,
                    fps: float = 0.0,
                    light_condition: Optional[str] = None,
                    distraction_causes: Optional[dict] = None) -> None:  # v4.17
        """更新所有显示数据 (v4.29: 缓存样式表避免每帧重绘)"""
        self._focus_duration_minutes = focus_duration_minutes
        self._face_detected = face_detected
        self._eye_detected = eye_detected
        self._fps = fps
        self._light_condition = light_condition

        # ── Hero 监测时长（值变化时更新） ──
        if focus_duration_minutes is not None:
            dur_text = str(int(focus_duration_minutes))
            if getattr(self, '_last_dur_text', None) != dur_text:
                self._hero_value.setText(dur_text)
                self._last_dur_text = dur_text
        else:
            if getattr(self, '_last_dur_text', None) != "--":
                self._hero_value.setText("--")
                self._last_dur_text = "--"

        # ── 专注度进度条（值变化 + 颜色变化时更新） ──
        if focus_score is not None:
            score = max(0, min(100, int(focus_score)))
            if getattr(self, '_last_focus_score', None) != score:
                self._last_focus_score = score
                self._focus_bar.setValue(score)
                self._focus_bar_value.setText(f"{score} / 100")
                # 颜色变化时才更新样式表
                if score >= 70:
                    new_color = "#5A8A6D"
                elif score >= 50:
                    new_color = "#C9843A"
                else:
                    new_color = "#B55C5C"
                if getattr(self, '_last_bar_color', None) != new_color:
                    self._last_bar_color = new_color
                    self._focus_bar.setStyleSheet(
                        "QProgressBar {"
                        "  background-color: #F2F2F7;"
                        "  border: none; border-radius: 3px;"
                        "}"
                        f"QProgressBar::chunk {{"
                        "  border-radius: 3px;"
                        f"  background-color: {new_color};"
                        "}"
                    )
        else:
            if getattr(self, '_last_focus_score', None) is not None:
                self._last_focus_score = None
                self._focus_bar.setValue(0)
                self._focus_bar_value.setText("-- / 100")

        # ── 识别状态（仅状态变化时更新） ──
        if not face_detected:
            new_status = "face_lost"
        elif not eye_detected:
            new_status = "eyes_closed"
        else:
            new_status = "normal"
        if getattr(self, '_last_face_status', None) != new_status:
            self._last_face_status = new_status
            if not face_detected:
                self._status_label.setText("🔴 人脸丢失")
                self._status_label.setStyleSheet("color: #B55C5C; background: transparent; border: none;")
            elif not eye_detected:
                self._status_label.setText("🟡 闭眼中")
                self._status_label.setStyleSheet("color: #C9843A; background: transparent; border: none;")
            else:
                self._status_label.setText("🟢 正常")
                self._status_label.setStyleSheet("color: #5A8A6D; background: transparent; border: none;")

        # ── Toast 警告（仅消息变化时更新） ──
        if not face_detected:
            new_toast = ("⚠ 人脸丢失 · 监测已暂停", "err")
        elif light_condition == "DARK":
            new_toast = ("⚠ 光照不足 · 检测精度可能下降", "warn")
        else:
            new_toast = None
        if getattr(self, '_last_toast', None) != new_toast:
            self._last_toast = new_toast
            if new_toast:
                self._show_toast(*new_toast)
            else:
                self._show_toast()

        # ── 分心原因 ──
        if hasattr(self, '_distraction_label') and distraction_causes != getattr(self, '_last_causes', None):
            self._last_causes = distraction_causes
            self._distraction_label.update_causes(distraction_causes or {})

        # ── 托盘状态 ──
        if self._tray_icon:
            self._tray_icon.update_status(focus_score=focus_score, fatigue_level=fatigue_level)

    def update_data_from_processor(self, frame_processor, fps: float = 0.0) -> None:
        """从 FrameProcessor 读取最新分析结果（兼容 main.py）"""
        fr = frame_processor.latest_focus_result
        fa = frame_processor.latest_fatigue_result
        face = frame_processor.latest_face_detected
        lr = getattr(frame_processor, 'latest_light_result', None)

        focus_score = None
        fatigue_level = None
        if fr is not None:
            focus_score = fr.focus_score
        if fa is not None:
            level = fa.fatigue_level
            fatigue_level = level.value.upper() if hasattr(level, 'value') else str(level)

        focus_dur = getattr(frame_processor, 'focus_duration_minutes', None)
        light_cond = lr.condition.value.upper() if lr else None

        # v4.17: 分心原因分解
        causes = {}
        if fr is not None:
            from analyzer.focus import compute_distraction_causes
            causes = compute_distraction_causes(fr)

        # v4.17: 眼睛检测状态从 FocusResult 获取，不再 aliased 到 face
        eyes_open = True
        if fr is not None and hasattr(fr, 'eye_openness'):
            eyes_open = fr.eye_openness > 0.5

        self.update_data(
            focus_score=focus_score,
            fatigue_level=fatigue_level,
            focus_duration_minutes=focus_dur,
            face_detected=face,
            eye_detected=eyes_open,
            fps=fps,
            light_condition=light_cond,
            distraction_causes=causes,
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
        """X 按钮关闭窗口 → 最小化到托盘（v4.10）"""
        if self._enable_tray and self._tray_icon and not self._force_exit:
            logger.info("窗口关闭 → 最小化到托盘")
            self.hide()
            event.ignore()
        else:
            logger.info("窗口关闭 → 退出程序")
            self.exit_requested.emit()
            event.accept()

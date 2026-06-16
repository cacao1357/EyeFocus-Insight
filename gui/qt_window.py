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
    DistractionLabel,
    FocusSparkline,
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
                 show_calibrate: bool = True, enable_tray: bool = True,
                 app_ref=None):
        super().__init__(parent)
        self._frame_buffer = frame_buffer
        self._show_calibrate = show_calibrate
        self._enable_tray = enable_tray
        self._force_exit = False

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

        # ── 上半：摄像头画面 (stretch 7) ──
        self._video_container = QWidget()
        self._video_container.setStyleSheet("background-color: #000000;")
        video_layout = QVBoxLayout(self._video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)
        self._video_label = VideoLabel()
        self._video_label.setStyleSheet("background-color: #000000;")
        video_layout.addWidget(self._video_label)
        # v4.17: 暂停覆盖层（居中半透明文字）
        self._pause_overlay = QLabel("⏸ 已暂停", self._video_container)
        self._pause_overlay.setAlignment(Qt.AlignCenter)
        self._pause_overlay.setStyleSheet(
            "color: white; background: rgba(0,0,0,140);"
            "font-size: 36px; font-weight: bold; border-radius: 12px;"
        )
        self._pause_overlay.setVisible(False)
        main_layout.addWidget(self._video_container, 7)

        # ── 下半：白色数据面板 (stretch 3) ──
        self._data_panel = DataPanel()
        panel_layout = QVBoxLayout(self._data_panel)
        panel_layout.setContentsMargins(0, 6, 0, 2)
        panel_layout.setSpacing(0)
        panel_layout.setAlignment(Qt.AlignCenter)

        # v4.19 新布局：左列[专注时长+番茄] | 圆环 | 右列[识别状态]
        content = QHBoxLayout()
        content.setSpacing(16)
        content.setAlignment(Qt.AlignCenter)

        # 左列：专注时长 + 番茄状态
        left_col = QVBoxLayout()
        left_col.setSpacing(6)
        left_col.setAlignment(Qt.AlignCenter)

        self._duration_card = StatusCard(
            emoji="⏱", main_text="--", label_text="专注时长", size=90)
        left_col.addWidget(self._duration_card)

        # v4.18 番茄状态移入左列
        self._pomodoro_card = StatusCard(
            emoji="🍅", main_text="--", label_text="番茄", size=90)
        left_col.addWidget(self._pomodoro_card)

        content.addLayout(left_col)

        # 中心圆环（字体放大）
        self._focus_ring = FocusRing()
        self._focus_ring.setMinimumSize(180, 180)
        content.addWidget(self._focus_ring)

        # 右列：识别状态（合并眼+脸）
        right_col = QVBoxLayout()
        right_col.setSpacing(6)
        right_col.setAlignment(Qt.AlignCenter)

        self._status_card = StatusCard(
            emoji="🟢", main_text="正常", label_text="识别状态", size=90)
        right_col.addWidget(self._status_card)

        content.addLayout(right_col)

        panel_layout.addLayout(content)

        # ── v4.17: 专注度波线 ──
        self._sparkline = FocusSparkline()
        panel_layout.addWidget(self._sparkline)

        # ── 光照警告标签（默认隐藏） ──
        self._light_warning.setAlignment(Qt.AlignCenter)
        self._light_warning.setStyleSheet(
            "color: #FF9500; background: #FFF3E0; border: 1px solid #FF9500;"
            "border-radius: 4px; padding: 4px 0; font-size: 12px;"
            "font-weight: 600; margin: 0 16px;"
        )
        self._light_warning.setVisible(False)
        panel_layout.addWidget(self._light_warning)

        # ── v4.17: 分心原因分解标签（默认隐藏） ──
        self._distraction_label = DistractionLabel()
        panel_layout.addWidget(self._distraction_label)

        # ── 人脸丢失警告标签（默认隐藏） ──
        self._face_lost_warning = QLabel("⚠ 人脸丢失 · 监测已暂停")
        self._face_lost_warning.setAlignment(Qt.AlignCenter)
        self._face_lost_warning.setStyleSheet(
            "color: #FF3B30; background: #FFEBEE; border: 1px solid #FF3B30;"
            "border-radius: 4px; padding: 4px 0; font-size: 12px;"
            "font-weight: 600; margin: 0 16px;"
        )
        self._face_lost_warning.setVisible(False)
        panel_layout.addWidget(self._face_lost_warning)

        # ── v4.17: 游戏化状态栏（专注天数 + 今日时长）──
        self._gamification_bar = QLabel("")
        self._gamification_bar.setAlignment(Qt.AlignCenter)
        self._gamification_bar.setStyleSheet(
            "color: #8B8680; background: transparent;"
            "border: none; font-size: 11px; padding: 2px 0;"
        )
        self._gamification_bar.setVisible(False)
        panel_layout.addWidget(self._gamification_bar)

        # ── v4.13: 校准提示标签（未校准时显示，校准后自动隐藏）──
        self._calib_prompt = QLabel("🟡 尚未校准 · 评分仅供参考 — 点击\"校准\"建立个人基线")
        self._calib_prompt.setAlignment(Qt.AlignCenter)
        self._calib_prompt.setStyleSheet(
            "color: #B8860B; background: #FFFDE7; border: 1px solid #FFD54F;"
            "border-radius: 4px; padding: 6px 0; font-size: 12px;"
            "font-weight: 500; margin: 0 16px;"
        )
        self._calib_prompt.setVisible(True)  # 默认显示（未校准状态）
        panel_layout.addWidget(self._calib_prompt)

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

        # ── v4.10: 系统托盘 ──
        self._tray_icon = None
        if self._enable_tray and app_ref is not None:
            from gui.tray import EyeFocusTrayIcon
            self._tray_icon = EyeFocusTrayIcon(parent_window=self, app_ref=app_ref)
            self._tray_icon.show()

    # ── v4.18: 番茄状态 ──

    def update_pomodoro(self, status: dict) -> None:
        """更新番茄状态显示"""
        if hasattr(self, '_pomodoro_card'):
            s = status["state"]
            if s == "IDLE":
                self._pomodoro_card.update_data(
                    main_text="--", label_text="番茄", emoji="🍅", status="ok")
            else:
                remaining = status["remaining_sec"]
                rm, rs = divmod(remaining, 60)
                time_str = f"{rm:02d}:{rs:02d}"
                emoji = "🍅" if s == "WORKING" else "☕"
                self._pomodoro_card.update_data(
                    main_text=time_str, label_text=emoji + " 番茄",
                    emoji="", status="ok")

    # ── v4.17: 专注度波线 ──

    def update_sparkline(self, focus_score: float) -> None:
        """每秒添加一个专注度点到波线"""
        if hasattr(self, '_sparkline') and self._sparkline is not None:
            self._sparkline.add_point(focus_score)

    # ── v4.17: 游戏化 ──

    def update_gamification(self, streak_days: int = 0, today_minutes: float = 0.0) -> None:
        """更新游戏化状态显示（专注天数 + 今日时长）"""
        parts = []
        if streak_days > 0:
            fire = "🔥" if streak_days >= 3 else ""
            parts.append(f"{fire}连续 {streak_days} 天")
        if today_minutes > 0:
            parts.append(f"今日 {today_minutes:.0f} 分钟")
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
        self._pause_btn.setText("继续" if paused else "暂停")
        # v4.17: 暂停覆盖层
        if hasattr(self, '_pause_overlay'):
            self._pause_overlay.setVisible(paused)
            if paused:
                self._position_pause_overlay()
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

    def show_frame(self, frame: np.ndarray) -> None:
        """直接显示一帧（从 _qt_process_frame 推送，解决 timer 时序依赖）"""
        if frame is not None:
            self._video_label.display_frame(frame)

    def set_face_lost_warning(self, visible: bool) -> None:
        """设置人脸丢失警告可见性"""
        if hasattr(self, '_face_lost_warning'):
            self._face_lost_warning.setVisible(visible)

    def set_calibration_prompt(self, visible: bool) -> None:
        """v4.13: 设置校准提示可见性"""
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
        """更新所有显示数据 (v4.6: 支持新 FocusLevel/FatigueIndicator)"""
        # v4.6: 提取字符串值
        fl_str = focus_level.value if hasattr(focus_level, 'value') else focus_level
        fi_str = fatigue_indicator.value if hasattr(fatigue_indicator, 'value') else fatigue_indicator

        self._focus_duration_minutes = focus_duration_minutes
        self._face_detected = face_detected
        self._eye_detected = eye_detected
        self._fps = fps
        self._light_condition = light_condition

        # 光照警告
        if light_condition == "DARK":
            self._light_warning.setVisible(True)
        else:
            self._light_warning.setVisible(False)

        # FocusRing — 优先使用 v4.6 参数
        self._focus_ring.update_data(
            focus_level=fl_str,
            fatigue_indicator=fi_str,
            focus_score=focus_score,       # 向后兼容
            fatigue_level=fatigue_level,   # 向后兼容
        )

        # v4.19: 疲劳信息已整合到 FocusRing 圆点中，不再单独卡片

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

        # v4.19: 识别状态卡片（合并眼+脸）
        if not face_detected:
            status_text = "丢失"
            status_emoji = "🔴"
            status_st = "error"
        elif not eye_detected:
            status_text = "闭眼"
            status_emoji = "🟡"
            status_st = "warn"
        else:
            status_text = "正常"
            status_emoji = "🟢"
            status_st = "ok"
        self._status_card.update_data(
            main_text=status_text,
            label_text="识别状态",
            emoji=status_emoji,
            status=status_st,
        )

        # v4.17: 分心原因分解
        if hasattr(self, '_distraction_label'):
            self._distraction_label.update_causes(distraction_causes or {})

        # v4.10: 同步更新托盘状态
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

"""
gui/tray.py — 系统托盘图标 (v4.10)

支持：
- 左键双击 → 显示/隐藏窗口
- 右键菜单 → 暂停/继续、生成报告、重新校准、免打扰、退出
- 图标颜色随专注度变化（绿/黄/红）
- 启动通知（2s 自动消失）/ 疲劳提醒（3s 自动消失）
"""

import logging
import os
from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import QAction, QMenu, QSystemTrayIcon

logger = logging.getLogger("eyefocus.gui.tray")


class EyeFocusTrayIcon(QSystemTrayIcon):
    """系统托盘图标 — 专注度实时状态 + 上下文菜单"""

    def __init__(self, parent_window, app_ref):
        """
        Args:
            parent_window: EyeFocusWindow 实例
            app_ref: EyeFocusApp 实例（用于调用 pause/finalize/calibrate）
        """
        super().__init__(parent_window)
        self._window = parent_window
        self._app = app_ref
        self._do_not_disturb = False
        self._focus_score: Optional[float] = None

        # 生成初始图标（灰色默认）
        self.setIcon(self._create_icon("#BDBDBD"))
        self.setToolTip("EyeFocus Insight\n专注度: --")

        # 创建右键菜单
        self._create_context_menu()

        # 左键双击事件
        self.activated.connect(self._on_activated)

        # 启动后 2s 显示启动通知
        QTimer.singleShot(2000, self._show_startup_notification)

    def _create_icon(self, color_hex: str) -> QIcon:
        """程序化生成 16x16 圆形图标"""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(color_hex))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(1, 1, 14, 14)
        painter.end()
        return QIcon(pixmap)

    def _create_context_menu(self):
        """创建右键菜单"""
        menu = QMenu()

        # 状态标题（不可交互）
        self._status_action = menu.addAction("专注度: --")
        self._status_action.setEnabled(False)
        menu.addSeparator()

        # 显示/隐藏
        self._toggle_visibility_action = menu.addAction("显示窗口")
        self._toggle_visibility_action.triggered.connect(self._toggle_visibility)

        # 暂停/继续
        self._pause_action = menu.addAction("暂停监测")
        self._pause_action.triggered.connect(self._toggle_pause)

        menu.addSeparator()

        # 打开报告（自动生成）
        generate_action = menu.addAction("打开报告")
        generate_action.triggered.connect(self._generate_report)

        # 重新校准
        calibrate_action = menu.addAction("重新校准")
        calibrate_action.triggered.connect(self._start_calibration)

        menu.addSeparator()

        # v4.17: 语音反馈开关
        self._voice_action = menu.addAction("启用语音反馈")
        self._voice_action.setCheckable(True)
        self._voice_action.setChecked(True)
        self._voice_action.triggered.connect(self._toggle_voice)

        # 免打扰模式
        self._dnd_action = menu.addAction("免打扰模式")
        self._dnd_action.setCheckable(True)
        self._dnd_action.setChecked(False)
        self._dnd_action.triggered.connect(self._toggle_dnd)

        menu.addSeparator()

        # 退出
        exit_action = menu.addAction("退出 EyeFocus Insight")
        exit_action.triggered.connect(self._exit_app)

        self.setContextMenu(menu)

    # ── 公共 API ──

    def update_status(self, focus_score: Optional[float], fatigue_level: Optional[str] = None):
        """更新托盘状态：图标颜色 + 提示文字 + 菜单标签"""
        self._focus_score = focus_score
        if focus_score is None:
            color = "#BDBDBD"
            label = "--"
        elif focus_score >= 70:
            color = "#4CAF50"
            label = f"{focus_score:.0f} (良好)"
        elif focus_score >= 40:
            color = "#FF9800"
            label = f"{focus_score:.0f} (一般)"
        else:
            color = "#F44336"
            label = f"{focus_score:.0f} (分心)"

        self.setIcon(self._create_icon(color))
        self.setToolTip(f"EyeFocus Insight\n专注度: {label}")
        self._status_action.setText(f"专注度: {label}")

    def set_paused_state(self, paused: bool):
        """同步暂停状态到菜单项"""
        self._pause_action.setText("继续监测" if paused else "暂停监测")

    def set_voice_enabled(self, enabled: bool):
        """同步语音状态到菜单项"""
        self._voice_action.setChecked(enabled)

    def set_do_not_disturb(self, enabled: bool):
        """设置免打扰模式"""
        self._do_not_disturb = enabled
        self._dnd_action.setChecked(enabled)

    def is_do_not_disturb(self) -> bool:
        return self._do_not_disturb

    def show_fatigue_notification(self, message: str = "检测到疲劳，建议休息"):
        """显示疲劳提醒气泡（3s 自动消失）"""
        if not self._do_not_disturb:
            self.showMessage(
                "EyeFocus Insight - 疲劳提醒",
                message,
                QSystemTrayIcon.Information,
                3000,
            )

    # ── 内部方法 ──

    def _show_startup_notification(self):
        """启动通知（2s 自动消失）"""
        self.showMessage(
            "EyeFocus Insight",
            "程序已启动，正在后台监测您的专注状态",
            QSystemTrayIcon.Information,
            2000,
        )

    def _on_activated(self, reason):
        """处理托盘图标激活事件"""
        if reason == QSystemTrayIcon.DoubleClick:
            self._toggle_visibility()

    def _toggle_visibility(self):
        """切换窗口显示/隐藏"""
        if self._window.isVisible():
            self._window.hide()
            self._toggle_visibility_action.setText("显示窗口")
        else:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()
            self._toggle_visibility_action.setText("隐藏窗口")

    def _toggle_pause(self):
        """切换暂停/继续"""
        self._window.toggle_pause()
        paused = self._window.is_paused()
        self.set_paused_state(paused)

    def _generate_report(self):
        """生成报告并自动打开"""
        logger.info("托盘菜单: 打开报告")
        if not hasattr(self._app, '_finalize_session'):
            logger.warning("无法生成报告: _app 无 _finalize_session")
            return
        self._app._finalize_session()
        # 自动在浏览器中打开报告
        sid = getattr(self._app, '_session_id', None)
        if sid:
            report_path = os.path.abspath(f"reports/{sid}.html")
            if os.path.exists(report_path):
                try:
                    os.startfile(report_path)
                    logger.info("报告已打开: %s", report_path)
                except Exception as e:
                    logger.warning("打开报告失败: %s", e)

    def _start_calibration(self):
        """启动重新校准（v4.16: try/except 保护，防止异常导致程序退出）"""
        logger.info("托盘菜单: 重新校准")
        try:
            if hasattr(self._app, '_on_qt_calibrate'):
                self._app._on_qt_calibrate()
            elif hasattr(self._app, 'start_calibration_flow'):
                self._app.start_calibration_flow()
            else:
                logger.warning("无法启动校准: _app 无校准方法")
        except Exception as e:
            logger.error("重新校准异常: %s", e)
            import traceback
            traceback.print_exc()

    def _toggle_voice(self, checked: bool):
        """切换语音反馈"""
        logger.info("语音反馈: %s", "ON" if checked else "OFF")
        try:
            if hasattr(self._app, '_voice_asst') and self._app._voice_asst is not None:
                self._app._voice_asst.set_enabled(checked)
        except Exception as e:
            logger.warning("切换语音反馈失败: %s", e)

    def _toggle_dnd(self, checked: bool):
        """切换免打扰模式"""
        self._do_not_disturb = checked
        logger.info("免打扰模式: %s", "ON" if checked else "OFF")

    def _exit_app(self):
        """完全退出程序"""
        logger.info("托盘菜单: 退出程序")
        # 先移除托盘图标，避免残留
        self.hide()
        # 设置强制退出标志，使 closeEvent 真正关闭而不是隐藏
        if hasattr(self._window, '_force_exit'):
            self._window._force_exit = True
        self._window.close()

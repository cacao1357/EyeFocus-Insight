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

        # v4.22: 移除启动通知（正常操作不弹窗）

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

        # v4.18: 最近会话子菜单
        self._recent_menu = menu.addMenu("最近会话")
        self._recent_menu.aboutToShow.connect(self._refresh_recent_sessions)

        # 打开报告（自动生成）
        generate_action = menu.addAction("打开报告")
        generate_action.triggered.connect(self._generate_report)

        # v4.18: 生成周报
        weekly_action = menu.addAction("生成周报")
        weekly_action.triggered.connect(self._generate_weekly_report)

        # v4.18: 导出数据
        export_action = menu.addAction("导出数据")
        export_action.triggered.connect(self._export_data)

        # v4.18: 番茄工作法（v4.20: 增加暂停/设置）
        self._pomodoro_action = menu.addAction("开始番茄")
        self._pomodoro_action.triggered.connect(self._toggle_pomodoro)
        self._pomodoro_pause_action = menu.addAction("暂停番茄")
        self._pomodoro_pause_action.setEnabled(False)
        self._pomodoro_pause_action.triggered.connect(self._pause_pomodoro)
        pomodoro_set_action = menu.addAction("设置番茄...")
        pomodoro_set_action.triggered.connect(self._set_pomodoro)

        # 重新校准
        calibrate_action = menu.addAction("重新校准")
        calibrate_action.triggered.connect(self._start_calibration)

        menu.addSeparator()

        # v4.17: 语音反馈开关（默认值从 config.yaml 读取）
        voice_enabled = True
        try:
            from config import get_yaml_value
            voice_enabled = get_yaml_value("voice", "enabled", default=True)
        except Exception:
            pass
        self._voice_action = menu.addAction("启用语音反馈")
        self._voice_action.setCheckable(True)
        self._voice_action.setChecked(voice_enabled)
        self._voice_action.triggered.connect(self._toggle_voice)

        # 免打扰模式
        self._dnd_action = menu.addAction("免打扰模式")
        self._dnd_action.setCheckable(True)
        self._dnd_action.setChecked(False)
        self._dnd_action.triggered.connect(self._toggle_dnd)

        # v4.22: 设置面板
        settings_action = menu.addAction("设置...")
        settings_action.triggered.connect(self._show_settings)

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
        # v4.18: tooltip 加入番茄状态
        pomo_info = ""
        try:
            if hasattr(self._app, '_pomodoro') and self._app._pomodoro is not None:
                s = self._app._pomodoro.state
                c = self._app._pomodoro.count
                if s == "WORKING":
                    pomo_info = f"\n🍅 番茄工作中 ×{c}"
                elif s == "BREAK":
                    pomo_info = "\n☕ 休息中"
        except Exception:
            pass
        self.setToolTip(f"EyeFocus Insight\n专注度: {label}{pomo_info}")
        self._status_action.setText(f"专注度: {label}")

    def set_paused_state(self, paused: bool):
        """同步暂停状态到菜单项"""
        self._pause_action.setText("继续监测" if paused else "暂停监测")

    def set_pomodoro_state(self, state: str, count: int = 0):
        """同步番茄状态到菜单项"""
        labels = {
            "IDLE": "开始番茄",
            "WORKING": f"🍅 ×{count} 工作中..." if count else "番茄工作中...",
            "BREAK": "☕ 休息中...",
            "PAUSED": "⏸ 已暂停",
        }
        self._pomodoro_action.setText(labels.get(state, "开始番茄"))
        can_pause = state in ("WORKING", "BREAK")
        self._pomodoro_pause_action.setEnabled(can_pause)
        self._pomodoro_pause_action.setText("继续番茄" if state == "PAUSED" else "暂停番茄")

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
        """v4.22: 疲劳提醒已移除（正常操作不弹窗）"""
        pass

    # ── 内部方法 ──

    def _show_startup_notification(self):
        """v4.22: 启动通知已移除（正常操作不弹窗）"""
        pass

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
        """生成报告快照（不终止会话）并自动打开

        v4.22 修复: 改用 generate_report_snapshot 而非 _finalize_session，
        避免托盘"打开报告"意外结束当前会话。
        """
        logger.info("托盘菜单: 打开报告")
        if not hasattr(self._app, 'generate_report_snapshot'):
            logger.warning("无法生成报告: _app 无 generate_report_snapshot")
            return

        # v4.22: 移除"报告生成中"进度通知（正常操作不弹窗）
        report_path = self._app.generate_report_snapshot()
        if report_path and os.path.exists(report_path):
            try:
                os.startfile(report_path)
                logger.info("报告已打开（会话继续）: %s", report_path)
            except Exception as e:
                logger.warning("打开报告失败: %s", e)
                self.showMessage(
                    "EyeFocus Insight", "打开报告失败，请手动打开 reports/ 目录",
                    QSystemTrayIcon.Critical, 3000,
                )
        else:
            logger.warning("报告生成失败或文件不存在")
            self.showMessage(
                "EyeFocus Insight", "报告生成失败，数据不足或系统错误",
                QSystemTrayIcon.Critical, 3000,
            )

    # ── v4.18: 最近会话 ──

    def _refresh_recent_sessions(self):
        """刷新最近会话子菜单（aboutToShow 时调用）"""
        self._recent_menu.clear()
        try:
            if not hasattr(self._app, '_db') or self._app._db is None:
                self._recent_menu.addAction("数据库未就绪").setEnabled(False)
                return

            sessions = self._app._db.list_sessions()[:10]  # 最近 10 条
            if not sessions:
                self._recent_menu.addAction("无历史记录").setEnabled(False)
                return

            for sess in sessions:
                start = sess.start_time.strftime("%m-%d %H:%M")
                dur = sess.duration_seconds()
                dur_str = f"{int(dur//60)}分钟" if dur else "--"
                avg = self._get_session_avg(sess.session_id)
                # 质量图标
                try:
                    avg_f = float(avg)
                    icon = "🟢" if avg_f >= 70 else "🟡" if avg_f >= 40 else "🔴"
                except (ValueError, TypeError):
                    icon = "⚪"
                cal_badge = "✓" if sess.is_calibrated else ""
                label = f"{icon} {start}  {dur_str}  {avg}分 {cal_badge}"
                action = self._recent_menu.addAction(label)
                sid = sess.session_id
                action.triggered.connect(lambda checked, s=sid: self._open_report(s))
        except Exception as e:
            logger.warning("刷新最近会话失败: %s", e)
            self._recent_menu.addAction("加载失败").setEnabled(False)

    def _get_session_avg(self, session_id: str) -> str:
        """获取会话平均专注度"""
        try:
            records = self._app._db.get_focus_records(session_id)
            if records:
                scores = [r.focus_score for r in records if r.focus_score is not None]
                if scores:
                    return f"{sum(scores)/len(scores):.0f}"
            return "--"
        except Exception:
            return "--"

    def _open_report(self, session_id: str) -> None:
        """打开指定会话的报告"""
        try:
            report_path = os.path.abspath(f"reports/{session_id}.html")
            if os.path.exists(report_path):
                os.startfile(report_path)
                logger.info("已打开报告: %s", report_path)
            else:
                # 报告文件不存在 → 尝试重新生成（不终止会话）
                logger.warning("报告文件不存在，尝试重新生成: %s", report_path)
                self._try_regenerate_report(session_id)
        except Exception as e:
            logger.warning("打开报告失败: %s", e)

    def _try_regenerate_report(self, session_id: str) -> None:
        """尝试为指定会话重新生成报告文件"""
        try:
            from reporter.report_html import create_html_generator
            import os
            if not hasattr(self._app, '_db') or self._app._db is None:
                logger.warning("无法重新生成报告: 数据库未就绪")
                return
            generator = create_html_generator(self._app._db)
            html = None
            try:
                html = generator.generate_report_with_insights(session_id)
            except Exception:
                try:
                    html = generator.generate_report(session_id)
                except Exception as e2:
                    logger.warning("重新生成报告失败 (基础报告也失败): %s", e2)
            if html:
                path = os.path.abspath(f"reports/{session_id}.html")
                os.makedirs("reports", exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html)
                os.startfile(path)
                logger.info("报告已重新生成并打开: %s", session_id)
        except Exception as e:
            logger.warning("重新生成报告失败: %s", e)

    # ── v4.18: 导出数据 ──

    def _generate_weekly_report(self) -> None:
        """生成周报"""
        try:
            if hasattr(self._app, '_generate_weekly_report'):
                self._app._generate_weekly_report()
        except Exception as e:
            logger.warning("生成周报失败: %s", e)

    def _export_data(self) -> None:
        """导出当前会话数据为 CSV"""
        try:
            sid = getattr(self._app, '_session_id', None)
            if not sid:
                return
            import os
            out_dir = os.path.abspath("reports/exports")
            self._app._db.export_csv(sid, out_dir)
            # v4.22: 移除导出成功通知（正常操作不弹窗）
            logger.info("CSV 导出完成: %s", out_dir)
        except Exception as e:
            logger.warning("导出数据失败: %s", e)
            self.showMessage(
                "EyeFocus Insight - 导出失败",
                str(e),
                QSystemTrayIcon.Critical,
                3000,
            )

    # ── v4.18: 番茄工作法 ──

    def _toggle_pomodoro(self) -> None:
        """切换番茄工作法：IDLE→开始 / WORKING→停止 / BREAK→跳过"""
        try:
            pomo = getattr(self._app, '_pomodoro', None)
            if pomo is None:
                return
            if pomo.state == "IDLE":
                pomo.start()
            else:
                pomo.stop()
            self.set_pomodoro_state(pomo.state, pomo.count)
        except Exception as e:
            logger.warning("番茄切换失败: %s", e)

    def _pause_pomodoro(self) -> None:
        """暂停或继续番茄"""
        try:
            pomo = getattr(self._app, '_pomodoro', None)
            if pomo is None or pomo.state == "IDLE":
                return
            if getattr(pomo, '_paused', False):
                pomo.resume()
            else:
                pomo.pause()
            self.set_pomodoro_state(pomo.state, pomo.count)
        except Exception as e:
            logger.warning("番茄暂停失败: %s", e)

    def _set_pomodoro(self) -> None:
        """设置番茄工作/休息时间"""
        try:
            from PyQt5.QtWidgets import QInputDialog
            work, ok = QInputDialog.getInt(None, "设置番茄",
                "工作分钟数 (1-120):", value=25, min=1, max=120)
            if not ok:
                return
            rest, ok = QInputDialog.getInt(None, "设置番茄",
                "休息分钟数 (1-60):", value=5, min=1, max=60)
            if not ok:
                return
            pomo = getattr(self._app, '_pomodoro', None)
            if pomo:
                pomo.set_duration(work, rest)
        except Exception as e:
            logger.warning("设置番茄失败: %s", e)

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

    def _show_settings(self):
        """打开设置对话框"""
        from gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._window)
        dlg.exec_()
        # 保存后刷新语音开关状态
        try:
            from config import get_yaml_value
            voice_enabled = get_yaml_value("voice", "enabled", default=True)
            self.set_voice_enabled(voice_enabled)
        except Exception:
            pass

    def _exit_app(self):
        """完全退出程序"""
        logger.info("托盘菜单: 退出程序")
        # 先移除托盘图标，避免残留
        self.hide()
        # 设置强制退出标志，使 closeEvent 真正关闭而不是隐藏
        if hasattr(self._window, '_force_exit'):
            self._window._force_exit = True
        self._window.close()

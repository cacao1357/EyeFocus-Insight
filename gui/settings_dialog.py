"""
gui/settings_dialog.py — 图形化设置面板 (v4.22)

替代 config.yaml 手动编辑，提供 GUI 配置：
- 摄像头选择
- 语音反馈开关
- 番茄工作法时间
- 数据目录

与托盘菜单"设置..."项集成。
"""

import logging
import os
import sys
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("eyefocus.gui.settings")


class SettingsDialog(QDialog):
    """应用设置对话框"""

    # 主题色 — 与 qt_window.py 保持一致
    COLOR_IRIS = "#5B4A8C"
    COLOR_SAGE = "#5A8A6D"
    COLOR_AMBER = "#C9843A"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._load_config()
        self._build_ui()
        self.setWindowTitle("EyeFocus 设置")
        self.setMinimumWidth(420)
        self.setModal(True)

    def _load_config(self) -> None:
        """从 config.yaml 读取当前值"""
        from config import get_yaml_value

        self._camera_index = get_yaml_value("camera", "index", default=0)
        self._voice_enabled = get_yaml_value("voice", "enabled", default=True)
        self._pomo_work = 25  # 默认值，与 pomodoro.py 一致
        self._pomo_break = 5
        self._data_dir = get_yaml_value("data", "db_path", default="data/eyefocus.db")

        # 尝试从主程序读取番茄当前设置
        self._try_load_pomodoro_settings()

    def _try_load_pomodoro_settings(self) -> None:
        """尝试从运行中的 EyeFocusApp 读取番茄设置"""
        try:
            # 从 parent window 链路上找 app
            app = getattr(self.parent(), '_app', None) or getattr(
                getattr(self.parent(), 'parent', None), '_app', None
            )
            if app and hasattr(app, '_pomodoro') and app._pomodoro is not None:
                st = app._pomodoro.get_status()
                self._pomo_work = st.get("work_min", 25)
                self._pomo_break = st.get("break_min", 5)
        except Exception:
            pass

    def _build_ui(self) -> None:
        """构建界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # ── 摄像头 ──
        cam_group = QGroupBox("📷 摄像头")
        cam_layout = QFormLayout(cam_group)
        self._cam_combo = QComboBox()
        for i in range(4):
            self._cam_combo.addItem(f"摄像头 {i}", i)
        self._cam_combo.setCurrentIndex(min(self._camera_index, 3))
        cam_layout.addRow("设备索引：", self._cam_combo)
        cam_layout.addRow("",
            QLabel("修改后需重启程序生效"))
        layout.addWidget(cam_group)

        # ── 语音 ──
        voice_group = QGroupBox("🎤 语音反馈")
        voice_layout = QVBoxLayout(voice_group)
        self._voice_check = QCheckBox("启用语音播报")
        self._voice_check.setChecked(self._voice_enabled)
        voice_layout.addWidget(self._voice_check)
        voice_layout.addWidget(
            QLabel("TTS 基于 pyttsx3 (仅 Windows SAPI5)"))
        layout.addWidget(voice_group)

        # ── 番茄工作法 ──
        pomo_group = QGroupBox("🍅 番茄工作法")
        pomo_layout = QFormLayout(pomo_group)
        self._pomo_work_spin = QSpinBox()
        self._pomo_work_spin.setRange(1, 120)
        self._pomo_work_spin.setSuffix(" 分钟")
        self._pomo_work_spin.setValue(self._pomo_work)
        pomo_layout.addRow("工作时长：", self._pomo_work_spin)

        self._pomo_break_spin = QSpinBox()
        self._pomo_break_spin.setRange(1, 60)
        self._pomo_break_spin.setSuffix(" 分钟")
        self._pomo_break_spin.setValue(self._pomo_break)
        pomo_layout.addRow("休息时长：", self._pomo_break_spin)
        layout.addWidget(pomo_group)

        # ── 数据 ──
        data_group = QGroupBox("💾 数据")
        data_layout = QVBoxLayout(data_group)
        data_layout.addWidget(
            QLabel(f"数据库：{self._data_dir}"))
        data_layout.addWidget(
            QLabel("数据存储在本地 SQLite，0 HTTP 请求"))
        layout.addWidget(data_group)

        # ── 按钮 ──
        layout.addStretch()
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._save_btn = QPushButton("💾 保存设置")
        self._save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.COLOR_IRIS};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 24px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #4A3B7A;
            }}
        """)
        self._save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(self._save_btn)

        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #E0E0E0;
                color: #333;
                border: none;
                border-radius: 6px;
                padding: 8px 24px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #D0D0D0;
            }
        """)
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        layout.addLayout(btn_layout)

    def _on_save(self) -> None:
        """保存设置并关闭"""
        from config import set_yaml_value, save_yaml_config

        # 收集值
        camera_idx = self._cam_combo.currentData()
        voice_on = self._voice_check.isChecked()
        pomo_work = self._pomo_work_spin.value()
        pomo_break = self._pomo_break_spin.value()

        # 写入运行时配置
        set_yaml_value("camera", "index", value=camera_idx)
        set_yaml_value("voice", "enabled", value=voice_on)

        # 番茄时间不持久化到 config.yaml（但应用到运行中引擎）
        self._apply_pomodoro_settings(pomo_work, pomo_break)

        # 持久化
        ok = save_yaml_config()
        if ok:
            logger.info("设置已保存: camera=%d, voice=%s, pomo=%d/%d",
                        camera_idx, voice_on, pomo_work, pomo_break)
        else:
            logger.warning("设置保存失败 (config.yaml 不可写)")

        self.accept()

    def _apply_pomodoro_settings(self, work: int, brake: int) -> None:
        """将番茄设置应用到运行中引擎（如果有）"""
        try:
            app = getattr(self.parent(), '_app', None)
            if app and hasattr(app, '_pomodoro') and app._pomodoro is not None:
                app._pomodoro.set_duration(work, brake)
                logger.info("番茄时间已应用: 工作%d分, 休息%d分", work, brake)
        except Exception as e:
            logger.warning("番茄设置应用失败: %s", e)

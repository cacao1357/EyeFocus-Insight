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
    QInputDialog,
    QLineEdit,
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


# ════════════════════════════════════════
# v4.26 颜色 token 统一
# 跟项目 Quiet Focus 调色板（与 report/ qt_window/ qt_overlay 一致）
# ════════════════════════════════════════
COLOR_PAPER = "#FFFFFF"
COLOR_LINE = "#E0E0E0"
COLOR_QUIET = "#8B8680"  # v4.26 替换 #8E8E93
COLOR_INK = "#1C1C1E"   # v4.26 统一为 #1C1C1E（去掉 #23201E / #1C1C1E 两套）


# v4.26 番茄设置 dialog 专用白底 QSS（替代 QInputDialog.getInt 黑底）
_POMO_INPUT_DIALOG_QSS = """
    QDialog { background-color: #FFFFFF; }
    QLabel {
        color: #1C1C1E; background: transparent; font-size: 14px;
    }
    QSpinBox, QLineEdit {
        background-color: #FFFFFF; color: #1C1C1E;
        border: 1px solid #D0D0D0; border-radius: 4px;
        padding: 4px 8px;
        selection-background-color: #5B4A8C; selection-color: #FFFFFF;
        font-size: 14px; min-height: 22px;
    }
    QSpinBox:focus, QLineEdit:focus {
        border: 1px solid #5B4A8C; outline: 0;
    }
    QSpinBox::up-button, QSpinBox::down-button {
        background: #F8F6F2; border: 1px solid #D0D0D0; width: 20px;
    }
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {
        background: #F0EBF8;
    }
    QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {
        background: #E0E0E0;
    }
    QPushButton {
        background-color: #F0F0F0; color: #1C1C1E;
        border: 1px solid #D0D0D0; border-radius: 4px;
        padding: 6px 18px; font-size: 13px; min-width: 70px;
    }
    QPushButton:hover { background-color: #E5E5E5; }
    QPushButton:pressed { background-color: #D8D8D8; }
    QPushButton:default {
        background-color: #5B4A8C; color: #FFFFFF;
        border: 1px solid #4A3A7A; font-weight: 600;
    }
    QPushButton:default:hover { background-color: #4A3A7A; }
    QPushButton:default:pressed { background-color: #3A2A6A; }
"""


def ask_pomo_int(parent, title: str, label: str,
                 value: int, min_val: int, max_val: int) -> Optional[int]:
    """v4.26 白底番茄分钟数输入框（替代 QInputDialog.getInt 黑底）

    Qt 自带 QInputDialog 在系统暗色主题下黑底、字看不清。
    重写为可 setStyleSheet 的非静态版本，套白底 QSS。
    v4.26.1: 去掉标题栏左侧 "?" 帮助按钮（Qt.WindowContextHelpButtonHint）
    """
    dlg = QInputDialog(parent)
    # v4.26.1: 去掉标题栏 ? 按钮，与项目"白底简洁"风格一致
    flags = dlg.windowFlags()
    flags &= ~Qt.WindowContextHelpButtonHint
    dlg.setWindowFlags(flags)
    dlg.setStyleSheet(_POMO_INPUT_DIALOG_QSS)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setIntRange(min_val, max_val)
    dlg.setIntValue(value)
    if dlg.exec_() == QInputDialog.Accepted:
        return dlg.intValue()
    return None


class SettingsDialog(QDialog):
    """应用设置对话框"""

    # 主题色 — 与 qt_window.py 保持一致
    COLOR_IRIS = "#5B4A8C"
    COLOR_SAGE = "#5A8A6D"
    COLOR_AMBER = "#C9843A"

    # v4.26 统一下拉/输入白底 QSS
    # 关键：setStyleSheet 在 QDialog 级别无法覆盖 popup 窗口
    # （Qt 的 popup 是独立 top-level，QSS 选择器不传递），
    # 必须把 QSS 直接绑到每个 QComboBox/QSpinBox/QLineEdit 实例上。
    INPUT_WIDGET_QSS = """
        QComboBox, QSpinBox, QLineEdit {
            background-color: #FFFFFF; color: #1C1C1E;
            border: 1px solid #D0D0D0; border-radius: 4px;
            padding: 4px 8px;
            selection-background-color: #5B4A8C; selection-color: #FFFFFF;
        }
        QComboBox:hover, QSpinBox:hover, QLineEdit:hover {
            border: 1px solid #5B4A8C;
        }
        QComboBox:focus, QSpinBox:focus, QLineEdit:focus {
            border: 1px solid #5B4A8C; outline: 0;
        }
        QComboBox::drop-down {
            subcontrol-origin: padding; subcontrol-position: top right;
            width: 20px; border-left: 1px solid #D0D0D0;
            background: #F8F6F2;
        }
        QComboBox::drop-down:hover { background: #F0EBF8; }
        QComboBox QAbstractItemView {
            background-color: #FFFFFF; color: #1C1C1E;
            selection-background-color: #5B4A8C; selection-color: #FFFFFF;
            border: 1px solid #D0D0D0; outline: 0; padding: 2px;
        }
        QComboBox QAbstractItemView::item {
            padding: 6px 10px; border: none;
            background-color: transparent; color: #1C1C1E;
            min-height: 20px;
        }
        QComboBox QAbstractItemView::item:hover {
            background-color: #F0EBF8; color: #1C1C1E;
        }
        QSpinBox::up-button, QSpinBox::down-button {
            background: #F8F6F2; border: 1px solid #D0D0D0; width: 18px;
        }
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {
            background: #F0EBF8;
        }
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._load_config()
        self._build_ui()
        self.setWindowTitle("EyeFocus 设置")
        self.setMinimumWidth(420)
        self.setModal(True)
        # v4.22: 强制白底（防止系统暗色模式导致全黑不可读）
        # v4.26: QComboBox/QSpinBox/QLineEdit 规则不在这里（绑在实例上才能覆盖 popup）
        self.setStyleSheet("""
            QDialog { background-color: #FFFFFF; }
            QGroupBox {
                background-color: #FFFFFF;
                border: 1px solid #E0E0E0;
                border-radius: 8px;
                margin-top: 10px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 6px;
                color: #1C1C1E; background-color: transparent;
            }
            QLabel { background: transparent; color: #1C1C1E; }
            QCheckBox {
                background: transparent; color: #1C1C1E; spacing: 6px;
            }
            QCheckBox::indicator {
                width: 14px; height: 14px;
                background-color: #FFFFFF; border: 1px solid #D0D0D0;
                border-radius: 2px;
            }
            QCheckBox::indicator:hover { border: 1px solid #5B4A8C; }
            QCheckBox::indicator:checked {
                background-color: #5B4A8C; border: 1px solid #5B4A8C;
            }
            QPushButton {
                background-color: #F0F0F0; color: #1C1C1E;
                border: 1px solid #D0D0D0; border-radius: 6px;
                padding: 8px 24px; font-size: 14px; min-width: 80px;
            }
            QPushButton:hover { background-color: #E5E5E5; }
            QPushButton:pressed { background-color: #D8D8D8; }
            QPushButton:disabled { background-color: #F8F6F2; color: #8B8680; }
            /* v4.26.3: API key 切换按钮 QSS 改在按钮实例上设置（QDialog 级 #apiKeyToggle 规则被系统主题覆盖，仍渲染为黑）
               此处不再设置，由 _build_ui 里 per-instance QSS 强制白底 */
        """)

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
            app = getattr(self.parent(), '_app', None)
            if app is None and self.parent() is not None:
                grandparent = self.parent().parent()
                if grandparent is not None:
                    app = getattr(grandparent, '_app', None)
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
        self._cam_combo.setStyleSheet(self.INPUT_WIDGET_QSS)  # v4.26: 实例级 popup 白底
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

        # ── AI 分析 ──
        ai_group = QGroupBox("🤖 AI 分析摘要")
        ai_layout = QFormLayout(ai_group)
        self._ai_backend = QComboBox()
        self._ai_backend.setStyleSheet(self.INPUT_WIDGET_QSS)  # v4.26
        self._ai_backend.addItem("内置分析（模板）", "template")
        self._ai_backend.addItem("OpenAI 兼容 (GPT/DeepSeek/Kimi...)", "openai")
        self._ai_backend.addItem("Claude API", "claude")
        self._ai_backend.addItem("Google Gemini", "gemini")
        self._ai_backend.addItem("Ollama 本地", "ollama")
        self._ai_backend.addItem("本地模型 (Qwen2.5)", "local")
        self._ai_backend.currentIndexChanged.connect(self._on_ai_backend_changed)
        ai_layout.addRow("分析引擎：", self._ai_backend)

        # 存储标签引用以便显示/隐藏
        self._ai_provider = QComboBox()
        self._ai_provider.setStyleSheet(self.INPUT_WIDGET_QSS)  # v4.26
        self._ai_provider.addItem("OpenAI GPT-4o", "openai")
        self._ai_provider.addItem("DeepSeek V4", "deepseek")
        self._ai_provider.addItem("Moonshot Kimi", "moonshot")
        self._ai_provider.addItem("智谱 GLM", "zhipu")
        self._ai_provider.addItem("通义千问 Qwen", "qwen")
        self._ai_provider.addItem("OpenRouter", "openrouter")
        self._ai_provider.addItem("Together AI", "together")
        self._ai_provider.addItem("Groq", "groq")
        self._ai_provider.addItem("自定义", "__custom__")
        self._ai_provider_row = ai_layout.addRow("提供商：", self._ai_provider)

        self._ai_api_key = QLineEdit()
        self._ai_api_key.setPlaceholderText("API Key...")
        self._ai_api_key.setEchoMode(QLineEdit.Password)
        self._ai_api_key.setStyleSheet(self.INPUT_WIDGET_QSS)  # v4.26
        # 密码可见性切换
        self._api_key_toggle_btn = QPushButton("👁")
        self._api_key_toggle_btn.setObjectName("apiKeyToggle")
        self._api_key_toggle_btn.setFixedWidth(36)
        self._api_key_toggle_btn.setToolTip("显示/隐藏 API Key")
        self._api_key_toggle_btn.setCheckable(True)
        # v4.26.4: 完全去掉按钮 border（含 focus 矩形），避免 Windows 主题下渲染为黑边
        # QSS `outline: none` + `border: none` 双保险，确保所有状态下都没有黑边
        # 视觉上 input 的 1px 灰边已经足够作为分隔，按钮完全融入背景
        self._api_key_toggle_btn.setStyleSheet("""
            QPushButton#apiKeyToggle {
                background-color: #FFFFFF;
                color: #5A5650;
                border: none;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
                font-size: 14px;
                padding: 4px 8px;
                margin: 0px;
                outline: none;
            }
            QPushButton#apiKeyToggle:hover {
                background-color: #F0EBF8;
                color: #5B4A8C;
                border: none;
                outline: none;
            }
            QPushButton#apiKeyToggle:pressed {
                background-color: #E0E0E0;
                border: none;
                outline: none;
            }
            QPushButton#apiKeyToggle:checked {
                background-color: #F0EBF8;
                color: #5B4A8C;
                border: none;
                outline: none;
            }
            QPushButton#apiKeyToggle:focus {
                border: none;
                outline: none;
            }
        """)
        self._api_key_toggle_btn.clicked.connect(self._toggle_api_key_visibility)
        api_key_row = QWidget()
        api_key_layout = QHBoxLayout(api_key_row)
        api_key_layout.setContentsMargins(0, 0, 0, 0)
        api_key_layout.setSpacing(0)
        api_key_layout.addWidget(self._ai_api_key)
        api_key_layout.addWidget(self._api_key_toggle_btn)
        ai_layout.addRow("API Key：", api_key_row)

        self._ai_base_url = QLineEdit("https://api.openai.com/v1")
        self._ai_base_url.setPlaceholderText("自定义 API 地址")
        self._ai_base_url.setStyleSheet(self.INPUT_WIDGET_QSS)  # v4.26
        self._ai_url_row = ai_layout.addRow("API 地址：", self._ai_base_url)
        layout.addWidget(ai_group)

        # ── 番茄工作法 ──
        pomo_group = QGroupBox("🍅 番茄工作法")
        pomo_layout = QFormLayout(pomo_group)
        self._pomo_work_spin = QSpinBox()
        self._pomo_work_spin.setStyleSheet(self.INPUT_WIDGET_QSS)  # v4.26
        self._pomo_work_spin.setRange(1, 120)
        self._pomo_work_spin.setSuffix(" 分钟")
        self._pomo_work_spin.setValue(self._pomo_work)
        pomo_layout.addRow("工作时长：", self._pomo_work_spin)

        self._pomo_break_spin = QSpinBox()
        self._pomo_break_spin.setStyleSheet(self.INPUT_WIDGET_QSS)  # v4.26
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

    def _on_ai_backend_changed(self, idx: int) -> None:
        """切换 AI 后端时显示/隐藏相关字段"""
        backend = self._ai_backend.itemData(idx)
        is_openai = (backend == "openai")
        self._ai_provider.setVisible(is_openai)
        self._ai_base_url.setVisible(is_openai)
        if hasattr(self, '_ai_provider_row'):
            for i in range(self._ai_provider_row.count()):
                w = self._ai_provider_row.itemAt(i)
                if w and w.widget():
                    w.widget().setVisible(is_openai)
        if hasattr(self, '_ai_url_row'):
            for i in range(self._ai_url_row.count()):
                w = self._ai_url_row.itemAt(i)
                if w and w.widget():
                    w.widget().setVisible(is_openai)

    def _toggle_api_key_visibility(self) -> None:
        """切换 API Key 可见性"""
        if self._ai_api_key.echoMode() == QLineEdit.Password:
            self._ai_api_key.setEchoMode(QLineEdit.Normal)
            self._api_key_toggle_btn.setText("🙈")
        else:
            self._ai_api_key.setEchoMode(QLineEdit.Password)
            self._api_key_toggle_btn.setText("👁")

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
        set_yaml_value("ai", "backend", value=self._ai_backend.currentData())
        set_yaml_value("ai", "provider", value=self._ai_provider.currentData())
        set_yaml_value("ai", "api_key", value=self._ai_api_key.text())
        set_yaml_value("ai", "base_url", value=self._ai_base_url.text())

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

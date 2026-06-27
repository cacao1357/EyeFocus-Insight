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
    QDoubleSpinBox,
    QInputDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
        self._auto_start = get_yaml_value("ui", "auto_start", default=False)
        self._minimize_on_start = get_yaml_value("ui", "minimize_on_start", default=False)

        self._ai_backend_loaded = get_yaml_value("ai", "backend", default="template")
        self._ai_model_key = get_yaml_value("ai", "model_key", default="qwen2.5:1.5b")

        # v4.x: API Key 不再从这里读取 — 由 keyring / env 提供
        self._api_url = get_yaml_value("ai", "api_url", default="")
        self._api_model = get_yaml_value("ai", "api_model", default="")

        # 尝试从主程序读取番茄当前设置
        self._try_load_pomodoro_settings()

    def _restore_ai_backend(self) -> None:
        """恢复已保存的 AI 后端选择"""
        bk = self._ai_backend_loaded
        mk = self._ai_model_key
        model_map = {"qwen2.5:1.5b": "local_qwen2.5",
                     "qwen3:1.7b": "local_qwen3",
                     "qwen3.5:1.5b": "local_qwen3.5"}
        target = model_map.get(mk, bk) if bk == "local" else bk
        for i in range(self._ai_backend.count()):
            if self._ai_backend.itemData(i) == target:
                self._ai_backend.setCurrentIndex(i)
                break

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

        # v4.42: 语音反馈开关移至托盘菜单，设置面板不再暴露
        # ── AI 分析 ──
        ai_group = QGroupBox("🤖 AI 分析摘要")
        ai_layout = QFormLayout(ai_group)
        self._ai_backend = QComboBox()
        self._ai_backend.setStyleSheet(self.INPUT_WIDGET_QSS)  # v4.26
        self._ai_backend.addItem("内置分析（模板）", "template")
        self._ai_backend.addItem("Ollama 本地", "ollama")
        self._ai_backend.addItem("API (云端)", "openai")
        self._ai_backend.addItem("Qwen2.5-1.5B (当前)", "local_qwen2.5")
        self._ai_backend.addItem("Qwen3-1.7B", "local_qwen3")
        self._ai_backend.addItem("Qwen3.5-1.5B", "local_qwen3.5")
        ai_layout.addRow("分析引擎：", self._ai_backend)
        # 恢复已保存的后端选择
        self._restore_ai_backend()

        # ── API 凭证（仅 API 云端模式使用） ──
        # v4.29: 从托盘独立弹窗移入设置面板，统一管理
        self._api_provider = QComboBox()
        self._api_provider.setStyleSheet(self.INPUT_WIDGET_QSS)
        _providers = [
            ("", "手动输入"),
            ("deepseek", "DeepSeek"),
            ("qwen", "Qwen（阿里通义）"),
            ("openai", "OpenAI"),
            ("moonshot", "Moonshot"),
            ("siliconflow", "SiliconFlow"),
            ("zhipu", "智谱 GLM"),
            ("openrouter", "OpenRouter"),
            ("groq", "Groq"),
        ]
        for key, label in _providers:
            self._api_provider.addItem(label, key)
        self._api_provider.currentIndexChanged.connect(self._on_api_provider_change)
        ai_layout.addRow("提供商：", self._api_provider)

        self._api_url_input = QLineEdit()
        self._api_url_input.setStyleSheet(self.INPUT_WIDGET_QSS)
        self._api_url_input.setPlaceholderText("https://api.deepseek.com/v1")
        self._api_url_input.setText(self._api_url)
        ai_layout.addRow("API 地址：", self._api_url_input)

        # v4.x: API Key 由 OS keyring 托管 — UI 只显示来源 + 操作按钮
        key_row = QHBoxLayout()
        self._key_storage_label = QLabel("（加载中…）")
        self._key_storage_label.setStyleSheet("color: #6B6B6B; font-size: 12px;")
        key_row.addWidget(self._key_storage_label, 1)

        _btn_qss = """
            QPushButton {
                background-color: #F0F0F0; color: #1C1C1E;
                border: 1px solid #D0D0D0; border-radius: 4px;
                padding: 4px 10px; font-size: 12px;
            }
            QPushButton:hover { background-color: #E5E5E5; }
            QPushButton:pressed { background-color: #D8D8D8; }
        """
        self._key_modify_btn = QPushButton("修改 Key")
        self._key_modify_btn.setStyleSheet(_btn_qss)
        self._key_modify_btn.clicked.connect(self._on_modify_api_key)
        key_row.addWidget(self._key_modify_btn)

        self._key_migrate_btn = QPushButton("移到凭据管理器")
        self._key_migrate_btn.setStyleSheet(_btn_qss)
        self._key_migrate_btn.clicked.connect(self._on_migrate_api_key)
        self._key_migrate_btn.setVisible(False)  # 仅在 .env 来源时显示
        key_row.addWidget(self._key_migrate_btn)

        self._key_clear_btn = QPushButton("清除")
        self._key_clear_btn.setStyleSheet(_btn_qss)
        self._key_clear_btn.clicked.connect(self._on_clear_api_key)
        key_row.addWidget(self._key_clear_btn)

        ai_layout.addRow("API Key：", key_row)
        self._refresh_key_storage_label()

        self._api_model_input = QLineEdit()
        self._api_model_input.setStyleSheet(self.INPUT_WIDGET_QSS)
        self._api_model_input.setPlaceholderText("deepseek-chat")
        self._api_model_input.setText(self._api_model)
        ai_layout.addRow("模型名：", self._api_model_input)

        # 测试连接
        test_row = QHBoxLayout()
        self._api_test_btn = QPushButton("测试连接")
        self._api_test_btn.setStyleSheet("""
            QPushButton {
                background-color: #F0F0F0; color: #1C1C1E;
                border: 1px solid #D0D0D0; border-radius: 4px;
                padding: 4px 14px; font-size: 12px;
            }
            QPushButton:hover { background-color: #E5E5E5; }
            QPushButton:disabled { background-color: #F8F6F2; color: #8B8680; }
        """)
        self._api_test_btn.clicked.connect(self._test_api_connection)
        test_row.addWidget(self._api_test_btn)
        self._api_test_result = QLabel("")
        test_row.addWidget(self._api_test_result, 1)
        ai_layout.addRow("", test_row)

        # 根据已保存的 URL 匹配提供商
        if self._api_url:
            self._match_api_provider(self._api_url)

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

        # v4.42: TTS 语速不再暴露于设置面板
        # v4.42: Web 仪表盘端口不再暴露于设置面板（默认 8080）
        # ── 启动行为 ──
        startup_group = QGroupBox("🚀 启动行为")
        startup_layout = QVBoxLayout(startup_group)
        self._auto_start_check = QCheckBox("启动时自动开始监测")
        self._auto_start_check.setChecked(self._auto_start)
        startup_layout.addWidget(self._auto_start_check)
        self._minimize_check = QCheckBox("启动时最小化到托盘")
        self._minimize_check.setChecked(self._minimize_on_start)
        startup_layout.addWidget(self._minimize_check)
        layout.addWidget(startup_group)

        # v4.42: 游戏化和数据路径不再暴露于设置面板
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
        pomo_work = self._pomo_work_spin.value()
        pomo_break = self._pomo_break_spin.value()
        auto_start = self._auto_start_check.isChecked()
        minimize = self._minimize_check.isChecked()

        # 写入运行时配置
        set_yaml_value("camera", "index", value=camera_idx)
        raw_backend = self._ai_backend.currentData()
        # 映射 local_* 到 local + model_key
        LOCAL_MODEL_MAP = {
            "local_qwen2.5": ("local", "qwen2.5:1.5b"),
            "local_qwen3": ("local", "qwen3:1.7b"),
            "local_qwen3.5": ("local", "qwen3.5:1.5b"),
        }
        if raw_backend in LOCAL_MODEL_MAP:
            set_yaml_value("ai", "backend", value="local")
            set_yaml_value("ai", "model_key", value=LOCAL_MODEL_MAP[raw_backend][1])
        else:
            set_yaml_value("ai", "backend", value=raw_backend)
        # v4.x: API Key 不再写入 YAML — 由 keyring / env 托管
        set_yaml_value("ai", "api_url", value=self._api_url_input.text().strip())
        set_yaml_value("ai", "api_model", value=self._api_model_input.text().strip())
        set_yaml_value("ui", "auto_start", value=auto_start)
        set_yaml_value("ui", "minimize_on_start", value=minimize)

        # 番茄时间不持久化到 config.yaml（但应用到运行中引擎）
        self._apply_pomodoro_settings(pomo_work, pomo_break)

        # 持久化
        ok = save_yaml_config()
        if ok:
            logger.info("设置已保存: camera=%d, pomo=%d/%d",
                        camera_idx, pomo_work, pomo_break)
        from PyQt5.QtWidgets import QMessageBox
        if ok:
            QMessageBox.information(self, "设置", "✅ 设置已保存并生效。\n部分设置（摄像头/端口）需重启程序。")
        else:
            QMessageBox.warning(self, "设置", "❌ 保存失败 (config.yaml 不可写)。\n请以管理员身份运行或检查文件权限。")

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

    # ── v4.x: API Key 凭据管理 (keyring) ──

    def _refresh_key_storage_label(self) -> None:
        """根据 keyring / env / none 刷新标签与按钮可见性"""
        try:
            from analyzer.secrets import storage_location, keyring_available
            loc = storage_location()
        except Exception:
            loc = "none"
            keyring_available = lambda: False  # noqa: E731
        if loc == "keyring":
            self._key_storage_label.setText("🔐 已存储于 Windows 凭据管理器")
            self._key_migrate_btn.setVisible(False)
        elif loc == "env":
            self._key_storage_label.setText("📄 来源: .env 环境变量（明文，建议改用凭据管理器）")
            self._key_migrate_btn.setVisible(keyring_available())
        else:
            self._key_storage_label.setText("（未设置 API Key）")
            self._key_migrate_btn.setVisible(False)

    def _on_modify_api_key(self) -> None:
        """弹出密码对话框，设置或替换 keyring 中的 API Key"""
        from PyQt5.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QDialogButtonBox
        from analyzer.secrets import get_api_key, set_api_key, is_loopback_url

        dlg = QDialog(self)
        dlg.setWindowTitle("设置 API Key")
        layout = QFormLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # 顶部提示
        url = self._api_url_input.text().strip()
        hint = "Key 将存储到 Windows 凭据管理器（推荐）"
        try:
            if url and is_loopback_url(url):
                hint = f"检测到 loopback 地址（{url}），调用时 Key 不会通过 HTTP header 发送。"
        except Exception:
            pass
        layout.addRow(QLabel(hint))

        # Key 输入（默认隐藏，可切换显示）
        current = get_api_key() or ""
        key_edit = QLineEdit()
        key_edit.setEchoMode(QLineEdit.Password)
        key_edit.setPlaceholderText("sk-...")
        key_edit.setText(current)

        show_btn = QPushButton("显示")
        show_btn.setFixedWidth(60)
        show_btn.setCheckable(True)
        show_btn.toggled.connect(
            lambda checked: key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        )
        show_btn.toggled.connect(
            lambda checked: show_btn.setText("隐藏" if checked else "显示")
        )
        row = QHBoxLayout()
        row.addWidget(key_edit)
        row.addWidget(show_btn)
        layout.addRow("API Key：", row)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addRow(btns)

        if dlg.exec_() == QDialog.Accepted:
            new_key = key_edit.text().strip()
            if not new_key:
                return
            if set_api_key(new_key):
                # 清掉 env，避免 split-brain
                os.environ.pop("MINIMAX_API_KEY", None)
                self._refresh_key_storage_label()
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.information(self, "API Key", "✅ Key 已存到凭据管理器。\n重启后下次启动会从这里读取。")
            else:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, "API Key", "❌ 保存到凭据管理器失败。\n请检查系统凭据存储是否可用。")

    def _on_migrate_api_key(self) -> None:
        """一键把 .env 里的 key 搬到 keyring"""
        try:
            from analyzer.secrets import get_api_key, set_api_key
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "迁移", f"keyring 模块不可用: {e}")
            return
        current = get_api_key() or ""
        if not current:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "迁移", ".env 中没有可迁移的 Key。")
            return
        if set_api_key(current):
            os.environ.pop("MINIMAX_API_KEY", None)
            self._refresh_key_storage_label()
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "迁移",
                "✅ Key 已迁移到 Windows 凭据管理器。\n\n"
                "建议下一步：从 .env 中删除 MINIMAX_API_KEY 行以彻底脱离明文存储。\n"
                "（本程序不会自动修改 .env，由你决定何时删除）",
            )
        else:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "迁移", "❌ 写入凭据管理器失败。")

    def _on_clear_api_key(self) -> None:
        """清除 keyring + env 中的 API Key"""
        from PyQt5.QtWidgets import QMessageBox
        ret = QMessageBox.question(
            self, "清除 API Key",
            "确认清除所有 API Key 存储（keyring + 环境变量）？\n清除后需要重新设置才能继续调用云端模型。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        try:
            from analyzer.secrets import delete_api_key
            delete_api_key()
        except Exception:
            pass
        os.environ.pop("MINIMAX_API_KEY", None)
        self._refresh_key_storage_label()
        QMessageBox.information(self, "清除", "✅ 已清除 API Key。")

    # ── v4.29: API 提供商辅助方法 ──

    def _on_api_provider_change(self, idx: int) -> None:
        """选择提供商时自动填入 URL 和模型名"""
        _api_providers = {
            "deepseek":   {"base_url": "https://api.deepseek.com/v1",          "model": "deepseek-chat"},
            "qwen":       {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
            "openai":     {"base_url": "https://api.openai.com/v1",            "model": "gpt-4o-mini"},
            "moonshot":   {"base_url": "https://api.moonshot.cn/v1",           "model": "moonshot-v1-8k"},
            "siliconflow":{"base_url": "https://api.siliconflow.cn/v1",        "model": "Qwen/Qwen2.5-7B-Instruct"},
            "zhipu":      {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash"},
            "openrouter": {"base_url": "https://openrouter.ai/api/v1",         "model": "openai/gpt-4o-mini"},
            "groq":       {"base_url": "https://api.groq.com/openai/v1",       "model": "llama-3.3-70b-versatile"},
        }
        key = self._api_provider.itemData(idx)
        if not key:
            return  # 手动输入 — 不清空已填内容
        cfg = _api_providers.get(key)
        if cfg:
            if cfg.get("base_url"):
                self._api_url_input.setText(cfg["base_url"])
            if cfg.get("model"):
                self._api_model_input.setText(cfg["model"])

    def _match_api_provider(self, url: str) -> None:
        """根据 URL 匹配已保存的提供商"""
        _api_providers = {
            "deepseek":   {"base_url": "https://api.deepseek.com/v1"},
            "qwen":       {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
            "openai":     {"base_url": "https://api.openai.com/v1"},
            "moonshot":   {"base_url": "https://api.moonshot.cn/v1"},
            "siliconflow":{"base_url": "https://api.siliconflow.cn/v1"},
            "zhipu":      {"base_url": "https://open.bigmodel.cn/api/paas/v4"},
            "openrouter": {"base_url": "https://openrouter.ai/api/v1"},
            "groq":       {"base_url": "https://api.groq.com/openai/v1"},
        }
        for pk, cfg in _api_providers.items():
            if cfg["base_url"] == url:
                for i in range(self._api_provider.count()):
                    if self._api_provider.itemData(i) == pk:
                        self._api_provider.setCurrentIndex(i)
                        return

    def _test_api_connection(self) -> None:
        """测试 API 连接（异步）"""
        # v4.x: Key 来自 keyring / env，不再有 _api_key_input
        try:
            from analyzer.secrets import get_api_key
            api_key = get_api_key() or ""
        except Exception:
            api_key = ""
        base_url = self._api_url_input.text().strip()
        model = self._api_model_input.text().strip()

        if not api_key:
            self._api_test_result.setText("⚠️ 未设置 API Key（点'修改 Key'配置）")
            self._api_test_result.setStyleSheet("color: #B55C5C;")
            return
        if not base_url:
            self._api_test_result.setText("⚠️ 请先输入 API 地址")
            self._api_test_result.setStyleSheet("color: #B55C5C;")
            return

        self._api_test_btn.setEnabled(False)
        self._api_test_btn.setText("测试中...")
        self._api_test_result.setText("⏳ 连接中...")
        self._api_test_result.setStyleSheet("color: #9E9A96;")

        def _do_test():
            from analyzer.llm_client import OpenAICompatibleClient
            client = OpenAICompatibleClient(
                api_key=api_key, base_url=base_url, model=model or "gpt-4o-mini"
            )
            err = client.test_connection()
            from PyQt5.QtCore import QMetaObject, Qt as _Qt, Q_ARG
            if err:
                QMetaObject.invokeMethod(
                    self._api_test_result, "setText", _Qt.QueuedConnection,
                    Q_ARG(str, f"❌ {err}"))
                QMetaObject.invokeMethod(
                    self._api_test_result, "setStyleSheet", _Qt.QueuedConnection,
                    Q_ARG(str, "color: #B55C5C;"))
            else:
                QMetaObject.invokeMethod(
                    self._api_test_result, "setText", _Qt.QueuedConnection,
                    Q_ARG(str, "✅ 连接成功"))
                QMetaObject.invokeMethod(
                    self._api_test_result, "setStyleSheet", _Qt.QueuedConnection,
                    Q_ARG(str, "color: #5A8A6D;"))
            QMetaObject.invokeMethod(
                self._api_test_btn, "setEnabled", _Qt.QueuedConnection,
                Q_ARG(bool, True))
            QMetaObject.invokeMethod(
                self._api_test_btn, "setText", _Qt.QueuedConnection,
                Q_ARG(str, "测试连接"))

        import threading
        threading.Thread(target=_do_test, daemon=True).start()

"""
gui/api_dialog.py — API 设置对话框 (v4.27)

托盘「API 设置」入口，配置 OpenAI 兼容 API 的 URL / Key / 模型。
支持预定义提供商（DeepSeek / Qwen / OpenAI / 等）一键填入。
"""

import logging
import threading

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QMessageBox,
)

logger = logging.getLogger("eyefocus.gui.api")

# 与 llm_client.OPENAI_COMPATIBLE_PROVIDERS 保持一致
API_PROVIDERS = {
    "":            {"base_url": "",                    "model": ""},
    "deepseek":   {"base_url": "https://api.deepseek.com/v1",          "model": "deepseek-chat"},
    "qwen":       {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "openai":     {"base_url": "https://api.openai.com/v1",            "model": "gpt-4o-mini"},
    "moonshot":   {"base_url": "https://api.moonshot.cn/v1",           "model": "moonshot-v1-8k"},
    "siliconflow":{"base_url": "https://api.siliconflow.cn/v1",        "model": "Qwen/Qwen2.5-7B-Instruct"},
    "zhipu":      {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",         "model": "openai/gpt-4o-mini"},
    "groq":       {"base_url": "https://api.groq.com/openai/v1",       "model": "llama-3.3-70b-versatile"},
}


class ApiSetupDialog(QDialog):
    """API 设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API 设置")
        self.setMinimumWidth(500)
        self.setStyleSheet("""
            QDialog { background-color: #FFFFFF; }
            QLabel { color: #1C1C1E; background: transparent; }
            QLineEdit {
                background-color: #FFFFFF; color: #1C1C1E;
                border: 1px solid #D0D0D0; border-radius: 4px;
                padding: 6px 10px;
                selection-background-color: #5B4A8C; selection-color: #FFFFFF;
            }
            QComboBox {
                background-color: #FFFFFF; color: #1C1C1E;
                border: 1px solid #D0D0D0; border-radius: 4px;
                padding: 4px 8px; min-height: 28px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #FFFFFF; color: #1C1C1E;
                selection-background-color: #5B4A8C; selection-color: #FFFFFF;
            }
            QPushButton {
                background-color: #F0F0F0; color: #1C1C1E;
                border: 1px solid #D0D0D0; border-radius: 6px;
                padding: 6px 18px;
            }
            QPushButton:hover { background-color: #E5E5E5; }
            QPushButton:pressed { background-color: #D8D8D8; }
            QPushButton:disabled { background-color: #F8F6F2; color: #8B8680; }
        """)
        self._build_ui()
        self._load_config()
        self._on_provider_change(self._provider_combo.currentIndex())

    # ── UI 构建 ──

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        # 提供商
        self._provider_combo = QComboBox()
        provider_names = {
            "": "手动输入",
            "deepseek": "DeepSeek（深度求索）",
            "qwen": "Qwen（阿里通义）",
            "openai": "OpenAI",
            "moonshot": "Moonshot（月之暗面）",
            "siliconflow": "SiliconFlow（硅基流动）",
            "zhipu": "智谱 GLM",
            "openrouter": "OpenRouter",
            "groq": "Groq",
        }
        for key, label in provider_names.items():
            self._provider_combo.addItem(label, key)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_change)
        form.addRow("提供商", self._provider_combo)

        # API URL
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("https://api.deepseek.com/v1")
        form.addRow("API 地址", self._url_input)

        # API Key
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.Password)
        self._key_input.setPlaceholderText("sk-...")
        # 切换显示按钮
        key_row = QHBoxLayout()
        key_row.addWidget(self._key_input)
        self._toggle_key_btn = QPushButton("显示")
        self._toggle_key_btn.setFixedWidth(50)
        self._toggle_key_btn.clicked.connect(self._toggle_key_visible)
        key_row.addWidget(self._toggle_key_btn)
        form.addRow("API Key", key_row)

        # 模型名
        self._model_input = QLineEdit()
        self._model_input.setPlaceholderText("deepseek-chat")
        form.addRow("模型名", self._model_input)

        layout.addLayout(form)

        # 测试连接
        test_row = QHBoxLayout()
        self._test_btn = QPushButton("🔄 测试连接")
        self._test_btn.clicked.connect(self._test_connection)
        test_row.addWidget(self._test_btn)
        self._test_result = QLabel("")
        self._test_result.setWordWrap(True)
        test_row.addWidget(self._test_result, 1)
        layout.addLayout(test_row)

        # 按钮
        self._btn_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        self._btn_box.accepted.connect(self._save)
        self._btn_box.rejected.connect(self.reject)
        layout.addWidget(self._btn_box)

    # ── 事件 ──

    def _on_provider_change(self, idx: int) -> None:
        provider_key = self._provider_combo.itemData(idx)
        cfg = API_PROVIDERS.get(provider_key, {})
        if cfg.get("base_url"):
            self._url_input.setText(cfg["base_url"])
        if cfg.get("model"):
            self._model_input.setText(cfg["model"])

    def _toggle_key_visible(self) -> None:
        if self._key_input.echoMode() == QLineEdit.Password:
            self._key_input.setEchoMode(QLineEdit.Normal)
            self._toggle_key_btn.setText("隐藏")
        else:
            self._key_input.setEchoMode(QLineEdit.Password)
            self._toggle_key_btn.setText("显示")

    def _test_connection(self) -> None:
        api_key = self._key_input.text().strip()
        base_url = self._url_input.text().strip()
        model = self._model_input.text().strip()

        if not api_key:
            self._test_result.setText("⚠️ 请先输入 API Key")
            self._test_result.setStyleSheet("color: #B55C5C;")
            return
        if not base_url:
            self._test_result.setText("⚠️ 请先输入 API 地址")
            self._test_result.setStyleSheet("color: #B55C5C;")
            return

        self._test_btn.setEnabled(False)
        self._test_btn.setText("测试中...")
        self._test_result.setText("⏳ 连接中...")
        self._test_result.setStyleSheet("color: #9E9A96;")

        def _do_test():
            from analyzer.llm_client import OpenAICompatibleClient
            client = OpenAICompatibleClient(
                api_key=api_key, base_url=base_url, model=model or "gpt-4o-mini"
            )
            err = client.test_connection()
            # 回到主线程更新 UI
            from PyQt5.QtCore import QMetaObject, Qt as _Qt, Q_ARG
            if err:
                QMetaObject.invokeMethod(
                    self._test_result, "setText", _Qt.QueuedConnection,
                    Q_ARG(str, f"❌ {err}"))
                QMetaObject.invokeMethod(
                    self._test_result, "setStyleSheet", _Qt.QueuedConnection,
                    Q_ARG(str, "color: #B55C5C;"))
            else:
                QMetaObject.invokeMethod(
                    self._test_result, "setText", _Qt.QueuedConnection,
                    Q_ARG(str, "✅ 连接成功"))
                QMetaObject.invokeMethod(
                    self._test_result, "setStyleSheet", _Qt.QueuedConnection,
                    Q_ARG(str, "color: #5A8A6D;"))
            QMetaObject.invokeMethod(
                self._test_btn, "setEnabled", _Qt.QueuedConnection,
                Q_ARG(bool, True))
            QMetaObject.invokeMethod(
                self._test_btn, "setText", _Qt.QueuedConnection,
                Q_ARG(str, "🔄 测试连接"))

        threading.Thread(target=_do_test, daemon=True).start()

    def _load_config(self) -> None:
        try:
            from config import get_yaml_value
            api_key = get_yaml_value("ai", "api_key", default="")
            api_url = get_yaml_value("ai", "api_url", default="")
            api_model = get_yaml_value("ai", "api_model", default="")

            if api_url:
                self._url_input.setText(api_url)
            if api_model:
                self._model_input.setText(api_model)
            if api_key:
                self._key_input.setText(api_key)

            # 尝试匹配提供商
            for i in range(self._provider_combo.count()):
                pk = self._provider_combo.itemData(i)
                cfg = API_PROVIDERS.get(pk)
                if cfg and cfg.get("base_url") and cfg["base_url"] == api_url:
                    self._provider_combo.setCurrentIndex(i)
                    break
        except Exception as e:
            logger.debug("加载 API 配置失败: %s", e)

    def _save(self) -> None:
        api_key = self._key_input.text().strip()
        api_url = self._url_input.text().strip()
        api_model = self._model_input.text().strip()

        if not api_url or not api_key:
            QMessageBox.warning(self, "配置不完整", "API 地址和 Key 为必填项。")
            return

        try:
            from config import set_yaml_value, save_yaml_config
            set_yaml_value("ai", "api_key", value=api_key)
            set_yaml_value("ai", "api_url", value=api_url)
            set_yaml_value("ai", "api_model", value=api_model)
            save_yaml_config()
            QMessageBox.information(self, "已保存", "API 设置已保存。\n\n如需切换后端，请到「设置 → AI 后端」选择「API (云端)」。")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存配置时出错:\n{e}")

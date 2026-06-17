"""
analyzer/llm_client.py — LLM 客户端抽象 (v4.24)

支持三种后端：
1. TemplateClient — 规则模板生成（零依赖，始终可用）
2. ClaudeClient — Claude API（需 api key）
3. OllamaClient — 本地 Ollama 服务

所有客户端返回相同格式的中文分析文本。
"""

import logging
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger("eyefocus.analyzer")

# ── 标准分析提示模板 ──

ANALYSIS_SYSTEM_PROMPT = """你是一个专注力分析教练。根据用户提供的专注度数据，给出分析。
要求：
1. 先说整体表现（好/一般/差，与用户基线对比）
2. 指出 1-2 个具体发现（如"第 35 分钟后专注度明显下降"）
3. 给出 1 条可执行的建议
4. 语言简洁，3-4 句
5. 用中文，口语化，像朋友聊天"""

ANALYSIS_USER_TEMPLATE = """会话时长：{duration} 分钟
平均专注度：{avg_focus} 分（用户基线：{baseline} 分）
专注趋势：前段 {seg_start} 分 → 中段 {seg_mid} 分 → 后段 {seg_end} 分
分心事件：{distractions} 次（头部偏移 {head_pct}%，视线偏移 {gaze_pct}%）
疲劳等级：{fatigue}
番茄钟完成：{pomo_count} 个
今日已连续专注：{streak} 天"""


# ── 抽象基类 ──

class LLMClient(ABC):
    """LLM 客户端抽象接口"""

    @property
    @abstractmethod
    def name(self) -> str:
        """客户端名称"""

    @property
    @abstractmethod
    def available(self) -> bool:
        """是否可用"""

    @abstractmethod
    def analyze(self, data: Dict[str, Any]) -> str:
        """分析专注度数据，返回中文分析文本"""


# ── 模板版（零依赖） ──

class TemplateClient(LLMClient):
    """规则模板生成 — 无需任何外部依赖"""

    @property
    def name(self) -> str:
        return "内置分析（模板）"

    @property
    def available(self) -> bool:
        return True

    def analyze(self, data: Dict[str, Any]) -> str:
        parts = []

        # 整体表现
        avg = data.get("avg_focus", 0)
        baseline = data.get("baseline", 60)
        if avg >= 80:
            parts.append(f"今天专注度 {avg:.0f} 分，表现很好！")
        elif avg >= 65:
            parts.append(f"今天专注度 {avg:.0f} 分，整体不错。")
        elif avg >= 50:
            parts.append(f"今天专注度 {avg:.0f} 分，还有提升空间。")
        else:
            parts.append(f"今天专注度 {avg:.0f} 分，状态不太理想。")

        # 与基线对比
        diff = avg - baseline
        if abs(diff) > 5:
            parts.append("高于日常基线" if diff > 0 else "低于日常基线")

        # 趋势分段
        segs = data.get("segments", {})
        s, m, e = segs.get("start", avg), segs.get("mid", avg), segs.get("end", avg)
        if s - e > 10:
            parts.append(f"前 {segs.get('start_label', '期')} 专注度较高"
                         f"，但后 {segs.get('end_label', '期')} 下降了 {s-e:.0f} 分，"
                         "建议中间安排一次休息。")
        elif e - s > 10:
            parts.append("后半程专注度上升，状态渐入佳境。")

        # 分心分析
        dist = data.get("distractions", 0)
        if dist > 5:
            parts.append(f"分心 {dist} 次偏多，头部偏移是主要原因，"
                         "建议调整工位或使用番茄钟。")
        elif dist > 0:
            parts.append(f"分心 {dist} 次，在正常范围内。")

        # 疲劳
        fatigue = data.get("fatigue", "")
        if fatigue == "HIGH":
            parts.append("疲劳程度较高，建议今晚早点休息。")
        elif fatigue == "MEDIUM":
            parts.append("有轻微疲劳信号，注意眨眼和起身活动。")

        # 番茄
        pc = data.get("pomodoro_count", 0)
        if pc >= 4:
            parts.append(f"完成了 {pc} 个番茄钟，节奏很好！")

        # 建议
        if avg < 60:
            parts.append("建议明天缩短单次工作时长，多设几个番茄钟试试。")

        return "。" if not parts else "".join(parts) + "。"


# ── Claude API 版 ──

class ClaudeClient(LLMClient):
    """Claude API — 需 ANTHROPIC_API_KEY 环境变量或传入"""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or ""

    @property
    def name(self) -> str:
        return "Claude AI"

    @property
    def available(self) -> bool:
        key = self._api_key or ""
        return bool(key) or bool(__import__("os").environ.get("ANTHROPIC_API_KEY", ""))

    def _get_key(self) -> str:
        return self._api_key or __import__("os").environ.get("ANTHROPIC_API_KEY", "")

    def analyze(self, data: Dict[str, Any]) -> str:
        from anthropic import Anthropic

        client = Anthropic(api_key=self._get_key())
        user_msg = ANALYSIS_USER_TEMPLATE.format(**data)

        resp = client.messages.create(
            model="claude-sonnet-4-6-20251001",
            max_tokens=300,
            system=ANALYSIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        return resp.content[0].text


# ── OpenAI 兼容版（覆盖 OpenAI / DeepSeek / Moonshot / 智谱GLM / Qwen / OpenRouter 等）──

# 预定义提供商配置
OPENAI_COMPATIBLE_PROVIDERS = {
    "openai":     {"base_url": "https://api.openai.com/v1",          "model": "gpt-4o"},
    "deepseek":   {"base_url": "https://api.deepseek.com/v1",        "model": "deepseek-chat"},
    "moonshot":   {"base_url": "https://api.moonshot.cn/v1",         "model": "moonshot-v1-8k"},
    "zhipu":      {"base_url": "https://open.bigmodel.cn/api/paas/v4","model": "glm-4-plus"},
    "qwen":       {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",       "model": "openai/gpt-4o"},
    "together":   {"base_url": "https://api.together.xyz/v1",        "model": "mistralai/Mixtral-8x22B-Instruct"},
    "groq":       {"base_url": "https://api.groq.com/openai/v1",     "model": "llama-3.3-70b-versatile"},
}


class OpenAICompatibleClient(LLMClient):
    """OpenAI 兼容 API（覆盖大多数主流云端 LLM）

    支持：OpenAI / DeepSeek / Moonshot / 智谱GLM / Qwen / OpenRouter 等
    只需换 base_url + api_key + model_name。
    """

    def __init__(self, api_key: str = "",
                 base_url: str = "https://api.openai.com/v1",
                 model: str = "gpt-4o"):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model

    @property
    def name(self) -> str:
        # 尝试匹配已知提供商
        for provider, cfg in OPENAI_COMPATIBLE_PROVIDERS.items():
            if cfg["base_url"].rstrip("/") == self._base_url:
                return f"{provider} ({self._model})"
        return f"OpenAI 兼容 ({self._base_url})"

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def analyze(self, data: Dict[str, Any]) -> str:
        import urllib.request
        import json as _json

        user_msg = ANALYSIS_USER_TEMPLATE.format(**data)
        payload = _json.dumps({
            "model": self._model,
            "messages": [
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 300,
            "temperature": 0.7,
        }).encode()

        req = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read())
            return result["choices"][0]["message"]["content"]


# ── Google Gemini 版 ──

class GeminiClient(LLMClient):
    """Google Gemini API — 需 GOOGLE_API_KEY"""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or ""

    @property
    def name(self) -> str:
        return "Google Gemini"

    @property
    def available(self) -> bool:
        key = self._api_key or __import__("os").environ.get("GOOGLE_API_KEY", "")
        return bool(key)

    def _get_key(self) -> str:
        return self._api_key or __import__("os").environ.get("GOOGLE_API_KEY", "")

    def analyze(self, data: Dict[str, Any]) -> str:
        try:
            import google.generativeai as genai
        except ImportError:
            logger.warning("google-generativeai 未安装，请 pip install google-generativeai")
            return "（Gemini SDK 未安装，请安装 google-generativeai 包）"

        genai.configure(api_key=self._get_key())
        user_msg = ANALYSIS_USER_TEMPLATE.format(**data)
        full_prompt = f"{ANALYSIS_SYSTEM_PROMPT}\n\n{user_msg}"

        model = genai.GenerativeModel("gemini-2.0-flash")
        resp = model.generate_content(full_prompt)
        return resp.text


# ── Ollama 本地版 ──

class OllamaClient(LLMClient):
    """本地 Ollama 服务（默认 http://127.0.0.1:11434）"""

    def __init__(self, base_url: str = "http://127.0.0.1:11434",
                 model: str = "qwen2.5:1.5b"):
        self._base_url = base_url.rstrip("/")
        self._model = model

    @property
    def name(self) -> str:
        return f"Ollama ({self._model})"

    @property
    def available(self) -> bool:
        try:
            import urllib.request
            req = urllib.request.Request(f"{self._base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def analyze(self, data: Dict[str, Any]) -> str:
        import urllib.request
        import json as _json

        user_msg = ANALYSIS_USER_TEMPLATE.format(**data)
        payload = _json.dumps({
            "model": self._model,
            "system": ANALYSIS_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_msg}],
            "stream": False,
            "options": {"temperature": 0.7, "max_tokens": 300},
        }).encode()

        req = urllib.request.Request(
            f"{self._base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read())
            return result.get("message", {}).get("content", "(空响应)")


# ── llama-cpp-python 本地版 ──


class LocalClient(LLMClient):
    """llama-cpp-python 本地推理（模型需提前通过 scripts/download_model.py 下载）"""

    def __init__(self, model_path: Optional[str] = None):
        self._model_path = model_path or self._default_path()
        self._llm = None

    @staticmethod
    def _default_path() -> str:
        import os
        return os.path.join(os.path.dirname(__file__), "..", "models",
                            "qwen2.5-1.5b-instruct-q4_k_m.gguf")

    @property
    def name(self) -> str:
        return "本地模型 (Qwen2.5-1.5B)"

    @property
    def available(self) -> bool:
        import os
        if not os.path.exists(self._model_path):
            return False
        try:
            from llama_cpp import Llama  # noqa
            return True
        except ImportError:
            return False

    def _load_model(self) -> bool:
        """加载 Llama 模型（CPU 模式 — 当前为 CPU-only 构建）

        模型文件需提前下载，请运行:
            python scripts/download_model.py
        """
        import os
        if not os.path.exists(self._model_path):
            logger.error("模型文件不存在: %s", self._model_path)
            logger.info("请先运行 python scripts/download_model.py 下载模型文件")
            return False
        from llama_cpp import Llama

        try:
            self._llm = Llama(
                model_path=self._model_path,
                n_ctx=2048,
                n_threads=16,
                n_gpu_layers=0,
                verbose=False,
            )
            logger.info("本地模型已加载（CPU 模式）")
            return True
        except Exception as e:
            logger.error("模型加载失败: %s", e)
            return False

    def analyze(self, data: Dict[str, Any]) -> str:
        if self._llm is None:
            if not self._load_model():
                return "（本地模型加载失败，请检查模型文件或切换到其他后端）"

        user_msg = ANALYSIS_USER_TEMPLATE.format(**data)

        # Qwen2.5-Instruct 使用 ChatML 格式
        prompt = (
            f"<|im_start|>system\n{ANALYSIS_SYSTEM_PROMPT}<|im_end|>\n"
            f"<|im_start|>user\n{user_msg}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

        resp = self._llm(
            prompt,
            max_tokens=300,
            temperature=0.7,
            stop=["<|im_end|>", "<|im_start|>"],
        )
        return resp["choices"][0]["text"].strip()


# ── 客户端工厂 ──

def create_llm_client(client_type: str = "template", **kwargs) -> LLMClient:
    """创建 LLM 客户端

    Args:
        client_type: "template" | "openai" | "claude" | "gemini" | "ollama" | "local"
        **kwargs: 传递给具体客户端的参数

    Returns:
        LLMClient 实例
    """
    if client_type == "template":
        return TemplateClient()
    elif client_type == "openai":
        provider = kwargs.get("provider", "openai")
        cfg = OPENAI_COMPATIBLE_PROVIDERS.get(provider, {})
        return OpenAICompatibleClient(
            api_key=kwargs.get("api_key", ""),
            base_url=kwargs.get("base_url", cfg.get("base_url", "https://api.openai.com/v1")),
            model=kwargs.get("model", cfg.get("model", "gpt-4o")),
        )
    elif client_type == "claude":
        return ClaudeClient(api_key=kwargs.get("api_key", ""))
    elif client_type == "gemini":
        return GeminiClient(api_key=kwargs.get("api_key", ""))
    elif client_type == "ollama":
        return OllamaClient(
            base_url=kwargs.get("base_url", "http://127.0.0.1:11434"),
            model=kwargs.get("model", "qwen2.5:1.5b"),
        )
    elif client_type == "local":
        return LocalClient(model_path=kwargs.get("model_path", ""))
    else:
        logger.warning("未知客户端类型 %s，使用模板版", client_type)
        return TemplateClient()

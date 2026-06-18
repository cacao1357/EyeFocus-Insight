"""
analyzer/llm_client.py — LLM 客户端抽象 (v4.27)

仅保留本地 AI：
1. TemplateClient — 规则模板生成（零依赖，始终可用）
2. OllamaClient — 本地 Ollama 服务
3. LocalClient — llama-cpp-python 本地推理

云端 API（Claude/OpenAI/Gemini）已移除。
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
        client_type: "template" | "ollama" | "local"
        **kwargs: 传递给具体客户端的参数

    Returns:
        LLMClient 实例
    """
    if client_type == "template":
        return TemplateClient()
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

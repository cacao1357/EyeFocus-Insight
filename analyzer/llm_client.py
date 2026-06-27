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
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger("eyefocus.analyzer")


def _endpoint_hint(body: str) -> str:
    """检测 LM Studio / Ollama 等"端点路径不对"的典型错误，返回 /v1 提示。

    LM Studio 收到错误路径会返回 {"error":"Unexpected endpoint or method. ..."}
    Ollama 返回 {"error":"404 page not found"}。这些是 base_url 缺 /v1 前缀的症状。
    注意：用具体短语而非裸 "not found"，避免误触发 "Model not found" 等常见 API 错误。
    """
    if not body:
        return ""
    body_lower = body.lower()
    if "unexpected endpoint" in body_lower or "404 page not found" in body_lower:
        return "\n\n💡 提示：LM Studio / Ollama / vLLM 等 OpenAI 兼容服务的 base_url 通常需要 /v1 前缀，例如 http://127.0.0.1:1234/v1"
    return ""

# ── 标准分析提示模板 ──

ANALYSIS_SYSTEM_PROMPT = """你是一个专注力分析教练，用朋友聊天的方式说话。

分析要求：
1. 先说整体表现（好/一般/差），跟用户历史基线对比
2. 指出 1-2 个具体发现，每个发现必须引用数字
3. 分析原因而非只描述现象（比如：专注度下降可能是因为疲劳累积）
4. 给 1 条可执行的建议
5. 语言简洁自然，像朋友聊天
6. 不知道就说不知道，不编造"""

ANALYSIS_USER_TEMPLATE = """会话时长：{duration} 分钟
平均专注度：{avg_focus} 分（用户基线：{baseline} 分，历史平均：{hist_avg_focus} 分）
专注趋势：前段 {seg_start} 分 → 中段 {seg_mid} 分 → 后段 {seg_end} 分
疲劳分布：高 {fatigue_high_pct}% / 中 {fatigue_mid_pct}% / 低 {fatigue_low_pct}%
分心事件：{distractions} 次（头部偏移 {head_pct}%，视线偏移 {gaze_pct}%）
分心高峰时段：{dist_peak_hour}
番茄钟完成：{pomo_count} 个
连续专注天数：{streak} 天"""


# ── L3 级深度分析提示模板（v4.27） ──

DEEP_ANALYSIS_SYSTEM_PROMPT = """你是一个专注力分析教练，像朋友一样聊天。任务是深度模式分析（L3级）：基于时序数据识别重复模式、因果链条，给可执行策略。

分析结构（每部分都要）：
1. 一句话总结 + 整体评分
2. 发现 1-2 个具体模式（如"每次第30分钟出现专注悬崖"、"疲劳上升总在分心前5分钟出现"）
   - 每个发现必须引用 2+ 个数字
   - 指出是单次异常还是重复模式
3. 与历史对比，指出改善/退步
4. 给 1 个可执行建议（含具体时间点）
5. 鼓励一句

铁律：
- 每个结论附具体数字，不写模糊结论
- 不确定就说"数据不足"
- 用中文，口语化，像朋友聊天
- 不说"根据数据"这种废话，直接说数字"""

DEEP_ANALYSIS_USER_TEMPLATE = """## 当前会话
- 日期：{session_date}
- 时长：{duration} 分钟
- 平均专注度：{avg_focus}/100 分（历史平均：{hist_avg_focus}）
- 专注趋势：前段 {seg_start} → 中段 {seg_mid} → 后段 {seg_end}
- 疲劳占比：高 {fatigue_high_pct}% / 中 {fatigue_mid_pct}% / 低 {fatigue_low_pct}%
- 分心事件：{distractions} 次

## 专注悬崖（>15 分降幅）
{focus_cliffs}

## 疲劳演变时间线
{fatigue_evolution}

## 分心分布
{dist_pattern}

## 历史对比
{past_sessions_summary}"""


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

    def deep_analyze(self, data: Dict[str, Any]) -> str:
        """L3 级深度分析（默认回退到标准分析）"""
        return self.analyze(data)


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
        avg = data.get("avg_focus", 0)
        baseline = data.get("baseline", 60)

        # ── 整体表现 ──
        if avg >= 80:
            parts.append(f"本次专注度 {avg:.0f} 分，表现优秀。")
        elif avg >= 65:
            parts.append(f"本次专注度 {avg:.0f} 分，整体良好。")
        elif avg >= 50:
            parts.append(f"本次专注度 {avg:.0f} 分，处于中等水平。")
        else:
            parts.append(f"本次专注度 {avg:.0f} 分，偏低，状态不太理想。")

        # ── 与历史对比 ──
        hist_avg = data.get("hist_avg_focus")
        if hist_avg and abs(avg - hist_avg) > 3:
            diff_dir = "高于" if avg > hist_avg else "低于"
            parts.append(f"{diff_dir}近期平均 ({hist_avg:.0f} 分) "
                         f"{avg - hist_avg:+.0f} 分。")

        # ── 趋势分段 ──
        s, m, e = data.get("seg_start", avg), data.get("seg_mid", avg), data.get("seg_end", avg)
        if s and e and abs(s - e) > 8:
            if s > e:
                parts.append(f"前半段 {s:.0f} 分，后半段降至 {e:.0f} 分"
                             f"，下降 {s-e:.0f} 分，建议中途安排一次休息。")
            else:
                parts.append(f"后半段 {e:.0f} 分高于前半段 {s:.0f} 分，渐入佳境。")

        # ── 疲劳分析 ──
        fatigue = data.get("fatigue", "")
        fatigue_records = data.get("fatigue_records", {})
        high_pct = fatigue_records.get("high_pct", 0)
        if high_pct > 30 or fatigue == "HIGH":
            parts.append(f"疲劳信号偏多 ({high_pct:.0f}% 时间处于高疲劳)，建议保证充足睡眠。")
        elif high_pct > 10 or fatigue == "MEDIUM":
            parts.append("有间歇性疲劳信号，注意定时起身活动、眨眼。")

        # ── 分心分析 ──
        dist = data.get("distractions", 0)
        h_pct = data.get("head_pct", 0)
        g_pct = data.get("gaze_pct", 0)
        dist_peak = data.get("dist_peak_hour", "")
        if dist > 8:
            base = f"分心 {dist} 次偏多"
            if h_pct > g_pct:
                base += "，主要由头部偏移引起"
            else:
                base += "，视线偏离是主要因素"
            if dist_peak:
                base += f"，{dist_peak} 时附近最频繁"
            base += "。建议检查工位或使用番茄钟。"
            parts.append(base)
        elif dist > 3:
            parts.append(f"分心 {dist} 次，在正常范围内。")

        # ── 时长评价 ──
        dur = data.get("duration", 0)
        if dur >= 90:
            parts.append(f"连续工作 {dur} 分钟，效率不错，注意规律休息。")
        elif dur >= 30:
            parts.append(f"会话时长 {dur} 分钟。")

        # ── 番茄 ──
        pc = data.get("pomo_count", 0)
        if pc >= 4:
            parts.append(f"完成 {pc} 个番茄钟，工作节奏稳定。")

        # ── 建议 ──
        suggestions = []
        if avg < 55:
            suggestions.append("尝试缩短单次工作时长，配合番茄钟提高专注。")
        if high_pct > 20:
            suggestions.append("疲劳累积较快，建议每小时起身活动 2 分钟。")
        if dist > 10:
            suggestions.append("分心较多，可尝试关闭通知、使用降噪耳机。")
        if dur > 120 and avg < 60:
            suggestions.append("长时间低效工作不如短时高效，明天试试 45 分钟深度工作法。")
        if suggestions:
            parts.append("建议：" + "".join(suggestions))

        return "。" if not parts else "".join(parts) + "。"


# ── OpenAI 兼容版（覆盖 OpenAI / DeepSeek / Moonshot / Qwen 等） ──

OPENAI_COMPATIBLE_PROVIDERS = {
    "deepseek":   {"base_url": "https://api.deepseek.com/v1",          "model": "deepseek-chat"},
    "qwen":       {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "openai":     {"base_url": "https://api.openai.com/v1",            "model": "gpt-4o-mini"},
    "moonshot":   {"base_url": "https://api.moonshot.cn/v1",           "model": "moonshot-v1-8k"},
    "siliconflow":{"base_url": "https://api.siliconflow.cn/v1",        "model": "Qwen/Qwen2.5-7B-Instruct"},
    "zhipu":      {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",         "model": "openai/gpt-4o-mini"},
    "groq":       {"base_url": "https://api.groq.com/openai/v1",       "model": "llama-3.3-70b-versatile"},
}

# v4.x: 错误消息脱敏用正则，避免 JSON body 边界漏脱敏
#  `{"key":"sk-abc"}` 用 word-split 切出 ['{"key":', '"sk-abc"}']，
#  两个 token 都不以 'sk-' 开头 — 会泄漏。regex.search 直接找 'sk-...' 模式。
_SK_TOKEN_PATTERN = __import__('re').compile(r'sk-[A-Za-z0-9_\-:]+')
_BEARER_PATTERN = __import__('re').compile(r'Bearer\s+[A-Za-z0-9_\-:]+')


class OpenAICompatibleClient(LLMClient):
    """OpenAI 兼容 API（覆盖大多数主流云端 LLM）

    支持：DeepSeek / Qwen / OpenAI / Moonshot / SiliconFlow 等
    只需配 base_url + api_key + model_name。
    """

    def __init__(self, api_key: str = "",
                 base_url: str = "https://api.deepseek.com/v1",
                 model: str = "deepseek-chat"):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model

    def __repr__(self) -> str:
        masked = self._mask_key(self._api_key)
        return f"OpenAICompatibleClient(model={self._model}, base={self._base_url}, key={masked})"

    @staticmethod
    def _mask_key(key: str) -> str:
        if not key or len(key) <= 8:
            return "****"
        return key[:4] + "****" + key[-4:]

    @staticmethod
    def _sanitize_err(msg: str) -> str:
        """脱敏错误消息中的 API Key。

        用正则而非 word-split，避免 JSON body 边界漏脱敏：
        `{"key":"sk-abc"}` 切词后是 ['{"key":', '"sk-abc"}']，
        两个 token 都不以 'sk-' 开头 — 会泄漏。regex.search 直接找 'sk-...' 模式。
        """
        if not msg:
            return msg
        if _SK_TOKEN_PATTERN.search(msg):
            return "认证失败（无效 API Key）"
        if _BEARER_PATTERN.search(msg):
            return "认证失败（API Key 格式错误）"
        return msg

    @property
    def name(self) -> str:
        for provider, cfg in OPENAI_COMPATIBLE_PROVIDERS.items():
            if cfg["base_url"].rstrip("/") == self._base_url:
                return f"{provider} ({self._model})"
        return f"API ({self._base_url})"

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _build_headers(self) -> dict:
        """构造 HTTP headers

        有 key 就发 Authorization header（loopback 也发）。
        Loopback 字节本来就不出本机，"省略" 是过度优化，且会破坏 LM Studio
        "Require API Key" 模式。Loopback 的安全保护靠上游 HTTP 警告而非省略 header。
        """
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _post_chat(self, payload: dict, timeout: int) -> str:
        """发送 chat/completions 请求并提取首个 choice 的 content

        异常时附带响应 body（截 500 字）便于诊断 LM Studio / OpenAI 兼容 API
        返回的非标准响应（如 {"error": {...}} 而非 {"choices": [...]}）。

        Raises:
            RuntimeError: HTTPError / 响应 schema 缺字段 / JSON 解析失败，
                message 内含响应 body 片段 + 端点路径提示（如果是 endpoint 错误）
        """
        import urllib.error
        import urllib.request
        import json as _json

        data = _json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=data,
            headers=self._build_headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body_bytes = resp.read()
        except urllib.error.HTTPError as e:
            body = e.read()[:500].decode("utf-8", errors="replace")
            hint = _endpoint_hint(body)
            raise RuntimeError(f"LLM HTTP {e.code}: {body}{hint}") from e

        # 200 OK — 解析响应
        try:
            result = _json.loads(body_bytes)
        except _json.JSONDecodeError as e:
            snippet = body_bytes[:500].decode("utf-8", errors="replace")
            hint = _endpoint_hint(snippet)
            raise RuntimeError(f"LLM 响应非 JSON ({e!r}); body={snippet}{hint}") from e

        try:
            return result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            snippet = body_bytes[:500].decode("utf-8", errors="replace")
            hint = _endpoint_hint(snippet)
            raise RuntimeError(f"LLM 响应缺字段 ({e!r}); body={snippet}{hint}") from e

    def test_connection(self) -> str:
        """测试 API 连通性，返回空字符串表示成功，否则返回错误描述"""
        if not self._api_key:
            return "API Key 未设置"
        try:
            payload = {
                "model": self._model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            }
            self._post_chat(payload, timeout=10)
            return ""
        except Exception as e:
            return self._sanitize_err(str(e))

    def analyze(self, data: Dict[str, Any]) -> str:
        _safe = lambda k, d: data.get(k, d)
        user_msg = ANALYSIS_USER_TEMPLATE.format(
            duration=_safe("duration", 0), avg_focus=_safe("avg_focus", 50),
            baseline=_safe("baseline", 60), hist_avg_focus=_safe("hist_avg_focus", 60),
            seg_start=_safe("seg_start", 50), seg_mid=_safe("seg_mid", 50), seg_end=_safe("seg_end", 50),
            fatigue=_safe("fatigue", "LOW"),
            fatigue_high_pct=_safe("fatigue_high_pct", 0),
            fatigue_mid_pct=_safe("fatigue_mid_pct", 0),
            fatigue_low_pct=_safe("fatigue_low_pct", 100),
            distractions=_safe("distractions", 0), head_pct=_safe("head_pct", 0),
            gaze_pct=_safe("gaze_pct", 0), dist_peak_hour=_safe("dist_peak_hour", ""),
            pomo_count=_safe("pomo_count", 0), streak=_safe("streak", 0),
        )
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 500,
            "temperature": 0.7,
        }
        try:
            return self._post_chat(payload, timeout=30)
        except Exception as e:
            logger.error("LLM analyze 请求失败: %s", self._sanitize_err(str(e)))
            return ""  # v4.33: 失败返回空串，不抛异常（符合"失败返回 Optional"规则）

    def deep_analyze(self, data: Dict[str, Any]) -> str:
        """L3 级深度分析（使用 DEEP_ANALYSIS 系列提示模板 + 时序数据）"""
        # 构造 L3 数据上下文
        context_parts = []
        for key in ["duration", "avg_focus", "hist_avg_focus", "seg_start", "seg_mid", "seg_end",
                     "fatigue_high_pct", "fatigue_mid_pct", "fatigue_low_pct", "distractions"]:
            context_parts.append(f"- {key}: {data.get(key, 'N/A')}")
        context_parts.append("")
        for extra_key in ["focus_cliffs", "fatigue_evolution", "dist_pattern", "past_sessions_summary"]:
            val = data.get(extra_key, "")
            if val:
                context_parts.append(f"## {extra_key.replace('_', ' ').title()}\n{val}")
                context_parts.append("")

        user_msg = "\n".join(context_parts).strip()
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": DEEP_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 800,
            "temperature": 0.7,
        }
        try:
            return self._post_chat(payload, timeout=60).strip()
        except Exception as e:
            logger.error("LLM deep_analyze 请求失败: %s", self._sanitize_err(str(e)))
            return ""  # v4.33: 失败返回空串，不抛异常

    def chat(self, messages: list, max_tokens: int = 500) -> str:
        """OpenAI 格式对话（供 server.py _llm_chat 调用）"""
        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }
        try:
            return self._post_chat(payload, timeout=30)
        except Exception as e:
            logger.error("LLM chat 请求失败: %s", self._sanitize_err(str(e)))
            return ""  # v4.33: 失败返回空串，不抛异常

    def chat_stream(self, messages: list, max_tokens: int = 500, timeout: int = 60):
        """流式 chat completion，yield 每段 token 字符串。

        使用 stream:true；响应是 SSE 格式 `data: {json}\\n\\n`，
        终止于 `data: [DONE]`。每个 chunk 解出 choices[0].delta.content。

        Yields:
            str: 增量 token（可能为空字符串，应跳过）

        Raises:
            RuntimeError: HTTPError / 响应异常（带诊断 body）
        """
        import urllib.error
        import urllib.request
        import json as _json

        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "stream": True,
        }
        data = _json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=data,
            headers=self._build_headers(),
        )
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            body = e.read()[:500].decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM HTTP {e.code}: {body}") from e

        # 流式读取 — http.client.HTTPResponse 可迭代（按行）
        try:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                payload_str = line[5:].strip()
                if payload_str == "[DONE]":
                    break
                try:
                    chunk = _json.loads(payload_str)
                except _json.JSONDecodeError:
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content")
                if token:
                    yield token
        finally:
            try:
                resp.close()
            except Exception:
                pass


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

        _safe = lambda k, d: data.get(k, d)
        user_msg = ANALYSIS_USER_TEMPLATE.format(
            duration=_safe("duration", 0), avg_focus=_safe("avg_focus", 50),
            baseline=_safe("baseline", 60), hist_avg_focus=_safe("hist_avg_focus", 60),
            seg_start=_safe("seg_start", 50), seg_mid=_safe("seg_mid", 50), seg_end=_safe("seg_end", 50),
            fatigue=_safe("fatigue", "LOW"),
            fatigue_high_pct=_safe("fatigue_high_pct", 0),
            fatigue_mid_pct=_safe("fatigue_mid_pct", 0),
            fatigue_low_pct=_safe("fatigue_low_pct", 100),
            distractions=_safe("distractions", 0), head_pct=_safe("head_pct", 0),
            gaze_pct=_safe("gaze_pct", 0), dist_peak_hour=_safe("dist_peak_hour", ""),
            pomo_count=_safe("pomo_count", 0), streak=_safe("streak", 0),
        )
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

    MODEL_NAMES = {
        "qwen2.5:1.5b": ("Qwen2.5-1.5B (当前)", "qwen2.5-1.5b-instruct-q4_k_m.gguf"),
        "qwen3:1.7b": ("Qwen3-1.7B Q8_0", "Qwen3-1.7B-Q8_0.gguf"),
        "qwen3.5:1.5b": ("Qwen3.5-1.5B", "qwen3.5-1.5b-instruct-q4_k_m.gguf"),
    }

    def __init__(self, model_path=None, n_gpu_layers=0, model_key="qwen2.5:1.5b", n_ctx=4096):
        self._model_key = model_key
        self._model_path = model_path or self._resolve_path(model_key)
        self._n_gpu_layers = n_gpu_layers
        self._n_ctx = n_ctx
        self._llm = None

    @classmethod
    def _resolve_path(cls, model_key: str) -> str:
        import os
        info = cls.MODEL_NAMES.get(model_key)
        fname = info[1] if info else "qwen2.5-1.5b-instruct-q4_k_m.gguf"
        return os.path.join(os.path.dirname(__file__), "..", "models", fname)

    @property
    def name(self) -> str:
        info = self.MODEL_NAMES.get(self._model_key)
        return f"本地模型 ({info[0]})" if info else f"本地模型 ({self._model_key})"

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
            ngl = self._n_gpu_layers
            self._llm = Llama(
                model_path=self._model_path,
                n_ctx=self._n_ctx,
                n_threads=16,
                n_gpu_layers=ngl,
                verbose=False,
            )
            mode = "GPU" if ngl == -1 else f"CPU+GPU({ngl})" if ngl > 0 else "CPU"
            logger.info("本地模型已加载（%s 模式, n_gpu_layers=%d）", mode, ngl)
            return True
        except Exception as e:
            logger.error("模型加载失败: %s", e)
            return False

    def analyze(self, data: Dict[str, Any]) -> str:
        if self._llm is None:
            if not self._load_model():
                return "（本地模型加载失败，请检查模型文件或切换到其他后端）"

        _safe = lambda k, d: data.get(k, d)
        user_msg = ANALYSIS_USER_TEMPLATE.format(
            duration=_safe("duration", 0), avg_focus=_safe("avg_focus", 50),
            baseline=_safe("baseline", 60), hist_avg_focus=_safe("hist_avg_focus", 60),
            seg_start=_safe("seg_start", 50), seg_mid=_safe("seg_mid", 50), seg_end=_safe("seg_end", 50),
            fatigue=_safe("fatigue", "LOW"),
            fatigue_high_pct=_safe("fatigue_high_pct", 0),
            fatigue_mid_pct=_safe("fatigue_mid_pct", 0),
            fatigue_low_pct=_safe("fatigue_low_pct", 100),
            distractions=_safe("distractions", 0), head_pct=_safe("head_pct", 0),
            gaze_pct=_safe("gaze_pct", 0), dist_peak_hour=_safe("dist_peak_hour", ""),
            pomo_count=_safe("pomo_count", 0), streak=_safe("streak", 0),
        )

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
        client_type: "template" | "openai" | "ollama" | "local"
        **kwargs: 传递给具体客户端的参数
            api_key / base_url / model: OpenAI 兼容
            base_url: Ollama 地址
            model: Ollama 模型名
            model_path: 本地模型路径
            model_key: 本地模型标识
            n_gpu_layers: GPU 层数
            n_ctx: 上下文长度

    Returns:
        LLMClient 实例
    """
    if client_type == "template":
        return TemplateClient()
    elif client_type == "openai":
        return OpenAICompatibleClient(
            api_key=kwargs.get("api_key", ""),
            base_url=kwargs.get("base_url", "https://api.deepseek.com/v1"),
            model=kwargs.get("model", "deepseek-chat"),
        )
    elif client_type == "ollama":
        return OllamaClient(
            base_url=kwargs.get("base_url", "http://127.0.0.1:11434"),
            model=kwargs.get("model", "qwen2.5:1.5b"),
        )
    elif client_type == "local":
        return LocalClient(
            model_path=kwargs.get("model_path", ""),
            n_gpu_layers=kwargs.get("n_gpu_layers", 0),
            model_key=kwargs.get("model_key", "qwen2.5:1.5b"),
            n_ctx=kwargs.get("n_ctx", 4096),
        )
    else:
        logger.warning("未知客户端类型 %s，使用模板版", client_type)
        return TemplateClient()


def warmup_client(client: LLMClient) -> None:
    """v4.26: 预热 LLM 客户端（后台加载模型，减少首次分析延迟）

    在监测开始时调用，不阻塞主流程。
    仅对 LocalClient 有意义（OllamaClient 是网络调用，无需预热）。
    """
    if isinstance(client, LocalClient):
        logger.info("后台预热本地模型...")
        client.analyze({
            "duration": 0, "avg_focus": 50, "baseline": 60, "hist_avg_focus": 60,
            "seg_start": 50, "seg_mid": 50, "seg_end": 50,
            "fatigue": "LOW", "fatigue_high_pct": 0, "fatigue_mid_pct": 0, "fatigue_low_pct": 100,
            "distractions": 0, "head_pct": 0, "gaze_pct": 0, "dist_peak_hour": "",
            "pomo_count": 0, "streak": 0,
        })
    elif isinstance(client, OllamaClient):
        # Ollama 预热 = 检查可用性
        client.available

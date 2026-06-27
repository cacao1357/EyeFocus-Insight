"""
tests/test_llm_warmup.py — LLM 预热回归 + loopback header 行为

覆盖：
- OpenAICompatibleClient._build_headers 各场景
- webserver.server.WebDashboard._start_llm_warmup 在 test_connection 失败时：
  · _llm_client 保持 None
  · 记录 WARNING
  · 不再记录误导性 INFO "LLM 预热完成"
- 非 loopback HTTP 触发警告；loopback HTTP 静默
"""

import logging
import os
import sys
import time
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyzer.llm_client import OpenAICompatibleClient
from webserver.server import WebDashboard


# ── 测试模块级 helper ────────────────────────────────────────────────────

def _make_http_error(code: int, body: bytes):
    """构造真实的 urllib.error.HTTPError（urlopen 4xx/5xx 时抛出）"""
    import io
    import urllib.error
    return urllib.error.HTTPError(
        url="http://127.0.0.1:1234/chat/completions",
        code=code,
        msg="Mocked",
        hdrs={},
        fp=io.BytesIO(body),
    )


def _mock_urlopen_ok(body_bytes: bytes):
    """模拟 urlopen 返回 200 OK 带指定 body"""
    resp = mock.MagicMock()
    resp.status = 200
    resp.read.return_value = body_bytes
    resp.__enter__ = mock.MagicMock(return_value=resp)
    resp.__exit__ = mock.MagicMock(return_value=False)
    return mock.patch("urllib.request.urlopen", return_value=resp)


def _mock_urlopen_err(http_error):
    """模拟 urlopen 抛 HTTPError"""
    return mock.patch("urllib.request.urlopen", side_effect=http_error)


# ── 公共 helper ──────────────────────────────────────────────────────────

def _patch_warmup_env(dashboard, backend="openai", base_url="http://127.0.0.1:1234",
                      test_err="API 连接失败: mock"):
    """Mock get_yaml_value + create_llm_client；启动预热；等待线程结束

    关键点：
    - 把父 logger "eyefocus" 暂时设回 INFO：tests/test_integration.py:617 会把它
      永久设到 ERROR（无 finally 还原），污染后续 caplog 测试
    - _llm_ready.set() 在 logger.info() 之前；wait() 返回后给线程 50ms flush 日志
    """
    fake_client = mock.MagicMock()
    fake_client.available = True
    fake_client.test_connection.return_value = test_err
    fake_client.name = "API (mock)"

    config_values = {
        ("ai", "backend"): backend,
        ("ai", "api_url"): base_url,
        ("ai", "api_model"): "test-model",
    }

    def fake_get_yaml(*args, **kwargs):
        return config_values.get((args[0], args[1]), kwargs.get("default", ""))

    parent_logger = logging.getLogger("eyefocus")
    saved_level = parent_logger.level
    parent_logger.setLevel(logging.INFO)

    p1 = mock.patch("config.get_yaml_value", side_effect=fake_get_yaml)
    p2 = mock.patch("analyzer.llm_client.create_llm_client", return_value=fake_client)
    p1.start(); p2.start()
    try:
        dashboard._start_llm_warmup()
        assert dashboard._llm_ready.wait(timeout=5), "warmup 线程未在 5s 内完成"
        # _llm_ready.set() 在 logger.info() 之前；给线程留窗口发完日志
        time.sleep(0.05)
    finally:
        p1.stop(); p2.stop()
        parent_logger.setLevel(saved_level)
    return fake_client


# ── _build_headers 各场景 ────────────────────────────────────────────────

class TestBuildHeaders:

    def test_sends_auth_on_loopback_127_when_key_set(self):
        """回归 v4.x.1: loopback + 有 key 也发 Authorization（LM Studio Require API Key 需要）"""
        c = OpenAICompatibleClient("sk-test", "http://127.0.0.1:1234", "qwen")
        h = c._build_headers()
        assert h["Authorization"] == "Bearer sk-test"
        assert h["Content-Type"] == "application/json"

    def test_sends_auth_on_loopback_localhost_when_key_set(self):
        c = OpenAICompatibleClient("sk-test", "http://localhost:1234", "qwen")
        assert c._build_headers()["Authorization"] == "Bearer sk-test"

    def test_sends_auth_on_ipv6_loopback_when_key_set(self):
        c = OpenAICompatibleClient("sk-test", "http://[::1]:1234", "qwen")
        assert c._build_headers()["Authorization"] == "Bearer sk-test"

    def test_sends_auth_on_https(self):
        c = OpenAICompatibleClient("sk-test", "https://api.deepseek.com/v1", "deepseek-chat")
        h = c._build_headers()
        assert h["Authorization"] == "Bearer sk-test"
        assert h["Content-Type"] == "application/json"

    def test_sends_auth_on_remote_http(self):
        """非 loopback HTTP 仍发 Authorization（上层 warning 兜底提示改 HTTPS）"""
        c = OpenAICompatibleClient("sk-test", "http://api.example.com", "x")
        assert c._build_headers()["Authorization"] == "Bearer sk-test"

    def test_empty_key_never_sends_auth_on_loopback(self):
        """空 key → 无 Authorization（LM Studio 默认 Require API Key = OFF 也能通）"""
        c = OpenAICompatibleClient("", "http://127.0.0.1:1234", "qwen")
        assert "Authorization" not in c._build_headers()
        assert c._build_headers() == {"Content-Type": "application/json"}

    def test_empty_key_never_sends_auth_on_https(self):
        c = OpenAICompatibleClient("", "https://api.deepseek.com/v1", "x")
        assert "Authorization" not in c._build_headers()


# ── Bug 回归：test_connection 失败时必须 return ─────────────────────────

class TestWarmupReturnsOnFailure:
    """回归 v4.x: server.py:263 缺 return 导致误导性 'LLM 预热完成'"""

    def test_failure_keeps_llm_client_none(self, caplog):
        d = WebDashboard(port=0)
        with caplog.at_level(logging.INFO, logger="eyefocus.webserver"):
            _patch_warmup_env(d)
        assert d._llm_client is None, "失败时 _llm_client 必须保持 None"

    def test_failure_logs_warning(self, caplog):
        d = WebDashboard(port=0)
        with caplog.at_level(logging.INFO, logger="eyefocus.webserver"):
            _patch_warmup_env(d, test_err="API 连接失败: WinError 10061")
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("API 连接失败" in r for r in warnings), \
            f"预期有 'API 连接失败' 警告，实际: {warnings}"

    def test_failure_does_not_log_misleading_complete(self, caplog):
        """回归关键：不再有 'LLM 预热完成' 的误导性 INFO"""
        d = WebDashboard(port=0)
        with caplog.at_level(logging.INFO, logger="eyefocus.webserver"):
            _patch_warmup_env(d)
        info_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert not any("LLM 预热完成" in m for m in info_msgs), \
            f"失败时不应有 'LLM 预热完成' INFO，实际: {info_msgs}"

    def test_failure_sets_ready_event_with_error(self, caplog):
        """_llm_ready 仍 set，_llm_error 有值 — 让 /api/llm_status 正确反映失败"""
        d = WebDashboard(port=0)
        with caplog.at_level(logging.INFO, logger="eyefocus.webserver"):
            _patch_warmup_env(d, test_err="API 连接失败: connection refused")
        assert d._llm_ready.is_set(), "_llm_ready 必须被 set"
        assert "API 连接失败" in d._llm_error

    def test_success_path_still_works(self, caplog):
        """回归不能破坏正常路径：test_connection 返回空 → 走完成日志"""
        d = WebDashboard(port=0)
        with caplog.at_level(logging.INFO, logger="eyefocus.webserver"):
            _patch_warmup_env(d, test_err="")  # 空字符串 = 成功
        info_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert any("LLM 预热完成" in m for m in info_msgs), \
            f"成功路径应记录 'LLM 预热完成'，实际: {info_msgs}"
        assert d._llm_client is not None
        assert d._llm_error == ""


# ── HTTP 明文警告：loopback 静默；远程 HTTP 触发 ─────────────────────────

class TestHttpPlaintxtWarning:

    def test_remote_http_triggers_warning(self, caplog):
        d = WebDashboard(port=0)
        with caplog.at_level(logging.INFO, logger="eyefocus.webserver"):
            _patch_warmup_env(d, base_url="http://api.example.com:8080")
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("HTTP" in w and "明文" in w for w in warnings), \
            f"非 loopback HTTP 应触发明文警告，实际: {warnings}"

    def test_loopback_http_silent(self, caplog):
        d = WebDashboard(port=0)
        with caplog.at_level(logging.INFO, logger="eyefocus.webserver"):
            _patch_warmup_env(d, base_url="http://127.0.0.1:1234")
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert not any("明文" in w for w in warnings), \
            f"loopback HTTP 不应触发明文警告，实际: {warnings}"

    def test_https_silent(self, caplog):
        d = WebDashboard(port=0)
        with caplog.at_level(logging.INFO, logger="eyefocus.webserver"):
            _patch_warmup_env(d, base_url="https://api.deepseek.com/v1")
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert not any("明文" in w for w in warnings), \
            f"HTTPS 不应触发明文警告，实际: {warnings}"


# ── _post_chat 诊断日志：响应 schema 异常时附带 body ─────────────────────

class TestPostChatDiagnostics:
    """回归 v4.x.2: 'choices' KeyError 应该附带响应 body 便于诊断"""

    def test_missing_choices_includes_body(self):
        """200 OK 但 body 是 {\"error\": ...} → RuntimeError 带 body"""
        body = b'{"error": {"message": "Model not found", "code": "model_not_found"}}'
        c = OpenAICompatibleClient("sk-test", "http://127.0.0.1:1234", "qwen")
        with _mock_urlopen_ok(body):
            with pytest.raises(RuntimeError) as exc_info:
                c._post_chat({"model": "qwen", "messages": [], "max_tokens": 10}, timeout=10)
        msg = str(exc_info.value)
        assert "choices" in msg
        assert "Model not found" in msg
        assert "model_not_found" in msg

    def test_http_error_includes_body(self):
        """HTTP 4xx/5xx → RuntimeError 带 status code + body"""
        err = _make_http_error(404, b'{"error": "model Qwen3 not found"}')
        c = OpenAICompatibleClient("sk-test", "http://127.0.0.1:1234", "Qwen3")
        with _mock_urlopen_err(err):
            with pytest.raises(RuntimeError) as exc_info:
                c._post_chat({"model": "Qwen3", "messages": [], "max_tokens": 10}, timeout=10)
        msg = str(exc_info.value)
        assert "HTTP 404" in msg
        assert "model Qwen3 not found" in msg

    def test_non_json_response_includes_body(self):
        """SSE 流式 / 纯文本 → RuntimeError 带 body 片段"""
        body = b'data: {"id":"x","choices":[...]}\n\ndata: [DONE]\n'
        c = OpenAICompatibleClient("sk-test", "http://127.0.0.1:1234", "qwen")
        with _mock_urlopen_ok(body):
            with pytest.raises(RuntimeError) as exc_info:
                c._post_chat({"model": "qwen", "messages": [], "max_tokens": 10}, timeout=10)
        msg = str(exc_info.value)
        assert "JSON" in msg
        assert "data:" in msg

    def test_successful_response_extracts_content(self):
        """正常 200 OK 响应 → 返回 content"""
        body = b'{"choices": [{"message": {"content": "hello"}}]}'
        c = OpenAICompatibleClient("sk-test", "http://127.0.0.1:1234", "qwen")
        with _mock_urlopen_ok(body):
            result = c._post_chat({"model": "qwen", "messages": [], "max_tokens": 10}, timeout=10)
        assert result == "hello"

    def test_analyze_returns_empty_on_diagnostic_error(self):
        """analyze 包装 _post_chat：异常时返回空串（不动 outer 语义）"""
        body = b'{"error": {"message": "Model not found"}}'
        c = OpenAICompatibleClient("sk-test", "http://127.0.0.1:1234", "qwen")
        with _mock_urlopen_ok(body):
            result = c.analyze({"duration": 100, "avg_focus": 80})
        assert result == ""

    def test_deep_analyze_returns_empty_on_diagnostic_error(self):
        body = b'{"error": {"message": "Model not found"}}'
        c = OpenAICompatibleClient("sk-test", "http://127.0.0.1:1234", "qwen")
        with _mock_urlopen_ok(body):
            result = c.deep_analyze({"duration": 100, "avg_focus": 80})
        assert result == ""


# ── _sanitize_err JSON 边界脱敏（避免漏掉 {"key":"sk-..."}） ──────────────

class TestSanitizeErr:
    """v4.x.5: 用 regex 替代 word-split，防止 JSON body 边界漏脱敏"""

    @staticmethod
    def _san(msg):
        return OpenAICompatibleClient._sanitize_err(msg)

    # ── 旧 word-split 漏掉的 JSON 边界场景（核心回归）

    def test_sk_token_in_json_quoted_value(self):
        """{\"key\":\"sk-abc\"} — word-split 切出 ['{\"key\":', '\"sk-abc\"}']，漏检。"""
        msg = '{"error":"invalid","key":"sk-test123"}'
        assert self._san(msg) == "认证失败（无效 API Key）"

    def test_bearer_in_json_quoted_value(self):
        """{\"authorization\":\"Bearer sk-abc\"} — 同理。命中 SK（SK 优先于 Bearer）。"""
        msg = '{"authorization":"Bearer sk-test123","error":"invalid"}'
        # 语义：原代码 SK 检查先于 Bearer；regex 化后保留同样语义（命中 SK → 无效 Key）
        assert self._san(msg) == "认证失败（无效 API Key）"

    def test_sk_with_colon_prefix(self):
        """用户的 key 含 ':'（LM Studio 本地 key 常见格式 sk-lm-xxx:yyy）。"""
        msg = '{"key":"sk-lm-5saGlLbb:63PkNMsVF3la2VKpJKw4"}'
        assert self._san(msg) == "认证失败（无效 API Key）"

    # ── 旧逻辑覆盖的场景（确保没破坏）

    def test_plain_sk_word(self):
        msg = "the key is sk-xyz"
        assert self._san(msg) == "认证失败（无效 API Key）"

    def test_plain_bearer_word(self):
        msg = "Authorization: Bearer sk-xyz"
        # 同上语义：SK 命中优先于 Bearer
        assert self._san(msg) == "认证失败（无效 API Key）"

    # ── 负向：不应误脱敏

    def test_no_key_message_passes_through(self):
        assert self._san("HTTP Error 500: server error") == "HTTP Error 500: server error"

    def test_unrelated_string_passes_through(self):
        assert self._san("connection refused") == "connection refused"

    def test_similar_but_not_sk(self):
        # "skill" 不应误判 — 旧逻辑也匹配是因为 word.startswith('sk-')
        # 新逻辑 r'sk-[A-Za-z0-9_\-:]+' 要求 'sk-' 紧跟一个 token 字符
        assert self._san("skill test") == "skill test"

    def test_empty_passes_through(self):
        assert self._san("") == ""

    # ── Real-world 错误消息

    def test_typical_lm_studio_401_body(self):
        msg = '{"error":{"message":"Invalid API Key. sk-abc123 provided.","code":"invalid_api_key"}}'
        assert self._san(msg) == "认证失败（无效 API Key）"

    def test_typical_openai_401_body(self):
        msg = '{"error":{"message":"Incorrect API key provided: sk-abc****xyz. ","type":"invalid_request_error"}}'
        assert self._san(msg) == "认证失败（无效 API Key）"


# ── chat_stream：流式 OpenAI 兼容协议（第二波 SSE） ──────────────────────

class TestChatStream:
    """v4.x 第二波：OpenAICompatibleClient.chat_stream() 解析 SSE"""

    @staticmethod
    def _mock_stream(lines):
        """构造可迭代的 mock urlopen 响应"""
        resp = mock.MagicMock()
        resp.__iter__ = mock.MagicMock(return_value=iter(lines))
        resp.close = mock.MagicMock()
        return mock.patch("urllib.request.urlopen", return_value=resp)

    def _run_stream(self, lines):
        """运行 chat_stream 并返回 tokens 列表"""
        c = OpenAICompatibleClient("sk-test", "http://127.0.0.1:1234", "qwen")
        with self._mock_stream(lines):
            return list(c.chat_stream([{"role": "user", "content": "hi"}], timeout=10))

    def test_yields_tokens_from_sse_chunks(self):
        sse = [
            b'data: {"id":"1","choices":[{"delta":{"content":"Hello"}}]}\n',
            b'\n',
            b'data: {"id":"2","choices":[{"delta":{"content":" "}}]}\n',
            b'\n',
            b'data: {"id":"3","choices":[{"delta":{"content":"world"}}]}\n',
            b'\n',
            b'data: [DONE]\n',
            b'\n',
        ]
        assert self._run_stream(sse) == ["Hello", " ", "world"]

    def test_stops_at_done_marker(self):
        sse = [
            b'data: {"choices":[{"delta":{"content":"a"}}]}\n',
            b'\n',
            b'data: [DONE]\n',
            b'\n',
            # DONE 之后的行不应被处理
            b'data: {"choices":[{"delta":{"content":"ignored"}}]}\n',
            b'\n',
        ]
        tokens = self._run_stream(sse)
        assert tokens == ["a"]

    def test_skips_chunks_without_content(self):
        """choices[].delta 为空 → 跳过（DONE 仍终止）"""
        sse = [
            b'data: {"choices":[{"delta":{}}]}\n',
            b'\n',
            b'data: {"choices":[{"delta":{"content":"only"}}]}\n',
            b'\n',
            b'data: [DONE]\n',
        ]
        assert self._run_stream(sse) == ["only"]

    def test_skips_malformed_json_lines(self):
        sse = [
            b'data: not valid json\n',
            b'\n',
            b'data: {"choices":[{"delta":{"content":"works"}}]}\n',
            b'\n',
            b'data: [DONE]\n',
        ]
        assert self._run_stream(sse) == ["works"]

    def test_skips_non_data_lines(self):
        """不以 data: 开头的行（如注释 :）跳过"""
        sse = [
            b': keepalive comment\n',
            b'\n',
            b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
            b'\n',
            b'data: [DONE]\n',
        ]
        assert self._run_stream(sse) == ["ok"]

    def test_raises_runtime_error_on_http_error(self):
        """HTTPError → RuntimeError 带 status + body"""
        err = _make_http_error(500, b'{"error":"server overloaded"}')
        with mock.patch("urllib.request.urlopen", side_effect=err):
            c = OpenAICompatibleClient("sk-test", "http://127.0.0.1:1234", "qwen")
            with pytest.raises(RuntimeError) as exc_info:
                list(c.chat_stream([{"role": "user", "content": "hi"}]))
        msg = str(exc_info.value)
        assert "HTTP 500" in msg
        assert "server overloaded" in msg

    def test_request_uses_stream_true(self):
        """请求 payload 应包含 stream:true 字段"""
        captured = {}
        original_stream_lines = [
            b'data: {"choices":[{"delta":{"content":"x"}}]}\n',
            b'\n',
            b'data: [DONE]\n',
        ]
        def fake_urlopen(req, timeout=10):
            # 捕获请求体
            captured["body"] = req.data
            captured["headers"] = dict(req.headers)
            resp = mock.MagicMock()
            resp.__iter__ = mock.MagicMock(return_value=iter(original_stream_lines))
            resp.close = mock.MagicMock()
            return resp
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            c = OpenAICompatibleClient("sk-test", "http://127.0.0.1:1234", "qwen")
            list(c.chat_stream([{"role": "user", "content": "hi"}]))
        import json
        payload = json.loads(captured["body"].decode())
        assert payload["stream"] is True, f"应 stream:true, payload={payload}"
        assert payload["model"] == "qwen"
        assert captured["headers"]["Authorization"] == "Bearer sk-test"


# ── /v1 端点路径提示：LM Studio / Ollama 缺 /v1 前缀的友好错误 ────────────
    """_endpoint_hint + _post_chat 在 endpoint 错误时追加 /v1 提示"""

    def test_unexpected_endpoint_includes_v1_hint(self):
        """LM Studio 典型 'Unexpected endpoint' 错误 → 错误消息含 /v1 提示"""
        body = b'{"error":"Unexpected endpoint or method. (POST /chat/completions)"}'
        c = OpenAICompatibleClient("sk-test", "http://127.0.0.1:1234", "Qwen3")
        with _mock_urlopen_ok(body):
            with pytest.raises(RuntimeError) as exc_info:
                c._post_chat({"model": "Qwen3", "messages": [], "max_tokens": 10}, timeout=10)
        msg = str(exc_info.value)
        assert "/v1" in msg
        assert "LM Studio" in msg or "Ollama" in msg

    def test_ollama_404_includes_v1_hint(self):
        """Ollama 典型 '404 page not found' → 触发 /v1 提示"""
        body = b'{"error":"404 page not found"}'
        c = OpenAICompatibleClient("sk-test", "http://127.0.0.1:11434", "qwen")
        with _mock_urlopen_ok(body):
            with pytest.raises(RuntimeError) as exc_info:
                c._post_chat({"model": "qwen", "messages": [], "max_tokens": 10}, timeout=10)
        msg = str(exc_info.value)
        assert "/v1" in msg

    def test_model_not_found_no_hint(self):
        """普通 'Model not found' 错误不应加 /v1 提示（避免误导）"""
        body = b'{"error": {"message": "Model not found", "code": "model_not_found"}}'
        c = OpenAICompatibleClient("sk-test", "http://127.0.0.1:1234/v1", "qwen")
        with _mock_urlopen_ok(body):
            with pytest.raises(RuntimeError) as exc_info:
                c._post_chat({"model": "qwen", "messages": [], "max_tokens": 10}, timeout=10)
        msg = str(exc_info.value)
        assert "/v1" not in msg, f"普通错误不应追加 /v1 提示: {msg}"

    def test_endpoint_hint_helper_unit(self):
        """_endpoint_hint 函数级单测"""
        from analyzer.llm_client import _endpoint_hint
        assert "/v1" in _endpoint_hint("Unexpected endpoint or method")
        assert "/v1" in _endpoint_hint("404 page not found")
        assert _endpoint_hint("") == ""
        assert _endpoint_hint("Model not found") == ""       # 不应误触发
        assert _endpoint_hint('{"error":"Model not found"}') == ""
        assert _endpoint_hint('{"choices": [...]}') == ""    # 正常响应无提示
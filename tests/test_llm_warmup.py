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


# ── /v1 端点路径提示：LM Studio / Ollama 缺 /v1 前缀的友好错误 ────────────

class TestEndpointHint:
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
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
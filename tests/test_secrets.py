"""
tests/test_secrets.py — analyzer.secrets (keyring + loopback) 单元测试

覆盖：
- is_loopback_url 各 URL 形态
- get_api_key 三种来源（keyring / env / none）+ keyring 失败降级
- set_api_key / delete_api_key 写入路径
- storage_location 状态判定
"""

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyzer import secrets


# ── is_loopback_url ──────────────────────────────────────────────────────

class TestIsLoopbackUrl:
    """loopback 判定：127/8 + localhost + ::1"""

    @pytest.mark.parametrize("url,expected", [
        ("http://127.0.0.1:1234",        True),
        ("http://localhost:1234",        True),
        ("http://[::1]:1234",            True),
        ("http://127.0.0.99:1234",       True),   # 127.0.0.0/8
        ("http://127.255.255.254:80",    True),
        ("HTTPS://LOCALHOST:443",        True),   # 大小写不敏感
        ("https://api.deepseek.com/v1",  False),
        ("http://api.deepseek.com/v1",   False),
        ("http://10.0.0.5:1234",         False),
        ("http://192.168.1.1:1234",      False),
        ("",                             False),
        ("not a url",                    False),
        ("file:///etc/passwd",           False),
    ])
    def test_various_urls(self, url, expected):
        assert secrets.is_loopback_url(url) is expected

    def test_none_url(self):
        assert secrets.is_loopback_url(None) is False  # type: ignore[arg-type]


# ── get_api_key 解析优先级 ──────────────────────────────────────────────

class TestGetApiKey:
    """keyring > env > None；任何一步失败都降级而非抛异常"""

    def test_returns_none_when_neither_set(self, monkeypatch):
        # keyring 返回 None（无存储） + env 未设
        with mock.patch("keyring.get_password", return_value=None):
            monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
            assert secrets.get_api_key() is None

    def test_keyring_wins_over_env(self, monkeypatch):
        # keyring 有值，env 也有值（不同） → 优先 keyring
        monkeypatch.setenv("MINIMAX_API_KEY", "sk-from-env")
        with mock.patch("keyring.get_password", return_value="sk-from-keyring"):
            assert secrets.get_api_key() == "sk-from-keyring"

    def test_env_fallback_when_keyring_missing(self, monkeypatch):
        # keyring 抛异常 → 回退 env
        monkeypatch.setenv("MINIMAX_API_KEY", "sk-from-env")
        with mock.patch("keyring.get_password", side_effect=Exception("vault locked")):
            assert secrets.get_api_key() == "sk-from-env"

    def test_env_fallback_when_keyring_returns_none(self, monkeypatch):
        monkeypatch.setenv("MINIMAX_API_KEY", "sk-from-env")
        with mock.patch("keyring.get_password", return_value=None):
            assert secrets.get_api_key() == "sk-from-env"

    def test_returns_none_when_keyring_empty_and_env_missing(self, monkeypatch):
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        with mock.patch("keyring.get_password", return_value=None):
            assert secrets.get_api_key() is None


# ── keyring 包不可用时降级 ───────────────────────────────────────────────

class TestKeyringUnavailable:
    """keyring 包未安装 / 后端 Fail → 静默走 env"""

    def test_get_api_key_when_keyring_import_fails(self, monkeypatch):
        """`import keyring` 抛 ImportError → 回退 env"""
        monkeypatch.setenv("MINIMAX_API_KEY", "sk-from-env")

        # 在 secrets.py 里 `import keyring` 是 lazy 的，需要屏蔽掉 sys.modules
        with mock.patch.dict(sys.modules, {"keyring": None}):
            # 在 secrets.py 重新触发 import
            assert secrets.get_api_key() == "sk-from-env"

    def test_keyring_available_returns_false_when_backend_is_null(self):
        """keyring.get_keyring() 返回 NullKeyring → 视为不可用"""
        with mock.patch("keyring.get_keyring", return_value=None):
            assert secrets.keyring_available() is False

    def test_keyring_available_returns_false_when_backend_is_fail(self):
        fake_fail = type("Fail", (), {})()
        with mock.patch("keyring.get_keyring", return_value=fake_fail):
            assert secrets.keyring_available() is False


# ── set_api_key / delete_api_key ─────────────────────────────────────────

class TestSetDeleteApiKey:

    def test_set_api_key_calls_keyring_set_password(self):
        with mock.patch("keyring.set_password") as mock_set:
            assert secrets.set_api_key("sk-new") is True
            mock_set.assert_called_once_with(secrets.KEYRING_SERVICE, secrets.KEYRING_USER, "sk-new")

    def test_set_api_key_rejects_empty(self):
        with mock.patch("keyring.set_password") as mock_set:
            assert secrets.set_api_key("") is False
            mock_set.assert_not_called()

    def test_set_api_key_returns_false_on_failure(self):
        with mock.patch("keyring.set_password", side_effect=Exception("vault locked")):
            assert secrets.set_api_key("sk-x") is False

    def test_delete_api_key_swallows_missing_entry(self):
        # keyring.PasswordDeleteError 不应抛
        import keyring.errors as ke
        with mock.patch("keyring.delete_password", side_effect=ke.PasswordDeleteError("not found")):
            assert secrets.delete_api_key() is True

    def test_delete_api_key_swallows_unexpected_error_treats_as_success(self):
        """delete_password 抛任意异常都视为成功（"不存在或无法删除"已是无 keyring 条目）"""
        with mock.patch("keyring.delete_password", side_effect=Exception("vault broken")):
            assert secrets.delete_api_key() is True


# ── storage_location ─────────────────────────────────────────────────────

class TestStorageLocation:

    def test_keyring_value_wins(self, monkeypatch):
        monkeypatch.setenv("MINIMAX_API_KEY", "sk-from-env")
        with mock.patch("keyring.get_password", return_value="sk-from-keyring"):
            assert secrets.storage_location() == "keyring"

    def test_env_only(self, monkeypatch):
        monkeypatch.setenv("MINIMAX_API_KEY", "sk-from-env")
        with mock.patch("keyring.get_password", return_value=None):
            assert secrets.storage_location() == "env"

    def test_none(self, monkeypatch):
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        with mock.patch("keyring.get_password", return_value=None):
            assert secrets.storage_location() == "none"
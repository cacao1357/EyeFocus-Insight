"""
analyzer/secrets.py — API key 解析与 OS keyring 包装

解析顺序（读取时）：
  1. OS keyring (Windows Credential Manager / macOS Keychain / Secret Service)
  2. os.environ['MINIMAX_API_KEY']（由 config.py 从 .env 加载）
  3. None

写入只通过 set_api_key()（Settings dialog 触发），**不会**自动从 .env 迁移。
keyring 包未安装 / 后端不可用时静默降级到 env，绝不抛异常。
"""
from __future__ import annotations

import logging
import os
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("eyefocus.secrets")

# ── 常量 ────────────────────────────────────────────────────────────────
KEYRING_SERVICE = "EyeFocusInsight"
KEYRING_USER = "minimax_api_key"
ENV_KEY = "MINIMAX_API_KEY"

_LOOPBACK_HOSTS = frozenset({"localhost", "::1", "[::1]"})


# ── Loopback 判定 ────────────────────────────────────────────────────────
def is_loopback_url(url: str) -> bool:
    """判断 URL 是否指向本机 loopback（127/8 / localhost / ::1）

    用于：HTTP 明文警告豁免 + Authorization header 发送策略。
    """
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    if host in _LOOPBACK_HOSTS:
        return True
    if host.startswith("127."):
        return True
    return False


# ── Keyring 后端检测 ────────────────────────────────────────────────────
def keyring_available() -> bool:
    """keyring 包存在且后端可用"""
    try:
        import keyring  # noqa: F401
        kr = keyring.get_keyring()
        return kr is not None and type(kr).__name__ not in {"Fail", "NullKeyring"}
    except Exception as e:
        logger.debug("keyring 不可用: %s", e)
        return False


# ── Key 解析 ─────────────────────────────────────────────────────────────
def get_api_key() -> Optional[str]:
    """keyring → env → None

    任意步骤失败都不抛。优先 keyring，回退到 os.environ。
    """
    # 1) keyring
    try:
        import keyring
        val = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        if val:
            return val
    except Exception as e:
        logger.debug("keyring 读取失败，回退到 env: %s", e)

    # 2) env
    return os.environ.get(ENV_KEY) or None


def set_api_key(key: str) -> bool:
    """写入 keyring。失败返回 False，**不会**回写 .env。"""
    if not key:
        return False
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
        return True
    except Exception as e:
        logger.warning("keyring 写入失败: %s", e)
        return False


def delete_api_key() -> bool:
    """删除 keyring 条目。不存在或失败都返回 True（无副作用）。"""
    try:
        import keyring
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception:
            # keyring.errors.PasswordDeleteError 或后端"不存在"语义
            pass
        return True
    except Exception as e:
        logger.warning("keyring 删除失败: %s", e)
        return False


def storage_location() -> str:
    """用户可见标签：'keyring' | 'env' | 'none'"""
    # keyring 有值即报 keyring（即使 env 也有值，keyring 优先）
    try:
        import keyring
        if keyring.get_password(KEYRING_SERVICE, KEYRING_USER):
            return "keyring"
    except Exception:
        pass
    if os.environ.get(ENV_KEY):
        return "env"
    return "none"
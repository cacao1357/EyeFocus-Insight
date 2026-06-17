"""
reporter/font_loader.py — 字体加载策略 (v4.26)

设计意图：报告是离线 .html（生成一次、浏览器反复打开），但生成时联网
就能拿到 Google Fonts CDN 链接 → 浏览器首次打开时下载字体。
若生成时已离线 → 不注入 link 标签，浏览器走系统字体回退。

字体选择（已写入 CSS 变量）:
  Display: Fraunces (variable serif, 光学仪器质感)
  Body:    Inter (modern UI sans, 强可读性)
  Mono:    JetBrains Mono (数据/时间戳)
  中文:    思源宋体 / SimSun (衬线落款)

所有字体均有本地 fallback，离线时自动降级到 Georgia + YaHei。
"""
from __future__ import annotations

import logging
import os
import socket
from typing import Optional

logger = logging.getLogger("eyefocus.reporter")

# Google Fonts CDN（不查 fonts.googleapis.com 根，HEAD 经常被 404/重定向，
# 实际 fetch 的是 fonts.gstatic.com 下的 woff2 —— 改用解析 google.com）
_FONT_PROBE_HOST = "fonts.googleapis.com"
_FONT_PROBE_PORT = 443
_PROBE_TIMEOUT = 1.5  # 秒（不能太慢，报告生成不能卡）

# 模块级缓存：单次报告生成只检测一次
_cached_online: Optional[bool] = None
_forced_offline: Optional[bool] = None  # 测试用：强制 offline


def force_offline(value: Optional[bool]) -> None:
    """测试钩子：强制指定在线/离线状态，绕过真实探测。

    None = 清除强制，恢复真实探测
    True  = 强制在线
    False = 强制离线
    """
    global _forced_offline, _cached_online
    _forced_offline = value
    _cached_online = None  # 清缓存


def _probe_online() -> bool:
    """探测是否能访问 Google Fonts CDN。失败/超时一律视为离线。"""
    if _forced_offline is not None:
        return not _forced_offline
    try:
        # 用 socket TCP 连接探测（HEAD 请求在小宽带上反而更慢）
        with socket.create_connection(
            (_FONT_PROBE_HOST, _FONT_PROBE_PORT),
            timeout=_PROBE_TIMEOUT,
        ):
            return True
    except (socket.timeout, OSError) as e:
        logger.debug("字体 CDN 探测失败（%s），将使用系统字体回退", e)
        return False


def is_online() -> bool:
    """返回当前是否能加载 Google Fonts。结果缓存。"""
    global _cached_online
    if _cached_online is None:
        _cached_online = _probe_online()
    return _cached_online


# ── 字体回退栈（与 CSS 中 font-family 一一对应）──

FONT_STACK_DISPLAY = (
    "'Fraunces', Georgia, 'Times New Roman', 'Source Han Serif SC', "
    "'Noto Serif SC', 'SimSun', serif"
)
FONT_STACK_BODY = (
    "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', "
    "'PingFang SC', 'Microsoft YaHei', 'Hiragino Sans GB', sans-serif"
)
FONT_STACK_MONO = (
    "'JetBrains Mono', 'Cascadia Mono', 'JetBrains Mono', Consolas, "
    "'SF Mono', 'Courier New', monospace"
)


def get_link_tag() -> str:
    """返回 <link> 标签用于加载 Google Fonts CSS。

    在线：返回 preconnect + stylesheet link
    离线：返回空字符串（CSS_STYLE :root 已有字体回退链，无需 link）

    注：字体回退链（'Fraunces', 'Inter', ...）写在 CSS_STYLE 的 :root 中，
    本函数仅负责加 <link>。这样离线时浏览器也能直接走 fallback。
    """
    if not is_online():
        return ""

    # Google Fonts CSS API：Fraunces + Inter + JetBrains Mono
    # weight 选择最少必要集（避免下载整个字体集）
    href = (
        "https://fonts.googleapis.com/css2?"
        "family=Fraunces:opsz,wght@9..144,300..700"
        "&family=Inter:wght@400;500;600;700"
        "&family=JetBrains+Mono:wght@400;500"
        "&display=swap"
    )

    return (
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        f'<link rel="stylesheet" href="{href}">'
    )

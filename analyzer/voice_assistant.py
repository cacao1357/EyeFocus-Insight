"""
analyzer/voice_assistant.py — 语音反馈助手 (v4.17)

v4.49+: 语音已移除，保留文件结构和类名为空存根。
原始代码仅注释保留，不删除。
"""

import logging
# import time
# from typing import Optional, Set

logger = logging.getLogger("eyefocus.analyzer")


class VoiceAssistant:                              # v4.49+: 空存根
    """语音反馈助手（已禁用）"""
    def __init__(self, enabled: bool = True, tts_rate: int = 160):
        self._enabled = False
    def on_tick(self, **kwargs) -> None: pass
    def say(self, text: str) -> None: pass
    def _say(self, text: str) -> None: pass
    def set_enabled(self, enabled: bool) -> None: self._enabled = enabled
    @property
    def is_enabled(self) -> bool: return self._enabled
    def shutdown(self) -> None: pass


# class VoiceAssistant:                             # v4.49+: 原始代码仅注释保留
#     """语音反馈助手"""
#
#     def __init__(self, enabled: bool = True, tts_rate: int = 160):
#         self._enabled = enabled
#         self._tts_rate = tts_rate
#         self._tts = None
#         self._last_announce: float = 0.0
#         self._last_alert: float = 0.0
#         self._milestone_announced: Set[int] = set()
#         self._prev_score: Optional[float] = None
#
#         if enabled:
#             try:
#                 from calibration.audio.tts import TTS
#                 self._tts = TTS(rate=tts_rate)
#                 logger.info("语音助手已初始化")
#             except Exception as e:
#                 logger.warning("语音助手初始化失败，将静默运行: %s", e)
#                 self._tts = None
#
#     def on_tick(self, focus_score: float = 50.0, fatigue_level: Optional[str] = None,
#                 session_minutes: float = 0.0, face_detected: bool = True) -> None:
#         ...
#
#     def say(self, text: str) -> None:
#         ...
#
#     def _say(self, text: str) -> None:
#         ...
#
#     def set_enabled(self, enabled: bool) -> None:
#         ...
#
#     @property
#     def is_enabled(self) -> bool:
#         return self._enabled
#
#     def shutdown(self) -> None:
#         ...


def create_voice_assistant(enabled: bool = True):
    """v4.49+: 返回空存根（语音已移除）"""
    return VoiceAssistant(enabled=enabled)

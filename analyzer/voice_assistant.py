"""
analyzer/voice_assistant.py — 语音反馈助手 (v4.17)

复用 calibration/audio/tts.py 的 TTS 封装，在监测过程中提供：
  - 定时播报专注度（每 120s）
  - 专注度骤降预警
  - 疲劳提醒
  - 专注里程碑（30/60/90 分钟）

所有发音在 daemon 线程中执行，不阻塞主循环。
初始化失败时静默降级。
"""

import logging
import time
from typing import Optional, Set

logger = logging.getLogger("eyefocus.analyzer")


class VoiceAssistant:
    """语音反馈助手

    由 main.py 的 _qt_process_frame 每帧调用 on_tick()，
    内部做时间门控，不刷屏。

    Args:
        enabled: 是否启用语音
        tts_rate: 语速 (默认 160, 比校准模块稍慢更自然)
    """

    def __init__(self, enabled: bool = True, tts_rate: int = 160):
        self._enabled = enabled
        self._tts = None
        self._last_announce: float = 0.0
        self._last_alert: float = 0.0
        self._milestone_announced: Set[int] = set()
        self._prev_score: Optional[float] = None

        # 延迟初始化 TTS（避免 import 时 pyttsx3 初始化失败影响启动）
        if enabled:
            try:
                from calibration.audio.tts import TTS
                self._tts = TTS(rate=tts_rate)
                logger.info("语音助手已初始化")
            except Exception as e:
                logger.warning("语音助手初始化失败，将静默运行: %s", e)
                self._tts = None

    def on_tick(self, focus_score: float, fatigue_level: Optional[str] = None,
                session_minutes: float = 0.0, face_detected: bool = True) -> None:
        """每帧调用，内部按条件门控发音

        Args:
            focus_score: 当前专注度 (0-100)
            fatigue_level: 疲劳等级 ("LOW"/"MEDIUM"/"HIGH" 或 None)
            session_minutes: 会话已进行分钟数
            face_detected: 是否检测到人脸
        """
        if not self._enabled or self._tts is None:
            self._prev_score = focus_score
            return

        if not face_detected:
            return

        now = time.time()

        # 1. 专注度骤降预警（一次下降 > 20 分）
        if self._prev_score is not None:
            drop = self._prev_score - focus_score
            if drop > 20 and focus_score < 60:
                if now - self._last_alert >= 30:
                    self._last_alert = now
                    self._say("检测到分心，请重新集中注意力")

        self._prev_score = focus_score

        # 2. 疲劳预警
        fatigue_high = fatigue_level in ("HIGH", "TIRED", "high", "tired")
        if fatigue_high and focus_score < 50:
            if now - self._last_alert >= 60:
                self._last_alert = now
                self._say("检测到疲劳，建议休息十分钟")

        # 3. 专注里程碑（仅首次到达时）
        for ms in (30, 60, 90, 120):
            if session_minutes >= ms and ms not in self._milestone_announced:
                self._milestone_announced.add(ms)
                self._say(f"您已专注{ms}分钟，继续保持")

        # 4. 定期播报（每 120s）
        if now - self._last_announce >= 120:
            self._last_announce = now
            score_int = int(round(focus_score))
            if focus_score >= 70:
                self._say(f"当前专注度{score_int}分，状态良好")
            elif focus_score >= 40:
                self._say(f"当前专注度{score_int}分，请注意保持")
            else:
                self._say(f"当前专注度{score_int}分，检测到分心")

    def say(self, text: str) -> None:
        """主动触发语音播报（外部调用用）"""
        if self._enabled and self._tts is not None:
            self._say(text)

    def _say(self, text: str) -> None:
        """直接调用 TTS（内部统一入口）"""
        if self._tts is not None:
            self._tts.say(text)

    def set_enabled(self, enabled: bool) -> None:
        """动态启用/禁用语音"""
        if enabled and self._tts is None:
            try:
                from calibration.audio.tts import TTS
                self._tts = TTS(rate=160)
            except Exception:
                self._tts = None
        self._enabled = enabled

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def shutdown(self) -> None:
        """关闭 TTS 引擎"""
        if self._tts is not None:
            try:
                self._tts.shutdown()
            except Exception:
                pass
            self._tts = None
        logger.info("语音助手已关闭")


def create_voice_assistant(enabled: bool = True) -> VoiceAssistant:
    """工厂函数"""
    return VoiceAssistant(enabled=enabled)

"""
analyzer/reminder_engine.py — 智能主动提醒引擎 (v4.26)

在工作过程中主动检测各种条件，通过托盘气泡和/或语音给出提醒。

提醒类型：
  1. 专注里程碑 — 30/60/90 分钟节点提醒
  2. 建议休息 — 长时间工作后注意力下降
  3. 频繁分心 — 短时间多次状态切换
  4. 疲劳自适应 — 高疲劳缩短冷却，低疲劳延长冷却

v4.26 新增：
  - snooze: 5 分钟静音
  - 深度工作时段 (silent_hours)
  - 疲劳等级自适应冷却间隔
"""

import logging
import time
from typing import Optional, Set, Tuple

logger = logging.getLogger("eyefocus.analyzer")


class ReminderEngine:
    """智能提醒引擎

    由 main.py 的 _qt_process_frame 每帧调用 check()，
    内部做时间门控。

    Args:
        tray_callback: 托盘通知回调 function(title, message)
        voice_callback: 语音播报回调 function(text)
    """

    def __init__(self, tray_callback=None, voice_callback=None):
        self._tray = tray_callback
        self._voice = voice_callback

        # 冷却追踪
        self._last_notify_time: float = 0.0
        self._notify_cooldown: float = 120.0  # 两次提醒最短间隔
        self._milestones_shown: Set[int] = set()
        self._last_break_suggest: float = 0.0
        self._break_cooldown: float = 300.0   # 建议休息 5 分钟冷却

        # 分心追踪
        self._prev_level: Optional[str] = None
        self._distract_count: int = 0
        self._last_distract_time: float = 0.0
        self._distract_window: float = 300.0  # 5 分钟窗口
        self._first_distract_time: float = 0.0

        # v4.26: snooze
        self._snoozed_until: float = 0.0

        # v4.26: 深度工作时段 (silent_hours)
        self._silent_start: Optional[Tuple[int, int]] = None  # (hour, min)
        self._silent_end: Optional[Tuple[int, int]] = None

    # ── v4.26: Snooze ──

    def snooze(self, minutes: int = 5) -> None:
        """静音提醒 minutes 分钟"""
        self._snoozed_until = time.time() + minutes * 60
        logger.info("提醒已 snooze %d 分钟", minutes)

    def cancel_snooze(self) -> None:
        """取消 snooze"""
        self._snoozed_until = 0.0

    # ── v4.26: 深度工作时段 ──

    def set_silent_hours(self, start: Optional[Tuple[int, int]],
                         end: Optional[Tuple[int, int]]) -> None:
        """设置静音时段，此期间不弹提醒

        Args:
            start: (hour, min) 如 (9, 0) 表示 9:00
            end:   (hour, min) 如 (11, 0) 表示 11:00
        """
        self._silent_start = start
        self._silent_end = end

    def _in_silent_hours(self) -> bool:
        """当前是否在深度工作时段内"""
        if self._silent_start is None or self._silent_end is None:
            return False
        now = time.localtime()
        now_m = now.tm_hour * 60 + now.tm_min
        start_m = self._silent_start[0] * 60 + self._silent_start[1]
        end_m = self._silent_end[0] * 60 + self._silent_end[1]
        if start_m < end_m:
            return start_m <= now_m < end_m
        else:
            # 跨天
            return now_m >= start_m or now_m < end_m

    def check(self, focus_score: float, focus_level: Optional[str] = None,
              fatigue_level: Optional[str] = None,
              session_minutes: float = 0.0, face_detected: bool = True) -> None:
        """每帧调用，检测条件并触发提醒

        Args:
            focus_score: 当前专注度 (0-100)
            focus_level: 专注等级 ("focused"/"normal"/"distracted")
            fatigue_level: 疲劳等级 ("LOW"/"MEDIUM"/"HIGH" 或 None)
            session_minutes: 会话已进行分钟数
            face_detected: 是否检测到人脸
        """
        if not face_detected:
            return

        now = time.time()

        # ── v4.26: snooze 期间不弹提醒 ──
        if now < self._snoozed_until:
            return

        # ── v4.26: 深度工作时段不弹提醒 ──
        if self._in_silent_hours():
            return

        # v4.26: 疲劳等级自适应冷却
        if fatigue_level == "HIGH":
            effective_cooldown = 60.0   # 高疲劳 → 缩短到 1 分钟
        elif fatigue_level == "MEDIUM":
            effective_cooldown = 90.0   # 中疲劳 → 1.5 分钟
        else:
            effective_cooldown = self._notify_cooldown

        # 全局冷却
        if now - self._last_notify_time < effective_cooldown:
            self._track_distraction(focus_level, now)
            return

        # 1. 专注里程碑 (30/60/90 分钟)
        for ms in (30, 60, 90):
            if session_minutes >= ms and ms not in self._milestones_shown:
                self._milestones_shown.add(ms)
                self._notify("milestone", f"🎯 已专注 {int(session_minutes)} 分钟",
                             f"您已专注 {int(session_minutes)} 分钟，继续保持！")
                return  # 一次只触发一个提醒

        # 2. 建议休息（超过 60 分钟 + 专注度偏低）
        if session_minutes >= 60 and focus_score < 65:
            if now - self._last_break_suggest >= self._break_cooldown:
                self._last_break_suggest = now
                self._notify("break", "💤 建议休息",
                             f"已持续工作 {int(session_minutes)} 分钟，专注度下降。建议短暂休息 5-10 分钟。")
                return

        # 3. 频繁分心（5 分钟内 >= 3 次状态切换为 distracted）
        self._track_distraction(focus_level, now)
        if self._distract_count >= 3:
            elapsed = now - self._first_distract_time
            if elapsed <= self._distract_window:
                self._notify("distraction", "🔄 频繁分心",
                             f"过去 {int(elapsed//60)} 分钟内分心 {self._distract_count} 次，" +
                             "是否需要调整工作环境？")
                # 重置计数器
                self._distract_count = 0
                return

        # v4.26: 移除"监测已稳定"弹窗

    def _track_distraction(self, focus_level: Optional[str], now: float) -> None:
        """跟踪专注度切换为 distracted 的次数"""
        if focus_level is None:
            return

        is_distracted = (focus_level.upper() == "DISTRACTED")
        was_normal = (self._prev_level is not None and
                      self._prev_level.upper() != "DISTRACTED")

        if is_distracted and was_normal:
            # 重置过期的计数
            if now - self._last_distract_time > self._distract_window:
                self._distract_count = 0
                self._first_distract_time = now
            elif self._distract_count == 0:
                self._first_distract_time = now

            self._distract_count += 1
            self._last_distract_time = now

        self._prev_level = focus_level

    def _notify(self, notify_type: str, title: str, message: str) -> None:
        """发送通知（托盘 + 语音）"""
        self._last_notify_time = time.time()
        logger.info("提醒 [%s]: %s — %s", notify_type, title, message)

        if self._tray:
            try:
                self._tray(title, message)
            except Exception:
                pass

        if self._voice:
            try:
                self._voice(message)
            except Exception:
                pass

    def reset(self) -> None:
        """重置所有追踪状态（新会话时调用）"""
        self._milestones_shown.clear()
        self._distract_count = 0
        self._first_distract_time = 0.0
        self._last_notify_time = 0.0
        self._last_break_suggest = 0.0
        self._prev_level = None
        self._snoozed_until = 0.0


def create_reminder_engine(tray_callback=None, voice_callback=None) -> ReminderEngine:
    """工厂函数"""
    return ReminderEngine(tray_callback=tray_callback, voice_callback=voice_callback)

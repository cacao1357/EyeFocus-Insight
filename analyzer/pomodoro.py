"""
analyzer/pomodoro.py — 番茄工作法引擎 (v4.18)

状态机: IDLE → WORKING(25min) → BREAK(5min) → WORKING → ...

与主程序联动：
- WORKING 开始时：自动取消暂停监测
- BREAK 开始时：自动暂停监测 + 语音提醒
- 每完成一个番茄：计数 +1
"""

import logging
import time
from typing import Optional, Callable

logger = logging.getLogger("eyefocus.analyzer")


class PomodoroEngine:
    """番茄工作法引擎

    纯逻辑，不依赖 GUI。通过回调与主程序交互。
    """

    # 默认时长（分钟）
    WORK_MINUTES = 25
    BREAK_MINUTES = 5
    LONG_BREAK_MINUTES = 15
    SESSIONS_BEFORE_LONG_BREAK = 4

    def __init__(self,
                 voice_callback: Optional[Callable[[str], None]] = None,
                 pause_callback: Optional[Callable[[], None]] = None,
                 resume_callback: Optional[Callable[[], None]] = None,
                 notify_callback: Optional[Callable[[str, str], None]] = None):
        # self._voice = voice_callback  # v4.49+: 语音已移除
        self._voice = None
        self._pause_cb = pause_callback
        self._resume_cb = resume_callback
        self._notify = notify_callback

        self._state = "IDLE"        # IDLE / WORKING / BREAK / PAUSED
        self._paused: bool = False
        self._elapsed: float = 0.0  # 当前阶段已过秒数
        self._duration: float = self.WORK_MINUTES * 60.0
        self._work_minutes: int = self.WORK_MINUTES
        self._break_minutes: int = self.BREAK_MINUTES
        self._count: int = 0        # 今日番茄数
        self._session_count: int = 0  # 连续番茄数
        self._last_tick: Optional[float] = None
        self._started: bool = False

    def start(self) -> None:
        """开始一个番茄"""
        if self._state == "IDLE":
            self._state = "WORKING"
            self._paused = False
            self._elapsed = 0.0
            self._duration = self._work_minutes * 60.0
            self._last_tick = time.time()
            self._started = True
            logger.info("🍅 番茄开始 (%d 分钟)", self._work_minutes)
            if self._notify:
                self._notify("🍅 番茄开始", f"专注工作 {self._work_minutes} 分钟")
            # if self._voice:                        # v4.49+: 语音已移除
            #     self._voice(f"番茄开始，专注工作{self._work_minutes}分钟")
            if self._resume_cb:
                self._resume_cb()

    def pause(self) -> None:
        """暂停当前番茄"""
        if self._state in ("WORKING", "BREAK") and not self._paused:
            self._paused = True
            logger.info("🍅 番茄已暂停")
            # if self._voice:                        # v4.49+: 语音已移除
            #     self._voice("番茄已暂停")

    def resume(self) -> None:
        """继续当前番茄"""
        if self._paused:
            self._paused = False
            self._last_tick = time.time()
            logger.info("🍅 番茄已继续")
            # if self._voice:                        # v4.49+: 语音已移除
            #     label = "工作" if self._state == "WORKING" else "休息"
            #     self._voice(f"{label}继续")

    def set_duration(self, work_minutes: int, break_minutes: int) -> None:
        """自定义工作/休息时长（运行时立即生效）"""
        self._work_minutes = max(1, min(120, work_minutes))
        self._break_minutes = max(1, min(60, break_minutes))
        logger.info("🍅 番茄时间已设置: 工作%d分, 休息%d分",
                     self._work_minutes, self._break_minutes)
        if self._state == "WORKING":
            self._duration = self._work_minutes * 60.0
            if self._elapsed >= self._duration:
                self._elapsed = self._duration - 1  # 防立即结束
        elif self._state == "BREAK":
            self._duration = self._break_minutes * 60.0
            if self._elapsed >= self._duration:
                self._elapsed = self._duration - 1
        else:
            self._duration = self._work_minutes * 60.0

    def stop(self) -> None:
        """停止当前番茄"""
        if self._state != "IDLE":
            old = self._state
            self._state = "IDLE"
            self._elapsed = 0.0
            self._started = False
            logger.info("🍅 番茄已停止 (%s)", old)
            # if self._voice:                        # v4.49+: 语音已移除
            #     self._voice("番茄已停止")

    def tick(self) -> None:
        """每秒调用一次，更新时间并检查状态切换"""
        now = time.time()
        # 首次调用或时钟回跳保护
        if self._last_tick is None:
            self._last_tick = now
            return
        dt = now - self._last_tick
        dt = max(0.0, min(dt, 60.0))  # 防护：最多按 60s 计算（防时钟回跳/大跳跃）
        self._last_tick = now

        if self._state == "IDLE":
            return

        if self._paused:
            return  # 暂停不计时

        self._elapsed += dt

        if self._elapsed >= self._duration:
            self._on_phase_end()

    def _on_phase_end(self) -> None:
        """当前阶段结束，切换到下一阶段"""
        if self._state == "WORKING":
            # 工作结束 → 休息
            self._count += 1
            self._session_count += 1
            is_long = (self._session_count % self.SESSIONS_BEFORE_LONG_BREAK == 0)
            break_min = self.LONG_BREAK_MINUTES if is_long else self.BREAK_MINUTES
            self._state = "BREAK"
            self._paused = False
            self._elapsed = 0.0
            self._duration = break_min * 60.0
            logger.info("🍅 番茄完成! 第 %d 个 (休息 %d 分钟)", self._count, break_min)
            if self._notify:
                self._notify("🍅 番茄完成", f"休息 {break_min} 分钟")
            # if self._voice:                        # v4.49+: 语音已移除
            #     self._voice(f"番茄完成！休息{break_min}分钟")
            if self._pause_cb:
                self._pause_cb()
        elif self._state == "BREAK":
            # 休息结束 → 工作
            self._state = "WORKING"
            self._paused = False
            self._elapsed = 0.0
            self._duration = self._work_minutes * 60.0
            logger.info("🍅 休息结束，开始第 %d 个番茄", self._count + 1)
            if self._notify:
                self._notify("🍅 休息结束", "开始新的番茄")
            # if self._voice:                        # v4.49+: 语音已移除
            #     self._voice("休息结束，开始新的番茄")
            if self._resume_cb:
                self._resume_cb()

    def get_status(self) -> dict:
        """获取当前状态（供 UI 显示）

        Returns:
            dict with: state, count, remaining_sec, elapsed_sec, total_sec,
                       progress, paused, work_min, break_min
        """
        remaining = max(0.0, self._duration - self._elapsed)
        return {
            "state": self._state,
            "count": self._count,
            "remaining_sec": int(remaining),
            "elapsed_sec": int(self._elapsed),
            "total_sec": int(self._duration),
            "progress": min(1.0, self._elapsed / max(1, self._duration)),
            "paused": self._paused,
            "work_min": self._work_minutes,
            "break_min": self._break_minutes,
        }

    @property
    def state(self) -> str:
        return self._state

    @property
    def count(self) -> int:
        return self._count

    def set_count(self, n: int) -> None:
        """设置番茄计数（供外部恢复用）"""
        self._count = n


def create_pomodoro_engine(voice_callback=None,
                           pause_callback=None,
                           resume_callback=None,
                           notify_callback=None) -> PomodoroEngine:
    """工厂函数"""
    return PomodoroEngine(
        voice_callback=voice_callback,
        pause_callback=pause_callback,
        resume_callback=resume_callback,
        notify_callback=notify_callback,
    )

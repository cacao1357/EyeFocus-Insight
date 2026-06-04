"""calibration/phases/head_pose.py — 阶段 3 头部姿态校准

4 个子阶段（抬头/低头/左转/右转）各独立 3s + 独立 TTS 指令。
解决 BUG 4：原 T148 不告诉用户当前子阶段，导致数据全是垃圾。

设计依据：spec §2.2（头部姿态拆 4 子阶段）+ §4.3。
"""
import math
import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from calibration.phases.base import LiveFeedback, Phase, PhaseResult

logger = logging.getLogger("eyefocus.calibration.phases")


class HeadDirection(Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True)
class HeadSubPhase:
    direction: HeadDirection
    tts: str
    hint: str


class HeadPosePhase(Phase):
    name = "头部姿态校准"
    # T-CAL-25: 4 个子阶段改为 click-to-advance, tts_intro 简短
    tts_intro = "请按提示依次做 4 个头部动作，每完成 1 个点继续"
    tts_complete = "头部姿态采集完成"

    def __init__(self, direction_seconds: float, min_degrees: float):
        self.direction_seconds = direction_seconds
        # T-CAL-25: 实际跑 4 秒, 给用户充足转头时间
        self.per_direction_seconds: float = 4.0
        self.duration_seconds = self.per_direction_seconds * 4
        self.min_degrees = min_degrees
        self.sub_phases: List[HeadSubPhase] = [
            HeadSubPhase(HeadDirection.UP,    "现在抬头",            "请抬头 (保持 4 秒)"),
            HeadSubPhase(HeadDirection.DOWN,  "现在低头",            "请低头 (保持 4 秒)"),
            HeadSubPhase(HeadDirection.LEFT,  "现在向左转",          "请向左转头 (保持 4 秒)"),
            HeadSubPhase(HeadDirection.RIGHT, "现在向右转",          "请向右转头 (保持 4 秒)"),
        ]
        # max 记录极值（pitch 抬头是负，低头是正；yaw 左是负，右是正）
        self._pitch_up_max: float = 0.0      # 越负越好
        self._pitch_down_max: float = 0.0    # 越正越好
        self._yaw_left_max: float = 0.0      # 越负越好
        self._yaw_right_max: float = 0.0     # 越正越好
        # T-CAL-16: 缓存最近 yaw/pitch, 供屏幕显示
        self._yaw_last: float = 0.0
        self._pitch_last: float = 0.0
        # T-CAL-22: 跟踪上一 sub_phase index, 3 秒静默自动提示
        self._last_sub_idx: int = -1
        self._stuck_counter: int = 0  # 帧计数, 头部不动时累加
        # T-CAL-25: 跟踪当前 sub_phase, click-to-advance 模式
        self._current_sub_idx: int = 0

    def reset(self) -> None:
        self._pitch_up_max = 0.0
        self._pitch_down_max = 0.0
        self._yaw_left_max = 0.0
        self._yaw_right_max = 0.0
        self._yaw_last = 0.0
        self._pitch_last = 0.0
        self._last_sub_idx = -1
        self._stuck_counter = 0
        self._current_sub_idx = 0

    def current_sub_phase(self, elapsed_sec: float) -> HeadSubPhase:
        # T-CAL-25: click-to-advance, 按 _current_sub_idx 而不是 elapsed
        idx = min(self._current_sub_idx, 3)
        return self.sub_phases[idx]

    def is_current_sub_done(self) -> bool:
        """T-CAL-25: click-to-advance, 始终返回 False (永远不停, 等用户点继续)。"""
        return False

    def advance_sub_phase(self) -> bool:
        """T-CAL-25: 用户点继续后调用, 推进到下一 sub-phase。

        Returns: True 如果还有下一 sub-phase, False 如果全部完成。
        """
        self._current_sub_idx += 1
        if self._current_sub_idx >= 4:
            return False
        # 重置检测状态
        self._yaw_last = 0.0
        self._pitch_last = 0.0
        self._stuck_counter = 0
        return True

    def is_complete(self, elapsed_sec: float) -> bool:
        """T-CAL-25: 全部 4 sub-phase 完成后才结束 (而非 timer)。"""
        return self._current_sub_idx >= 4

    def feed_frame(self, ear, yaw, pitch, timestamp) -> None:
        if yaw is None or pitch is None:
            return
        # T-CAL-16: cache last values for live display
        self._yaw_last = yaw
        self._pitch_last = pitch

        sub = self.current_sub_phase(timestamp)
        if sub.direction == HeadDirection.UP and pitch < self._pitch_up_max:
            self._pitch_up_max = pitch
        elif sub.direction == HeadDirection.DOWN and pitch > self._pitch_down_max:
            self._pitch_down_max = pitch
        elif sub.direction == HeadDirection.LEFT and yaw < self._yaw_left_max:
            self._yaw_left_max = yaw
        elif sub.direction == HeadDirection.RIGHT and yaw > self._yaw_right_max:
            self._yaw_right_max = yaw

        # T-CAL-29 调试日志: 每秒 (30 帧) 打印当前 sub_idx + max values
        if not hasattr(self, '_log_counter'):
            self._log_counter = 0
        self._log_counter += 1
        if self._log_counter % 30 == 0:
            import logging
            logger = logging.getLogger("eyefocus.calibration.phases")
            logger.info(
                "[T-CAL-29] sub_idx=%d yaw=%.1f pitch=%.1f | max: pitch_up=%.1f pitch_down=%.1f yaw_L=%.1f yaw_R=%.1f | thr=%.1f",
                self._current_sub_idx, yaw, pitch,
                self._pitch_up_max, self._pitch_down_max,
                self._yaw_left_max, self._yaw_right_max,
                self.min_degrees,
            )

        # T-CAL-16: 检测头部是否在动 (与上次差异 < 5°)
        # T-CAL-22: 2°→5° (宽松, 避免用户慢慢转头时误判 stuck)
        if abs(self._yaw_last - getattr(self, '_prev_yaw', 0.0)) < 5.0 and \
           abs(self._pitch_last - getattr(self, '_prev_pitch', 0.0)) < 5.0:
            self._stuck_counter += 1
        else:
            self._stuck_counter = 0
        self._prev_yaw = self._yaw_last
        self._prev_pitch = self._pitch_last

    def is_stuck(self) -> bool:
        """T-CAL-16/22: 头部不动 1.5 秒才判 stuck (45 帧 @ 30fps)"""
        return self._stuck_counter > 45

    def get_live_feedback(self, elapsed_sec: float) -> LiveFeedback:
        sub = self.current_sub_phase(elapsed_sec)
        remaining = max(0.0, self.duration_seconds - elapsed_sec)
        # T-CAL-16: quality_hint 加实时 yaw/pitch + 阈值 (用户能调整头部角度)
        hint = f"{sub.hint} | yaw={self._yaw_last:.1f}° pitch={self._pitch_last:.1f}° | 阈值≥{self.min_degrees}°"
        if self.is_stuck():
            hint += " ⚠️ 头部未动, 请尽量大幅度"
        return LiveFeedback(
            remaining_sec=remaining,
            sample_count=0,
            quality_hint=hint,
            current_yaw=self._yaw_last,
            current_pitch=self._pitch_last,
            threshold_yaw=self.min_degrees,
        )

    def evaluate(self) -> PhaseResult:
        thr = self.min_degrees
        failures = []
        if abs(self._pitch_up_max) < thr:
            failures.append(("抬头", abs(self._pitch_up_max)))
        if abs(self._pitch_down_max) < thr:
            failures.append(("低头", abs(self._pitch_down_max)))
        if abs(self._yaw_left_max) < thr:
            failures.append(("向左转", abs(self._yaw_left_max)))
        if abs(self._yaw_right_max) < thr:
            failures.append(("向右转", abs(self._yaw_right_max)))

        summary = {
            "pitch_up_max": self._pitch_up_max,
            "pitch_down_max": self._pitch_down_max,
            "yaw_left_max": self._yaw_left_max,
            "yaw_right_max": self._yaw_right_max,
            "min_degrees_required": thr,
        }

        if failures:
            failed_names = "、".join(name for name, _ in failures)
            return PhaseResult(
                success=False, summary=summary,
                failure_reason="head_direction_insufficient",
                failure_diagnosis=f"{failed_names} 转动幅度不够（需 ≥ {thr}°），请大一点动作后重做",
            )
        return PhaseResult(success=True, summary=summary)

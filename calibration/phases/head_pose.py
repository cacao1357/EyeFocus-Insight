"""calibration/phases/head_pose.py — 阶段 3 头部姿态校准

4 个子阶段（抬头/低头/左转/右转）各独立 3s + 独立 TTS 指令。
解决 BUG 4：原 T148 不告诉用户当前子阶段，导致数据全是垃圾。

设计依据：spec §2.2（头部姿态拆 4 子阶段）+ §4.3。
"""
import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from calibration.phases.base import LiveFeedback, Phase, PhaseResult


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
    # T-CAL-16: tts_intro 加"请尽量大幅度"
    tts_intro = "接下来请按提示移动头部，4 个方向各 3 秒，请尽量大幅度"
    tts_complete = "头部姿态采集完成"

    def __init__(self, direction_seconds: float, min_degrees: float):
        self.direction_seconds = direction_seconds
        self.duration_seconds = direction_seconds * 4
        self.min_degrees = min_degrees
        # T-CAL-16: hint 加"保持 3 秒"提示
        self.sub_phases: List[HeadSubPhase] = [
            HeadSubPhase(HeadDirection.UP,    "现在抬头",            "请抬头 (保持 3 秒)"),
            HeadSubPhase(HeadDirection.DOWN,  "现在低头",            "请低头 (保持 3 秒)"),
            HeadSubPhase(HeadDirection.LEFT,  "现在向左转",          "请向左转头 (保持 3 秒)"),
            HeadSubPhase(HeadDirection.RIGHT, "现在向右转",          "请向右转头 (保持 3 秒)"),
        ]
        # max 记录极值（pitch 抬头是负，低头是正；yaw 左是负，右是正）
        self._pitch_up_max: float = 0.0      # 越负越好
        self._pitch_down_max: float = 0.0    # 越正越好
        self._yaw_left_max: float = 0.0      # 越负越好
        self._yaw_right_max: float = 0.0     # 越正越好
        # T-CAL-16: 缓存最近 yaw/pitch, 供屏幕显示
        self._yaw_last: float = 0.0
        self._pitch_last: float = 0.0
        # T-CAL-16: 跟踪上一 sub_phase index, 3 秒静默自动提示
        self._last_sub_idx: int = -1
        self._stuck_counter: int = 0  # 帧计数, 头部不动时累加

    def reset(self) -> None:
        self._pitch_up_max = 0.0
        self._pitch_down_max = 0.0
        self._yaw_left_max = 0.0
        self._yaw_right_max = 0.0
        self._yaw_last = 0.0
        self._pitch_last = 0.0
        self._last_sub_idx = -1
        self._stuck_counter = 0

    def current_sub_phase(self, elapsed_sec: float) -> HeadSubPhase:
        idx = min(int(elapsed_sec // self.direction_seconds), 3)
        return self.sub_phases[idx]

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

        # T-CAL-16: 检测头部是否在动 (与上次差异 < 2°)
        if abs(self._yaw_last - getattr(self, '_prev_yaw', 0.0)) < 2.0 and \
           abs(self._pitch_last - getattr(self, '_prev_pitch', 0.0)) < 2.0:
            self._stuck_counter += 1
        else:
            self._stuck_counter = 0
        self._prev_yaw = self._yaw_last
        self._prev_pitch = self._pitch_last

    def is_stuck(self) -> bool:
        """T-CAL-16: 是否头部不动 (1.5 秒无变化 @ 30fps = 45 帧)"""
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

    def is_complete(self, elapsed_sec: float) -> bool:
        return elapsed_sec >= self.duration_seconds

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

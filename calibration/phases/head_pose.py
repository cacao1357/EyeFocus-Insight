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
    tts_intro = "接下来请按照语音提示移动头部，每个方向 3 秒"
    tts_complete = "头部姿态采集完成"

    def __init__(self, direction_seconds: float, min_degrees: float):
        self.direction_seconds = direction_seconds
        self.duration_seconds = direction_seconds * 4
        self.min_degrees = min_degrees
        self.sub_phases: List[HeadSubPhase] = [
            HeadSubPhase(HeadDirection.UP, "现在抬头", "请抬头"),
            HeadSubPhase(HeadDirection.DOWN, "现在低头", "请低头"),
            HeadSubPhase(HeadDirection.LEFT, "现在向左转", "请向左转头"),
            HeadSubPhase(HeadDirection.RIGHT, "现在向右转", "请向右转头"),
        ]
        # max 记录极值（pitch 抬头是负，低头是正；yaw 左是负，右是正）
        self._pitch_up_max: float = 0.0      # 越负越好
        self._pitch_down_max: float = 0.0    # 越正越好
        self._yaw_left_max: float = 0.0      # 越负越好
        self._yaw_right_max: float = 0.0     # 越正越好

    def reset(self) -> None:
        self._pitch_up_max = 0.0
        self._pitch_down_max = 0.0
        self._yaw_left_max = 0.0
        self._yaw_right_max = 0.0

    def current_sub_phase(self, elapsed_sec: float) -> HeadSubPhase:
        idx = min(int(elapsed_sec // self.direction_seconds), 3)
        return self.sub_phases[idx]

    def feed_frame(self, ear, yaw, pitch, timestamp) -> None:
        if yaw is None or pitch is None:
            return
        sub = self.current_sub_phase(timestamp)
        if sub.direction == HeadDirection.UP and pitch < self._pitch_up_max:
            self._pitch_up_max = pitch
        elif sub.direction == HeadDirection.DOWN and pitch > self._pitch_down_max:
            self._pitch_down_max = pitch
        elif sub.direction == HeadDirection.LEFT and yaw < self._yaw_left_max:
            self._yaw_left_max = yaw
        elif sub.direction == HeadDirection.RIGHT and yaw > self._yaw_right_max:
            self._yaw_right_max = yaw

    def get_live_feedback(self, elapsed_sec: float) -> LiveFeedback:
        sub = self.current_sub_phase(elapsed_sec)
        remaining = max(0.0, self.duration_seconds - elapsed_sec)
        return LiveFeedback(
            remaining_sec=remaining,
            sample_count=0,  # 头部姿态不显示样本数，显示方向提示
            quality_hint=sub.hint,
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

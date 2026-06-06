"""calibration/phases/blink_count.py — 阶段 4 眨眼计数（2 轮 + 用户输入）

每帧调用 feed_frame 检测眨眼（BUG 1 修复：原 T148 仅每秒采样导致漏检 95%+）。
每轮结束等待用户输入实际眨眼数 → 计算 adjustment_factor。

设计依据：spec §2.2 + §3.2 BlinkCount 特殊流程。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from calibration.phases.base import LiveFeedback, Phase, PhaseResult
from calibration.result import BlinkCalibrationRound


class BlinkCountState(Enum):
    COUNTING = "counting"
    WAITING_INPUT = "waiting_input"
    DONE = "done"


# 眨眼/眯眼判定时间阈值（与 EyeAspectDetector 一致）
BLINK_MAX_DURATION_SEC = 0.4


class BlinkCountPhase(Phase):
    name = "眨眼计数校准"
    tts_intro = "请自然眨眼，结束后告诉我你眨了多少次"
    tts_complete = "眨眼记录完成"

    def __init__(
        self,
        round_seconds: float,
        rounds: int,
        baseline_ear: float,
        ear_min: float,
        count_min: int,
        count_max: int,
    ):
        self.round_seconds = round_seconds
        self.rounds = rounds
        self.duration_seconds = round_seconds * rounds
        self.baseline_ear = baseline_ear
        self.ear_min = ear_min
        self.count_min = count_min
        self.count_max = count_max
        # 阈值（同 spec §6.8 阶段一）
        self.blink_threshold = baseline_ear * 0.75   # 0.225
        self.squint_threshold = baseline_ear * 0.90  # 0.27

        self.current_round = 1
        self.state = BlinkCountState.COUNTING

        # 当前轮检测器内部状态
        self._in_eye_closed: bool = False
        self._close_start_t: Optional[float] = None
        self._round_blinks: int = 0
        self._round_squints: int = 0

        # 完成的轮次
        self._completed_rounds: List[BlinkCalibrationRound] = []

    def reset(self) -> None:
        self.current_round = 1
        self.state = BlinkCountState.COUNTING
        self._in_eye_closed = False
        self._close_start_t = None
        self._round_blinks = 0
        self._round_squints = 0
        self._completed_rounds.clear()

    def feed_frame(self, ear, yaw, pitch, timestamp) -> None:
        if ear is None or self.state != BlinkCountState.COUNTING:
            return

        if ear < self.blink_threshold:
            if not self._in_eye_closed:
                self._in_eye_closed = True
                self._close_start_t = timestamp
        else:
            if self._in_eye_closed and self._close_start_t is not None:
                duration = timestamp - self._close_start_t
                if duration < BLINK_MAX_DURATION_SEC:
                    self._round_blinks += 1
                else:
                    self._round_squints += 1
                self._in_eye_closed = False
                self._close_start_t = None

    def get_live_feedback(self, elapsed_sec: float) -> LiveFeedback:
        round_elapsed = elapsed_sec - (self.current_round - 1) * self.round_seconds
        remaining = max(0.0, self.round_seconds - round_elapsed)
        return LiveFeedback(
            remaining_sec=remaining,
            sample_count=self._round_blinks,
            quality_hint=f"第 {self.current_round}/{self.rounds} 轮 - 已检出 {self._round_blinks} 次",
        )

    def get_round_detected_blinks(self) -> int:
        return self._round_blinks

    def get_round_detected_squints(self) -> int:
        return self._round_squints

    def on_round_time_up(self) -> None:
        """flow.py 在每轮 15s 到点时调用。"""
        if self.state != BlinkCountState.COUNTING:
            return
        self.state = BlinkCountState.WAITING_INPUT

    def on_user_input(self, user_count: int) -> bool:
        """flow.py 在收到用户输入数字后调用。返回 False 表示输入超范围。"""
        if self.state != BlinkCountState.WAITING_INPUT:
            return False
        if not (self.count_min <= user_count <= self.count_max):
            return False

        program_count = self._round_blinks
        error_rate = (
            (user_count - program_count) / user_count if user_count > 0 else 0.0
        )
        adjustment = max(0.7, min(1.3, 1.0 + error_rate))

        self._completed_rounds.append(BlinkCalibrationRound(
            round_index=self.current_round,
            duration_seconds=int(self.round_seconds),
            user_blink_count=user_count,
            program_blink_count=program_count,
            program_squint_count=self._round_squints,
            error_rate=error_rate,
            adjustment_factor=adjustment,
        ))

        if self.current_round < self.rounds:
            self.current_round += 1
            self.state = BlinkCountState.COUNTING
            self._reset_round_counters()
        else:
            self.state = BlinkCountState.DONE
        return True

    def _reset_round_counters(self) -> None:
        self._in_eye_closed = False
        self._close_start_t = None
        self._round_blinks = 0
        self._round_squints = 0

    def is_complete(self, elapsed_sec: float) -> bool:
        return self.state == BlinkCountState.DONE

    def evaluate(self) -> PhaseResult:
        if len(self._completed_rounds) < self.rounds:
            return PhaseResult(
                success=False,
                summary={"completed_rounds": len(self._completed_rounds)},
                failure_reason="rounds_incomplete",
                failure_diagnosis=f"未完成 {self.rounds} 轮（已完成 {len(self._completed_rounds)}）",
            )

        factors = [r.adjustment_factor for r in self._completed_rounds]
        final_adj = sum(factors) / len(factors)
        total_user = sum(r.user_blink_count for r in self._completed_rounds)
        total_dur_min = sum(r.duration_seconds for r in self._completed_rounds) / 60.0
        baseline_blink_rate = total_user / total_dur_min if total_dur_min > 0 else 15.0

        return PhaseResult(
            success=True,
            summary={
                "rounds": list(self._completed_rounds),
                "final_adjustment_factor": final_adj,
                "baseline_blink_rate": baseline_blink_rate,
            },
        )

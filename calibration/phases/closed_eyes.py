"""calibration/phases/closed_eyes.py — 阶段 1 闭眼校准

5s 闭眼 → 采集 ear_min；3s 自动验证 EAR 回升到合理范围。
失败条件：ear_min > baseline_ear × min_ratio（未真正闭眼）。

设计依据：spec §2.2 + §4.3 + P2（合并睁眼回升验证到此阶段）。
"""
import math
from typing import List, Optional

from calibration.phases.base import LiveFeedback, Phase, PhaseResult


class ClosedEyesPhase(Phase):
    name = "闭眼校准"
    tts_intro = "请闭眼并保持 5 秒"
    tts_complete = "好，可以睁眼了"   # ← BUG 3 修复点：闭眼结束 TTS 明确告诉用户睁眼

    def __init__(
        self,
        closed_duration_seconds: float,
        verify_duration_seconds: float,
        baseline_ear: float,
        min_ratio: float,
    ):
        self.closed_duration_seconds = closed_duration_seconds
        self.verify_duration_seconds = verify_duration_seconds
        self.duration_seconds = closed_duration_seconds + verify_duration_seconds
        self.baseline_ear = baseline_ear
        self.min_ratio = min_ratio
        self._ear_min: float = math.inf
        self._closed_phase_samples: int = 0
        self._verify_phase_samples: int = 0
        self._verify_ear_sum: float = 0.0

    def reset(self) -> None:
        self._ear_min = math.inf
        self._closed_phase_samples = 0
        self._verify_phase_samples = 0
        self._verify_ear_sum = 0.0

    def feed_frame(self, ear, yaw, pitch, timestamp) -> None:
        if ear is None:
            return
        # 用 timestamp 来判断处于哪个子阶段：< closed_duration = 闭眼期
        if timestamp < self.closed_duration_seconds:
            if ear < self._ear_min:
                self._ear_min = ear
            self._closed_phase_samples += 1
        else:
            self._verify_phase_samples += 1
            self._verify_ear_sum += ear

    def get_live_feedback(self, elapsed_sec: float) -> LiveFeedback:
        remaining = max(0.0, self.duration_seconds - elapsed_sec)
        if elapsed_sec < self.closed_duration_seconds:
            hint = "闭眼中，请保持..."
            count = self._closed_phase_samples
        else:
            hint = "睁眼验证中..."
            count = self._verify_phase_samples
        return LiveFeedback(remaining_sec=remaining, sample_count=count, quality_hint=hint)

    def is_complete(self, elapsed_sec: float) -> bool:
        return elapsed_sec >= self.duration_seconds

    def evaluate(self) -> PhaseResult:
        if self._closed_phase_samples == 0:
            return PhaseResult(
                success=False, summary={},
                failure_reason="no_samples",
                failure_diagnosis="未采集到任何数据，请确认人脸在画面内",
            )

        ear_min = self._ear_min
        threshold = self.baseline_ear * self.min_ratio

        if ear_min > threshold:
            return PhaseResult(
                success=False,
                summary={"ear_min": ear_min, "threshold": threshold,
                         "closed_samples": self._closed_phase_samples},
                failure_reason="ear_min_too_high",
                failure_diagnosis=f"似乎没有完全闭眼（最低 EAR {ear_min:.3f}，需 < {threshold:.3f}），请用力闭眼后重做",
            )

        verify_ear_avg = (
            self._verify_ear_sum / self._verify_phase_samples
            if self._verify_phase_samples > 0 else 0.0
        )

        return PhaseResult(
            success=True,
            summary={
                "ear_min": ear_min,
                "verify_ear_avg": verify_ear_avg,
                "closed_samples": self._closed_phase_samples,
                "verify_samples": self._verify_phase_samples,
            },
        )

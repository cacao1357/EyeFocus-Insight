"""calibration/phases/squint.py — 阶段 2 眯眼校准

8s 采集眯眼 EAR，得到 ear_mid（眨眼/眯眼判定边界）。
判定有效区间：ear_min × 1.2 < ear_mid < baseline × baseline_ratio。

设计依据：spec §2.2 + §4.3。
"""
import statistics
from typing import List

from calibration.phases.base import LiveFeedback, Phase, PhaseResult


class SquintPhase(Phase):
    name = "眯眼校准"
    tts_intro = "请眯眼，眼睛留一条缝"
    tts_complete = "好，可以睁眼了"

    def __init__(
        self,
        duration_seconds: float,
        baseline_ear: float,
        baseline_ratio: float,
        ear_min: float,
    ):
        self.duration_seconds = duration_seconds
        self.baseline_ear = baseline_ear
        self.baseline_ratio = baseline_ratio
        self.ear_min = ear_min
        self._ears: List[float] = []

    def reset(self) -> None:
        self._ears.clear()

    def feed_frame(self, ear, yaw, pitch, timestamp) -> None:
        if ear is not None:
            self._ears.append(ear)

    def get_live_feedback(self, elapsed_sec: float) -> LiveFeedback:
        return LiveFeedback(
            remaining_sec=max(0.0, self.duration_seconds - elapsed_sec),
            sample_count=len(self._ears),
            quality_hint="眯眼保持中...",
        )

    def is_complete(self, elapsed_sec: float) -> bool:
        return elapsed_sec >= self.duration_seconds

    def evaluate(self) -> PhaseResult:
        if not self._ears:
            return PhaseResult(
                success=False, summary={},
                failure_reason="no_samples",
                failure_diagnosis="未采集到数据，请确认人脸在画面内",
            )

        ear_mid = statistics.fmean(self._ears)
        upper = self.baseline_ear * self.baseline_ratio  # 0.225 当 baseline=0.30
        lower = self.ear_min * 1.2                        # 0.096 当 ear_min=0.08

        summary = {
            "ear_mid": ear_mid, "upper_limit": upper, "lower_limit": lower,
            "sample_count": len(self._ears),
        }

        if ear_mid >= upper:
            return PhaseResult(
                success=False, summary=summary,
                failure_reason="squint_too_open",
                failure_diagnosis=f"眯眼幅度不够（EAR {ear_mid:.3f} ≥ {upper:.3f}），请眼睛眯小一点",
            )
        if ear_mid <= lower:
            return PhaseResult(
                success=False, summary=summary,
                failure_reason="squint_too_closed",
                failure_diagnosis=f"眼睛眯得过死，请留一条缝（EAR {ear_mid:.3f} ≤ {lower:.3f}）",
            )

        return PhaseResult(success=True, summary=summary)

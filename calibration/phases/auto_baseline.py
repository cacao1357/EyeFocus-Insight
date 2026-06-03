"""calibration/phases/auto_baseline.py — 阶段 0 自动基线采集

7 秒内采集 EAR/yaw/pitch 均值。
失败条件：face_detected_ratio < 0.7 或 ear_cv > 0.15。

设计依据：spec §2.2 + §4.3。
"""
import statistics
from typing import List, Optional

from calibration.phases.base import LiveFeedback, Phase, PhaseResult


class AutoBaselinePhase(Phase):
    name = "自动基线采集"
    tts_intro = "请保持自然睁眼，系统将自动采集 7 秒数据"
    tts_complete = "基线采集完成"

    def __init__(self, duration_seconds: float = 7.0):
        self.duration_seconds = duration_seconds
        self._ears: List[float] = []
        self._yaws: List[float] = []
        self._pitches: List[float] = []
        self._frames_total: int = 0       # 含 None 帧

    def reset(self) -> None:
        self._ears.clear()
        self._yaws.clear()
        self._pitches.clear()
        self._frames_total = 0

    def feed_frame(self, ear, yaw, pitch, timestamp) -> None:
        self._frames_total += 1
        if ear is not None:
            self._ears.append(ear)
            self._yaws.append(yaw if yaw is not None else 0.0)
            self._pitches.append(pitch if pitch is not None else 0.0)

    def get_live_feedback(self, elapsed_sec: float) -> LiveFeedback:
        remaining = max(0.0, self.duration_seconds - elapsed_sec)
        return LiveFeedback(
            remaining_sec=remaining,
            sample_count=len(self._ears),
            quality_hint="保持自然，无需眨眼",
        )

    def is_complete(self, elapsed_sec: float) -> bool:
        return elapsed_sec >= self.duration_seconds

    def evaluate(self) -> PhaseResult:
        n_valid = len(self._ears)
        if self._frames_total == 0:
            return PhaseResult(
                success=False, summary={},
                failure_reason="no_frames",
                failure_diagnosis="未收到任何帧，请检查摄像头",
            )

        face_ratio = n_valid / self._frames_total

        if face_ratio < 0.7:
            return PhaseResult(
                success=False,
                summary={"face_detected_ratio": face_ratio, "sample_count": n_valid},
                failure_reason="face_detected_ratio_low",
                failure_diagnosis="人脸检测不稳定，请确认摄像头对准你的脸",
            )

        ear_mean = statistics.fmean(self._ears)
        ear_stdev = statistics.stdev(self._ears) if n_valid > 1 else 0.0
        ear_cv = ear_stdev / ear_mean if ear_mean > 0 else 0.0
        yaw_mean = statistics.fmean(self._yaws)
        pitch_mean = statistics.fmean(self._pitches)

        if ear_cv > 0.15:
            return PhaseResult(
                success=False,
                summary={"ear_mean": ear_mean, "ear_cv": ear_cv, "face_detected_ratio": face_ratio},
                failure_reason="ear_cv_high",
                failure_diagnosis="请保持自然睁眼，眨眼请等校准后再做",
            )

        return PhaseResult(
            success=True,
            summary={
                "ear_mean": ear_mean,
                "ear_cv": ear_cv,
                "yaw_mean": yaw_mean,
                "pitch_mean": pitch_mean,
                "sample_count": n_valid,
                "face_detected_ratio": face_ratio,
            },
        )

"""测试 CalibrationResult 数据契约 — 字段冻结、必填、类型。"""
import pytest
from dataclasses import FrozenInstanceError
from datetime import datetime

from calibration.result import (
    CalibrationResult,
    CalibrationSignal,
    BlinkCalibrationRound,
)


# ---------- CalibrationSignal ----------

def test_calibration_signal_fields():
    sig = CalibrationSignal(
        ear_mean=0.30,
        ear_min=0.08,
        ear_mid=0.22,
        yaw_mean=0.5,
        yaw_range=(-15.0, 18.0),
        pitch_mean=1.2,
        pitch_range=(-12.0, 10.0),
        glasses_mode=False,
        timestamp=1700000000.0,
    )
    assert sig.ear_mean == 0.30
    assert sig.yaw_range == (-15.0, 18.0)


def test_calibration_signal_is_frozen():
    sig = CalibrationSignal(
        ear_mean=0.30, ear_min=0.08, ear_mid=0.22,
        yaw_mean=0.0, yaw_range=(0.0, 0.0),
        pitch_mean=0.0, pitch_range=(0.0, 0.0),
        glasses_mode=False, timestamp=0.0,
    )
    with pytest.raises(FrozenInstanceError):
        sig.ear_mean = 0.99  # type: ignore[misc]


# ---------- BlinkCalibrationRound ----------

def test_blink_round_fields():
    r = BlinkCalibrationRound(
        round_index=1,
        duration_seconds=15,
        user_blink_count=10,
        program_blink_count=8,
        program_squint_count=2,
        error_rate=0.2,
        adjustment_factor=1.2,
    )
    assert r.round_index == 1
    assert r.adjustment_factor == 1.2


def test_blink_round_is_frozen():
    r = BlinkCalibrationRound(
        round_index=1, duration_seconds=15, user_blink_count=10,
        program_blink_count=8, program_squint_count=0,
        error_rate=0.2, adjustment_factor=1.0,
    )
    with pytest.raises(FrozenInstanceError):
        r.user_blink_count = 99  # type: ignore[misc]


# ---------- CalibrationResult ----------

def _make_signal():
    return CalibrationSignal(
        ear_mean=0.30, ear_min=0.08, ear_mid=0.22,
        yaw_mean=0.0, yaw_range=(-15.0, 15.0),
        pitch_mean=0.0, pitch_range=(-10.0, 10.0),
        glasses_mode=False, timestamp=1700000000.0,
    )


def test_calibration_result_full():
    r1 = BlinkCalibrationRound(
        round_index=1, duration_seconds=15, user_blink_count=10,
        program_blink_count=8, program_squint_count=0,
        error_rate=0.2, adjustment_factor=1.2,
    )
    res = CalibrationResult(
        session_id="s1",
        timestamp=datetime(2026, 6, 2, 10, 0, 0),
        signal=_make_signal(),
        blink_rounds=[r1],
        final_adjustment_factor=1.2,
        final_blink_threshold=0.27,
        final_squint_threshold=0.225,
        baseline_blink_rate=14.0,
        cqs=0.85,
        is_accepted=True,
    )
    assert res.session_id == "s1"
    assert res.is_accepted is True
    assert res.notes == ""  # default


def test_calibration_result_is_frozen():
    res = CalibrationResult(
        session_id="s1", timestamp=datetime(2026, 6, 2),
        signal=_make_signal(), blink_rounds=[],
        final_adjustment_factor=1.0,
        final_blink_threshold=0.27, final_squint_threshold=0.225,
        baseline_blink_rate=14.0, cqs=0.80, is_accepted=True,
    )
    with pytest.raises(FrozenInstanceError):
        res.session_id = "s2"  # type: ignore[misc]


def test_calibration_result_default_notes_empty():
    res = CalibrationResult(
        session_id="s1", timestamp=datetime(2026, 6, 2),
        signal=_make_signal(), blink_rounds=[],
        final_adjustment_factor=1.0,
        final_blink_threshold=0.27, final_squint_threshold=0.225,
        baseline_blink_rate=14.0, cqs=0.80, is_accepted=True,
    )
    assert res.notes == ""


def test_calibration_result_with_notes():
    res = CalibrationResult(
        session_id="s1", timestamp=datetime(2026, 6, 2),
        signal=_make_signal(), blink_rounds=[],
        final_adjustment_factor=1.0,
        final_blink_threshold=0.27, final_squint_threshold=0.225,
        baseline_blink_rate=14.0, cqs=0.80, is_accepted=True,
        notes="用户跳过了眨眼计数",
    )
    assert res.notes == "用户跳过了眨眼计数"


def test_calibration_result_empty_blink_rounds_allowed():
    """跳过眨眼计数阶段时，blink_rounds 可为空。"""
    res = CalibrationResult(
        session_id="s1", timestamp=datetime(2026, 6, 2),
        signal=_make_signal(), blink_rounds=[],
        final_adjustment_factor=1.0,
        final_blink_threshold=0.27, final_squint_threshold=0.225,
        baseline_blink_rate=15.0,  # 默认值
        cqs=0.80, is_accepted=True,
    )
    assert res.blink_rounds == []


def test_calibration_result_multi_rounds():
    rounds = [
        BlinkCalibrationRound(
            round_index=i, duration_seconds=15, user_blink_count=10,
            program_blink_count=8, program_squint_count=0,
            error_rate=0.2, adjustment_factor=1.2,
        )
        for i in (1, 2)
    ]
    res = CalibrationResult(
        session_id="s1", timestamp=datetime(2026, 6, 2),
        signal=_make_signal(), blink_rounds=rounds,
        final_adjustment_factor=1.2,
        final_blink_threshold=0.27, final_squint_threshold=0.225,
        baseline_blink_rate=14.0, cqs=0.85, is_accepted=True,
    )
    assert len(res.blink_rounds) == 2
    assert res.blink_rounds[0].round_index == 1

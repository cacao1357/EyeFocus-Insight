"""测试 CalibrationConfig 配置项默认值与可定制性。"""
import pytest
from calibration.config import CalibrationConfig


def test_default_config_fields_present():
    c = CalibrationConfig()
    # 阶段时长
    assert c.auto_baseline_seconds == 7.0
    assert c.closed_eyes_seconds == 5.0
    assert c.open_eyes_verify_seconds == 0.0  # T-CAL-27: 跳过
    assert c.squint_seconds == 3.0      # v4.4: 5→3
    assert c.head_direction_seconds == 2.5  # v4.4: 3.0→2.5
    assert c.blink_round_seconds == 8.0  # v4.4: 15→8
    assert c.blink_rounds_count == 1     # v4.4: 2→1

    # 阈值 (T-CAL-15: closed_eyes_min_ratio 0.5→0.6; T-CAL-16: head_direction_min_degrees 10→20)
    assert c.closed_eyes_min_ratio == 0.6
    assert c.squint_baseline_ratio == 0.75
    assert c.head_direction_min_degrees == 15.0  # v4.4: 12→15
    assert c.blink_count_min == 5
    assert c.blink_count_max == 60

    # UI
    assert c.ui_panel_height_px == 240
    assert c.button_height_px == 50
    assert c.button_padding_px == 10

    # 音频
    assert c.tts_rate == 180
    assert c.audio_enabled is True


def test_config_total_estimated_seconds():
    """5 阶段大致总时长（不含用户确认等待）应 < 90 秒。"""
    c = CalibrationConfig()
    total = (
        c.auto_baseline_seconds
        + c.closed_eyes_seconds + c.open_eyes_verify_seconds
        + c.squint_seconds
        + c.head_direction_seconds * 4
        + c.blink_round_seconds * c.blink_rounds_count
    )
    assert total < 50, f"5 阶段裸时长 {total}s 超过 50 秒上限 (v4.4 缩短后)"


def test_config_customizable():
    c = CalibrationConfig(
        auto_baseline_seconds=5.0,
        blink_rounds_count=3,
        audio_enabled=False,
    )
    assert c.auto_baseline_seconds == 5.0
    assert c.blink_rounds_count == 3
    assert c.audio_enabled is False


def test_blink_count_range_sensible():
    c = CalibrationConfig()
    assert c.blink_count_min < c.blink_count_max
    assert c.blink_count_min >= 1
    assert c.blink_count_max <= 100


def test_thresholds_in_valid_range():
    c = CalibrationConfig()
    assert 0.0 < c.closed_eyes_min_ratio < 1.0
    assert 0.0 < c.squint_baseline_ratio < 1.0
    assert c.head_direction_min_degrees > 0


def test_ui_dimensions_positive():
    c = CalibrationConfig()
    assert c.ui_panel_height_px > 0
    assert c.button_height_px > 0
    assert c.button_padding_px >= 0

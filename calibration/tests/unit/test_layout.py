"""测试 layout.compose — vconcat 拼合视频 + UI 面板。"""
import numpy as np
import pytest

from calibration.ui.layout import compose


def test_compose_normal_size():
    cam = np.zeros((480, 640, 3), dtype=np.uint8)
    panel = np.zeros((240, 640, 3), dtype=np.uint8)
    out = compose(cam, panel)
    assert out.shape == (720, 640, 3)


def test_compose_panel_height_must_match_width():
    cam = np.zeros((480, 640, 3), dtype=np.uint8)
    panel = np.zeros((240, 320, 3), dtype=np.uint8)  # 宽度不匹配
    with pytest.raises(ValueError):
        compose(cam, panel)


def test_compose_preserves_dtype():
    cam = np.zeros((480, 640, 3), dtype=np.uint8)
    panel = np.full((240, 640, 3), 50, dtype=np.uint8)
    out = compose(cam, panel)
    assert out.dtype == np.uint8


def test_compose_video_region_unchanged():
    cam = np.full((480, 640, 3), 100, dtype=np.uint8)
    panel = np.full((240, 640, 3), 50, dtype=np.uint8)
    out = compose(cam, panel)
    # 视频区域（前 480 行）应与 cam 完全相同
    assert np.array_equal(out[:480], cam)
    # UI 区域（后 240 行）应与 panel 完全相同
    assert np.array_equal(out[480:], panel)

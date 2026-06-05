"""
tests/test_light.py — LightDetector 单元测试
覆盖 detector/light.py 中可离线测试的函数。
3级分类: DARK (≤50), NORMAL (50-100), BRIGHT (>100)
"""

import numpy as np
import pytest

from detector.light import (
    LightCondition,
    LightDetector,
    LightResult,
    create_light_detector,
    DEFAULT_BRIGHTNESS_DARK,
    DEFAULT_BRIGHTNESS_BRIGHT,
)


def make_frame(brightness: int) -> np.ndarray:
    """创建指定亮度的 BGR 帧"""
    return np.full((480, 640, 3), brightness, dtype=np.uint8)


# ---------------------------------------------------------------------------
# TestLightCondition
# ---------------------------------------------------------------------------

class TestLightCondition:
    def test_enum_values(self):
        """验证 LightCondition 枚举的3个成员"""
        assert LightCondition.DARK.value == "dark"
        assert LightCondition.NORMAL.value == "normal"
        assert LightCondition.BRIGHT.value == "bright"
        assert len(LightCondition) == 3


# ---------------------------------------------------------------------------
# TestLightResult
# ---------------------------------------------------------------------------

class TestLightResult:
    def test_result_creation(self):
        """验证 LightResult dataclass 字段"""
        result = LightResult(
            condition=LightCondition.NORMAL,
            brightness=75.0,
            brightness_std=10.5,
            face_region_brightness=130.0,
            is_adequate=True,
        )
        assert result.condition == LightCondition.NORMAL
        assert result.brightness == 75.0
        assert result.brightness_std == 10.5
        assert result.face_region_brightness == 130.0
        assert result.is_adequate is True


# ---------------------------------------------------------------------------
# TestLightDetector
# ---------------------------------------------------------------------------

class TestLightDetector:
    def test_initial_state(self):
        """验证检测器初始状态为空历史"""
        detector = LightDetector()
        assert detector.get_smoothed_brightness() == 0.0
        assert detector.get_smoothed_condition() == LightCondition.NORMAL
        assert len(detector._brightness_history) == 0
        assert len(detector._condition_history) == 0

    def test_analyze_bright_frame(self):
        """分析明亮场景（亮度 > 100）"""
        detector = LightDetector()
        frame = make_frame(150)  # BRIGHT
        result = detector.analyze_frame(frame)

        assert result.condition == LightCondition.BRIGHT
        assert result.brightness > 100
        # M-06: is_adequate 仅 NORMAL 时为 True
        assert result.is_adequate is False

    def test_analyze_dark_frame(self):
        """分析偏暗场景（亮度 ≤ 50）"""
        detector = LightDetector()
        frame = make_frame(40)  # DARK
        result = detector.analyze_frame(frame)

        assert result.condition == LightCondition.DARK
        assert result.brightness <= 50
        # M-06: is_adequate 仅 NORMAL 时为 True
        assert result.is_adequate is False

    def test_analyze_normal_frame(self):
        """分析正常光照场景（亮度 50-100）"""
        detector = LightDetector()
        frame = make_frame(75)  # NORMAL
        result = detector.analyze_frame(frame)

        assert result.condition == LightCondition.NORMAL
        assert 50 < result.brightness < 100
        assert result.is_adequate is True

    def test_classify_brightness_boundaries(self):
        """测试亮度分类的边界值（Dark≤50, Normal 50-100, Bright>100）"""
        detector = LightDetector()

        # 边界：thresh_dark = 50
        assert detector._classify_brightness(49.9) == LightCondition.DARK
        assert detector._classify_brightness(50.0) == LightCondition.DARK
        assert detector._classify_brightness(50.1) == LightCondition.NORMAL

        # 边界：thresh_bright = 100
        assert detector._classify_brightness(99.9) == LightCondition.NORMAL
        assert detector._classify_brightness(100.0) == LightCondition.NORMAL
        assert detector._classify_brightness(100.1) == LightCondition.BRIGHT

    def test_face_region_brightness(self):
        """测试人脸区域亮度计算"""
        detector = LightDetector(face_region_ratio=0.15)
        # 创建全帧：中心区域亮度 = 200，其他区域 = 50
        h, w = 480, 640
        frame = np.full((h, w, 3), 50, dtype=np.uint8)
        face_h = int(h * 0.15)  # 72
        face_w = int(w * 0.15)  # 96
        top = (h - face_h) // 2  # 204
        left = (w - face_w) // 2  # 272
        frame[top:top+face_h, left:left+face_w] = 200

        result = detector._compute_face_region_brightness(frame[:, :, 0])
        assert 150 < result < 250  # 中心区域应该是亮的

    def test_smoothed_condition_voting(self):
        """测试平滑条件多数投票"""
        detector = LightDetector(smooth_window=5)

        # 输入多帧：3帧BRIGHT，2帧NORMAL
        for brightness in [150, 160, 140, 90, 95]:
            detector.analyze_frame(make_frame(brightness))

        assert detector.get_smoothed_condition() == LightCondition.BRIGHT

    def test_lighting_adequate_normal(self):
        """正常光照应 adequate"""
        detector = LightDetector()
        detector.analyze_frame(make_frame(75))
        assert detector.is_lighting_adequate() is True

    def test_reset_clears_history(self):
        """reset 应清空历史并恢复初始状态"""
        detector = LightDetector()

        # 分析几帧
        detector.analyze_frame(make_frame(75))
        detector.analyze_frame(make_frame(150))
        assert len(detector._brightness_history) == 2

        # 重置
        detector.reset()
        assert len(detector._brightness_history) == 0
        assert len(detector._condition_history) == 0
        assert detector.get_smoothed_brightness() == 0.0
        assert detector.get_smoothed_condition() == LightCondition.NORMAL

    def test_stats(self):
        """测试 get_stats 返回完整统计信息"""
        detector = LightDetector()
        detector.analyze_frame(make_frame(75))

        stats = detector.get_stats()
        assert "current_brightness" in stats
        assert "current_condition" in stats
        assert "is_adequate" in stats
        assert "history_size" in stats
        assert stats["current_condition"] == "normal"
        assert stats["history_size"] == 1

    def test_custom_thresholds(self):
        """测试自定义阈值"""
        detector = LightDetector(
            brightness_thresh_dark=40.0,
            brightness_thresh_bright=80.0,
        )
        assert detector._classify_brightness(39) == LightCondition.DARK
        assert detector._classify_brightness(41) == LightCondition.NORMAL
        assert detector._classify_brightness(81) == LightCondition.BRIGHT

    def test_analyze_frame_brightness_100_is_normal(self):
        """亮度=100.0 时 analyze_frame 返回 NORMAL（不是 BRIGHT，因为是严格大于）"""
        detector = LightDetector(brightness_thresh_dark=50.0, brightness_thresh_bright=100.0)
        frame = make_frame(100)  # 全帧亮度=100
        result = detector.analyze_frame(frame)
        assert result.condition == LightCondition.NORMAL

    def test_brightness_threshold_is_strict_greater(self):
        """_classify_brightness 中 brightness > thresh_bright (严格大于，100.0 仍属 NORMAL)"""
        detector = LightDetector(brightness_thresh_dark=50.0, brightness_thresh_bright=100.0)
        assert detector._classify_brightness(100.0) == LightCondition.NORMAL
        assert detector._classify_brightness(100.1) == LightCondition.BRIGHT

    # ===== M-06: is_adequate 仅 NORMAL 时为 True =====

    # ===== M-07: face_region_brightness 空切片 NaN =====

    def test_face_region_brightness_no_nan_when_zero_ratio_M07(self):
        """M-07: face_region_ratio=0 → face_h=0/face_w=0 → 切片空数组 np.mean 返回 NaN
        修复后: 入口检查 face_h/face_w 为 0 → 返回 0.0
        """
        # face_region_ratio=0 → face_h = int(h*0) = 0
        detector = LightDetector(face_region_ratio=0.0)
        gray = np.zeros((480, 640), dtype=np.uint8)
        result = detector._compute_face_region_brightness(gray)
        assert not np.isnan(result), \
            f"M-07 失败: face_region_brightness 不应返回 NaN，实际={result}"
        assert result == 0.0

    # ===== M-08: analyze_frame 空帧保护 =====

    def test_is_adequate_only_normal_M06(self):
        """M-06: is_adequate 只在 LightCondition.NORMAL 时为 True
        原代码 (line 106):
            is_adequate = (NORMAL or DARK or BRIGHT)  # 恒真
        修复后: 只 NORMAL → True
        """
        detector = LightDetector()

        # Mock _classify_brightness 直接返回各 condition
        for condition, expected in [
            (LightCondition.NORMAL, True),
            (LightCondition.DARK, False),
            (LightCondition.BRIGHT, False),
        ]:
            detector._classify_brightness = lambda b, _c=condition: _c
            # 提供一张任意 frame (analyze_frame 内会先 cv2.cvtColor)
            frame = make_frame(75)
            result = detector.analyze_frame(frame)
            assert result.is_adequate is expected, \
                f"M-06 失败: condition={condition.value}, 期望 is_adequate={expected}, 实际={result.is_adequate}"


# ---------------------------------------------------------------------------
# TestFactoryFunction
# ---------------------------------------------------------------------------

class TestFactoryFunction:
    def test_create_light_detector(self):
        """工厂函数应返回正确配置的 LightDetector"""
        detector = create_light_detector()
        assert isinstance(detector, LightDetector)
        # 验证使用默认参数（3级阈值）
        assert detector.thresh_dark == DEFAULT_BRIGHTNESS_DARK
        assert detector.thresh_bright == DEFAULT_BRIGHTNESS_BRIGHT

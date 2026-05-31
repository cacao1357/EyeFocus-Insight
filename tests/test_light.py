"""
tests/test_light.py — LightDetector 单元测试
覆盖 detector/light.py 中可离线测试的函数。
"""

import numpy as np
import pytest

from detector.light import (
    LightCondition,
    LightDetector,
    LightResult,
    create_light_detector,
    DEFAULT_BRIGHTNESS_DARK,
    DEFAULT_BRIGHTNESS_TOO_DARK,
    DEFAULT_BRIGHTNESS_BRIGHT,
    DEFAULT_BRIGHTNESS_TOO_BRIGHT,
)


# ---------------------------------------------------------------------------
# Mock 帧构造辅助函数
# ---------------------------------------------------------------------------

def make_frame(brightness: int, size=(480, 640, 3)):
    """创建指定亮度的灰度帧（RGB 三通道相同值）"""
    frame = np.full(size, brightness, dtype=np.uint8)
    return frame


def make_color_frame(r: int, g: int, b: int, size=(480, 640, 3)):
    """创建指定 RGB 值的彩色帧"""
    frame = np.zeros(size, dtype=np.uint8)
    frame[:, :, 0] = b  # Blue
    frame[:, :, 1] = g  # Green
    frame[:, :, 2] = r  # Red
    return frame


# ---------------------------------------------------------------------------
# TestLightCondition
# ---------------------------------------------------------------------------

class TestLightCondition:
    def test_enum_values(self):
        """验证 LightCondition 枚举的所有成员"""
        assert LightCondition.TOO_DARK.value == "too_dark"
        assert LightCondition.DARK.value == "dark"
        assert LightCondition.NORMAL.value == "normal"
        assert LightCondition.BRIGHT.value == "bright"
        assert LightCondition.TOO_BRIGHT.value == "too_bright"
        # 确保没有意外成员
        assert len(LightCondition) == 5


# ---------------------------------------------------------------------------
# TestLightResult
# ---------------------------------------------------------------------------

class TestLightResult:
    def test_result_creation(self):
        """验证 LightResult dataclass 字段"""
        result = LightResult(
            condition=LightCondition.NORMAL,
            brightness=128.0,
            brightness_std=10.5,
            face_region_brightness=130.0,
            is_adequate=True,
        )
        assert result.condition == LightCondition.NORMAL
        assert result.brightness == 128.0
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
        assert detector.is_lighting_adequate() is True
        assert len(detector._brightness_history) == 0
        assert len(detector._condition_history) == 0

    def test_analyze_bright_frame(self):
        """分析明亮场景（亮度接近180）"""
        detector = LightDetector()
        frame = make_frame(175)  # 正常偏亮
        result = detector.analyze_frame(frame)

        assert result.condition == LightCondition.NORMAL
        assert 170 < result.brightness < 180
        assert result.is_adequate is True

    def test_analyze_dark_frame(self):
        """分析偏暗场景（亮度接近40）"""
        detector = LightDetector()
        frame = make_frame(35)  # 偏暗
        result = detector.analyze_frame(frame)

        assert result.condition == LightCondition.DARK
        assert 30 < result.brightness < 45
        assert result.is_adequate is True

    def test_analyze_normal_frame(self):
        """分析正常光照场景"""
        detector = LightDetector()
        frame = make_frame(128)  # 正常
        result = detector.analyze_frame(frame)

        assert result.condition == LightCondition.NORMAL
        assert 120 < result.brightness < 136
        assert result.is_adequate is True

    def test_analyze_too_bright_frame(self):
        """分析过亮场景（亮度 > 220）"""
        detector = LightDetector()
        frame = make_frame(240)  # 过亮
        result = detector.analyze_frame(frame)

        assert result.condition == LightCondition.TOO_BRIGHT
        assert result.brightness > 220
        assert result.is_adequate is False

    def test_analyze_too_dark_frame(self):
        """分析过暗场景（亮度 < 25）"""
        detector = LightDetector()
        frame = make_frame(15)  # 过暗
        result = detector.analyze_frame(frame)

        assert result.condition == LightCondition.TOO_DARK
        assert result.brightness < 25
        assert result.is_adequate is False

    def test_classify_brightness_boundaries(self):
        """测试亮度分类的边界值"""
        detector = LightDetector()

        # 边界：thresh_too_dark = 25
        assert detector._classify_brightness(24.9) == LightCondition.TOO_DARK
        assert detector._classify_brightness(25.0) == LightCondition.DARK

        # 边界：thresh_dark = 40
        assert detector._classify_brightness(39.9) == LightCondition.DARK
        assert detector._classify_brightness(40.0) == LightCondition.NORMAL

        # 边界：thresh_bright = 180（使用 strict >，所以 180.0 落在 NORMAL）
        assert detector._classify_brightness(179.9) == LightCondition.NORMAL
        assert detector._classify_brightness(180.0) == LightCondition.NORMAL
        assert detector._classify_brightness(180.1) == LightCondition.BRIGHT

        # 边界：thresh_too_bright = 220（使用 strict >，所以 220.0 落在 BRIGHT）
        assert detector._classify_brightness(219.9) == LightCondition.BRIGHT
        assert detector._classify_brightness(220.0) == LightCondition.BRIGHT
        assert detector._classify_brightness(220.1) == LightCondition.TOO_BRIGHT

    def test_face_region_brightness(self):
        """测试人脸区域亮度计算"""
        detector = LightDetector(face_region_ratio=0.15)
        # 创建棋盘格帧：人脸区域亮度 = 200，其他区域 = 50
        h, w = 480, 640
        frame = np.full((h, w, 3), 50, dtype=np.uint8)
        face_h = int(h * 0.15)  # 72
        face_w = int(w * 0.15)  # 96
        top = (h - face_h) // 2  # 204
        left = (w - face_w) // 2  # 272
        frame[top:top+face_h, left:left+face_w] = 200

        gray = frame[:, :, 0]  # BGR转灰度后各通道相同
        face_brightness = detector._compute_face_region_brightness(gray)

        # 人脸区域应该接近200
        assert 195 < face_brightness < 205

    def test_smoothed_brightness_multiple_frames(self):
        """测试多帧平滑亮度"""
        detector = LightDetector(smooth_window=3)

        # 第一帧：暗
        result1 = detector.analyze_frame(make_frame(20))
        assert result1.condition == LightCondition.TOO_DARK

        # 第二帧：正常
        result2 = detector.analyze_frame(make_frame(128))
        assert result2.condition == LightCondition.NORMAL

        # 第三帧：亮
        result3 = detector.analyze_frame(make_frame(200))
        assert result3.condition == LightCondition.BRIGHT

        # 平滑值应为三帧平均
        smoothed = detector.get_smoothed_brightness()
        expected_avg = (20 + 128 + 200) / 3
        assert abs(smoothed - expected_avg) < 5

    def test_smoothed_condition_voting(self):
        """测试条件多数投票"""
        detector = LightDetector(smooth_window=5)

        # 输入多帧：3帧BRIGHT，2帧NORMAL
        for brightness in [200, 210, 190, 175, 180]:
            detector.analyze_frame(make_frame(brightness))

        assert detector.get_smoothed_condition() == LightCondition.BRIGHT

    def test_lighting_adequate_normal(self):
        """正常光照应 adequate"""
        detector = LightDetector()
        detector.analyze_frame(make_frame(128))
        assert detector.is_lighting_adequate() is True

    def test_lighting_adequate_too_dark(self):
        """过暗光照应 inadequate"""
        detector = LightDetector()
        detector.analyze_frame(make_frame(15))
        assert detector.is_lighting_adequate() is False

    def test_reset_clears_history(self):
        """reset 应清空历史并恢复初始状态"""
        detector = LightDetector()

        # 分析几帧
        detector.analyze_frame(make_frame(128))
        detector.analyze_frame(make_frame(200))
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
        detector.analyze_frame(make_frame(128))

        stats = detector.get_stats()
        assert "current_brightness" in stats
        assert "current_condition" in stats
        assert "is_adequate" in stats
        assert "history_size" in stats
        assert stats["current_condition"] == "normal"
        assert stats["history_size"] == 1
        assert stats["is_adequate"] is True

    def test_custom_thresholds(self):
        """测试自定义阈值"""
        # 使用宽松的过暗阈值
        detector = LightDetector(
            brightness_thresh_too_dark=15.0,
            brightness_thresh_dark=30.0,
        )
        # 亮度25应该落在DARK区间（因为 > 15 且 < 30）
        assert detector._classify_brightness(25) == LightCondition.DARK


# ---------------------------------------------------------------------------
# TestFactoryFunction
# ---------------------------------------------------------------------------

class TestFactoryFunction:
    def test_create_light_detector(self):
        """工厂函数应返回正确配置的 LightDetector"""
        detector = create_light_detector()
        assert isinstance(detector, LightDetector)
        # 验证使用默认参数
        assert detector.thresh_too_dark == DEFAULT_BRIGHTNESS_TOO_DARK
        assert detector.thresh_dark == DEFAULT_BRIGHTNESS_DARK
        assert detector.thresh_bright == DEFAULT_BRIGHTNESS_BRIGHT
        assert detector.thresh_too_bright == DEFAULT_BRIGHTNESS_TOO_BRIGHT

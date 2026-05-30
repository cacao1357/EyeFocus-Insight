"""
tests/test_gui.py — GUI 模块单元测试
覆盖 gui/ 包中所有可离线测试的函数。
"""

import sys
import os
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.overlay import (
    FocusOverlay,
    OverlayConfig,
    CalibrationProgress,
    AlertLevel,
    AlertMessage,
    create_focus_overlay,
)


class TestOverlayConfig:
    """OverlayConfig 单元测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = OverlayConfig()
        assert config.window_name == "EyeFocus Insight"
        assert config.width == 640
        assert config.height == 480
        assert config.alpha == 0.85

    def test_custom_config(self):
        """测试自定义配置"""
        config = OverlayConfig(
            window_name="Test Window",
            width=1280,
            height=720,
            alpha=0.8,
        )
        assert config.window_name == "Test Window"
        assert config.width == 1280
        assert config.height == 720


class TestFocusOverlay:
    """FocusOverlay 单元测试"""

    def test_initial_state(self):
        """测试初始状态"""
        overlay = FocusOverlay()
        assert overlay._alerts == []
        assert overlay._calibration is None

    def test_draw_basic_frame(self):
        """测试基本帧绘制"""
        overlay = FocusOverlay()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        result = overlay.draw(frame)
        assert result is not None
        assert result.shape == frame.shape

    def test_draw_with_focus_score(self):
        """测试带专注度分数的绘制"""
        overlay = FocusOverlay()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        result = overlay.draw(frame, focus_score=85.0)
        assert result is not None

    def test_draw_with_fatigue_level(self):
        """测试带疲劳等级的绘制"""
        overlay = FocusOverlay()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        result = overlay.draw(frame, fatigue_level="LOW")
        assert result is not None

        result = overlay.draw(frame, fatigue_level="MEDIUM")
        assert result is not None

        result = overlay.draw(frame, fatigue_level="HIGH")
        assert result is not None

    def test_draw_with_no_detection(self):
        """测试未检测到人脸/眼睛的绘制"""
        overlay = FocusOverlay()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        result = overlay.draw(frame, eye_detected=False, face_detected=False)
        assert result is not None

    def test_draw_with_calibration(self):
        """测试带校准进度的绘制"""
        overlay = FocusOverlay()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        calibration = CalibrationProgress(
            current=50,
            total=100,
            cqs=0.65,
            is_complete=False,
        )

        result = overlay.draw(frame, calibration=calibration)
        assert result is not None

    def test_draw_with_complete_calibration(self):
        """测试带完成校准的绘制"""
        overlay = FocusOverlay()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        calibration = CalibrationProgress(
            current=100,
            total=100,
            cqs=0.75,
            is_complete=True,
        )

        result = overlay.draw(frame, calibration=calibration)
        assert result is not None

    def test_add_alert(self):
        """测试添加告警"""
        overlay = FocusOverlay()

        overlay.add_alert(AlertLevel.INFO, "测试信息")
        assert len(overlay._alerts) == 1

        overlay.add_alert(AlertLevel.WARNING, "测试警告")
        assert len(overlay._alerts) == 2

    def test_add_alert_auto_cleanup(self):
        """测试告警自动清理"""
        overlay = FocusOverlay()

        # 添加旧告警（时间戳被覆盖）
        overlay._alerts.append(
            AlertMessage(level=AlertLevel.WARNING, text="旧告警", timestamp=time.time() - 10)
        )

        # 添加新告警
        overlay.add_alert(AlertLevel.INFO, "新告警")

        # 触发绘制（会清理过期告警）
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        overlay.draw(frame)

        # 旧告警应该被清理
        assert len(overlay._alerts) <= 3  # 最多保留3条

    def test_fatigue_color_method(self):
        """测试疲劳颜色映射"""
        overlay = FocusOverlay()

        assert overlay._fatigue_color("LOW") == (0, 255, 0)
        assert overlay._fatigue_color("MEDIUM") == (0, 255, 255)
        assert overlay._fatigue_color("HIGH") == (0, 0, 255)
        assert overlay._fatigue_color(None) == overlay.config.text_color

    def test_alert_color_method(self):
        """测试告警颜色映射"""
        overlay = FocusOverlay()

        assert overlay._alert_color(AlertLevel.INFO) == (255, 255, 255)
        assert overlay._alert_color(AlertLevel.WARNING) == (0, 165, 255)
        assert overlay._alert_color(AlertLevel.ERROR) == (0, 0, 255)
        assert overlay._alert_color(AlertLevel.NONE) == overlay.config.text_color

    def test_factory_function(self):
        """测试工厂函数"""
        overlay = create_focus_overlay()
        assert isinstance(overlay, FocusOverlay)


class TestCalibrationProgress:
    """CalibrationProgress 单元测试"""

    def test_in_progress_calibration(self):
        """测试进行中的校准"""
        cal = CalibrationProgress(
            current=50,
            total=100,
            cqs=0.65,
            is_complete=False,
        )
        assert cal.current == 50
        assert cal.total == 100
        assert cal.cqs == 0.65
        assert cal.is_complete is False

    def test_complete_calibration(self):
        """测试完成的校准"""
        cal = CalibrationProgress(
            current=100,
            total=100,
            cqs=0.75,
            is_complete=True,
        )
        assert cal.is_complete is True


class TestAlertMessage:
    """AlertMessage 单元测试"""

    def test_alert_message_creation(self):
        """测试告警消息创建"""
        alert = AlertMessage(
            level=AlertLevel.WARNING,
            text="测试警告",
            timestamp=time.time(),
        )
        assert alert.level == AlertLevel.WARNING
        assert alert.text == "测试警告"

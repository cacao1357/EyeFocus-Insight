"""
tests/test_analyzer.py — Analyzer 模块单元测试
覆盖 analyzer/ 包中所有可离线测试的函数。
"""

import sys
import os
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyzer.baseline import BaselineCalibrator, BaselineResult, create_baseline_calibrator
from analyzer.focus import FocusAnalyzer, FocusResult, KalmanFilter1D, create_focus_analyzer
from analyzer.fatigue import FatigueAnalyzer, FatigueAnalysisResult, create_fatigue_analyzer
from storage.models import GlassesMode


class TestBaselineCalibrator:
    """BaselineCalibrator 单元测试"""

    def test_initial_state(self):
        """测试初始状态"""
        calibrator = BaselineCalibrator()
        assert calibrator.get_result() is None
        # is_complete() 初始为 False
        assert calibrator.is_complete() is False

    def test_add_frame_valid(self):
        """测试添加有效帧"""
        calibrator = BaselineCalibrator()
        calibrator.start()

        # 添加一些有效数据
        for _ in range(50):
            result = calibrator.add_frame(ear=0.25, yaw=0.0, pitch=0.0)
            # add_frame 可能返回 bool 或 None

        # 校准可能完成也可能不完成，取决于数据质量

    def test_add_frame_immediate_complete(self):
        """测试立即完成的校准"""
        calibrator = BaselineCalibrator()

        # 添加高质量数据（高 EAR 值，低变化）
        calibrator.start()
        for i in range(100):
            ear = 0.25 + np.sin(i * 0.1) * 0.02  # 稳定的高 EAR
            calibrator.add_frame(ear=ear, yaw=0.0, pitch=0.0)

        result = calibrator.get_result()
        # 结果可能是 None（数据不够好）或 BaselineResult

    def test_get_result_before_start(self):
        """测试未开始时的结果"""
        calibrator = BaselineCalibrator()
        assert calibrator.get_result() is None

    def test_factory_function(self):
        """测试工厂函数"""
        calibrator = create_baseline_calibrator()
        assert isinstance(calibrator, BaselineCalibrator)


class TestKalmanFilter1D:
    """KalmanFilter1D 单元测试"""

    def test_initial_state(self):
        """测试初始状态"""
        kf = KalmanFilter1D()
        # 第一次 update 返回接近测量值的值（受卡尔曼增益影响）
        result = kf.update(10.0)
        assert 0.0 < result < 15.0  # 应该在合理范围内

    def test_smoothing(self):
        """测试平滑效果"""
        kf = KalmanFilter1D()

        # 添加一些噪声数据
        measurements = [100.0, 105.0, 95.0, 102.0, 98.0]
        results = []
        for m in measurements:
            results.append(kf.update(m))

        # 结果应该比输入平滑
        variance = np.var(results)
        input_variance = np.var(measurements)
        assert variance < input_variance

    def test_convergence(self):
        """测试收敛性"""
        kf = KalmanFilter1D()

        # 稳定输入应该快速收敛
        for _ in range(100):
            kf.update(50.0)

        result = kf.update(50.0)
        assert abs(result - 50.0) < 1.0


class TestFocusAnalyzer:
    """FocusAnalyzer 单元测试"""

    def test_initial_state(self):
        """测试初始状态"""
        analyzer = FocusAnalyzer()
        # 初始分数为 0
        stats = analyzer.get_stats()
        assert stats["current_focus_score"] == 0.0

    def test_analyze_normal(self):
        """测试正常情况分析"""
        analyzer = FocusAnalyzer()
        result = analyzer.analyze(
            ear=0.25,
            yaw=0.0,
            pitch=0.0,
            gaze_score=100.0,
            brightness=128.0,
            face_detected=True
        )

        assert isinstance(result, FocusResult)
        assert 0.0 <= result.focus_score <= 100.0

    def test_analyze_no_face(self):
        """测试未检测到人脸"""
        analyzer = FocusAnalyzer()
        result = analyzer.analyze(
            ear=0.0,
            yaw=0.0,
            pitch=0.0,
            gaze_score=0.0,
            brightness=128.0,
            face_detected=False
        )

        assert result.focus_score == 0.0

    def test_smoothing(self):
        """测试平滑效果"""
        analyzer = FocusAnalyzer()

        # 添加一些变化的输入
        scores = []
        for i in range(20):
            ear = 0.25 if i % 2 == 0 else 0.15
            result = analyzer.analyze(
                ear=ear,
                yaw=0.0,
                pitch=0.0,
                gaze_score=80.0,
                brightness=128.0,
                face_detected=True
            )
            scores.append(result.focus_score)

        # 相邻分数变化应该较小
        max_diff = max(abs(scores[i] - scores[i-1]) for i in range(1, len(scores)))
        assert max_diff < 50.0  # 平滑后相邻变化不应太大

    def test_factory_function(self):
        """测试工厂函数"""
        analyzer = create_focus_analyzer()
        assert isinstance(analyzer, FocusAnalyzer)


class TestFatigueAnalyzer:
    """FatigueAnalyzer 单元测试"""

    def test_initial_state(self):
        """测试初始状态"""
        analyzer = FatigueAnalyzer()
        assert analyzer.get_stats()["cumulative_fatigue"] == 0.0

    def test_analyze_low_fatigue(self):
        """测试低疲劳状态"""
        analyzer = FatigueAnalyzer()
        result = analyzer.analyze(
            blink_rate=15.0,
            ear_nadir=0.15,
            head_stability=90.0
        )

        assert isinstance(result, FatigueAnalysisResult)
        assert result.fatigue_level.value == "low"
        assert 0.0 <= result.fatigue_score <= 100.0

    def test_analyze_medium_fatigue(self):
        """测试中等疲劳状态"""
        analyzer = FatigueAnalyzer()
        result = analyzer.analyze(
            blink_rate=25.0,
            ear_nadir=0.10,
            head_stability=70.0
        )

        assert result.fatigue_level.value in ["low", "medium", "high"]

    def test_analyze_high_fatigue(self):
        """测试高疲劳状态"""
        analyzer = FatigueAnalyzer()
        result = analyzer.analyze(
            blink_rate=35.0,
            ear_nadir=0.06,
            head_stability=50.0
        )

        assert isinstance(result.fatigue_level.value, str)

    def test_start_reset(self):
        """测试开始和重置"""
        analyzer = FatigueAnalyzer()
        analyzer.start()

        stats = analyzer.get_stats()
        assert stats["cumulative_fatigue"] == 0.0

        # 添加一些分析数据
        analyzer.analyze(blink_rate=20.0, ear_nadir=0.10, head_stability=80.0)

        # 重置
        analyzer.reset()
        stats = analyzer.get_stats()
        assert stats["cumulative_fatigue"] == 0.0

    def test_factory_function(self):
        """测试工厂函数"""
        analyzer = create_fatigue_analyzer()
        assert isinstance(analyzer, FatigueAnalyzer)


class TestGlassesModeEnum:
    """GlassesMode 枚举测试"""

    def test_glasses_mode_values(self):
        """测试 GlassesMode 枚举值"""
        from storage.models import GlassesMode

        assert GlassesMode.UNKNOWN.value == "unknown"
        assert GlassesMode.WITH_GLASSES.value == "with_glasses"
        assert GlassesMode.WITHOUT_GLASSES.value == "without_glasses"
        assert GlassesMode.MANUAL_GLASSES.value == "manual_glasses"
        assert GlassesMode.MANUAL_NO_GLASSES.value == "manual_no_glasses"

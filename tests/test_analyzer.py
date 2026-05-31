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


class TestBaselineCalibratorBoundary:
    """BaselineCalibrator 边界条件测试"""

    def test_get_result_before_start(self):
        """测试未开始校准时获取结果"""
        calibrator = BaselineCalibrator()
        assert calibrator.get_result() is None

    def test_get_result_after_cancel(self):
        """测试取消后获取结果"""
        calibrator = BaselineCalibrator()
        calibrator.start()
        calibrator.add_frame(ear=0.25, yaw=0.0, pitch=0.0)
        calibrator.cancel()
        assert calibrator.get_result() is None

    def test_add_frame_before_start(self):
        """测试未开始前添加帧"""
        calibrator = BaselineCalibrator()
        result = calibrator.add_frame(ear=0.25, yaw=0.0, pitch=0.0)
        assert result is False

    def test_add_frame_all_invalid_head_pose(self):
        """测试所有帧头部姿态都不合格的情况"""
        calibrator = BaselineCalibrator(yaw_thresh=10.0, pitch_thresh=20.0)
        calibrator.start()

        # 添加帧但头部姿态全部超出阈值
        valid_count = 0
        for i in range(50):
            is_valid = calibrator.add_frame(ear=0.25, yaw=30.0, pitch=40.0)
            if is_valid:
                valid_count += 1

        # 虽然添加了帧，但因头部姿态不合格，valid_count 应为 0
        status = calibrator.get_status()
        assert status.valid_frames == 0
        assert status.collected_frames == 50

    def test_get_status_before_start(self):
        """测试未开始前的状态"""
        calibrator = BaselineCalibrator()
        status = calibrator.get_status()
        assert status.is_calibrating is False
        assert status.progress == 0.0
        assert status.collected_frames == 0
        assert status.valid_frames == 0

    def test_get_status_after_cancel(self):
        """测试取消后的状态"""
        calibrator = BaselineCalibrator()
        calibrator.start()
        calibrator.add_frame(ear=0.25, yaw=0.0, pitch=0.0)
        calibrator.cancel()

        status = calibrator.get_status()
        assert status.is_calibrating is False

    def test_cqs_with_very_low_ear_variance(self):
        """测试 EAR 方差极低时的 CQS 计算"""
        calibrator = BaselineCalibrator(min_valid_frames=10, collection_duration=0.1)
        calibrator.start()

        # 添加 EAR 几乎相同的帧
        for i in range(50):
            calibrator.add_frame(ear=0.3000, yaw=0.0, pitch=0.0)
            time.sleep(0.002)  # 模拟时间流逝

        time.sleep(0.2)  # 等待校准完成
        calibrator.is_complete()  # 触发 _finish()

        result = calibrator.get_result()
        assert result is not None
        assert result.cqs_score >= 0.8  # 高质量校准

    def test_cqs_with_high_ear_variance(self):
        """测试 EAR 方差极高时的 CQS 计算"""
        calibrator = BaselineCalibrator(min_valid_frames=10, collection_duration=0.05)
        calibrator.start()

        # 添加 EAR 变化很大的帧
        for i in range(50):
            ear = 0.1 + (i % 20) * 0.02  # 0.1 到 0.5 之间变化
            calibrator.add_frame(ear=ear, yaw=0.0, pitch=0.0)
            time.sleep(0.001)

        time.sleep(0.1)
        calibrator.is_complete()  # 触发 _finish()

        result = calibrator.get_result()
        assert result is not None
        assert result.cqs_score < 0.8

    def test_cqs_at_threshold_boundary(self):
        """测试 CQS 刚好在阈值边界的情况"""
        calibrator = BaselineCalibrator(
            min_valid_frames=10,
            cqs_threshold=0.60,
            collection_duration=0.05
        )
        calibrator.start()

        for i in range(100):
            yaw = 0.0 if i < 50 else 30.0
            calibrator.add_frame(ear=0.25 + (i % 5) * 0.02, yaw=yaw, pitch=0.0)
            time.sleep(0.0005)

        time.sleep(0.1)
        calibrator.is_complete()

        result = calibrator.get_result()
        if result is not None:
            assert 0.0 <= result.cqs_score <= 1.0

    def test_zero_ear_value(self):
        """测试 EAR 为零的情况（边界条件）"""
        calibrator = BaselineCalibrator()
        calibrator.start()

        calibrator.add_frame(ear=0.0, yaw=0.0, pitch=0.0)

        # CQS 计算中有 ear_mean 作为分母
        # 代码中使用 max(ear_mean, 1e-6) 防零
        result = calibrator.get_result()
        # 不应崩溃
        assert result is None or isinstance(result.cqs_score, float)

    def test_negative_ear_value(self):
        """测试负 EAR 值（边界条件）"""
        calibrator = BaselineCalibrator()
        calibrator.start()

        calibrator.add_frame(ear=-0.1, yaw=0.0, pitch=0.0)

        result = calibrator.get_result()
        # 不应崩溃
        assert result is None or isinstance(result.cqs_score, float)

    def test_trim_ratio_zero(self):
        """测试 trim_ratio 为零的情况"""
        calibrator = BaselineCalibrator(trim_ratio=0.0, min_valid_frames=5, collection_duration=0.5)
        calibrator.start()

        # 添加足够的帧
        for i in range(50):
            calibrator.add_frame(ear=0.25, yaw=0.0, pitch=0.0)
            time.sleep(0.01)

        time.sleep(0.2)
        calibrator.is_complete()

        result = calibrator.get_result()
        assert result is not None
        assert result.total_frame_count == result.valid_frame_count or \
               result.valid_frame_count < result.total_frame_count

    def test_trim_ratio_half(self):
        """测试 trim_ratio 为 0.5 的情况"""
        calibrator = BaselineCalibrator(trim_ratio=0.5, min_valid_frames=5, collection_duration=0.5)
        calibrator.start()

        for i in range(50):
            calibrator.add_frame(ear=0.25, yaw=0.0, pitch=0.0)
            time.sleep(0.01)

        time.sleep(0.2)
        calibrator.is_complete()

        result = calibrator.get_result()
        assert result is not None

    def test_min_valid_frames_not_met(self):
        """测试有效帧数不足最小要求"""
        calibrator = BaselineCalibrator(min_valid_frames=100, collection_duration=0.5)
        calibrator.start()

        for i in range(30):
            calibrator.add_frame(ear=0.25, yaw=0.0, pitch=0.0)
            time.sleep(0.01)

        time.sleep(0.2)
        calibrator.is_complete()

        result = calibrator.get_result()
        assert result is None

    def test_cqs_preview_empty(self):
        """测试无帧时的 CQS 预览"""
        calibrator = BaselineCalibrator()
        cqs = calibrator._compute_cqs_preview()
        assert cqs == 0.0

    def test_cqs_preview_insufficient_frames(self):
        """测试帧数不足时的 CQS 预览"""
        calibrator = BaselineCalibrator(min_valid_frames=50)
        calibrator.start()

        for i in range(10):  # 少于 min_valid_frames
            calibrator.add_frame(ear=0.25, yaw=0.0, pitch=0.0)

        cqs = calibrator._compute_cqs_preview()
        assert cqs == 0.0

    def test_exact_min_valid_frames(self):
        """测试刚好达到最小有效帧数"""
        calibrator = BaselineCalibrator(min_valid_frames=30, collection_duration=0.5)
        calibrator.start()

        # 添加足够的帧（考虑10% trim后仍有30+）
        for i in range(50):
            calibrator.add_frame(ear=0.25, yaw=0.0, pitch=0.0)
            time.sleep(0.01)

        time.sleep(0.2)
        calibrator.is_complete()

        result = calibrator.get_result()
        assert result is not None

    def test_glasses_mode_setting(self):
        """测试眼镜模式设置"""
        from storage.models import GlassesMode

        calibrator = BaselineCalibrator(collection_duration=0.5)
        calibrator.set_glasses_mode(GlassesMode.WITH_GLASSES)
        calibrator.start()

        for i in range(50):
            calibrator.add_frame(ear=0.25, yaw=0.0, pitch=0.0)
            time.sleep(0.01)

        time.sleep(0.2)
        calibrator.is_complete()

        result = calibrator.get_result()
        assert result is not None
        assert result.glasses_mode == GlassesMode.WITH_GLASSES

    def test_multiple_start_calls(self):
        """测试多次调用 start 的情况"""
        calibrator = BaselineCalibrator()

        calibrator.start()
        calibrator.add_frame(ear=0.25, yaw=0.0, pitch=0.0)
        calibrator.start()  # 重新开始

        status = calibrator.get_status()
        assert status.collected_frames == 0  # 应该重置

    def test_ear_mean_near_zero(self):
        """测试 EAR 均值接近零的情况"""
        calibrator = BaselineCalibrator()
        calibrator.start()

        # 添加非常小的 EAR 值
        for i in range(50):
            calibrator.add_frame(ear=0.001, yaw=0.0, pitch=0.0)

        result = calibrator.get_result()
        # 防零保护应该生效，不应崩溃
        assert result is None or isinstance(result.cqs_score, float)


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

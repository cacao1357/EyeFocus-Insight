"""
tests/test_analyzer.py — Analyzer 模块单元测试 (v4.6 适配)
"""
import sys, os, time
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyzer.baseline import BaselineCalibrator, BaselineResult, create_baseline_calibrator
from analyzer.focus import FocusAnalyzer, FocusResult, FocusLevel, KalmanFilter1D, create_focus_analyzer
from analyzer.fatigue import FatigueAnalyzer, FatigueAnalysisResult, FatigueIndicator, create_fatigue_analyzer
from storage.models import GlassesMode


class TestBaselineCalibrator:
    def test_initial_state(self):
        calibrator = BaselineCalibrator()
        assert calibrator.get_result() is None
        assert calibrator.is_complete() is False

    def test_add_frame_valid(self):
        calibrator = BaselineCalibrator()
        calibrator.start()
        for _ in range(50):
            result = calibrator.add_frame(ear=0.25, yaw=0.0, pitch=0.0)

    def test_add_frame_immediate_complete(self):
        calibrator = BaselineCalibrator()
        calibrator.start()
        for i in range(100):
            ear = 0.25 + np.sin(i * 0.1) * 0.02
            calibrator.add_frame(ear=ear, yaw=0.0, pitch=0.0)
        result = calibrator.get_result()

    def test_get_result_before_start(self):
        calibrator = BaselineCalibrator()
        assert calibrator.get_result() is None

    def test_factory_function(self):
        calibrator = create_baseline_calibrator()
        assert isinstance(calibrator, BaselineCalibrator)


class TestKalmanFilter1D:
    def test_initial_state(self):
        kf = KalmanFilter1D()
        result = kf.update(10.0)
        assert 0.0 < result < 15.0

    def test_smoothing(self):
        kf = KalmanFilter1D()
        measurements = [100.0, 105.0, 95.0, 102.0, 98.0]
        results = [kf.update(m) for m in measurements]
        variance = np.var(results)
        input_variance = np.var(measurements)
        assert variance < input_variance

    def test_convergence(self):
        kf = KalmanFilter1D()
        for _ in range(100):
            kf.update(50.0)
        result = kf.update(50.0)
        assert abs(result - 50.0) < 1.0


class TestFocusAnalyzer:
    def test_initial_state(self):
        analyzer = FocusAnalyzer()
        stats = analyzer.get_stats()
        assert stats["current_level"] == "normal"

    def test_analyze_normal(self):
        analyzer = FocusAnalyzer(baseline_ear=0.25)
        result = analyzer.analyze(ear=0.25, yaw=0.0, pitch=0.0, face_detected=True)
        assert isinstance(result, FocusResult)
        assert result.focus_level in (FocusLevel.FOCUSED, FocusLevel.NORMAL)

    def test_analyze_no_face(self):
        analyzer = FocusAnalyzer()
        result = analyzer.analyze(ear=0.0, yaw=0.0, pitch=0.0, face_detected=False)
        assert result.focus_level != FocusLevel.FOCUSED

    def test_window_converges_to_focused(self):
        """v4.6: 30s 稳定睁眼 → FOCUSED（预填充窗口模拟 30s 数据）"""
        analyzer = FocusAnalyzer(baseline_ear=0.25)
        # 直接填充 30 个采样点（模拟 30s 稳定数据）
        analyzer._window_samples.extend([0.25 + (i % 3) * 0.01 for i in range(30)])
        result = analyzer.analyze(ear=0.25, yaw=0.0, pitch=0.0, face_detected=True)
        assert result.focus_level == FocusLevel.FOCUSED
        assert result.eye_openness > 0.9

    def test_factory_function(self):
        analyzer = create_focus_analyzer()
        assert isinstance(analyzer, FocusAnalyzer)


class TestFatigueAnalyzer:
    def test_initial_state(self):
        analyzer = FatigueAnalyzer()
        assert analyzer.get_stats()["cumulative_fatigue"] == 0.0

    def test_normal_returns_rested(self):
        """v4.6: 正常状态 → RESTED"""
        analyzer = FatigueAnalyzer()
        analyzer.start()
        result = analyzer.analyze(closure_type="open", blink_rate=15.0)
        assert result.fatigue_indicator == FatigueIndicator.RESTED

    def test_prolonged_closures_trigger_attention(self):
        """v4.45: 累计15s闭眼 → PERCLOS≈42 → ATTENTION"""
        analyzer = FatigueAnalyzer()
        analyzer.start()
        now = time.time()
        for i in range(8):
            analyzer._prolonged_events.append((now - i * 20, 1.8))
        result = analyzer.analyze(closure_type="open", blink_rate=15.0)
        assert result.fatigue_indicator == FatigueIndicator.ATTENTION

    def test_many_prolonged_trigger_tired(self):
        """v4.45: 持续闭眼30s + 实时加成 → PERCLOS 70×1.25=88 → TIRED"""
        analyzer = FatigueAnalyzer()
        analyzer.start()
        now = time.time()
        for i in range(5):
            analyzer._prolonged_events.append((now - i * 30, 6.0))
        result = analyzer.analyze(closure_type="prolonged", closure_duration=30.0,
                                  blink_rate=15.0)
        assert result.fatigue_indicator == FatigueIndicator.TIRED

    def test_start_reset(self):
        analyzer = FatigueAnalyzer()
        analyzer.start()
        assert analyzer.get_stats()["cumulative_fatigue"] == 0.0
        analyzer.analyze(closure_type="open", blink_rate=20.0)
        analyzer.reset()
        assert analyzer.get_stats()["cumulative_fatigue"] == 0.0

    def test_factory_function(self):
        analyzer = create_fatigue_analyzer()
        assert isinstance(analyzer, FatigueAnalyzer)

    def test_perclos_threshold_mild_default(self):
        """v4.6: perclos_threshold_mild 保持 8.0"""
        analyzer = create_fatigue_analyzer()
        assert analyzer.perclos_threshold_mild == 8.0

    def test_start_clears_recent_ear_head_blink_rate_M01(self):
        from analyzer.fatigue import create_fatigue_analyzer
        analyzer = create_fatigue_analyzer()
        analyzer.start()
        for _ in range(3):
            analyzer.analyze(closure_type="open", blink_rate=20.0, ear_nadir=0.10, head_stability=80.0)
        assert len(analyzer._recent_ear_nadirs) > 0
        assert len(analyzer._recent_head_stabilities) > 0
        assert analyzer._last_blink_rate != 0.0
        analyzer.start()
        assert len(analyzer._recent_ear_nadirs) == 0
        assert len(analyzer._recent_head_stabilities) == 0
        assert analyzer._last_blink_rate == 0.0

    def test_prolonged_deduplication(self):
        """v4.6: 同一 prolonged 事件不重复计数"""
        from analyzer.fatigue import create_fatigue_analyzer
        analyzer = create_fatigue_analyzer()
        analyzer.start()
        analyzer.analyze(closure_type="prolonged", blink_rate=15.0)
        analyzer.analyze(closure_type="prolonged", blink_rate=15.0)
        analyzer.analyze(closure_type="prolonged", blink_rate=15.0)
        assert len(analyzer._prolonged_events) == 1
        # 中间断开再 prolonged 应计数第二次
        analyzer.analyze(closure_type="open", blink_rate=15.0)
        analyzer.analyze(closure_type="prolonged", blink_rate=15.0)
        assert len(analyzer._prolonged_events) == 2

    def test_get_record_readonly(self):
        """v4.6: get_record 只读"""
        from analyzer.fatigue import create_fatigue_analyzer
        analyzer = create_fatigue_analyzer()
        analyzer.start()
        analyzer.analyze(closure_type="open", blink_rate=15.0)
        record = analyzer.get_record("test", timestamp=time.time())
        assert record is not None


class TestMultiSignalFocusLevel:
    """v4.34: 多信号门控 — 高频眨眼 + 视线注视 ≠ 分心"""

    def test_high_blink_with_gaze_head_stays_normal(self):
        """EAR 偏离 8s+ 但视线注视 + 头部稳定 → NORMAL"""
        from analyzer.focus import FocusLevel
        analyzer = FocusAnalyzer(baseline_ear=0.25)
        # 8 个偏离样本 (> DISTRACTED_MIN_DEVIATION_SECS)
        analyzer._window_samples.extend([0.15] * 8)
        analyzer._window_samples.extend([0.25] * 7)
        result = analyzer.analyze(ear=0.15, yaw=0.0, pitch=0.0,
                                  gaze_score=90.0, face_detected=True)
        assert result.focus_level == FocusLevel.NORMAL

    def test_high_blink_with_low_gaze_stays_distracted(self):
        """EAR 偏离 8s+ + 视线偏离 → 仍是 DISTRACTED"""
        from analyzer.focus import FocusLevel
        analyzer = FocusAnalyzer(baseline_ear=0.25)
        analyzer._window_samples.extend([0.15] * 8)
        analyzer._window_samples.extend([0.25] * 7)
        result = analyzer.analyze(ear=0.15, yaw=0.0, pitch=0.0,
                                  gaze_score=20.0, face_detected=True)
        assert result.focus_level == FocusLevel.DISTRACTED

    def test_high_blink_with_head_turned_stays_distracted(self):
        """EAR 偏离 8s+ + 头部偏转 → 仍是 DISTRACTED"""
        from analyzer.focus import FocusLevel
        analyzer = FocusAnalyzer(baseline_ear=0.25)
        analyzer._window_samples.extend([0.15] * 8)
        analyzer._window_samples.extend([0.25] * 7)
        result = analyzer.analyze(ear=0.15, yaw=35.0, pitch=0.0,
                                  gaze_score=90.0, face_detected=True)
        assert result.focus_level == FocusLevel.DISTRACTED


class TestFocusAnalyzerBaselineZero:
    """v4.6: baseline_ear=0 不崩溃"""

    def test_baseline_ear_zero_no_crash(self):
        analyzer = FocusAnalyzer(baseline_ear=0.0)
        result = analyzer.analyze(ear=0.25, yaw=0.0, pitch=0.0, face_detected=True)
        assert isinstance(result, FocusResult)
        assert result.focus_level == FocusLevel.NORMAL

    def test_baseline_ear_negative_no_crash(self):
        analyzer = FocusAnalyzer(baseline_ear=-1.0)
        result = analyzer.analyze(ear=0.25, yaw=0.0, pitch=0.0, face_detected=True)
        assert isinstance(result, FocusResult)
        assert result.focus_level == FocusLevel.NORMAL

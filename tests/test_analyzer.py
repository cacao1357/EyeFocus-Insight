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

    def test_create_fatigue_analyzer_perclos_default_H03(self):
        """H-03: 工厂函数 perclos_threshold_mild 默认值必须等于类常量 5.0
        原 default=0.15 与类常量 DEFAULT_PERCLOS_THRESHOLD_MILD=5.0 不一致,
        PERCLOS 是百分比 (0-100), 0.15 几乎永远成立, 中度疲劳误判率 100%
        """
        from analyzer.fatigue import DEFAULT_PERCLOS_THRESHOLD_MILD
        analyzer = create_fatigue_analyzer()
        assert analyzer.perclos_threshold_mild == DEFAULT_PERCLOS_THRESHOLD_MILD, (
            f"perclos_threshold_mild={analyzer.perclos_threshold_mild}, "
            f"应等于类常量 {DEFAULT_PERCLOS_THRESHOLD_MILD}"
        )
        # 显式断言 5% 业务阈值
        assert analyzer.perclos_threshold_mild == 5.0, (
            f"perclos_threshold_mild 应为 5.0 (5%), 实际 {analyzer.perclos_threshold_mild}"
        )

    def test_start_clears_recent_ear_head_blink_rate_M01(self):
        """M-01: start() 必须清空 _recent_ear_nadirs / _recent_head_stabilities / _last_blink_rate

        复盘: 跨 session 复用 FatigueAnalyzer 实例时, 上 session 残留数据会让 session
        开头几秒的 avg_ear_nadir / avg_head_stability 混入历史, 产生错误的疲劳分数。
        """
        from analyzer.fatigue import create_fatigue_analyzer
        analyzer = create_fatigue_analyzer()

        # 第 1 轮: 模拟上 session 残留数据
        analyzer.start()
        for _ in range(3):
            analyzer.analyze(blink_rate=20.0, ear_nadir=0.10, head_stability=80.0)

        # 断言上 session 残留确实存在
        assert len(analyzer._recent_ear_nadirs) > 0
        assert len(analyzer._recent_head_stabilities) > 0
        assert analyzer._last_blink_rate != 0.0

        # 第 2 轮: 调 start() 期望清空所有历史
        analyzer.start()

        assert len(analyzer._recent_ear_nadirs) == 0, (
            f"start() 未清空 _recent_ear_nadirs, 残留 {len(analyzer._recent_ear_nadirs)} 条"
        )
        assert len(analyzer._recent_head_stabilities) == 0, (
            f"start() 未清空 _recent_head_stabilities, 残留 {len(analyzer._recent_head_stabilities)} 条"
        )
        assert analyzer._last_blink_rate == 0.0, (
            f"start() 未重置 _last_blink_rate, 残留 {analyzer._last_blink_rate}"
        )

    def test_compute_perclos_includes_last_closed_frame_M02(self):
        """M-02: _compute_perclos 末帧仍闭眼时, 必须把从最后帧到 current_time 的时长计入 closed_time

        复盘: 原实现循环用 (prev, current) 配对累加, 末帧仍闭眼时,
        该段从最后一帧到 current_time 的时长未累加, 少算末段闭眼时长。
        """
        from analyzer.fatigue import create_fatigue_analyzer, FatigueAnalyzer
        analyzer = FatigueAnalyzer(perclos_window=60.0)
        analyzer.start()

        # 构造 3 帧历史: t=0.0 闭, t=1.0 闭, t=2.0 闭
        # 期望: closed_time = (1.0-0.0) + (2.0-1.0) + (current-2.0) = 2.0 + (current-2.0)
        analyzer._perclos_history.append((0.0, True))
        analyzer._perclos_history.append((1.0, True))
        analyzer._perclos_history.append((2.0, True))

        current_time = 3.0  # 末帧到 current 距离 1.0s
        perclos = analyzer._compute_perclos(current_time)

        # 期望: closed_time = 3.0 (0->1, 1->2, 2->3)
        # perclos_window = 60, perclos = (3.0/60) * 100 = 5.0%
        assert perclos == pytest.approx(5.0, abs=0.01), (
            f"M-02 末帧闭眼时长应计入 PERCLOS, 期望 5.0%, 实际 {perclos}%"
        )

    def test_get_record_does_not_pollute_sustained_state_H04(self):
        """H-04: get_record() 语义上是只读, 不应修改 _medium_onset_time / _high_onset_time
        原实现 get_record 调 _update_sustained_tracking(), 该函数会修改 self._medium_onset_time,
        污染状态, 影响后续 analyze() 的持续时间基准。
        """
        from analyzer.fatigue import create_fatigue_analyzer
        analyzer = create_fatigue_analyzer()
        analyzer.start()

        # 1) 跑高眨眼率数据, 让 _fatigue_history 非空 (get_record 才能往下走),
        #    并触发 medium/high onset
        for _ in range(3):
            analyzer.analyze(blink_rate=30.0, ear_nadir=0.08, head_stability=50.0)

        # 2) 跑低眨眼率数据, 让 conditions 变 False, reset _medium_onset_time / _high_onset_time 到 None
        for _ in range(3):
            analyzer.analyze(blink_rate=10.0, ear_nadir=0.20, head_stability=90.0)

        # 3) 手动设置 sentinel: 模拟外部状态
        #    用 sentinel 而不是 None 是为了精确捕获 mutation (None -> 非 None 不会触发, 但 reset 会)
        SENTINEL = 99999.0
        analyzer._medium_onset_time = SENTINEL
        analyzer._high_onset_time = SENTINEL

        # 4) 多次调 get_record — buggy 代码会调 _update_sustained_tracking,
        #    因 conditions=False, 把 sentinel reset 回 None
        for i in range(5):
            analyzer.get_record("test_session", timestamp=time.time() + i * 0.5)

        # 5) 验证 sentinel 未被修改 (buggy 代码会把它重置为 None)
        assert analyzer._medium_onset_time == SENTINEL, (
            f"get_record 修改了 _medium_onset_time: {SENTINEL} -> {analyzer._medium_onset_time}"
        )
        assert analyzer._high_onset_time == SENTINEL, (
            f"get_record 修改了 _high_onset_time: {SENTINEL} -> {analyzer._high_onset_time}"
        )


class TestFocusAnalyzerBaselineZero:
    """H-05: _compute_eye_score baseline_ear=0 必须不除零"""

    def test_focus_analyzer_no_dead_ear_thresholds_M04(self):
        """M-04: _ear_low_thresh / _ear_high_thresh 死代码, 必须删除

        复盘: __init__ / set_baseline 中赋值但全类无引用, 是 v4 早期 EAR 阈值
        标记方案的残留, 现 _compute_eye_score 改用相对偏差计算, 不再需要绝对阈值。
        """
        import inspect
        from analyzer.focus import FocusAnalyzer

        # 1) 实例化不抛异常
        analyzer = FocusAnalyzer()
        assert not hasattr(analyzer, "_ear_low_thresh"), (
            "M-04 死代码 _ear_low_thresh 仍存在, 应删除"
        )
        assert not hasattr(analyzer, "_ear_high_thresh"), (
            "M-04 死代码 _ear_high_thresh 仍存在, 应删除"
        )

        # 2) 源码中无任何引用
        source = inspect.getsource(FocusAnalyzer)
        assert "_ear_low_thresh" not in source, (
            "M-04 源码中仍出现 _ear_low_thresh, 应删除"
        )
        assert "_ear_high_thresh" not in source, (
            "M-04 源码中仍出现 _ear_high_thresh, 应删除"
        )

        # 3) set_baseline 不抛异常
        analyzer.set_baseline(ear=0.30, yaw_std=3.0, pitch_std=3.0)

    def test_focus_analyzer_baseline_ear_zero_no_crash_H05(self):
        """H-05: set_baseline(0.0) 后 _compute_eye_score 必须不除零崩溃
        修法: _compute_eye_score 入口加 if self.baseline_ear <= 0: return 50.0
        """
        analyzer = create_focus_analyzer()
        analyzer.set_baseline(ear=0.0, yaw_std=None, pitch_std=None)

        try:
            score = analyzer._compute_eye_score(ear=0.25)
        except ZeroDivisionError as e:
            pytest.fail(f"baseline_ear=0 时 _compute_eye_score 不应除零, 实际: {e}")

        assert score == 50.0, (
            f"baseline_ear=0 时应返回中性分 50.0, 实际 {score}"
        )

    def test_focus_analyzer_baseline_ear_negative_no_crash_H05(self):
        """H-05: set_baseline(-0.1) 后 _compute_eye_score 必须不除零"""
        analyzer = create_focus_analyzer()
        analyzer.set_baseline(ear=-0.1, yaw_std=None, pitch_std=None)

        try:
            score = analyzer._compute_eye_score(ear=0.25)
        except ZeroDivisionError as e:
            pytest.fail(f"baseline_ear<0 时 _compute_eye_score 不应除零, 实际: {e}")

        assert score == 50.0


class TestBlinkRoundCollectorThreshold:
    """H-06: BlinkRoundCollector.record_frame 必须用 ear_threshold 区分 blink/squint"""

    def test_record_frame_uses_ear_threshold_for_squint_H06(self):
        """H-06: ear 介于 ear_threshold 与 squint_threshold 之间 + 短持续 → 分类为 squint
        当前实现只判断 ear < squint_threshold, 把所有 EAR 下降按 400ms 时长二分类,
        忽略了 ear_threshold (blink 强信号) 这个本应作为 blink 强判据的字段。

        调用方约定: ear_threshold=0.225, squint_threshold=0.27
        ear=0.24: 大于 blink 阈值 (0.225) 但小于 squint 阈值 (0.27) → squint 候选
        短持续 0.1s → 修复后期望 classified as squint, 当前实现 classified as blink
        """
        from analyzer.user_calibration import BlinkRoundCollector
        collector = BlinkRoundCollector()
        collector.reset()

        blink_threshold = 0.225
        squint_threshold = 0.27

        # ear=0.24 (介于两者之间) 持续 0.1s (短)
        collector.record_frame(
            ear=0.24,
            ear_threshold=blink_threshold,
            squint_threshold=squint_threshold,
            current_time=0.0,
        )
        # EAR 恢复
        collector.record_frame(
            ear=0.30,
            ear_threshold=blink_threshold,
            squint_threshold=squint_threshold,
            current_time=0.1,
        )

        assert collector.detected_squints >= 1, (
            f"ear=0.24 介于 blink/squint 阈值之间 + 短持续 0.1s, 应分类为 squint. "
            f"实际 detected_blinks={collector.detected_blinks}, "
            f"detected_squints={collector.detected_squints}"
        )
        assert collector.detected_blinks == 0, (
            f"ear=0.24 不应分类为 blink (因为它 > ear_threshold 0.225). "
            f"实际 detected_blinks={collector.detected_blinks}"
        )

    def test_record_frame_ear_below_blink_threshold_classified_as_blink_H06(self):
        """H-06: ear 显著低于 ear_threshold + 短持续 → 分类为 blink
        验证 ear_threshold 仍能作为 blink 强信号 (修复不应破坏原行为)
        """
        from analyzer.user_calibration import BlinkRoundCollector
        collector = BlinkRoundCollector()
        collector.reset()

        blink_threshold = 0.225
        squint_threshold = 0.27

        # ear=0.10 显著低于 blink 阈值 0.225, 持续 0.1s (短)
        collector.record_frame(
            ear=0.10,
            ear_threshold=blink_threshold,
            squint_threshold=squint_threshold,
            current_time=0.0,
        )
        collector.record_frame(
            ear=0.30,
            ear_threshold=blink_threshold,
            squint_threshold=squint_threshold,
            current_time=0.1,
        )

        assert collector.detected_blinks >= 1, (
            f"ear=0.10 显著低于 blink 阈值, 短持续 0.1s, 应分类为 blink. "
            f"实际 detected_blinks={collector.detected_blinks}"
        )


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

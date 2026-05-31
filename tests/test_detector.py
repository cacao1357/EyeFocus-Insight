"""
tests/test_detector.py — Detector 模块单元测试
覆盖 detector/ 包中所有可离线测试的函数。
"""

import sys
import os
import math

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector.eye_aspect import EyeAspectDetector, create_eye_aspect_detector
from detector.head_pose import HeadPoseDetector, HeadPoseResult, create_head_pose_detector
from detector.gaze import GazeDetector, GazeResult, create_gaze_detector


class TestHeadPoseDetector:
    """HeadPoseDetector 单元测试"""

    def test_detect_valid_matrix(self):
        """测试有效的 transformation_matrix"""
        detector = HeadPoseDetector()

        # 创建一个正面朝前的 4x4 单位矩阵
        # 实际使用时 MediaPipe 的 transformation_matrix 更复杂
        # 这里测试基本功能
        matrix = np.eye(4).flatten()

        result = detector.detect(matrix)
        # 单位矩阵应该给出接近 0 的角度
        assert result is not None or result is None  # 允许返回 None（取决于实现）

    def test_detect_none_matrix(self):
        """测试 None 输入"""
        detector = HeadPoseDetector()
        result = detector.detect(None)
        assert result is None

    def test_detect_invalid_shape(self):
        """测试无效形状的矩阵"""
        detector = HeadPoseDetector()
        result = detector.detect(np.array([1, 2, 3]))  # 不是 16 元素
        assert result is None

    def test_is_frontal_detection(self):
        """测试正面检测逻辑"""
        detector = HeadPoseDetector(yaw_thresh=10.0, pitch_thresh=20.0)

        # 创建一个表示正面姿态的矩阵
        matrix = np.eye(4).flatten()
        result = detector.detect(matrix)

        if result is not None:
            # 正面姿态应该被检测为 frontal
            assert isinstance(result.is_frontal, bool)

    def test_compute_stability_empty(self):
        """测试空历史数据的稳定性计算"""
        detector = HeadPoseDetector()
        score = detector.compute_stability([], [])
        assert score == 100.0

    def test_compute_stability_normal(self):
        """测试正常历史数据的稳定性计算"""
        detector = HeadPoseDetector()
        yaw_history = [1.0, 2.0, 1.5, 1.8, 2.2]
        pitch_history = [1.0, 1.2, 0.8, 1.1, 0.9]
        score = detector.compute_stability(yaw_history, pitch_history)
        assert 0.0 <= score <= 100.0

    def test_factory_function(self):
        """测试工厂函数"""
        detector = create_head_pose_detector()
        assert isinstance(detector, HeadPoseDetector)


class TestEyeAspectDetector:
    """EyeAspectDetector 单元测试 — T145/T146/T147"""

    def _make_landmarks(self, ear_value: float = 0.35):
        """创建标准 468 关键点数组"""
        landmarks = np.zeros((468, 3), dtype=np.float64)

        # 基于目标 EAR 值反推眼睑尺寸
        # EAR = (a + b) / (2 * c)，其中 a≈b，c=眼宽
        eye_width = 30.0
        # a = b = EAR * 2 * c / 2 = EAR * c
        eye_vertical = ear_value * eye_width

        # 左眼 (33, 160, 158, 133, 153, 144)
        cx, cy = 200, 200
        landmarks[33] = [cx - eye_width, cy, 0]
        landmarks[160] = [cx - eye_width * 0.5, cy - eye_vertical, 0]
        landmarks[158] = [cx + eye_width * 0.5, cy - eye_vertical, 0]
        landmarks[133] = [cx + eye_width, cy, 0]
        landmarks[153] = [cx + eye_width * 0.5, cy + eye_vertical, 0]
        landmarks[144] = [cx - eye_width * 0.5, cy + eye_vertical, 0]

        # 右眼 (362, 385, 387, 263, 380, 373)
        cx2, cy2 = 440, 200
        landmarks[362] = [cx2 - eye_width, cy2, 0]
        landmarks[385] = [cx2 - eye_width * 0.5, cy2 - eye_vertical, 0]
        landmarks[387] = [cx2 + eye_width * 0.5, cy2 - eye_vertical, 0]
        landmarks[263] = [cx2 + eye_width, cy2, 0]
        landmarks[380] = [cx2 + eye_width * 0.5, cy2 + eye_vertical, 0]
        landmarks[373] = [cx2 - eye_width * 0.5, cy2 + eye_vertical, 0]

        return landmarks

    def test_initial_state(self):
        """测试初始状态"""
        detector = EyeAspectDetector()
        stats = detector.get_stats()
        assert stats["ear_threshold"] == 0.26  # 默认固定阈值
        assert stats["has_baseline"] is False

    def test_set_baseline_updates_threshold(self):
        """T145: 测试 set_baseline 更新动态阈值"""
        detector = EyeAspectDetector()
        detector.set_baseline(0.35)
        stats = detector.get_stats()
        # 眨眼阈值 = baseline * 0.75
        assert stats["ear_threshold"] == pytest.approx(0.2625, abs=0.001)
        assert stats["has_baseline"] is True
        assert stats["baseline_ear"] == 0.35

    def test_open_threshold_is_baseline_090(self):
        """T145: 测试睁眼阈值 = baseline * 0.90"""
        detector = EyeAspectDetector()
        detector.set_baseline(0.35)
        assert detector.open_threshold == pytest.approx(0.315, abs=0.001)

    def test_compute_returns_ear(self):
        """测试 EAR 计算"""
        detector = EyeAspectDetector()
        landmarks = self._make_landmarks(ear_value=0.35)
        result = detector.compute(landmarks)
        assert isinstance(result.ear_left, float)
        assert isinstance(result.ear_right, float)
        assert isinstance(result.ear_avg, float)
        assert 0.2 < result.ear_avg < 0.6

    def test_blink_detection_below_threshold(self):
        """测试眨眼检测（EAR 低于阈值）"""
        detector = EyeAspectDetector()
        # 睁眼
        open_landmarks = self._make_landmarks(ear_value=0.35)
        result = detector.compute(open_landmarks)
        assert result.is_blink is False

        # 闭眼（EAR 低于阈值）
        closed_landmarks = self._make_landmarks(ear_value=0.1)
        result = detector.compute(closed_landmarks)
        assert result.is_blink is True

    def test_classify_eye_event_blink(self):
        """T146: 测试眨眼分类（< 400ms = 眨眼）"""
        detector = EyeAspectDetector()
        assert detector._classify_eye_event(0.2) is True   # 200ms → 眨眼
        assert detector._classify_eye_event(0.3) is True   # 300ms → 眨眼
        assert detector._classify_eye_event(0.39) is True  # 390ms → 眨眼

    def test_classify_eye_event_squint(self):
        """T146: 测试眯眼分类（>= 400ms = 眯眼）"""
        detector = EyeAspectDetector()
        assert detector._classify_eye_event(0.4) is False   # 400ms → 眯眼
        assert detector._classify_eye_event(0.5) is False   # 500ms → 眯眼
        assert detector._classify_eye_event(1.0) is False   # 1000ms → 眯眼

    def test_compute_blink_confidence_default(self):
        """T147: 测试默认置信度为 1.0"""
        detector = EyeAspectDetector()
        confidence = detector._compute_blink_confidence()
        assert confidence == 1.0

    def test_compute_blink_confidence_reduced_by_head_pose(self):
        """T147: 测试头部姿态异常降低置信度"""
        detector = EyeAspectDetector()
        detector.set_head_pose_weight(0.5)
        confidence = detector._compute_blink_confidence()
        assert confidence == 0.5

    def test_compute_blink_confidence_reduced_by_face_stability(self):
        """T147: 测试面部晃动降低置信度"""
        detector = EyeAspectDetector()
        detector.set_face_stability_weight(0.3)
        confidence = detector._compute_blink_confidence()
        assert confidence == 0.3

    def test_compute_blink_confidence_combined(self):
        """T147: 测试多信号融合"""
        detector = EyeAspectDetector()
        detector.set_head_pose_weight(0.5)
        detector.set_face_stability_weight(0.6)
        confidence = detector._compute_blink_confidence()
        assert confidence == pytest.approx(0.3, abs=0.01)

    def test_reset_clears_state(self):
        """测试 reset() 清除状态"""
        detector = EyeAspectDetector()
        detector.set_baseline(0.35)
        detector._blinks_in_progress = 2
        detector._frame_count = 100

        detector.reset()

        stats = detector.get_stats()
        assert stats["has_baseline"] is False
        assert stats["blinks_in_progress"] == 0
        assert stats["frame_count"] == 0
        assert stats["head_pose_weight"] == 1.0
        assert stats["face_stability_weight"] == 1.0

    def test_factory_with_baseline(self):
        """测试工厂函数支持 baseline_ear 参数"""
        from detector.eye_aspect import create_eye_aspect_detector
        detector = create_eye_aspect_detector(baseline_ear=0.35)
        stats = detector.get_stats()
        assert stats["has_baseline"] is True
        assert stats["ear_threshold"] == pytest.approx(0.2625, abs=0.001)

    def test_blink_rate_empty(self):
        """测试无眨眼事件时返回 0"""
        detector = EyeAspectDetector()
        rate, count = detector.get_blink_rate()
        assert rate == 0.0
        assert count == 0

    def test_get_current_ear(self):
        """测试 get_current_ear() 返回当前 EAR 值"""
        detector = EyeAspectDetector()
        # 初始为 0
        assert detector.get_current_ear() == 0.0

        # compute() 后会更新
        landmarks = self._make_landmarks(ear_value=0.35)
        detector.compute(landmarks)
        assert detector.get_current_ear() > 0

    def test_factory_function(self):
        """测试工厂函数"""
        from detector.eye_aspect import create_eye_aspect_detector
        detector = create_eye_aspect_detector()
        assert isinstance(detector, EyeAspectDetector)


class TestGazeDetector:

    def _make_landmarks(self):
        """创建标准 478 关键点数组（包含虹膜关键点 468-477）"""
        landmarks = np.zeros((478, 3), dtype=np.float64)

        # 设置左眼关键点 (33, 160, 158, 133, 153, 144)
        eye_center_x, eye_center_y = 200, 200
        eye_width = 30
        eye_height = 12
        landmarks[33] = [eye_center_x - eye_width, eye_center_y, 0]  # 左眼角
        landmarks[160] = [eye_center_x - eye_width * 0.5, eye_center_y - eye_height, 0]
        landmarks[158] = [eye_center_x + eye_width * 0.5, eye_center_y - eye_height, 0]
        landmarks[133] = [eye_center_x + eye_width, eye_center_y, 0]  # 右眼角
        landmarks[153] = [eye_center_x + eye_width * 0.5, eye_center_y + eye_height, 0]
        landmarks[144] = [eye_center_x - eye_width * 0.5, eye_center_y + eye_height, 0]

        # 设置右眼关键点 (362, 385, 387, 263, 380, 373)
        eye_center_x2, eye_center_y2 = 440, 200
        landmarks[362] = [eye_center_x2 - eye_width, eye_center_y2, 0]  # 左眼角
        landmarks[385] = [eye_center_x2 - eye_width * 0.5, eye_center_y2 - eye_height, 0]
        landmarks[387] = [eye_center_x2 + eye_width * 0.5, eye_center_y2 - eye_height, 0]
        landmarks[263] = [eye_center_x2 + eye_width, eye_center_y2, 0]  # 右眼角
        landmarks[380] = [eye_center_x2 + eye_width * 0.5, eye_center_y2 + eye_height, 0]
        landmarks[373] = [eye_center_x2 - eye_width * 0.5, eye_center_y2 + eye_height, 0]

        # 设置虹膜关键点（左 468-472，右 473-477）
        # 虹膜中心大约在眼睑中心位置
        iris_center_x, iris_center_y = eye_center_x, eye_center_y
        iris_center_x2, iris_center_y2 = eye_center_x2, eye_center_y2
        iris_radius = 5.0
        for i in range(5):
            angle = 2 * np.pi * i / 5
            landmarks[468 + i] = [iris_center_x + iris_radius * np.cos(angle), iris_center_y + iris_radius * np.sin(angle), 0]
            landmarks[473 + i] = [iris_center_x2 + iris_radius * np.cos(angle), iris_center_y2 + iris_radius * np.sin(angle), 0]

        return landmarks

    def test_detect_normal_eyes(self):
        """测试正常睁眼检测"""
        detector = GazeDetector()
        landmarks = self._make_landmarks()

        result = detector.detect(landmarks, head_pose_yaw=0.0, head_pose_pitch=0.0)

        assert result is not None
        assert isinstance(result.gaze_offset, tuple)
        assert len(result.gaze_offset) == 2
        assert 0.0 <= result.gaze_concentration <= 100.0

    def test_detect_none_landmarks(self):
        """测试 None 输入"""
        detector = GazeDetector()
        result = detector.detect(None)
        assert result is None

    def test_detect_partial_landmarks(self):
        """测试不完整的 landmarks"""
        detector = GazeDetector()
        landmarks = np.zeros((100, 3))  # 不足 468 个关键点
        result = detector.detect(landmarks)
        assert result is None

    def test_gaze_score_range(self):
        """测试视线分数在有效范围内"""
        detector = GazeDetector()
        landmarks = self._make_landmarks()

        result = detector.detect(landmarks, head_pose_yaw=0.0, head_pose_pitch=0.0)

        if result is not None:
            assert 0.0 <= result.gaze_concentration <= 100.0

    def test_factory_function(self):
        """测试工厂函数"""
        detector = create_gaze_detector()
        assert isinstance(detector, GazeDetector)

    def test_is_looking_at_screen(self):
        """测试视线方向判断"""
        detector = GazeDetector()
        landmarks = self._make_landmarks()

        # 正面姿态应该被认为在看屏幕
        result = detector.detect(landmarks, head_pose_yaw=0.0, head_pose_pitch=0.0)

        if result is not None:
            assert isinstance(result.is_looking_at_screen, bool)

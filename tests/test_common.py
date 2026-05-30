"""
EyeFocus Insight — 核心算法单元测试
覆盖 spike/common.py 中所有可离线测试的函数。
"""

import sys
import os
import math

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spike.common import (
    MODEL_POINTS,
    LANDMARK_INDICES,
    calculate_ear,
    calc_cqs,
    get_camera_matrix,
    solve_head_pose,
)


class TestModelPoints:
    def test_y_axis_direction_matches_opencv(self):
        assert MODEL_POINTS[1][1] > 0, "下巴 Y 应为正（OpenCV Y-down）"
        assert MODEL_POINTS[2][1] < 0, "左眼角 Y 应为负（OpenCV Y-down）"
        assert MODEL_POINTS[3][1] < 0, "右眼角 Y 应为负（OpenCV Y-down）"
        assert MODEL_POINTS[4][1] > 0, "左嘴角 Y 应为正（OpenCV Y-down）"
        assert MODEL_POINTS[5][1] > 0, "右嘴角 Y 应为正（OpenCV Y-down）"

    def test_chin_below_eyes(self):
        assert MODEL_POINTS[1][1] > MODEL_POINTS[2][1], "下巴应在眼睛下方（Y更大）"

    def test_symmetry(self):
        assert MODEL_POINTS[2][0] == -MODEL_POINTS[3][0], "左右眼 X 对称"
        assert MODEL_POINTS[4][0] == -MODEL_POINTS[5][0], "左右嘴角 X 对称"

    def test_nose_at_origin(self):
        assert MODEL_POINTS[0][0] == 0.0
        assert MODEL_POINTS[0][1] == 0.0
        assert MODEL_POINTS[0][2] == 0.0


class TestSolveHeadPose:
    def _make_frontal_image_points(self, img_w=640, img_h=480):
        return np.array([
            (img_w / 2, img_h * 0.42),
            (img_w / 2, img_h * 0.73),
            (img_w * 0.34, img_h * 0.38),
            (img_w * 0.66, img_h * 0.38),
            (img_w * 0.39, img_h * 0.63),
            (img_w * 0.61, img_h * 0.63),
        ], dtype=np.float64)

    def test_frontal_face_yaw_near_zero(self):
        img_w, img_h = 640, 480
        camera_matrix = get_camera_matrix(img_w, img_h)
        image_points = self._make_frontal_image_points(img_w, img_h)
        landmarks = np.zeros((468, 2), dtype=np.float64)
        for i, idx in enumerate(LANDMARK_INDICES):
            landmarks[idx] = image_points[i]
        yaw, pitch, roll = solve_head_pose(landmarks, camera_matrix)
        assert yaw is not None
        assert abs(yaw) < 5.0, f"正面人脸 yaw 应接近 0, 实际: {yaw:.1f}"

    def test_frontal_face_pitch_near_zero(self):
        img_w, img_h = 640, 480
        camera_matrix = get_camera_matrix(img_w, img_h)
        image_points = self._make_frontal_image_points(img_w, img_h)
        landmarks = np.zeros((468, 2), dtype=np.float64)
        for i, idx in enumerate(LANDMARK_INDICES):
            landmarks[idx] = image_points[i]
        yaw, pitch, roll = solve_head_pose(landmarks, camera_matrix)
        assert pitch is not None
        assert abs(pitch) < 10.0, f"正面人脸 pitch 应接近 0, 实际: {pitch:.1f}"

    def test_frontal_face_roll_near_zero(self):
        img_w, img_h = 640, 480
        camera_matrix = get_camera_matrix(img_w, img_h)
        image_points = self._make_frontal_image_points(img_w, img_h)
        landmarks = np.zeros((468, 2), dtype=np.float64)
        for i, idx in enumerate(LANDMARK_INDICES):
            landmarks[idx] = image_points[i]
        _, _, roll = solve_head_pose(landmarks, camera_matrix)
        assert roll is not None
        assert abs(roll) < 45.0, f"正面人脸 roll 应接近 0, 实际: {roll:.1f}"

    def test_turn_left_positive_yaw(self):
        img_w, img_h = 640, 480
        camera_matrix = get_camera_matrix(img_w, img_h)
        image_points = self._make_frontal_image_points(img_w, img_h)
        left_eye_x = image_points[2][0]
        right_eye_x = image_points[3][0]
        shift = (right_eye_x - left_eye_x) * 0.3
        image_points[2][0] += shift
        image_points[4][0] += shift * 0.5
        image_points[3][0] -= shift * 0.3
        landmarks = np.zeros((468, 2), dtype=np.float64)
        for i, idx in enumerate(LANDMARK_INDICES):
            landmarks[idx] = image_points[i]
        yaw, _, _ = solve_head_pose(landmarks, camera_matrix)
        assert yaw is not None
        assert abs(yaw) > 3.0, f"转头应产生非零 yaw, 实际: {yaw:.1f}"

    def test_degenerate_points_returns_none(self):
        img_w, img_h = 640, 480
        camera_matrix = get_camera_matrix(img_w, img_h)
        landmarks = np.zeros((468, 2), dtype=np.float64)
        for idx in LANDMARK_INDICES:
            landmarks[idx] = [320.0, 240.0]
        yaw, pitch, roll = solve_head_pose(landmarks, camera_matrix)
        assert yaw is None
        assert pitch is None
        assert roll is None


class TestCalculateEar:
    def _make_open_eye(self, center=(320, 200), w=30, h=12):
        cx, cy = center
        return np.array([
            [cx - w, cy],
            [cx - w * 0.5, cy - h],
            [cx + w * 0.5, cy - h],
            [cx + w, cy],
            [cx + w * 0.5, cy + h],
            [cx - w * 0.5, cy + h],
        ])

    def test_open_eye_ear_in_range(self):
        pts = self._make_open_eye()
        ear = calculate_ear(pts)
        assert 0.2 < ear < 0.6, f"睁眼 EAR 应在 0.2-0.6, 实际: {ear:.4f}"

    def test_closed_eye_ear_near_zero(self):
        pts = self._make_open_eye(h=1)
        ear = calculate_ear(pts)
        assert ear < 0.1, f"闭眼 EAR 应 < 0.1, 实际: {ear:.4f}"

    def test_zero_denominator_returns_zero(self):
        pts = np.array([
            [0.0, 0.0],
            [0.0, 1.0],
            [0.0, 2.0],
            [0.0, 0.0],
            [0.0, 2.0],
            [0.0, 1.0],
        ])
        ear = calculate_ear(pts)
        assert ear == 0.0

    def test_left_right_symmetry(self):
        left_pts = self._make_open_eye(center=(200, 200))
        right_pts = self._make_open_eye(center=(440, 200))
        ear_left = calculate_ear(left_pts)
        ear_right = calculate_ear(right_pts)
        assert abs(ear_left - ear_right) < 0.01


class TestCalcCqs:
    def test_perfect_data(self):
        cqs = calc_cqs(100, 100, 0.0)
        assert cqs == 1.0

    def test_all_invalid_frames(self):
        cqs = calc_cqs(0, 100, 0.0)
        assert cqs == 0.5

    def test_high_cv_penalty(self):
        # ear_cv=0.2: cv_score = (1 - 0.6) * 0.5 = 0.2, ratio_score = 0.5, cqs = 0.7
        cqs = calc_cqs(100, 100, 0.2)
        assert cqs == 0.7

    def test_zero_total_count(self):
        cqs = calc_cqs(0, 0, 0.0)
        assert cqs == 0.5

    def test_moderate_quality(self):
        cqs = calc_cqs(80, 100, 0.05)
        assert 0.5 < cqs < 1.0


class TestGetCameraMatrix:
    def test_shape(self):
        mat = get_camera_matrix(640, 480)
        assert mat.shape == (3, 3)

    def test_focal_length(self):
        mat = get_camera_matrix(640, 480)
        assert mat[0, 0] == 640.0
        assert mat[1, 1] == 640.0

    def test_principal_point(self):
        mat = get_camera_matrix(640, 480)
        assert mat[0, 2] == 320.0
        assert mat[1, 2] == 240.0

    def test_dtype(self):
        mat = get_camera_matrix(640, 480)
        assert mat.dtype == np.float64

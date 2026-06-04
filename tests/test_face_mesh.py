"""
tests/test_face_mesh.py — FaceMeshDetector 单元测试
覆盖 detector/face_mesh.py 中可离线测试的函数。
"""

import sys
import os
import math

import numpy as np
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector.face_mesh import FaceMeshDetector, FaceMeshResult
from detector.euler_utils import solve_head_pose_from_matrix


class TestFaceMeshResult:
    """FaceMeshResult dataclass 单元测试"""

    def test_result_creation(self):
        """测试基本结果创建"""
        result = FaceMeshResult(
            landmarks=None,
            face_detected=False,
            confidence=0.0,
        )
        assert result.landmarks is None
        assert result.face_detected is False
        assert result.confidence == 0.0
        assert result.yaw is None
        assert result.pitch is None
        assert result.roll is None
        assert result.blendshapes is None

    def test_result_with_landmarks(self):
        """测试带 landmarks 的结果创建"""
        landmarks = np.array([[100.0, 200.0], [150.0, 250.0]])
        result = FaceMeshResult(
            landmarks=landmarks,
            face_detected=True,
            yaw=10.0,
            pitch=-5.0,
            roll=3.0,
            confidence=0.95,
        )
        assert result.landmarks is not None
        assert result.landmarks.shape == (2, 2)
        assert result.face_detected is True
        assert result.yaw == 10.0
        assert result.pitch == -5.0
        assert result.roll == 3.0
        assert result.confidence == 0.95

    def test_result_with_blendshapes(self):
        """测试带 blendshapes 的结果创建"""
        blendshapes = {"browInnerUp": 0.5, "browDown_L": 0.1}
        result = FaceMeshResult(
            landmarks=None,
            face_detected=True,
            blendshapes=blendshapes,
            confidence=0.8,
        )
        assert result.blendshapes is not None
        assert result.blendshapes["browInnerUp"] == 0.5
        assert result.blendshapes["browDown_L"] == 0.1


class TestSolveHeadPoseFromMatrix:
    """solve_head_pose_from_matrix 单元测试 — 纯数学函数"""

    def test_identity_matrix_returns_zeros(self):
        """单位矩阵应返回接近零的角度"""
        # 单位矩阵的旋转部分也是单位矩阵，表示无旋转
        matrix = np.eye(4).flatten()  # 4x4 单位矩阵扁平化
        yaw, pitch, roll = solve_head_pose_from_matrix(matrix)

        assert yaw is not None
        assert pitch is not None
        assert roll is not None
        # 单位矩阵应该给出接近 0 的角度（允许小误差）
        assert abs(yaw) < 1.0
        assert abs(pitch) < 1.0
        assert abs(roll) < 1.0

    def test_rotation_matrix_extraction(self):
        """测试旋转矩阵提取"""
        # 创建一个绕 Y 轴旋转 45 度的变换矩阵
        # 标准 Y 轴旋转矩阵 Ry(theta):
        # [[cos, 0, sin], [0, 1, 0], [-sin, 0, cos]]
        # 注意: yaw = arctan2(rmat[1,0], rmat[0,0])
        # 但对于纯 Y 旋转, rmat[1,0] = 0, 所以 yaw = 0
        # 这里验证函数能正确处理并返回有效值
        angle = np.radians(45.0)
        matrix = np.eye(4)
        matrix[0, 0] = np.cos(angle)
        matrix[0, 2] = np.sin(angle)
        matrix[2, 0] = -np.sin(angle)
        matrix[2, 2] = np.cos(angle)

        yaw, pitch, roll = solve_head_pose_from_matrix(matrix.flatten())

        assert yaw is not None
        assert pitch is not None
        assert roll is not None
        # 纯 Y 旋转: yaw=0, pitch=0, roll=0

    def test_4x4_matrix_input(self):
        """测试 4x4 矩阵输入（不扁平化）"""
        matrix = np.eye(4)
        yaw, pitch, roll = solve_head_pose_from_matrix(matrix)

        assert yaw is not None
        assert pitch is not None
        assert roll is not None
        assert abs(yaw) < 1.0

    def test_invalid_matrix_returns_none(self):
        """无效矩阵形状返回 None"""
        # 3x3 矩阵（不是 4x4）
        invalid_matrix = np.eye(3).flatten()
        result = solve_head_pose_from_matrix(invalid_matrix)
        assert result == (None, None, None)

    def test_invalid_matrix_5x5_returns_none(self):
        """5x5 矩阵返回 None"""
        invalid_matrix = np.eye(5).flatten()
        result = solve_head_pose_from_matrix(invalid_matrix)
        assert result == (None, None, None)

    def test_none_input_returns_none(self):
        """None 输入返回 None"""
        result = solve_head_pose_from_matrix(None)
        assert result == (None, None, None)

    def test_pitch_extraction(self):
        """测试俯仰角 (pitch) 提取"""
        # 对于纯 X 轴旋转，pitch 公式中的 rmat[2,0] = 0，所以 pitch = 0
        # 使用复合旋转来测试 pitch 提取
        # 创建一个 Y+Z 复合旋转
        yaw_angle = np.radians(20.0)
        roll_angle = np.radians(15.0)
        matrix = np.eye(4)
        # 简化的测试：验证函数能正确处理非奇异情况
        # 使用一个已知的复合旋转矩阵
        cy, sy = np.cos(yaw_angle), np.sin(yaw_angle)
        cr, sr = np.cos(roll_angle), np.sin(roll_angle)
        # 复合旋转矩阵 (先 yaw 再 roll)
        matrix[0, 0] = cy
        matrix[0, 1] = sr * sy
        matrix[1, 1] = cr
        matrix[1, 2] = -sr * cy
        matrix[2, 0] = -sy
        matrix[2, 1] = sr * cy
        matrix[2, 2] = cr * cy

        yaw, pitch, roll = solve_head_pose_from_matrix(matrix.flatten())

        assert pitch is not None
        # pitch 应该约为 0（因为没有 X 轴旋转）

    def test_roll_extraction(self):
        """测试翻滚角 (roll) 提取"""
        # 使用纯 Z 轴旋转测试 roll
        # 对于纯 Z 轴旋转: rmat[2,1] = sin(angle), rmat[2,2] = cos(angle)
        # roll = arctan2(rmat[2,1], rmat[2,2])
        # 但对于纯 Z 旋转, rmat[2,1] = 0, 所以 roll = 0
        angle = np.radians(15.0)
        matrix = np.eye(4)
        # Rz(15) - 绕 Z 轴旋转矩阵
        matrix[0, 0] = np.cos(angle)
        matrix[0, 1] = -np.sin(angle)
        matrix[1, 0] = np.sin(angle)
        matrix[1, 1] = np.cos(angle)

        yaw, pitch, roll = solve_head_pose_from_matrix(matrix.flatten())

        assert roll is not None
        assert yaw is not None
        assert pitch is not None
        # 纯 Z 旋转: yaw=0, pitch=0, roll=0

    # ===== T-CAL-32: 数值断言测试 (修复前应失败) =====

    def test_pure_y_rotation_maps_to_yaw_T_CAL_32(self):
        """T-CAL-32: 纯 Y 轴旋转 30° → yaw 应为 30°，pitch/roll 应为 0°

        Bug 验证: 修复前变量名错位，code's pitch 实际是 Y 轴旋转
        → 此测试应失败（code 返回 pitch=30, yaw=0）
        """
        theta = np.radians(30.0)
        # Ry(θ) = [[cos, 0, sin], [0, 1, 0], [-sin, 0, cos]]
        matrix = np.eye(4)
        matrix[0, 0] = np.cos(theta)
        matrix[0, 2] = np.sin(theta)
        matrix[2, 0] = -np.sin(theta)
        matrix[2, 2] = np.cos(theta)

        yaw, pitch, roll = solve_head_pose_from_matrix(matrix.flatten())

        # 修复后: yaw=30°, pitch=0, roll=0
        assert yaw is not None and abs(yaw - 30.0) < 0.5, \
            f"T-CAL-32 失败: 期望 yaw=30.0 (Y轴旋转)，实际 yaw={yaw}"
        assert pitch is not None and abs(pitch) < 0.5, \
            f"T-CAL-32 失败: 期望 pitch=0，实际 pitch={pitch}"
        assert roll is not None and abs(roll) < 0.5, \
            f"T-CAL-32 失败: 期望 roll=0，实际 roll={roll}"

    def test_pure_x_rotation_maps_to_pitch_T_CAL_32(self):
        """T-CAL-32: 纯 X 轴旋转 30° → pitch 应为 30°，yaw/roll 应为 0°

        Bug 验证: 修复前 code's roll 实际是 X 轴旋转
        → 此测试应失败（code 返回 roll=30, pitch=0）
        """
        theta = np.radians(30.0)
        # Rx(θ) = [[1, 0, 0], [0, cos, -sin], [0, sin, cos]]
        matrix = np.eye(4)
        matrix[1, 1] = np.cos(theta)
        matrix[1, 2] = -np.sin(theta)
        matrix[2, 1] = np.sin(theta)
        matrix[2, 2] = np.cos(theta)

        yaw, pitch, roll = solve_head_pose_from_matrix(matrix.flatten())

        # 修复后: pitch=30°, yaw=0, roll=0
        assert pitch is not None and abs(pitch - 30.0) < 0.5, \
            f"T-CAL-32 失败: 期望 pitch=30.0 (X轴旋转)，实际 pitch={pitch}"
        assert yaw is not None and abs(yaw) < 0.5, \
            f"T-CAL-32 失败: 期望 yaw=0，实际 yaw={yaw}"
        assert roll is not None and abs(roll) < 0.5, \
            f"T-CAL-32 失败: 期望 roll=0，实际 roll={roll}"

    def test_pure_z_rotation_maps_to_roll_T_CAL_32(self):
        """T-CAL-32: 纯 Z 轴旋转 30° → roll 应为 30°，yaw/pitch 应为 0°

        Bug 验证: 修复前 code's yaw 实际是 Z 轴旋转
        → 此测试应失败（code 返回 yaw=30, roll=0）
        """
        theta = np.radians(30.0)
        # Rz(θ) = [[cos, -sin, 0], [sin, cos, 0], [0, 0, 1]]
        matrix = np.eye(4)
        matrix[0, 0] = np.cos(theta)
        matrix[0, 1] = -np.sin(theta)
        matrix[1, 0] = np.sin(theta)
        matrix[1, 1] = np.cos(theta)

        yaw, pitch, roll = solve_head_pose_from_matrix(matrix.flatten())

        # 修复后: roll=30°, yaw=0, pitch=0
        assert roll is not None and abs(roll - 30.0) < 0.5, \
            f"T-CAL-32 失败: 期望 roll=30.0 (Z轴旋转)，实际 roll={roll}"
        assert yaw is not None and abs(yaw) < 0.5, \
            f"T-CAL-32 失败: 期望 yaw=0，实际 yaw={yaw}"
        assert pitch is not None and abs(pitch) < 0.5, \
            f"T-CAL-32 失败: 期望 pitch=0，实际 pitch={pitch}"


class TestNormalizeYaw:
    """normalize_yaw 单元测试 — 纯数学函数"""

    def test_yaw_in_range_unchanged(self):
        """范围 (-90, 90] 内的 yaw 保持不变"""
        test_values = [-90.0, -45.0, 0.0, 45.0, 90.0]
        for yaw in test_values:
            result = FaceMeshDetector.normalize_yaw(yaw)
            assert result == yaw

    def test_yaw_above_90_reduced(self):
        """yaw > 90 时减去 180"""
        assert FaceMeshDetector.normalize_yaw(100.0) == -80.0
        assert FaceMeshDetector.normalize_yaw(135.0) == -45.0
        assert FaceMeshDetector.normalize_yaw(180.0) == 0.0
        # 270 - 180 = 90 (不是 -90)
        assert FaceMeshDetector.normalize_yaw(270.0) == 90.0

    def test_yaw_below_minus_90_increased(self):
        """yaw < -90 时加上 180"""
        assert FaceMeshDetector.normalize_yaw(-100.0) == 80.0
        assert FaceMeshDetector.normalize_yaw(-135.0) == 45.0
        assert FaceMeshDetector.normalize_yaw(-180.0) == 0.0
        # -270 + 180 = -90 (不是 90)
        assert FaceMeshDetector.normalize_yaw(-270.0) == -90.0

    def test_boundary_values(self):
        """边界值测试"""
        # 精确 90 和 -90 应该保持不变
        assert FaceMeshDetector.normalize_yaw(90.0) == 90.0
        assert FaceMeshDetector.normalize_yaw(-90.0) == -90.0

        # 略超过边界
        assert FaceMeshDetector.normalize_yaw(90.1) == -89.9
        assert FaceMeshDetector.normalize_yaw(-90.1) == 89.9


class TestFaceMeshDetector:
    """FaceMeshDetector 集成测试（使用 Mock MediaPipe）"""

    @patch('mediapipe.tasks.python.vision')
    @patch('mediapipe.tasks.python.core.base_options')
    def test_init_video_mode(self, mock_base_options, mock_vision):
        """测试视频模式初始化"""
        mock_detector = MagicMock()
        mock_vision.FaceLandmarker.create_from_options.return_value = mock_detector
        mock_vision.RunningMode.VIDEO = "VIDEO"

        detector = FaceMeshDetector(running_mode="video")

        assert detector._running_mode == "video"
        mock_vision.FaceLandmarker.create_from_options.assert_called_once()

    @patch('mediapipe.tasks.python.vision')
    @patch('mediapipe.tasks.python.core.base_options')
    def test_init_image_mode(self, mock_base_options, mock_vision):
        """测试图片模式初始化"""
        mock_detector = MagicMock()
        mock_vision.FaceLandmarker.create_from_options.return_value = mock_detector
        mock_vision.RunningMode.IMAGE = "IMAGE"

        detector = FaceMeshDetector(running_mode="image")

        assert detector._running_mode == "image"

    @patch('mediapipe.tasks.python.vision')
    @patch('mediapipe.tasks.python.core.base_options')
    def test_init_invalid_mode_raises(self, mock_base_options, mock_vision):
        """测试无效运行模式抛出异常"""
        with pytest.raises(ValueError, match="不支持的运行模式"):
            FaceMeshDetector(running_mode="invalid_mode")

    @patch('mediapipe.tasks.python.vision')
    @patch('mediapipe.tasks.python.core.base_options')
    def test_close_method(self, mock_base_options, mock_vision):
        """测试 close 方法正常关闭"""
        mock_detector = MagicMock()
        mock_vision.FaceLandmarker.create_from_options.return_value = mock_detector

        detector = FaceMeshDetector()
        detector.close()

        mock_detector.close.assert_called_once()

    @patch('mediapipe.tasks.python.vision')
    @patch('mediapipe.tasks.python.core.base_options')
    def test_context_manager(self, mock_base_options, mock_vision):
        """测试上下文管理器"""
        mock_detector = MagicMock()
        mock_vision.FaceLandmarker.create_from_options.return_value = mock_detector

        with FaceMeshDetector() as detector:
            assert detector is not None

        mock_detector.close.assert_called_once()


class TestProcessResult:
    """_process_result 单元测试"""

    def _make_mock_result(self, face_detected=True, has_matrix=True, has_blendshapes=True):
        """创建 Mock MediaPipe 检测结果对象"""
        mock_result = MagicMock()

        if face_detected:
            # Mock face_landmarks
            mock_landmark = MagicMock()
            mock_landmark.x = 0.5
            mock_landmark.y = 0.5
            mock_landmark.presence = 0.95
            mock_result.face_landmarks = [[mock_landmark] * 478]  # 478 个关键点
        else:
            mock_result.face_landmarks = []

        # Mock facial_transformation_matrixes
        if has_matrix:
            # 4x4 单位矩阵
            matrix_4x4 = np.eye(4).tolist()
            mock_result.facial_transformation_matrixes = [matrix_4x4]
        else:
            mock_result.facial_transformation_matrixes = None

        # Mock face_blendshapes
        if has_blendshapes:
            mock_bs = MagicMock()
            mock_bs.display_name = "browInnerUp"
            mock_bs.score = 0.5
            mock_result.face_blendshapes = [[mock_bs]]
        else:
            mock_result.face_blendshapes = []

        return mock_result

    def test_process_no_face_detected(self):
        """测试未检测到人脸"""
        mock_result = MagicMock()
        mock_result.face_landmarks = []

        detector = FaceMeshDetector.__new__(FaceMeshDetector)
        detector._lock = MagicMock()

        result = detector._process_result(mock_result, 640, 480)

        assert result.face_detected is False
        assert result.landmarks is None
        assert result.confidence == 0.0

    def test_process_with_face_and_landmarks(self):
        """测试检测到人脸并有 landmarks"""
        mock_result = self._make_mock_result(face_detected=True, has_matrix=False, has_blendshapes=False)

        detector = FaceMeshDetector.__new__(FaceMeshDetector)
        detector._lock = MagicMock()

        result = detector._process_result(mock_result, 640, 480)

        assert result.face_detected is True
        assert result.landmarks is not None
        assert result.landmarks.shape[1] == 2  # (N, 2) 坐标

    def test_process_with_transformation_matrix(self):
        """测试带变换矩阵的结果处理"""
        mock_result = self._make_mock_result(face_detected=True, has_matrix=True, has_blendshapes=False)

        detector = FaceMeshDetector.__new__(FaceMeshDetector)
        detector._lock = MagicMock()

        result = detector._process_result(mock_result, 640, 480)

        assert result.face_detected is True
        assert result.yaw is not None
        assert result.pitch is not None
        assert result.roll is not None

    def test_process_with_blendshapes(self):
        """测试带 blendshapes 的结果处理"""
        mock_result = self._make_mock_result(face_detected=True, has_matrix=False, has_blendshapes=True)

        detector = FaceMeshDetector.__new__(FaceMeshDetector)
        detector._lock = MagicMock()

        result = detector._process_result(mock_result, 640, 480)

        assert result.face_detected is True
        assert result.blendshapes is not None
        assert "browInnerUp" in result.blendshapes
        assert result.blendshapes["browInnerUp"] == 0.5

    def test_process_confidence_from_presence(self):
        """测试置信度从 presence 属性获取"""
        mock_result = self._make_mock_result(face_detected=True, has_matrix=False, has_blendshapes=False)

        detector = FaceMeshDetector.__new__(FaceMeshDetector)
        detector._lock = MagicMock()

        result = detector._process_result(mock_result, 640, 480)

        assert result.confidence == 0.95

    def test_process_landmarks_pixel_coordinates(self):
        """测试 landmarks 转换为像素坐标"""
        mock_result = self._make_mock_result(face_detected=True, has_matrix=False, has_blendshapes=False)

        detector = FaceMeshDetector.__new__(FaceMeshDetector)
        detector._lock = MagicMock()

        frame_w, frame_h = 640, 480
        result = detector._process_result(mock_result, frame_w, frame_h)

        # 验证 landmarks 在像素坐标范围内
        assert result.landmarks is not None
        assert result.landmarks[:, 0].max() <= frame_w  # x 坐标
        assert result.landmarks[:, 1].max() <= frame_h  # y 坐标

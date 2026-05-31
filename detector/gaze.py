"""
detector/gaze.py — 视线方向检测模块

基于眼部关键点和头部姿态估算视线方向/注意力偏移。

输入依赖：
- EyeAspectDetector 提供眼部关键点
- HeadPoseDetector 提供头部姿态

输出：
- gaze_offset: 视线偏移 (x, y)，归一化到 [-1, 1]
- gaze_score: 视线集中度分数 (0-100)
"""

import logging
import math
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from config import HEAD_POSE

logger = logging.getLogger("eyefocus.detector")


# 默认配置：从 HEAD_POSE 加载，与头部姿态阈值保持一致
DEFAULT_GAZE_YAW_THRESH = HEAD_POSE.yaw_thresh   # 视线横向偏移阈值（度）
DEFAULT_GAZE_PITCH_THRESH = HEAD_POSE.pitch_thresh  # 视线纵向偏移阈值（度）


@dataclass
class GazeResult:
    """视线方向检测结果"""
    gaze_offset: Tuple[float, float]  # (x, y) 视线偏移，归一化到 [-1, 1]
    gaze_concentration: float          # 视线集中度分数 (0-100)，区别于 FocusResult.gaze_score
    is_looking_at_screen: bool         # 是否在看屏幕
    left_eye_offset: Tuple[float, float]
    right_eye_offset: Tuple[float, float]


class GazeDetector:
    """视线方向检测器

    通过分析眼部特征点位置和头部姿态估算视线方向。

    视线偏移计算逻辑：
    - 瞳孔相对于眼睑中心的位置
    - 结合头部姿态进行角度补偿
    - 归一化到 [-1, 1] 范围

    使用方法：
        detector = GazeDetector()
        result = detector.detect(landmarks, head_pose_yaw, head_pose_pitch)
    """

    # 左眼关键点索引 (参考 EAR 计算)
    LEFT_EYE_INDICES = (33, 160, 158, 133, 153, 144)
    RIGHT_EYE_INDICES = (362, 385, 387, 263, 380, 373)

    def __init__(
        self,
        yaw_thresh: float = DEFAULT_GAZE_YAW_THRESH,
        pitch_thresh: float = DEFAULT_GAZE_PITCH_THRESH,
    ):
        """初始化视线检测器

        Args:
            yaw_thresh: yaw 阈值（度），超过视为视线偏移
            pitch_thresh: pitch 阈值（度），超过视为视线偏移
        """
        self.yaw_thresh = yaw_thresh
        self.pitch_thresh = pitch_thresh

    def detect(
        self,
        landmarks: np.ndarray,
        head_pose_yaw: float = 0.0,
        head_pose_pitch: float = 0.0,
    ) -> Optional[GazeResult]:
        """检测视线方向

        Args:
            landmarks: 468个人脸关键点数组
            head_pose_yaw: 头部 yaw 角度
            head_pose_pitch: 头部 pitch 角度

        Returns:
            GazeResult 或 None（检测失败）
        """
        if landmarks is None or len(landmarks) < 468:
            return None

        try:
            # 提取左右眼的 6 个关键点
            left_eye = np.array([landmarks[i] for i in self.LEFT_EYE_INDICES])
            right_eye = np.array([landmarks[i] for i in self.RIGHT_EYE_INDICES])

            # 计算眼睑中心（眼角中点和眼尾中点的中点）
            left_center = self._eye_center(left_eye)
            right_center = self._eye_center(right_eye)

            # 计算瞳孔位置（眼角连线的中心点）
            left_pupil = self._pupil_position(left_eye)
            right_pupil = self._pupil_position(right_eye)

            # 计算相对于眼睑中心的偏移
            left_offset = left_pupil - left_center
            right_offset = right_pupil - right_center

            # 归一化偏移量（使用眼宽作为参考）
            left_eye_width = np.linalg.norm(left_eye[0] - left_eye[3])
            right_eye_width = np.linalg.norm(right_eye[0] - right_eye[3])

            if left_eye_width < 1e-4 or right_eye_width < 1e-4:
                return None

            left_offset_norm = left_offset / (left_eye_width / 2)
            right_offset_norm = right_offset / (right_eye_width / 2)

            # 综合左右眼的偏移
            avg_offset_x = (left_offset_norm[0] + right_offset_norm[0]) / 2
            avg_offset_y = (left_offset_norm[1] + right_offset_norm[1]) / 2

            # 限制在 [-1, 1] 范围
            gaze_offset_x = max(-1.0, min(1.0, avg_offset_x))
            gaze_offset_y = max(-1.0, min(1.0, avg_offset_y))

            # 结合头部姿态计算视线集中度
            gaze_score = self._compute_gaze_score(
                gaze_offset_x, gaze_offset_y,
                head_pose_yaw, head_pose_pitch
            )

            # 判断是否在看屏幕
            is_looking_at_screen = (
                abs(head_pose_yaw) <= self.yaw_thresh
                and abs(head_pose_pitch) <= self.pitch_thresh
                and gaze_score >= 50.0
            )

            return GazeResult(
                gaze_offset=(gaze_offset_x, gaze_offset_y),
                gaze_concentration=gaze_score,
                is_looking_at_screen=is_looking_at_screen,
                left_eye_offset=(float(left_offset_norm[0]), float(left_offset_norm[1])),
                right_eye_offset=(float(right_offset_norm[0]), float(right_offset_norm[1])),
            )

        except (IndexError, ValueError) as e:
            logger.debug("视线检测失败: %s", e)
            return None

    def _eye_center(self, eye_points: np.ndarray) -> np.ndarray:
        """计算眼睑中心

        Args:
            eye_points: 6个眼部关键点坐标

        Returns:
            眼睑中心点坐标
        """
        # 眼角中点 (内侧眼角和和外侧眼角的中心)
        inner = (eye_points[1] + eye_points[5]) / 2
        outer = (eye_points[3] + eye_points[2]) / 2
        return (inner + outer) / 2

    def _pupil_position(self, eye_points: np.ndarray) -> np.ndarray:
        """计算瞳孔位置（近似）

        Args:
            eye_points: 6个眼部关键点坐标

        Returns:
            瞳孔位置坐标
        """
        # 简化为眼角连线和眼尾连线的中点
        top = (eye_points[1] + eye_points[2]) / 2
        bottom = (eye_points[4] + eye_points[5]) / 2
        return (top + bottom) / 2

    def _compute_gaze_score(
        self,
        offset_x: float,
        offset_y: float,
        head_yaw: float,
        head_pitch: float,
    ) -> float:
        """计算视线集中度分数 (0-100)

        综合瞳孔偏移和头部姿态：
        - 瞳孔居中 + 头部正对 → 高分
        - 瞳孔偏心 + 头部偏移 → 低分
        """
        # 瞳孔偏移分数 (0-60)
        offset_magnitude = math.sqrt(offset_x ** 2 + offset_y ** 2)
        pupil_score = max(0.0, 60.0 - offset_magnitude * 60.0)

        # 头部姿态分数 (0-40)
        yaw_deviation = min(abs(head_yaw) / self.yaw_thresh, 1.0)
        pitch_deviation = min(abs(head_pitch) / self.pitch_thresh, 1.0)
        head_score = max(0.0, 40.0 - (yaw_deviation + pitch_deviation) * 20.0)

        return pupil_score + head_score


def create_gaze_detector() -> GazeDetector:
    """工厂函数：创建视线检测器"""
    return GazeDetector()

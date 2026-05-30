"""
detector/head_pose.py — 头部姿态检测模块

基于 MediaPipe FaceLandmarker 的 transformation_matrix 提取头部姿态角。

输入依赖：
- FaceMeshDetector 提供 transformation_matrix

输出：
- yaw, pitch, roll 角度（度）
"""

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from config import HEAD_POSE

logger = logging.getLogger("eyefocus.detector")


@dataclass
class HeadPoseResult:
    """头部姿态检测结果"""
    yaw: float          # 水平转头角度（度），正值=向左，负值=向右
    pitch: float        # 垂直点头角度（度），正值=低头，负值=仰头
    roll: float         # 侧倾角度（度），正值=右倾，负值=左倾
    is_frontal: bool    # 是否为正面姿态（within thresholds）


class HeadPoseDetector:
    """头部姿态检测器

    使用 MediaPipe 内置的 facial_transformation_matrix 提取头部姿态，
    相比 solvePnP 更高效且稳定。

    使用方法：
        detector = HeadPoseDetector()
        result = detector.detect(transformation_matrix)
    """

    def __init__(
        self,
        yaw_thresh: float = HEAD_POSE.yaw_thresh,
        pitch_thresh: float = HEAD_POSE.pitch_thresh,
    ):
        """初始化头部姿态检测器

        Args:
            yaw_thresh: yaw 阈值（度），超过视为非正面
            pitch_thresh: pitch 阈值（度），超过视为非正面
        """
        self.yaw_thresh = yaw_thresh
        self.pitch_thresh = pitch_thresh

    def detect(self, transformation_matrix) -> Optional[HeadPoseResult]:
        """从 MediaPipe transformation_matrix 提取头部姿态

        Args:
            transformation_matrix: MediaPipe facial_transformation_matrix[0]

        Returns:
            HeadPoseResult 或 None（检测失败）
        """
        if transformation_matrix is None:
            return None

        # 转换为 numpy 数组
        if not isinstance(transformation_matrix, np.ndarray):
            mat = np.array(transformation_matrix).flatten()
        else:
            mat = transformation_matrix.flatten()

        # 确保是 4x4 矩阵
        if mat.shape != (16,):
            return None

        matrix = mat.reshape(4, 4)

        # 提取 3x3 旋转矩阵
        rmat = matrix[:3, :3].astype(np.float64)

        # 欧拉角分解（OpenCV 约定：pitch-x, yaw-y, roll-z）
        sy = np.sqrt(rmat[0, 0] ** 2 + rmat[1, 0] ** 2)
        singular = sy < 1e-6

        if singular:
            pitch = np.arctan2(-rmat[2, 0], sy)
            yaw = np.arctan2(-rmat[0, 1], rmat[1, 1]) if not singular else 0.0
            roll = 0.0
        else:
            pitch = np.arctan2(-rmat[2, 0], sy)
            yaw = np.arctan2(rmat[1, 0], rmat[0, 0])
            roll = np.arctan2(rmat[2, 1], rmat[2, 2])

        yaw_deg = float(np.degrees(yaw))
        pitch_deg = float(np.degrees(pitch))
        roll_deg = float(np.degrees(roll))

        # 判断是否为正面姿态
        is_frontal = (
            abs(yaw_deg) <= self.yaw_thresh
            and abs(pitch_deg) <= self.pitch_thresh
        )

        return HeadPoseResult(
            yaw=yaw_deg,
            pitch=pitch_deg,
            roll=roll_deg,
            is_frontal=is_frontal,
        )

    def compute_stability(
        self,
        yaw_history: list,
        pitch_history: list,
        yaw_std_thresh: float = HEAD_POSE.frontal_yaw_std_thresh,
        pitch_std_thresh: float = HEAD_POSE.frontal_pitch_std_thresh,
    ) -> float:
        """计算头部稳定性分数 (0-100)

        Args:
            yaw_history: yaw 历史列表
            pitch_history: pitch 历史列表
            yaw_std_thresh: yaw 标准差阈值
            pitch_std_thresh: pitch 标准差阈值

        Returns:
            稳定性分数，100=非常稳定，0=非常不稳定
        """
        if not yaw_history or not pitch_history:
            return 100.0

        yaw_std = float(np.std(yaw_history))
        pitch_std = float(np.std(pitch_history))

        yaw_score = max(0.0, 1.0 - yaw_std / yaw_std_thresh) * 50.0
        pitch_score = max(0.0, 1.0 - pitch_std / pitch_std_thresh) * 50.0

        return yaw_score + pitch_score


def create_head_pose_detector() -> HeadPoseDetector:
    """工厂函数：创建头部姿态检测器"""
    return HeadPoseDetector()

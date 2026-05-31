"""
detector/euler_utils.py — 欧拉角计算工具

从旋转矩阵提取头部姿态欧拉角 (yaw, pitch, roll)。
被 face_mesh.py 和 head_pose.py 共用。
"""

from typing import Optional, Tuple

import numpy as np


def solve_head_pose_from_matrix(
    transformation_matrix: np.ndarray,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """从 MediaPipe 4x4 变换矩阵提取头部姿态欧拉角

    使用 OpenCV 约定：pitch-x, yaw-y, roll-z

    Args:
        transformation_matrix: 4x4 变换矩阵（扁平 16 元素或 4x4）

    Returns:
        (yaw, pitch, roll) 元组，单位为度
    """
    if transformation_matrix is None:
        return None, None, None

    # reshape to 4x4
    if transformation_matrix.shape == (16,):
        mat = transformation_matrix.reshape(4, 4)
    elif transformation_matrix.shape == (4, 4):
        mat = transformation_matrix
    else:
        return None, None, None

    # 提取 3x3 旋转矩阵
    rmat = mat[:3, :3].astype(np.float64)

    # 分解为欧拉角 (pitch-x, yaw-y, roll-z)
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

    return (
        float(np.degrees(yaw)),
        float(np.degrees(pitch)),
        float(np.degrees(roll)),
    )
"""
angle_verify.py — 头部姿态角度检测精度验证 spike

目的：验证 solve_head_pose_from_matrix() 是否能正确还原已知角度。
方法：构造已知旋转矩阵 → 提取角度 → 对比输入输出。

用法：".venv312/Scripts/python.exe" -X utf8 spike/angle_verify.py
"""
import sys, os, math, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from detector.euler_utils import solve_head_pose_from_matrix


def rotation_matrix_y(yaw_deg: float) -> np.ndarray:
    """绕 Y 轴旋转矩阵 (yaw = 水平转头)"""
    yaw = math.radians(yaw_deg)
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([
        [c,  0,  s],
        [0,  1,  0],
        [-s, 0,  c],
    ])


def rotation_matrix_x(pitch_deg: float) -> np.ndarray:
    """绕 X 轴旋转矩阵 (pitch = 垂直点头)"""
    p = math.radians(pitch_deg)
    c, s = math.cos(p), math.sin(p)
    return np.array([
        [1,  0,  0],
        [0,  c, -s],
        [0,  s,  c],
    ])


def rotation_matrix_z(roll_deg: float) -> np.ndarray:
    """绕 Z 轴旋转矩阵 (roll = 侧倾)"""
    r = math.radians(roll_deg)
    c, s = math.cos(r), math.sin(r)
    return np.array([
        [c, -s,  0],
        [s,  c,  0],
        [0,  0,  1],
    ])


def make_4x4_affine(rmat_3x3: np.ndarray) -> np.ndarray:
    """3x3 旋转矩阵 → 4x4 affine (平移=0, 缩放=1)"""
    aff = np.eye(4)
    aff[:3, :3] = rmat_3x3
    return aff


def test_pure_rotations():
    """纯旋转: 只有 yaw/pitch/roll 之一, 其他为 0"""
    print("=" * 60)
    print("纯旋转测试 (单一轴)")
    print(f"{'输入角度':>10} | {'公式输出 yaw':>12} {'pitch':>8} {'roll':>8} | {'误差':>8}")
    print("-" * 60)

    for deg in [0, 10, 20, 30, 45, 60, -10, -20, -30, -45]:
        R = rotation_matrix_y(deg)
        aff = make_4x4_affine(R)
        yaw, pitch, roll = solve_head_pose_from_matrix(aff.flatten())
        ye = abs(abs(yaw or 0) - abs(deg))
        print(f"{deg:>8}° yaw | {yaw:>8.2f}° {pitch:>8.2f}° {roll:>8.2f}° | err={ye:>4.1f}°")
    print()

    for deg in [0, 10, 20, 30, 45, -10, -20, -30]:
        R = rotation_matrix_x(deg)
        aff = make_4x4_affine(R)
        yaw, pitch, roll = solve_head_pose_from_matrix(aff.flatten())
        pe = abs(abs(pitch or 0) - abs(deg))
        print(f"{deg:>8}° pitch| {yaw:>8.2f}° {pitch:>8.2f}° {roll:>8.2f}° | err={pe:>4.1f}°")
    print()

    for deg in [0, 10, 20, 30, -10, -20, -30]:
        R = rotation_matrix_z(deg)
        aff = make_4x4_affine(R)
        yaw, pitch, roll = solve_head_pose_from_matrix(aff.flatten())
        re = abs(abs(roll or 0) - abs(deg))
        print(f"{deg:>8}° roll | {yaw:>8.2f}° {pitch:>8.2f}° {roll:>8.2f}° | err={re:>4.1f}°")
    print()


def test_combined_yaw_pitch():
    """组合 yaw+pitch 测试 (真实场景: 转头同时有点头)"""
    print("=" * 60)
    print("组合测试 (yaw + pitch)")
    print(f"{'输入':>18} | {'公式输出 yaw':>12} {'pitch':>8} {'roll':>8}")
    print("-" * 60)
    test_cases = [
        (30, 10), (30, -10), (45, 15), (45, -15),
        (20, 20), (20, -20), (-30, 10), (-30, -10),
        (10, 30), (-10, 30),
    ]
    for yaw_in, pitch_in in test_cases:
        R = rotation_matrix_y(yaw_in) @ rotation_matrix_x(pitch_in)
        aff = make_4x4_affine(R)
        yaw, pitch, roll = solve_head_pose_from_matrix(aff.flatten())
        print(f"y={yaw_in:>3}° p={pitch_in:>3}°   | {yaw:>8.2f}° {pitch:>8.2f}° {roll:>8.2f}°")
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("头部姿态角度检测精度验证")
    print("solve_head_pose_from_matrix 公式验证")
    print("=" * 60)
    test_pure_rotations()
    test_combined_yaw_pitch()
    print("Done.")

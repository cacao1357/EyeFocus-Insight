"""
Spike 公共工具模块
提取所有 spike 脚本共享的常量、函数和初始化逻辑。

修复记录:
  - MODEL_POINTS Y 轴取反，匹配 OpenCV 相机坐标系 (Y-down)
  - 添加类型注解
  - 引入 logging 替代 print
  - 使用 sys.exit() 替代 os._exit()
"""

import logging
import os
import sys
from contextlib import contextmanager
from typing import Optional, Tuple

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import FACE_MESH, EYE

logger = logging.getLogger("eyefocus.spike")

MODEL_POINTS = np.array([
    (0.0, 0.0, 0.0),
    (0.0, 63.6, -12.5),
    (-43.3, -32.7, -26.0),
    (43.3, -32.7, -26.0),
    (-28.9, 28.9, -24.1),
    (28.9, 28.9, -24.1),
], dtype=np.float64)

LANDMARK_INDICES = [1, 152, 33, 263, 61, 291]


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="[%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def get_camera_matrix(img_w: int, img_h: int) -> np.ndarray:
    focal = img_w
    cx, cy = img_w / 2, img_h / 2
    return np.array([[focal, 0, cx], [0, focal, cy], [0, 0, 1]], dtype=np.float64)


def solve_head_pose(
    landmarks: np.ndarray, camera_matrix: np.ndarray
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    image_points = np.array(
        [landmarks[idx] for idx in LANDMARK_INDICES], dtype=np.float64
    )
    dist_coeffs = np.zeros((4, 1), dtype=np.float64)
    try:
        success, rvec, _ = cv2.solvePnP(
            MODEL_POINTS, image_points, camera_matrix, dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
    except cv2.error:
        return None, None, None
    if not success:
        return None, None, None

    rmat, _ = cv2.Rodrigues(rvec)
    sy = np.sqrt(rmat[0, 0] ** 2 + rmat[1, 0] ** 2)
    if sy < 1e-6:
        pitch = np.arctan2(-rmat[2, 0], sy)
        yaw = np.arctan2(-rmat[0, 1], rmat[1, 1])
        roll = 0.0
    else:
        pitch = np.arctan2(-rmat[2, 0], sy)
        yaw = np.arctan2(rmat[1, 0], rmat[0, 0])
        roll = np.arctan2(rmat[2, 1], rmat[2, 2])

    return float(np.degrees(yaw)), float(np.degrees(pitch)), float(np.degrees(roll))


def calculate_ear(eye_points: np.ndarray) -> float:
    p1, p2, p3, p4, p5, p6 = eye_points
    a = np.linalg.norm(p2 - p6)
    b = np.linalg.norm(p3 - p5)
    c = np.linalg.norm(p1 - p4)
    if c < 1e-6:
        return 0.0
    return float((a + b) / (2.0 * c))


def calc_cqs(valid_count: int, total_count: int, ear_cv: float) -> float:
    ratio_score = valid_count / max(total_count, 1) * 0.5
    cv_score = max(0.0, (1.0 - ear_cv * 10.0)) * 0.5
    return round(min(1.0, ratio_score + cv_score), 3)


def create_face_landmarker():
    from mediapipe.tasks.python import vision
    from mediapipe.tasks.python.core import base_options as mp_base_options

    model_path = os.path.join(os.path.dirname(__file__), FACE_MESH.model_filename)
    options = vision.FaceLandmarkerOptions(
        base_options=mp_base_options.BaseOptions(model_asset_path=model_path),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=FACE_MESH.num_faces,
        output_face_blendshapes=False,
        output_facial_transformation_matrixes=False,
        min_face_detection_confidence=FACE_MESH.min_detection_confidence,
        min_face_presence_confidence=FACE_MESH.min_presence_confidence,
        min_tracking_confidence=FACE_MESH.min_tracking_confidence,
    )
    return vision.FaceLandmarker.create_from_options(options)


@contextmanager
def camera_context(camera_index: int = 0):
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        logger.error("无法打开摄像头 (index %d)", camera_index)
        sys.exit(1)
    try:
        yield cap
    finally:
        cap.release()


@contextmanager
def opencv_windows(*names: str):
    try:
        yield
    finally:
        for name in names:
            cv2.destroyWindow(name)
        # Process window events to ensure cleanup on Windows
        for _ in range(5):
            cv2.waitKey(1)


def cleanup_exit(face_landmarker=None, exit_code: int = 0) -> None:
    """Safely cleanup all resources and exit.

    MediaPipe FaceLandmarker.close() has a known bug where its internal
    XNNPACK delegate threads never terminate, causing close() to block
    indefinitely. Since this is a spike script that exits immediately after
    cleanup, we use os._exit() to bypass the broken close() call.
    The OS will reclaim all resources (threads, memory, handles) on exit.

    IMPORTANT: Only use this when exiting immediately. For long-running
    processes, close() should be called in a non-blocking manner.
    """
    # Process any remaining window events before exit
    for _ in range(3):
        cv2.waitKey(1)
    os._exit(exit_code)


def extract_landmarks(result, frame_w: int, frame_h: int) -> Optional[np.ndarray]:
    if not result.face_landmarks:
        return None
    landmarks = result.face_landmarks[0]
    return np.array([(lm.x * frame_w, lm.y * frame_h) for lm in landmarks])


def compute_ear_from_landmarks(pts: np.ndarray) -> Tuple[float, bool]:
    left_pts = np.array([pts[i] for i in EYE.left_indices])
    right_pts = np.array([pts[i] for i in EYE.right_indices])
    ear_left = calculate_ear(left_pts)
    ear_right = calculate_ear(right_pts)
    ear_avg = (ear_left + ear_right) / 2.0
    return ear_avg, ear_left >= EYE.ear_min and ear_right >= EYE.ear_min


def normalize_yaw(yaw: float) -> float:
    """Normalize yaw to (-90, 90] range to handle ±180° Euler angle boundary.

    solvePnP Euler angles wrap at ±180°. A yaw of 177° and -177° both mean
    "facing nearly straight ahead" — just expressed differently.
    This function normalizes raw yaw values so that threshold comparisons
    (abs(yaw) <= threshold) work correctly for all frontal-face angles.
    """
    if yaw > 90.0:
        return yaw - 180.0
    elif yaw < -90.0:
        return yaw + 180.0
    return yaw

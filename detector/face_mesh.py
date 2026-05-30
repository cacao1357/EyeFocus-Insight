"""
detector/face_mesh.py — MediaPipe 人脸网格检测封装

提供 FaceMeshDetector 类，封装 MediaPipe FaceLandmarker 的初始化和检测逻辑。
支持视频流模式和图片模式。
"""

import logging
import os
import threading
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import mediapipe as mp
import numpy as np

logger = logging.getLogger("eyefocus.detector")


@dataclass
class FaceMeshResult:
    """人脸网格检测结果"""
    landmarks: Optional[np.ndarray]  # (478, 2) 归一化坐标 (x, y)
    face_detected: bool
    yaw: Optional[float] = None  # 偏航角 (度)
    pitch: Optional[float] = None  # 俯仰角 (度)
    roll: Optional[float] = None  # 翻滚角 (度)
    blendshapes: Optional[dict] = None  # blendshapes 字典
    confidence: float = 0.0  # 人脸检测置信度


class FaceMeshDetector:
    """MediaPipe FaceLandmarker 封装类

    支持：
    - 视频流模式（逐帧检测）
    - 线程安全的检测接口
    - 自动从配置加载参数
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        num_faces: int = 1,
        min_detection_confidence: float = 0.5,
        min_presence_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
        running_mode: str = "video",
    ):
        """初始化人脸网格检测器

        Args:
            model_path: FaceLandmarker 模型文件路径
            num_faces: 最大检测人脸数
            min_detection_confidence: 最小人脸检测置信度
            min_presence_confidence: 最小人脸存在置信度
            min_tracking_confidence: 最小跟踪置信度
            running_mode: 运行模式 "video" | "image" | "live_stream"
        """
        self._lock = threading.Lock()
        self._running_mode = running_mode

        if model_path is None:
            model_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "face_landmarker.task"
            )

        if not os.path.exists(model_path):
            logger.warning("模型文件不存在: %s，尝试从 MediaPipe assets 加载", model_path)

        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.core import base_options as mp_base_options

        base_options = mp_base_options.BaseOptions(model_asset_path=model_path)

        if running_mode == "video":
            running_mode_enum = vision.RunningMode.VIDEO
        elif running_mode == "image":
            running_mode_enum = vision.RunningMode.IMAGE
        elif running_mode == "live_stream":
            running_mode_enum = vision.RunningMode.LIVE_STREAM
        else:
            raise ValueError(f"不支持的运行模式: {running_mode}")

        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=running_mode_enum,
            num_faces=num_faces,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
            min_face_detection_confidence=min_detection_confidence,
            min_face_presence_confidence=min_presence_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

        self._detector = vision.FaceLandmarker.create_from_options(options)
        logger.info("FaceMeshDetector 初始化完成 (mode=%s)", running_mode)

    def detect_from_frame(
        self,
        frame: np.ndarray,
        timestamp_ms: int,
    ) -> FaceMeshResult:
        """从视频帧检测人脸网格（视频模式）

        Args:
            frame: BGR 格式的 OpenCV 图像 (H, W, 3)
            timestamp_ms: 帧时间戳（毫秒）

        Returns:
            FaceMeshResult 对象
        """
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        from mediapipe import Image, ImageFormat

        mp_image = Image(image_format=ImageFormat.SRGB, data=frame_rgb)

        with self._lock:
            result = self._detector.detect_for_video(mp_image, timestamp_ms)

        return self._process_result(result, frame.shape[1], frame.shape[0])

    def detect_from_image(self, frame: np.ndarray) -> FaceMeshResult:
        """从图像检测人脸网格（图片模式）

        Args:
            frame: BGR 格式的 OpenCV 图像

        Returns:
            FaceMeshResult 对象
        """
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        from mediapipe import Image, ImageFormat

        mp_image = Image(image_format=ImageFormat.SRGB, data=frame_rgb)

        with self._lock:
            result = self._detector.detect(mp_image)

        return self._process_result(result, frame.shape[1], frame.shape[0])

    def _process_result(
        self,
        result,
        frame_w: int,
        frame_h: int,
    ) -> FaceMeshResult:
        """处理 MediaPipe 检测结果"""
        if not result.face_landmarks:
            return FaceMeshResult(
                landmarks=None,
                face_detected=False,
                confidence=0.0,
            )

        # 获取第一个检测到的人脸
        landmarks = result.face_landmarks[0]
        # 转换为像素坐标 (x, y)
        landmarks_px = np.array(
            [(lm.x * frame_w, lm.y * frame_h) for lm in landmarks]
        )

        # 提取头部姿态
        yaw, pitch, roll = None, None, None
        if (
            result.facial_transformation_matrixes is not None
            and result.facial_transformation_matrixes[0] is not None
        ):
            matrix = np.array(result.facial_transformation_matrixes[0]).flatten()
            yaw, pitch, roll = self._solve_head_pose_from_matrix(matrix)

        # 提取 blendshapes
        blendshapes = None
        if result.face_blendshapes and result.face_blendshapes[0]:
            # MediaPipe Category objects use display_name (not name) in some versions
            blendshapes = {}
            for bs in result.face_blendshapes[0]:
                key = getattr(bs, 'display_name', None) or getattr(bs, 'name', str(bs))
                blendshapes[key] = bs.score

        # 置信度 - landmarks[0] is a NormalizedLandmark, use presence or x (which is always valid)
        if landmarks and len(landmarks) > 0:
            first_lm = landmarks[0]
            confidence = float(first_lm.presence) if first_lm.presence is not None else 1.0
        else:
            confidence = 0.0

        return FaceMeshResult(
            landmarks=landmarks_px,
            face_detected=True,
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            blendshapes=blendshapes,
            confidence=confidence,
        )

    @staticmethod
    def _solve_head_pose_from_matrix(
        transformation_matrix: np.ndarray,
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """从 MediaPipe 变换矩阵提取头部姿态欧拉角

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

    @staticmethod
    def normalize_yaw(yaw: float) -> float:
        """归一化偏航角到 (-90, 90] 范围，处理 ±180° 边界

        Args:
            yaw: 原始偏航角（度）

        Returns:
            归一化后的偏航角
        """
        if yaw > 90.0:
            return yaw - 180.0
        elif yaw < -90.0:
            return yaw + 180.0
        return yaw

    def close(self) -> None:
        """关闭检测器，释放资源

        注意：MediaPipe 的 close() 方法存在已知 bug，
        可能会无限期阻塞。在主程序中使用线程超控制。
        """
        with self._lock:
            try:
                self._detector.close()
            except Exception as e:
                logger.warning("FaceMeshDetector.close() 异常: %s", e)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def create_face_mesh_detector(
    model_path: Optional[str] = None,
    num_faces: int = 1,
    min_detection_confidence: float = 0.5,
    min_presence_confidence: float = 0.5,
    min_tracking_confidence: float = 0.5,
) -> FaceMeshDetector:
    """工厂函数：创建 FaceMeshDetector 实例

    从 config 模块加载默认参数。
    """
    from config import FACE_MESH

    if model_path is None:
        model_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            FACE_MESH.model_filename
        )

    return FaceMeshDetector(
        model_path=model_path,
        num_faces=num_faces or FACE_MESH.num_faces,
        min_detection_confidence=(
            min_detection_confidence or FACE_MESH.min_detection_confidence
        ),
        min_presence_confidence=(
            min_presence_confidence or FACE_MESH.min_presence_confidence
        ),
        min_tracking_confidence=(
            min_tracking_confidence or FACE_MESH.min_tracking_confidence
        ),
        running_mode="video",
    )

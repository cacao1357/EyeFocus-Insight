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

from detector.euler_utils import solve_head_pose_from_matrix

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

        # H-07: 模型文件不存在时 fail-fast，给出明确错误信息
        # 原代码仅打 logger.warning 后继续，让 MediaPipe BaseOptions 后续抛
        # 模糊的 RuntimeError / FileNotFoundError("Unable to open file at ...")
        # — 缺少 "model" / "FaceLandmarker" 关键词，用户难以定位。
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"FaceLandmarker model 文件不存在: {model_path}。"
                f"请检查 (1) 路径是否正确 (2) 是否已下载 face_landmarker.task。"
            )

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
        # M-10: 入口校验 None/空帧/非数组 → 返回 face_detected=False
        if frame is None or frame.size == 0 or frame.ndim < 2:
            return FaceMeshResult(
                landmarks=None,
                face_detected=False,
                confidence=0.0,
            )

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
        # M-10: 入口校验 None/空帧/非数组 → 返回 face_detected=False
        if frame is None or frame.size == 0 or frame.ndim < 2:
            return FaceMeshResult(
                landmarks=None,
                face_detected=False,
                confidence=0.0,
            )

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
            yaw, pitch, roll = solve_head_pose_from_matrix(matrix)

        # 提取 blendshapes
        blendshapes = None
        if result.face_blendshapes and result.face_blendshapes[0]:
            # MediaPipe Category objects use display_name (not name) in some versions
            blendshapes = {}
            for bs in result.face_blendshapes[0]:
                key = getattr(bs, 'display_name', None) or getattr(bs, 'category_name', None) or getattr(bs, 'name', str(bs))
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

    def close(self, timeout: float = 0.5) -> None:
        """关闭检测器，释放资源

        使用独立线程调用 MediaPipe 的 close()，并通过 join(timeout)
        实现超时控制，防止 close() 可能无限阻塞。

        v4.4: timeout 2.0→0.5 (关闭卡顿, 进程即将退出无需等待)

        Args:
            timeout: 超时时间（秒），默认 0.5 秒
        """
        def _close_async():
            with self._lock:
                try:
                    self._detector.close()
                except Exception as e:
                    logger.warning("FaceMeshDetector._detector.close() 异常: %s", e)

        close_thread = threading.Thread(target=_close_async, name="FaceMeshDetector-close", daemon=True)
        close_thread.start()
        close_thread.join(timeout=timeout)

        if close_thread.is_alive():
            logger.warning(
                "FaceMeshDetector.close() 超时 (%.1fs)，MediaPipe close() 可能阻塞",
                timeout
            )

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
        num_faces=num_faces if num_faces is not None else FACE_MESH.num_faces,
        min_detection_confidence=(
            min_detection_confidence
            if min_detection_confidence is not None
            else FACE_MESH.min_detection_confidence
        ),
        min_presence_confidence=(
            min_presence_confidence
            if min_presence_confidence is not None
            else FACE_MESH.min_presence_confidence
        ),
        min_tracking_confidence=(
            min_tracking_confidence
            if min_tracking_confidence is not None
            else FACE_MESH.min_tracking_confidence
        ),
        running_mode="video",
    )

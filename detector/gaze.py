"""
detector/gaze.py — 视线方向检测模块 (v4.47)

v4.47: 纯瞳孔偏移模型
  - 头部姿态从视线分中移除（头部姿态通过 focus.head_score 独立作用）
  - 虹膜个人基线：前3秒自动校准 + 持续自适应
  - 死区+线性衰减：偏移≤0.3满分，超出线性衰减
  - 闭眼/虹膜丢失 → gaze_concentration=0

输入依赖：
- landmarks: MediaPipe 478点人脸关键点
- head_pose_yaw/pitch: 用于 is_looking_at_screen 判定（不影响视线分）

输出：
- gaze_offset: 视线偏移 (x, y)，归一化到 [-1, 1]
- gaze_concentration: 视线集中度分数 (0-60)
"""

import logging
import math
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from config import HEAD_POSE

logger = logging.getLogger("eyefocus.detector")


# 默认配置：从 HEAD_POSE 加载，与头部姿态阈值保持一致
DEFAULT_GAZE_YAW_THRESH = HEAD_POSE.yaw_thresh   # 视线横向偏移阈值（度）
DEFAULT_GAZE_PITCH_THRESH = HEAD_POSE.pitch_thresh  # 视线纵向偏移阈值（度）

# v4.47: 虹膜基线校准参数
BASELINE_CALIBRATION_SECS = 3.0     # 首次校准采集时长
BASELINE_ADAPT_INTERVAL = 30.0      # 自适应间隔（秒）
BASELINE_ADAPT_ALPHA = 0.02         # 自适应 EMA 速率
BASELINE_COLLECT_MAX_SAMPLES = 90   # 校准期最多采集样本数（3s×30fps）

# v4.47: 死区阈值 — 偏移在此范围内不扣分（容忍自然扫视）
DEAD_ZONE = 0.3
# v4.47: 瞳孔偏移满分
PUPIL_SCORE_MAX = 60.0


@dataclass
class GazeResult:
    """视线方向检测结果"""
    gaze_offset: Tuple[float, float]  # (x, y) 视线偏移，归一化到 [-1, 1]
    gaze_concentration: float          # 视线集中度分数 (0-60)，v4.47: 纯瞳孔偏移分
    is_looking_at_screen: bool         # 是否在看屏幕
    left_eye_offset: Tuple[float, float]
    right_eye_offset: Tuple[float, float]


class GazeDetector:
    """视线方向检测器 (v4.47)

    纯瞳孔偏移模型：
    - 通过虹膜关键点 vs 眼睑中心计算视线偏移
    - 个人基线校准消除生理偏差
    - 死区容忍自然扫视（saccade）

    使用方法：
        detector = GazeDetector()
        result = detector.detect(landmarks, head_pose_yaw, head_pose_pitch)
    """

    # 左眼关键点索引 (参考 EAR 计算)
    LEFT_EYE_INDICES = (33, 160, 158, 133, 153, 144)
    RIGHT_EYE_INDICES = (362, 385, 387, 263, 380, 373)

    # MediaPipe 虹膜关键点索引（用于瞳孔位置计算）
    # 左虹膜: 468-472, 右虹膜: 473-477
    LEFT_IRIS_INDICES = (468, 469, 470, 471, 472)
    RIGHT_IRIS_INDICES = (473, 474, 475, 476, 477)

    def __init__(
        self,
        yaw_thresh: float = DEFAULT_GAZE_YAW_THRESH,
        pitch_thresh: float = DEFAULT_GAZE_PITCH_THRESH,
    ):
        """初始化视线检测器

        Args:
            yaw_thresh: yaw 阈值（度），超过视为头部偏离屏幕
            pitch_thresh: pitch 阈值（度），超过视为头部偏离屏幕
        """
        self.yaw_thresh = yaw_thresh
        self.pitch_thresh = pitch_thresh

        # v4.47: 虹膜个人基线
        self._baseline_offset: Tuple[float, float] = (0.0, 0.0)
        self._baseline_samples: List[Tuple[float, float]] = []
        self._baseline_ready: bool = False
        self._baseline_start_time: Optional[float] = None
        self._last_adapt_time: Optional[float] = None

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
        if landmarks is None or len(landmarks) < 478:
            return None

        try:
            current_time = time.time()

            # 提取左右眼的 6 个关键点
            left_eye = np.array([landmarks[i] for i in self.LEFT_EYE_INDICES])
            right_eye = np.array([landmarks[i] for i in self.RIGHT_EYE_INDICES])

            # 提取左右虹膜关键点（MediaPipe iris landmarks 468-477）
            left_iris = np.array([landmarks[i] for i in self.LEFT_IRIS_INDICES])
            right_iris = np.array([landmarks[i] for i in self.RIGHT_IRIS_INDICES])

            # 计算眼睑中心（眼角中点和眼尾中点的中点）
            left_center = self._eye_center(left_eye)
            right_center = self._eye_center(right_eye)

            # 计算瞳孔位置（虹膜中心）
            left_pupil = self._pupil_position(left_iris)
            right_pupil = self._pupil_position(right_iris)

            # 计算相对于眼睑中心的偏移
            left_offset = left_pupil - left_center
            right_offset = right_pupil - right_center

            # 归一化偏移量（使用眼宽作为参考）
            left_eye_width = np.linalg.norm(left_eye[0] - left_eye[3])
            right_eye_width = np.linalg.norm(right_eye[0] - right_eye[3])

            if left_eye_width < 1e-4 or right_eye_width < 1e-4:
                # v4.47: 闭眼/眼宽过小 → 虹膜检测失败，视线分=0
                return GazeResult(
                    gaze_offset=(0.0, 0.0),
                    gaze_concentration=0.0,
                    is_looking_at_screen=False,
                    left_eye_offset=(0.0, 0.0),
                    right_eye_offset=(0.0, 0.0),
                )

            left_offset_norm = left_offset / (left_eye_width / 2)
            right_offset_norm = right_offset / (right_eye_width / 2)

            # 综合左右眼的偏移
            avg_offset_x = (left_offset_norm[0] + right_offset_norm[0]) / 2
            avg_offset_y = (left_offset_norm[1] + right_offset_norm[1]) / 2

            # 限制在 [-1, 1] 范围
            gaze_offset_x = max(-1.0, min(1.0, avg_offset_x))
            gaze_offset_y = max(-1.0, min(1.0, avg_offset_y))

            # v4.47: 虹膜基线校准（首次3秒采集 + 持续自适应）
            self._update_baseline(gaze_offset_x, gaze_offset_y, current_time,
                                  head_pose_yaw, head_pose_pitch)

            # v4.47: 纯瞳孔偏移视线分（0-60），使用个人基线
            gaze_score = self._compute_gaze_score(gaze_offset_x, gaze_offset_y)

            # 判断是否在看屏幕（v4.47: 头部姿态检查 + 视线分≥30/60=50%）
            is_looking_at_screen = (
                abs(head_pose_yaw) <= self.yaw_thresh
                and abs(head_pose_pitch) <= self.pitch_thresh
                and gaze_score >= 30.0
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

    def _update_baseline(
        self,
        offset_x: float,
        offset_y: float,
        current_time: float,
        head_yaw: float,
        head_pitch: float,
    ) -> None:
        """v4.47: 更新虹膜个人基线

        首次校准：前3秒采集有效偏移量，取中位数作为基线
        持续自适应：每30秒用EMA微调基线
        """
        # 只采集头部大致正对屏幕时的样本（|yaw|<15, |pitch|<20）
        if abs(head_yaw) > 15.0 or abs(head_pitch) > 20.0:
            return

        if not self._baseline_ready:
            # 校准期：采集样本
            if self._baseline_start_time is None:
                self._baseline_start_time = current_time

            elapsed = current_time - self._baseline_start_time
            if elapsed <= BASELINE_CALIBRATION_SECS and len(self._baseline_samples) < BASELINE_COLLECT_MAX_SAMPLES:
                self._baseline_samples.append((offset_x, offset_y))
            elif elapsed > BASELINE_CALIBRATION_SECS and len(self._baseline_samples) >= 5:
                # 校准完成：取中位数
                xs = [s[0] for s in self._baseline_samples]
                ys = [s[1] for s in self._baseline_samples]
                self._baseline_offset = (float(np.median(xs)), float(np.median(ys)))
                self._baseline_ready = True
                self._last_adapt_time = current_time
                logger.info("虹膜基线校准完成: offset=(%.3f, %.3f), samples=%d",
                            self._baseline_offset[0], self._baseline_offset[1],
                            len(self._baseline_samples))
                self._baseline_samples.clear()  # 释放内存
        else:
            # 自适应：每30秒微调
            if self._last_adapt_time is not None and (current_time - self._last_adapt_time) >= BASELINE_ADAPT_INTERVAL:
                bx, by = self._baseline_offset
                self._baseline_offset = (
                    bx * (1.0 - BASELINE_ADAPT_ALPHA) + offset_x * BASELINE_ADAPT_ALPHA,
                    by * (1.0 - BASELINE_ADAPT_ALPHA) + offset_y * BASELINE_ADAPT_ALPHA,
                )
                self._last_adapt_time = current_time

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
        """计算瞳孔/虹膜中心位置

        Args:
            eye_points: 虹膜关键点数组（5个点：468-472 或 473-477）

        Returns:
            虹膜中心坐标（5个点的平均）
        """
        return np.mean(eye_points, axis=0)

    def _compute_gaze_score(
        self,
        offset_x: float,
        offset_y: float,
    ) -> float:
        """v4.47: 计算纯瞳孔偏移视线分 (0-60)

        使用个人基线校正 + 死区 + 线性衰减：
        - 有效偏移 = |实际偏移 - 个人基线|
        - 偏移幅度 ≤ 0.3（死区）→ 满分60
        - 超出死区 → 线性衰减至偏移=1.0时归零

        死区容忍正常的微小扫视（saccade），避免误扣分。
        """
        # 减去个人基线
        bx, by = self._baseline_offset
        effective_x = offset_x - bx
        effective_y = offset_y - by
        magnitude = math.sqrt(effective_x ** 2 + effective_y ** 2)

        # 死区+线性衰减
        if magnitude <= DEAD_ZONE:
            return PUPIL_SCORE_MAX
        else:
            # 从死区边界到1.0线性衰减：60分→0分
            # slope = 60 / (1.0 - 0.3) = 60 / 0.7 ≈ 85.714
            excess = magnitude - DEAD_ZONE
            score = PUPIL_SCORE_MAX - excess * (PUPIL_SCORE_MAX / (1.0 - DEAD_ZONE))
            return round(max(0.0, score), 1)

    def reset_baseline(self) -> None:
        """重置虹膜基线（用于重新校准）"""
        self._baseline_offset = (0.0, 0.0)
        self._baseline_samples.clear()
        self._baseline_ready = False
        self._baseline_start_time = None
        self._last_adapt_time = None

    @property
    def baseline_offset(self) -> Tuple[float, float]:
        """当前虹膜基线偏移"""
        return self._baseline_offset

    @property
    def baseline_ready(self) -> bool:
        """基线是否已就绪"""
        return self._baseline_ready


def create_gaze_detector() -> GazeDetector:
    """工厂函数：创建视线检测器（支持 YAML 配置覆盖）"""
    from config import get_yaml_value
    return GazeDetector(
        yaw_thresh=get_yaml_value("gaze", "yaw_thresh", default=20.0),
        pitch_thresh=get_yaml_value("gaze", "pitch_thresh", default=15.0),
    )

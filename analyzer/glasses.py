"""
analyzer/glasses.py — 眼镜检测模块

提供 GlassesDetector 类，基于 MediaPipe blendshapes 和眼角关键点距离
双保险判断用户是否戴眼镜。

检测方案：
1. blendshapes 眯眼比率：squint / (squint + wide) > 0.85 → 戴眼镜
2. 眼角关键点距离：内侧眼角距离 < 阈值 → 戴眼镜
3. 手动开关兜底：用户可强制指定模式
4. 双保险逻辑：两者之一触发即判定为戴眼镜

参考：Phase 0 实测数据
- 戴眼镜用户：squint ratio 0.85-0.99，眼角距离偏小
- 正常用户：squint ratio < 0.85，眼角距离正常
"""

import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from storage.models import GlassesDetectionResult, GlassesMode

logger = logging.getLogger("eyefocus.analyzer")


# 默认配置
DEFAULT_SQUINT_RATIO_THRESHOLD = 0.85
DEFAULT_INNER_CANTHUS_RATIO_THRESHOLD = 0.5  # 归一化比值（基于 Phase 0 实测 28px/55px ≈ 0.51）
DEFAULT_CONFIDENCE_WEIGHT_SQUINT = 0.6
DEFAULT_CONFIDENCE_WEIGHT_DISTANCE = 0.4


# MediaPipe 人脸关键点索引
LEFT_INNER_CANTHUS = 133  # 左眼内侧眼角
RIGHT_INNER_CANTHUS = 362  # 右眼内侧眼角
LEFT_OUTER_CANTHUS = 33  # 左眼外侧眼角
RIGHT_OUTER_CANTHUS = 263  # 右眼外侧眼角

# 眼部关键点索引（用于计算瞳孔距离，与 gaze.py 保持一致）
LEFT_EYE_INDICES = (33, 160, 158, 133, 153, 144)
RIGHT_EYE_INDICES = (362, 385, 387, 263, 380, 373)

# Blendshapes 名称
BLENDSHAPE_SQUINT_LEFT = "eyeSquintLeft"
BLENDSHAPE_SQUINT_RIGHT = "eyeSquintRight"
BLENDSHAPE_WIDE_LEFT = "eyeWideLeft"
BLENDSHAPE_WIDE_RIGHT = "eyeWideRight"


@dataclass
class GlassesInfo:
    """眼镜检测信息（调试用）"""
    squint_ratio: float
    inner_canthus_distance: float
    inner_canthus_ratio: float  # inner_canthus_distance / pupil_distance
    squint_left: float
    squint_right: float
    wide_left: float
    wide_right: float
    detection_method: str
    confidence: float


class GlassesDetector:
    """眼镜检测器

    使用方法：
        detector = GlassesDetector()
        result = detector.detect(landmarks, blendshapes)

        # 或手动设置模式
        detector.set_manual_mode(GlassesMode.WITH_GLASSES)
    """

    def __init__(
        self,
        squint_ratio_thresh: float = DEFAULT_SQUINT_RATIO_THRESHOLD,
        inner_canthus_ratio_thresh: float = DEFAULT_INNER_CANTHUS_RATIO_THRESHOLD,
        squint_weight: float = DEFAULT_CONFIDENCE_WEIGHT_SQUINT,
        distance_weight: float = DEFAULT_CONFIDENCE_WEIGHT_DISTANCE,
    ):
        """初始化眼镜检测器

        Args:
            squint_ratio_thresh: 眯眼比率阈值
            inner_canthus_ratio_thresh: 内侧眼角/瞳孔距离比值阈值
            squint_weight: blendshapes 方法的置信度权重
            distance_weight: 眼角距离方法的置信度权重
        """
        self.squint_ratio_thresh = squint_ratio_thresh
        self.inner_canthus_ratio_thresh = inner_canthus_ratio_thresh
        self.squint_weight = squint_weight
        self.distance_weight = distance_weight

        # 手动模式覆盖
        self._manual_mode: Optional[GlassesMode] = None

        # 统计信息
        self._detection_count = 0
        self._glasses_count = 0

    def detect(
        self,
        landmarks: Optional[np.ndarray] = None,
        blendshapes: Optional[dict] = None,
    ) -> GlassesDetectionResult:
        """检测是否戴眼镜

        Args:
            landmarks: MediaPipe 人脸关键点 (478, 2) 像素坐标
            blendshapes: MediaPipe blendshapes 字典

        Returns:
            GlassesDetectionResult 对象
        """
        # 手动模式优先
        if self._manual_mode is not None:
            is_glasses = self._manual_mode in (
                GlassesMode.WITH_GLASSES,
                GlassesMode.MANUAL_GLASSES,
            )
            return GlassesDetectionResult(
                is_glasses=is_glasses,
                confidence=1.0,
                method="manual",
            )

        # 方法 1: blendshapes 眯眼比率
        squint_result = self._detect_by_squint(blendshapes) if blendshapes else None

        # 方法 2: 眼角距离
        distance_result = self._detect_by_distance(landmarks) if landmarks is not None else None

        # 双保险逻辑：两者之一触发即判定
        is_glasses = False
        method_parts = []
        confidence = 0.0

        if squint_result is not None and squint_result[0]:
            is_glasses = True
            method_parts.append("blendshapes")
            confidence = max(confidence, squint_result[1])

        if distance_result is not None and distance_result[0]:
            is_glasses = True
            method_parts.append("distance")
            confidence = max(confidence, distance_result[1])

        method = "+".join(method_parts) if method_parts else "none"

        # 如果两者都没触发，使用置信度较高的结果（即使是 negative）
        if not is_glasses and (squint_result or distance_result):
            if squint_result and squint_result[1] > 0.7:
                confidence = squint_result[1]
            elif distance_result and distance_result[1] > 0.7:
                confidence = distance_result[1]

        self._detection_count += 1
        if is_glasses:
            self._glasses_count += 1

        return GlassesDetectionResult(
            is_glasses=is_glasses,
            confidence=confidence,
            squint_ratio=squint_result[2] if squint_result else None,
            inner_canthus_distance=distance_result[2] if distance_result else None,
            inner_canthus_ratio=distance_result[3] if distance_result else None,
            method=method,
        )

    def _detect_by_squint(
        self,
        blendshapes: dict,
    ) -> Optional[tuple]:
        """通过 blendshapes 眯眼比率检测

        眯眼比率 = squint / (squint + wide)
        戴眼镜用户：眼镜框支撑导致眯眼比例高

        Returns:
            (is_glasses, confidence, squint_ratio) 元组，或 None
        """
        try:
            # 检查必需键是否存在
            required_keys = {
                BLENDSHAPE_SQUINT_LEFT,
                BLENDSHAPE_SQUINT_RIGHT,
                BLENDSHAPE_WIDE_LEFT,
                BLENDSHAPE_WIDE_RIGHT,
            }
            if not required_keys.issubset(blendshapes.keys()):
                return None

            squint_left = blendshapes[BLENDSHAPE_SQUINT_LEFT]
            squint_right = blendshapes[BLENDSHAPE_SQUINT_RIGHT]
            wide_left = blendshapes[BLENDSHAPE_WIDE_LEFT]
            wide_right = blendshapes[BLENDSHAPE_WIDE_RIGHT]

            squint_sum = squint_left + squint_right
            wide_sum = wide_left + wide_right
            total = squint_sum + wide_sum

            if total < 1e-6:
                return None

            squint_ratio = squint_sum / total

            is_glasses = squint_ratio > self.squint_ratio_thresh

            # 置信度：超出阈值越多，置信度越高
            if is_glasses:
                confidence = min(1.0, (squint_ratio - self.squint_ratio_thresh) / 0.1 + 0.7)
            else:
                confidence = min(1.0, (self.squint_ratio_thresh - squint_ratio) / 0.1 + 0.7)

            return (is_glasses, confidence, squint_ratio)

        except Exception as e:
            logger.warning("blendshapes 检测失败: %s", e)
            return None

    def _compute_pupil_distance(self, landmarks: np.ndarray) -> Optional[float]:
        """计算双眼瞳孔距离（用于归一化）

        使用左右眼外侧眼角（33 和 263）的距离作为瞳孔距离的近似。
        这与 gaze.py 中眼宽计算使用的是同一组关键点。

        Returns:
            瞳孔距离（像素），或 None（计算失败）
        """
        try:
            left_eye = np.array([landmarks[i] for i in LEFT_EYE_INDICES])
            right_eye = np.array([landmarks[i] for i in RIGHT_EYE_INDICES])

            # 左眼外侧眼角（索引 0 = 33）和内侧眼角（索引 3 = 133）之间的距离
            left_pupil_x = (left_eye[0][0] + left_eye[3][0]) / 2
            left_pupil_y = (left_eye[0][1] + left_eye[3][1]) / 2
            right_pupil_x = (right_eye[0][0] + right_eye[3][0]) / 2
            right_pupil_y = (right_eye[0][1] + right_eye[3][1]) / 2

            return math.sqrt((right_pupil_x - left_pupil_x) ** 2 + (right_pupil_y - left_pupil_y) ** 2)
        except Exception:
            return None

    def _detect_by_distance(
        self,
        landmarks: np.ndarray,
    ) -> Optional[tuple]:
        """通过眼角关键点距离检测（归一化比值版本）

        戴眼镜用户的内侧眼角距离通常较小（眼镜框遮挡）
        使用 inner_canthus_distance / pupil_distance 比值来判定，
        这样在不同分辨率下都能正常工作。

        Returns:
            (is_glasses, confidence, distance, ratio) 元组，或 None
        """
        try:
            # 计算瞳孔距离（归一化基准）
            pupil_distance = self._compute_pupil_distance(landmarks)
            if pupil_distance is None or pupil_distance < 1e-4:
                return None

            # 计算内侧眼角距离
            left_inner = landmarks[LEFT_INNER_CANTHUS]
            right_inner = landmarks[RIGHT_INNER_CANTHUS]
            distance = float(np.linalg.norm(left_inner - right_inner))

            # 计算比值并判定
            ratio = distance / pupil_distance
            is_glasses = ratio < self.inner_canthus_ratio_thresh

            # 置信度（基于比值与阈值的偏差）
            if is_glasses:
                confidence = min(1.0, (self.inner_canthus_ratio_thresh - ratio) / 0.05 + 0.7)
            else:
                confidence = min(1.0, (ratio - self.inner_canthus_ratio_thresh) / 0.05 + 0.7)

            return (is_glasses, confidence, distance, ratio)

        except Exception as e:
            logger.warning("眼角距离检测失败: %s", e)
            return None

    def set_manual_mode(self, mode: GlassesMode) -> None:
        """手动设置眼镜模式

        Args:
            mode: GlassesMode 枚举
        """
        self._manual_mode = mode
        logger.info("眼镜检测已设置为手动模式: %s", mode.value)

    def clear_manual_mode(self) -> None:
        """清除手动模式，恢复自动检测"""
        self._manual_mode = None
        logger.info("眼镜检测已恢复自动模式")

    def get_glasses_rate(self) -> float:
        """获取历史检测中戴眼镜的比例"""
        if self._detection_count == 0:
            return 0.0
        return self._glasses_count / self._detection_count

    def reset(self) -> None:
        """重置检测器状态"""
        self._manual_mode = None
        self._detection_count = 0
        self._glasses_count = 0

    def get_stats(self) -> dict:
        """获取检测统计信息"""
        return {
            "manual_mode": self._manual_mode.value if self._manual_mode else None,
            "detection_count": self._detection_count,
            "glasses_count": self._glasses_count,
            "glasses_rate": self.get_glasses_rate(),
            "squint_ratio_thresh": self.squint_ratio_thresh,
            "inner_canthus_ratio_thresh": self.inner_canthus_ratio_thresh,
        }


def create_glasses_detector() -> GlassesDetector:
    """工厂函数：创建眼镜检测器"""
    return GlassesDetector()

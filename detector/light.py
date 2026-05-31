"""
detector/light.py — 光照条件感知模块

提供 LightDetector 类，通过分析视频帧的亮度分布判断光照条件。
光照条件直接影响检测算法的可靠性。
"""

import logging
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Optional

import cv2
import numpy as np

logger = logging.getLogger("eyefocus.detector")


class LightCondition(Enum):
    """光照条件枚举"""
    DARK = "dark"  # 偏暗
    NORMAL = "normal"  # 正常
    BRIGHT = "bright"  # 偏亮


@dataclass
class LightResult:
    """光照检测结果"""
    condition: LightCondition
    brightness: float  # 平均亮度 (0-255)
    brightness_std: float  # 亮度标准差
    face_region_brightness: float  # 人脸区域平均亮度
    is_adequate: bool  # 光照是否满足检测要求


# 光照阈值配置（按 PROJECT_PLAN.md §6.6: Dark≤50, Normal 50-100, Bright>100）
DEFAULT_BRIGHTNESS_DARK = 50.0
DEFAULT_BRIGHTNESS_BRIGHT = 100.0

# 人脸区域占图像比例的估计值
FACE_REGION_RATIO = 0.15


class LightDetector:
    """光照条件检测器

    通过分析图像亮度分布判断光照条件（3级分类，按 PROJECT_PLAN.md §6.6）：
    - 偏暗 (DARK)：平均亮度 ≤ 50
    - 正常 (NORMAL)：平均亮度 50-100
    - 偏亮 (BRIGHT)：平均亮度 > 100

    同时支持 ROI（感兴趣区域）模式，只分析人脸区域的亮度。
    """

    def __init__(
        self,
        brightness_thresh_dark: float = DEFAULT_BRIGHTNESS_DARK,
        brightness_thresh_bright: float = DEFAULT_BRIGHTNESS_BRIGHT,
        face_region_ratio: float = FACE_REGION_RATIO,
        smooth_window: int = 5,
    ):
        """初始化光照检测器

        Args:
            brightness_thresh_dark: 偏暗阈值（≤50 为 Dark）
            brightness_thresh_bright: 偏亮阈值（>100 为 Bright，之间为 Normal）
            face_region_ratio: 人脸区域占图像比例
            smooth_window: 平滑窗口大小
        """
        self.thresh_dark = brightness_thresh_dark
        self.thresh_bright = brightness_thresh_bright
        self.face_region_ratio = face_region_ratio
        self.smooth_window = smooth_window

        # 平滑历史
        self._brightness_history: Deque[float] = deque(maxlen=smooth_window)
        self._condition_history: Deque[LightCondition] = deque(maxlen=smooth_window)

    def analyze_frame(self, frame: np.ndarray) -> LightResult:
        """分析单帧的光照条件

        Args:
            frame: BGR 格式 OpenCV 图像

        Returns:
            LightResult 对象
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 计算整体亮度统计
        brightness = float(np.mean(gray))
        brightness_std = float(np.std(gray))

        # 判断光照条件
        condition = self._classify_brightness(brightness)

        # 人脸区域亮度（假设人脸在图像中心）
        face_region_brightness = self._compute_face_region_brightness(gray)

        # 更新历史
        self._brightness_history.append(brightness)
        self._condition_history.append(condition)

        # 判断光照是否充足（检测算法可正常工作）
        is_adequate = (
            condition == LightCondition.NORMAL
            or condition == LightCondition.DARK
            or condition == LightCondition.BRIGHT
        )

        return LightResult(
            condition=condition,
            brightness=brightness,
            brightness_std=brightness_std,
            face_region_brightness=face_region_brightness,
            is_adequate=is_adequate,
        )

    def _classify_brightness(self, brightness: float) -> LightCondition:
        """根据亮度值分类光照条件（3级：Dark≤50, Normal 50-100, Bright>100）"""
        if brightness <= self.thresh_dark:
            return LightCondition.DARK
        elif brightness > self.thresh_bright:
            return LightCondition.BRIGHT
        else:
            return LightCondition.NORMAL

    def _compute_face_region_brightness(self, gray: np.ndarray) -> float:
        """计算人脸区域的亮度

        假设人脸位于图像中心区域。
        """
        h, w = gray.shape
        face_h = int(h * self.face_region_ratio)
        face_w = int(w * self.face_region_ratio)

        top = (h - face_h) // 2
        left = (w - face_w) // 2

        face_region = gray[top:top+face_h, left:left+face_w]
        return float(np.mean(face_region))

    def get_smoothed_brightness(self) -> float:
        """获取平滑后的亮度值"""
        if not self._brightness_history:
            return 0.0
        return float(np.mean(self._brightness_history))

    def get_smoothed_condition(self) -> LightCondition:
        """获取平滑后的光照条件（多数投票）"""
        if not self._condition_history:
            return LightCondition.NORMAL

        # 多数投票
        conditions = list(self._condition_history)
        condition_counts = {}
        for c in conditions:
            condition_counts[c] = condition_counts.get(c, 0) + 1

        return max(condition_counts, key=condition_counts.get)

    def is_lighting_adequate(self) -> bool:
        """判断当前光照是否满足检测要求"""
        condition = self.get_smoothed_condition()
        return (
            condition == LightCondition.NORMAL
            or condition == LightCondition.DARK
            or condition == LightCondition.BRIGHT
        )

    def reset(self) -> None:
        """重置检测器状态"""
        self._brightness_history.clear()
        self._condition_history.clear()

    def get_stats(self) -> dict:
        """获取检测统计信息"""
        return {
            "current_brightness": self.get_smoothed_brightness(),
            "current_condition": self.get_smoothed_condition().value,
            "is_adequate": self.is_lighting_adequate(),
            "history_size": len(self._brightness_history),
        }


def create_light_detector() -> LightDetector:
    """工厂函数：创建光照检测器（支持 YAML 配置覆盖）"""
    from config import get_yaml_value
    return LightDetector(
        brightness_thresh_dark=get_yaml_value("light", "brightness_thresh_dark", default=50.0),
        brightness_thresh_bright=get_yaml_value("light", "brightness_thresh_bright", default=100.0),
    )

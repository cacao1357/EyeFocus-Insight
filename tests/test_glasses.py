"""
tests/test_glasses.py — GlassesDetector 单元测试
覆盖 analyzer/glasses.py 中可离线测试的函数。
"""

import sys
import os

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyzer.glasses import (
    GlassesInfo,
    GlassesDetector,
    create_glasses_detector,
    DEFAULT_SQUINT_RATIO_THRESHOLD,
    DEFAULT_INNER_CANTHUS_RATIO_THRESHOLD,
)
from storage.models import GlassesMode, GlassesDetectionResult


# ============================================================================
# Mock 数据构造辅助函数
# ============================================================================

def make_landmarks(distance: float = 30.0, pupil_distance: float = 56.0):
    """创建指定内侧眼角距离和瞳孔距离的 landmarks

    Args:
        distance: 内侧眼角之间的距离（像素）
        pupil_distance: 双眼瞳孔距离（像素），默认 56.0

    MediaPipe 关键点索引：
    - LEFT_INNER_CANTHUS = 133
    - RIGHT_INNER_CANTHUS = 362
    - LEFT_EYE_INDICES = (33, 160, 158, 133, 153, 144)
    - RIGHT_EYE_INDICES = (362, 385, 387, 263, 380, 373)

    瞳孔位置通过 eye[0] 和 eye[3] 的中点计算。
    左眼：eye[0]=33 和 eye[3]=133 的中点 = 左瞳孔位置
    右眼：eye[0]=362 和 eye[3]=263 的中点 = 右瞳孔位置
    """
    landmarks = np.zeros((468, 3), dtype=np.float64)
    eye_y = 200

    # 左眼瞳孔 x 位置（作为所有左眼关键点的参考）
    left_pupil_x = 200.0
    # 右眼瞳孔 x 位置
    right_pupil_x = left_pupil_x + pupil_distance

    # 左眼：eye[0]=33 和 eye[3]=133 中点为左瞳孔
    landmarks[133] = [left_pupil_x, eye_y, 0]  # eye[3] = 内侧眼角
    landmarks[33] = [left_pupil_x, eye_y, 0]   # eye[0] = 外侧眼角
    landmarks[160] = [left_pupil_x, eye_y - 8, 0]
    landmarks[158] = [left_pupil_x, eye_y + 8, 0]
    landmarks[153] = [left_pupil_x, eye_y - 5, 0]
    landmarks[144] = [left_pupil_x, eye_y + 5, 0]

    # 右眼：eye[0]=362 和 eye[3]=263 中点为右瞳孔
    # 设右眼内侧眼角(362)在 x，右眼外侧眼角(263)在 x+28
    # 则中点 = (x + x + 28) / 2 = x + 14 = right_pupil_x
    # 所以 x = right_pupil_x - 14
    landmarks[362] = [right_pupil_x - 14, eye_y, 0]  # eye[0] = 内侧眼角
    landmarks[263] = [right_pupil_x + 14, eye_y, 0]   # eye[3] = 外侧眼角
    landmarks[385] = [right_pupil_x, eye_y - 8, 0]
    landmarks[387] = [right_pupil_x, eye_y + 8, 0]
    landmarks[380] = [right_pupil_x, eye_y - 5, 0]
    landmarks[373] = [right_pupil_x, eye_y + 5, 0]

    # 覆盖内侧眼角以实现指定的距离
    landmarks[133] = [left_pupil_x, eye_y, 0]
    landmarks[362] = [left_pupil_x + distance, eye_y, 0]
    # 重新计算右眼外侧眼角位置以保持瞳孔距离不变
    landmarks[263] = [2 * right_pupil_x - landmarks[362][0], eye_y, 0]

    return landmarks


def make_blendshapes(squint_left=0.5, squint_right=0.5, wide_left=0.1, wide_right=0.1):
    """创建指定眯眼比率的 blendshapes

    squint_ratio = (squint_left + squint_right) / (squint_left + squint_right + wide_left + wide_right)

    Examples:
        squint=(0.5, 0.5), wide=(0.1, 0.1) → ratio = 1.0/(1.0+0.2) = 0.83
        squint=(0.9, 0.9), wide=(0.05, 0.05) → ratio = 1.8/(1.8+0.1) = 0.95
    """
    return {
        "eyeSquintLeft": squint_left,
        "eyeSquintRight": squint_right,
        "eyeWideLeft": wide_left,
        "eyeWideRight": wide_right,
    }


# ============================================================================
# TestGlassesInfo
# ============================================================================

class TestGlassesInfo:
    """GlassesInfo dataclass 测试"""

    def test_info_creation(self):
        """测试 GlassesInfo 创建和属性访问"""
        info = GlassesInfo(
            squint_ratio=0.9,
            inner_canthus_distance=25.0,
            inner_canthus_ratio=0.45,
            squint_left=0.45,
            squint_right=0.45,
            wide_left=0.05,
            wide_right=0.05,
            detection_method="blendshapes",
            confidence=0.95,
        )
        assert info.squint_ratio == 0.9
        assert info.inner_canthus_distance == 25.0
        assert info.inner_canthus_ratio == 0.45
        assert info.squint_left == 0.45
        assert info.squint_right == 0.45
        assert info.wide_left == 0.05
        assert info.wide_right == 0.05
        assert info.detection_method == "blendshapes"
        assert info.confidence == 0.95


# ============================================================================
# TestGlassesDetector
# ============================================================================

class TestGlassesDetector:
    """GlassesDetector 单元测试"""

    def test_initial_state(self):
        """测试初始状态"""
        detector = GlassesDetector()
        stats = detector.get_stats()
        assert stats["manual_mode"] is None
        assert stats["detection_count"] == 0
        assert stats["glasses_count"] == 0
        assert stats["glasses_rate"] == 0.0
        assert stats["squint_ratio_thresh"] == DEFAULT_SQUINT_RATIO_THRESHOLD
        assert stats["inner_canthus_ratio_thresh"] == DEFAULT_INNER_CANTHUS_RATIO_THRESHOLD

    # ------------------------------------------------------------------------
    # Manual mode tests
    # ------------------------------------------------------------------------

    def test_manual_mode_with_glasses(self):
        """测试手动模式设置为戴眼镜"""
        detector = GlassesDetector()
        detector.set_manual_mode(GlassesMode.WITH_GLASSES)

        result = detector.detect(landmarks=make_landmarks(30), blendshapes=make_blendshapes(0.5, 0.5, 0.1, 0.1))
        assert result.is_glasses is True
        assert result.confidence == 1.0
        assert result.method == "manual"

    def test_manual_mode_without_glasses(self):
        """测试手动模式设置为不戴眼镜"""
        detector = GlassesDetector()
        detector.set_manual_mode(GlassesMode.MANUAL_NO_GLASSES)

        # 即使 squint ratio 很高，也应该返回不戴眼镜
        result = detector.detect(landmarks=make_landmarks(20), blendshapes=make_blendshapes(0.95, 0.95, 0.05, 0.05))
        assert result.is_glasses is False
        assert result.confidence == 1.0
        assert result.method == "manual"

    def test_manual_mode_cleared(self):
        """测试清除手动模式后恢复自动检测"""
        detector = GlassesDetector()
        detector.set_manual_mode(GlassesMode.WITH_GLASSES)
        detector.clear_manual_mode()

        # 清除后应该使用自动检测
        # squint ratio 0.83 < 0.85，不触发眯眼检测
        # distance 30 > 28，不触发距离检测
        result = detector.detect(landmarks=make_landmarks(30), blendshapes=make_blendshapes(0.5, 0.5, 0.1, 0.1))
        assert result.is_glasses is False
        assert result.confidence > 0  # 应该有置信度

    # ------------------------------------------------------------------------
    # Squint detection tests
    # ------------------------------------------------------------------------

    def test_detect_by_squint_high_ratio(self):
        """测试眯眼检测：ratio > 0.85 → 戴眼镜"""
        detector = GlassesDetector()
        # squint=(0.9, 0.9), wide=(0.05, 0.05) → ratio = 1.8/1.9 = 0.947
        blendshapes = make_blendshapes(squint_left=0.9, squint_right=0.9, wide_left=0.05, wide_right=0.05)
        result = detector._detect_by_squint(blendshapes)

        assert result is not None
        is_glasses, confidence, squint_ratio = result
        assert is_glasses is True
        assert squint_ratio > 0.85
        assert 0.0 <= confidence <= 1.0

    def test_detect_by_squint_low_ratio(self):
        """测试眯眼检测：ratio < 0.85 → 不戴眼镜"""
        detector = GlassesDetector()
        # squint=(0.5, 0.5), wide=(0.1, 0.1) → ratio = 1.0/1.2 = 0.833
        blendshapes = make_blendshapes(squint_left=0.5, squint_right=0.5, wide_left=0.1, wide_right=0.1)
        result = detector._detect_by_squint(blendshapes)

        assert result is not None
        is_glasses, confidence, squint_ratio = result
        assert is_glasses is False
        assert squint_ratio < 0.85
        assert 0.0 <= confidence <= 1.0

    def test_detect_by_squint_boundary(self):
        """测试眯眼检测：ratio ≈ 0.85 边界情况"""
        detector = GlassesDetector()
        # squint=(0.85, 0.85), wide=(0.15, 0.15) → ratio = 1.7/2.0 = 0.85
        blendshapes = make_blendshapes(squint_left=0.85, squint_right=0.85, wide_left=0.15, wide_right=0.15)
        result = detector._detect_by_squint(blendshapes)

        assert result is not None
        is_glasses, confidence, squint_ratio = result
        # 0.85 不大于 0.85 阈值，所以 is_glasses = False
        assert squint_ratio == pytest.approx(0.85, abs=0.001)
        assert is_glasses is False

    def test_detect_by_squint_missing_keys(self):
        """测试眯眼检测：blendshapes 缺少键"""
        detector = GlassesDetector()
        # 只提供部分键
        blendshapes = {"eyeLookDownLeft": 0.5}
        result = detector._detect_by_squint(blendshapes)

        assert result is None

    def test_detect_by_squint_all_zeros(self):
        """测试眯眼检测：所有值为 0"""
        detector = GlassesDetector()
        blendshapes = make_blendshapes(squint_left=0.0, squint_right=0.0, wide_left=0.0, wide_right=0.0)
        result = detector._detect_by_squint(blendshapes)

        # total < 1e-6 时返回 None
        assert result is None

    # ------------------------------------------------------------------------
    # Distance detection tests
    # ------------------------------------------------------------------------

    def test_detect_by_distance_short(self):
        """测试距离检测：ratio < 0.5 → 戴眼镜（瞳孔距离 56，内眼角距离 20，ratio≈0.36）"""
        detector = GlassesDetector()
        landmarks = make_landmarks(distance=20.0, pupil_distance=56.0)
        result = detector._detect_by_distance(landmarks)

        assert result is not None
        is_glasses, confidence, distance, ratio = result
        assert is_glasses is True
        assert ratio < 0.5
        assert 0.0 <= confidence <= 1.0

    def test_detect_by_distance_long(self):
        """测试距离检测：ratio > 0.5 → 不戴眼镜（瞳孔距离 56，内眼角距离 35，ratio≈0.63）"""
        detector = GlassesDetector()
        landmarks = make_landmarks(distance=35.0, pupil_distance=56.0)
        result = detector._detect_by_distance(landmarks)

        assert result is not None
        is_glasses, confidence, distance, ratio = result
        assert is_glasses is False
        assert ratio > 0.5
        assert 0.0 <= confidence <= 1.0

    def test_detect_by_distance_boundary(self):
        """测试距离检测：ratio = 0.5 边界情况（瞳孔距离 56，内眼角距离 28）"""
        detector = GlassesDetector()
        landmarks = make_landmarks(distance=28.0, pupil_distance=56.0)
        result = detector._detect_by_distance(landmarks)

        assert result is not None
        is_glasses, confidence, distance, ratio = result
        # 0.5 不小于 0.5 阈值，所以 is_glasses = False
        assert ratio == pytest.approx(0.5, abs=0.001)
        assert is_glasses is False

    # ------------------------------------------------------------------------
    # Combined detection (dual insurance)
    # ------------------------------------------------------------------------

    def test_combined_both_trigger_glasses(self):
        """测试双重检测：两者都触发戴眼镜"""
        detector = GlassesDetector()
        # squint ratio 高 + 距离近
        landmarks = make_landmarks(distance=20.0)  # < 28
        blendshapes = make_blendshapes(squint_left=0.9, squint_right=0.9, wide_left=0.05, wide_right=0.05)  # ratio ≈ 0.95

        result = detector.detect(landmarks=landmarks, blendshapes=blendshapes)

        assert result.is_glasses is True
        assert "blendshapes" in result.method
        assert "distance" in result.method
        assert result.confidence > 0

    def test_combined_one_triggers_glasses(self):
        """测试双重检测：只有其中一个触发戴眼镜"""
        detector = GlassesDetector()

        # 场景 1：squint 触发，距离不触发
        landmarks = make_landmarks(distance=35.0)  # > 28，不触发
        blendshapes = make_blendshapes(squint_left=0.95, squint_right=0.95, wide_left=0.05, wide_right=0.05)  # ratio > 0.85

        result = detector.detect(landmarks=landmarks, blendshapes=blendshapes)
        assert result.is_glasses is True
        assert "blendshapes" in result.method

        # 场景 2：距离触发，squint 不触发
        detector.reset()
        landmarks = make_landmarks(distance=20.0)  # < 28，触发
        blendshapes = make_blendshapes(squint_left=0.5, squint_right=0.5, wide_left=0.1, wide_right=0.1)  # ratio ≈ 0.83

        result = detector.detect(landmarks=landmarks, blendshapes=blendshapes)
        assert result.is_glasses is True
        assert "distance" in result.method

    def test_combined_neither_triggers(self):
        """测试双重检测：两者都不触发戴眼镜"""
        detector = GlassesDetector()
        # squint ratio 低 + 距离远
        landmarks = make_landmarks(distance=35.0)
        blendshapes = make_blendshapes(squint_left=0.5, squint_right=0.5, wide_left=0.1, wide_right=0.1)

        result = detector.detect(landmarks=landmarks, blendshapes=blendshapes)

        assert result.is_glasses is False
        assert result.method == "none"

    def test_combined_neither_triggers_with_fallback_confidence(self):
        """测试双重检测：两者都不触发但有 fallback 置信度"""
        detector = GlassesDetector()
        # squint ratio 略低于阈值，distance 略高于阈值
        landmarks = make_landmarks(distance=30.0)
        blendshapes = make_blendshapes(squint_left=0.7, squint_right=0.7, wide_left=0.2, wide_right=0.2)  # ratio = 1.4/1.8 ≈ 0.78

        result = detector.detect(landmarks=landmarks, blendshapes=blendshapes)

        assert result.is_glasses is False
        # 由于 squint_ratio=0.78 < 0.85，confidence 计算：(0.85-0.78)/0.1+0.7 = 1.4，但 capped at 1.0
        # 实际上这个会返回 confidence 0.7，因为 else 分支
        assert result.confidence > 0

    # ------------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------------

    def test_glasses_rate(self):
        """测试眼镜检测比率统计"""
        detector = GlassesDetector()

        # 检测 3 次，2 次戴眼镜
        detector.detect(landmarks=make_landmarks(20.0), blendshapes=make_blendshapes(0.9, 0.9, 0.05, 0.05))  # glasses
        detector.detect(landmarks=make_landmarks(35.0), blendshapes=make_blendshapes(0.9, 0.9, 0.05, 0.05))  # glasses (blendshapes trigger)
        detector.detect(landmarks=make_landmarks(35.0), blendshapes=make_blendshapes(0.5, 0.5, 0.1, 0.1))  # no glasses

        assert detector.get_glasses_rate() == pytest.approx(2.0 / 3.0, abs=0.001)

    def test_glasses_rate_no_detections(self):
        """测试无检测时眼镜比率为 0"""
        detector = GlassesDetector()
        assert detector.get_glasses_rate() == 0.0

    def test_reset_clears_state(self):
        """测试 reset() 清除所有状态"""
        detector = GlassesDetector()

        # 进行一些检测
        detector.detect(landmarks=make_landmarks(20.0), blendshapes=make_blendshapes(0.9, 0.9, 0.05, 0.05))
        detector.set_manual_mode(GlassesMode.WITH_GLASSES)

        detector.reset()

        stats = detector.get_stats()
        assert stats["manual_mode"] is None
        assert stats["detection_count"] == 0
        assert stats["glasses_count"] == 0
        assert stats["glasses_rate"] == 0.0

    def test_stats(self):
        """测试 get_stats() 返回完整统计"""
        detector = GlassesDetector()

        detector.detect(landmarks=make_landmarks(20.0), blendshapes=make_blendshapes(0.9, 0.9, 0.05, 0.05))
        detector.set_manual_mode(GlassesMode.WITH_GLASSES)

        stats = detector.get_stats()

        assert "manual_mode" in stats
        assert "detection_count" in stats
        assert "glasses_count" in stats
        assert "glasses_rate" in stats
        assert "squint_ratio_thresh" in stats
        assert "inner_canthus_ratio_thresh" in stats
        assert stats["detection_count"] == 1
        assert stats["glasses_count"] == 1

    # ------------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------------

    def test_detect_no_landmarks_no_blendshapes(self):
        """测试无 landmarks 和 blendshapes 时返回无方法结果"""
        detector = GlassesDetector()
        result = detector.detect()

        assert result.is_glasses is False
        assert result.method == "none"

    def test_detect_only_landmarks(self):
        """测试只提供 landmarks"""
        detector = GlassesDetector()
        landmarks = make_landmarks(distance=20.0)  # < 28，触发

        result = detector.detect(landmarks=landmarks)

        assert result.is_glasses is True
        assert "distance" in result.method

    def test_detect_only_blendshapes(self):
        """测试只提供 blendshapes"""
        detector = GlassesDetector()
        blendshapes = make_blendshapes(squint_left=0.9, squint_right=0.9, wide_left=0.05, wide_right=0.05)  # ratio > 0.85

        result = detector.detect(blendshapes=blendshapes)

        assert result.is_glasses is True
        assert "blendshapes" in result.method


# ============================================================================
# TestFactoryFunction
# ============================================================================

class TestFactoryFunction:
    """工厂函数测试"""

    def test_create_glasses_detector(self):
        """测试 create_glasses_detector 工厂函数"""
        detector = create_glasses_detector()
        assert isinstance(detector, GlassesDetector)
        assert detector.squint_ratio_thresh == DEFAULT_SQUINT_RATIO_THRESHOLD
        assert detector.inner_canthus_ratio_thresh == DEFAULT_INNER_CANTHUS_RATIO_THRESHOLD

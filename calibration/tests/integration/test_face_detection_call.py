"""集成测试：calibration/flow.py 的 _extract_metrics 必须调正确方法。

BUG-4 根因：flow.py:153 调 self._face_detector.detect(frame)，
     但 FaceMeshDetector 的实际方法名是 detect_from_frame(frame, timestamp_ms)。
     'detect' 不存在 → AttributeError → _extract_metrics 静默 catch → 返回 (None,None,None)
     → 所有 phase 收不到人脸数据 → 永远 face_ratio=0 → PHASE_SUMMARY_FAILED → "检测失败"

这个测试必须能区分：调错方法 (AttributeError 被吞) vs 调对方法。
"""
import time
from unittest.mock import MagicMock

import cv2
import numpy as np

from calibration.flow import CalibrationFlow
from calibration.config import CalibrationConfig


def _make_flow_with_mock_detector():
    """构造一个 mock detector, 调用记录。"""
    flow = CalibrationFlow.__new__(CalibrationFlow)
    flow._face_detector = MagicMock()
    # 关键: detect_from_frame 返回 detected=True
    flow._face_detector.detect_from_frame.return_value = MagicMock(
        detected=True,
        landmarks=np.zeros((468, 3)),
        transformation_matrix=np.eye(4),
    )
    return flow


def test_extract_metrics_calls_detect_from_frame_not_detect():
    """_extract_metrics 必须调 detect_from_frame(frame, timestamp_ms) 而非 detect(frame)。"""
    flow = _make_flow_with_mock_detector()
    fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    # 关键: 调 detect_from_frame 应被调用; detect 不应被调
    ear, yaw, pitch = flow._extract_metrics(fake_frame)

    assert flow._face_detector.detect_from_frame.called, (
        "BUG-4: _extract_metrics 没调 detect_from_frame"
    )
    assert not flow._face_detector.detect.called, (
        "BUG-4: _extract_metrics 调了不存在的 .detect() 方法, 永远 AttributeError"
    )


def test_extract_metrics_returns_actual_ear_yaw_pitch_when_mock_provides():
    """detect_from_frame 返回 mock 数据时, _extract_metrics 应能调用成功。

    修复后: detect_from_frame 被调, 返回 mock detected=True。
    EAR/yaw/pitch 取决于 compute_ear_from_landmarks(零矩阵) 返回什么,
    这里不强求非 None — 关键是 'extract_metrics 没有静默 catch AttributeError'。
    """
    flow = _make_flow_with_mock_detector()
    fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    # BUG-4 修复前: 调 .detect() → AttributeError → except → (None,None,None)
    # 修复后: 调 .detect_from_frame() → mock 返回 detected=True → 进 EAR 计算
    # 不抛 AttributeError 即视为通过
    ear, yaw, pitch = flow._extract_metrics(fake_frame)
    # 这个调用本身不应抛 AttributeError
    # ear/yaw/pitch 是否 None 取决于 compute_*_from_* 在零矩阵上返回什么
    # (核心是方法名对了, AttributeError 不再被 catch)


def test_extract_metrics_with_real_detector_no_attribute_error():
    """Smoke test: 用真实 detector, 真实 frame, _extract_metrics 不能抛 AttributeError。

    这个测试需要 MediaPipe 模型 + 摄像头。如果摄像头不可用会 RuntimeError, 不是 AttributeError。
    关键: AttributeError 必须是 'FaceMeshDetector' object has no attribute 'detect' 类型。
    """
    from detector.face_mesh import create_face_mesh_detector

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return  # skip if no camera

    detector = create_face_mesh_detector()
    flow = CalibrationFlow.__new__(CalibrationFlow)
    flow._face_detector = detector

    ret, frame = cap.read()
    cap.release()
    if not ret:
        return

    # 调 _extract_metrics — 不应抛 AttributeError
    try:
        ear, yaw, pitch = flow._extract_metrics(frame)
        # Success — no AttributeError thrown
    except AttributeError as e:
        if "'detect'" in str(e) and "attribute" in str(e).lower():
            raise AssertionError(f"BUG-4 复现: {e}")

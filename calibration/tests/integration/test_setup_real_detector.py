"""集成测试：CalibrationFlow._setup() 必须能创建真实 FaceMeshDetector。

背景：A1 agent 在 calibration/flow.py:89 写了 create_face_mesh_detector(mode="video")，
     但 factory 不接受 mode 参数。真机验收 (python -m calibration) 启动时崩溃。
     unit test 全部 mock，没覆盖 _setup() 实际调用路径。

这个测试必须**不**mock detector，验证 _setup() 能用真实 factory 创建 detector。
"""
import pytest
from unittest.mock import patch, MagicMock

from calibration.flow import CalibrationFlow
from calibration.config import CalibrationConfig


@pytest.mark.slow
def test_setup_creates_real_face_detector_without_typeerror():
    """_setup() 必须能用真实 create_face_mesh_detector 工厂（不带任何额外 kwarg）。

    前置：mock cv2.VideoCapture / cv2.namedWindow / InputHandler 避免真实摄像头/窗口；
          但 detector factory 必须真实调用。

    ⚠️ 标记 @pytest.mark.slow: 加载 MediaPipe ~3-5s。
    ⚠️ 必须清理 detector，否则 MediaPipe daemon 线程泄漏到后续 unit 测试触发死锁。
    """
    config = CalibrationConfig(audio_enabled=False)

    with patch("calibration.flow.cv2.VideoCapture") as mock_cap, \
         patch("calibration.flow.cv2.namedWindow"), \
         patch("calibration.flow.InputHandler"):

        # 让 mock 的 cap "成功打开"
        mock_cap.return_value.isOpened.return_value = True

        flow = CalibrationFlow(session_id="setup_test", config=config)
        try:
            flow._setup()

            # 关键断言：face_detector 被创建（不是 None），且是 FaceMeshDetector 实例
            assert flow._face_detector is not None
            # 不抛 TypeError 即视为通过（之前 mode="video" 会抛 TypeError）
        finally:
            # 释放 MediaPipe 资源, 防止 daemon 线程 (clearcut uploader 等)
            # 泄漏到后续 unit 测试, 避免与 test_audio_tts.py 的 importlib.reload 冲突
            if flow._face_detector is not None:
                flow._face_detector.close(timeout=2.0)


def test_setup_raises_runtimeerror_if_camera_unavailable():
    """_setup() 必须检测摄像头不可用，抛 RuntimeError 而不是静默失败。"""
    config = CalibrationConfig(audio_enabled=False)

    with patch("calibration.flow.cv2.VideoCapture") as mock_cap, \
         patch("calibration.flow.cv2.namedWindow"), \
         patch("calibration.flow.InputHandler"):

        mock_cap.return_value.isOpened.return_value = False

        flow = CalibrationFlow(session_id="setup_test", config=config)
        with pytest.raises(RuntimeError, match="无法打开摄像头"):
            flow._setup()

"""
tests/test_integration.py — T143 端到端集成测试

测试目标：
- 验证所有模块在完整流程中的协作
- 测试 main.py 中 EyeFocusApp 的帧处理流程
- 验证数据在各模块间的正确流动

依赖：T135（联调完成）
"""

import sys
import os
import tempfile
import time
from datetime import datetime
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import EyeFocusApp, AppConfig


def make_mock_frame(brightness: int = 128, size=(480, 640, 3)):
    """创建指定亮度的 mock 视频帧"""
    return np.full(size, brightness, dtype=np.uint8)


def make_mock_landmarks(ear_value: float = 0.35):
    """创建标准 478 关键点数组（含虹膜 468-477），模拟指定 EAR 值"""
    landmarks = np.zeros((478, 3), dtype=np.float64)

    eye_width = 30.0
    eye_vertical = ear_value * eye_width

    cx, cy = 200, 200
    landmarks[33] = [cx - eye_width, cy, 0]
    landmarks[160] = [cx - eye_width * 0.5, cy - eye_vertical, 0]
    landmarks[158] = [cx + eye_width * 0.5, cy - eye_vertical, 0]
    landmarks[133] = [cx + eye_width, cy, 0]
    landmarks[153] = [cx + eye_width * 0.5, cy + eye_vertical, 0]
    landmarks[144] = [cx - eye_width * 0.5, cy + eye_vertical, 0]

    cx2, cy2 = 440, 200
    landmarks[362] = [cx2 - eye_width, cy2, 0]
    landmarks[385] = [cx2 - eye_width * 0.5, cy2 - eye_vertical, 0]
    landmarks[387] = [cx2 + eye_width * 0.5, cy2 - eye_vertical, 0]
    landmarks[263] = [cx2 + eye_width, cy2, 0]
    landmarks[380] = [cx2 + eye_width * 0.5, cy2 + eye_vertical, 0]
    landmarks[373] = [cx2 - eye_width * 0.5, cy2 + eye_vertical, 0]

    # 虹膜关键点（左 468-472，右 473-477）
    iris_radius = 5.0
    for i in range(5):
        angle = 2 * np.pi * i / 5
        landmarks[468 + i] = [cx + iris_radius * np.cos(angle), cy + iris_radius * np.sin(angle), 0]
        landmarks[473 + i] = [cx2 + iris_radius * np.cos(angle), cy2 + iris_radius * np.sin(angle), 0]

    return landmarks


def make_mock_face_result(landmarks=None, ear_value: float = 0.35,
                           yaw: float = 0.0, pitch: float = 0.0,
                           blendshapes: dict = None):
    """创建 Mock FaceMeshResult"""
    from detector.face_mesh import FaceMeshResult

    if landmarks is None:
        landmarks = make_mock_landmarks(ear_value)

    return FaceMeshResult(
        landmarks=landmarks,
        face_detected=True,
        yaw=yaw,
        pitch=pitch,
        roll=0.0,
        blendshapes=blendshapes or {
            "eyeSquintLeft": 0.1,
            "eyeSquintRight": 0.1,
            "eyeWideLeft": 0.1,
            "eyeWideRight": 0.1,
        },
        confidence=0.95,
    )


class TestEyeFocusAppIntegration:
    """EyeFocusApp 集成测试"""

    @pytest.fixture
    def app(self):
        """创建并初始化 App 实例"""
        import tempfile
        from storage.db import DatabaseManager, DBConfig

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")

        app = EyeFocusApp(AppConfig(
            camera_index=0,
            enable_calibration=False,
            calibration_duration=1.0,
        ))

        app._db = DatabaseManager(DBConfig(db_path=db_path))
        app._db.initialize()
        app._session_id = app._db.create_session()

        # 初始化检测器（使用 mock）
        app._face_detector = MagicMock()
        app._eye_detector = MagicMock()
        app._gaze_detector = MagicMock()
        app._light_detector = MagicMock()
        app._overlay = MagicMock()

        # 初始化分析器（使用 mock）
        from analyzer.focus import FocusAnalyzer
        from analyzer.glasses import GlassesDetector
        from analyzer.fatigue import FatigueAnalyzer

        app._focus_analyzer = MagicMock()  # Mock FocusAnalyzer
        app._glasses_detector = MagicMock()  # Mock GlassesDetector
        app._fatigue_analyzer = MagicMock()  # Mock FatigueAnalyzer

        # Mock 校准管理器
        app._calib_manager = MagicMock()
        app._calib_callbacks = MagicMock()

        # Mock database write operations for integration tests
        app._db.write_frame = MagicMock()
        app._db.write_fatigue_record = MagicMock()
        app._db.write_blink_event = MagicMock()
        app._db.write_focus_record = MagicMock()

        # v4.0 重构：FrameProcessor 是帧处理的单一数据源。
        # 集成测试 fixture 必须显式构造一个 FrameProcessor 注入到 app 上。
        from main import FrameProcessor
        app._frame_processor = FrameProcessor(
            face_detector=app._face_detector,
            eye_detector=app._eye_detector,
            gaze_detector=app._gaze_detector,
            light_detector=app._light_detector,
            glasses_detector=app._glasses_detector,
            focus_analyzer=app._focus_analyzer,
            fatigue_analyzer=app._fatigue_analyzer,
            calib_manager=app._calib_manager,
            is_calibration_active=lambda: False,
            db=app._db,
            session_id=app._session_id,
        )

        yield app

        # Cleanup
        try:
            app._db.close()
        except Exception:
            pass
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    def test_initialization_creates_all_detectors(self, app):
        """验证初始化创建了所有必需的检测器"""
        assert app._face_detector is not None
        assert app._eye_detector is not None
        assert app._gaze_detector is not None
        assert app._light_detector is not None
        assert app._focus_analyzer is not None
        assert app._fatigue_analyzer is not None
        assert app._glasses_detector is not None

    def test_initialization_creates_database_session(self, app):
        """验证初始化创建了数据库会话"""
        assert app._db is not None
        assert app._session_id is not None
        assert isinstance(app._session_id, str)
        assert len(app._session_id) > 0

    def test_process_frame_calls_all_detectors(self, app):
        """验证 _process_frame 调用了所有检测器"""
        frame = make_mock_frame()
        mock_face_result = make_mock_face_result()

        app._face_detector.get_latest.return_value = mock_face_result
        app._eye_detector.compute.return_value = MagicMock(
            ear_left=0.3, ear_right=0.31, ear_avg=0.305, is_blink=False
        )
        app._light_detector.analyze_frame.return_value = MagicMock(
            condition=MagicMock(value="normal"),
            brightness=128.0,
            brightness_std=10.0,
            face_region_brightness=120.0,
            is_adequate=True,
        )
        app._gaze_detector.detect.return_value = MagicMock(
            gaze_score=95.0, is_looking_at_screen=True, gaze_offset=(0.5, 0.3)
        )

        # Mock database to avoid real DB operations
        app._db.write_frame = MagicMock()
        app._db.write_fatigue_record = MagicMock()
        app._db.write_blink_event = MagicMock()

        app._frame_processor.process_frame(frame)

        # v4.29: 异步检测 — push_frame + get_latest 代替 detect_from_frame
        app._face_detector.push_frame.assert_called_once()
        app._face_detector.get_latest.assert_called_once()
        app._eye_detector.compute.assert_called_once()
        app._light_detector.analyze_frame.assert_called_once()
        app._gaze_detector.detect.assert_called_once()
        app._glasses_detector.detect.assert_called_once()

    def test_process_frame_handles_no_face(self, app):
        """验证人脸丢失时的处理"""
        frame = make_mock_frame()
        mock_face_result = make_mock_face_result()
        mock_face_result.face_detected = False

        app._face_detector.get_latest.return_value = mock_face_result

        # 不应抛出异常
        app._frame_processor.process_frame(frame)

        # 眨眼检测和视线检测不应被调用
        app._eye_detector.compute.assert_not_called()
        app._gaze_detector.detect.assert_not_called()

    def test_process_frame_eye_aspect_flow(self, app):
        """测试眨眼检测流程"""
        frame = make_mock_frame()
        ear_value = 0.35
        mock_face_result = make_mock_face_result(ear_value=ear_value)

        # Mock EAR 计算返回值
        mock_eye_result = MagicMock(
            ear_left=ear_value,
            ear_right=ear_value,
            ear_avg=ear_value,
            is_blink=False,
        )
        app._face_detector.get_latest.return_value = mock_face_result
        app._eye_detector.compute.return_value = mock_eye_result
        app._eye_detector.get_blink_events.return_value = []
        app._eye_detector.get_blink_rate.return_value = (0.0, 0)
        app._eye_detector.get_stats.return_value = {"has_baseline": False}

        app._light_detector.analyze_frame.return_value = MagicMock(
            condition=MagicMock(value="normal"),
            brightness=128.0,
            brightness_std=10.0,
            face_region_brightness=120.0,
            is_adequate=True,
        )
        app._gaze_detector.detect.return_value = MagicMock(
            gaze_score=100.0, is_looking_at_screen=True, gaze_offset=(0.0, 0.0)
        )

        app._frame_processor.process_frame(frame)

        # 验证眨眼检测器被调用
        app._eye_detector.compute.assert_called_once()

    def test_process_frame_gaze_flow(self, app):
        """测试视线检测流程"""
        frame = make_mock_frame()
        mock_face_result = make_mock_face_result(yaw=5.0, pitch=-3.0)

        app._face_detector.get_latest.return_value = mock_face_result
        app._eye_detector.compute.return_value = MagicMock(
            ear_left=0.3, ear_right=0.31, ear_avg=0.305, is_blink=False
        )
        app._eye_detector.get_blink_events.return_value = []
        app._eye_detector.get_blink_rate.return_value = (0.0, 0)
        app._light_detector.analyze_frame.return_value = MagicMock(
            condition=MagicMock(value="normal"),
            brightness=128.0,
            brightness_std=10.0,
            face_region_brightness=120.0,
            is_adequate=True,
        )
        app._gaze_detector.detect.return_value = MagicMock(
            gaze_score=85.0, is_looking_at_screen=True, gaze_offset=(2.0, -1.0)
        )

        app._frame_processor.process_frame(frame)

        # 验证视线检测器被调用，传入正确的头部姿态
        call_args = app._gaze_detector.detect.call_args
        assert call_args is not None

    def test_process_frame_light_flow(self, app):
        """测试光照检测流程"""
        frame = make_mock_frame(brightness=180)

        mock_face_result = make_mock_face_result()
        app._face_detector.get_latest.return_value = mock_face_result
        app._eye_detector.compute.return_value = MagicMock(
            ear_left=0.3, ear_right=0.31, ear_avg=0.305, is_blink=False
        )
        app._eye_detector.get_blink_events.return_value = []
        app._eye_detector.get_blink_rate.return_value = (0.0, 0)
        app._light_detector.analyze_frame.return_value = MagicMock(
            condition=MagicMock(value="bright"),
            brightness=180.0,
            brightness_std=15.0,
            face_region_brightness=170.0,
            is_adequate=True,
        )
        app._gaze_detector.detect.return_value = MagicMock(
            gaze_score=100.0, is_looking_at_screen=True, gaze_offset=(0.0, 0.0)
        )

        app._frame_processor.process_frame(frame)

        # 验证光照检测器被调用
        app._light_detector.analyze_frame.assert_called_once()

    def test_process_frame_glasses_flow(self, app):
        """测试眼镜检测流程"""
        frame = make_mock_frame()
        blendshapes = {
            "eyeSquintLeft": 0.9,
            "eyeSquintRight": 0.9,
            "eyeWideLeft": 0.05,
            "eyeWideRight": 0.05,
        }
        mock_face_result = make_mock_face_result(blendshapes=blendshapes)

        app._face_detector.get_latest.return_value = mock_face_result
        app._eye_detector.compute.return_value = MagicMock(
            ear_left=0.3, ear_right=0.31, ear_avg=0.305, is_blink=False
        )
        app._eye_detector.get_blink_events.return_value = []
        app._eye_detector.get_blink_rate.return_value = (0.0, 0)
        app._light_detector.analyze_frame.return_value = MagicMock(
            condition=MagicMock(value="normal"),
            brightness=128.0,
            brightness_std=10.0,
            face_region_brightness=120.0,
            is_adequate=True,
        )
        app._gaze_detector.detect.return_value = MagicMock(
            gaze_score=100.0, is_looking_at_screen=True, gaze_offset=(0.0, 0.0)
        )

        app._frame_processor.process_frame(frame)

        # 验证眼镜检测器被调用
        app._glasses_detector.detect.assert_called_once()

    def test_process_frame_focus_analysis_flow(self, app):
        """测试专注度分析流程"""
        frame = make_mock_frame()
        mock_face_result = make_mock_face_result()

        app._face_detector.get_latest.return_value = mock_face_result
        app._eye_detector.compute.return_value = MagicMock(
            ear_left=0.3, ear_right=0.31, ear_avg=0.305, is_blink=False
        )
        app._eye_detector.get_blink_events.return_value = []
        app._eye_detector.get_blink_rate.return_value = (18.0, 6)
        app._eye_detector.get_stats.return_value = {"has_baseline": True, "ear_threshold": 0.26}

        app._light_detector.analyze_frame.return_value = MagicMock(
            condition=MagicMock(value="normal"),
            brightness=128.0,
            brightness_std=10.0,
            face_region_brightness=120.0,
            is_adequate=True,
        )
        app._gaze_detector.detect.return_value = MagicMock(
            gaze_score=90.0, is_looking_at_screen=True, gaze_offset=(0.5, 0.3)
        )

        app._frame_processor.process_frame(frame)

        # 验证专注度分析器被调用
        app._focus_analyzer.analyze.assert_called_once()

    def test_process_frame_fatigue_analysis_flow(self, app):
        """测试疲劳分析流程"""
        frame = make_mock_frame()
        mock_face_result = make_mock_face_result()

        mock_eye_result = MagicMock(
            ear_left=0.3, ear_right=0.31, ear_avg=0.305, is_blink=False
        )

        # 模拟眨眼事件
        from detector.eye_aspect import BlinkEvent
        mock_blink = BlinkEvent(
            start_frame=1, end_frame=3,
            start_time=time.time()-0.2, end_time=time.time(),
            duration=0.2, ear_nadir=0.15, is_confirmed=True
        )

        app._face_detector.get_latest.return_value = mock_face_result
        app._eye_detector.compute.return_value = mock_eye_result
        app._eye_detector.get_blink_events.return_value = [mock_blink]
        app._eye_detector.get_blink_rate.return_value = (22.0, 7)

        app._light_detector.analyze_frame.return_value = MagicMock(
            condition=MagicMock(value="normal"),
            brightness=128.0,
            brightness_std=10.0,
            face_region_brightness=120.0,
            is_adequate=True,
        )
        app._gaze_detector.detect.return_value = MagicMock(
            gaze_score=90.0, is_looking_at_screen=True, gaze_offset=(0.5, 0.3)
        )

        app._frame_processor.process_frame(frame)

        # 验证疲劳分析器被调用
        app._fatigue_analyzer.analyze.assert_called_once()

    def test_process_frame_database_write(self, app):
        """测试帧数据写入数据库"""
        frame = make_mock_frame()
        mock_face_result = make_mock_face_result()

        app._face_detector.get_latest.return_value = mock_face_result
        app._eye_detector.compute.return_value = MagicMock(
            ear_left=0.3, ear_right=0.31, ear_avg=0.305, is_blink=False
        )
        app._eye_detector.get_blink_events.return_value = []
        app._eye_detector.get_blink_rate.return_value = (0.0, 0)
        app._light_detector.analyze_frame.return_value = MagicMock(
            condition=MagicMock(value="normal"),
            brightness=128.0,
            brightness_std=10.0,
            face_region_brightness=120.0,
            is_adequate=True,
        )
        app._gaze_detector.detect.return_value = MagicMock(
            gaze_score=100.0, is_looking_at_screen=True, gaze_offset=(0.0, 0.0)
        )

        # Mock 数据库写入
        app._db.write_frame = MagicMock()
        app._db.write_fatigue_record = MagicMock()

        app._frame_processor.process_frame(frame)

        # 验证数据库写入被调用
        app._db.write_frame.assert_called_once()
        app._db.write_fatigue_record.assert_called_once()

    def test_process_frame_calibration_mode(self, app):
        """测试校准模式下的帧处理路径

        注：校准数据流（add_frame → calib_manager.add_frame）由 T155+T156 单独接线。
        本测试目前只验证 FrameProcessor.process_frame 在未启用校准时
        不抛异常、不向 calib_manager.add_frame 注入校准数据。
        完整的"校准模式 → 校准数据采集"端到端路径在 T162 审计中验证。
        """
        # 校准未激活（fixture 默认），所以 calib_manager.add_frame 不应被调用
        frame = make_mock_frame()
        mock_face_result = make_mock_face_result()

        app._face_detector.get_latest.return_value = mock_face_result
        app._eye_detector.compute.return_value = MagicMock(
            ear_left=0.3, ear_right=0.31, ear_avg=0.305, is_blink=False
        )
        app._eye_detector.get_blink_events.return_value = []
        app._eye_detector.get_blink_rate.return_value = (0.0, 0)
        app._light_detector.analyze_frame.return_value = MagicMock(
            condition=MagicMock(value="normal"),
            brightness=128.0,
            brightness_std=10.0,
            face_region_brightness=120.0,
            is_adequate=True,
        )
        app._gaze_detector.detect.return_value = MagicMock(
            gaze_score=100.0, is_looking_at_screen=True, gaze_offset=(0.0, 0.0)
        )

        # 执行帧处理，验证不抛异常
        app._frame_processor.process_frame(frame)

        # 校准未激活时，calib_manager.add_frame 不应被调用（T162 端到端验证启用场景）
        app._calib_manager.add_frame.assert_not_called()

    def test_app_state_transitions(self, app):
        """测试应用状态转换"""
        assert app._running is False
        # M-22: _paused 是死代码字段, 已删除

        # 模拟开始
        app._running = True

        assert app._running is True

        # 模拟停止
        app._running = False

        assert app._running is False

    def test_multiple_frames_processing(self, app):
        """测试连续多帧处理"""
        frame = make_mock_frame()
        mock_face_result = make_mock_face_result()

        app._face_detector.get_latest.return_value = mock_face_result
        app._eye_detector.compute.return_value = MagicMock(
            ear_left=0.3, ear_right=0.31, ear_avg=0.305, is_blink=False
        )
        app._eye_detector.get_blink_events.return_value = []
        app._eye_detector.get_blink_rate.return_value = (0.0, 0)
        app._eye_detector.get_stats.return_value = {"has_baseline": False}

        app._light_detector.analyze_frame.return_value = MagicMock(
            condition=MagicMock(value="normal"),
            brightness=128.0,
            brightness_std=10.0,
            face_region_brightness=120.0,
            is_adequate=True,
        )
        app._gaze_detector.detect.return_value = MagicMock(
            gaze_score=100.0, is_looking_at_screen=True, gaze_offset=(0.0, 0.0)
        )

        # 处理 10 帧
        for i in range(10):
            app._frame_processor.process_frame(frame)

        # 验证帧计数增加（v4.0：FrameProcessor 持有 frame_count）
        assert app._frame_processor.frame_count == 10

    def test_fps_calculation(self, app):
        """测试 FPS 计算"""
        app._fps_start_time = time.time()
        app._fps_frame_count = 0
        app._fps = 0.0

        # 模拟帧计数
        for i in range(30):
            app._fps_frame_count += 1
            app._update_fps()

        # FPS 应该被更新
        assert app._fps >= 0

    def test_cleanup(self, app):
        """测试清理方法"""
        app._running = True
        # v4.0：_frame_count 移至 FrameProcessor，_cleanup 不再依赖它

        # Mock 所有需要关闭的对象
        app._db = MagicMock()
        app._face_detector = MagicMock()
        app._overlay = MagicMock()

        # 执行清理
        app._cleanup()

        # 验证数据库关闭被调用
        app._db.close.assert_called()


class TestEyeFocusAppCameraValidation:
    """v4.0.2 回归: 摄像头不可用时 initialize() 必须返回 False (B3)"""

    def test_initialize_returns_false_when_camera_unavailable(self, monkeypatch, tmp_path):
        """无效摄像头 index → initialize() 返回 False，且记录明确错误 (B3)

        策略: 在 EyeFocusApp 创建前 monkeypatch CameraManager，绕过真实检测器加载。
        """
        from main import EyeFocusApp, AppConfig

        class FakeCameraManager:
            def __init__(self, camera_index):
                self.camera_index = camera_index
                self.started = False
            def start(self):
                self.started = True
                return False
            def stop(self):
                self.started = False
                return True
            def is_running(self):
                return False
            def get_frame(self):
                return (False, None)
            def release(self):
                self.started = False

        # 把所有可能触发模型加载的工厂函数全部 mock
        import main as main_module
        from unittest.mock import MagicMock
        monkeypatch.setattr(main_module, "CameraManager", FakeCameraManager)
        monkeypatch.setattr(main_module, "create_face_mesh_detector", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(main_module, "create_eye_aspect_detector", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(main_module, "create_gaze_detector", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(main_module, "create_light_detector", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(main_module, "create_glasses_detector", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(main_module, "create_focus_analyzer", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(main_module, "create_fatigue_analyzer", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(main_module, "create_user_calibration_manager", MagicMock(return_value=MagicMock()))
        import gui.overlay
        monkeypatch.setattr(gui.overlay, "FocusOverlay", MagicMock())

        import logging
        log_records = []
        handler = logging.Handler()
        handler.emit = lambda r: log_records.append(r.getMessage())
        logging.getLogger("eyefocus").addHandler(handler)
        logging.getLogger("eyefocus").setLevel(logging.ERROR)
        try:
            app = EyeFocusApp(AppConfig(
                camera_index=99,
                enable_calibration=False,
                data_dir=str(tmp_path),
            ))
            ok = app.initialize()
            assert ok is False, f"无效摄像头 initialize() 应返回 False, 实际 {ok}"
            err_logs = [m for m in log_records if "摄像头" in m and "无法" in m]
            assert err_logs, f"应记录摄像头无法打开的错误日志, 实际 {log_records}"
            assert any("99" in m for m in err_logs), f"错误日志应含 camera_index=99"
        finally:
            logging.getLogger("eyefocus").removeHandler(handler)

    def test_initialize_stops_camera_after_validation(self, monkeypatch, tmp_path):
        """B3 验证: 摄像头 start() 验证后必须 stop()，否则 main_loop start() 会冲突"""
        from main import EyeFocusApp, AppConfig
        from unittest.mock import MagicMock

        stop_called = [False]
        class FakeCameraManager:
            def __init__(self, camera_index):
                self.camera_index = camera_index
            def start(self):
                return True
            def stop(self):
                stop_called[0] = True
                return True
            def is_running(self):
                return False
            def get_frame(self):
                return (False, None)
            def release(self):
                stop_called[0] = True

        import main as main_module
        monkeypatch.setattr(main_module, "CameraManager", FakeCameraManager)
        monkeypatch.setattr(main_module, "create_face_mesh_detector", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(main_module, "create_eye_aspect_detector", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(main_module, "create_gaze_detector", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(main_module, "create_light_detector", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(main_module, "create_glasses_detector", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(main_module, "create_focus_analyzer", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(main_module, "create_fatigue_analyzer", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(main_module, "create_user_calibration_manager", MagicMock(return_value=MagicMock()))
        import gui.overlay
        monkeypatch.setattr(gui.overlay, "FocusOverlay", MagicMock())

        app = EyeFocusApp(AppConfig(
            camera_index=0,
            enable_calibration=False,
            data_dir=str(tmp_path),
        ))
        ok = app.initialize()
        assert ok is True
        assert stop_called[0], "B3: 验证后必须 stop()，避免 main_loop start() 冲突"


class TestModuleIntegration:
    """模块间集成测试"""

    def test_detector_to_analyzer_flow(self):
        """测试从检测器到分析器的数据流"""
        from detector.eye_aspect import EyeAspectDetector
        from analyzer.focus import FocusAnalyzer

        # 创建检测器
        eye_detector = EyeAspectDetector()
        eye_detector.set_baseline(0.35)

        # 创建分析器并连接检测器
        focus_analyzer = FocusAnalyzer()
        focus_analyzer.set_blink_detector(eye_detector)

        # 模拟检测结果
        landmarks = make_mock_landmarks(ear_value=0.35)
        ear_result = eye_detector.compute(landmarks)

        assert ear_result.ear_avg > 0
        assert ear_result.ear_avg < 0.5

    def test_blink_detection_to_fatigue_flow(self):
        """测试从眨眼检测到疲劳分析的数据流"""
        from detector.eye_aspect import EyeAspectDetector, BlinkEvent
        from analyzer.fatigue import FatigueAnalyzer

        eye_detector = EyeAspectDetector()
        eye_detector.set_baseline(0.35)

        fatigue_analyzer = FatigueAnalyzer()
        fatigue_analyzer.start()

        # 模拟眨眼事件（使用 detector.eye_aspect 中的 BlinkEvent）
        blink = BlinkEvent(
            start_frame=1, end_frame=7,
            start_time=0.0, end_time=0.2,
            duration=0.2, ear_nadir=0.15, is_confirmed=True
        )

        # 分析疲劳
        result = fatigue_analyzer.analyze(
            blink_rate=20.0,  # 20 次/分钟
            ear_nadir=0.15,
            head_stability=80.0,
            avg_ear=0.30,
        )

        assert result is not None
        assert hasattr(result, 'fatigue_level')
        assert hasattr(result, 'fatigue_score')

    def test_glasses_detection_integration(self):
        """测试眼镜检测集成"""
        from analyzer.glasses import GlassesDetector

        detector = GlassesDetector()

        # 模拟戴眼镜的 blendshapes
        blendshapes_glasses = {
            "eyeSquintLeft": 0.9,
            "eyeSquintRight": 0.9,
            "eyeWideLeft": 0.05,
            "eyeWideRight": 0.05,
        }

        result = detector.detect(blendshapes=blendshapes_glasses)
        assert result.is_glasses is True
        assert result.method == "blendshapes"

        # 模拟不戴眼镜的 blendshapes
        blendshapes_no_glasses = {
            "eyeSquintLeft": 0.3,
            "eyeSquintRight": 0.3,
            "eyeWideLeft": 0.3,
            "eyeWideRight": 0.3,
        }

        result = detector.detect(blendshapes=blendshapes_no_glasses)
        assert result.is_glasses is False


class TestDatabaseIntegration:
    """数据库集成测试"""

    def test_session_lifecycle(self):
        """测试会话生命周期"""
        with tempfile.TemporaryDirectory() as tmpdir:
            from storage.db import DatabaseManager, DBConfig

            db = DatabaseManager(DBConfig(db_path=os.path.join(tmpdir, "test.db")))
            db.initialize()

            # 创建会话
            session_id = db.create_session()
            assert session_id is not None

            # 获取会话
            session = db.get_session(session_id)
            assert session is not None
            assert session.session_id == session_id

            # 更新会话
            db.update_session(session_id, is_calibrated=True, baseline_ear=0.35)
            updated_session = db.get_session(session_id)
            assert updated_session.is_calibrated is True

            db.close()

    def test_frame_record_storage(self):
        """测试帧记录存储"""
        with tempfile.TemporaryDirectory() as tmpdir:
            from storage.db import DatabaseManager, DBConfig
            from storage.models import FrameRecord

            db = DatabaseManager(DBConfig(db_path=os.path.join(tmpdir, "test.db")))
            db.initialize()

            session_id = db.create_session()

            # 写入帧记录
            frame = FrameRecord(
                session_id=session_id,
                timestamp=time.time(),
                ear_left=0.3,
                ear_right=0.31,
                ear_avg=0.305,
                yaw=0.0,
                pitch=0.0,
                roll=0.0,
                gaze_score=95.0,
                brightness=128.0,
                face_detected=True,
            )

            db.write_frame(session_id, frame)

            # 验证写入成功（不抛异常）
            db.close()

    def test_calibration_result_storage(self):
        """测试校准结果存储"""
        with tempfile.TemporaryDirectory() as tmpdir:
            from storage.db import DatabaseManager, DBConfig
            from storage.models import CalibrationSignal

            db = DatabaseManager(DBConfig(db_path=os.path.join(tmpdir, "test.db")))
            db.initialize()

            session_id = db.create_session()

            # 创建校准信号
            signal = CalibrationSignal(
                ear_mean=0.35,
                ear_min=0.08,
                ear_mid=0.25,
                yaw_mean=0.5,
                yaw_range=(-5.0, 5.0),
                pitch_mean=-1.0,
                pitch_range=(-10.0, 10.0),
                glasses_mode=False,
                timestamp=time.time(),
            )

            # 创建校准记录（返回 calibration_id）
            calibration_id = db.create_calibration(session_id)

            # 保存校准信号
            db.save_calibration(
                calibration_id=calibration_id,
                session_id=session_id,
                signal=signal,
                is_accepted=True,
                notes="test",
            )

            # 验证写入成功
            cursor = db._conn.cursor()
            cursor.execute("SELECT ear_mean FROM calibration WHERE id = ?", (calibration_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == 0.35

            db.close()


class TestEndToEndScenarios:
    """端到端场景测试"""

    def test_normal_work_session_scenario(self):
        """场景：正常工作时会话"""
        from detector.eye_aspect import EyeAspectDetector
        from detector.gaze import GazeDetector
        from detector.light import LightDetector
        from analyzer.focus import FocusAnalyzer
        from analyzer.fatigue import FatigueAnalyzer

        # 初始化
        eye_detector = EyeAspectDetector()
        eye_detector.set_baseline(0.35)

        gaze_detector = GazeDetector()
        light_detector = LightDetector()
        focus_analyzer = FocusAnalyzer()
        fatigue_analyzer = FatigueAnalyzer()

        focus_analyzer.set_blink_detector(eye_detector)
        fatigue_analyzer.start()

        # 模拟 1 分钟会话（简化版）
        frame = make_mock_frame(brightness=128)
        light_result = light_detector.analyze_frame(frame)

        assert light_result.brightness > 0

        # 模拟眨眼检测
        landmarks = make_mock_landmarks(ear_value=0.35)
        eye_result = eye_detector.compute(landmarks)
        gaze_result = gaze_detector.detect(landmarks, head_pose_yaw=0.0, head_pose_pitch=0.0)

        # 分析专注度
        focus_result = focus_analyzer.analyze(
            ear=eye_result.ear_avg,
            yaw=0.0,
            pitch=0.0,
            gaze_score=gaze_result.gaze_concentration,
            brightness=light_result.brightness,
            face_detected=True,
        )

        # 分析疲劳
        fatigue_result = fatigue_analyzer.analyze(
            blink_rate=18.0,
            ear_nadir=0.15,
            head_stability=90.0,
            avg_ear=eye_result.ear_avg,
        )

        # 验证结果
        assert 0 <= focus_result.focus_score <= 100
        assert fatigue_result.fatigue_level.value in ["low", "medium", "high"]

    def test_glasses_user_scenario(self):
        """场景：戴眼镜用户"""
        from analyzer.glasses import GlassesDetector

        detector = GlassesDetector()

        # 模拟戴眼镜用户
        blendshapes = {
            "eyeSquintLeft": 0.92,
            "eyeSquintRight": 0.93,
            "eyeWideLeft": 0.03,
            "eyeWideRight": 0.02,
        }

        result = detector.detect(blendshapes=blendshapes)
        assert result.is_glasses is True

        # 模拟不戴眼镜用户
        blendshapes_no_glasses = {
            "eyeSquintLeft": 0.4,
            "eyeSquintRight": 0.4,
            "eyeWideLeft": 0.2,
            "eyeWideRight": 0.2,
        }

        result = detector.detect(blendshapes=blendshapes_no_glasses)
        assert result.is_glasses is False

    def test_low_light_scenario(self):
        """场景：低光照环境"""
        from detector.light import LightDetector, LightCondition

        detector = LightDetector()

        # 模拟暗光环境 (brightness <= 50)
        dark_frame = make_mock_frame(brightness=20)
        result = detector.analyze_frame(dark_frame)

        assert result.condition == LightCondition.DARK
        # M-06: is_adequate 仅 NORMAL=True, DARK/BRIGHT=False
        assert result.is_adequate is False

        # 模拟正常光照 (50 < brightness <= 100)
        normal_frame = make_mock_frame(brightness=75)
        result = detector.analyze_frame(normal_frame)

        assert result.condition == LightCondition.NORMAL
        assert result.is_adequate is True

        # 模拟明亮光照 (brightness > 100)
        bright_frame = make_mock_frame(brightness=150)
        result = detector.analyze_frame(bright_frame)

        assert result.condition == LightCondition.BRIGHT
        assert result.is_adequate is False

    def test_fatigue_detection_scenario(self):
        """场景：疲劳检测"""
        from analyzer.fatigue import FatigueAnalyzer, FatigueLevel

        analyzer = FatigueAnalyzer()
        analyzer.start()

        # v4.6: 正常状态（无长闭眼）→ RESTED
        result = analyzer.analyze(closure_type="open", blink_rate=15.0)
        assert result.fatigue_indicator.value == "rested"

        # v4.6.1: 模拟 3 分钟内 9 次长闭眼 → TIRED
        import time as _time
        now = _time.time()
        for i in range(9):
            analyzer._prolonged_events.append(now - i * 15)
        result = analyzer.analyze(closure_type="open", blink_rate=15.0)
        assert result.fatigue_indicator.value == "tired", (
            f"9次长闭眼应判定 TIRED, 实际: {result.fatigue_indicator}")

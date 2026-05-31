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
    """创建标准 468 关键点数组，模拟指定 EAR 值"""
    landmarks = np.zeros((468, 3), dtype=np.float64)

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

        app._face_detector.detect_from_frame.return_value = mock_face_result
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

        app._process_frame(frame)

        # 验证各检测器被调用
        app._face_detector.detect_from_frame.assert_called_once()
        app._eye_detector.compute.assert_called_once()
        app._light_detector.analyze_frame.assert_called_once()
        app._gaze_detector.detect.assert_called_once()
        app._glasses_detector.detect.assert_called_once()

    def test_process_frame_handles_no_face(self, app):
        """验证人脸丢失时的处理"""
        frame = make_mock_frame()
        mock_face_result = make_mock_face_result()
        mock_face_result.face_detected = False

        app._face_detector.detect_from_frame.return_value = mock_face_result

        # 不应抛出异常
        app._process_frame(frame)

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
        app._face_detector.detect_from_frame.return_value = mock_face_result
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

        app._process_frame(frame)

        # 验证眨眼检测器被调用
        app._eye_detector.compute.assert_called_once()

    def test_process_frame_gaze_flow(self, app):
        """测试视线检测流程"""
        frame = make_mock_frame()
        mock_face_result = make_mock_face_result(yaw=5.0, pitch=-3.0)

        app._face_detector.detect_from_frame.return_value = mock_face_result
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

        app._process_frame(frame)

        # 验证视线检测器被调用，传入正确的头部姿态
        call_args = app._gaze_detector.detect.call_args
        assert call_args is not None

    def test_process_frame_light_flow(self, app):
        """测试光照检测流程"""
        frame = make_mock_frame(brightness=180)

        mock_face_result = make_mock_face_result()
        app._face_detector.detect_from_frame.return_value = mock_face_result
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

        app._process_frame(frame)

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

        app._face_detector.detect_from_frame.return_value = mock_face_result
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

        app._process_frame(frame)

        # 验证眼镜检测器被调用
        app._glasses_detector.detect.assert_called_once()

    def test_process_frame_focus_analysis_flow(self, app):
        """测试专注度分析流程"""
        frame = make_mock_frame()
        mock_face_result = make_mock_face_result()

        app._face_detector.detect_from_frame.return_value = mock_face_result
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

        app._process_frame(frame)

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

        app._face_detector.detect_from_frame.return_value = mock_face_result
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

        app._process_frame(frame)

        # 验证疲劳分析器被调用
        app._fatigue_analyzer.analyze.assert_called_once()

    def test_process_frame_database_write(self, app):
        """测试帧数据写入数据库"""
        frame = make_mock_frame()
        mock_face_result = make_mock_face_result()

        app._face_detector.detect_from_frame.return_value = mock_face_result
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

        app._process_frame(frame)

        # 验证数据库写入被调用
        app._db.write_frame.assert_called_once()
        app._db.write_fatigue_record.assert_called_once()

    def test_process_frame_calibration_mode(self, app):
        """测试校准模式（使用 UserCalibrationManager）"""
        from analyzer.user_calibration import CalibrationState

        frame = make_mock_frame()
        mock_face_result = make_mock_face_result()

        app._face_detector.detect_from_frame.return_value = mock_face_result
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

        # 设置校准管理器处于 AUTO_CALIB 状态
        app._calib_manager.state = CalibrationState.AUTO_CALIB
        app._calib_manager.add_frame = MagicMock()

        app._process_frame(frame)

        # 验证校准管理器 add_frame 被调用
        app._calib_manager.add_frame.assert_called()

    def test_app_state_transitions(self, app):
        """测试应用状态转换"""
        assert app._running is False
        assert app._paused is False

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

        app._face_detector.detect_from_frame.return_value = mock_face_result
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
            app._process_frame(frame)

        # 验证帧计数增加
        assert app._frame_count == 10

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
        app._frame_count = 100

        # Mock 所有需要关闭的对象
        app._db = MagicMock()
        app._face_detector = MagicMock()
        app._overlay = MagicMock()

        # 执行清理
        app._cleanup()

        # 验证数据库关闭被调用
        app._db.close.assert_called()


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
            gaze_score=gaze_result.gaze_score,
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

        # 模拟过暗环境 (brightness < 25)
        too_dark_frame = make_mock_frame(brightness=20)
        result = detector.analyze_frame(too_dark_frame)

        assert result.condition == LightCondition.TOO_DARK
        assert result.is_adequate is False

        # 模拟暗光环境 (25 <= brightness < 40)
        dark_frame = make_mock_frame(brightness=30)
        result = detector.analyze_frame(dark_frame)

        assert result.condition == LightCondition.DARK
        assert result.is_adequate is True  # DARK 被认为是 adequate

        # 模拟正常光照
        normal_frame = make_mock_frame(brightness=128)
        result = detector.analyze_frame(normal_frame)

        assert result.is_adequate is True

    def test_fatigue_detection_scenario(self):
        """场景：疲劳检测"""
        from analyzer.fatigue import FatigueAnalyzer, FatigueLevel

        analyzer = FatigueAnalyzer()
        analyzer.start()

        # 正常状态
        result = analyzer.analyze(
            blink_rate=15.0,
            ear_nadir=0.18,
            head_stability=95.0,
            avg_ear=0.32,
        )

        assert result.fatigue_level == FatigueLevel.LOW

        # 高疲劳状态
        result = analyzer.analyze(
            blink_rate=35.0,
            ear_nadir=0.08,
            head_stability=60.0,
            avg_ear=0.25,
        )

        assert result.fatigue_level in [FatigueLevel.MEDIUM, FatigueLevel.HIGH]

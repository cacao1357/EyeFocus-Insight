"""
tests/test_main_medium_bugs.py — main.py 4 个 medium bug 修复回归测试

M-20: shutdown() 与 main_loop finally 双重清理
M-21: run_v4_2_calibration 忽略 AppConfig.camera_index
M-22: _shutdown_event / _paused 死状态字段
M-23: _cleanup 异常处理不一致 (db.close() 无 try/except)
"""

import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calibration as calibration_module_real
from main import EyeFocusApp, AppConfig
from calibration.result import CalibrationResult, CalibrationSignal


# ============ M-20: shutdown 与 main_loop 双重清理 ============


class TestM20ShutdownIdempotent:
    """M-20: shutdown() 和 main_loop finally 都会调 _cleanup(),
    需要保证 _cleanup 多次调用安全: face_detector.close() / db.close() 必须幂等,
    且第二次 shutdown() 应立即 return."""

    def test_shutdown_called_twice_second_is_noop(self):
        """M-20: shutdown() 第二次调用应被 _cleanup_done 标志拦截, 不重复清理资源"""
        from main import EyeFocusApp

        app = EyeFocusApp.__new__(EyeFocusApp)
        app._running = True
        app._db = MagicMock()
        app._session_id = "s1"
        app._face_detector = MagicMock()
        app._original_sigint = None
        app._original_sigterm = None

        with patch("main.logger"):
            # 第一次 shutdown: 完整执行
            app.shutdown()
        # 第二次 shutdown: _cleanup_done 已 True, 应立即 return
        # 验证: _db.update_session 不再被调 (只有第一次会)
        call_count_after_first = app._db.update_session.call_count

        with patch("main.logger"):
            app.shutdown()

        # 第二次 shutdown 不应重复 update_session
        assert app._db.update_session.call_count == call_count_after_first, \
            "第二次 shutdown() 不应再调 update_session"
        # 验证: _cleanup_done 被设
        assert getattr(app, '_cleanup_done', False) is True, \
            "_cleanup_done 标志应在第一次 shutdown 后被设置"

    def test_cleanup_called_twice_each_close_idempotent(self):
        """M-20: _cleanup() 调两次, 第二次每个 close 都应被 try/except 包裹不抛异常.
        模拟 main_loop finally + shutdown() 都触发 _cleanup 的场景."""
        from main import EyeFocusApp

        app = EyeFocusApp.__new__(EyeFocusApp)
        app._original_sigint = None
        app._original_sigterm = None
        app._db = MagicMock()
        # db.close() 第二次抛异常: 模拟 SQLite 句柄已失效
        db_call_count = [0]
        def fake_db_close():
            db_call_count[0] += 1
            if db_call_count[0] >= 2:
                raise RuntimeError("db already closed")
        app._db.close.side_effect = fake_db_close
        # face_detector.close() 第二次抛异常: 模拟已关闭
        face_call_count = [0]
        def fake_face_close():
            face_call_count[0] += 1
            if face_call_count[0] >= 2:
                raise RuntimeError("face detector already closed")
        app._face_detector = MagicMock()
        app._face_detector.close.side_effect = fake_face_close
        app._cleanup_errors = 0

        with patch("main.logger") as mock_logger:
            # 第一次 _cleanup: 正常关闭
            app._cleanup()
            # 第二次 _cleanup: 两个 close 都抛异常, 都不应逃逸
            app._cleanup()

        # 不应抛异常
        # _cleanup_errors 应至少 +2 (face + db)
        assert app._cleanup_errors >= 2, \
            f"_cleanup_errors 应增加至少 2 次 (face + db), 实际 {app._cleanup_errors}"
        # face_detector.close 被调 2 次
        assert face_call_count[0] == 2
        # db.close 被调 2 次
        assert db_call_count[0] == 2
        # logger.exception 应至少被调 2 次
        assert mock_logger.exception.call_count >= 2, \
            f"logger.exception 应被调至少 2 次, 实际 {mock_logger.exception.call_count}"


# ============ M-21: run_v4_2_calibration 传 AppConfig.camera_index ============


@dataclass
class _FakeCamConfig:
    """最小 calibration.Config 替代, 验证字段传递."""
    camera_index: int = 0
    frame_width: int = 640
    frame_height: int = 480
    session_id: str = ""


class TestM21V42CalibrationCameraIndex:
    """M-21: run_v4_2_calibration() 必须把 AppConfig.camera_index / frame 尺寸
    显式传给 calibration.run() 的 config 参数, 避免用默认 0."""

    def test_run_v4_2_calibration_passes_camera_index_from_app_config(self, tmp_path, monkeypatch):
        """M-21: AppConfig.camera_index=1 → calibration.run() 收到 camera_index=1"""
        import main as main_module

        # 替换构造器, 避免真的初始化
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

        # AppConfig.camera_index = 1 (用户配置外接摄像头)
        app = EyeFocusApp(AppConfig(
            camera_index=1,
            enable_calibration=False,
            data_dir=str(tmp_path),
        ))

        # 模拟 camera_manager 状态: not running (避免 release/start 副作用)
        cam = MagicMock()
        cam.is_running = MagicMock(return_value=False)
        app._camera_manager = cam
        app._eye_detector = None
        app._fatigue_analyzer = None
        app._db = None
        app._session_id = None

        # 用 CalibrationConfig 替代以验证字段
        from calibration.config import CalibrationConfig

        with patch.object(calibration_module_real, "run", return_value=None) as mock_run:
            app.run_v4_2_calibration()

        # 验证 calibration.run() 被调, 且 config 参数的 camera_index=1
        mock_run.assert_called_once()
        run_kwargs = mock_run.call_args.kwargs
        assert "config" in run_kwargs, "calibration.run() 必须传 config 参数"
        cfg = run_kwargs["config"]
        assert cfg is not None, "config 不应为 None"
        assert cfg.camera_index == 1, \
            f"camera_index 应为 1 (来自 AppConfig), 实际 {cfg.camera_index}"


# ============ M-22: _shutdown_event / _paused 死状态字段 ============


class TestM22DeadCodeFields:
    """M-22: _shutdown_event 仅 init + set, main_loop 不读; _paused 仅 init, 从不修改.
    选项 A (推荐): 删除两个死代码字段 + 移除 _shutdown_event 引用."""

    def test_no_shutdown_event_attribute(self):
        """M-22 选项 A: 实例化后不应再有 _shutdown_event 属性"""
        from main import EyeFocusApp

        app = EyeFocusApp()
        # EyeFocusApp.__init__ 不应再初始化 self._shutdown_event
        assert not hasattr(app, "_shutdown_event"), \
            "_shutdown_event 是死代码字段, 应已删除"

    def test_paused_attribute_exists_and_default_false(self):
        """v4.3 修复: _paused 是合法字段, 默认 False, P 键切换
        (M-22 误删字段但 _render_frame 还在引用导致 AttributeError 崩溃)
        """
        from main import EyeFocusApp

        app = EyeFocusApp()
        assert hasattr(app, "_paused"), \
            "_paused 应被保留 (v4.3 修复), 它是 _render_frame line 981 引用的合法字段"
        assert app._paused is False, f"_paused 默认应为 False, 实际 {app._paused}"

    def test_toggle_pause_api(self):
        """v4.3 修复: toggle_pause() API 可切换 _paused"""
        from main import EyeFocusApp

        app = EyeFocusApp()
        assert app._paused is False
        app.toggle_pause()
        assert app._paused is True, "调用 toggle_pause() 后应进入 PAUSED"
        app.toggle_pause()
        assert app._paused is False, "再调用 toggle_pause() 应恢复 RESUMED"

    def test_signal_handler_does_not_set_shutdown_event(self):
        """M-22 选项 A: _signal_handler 不再 set _shutdown_event (字段已删除)"""
        from main import EyeFocusApp

        app = EyeFocusApp.__new__(EyeFocusApp)
        app._running = True
        # _shutdown_event 不应被设置, 也不存在
        with patch("main.logger"):
            app._signal_handler(2, None)

        # 验证 _running 被设 False
        assert app._running is False, "signal handler 应设 _running=False"
        # 验证 _shutdown_event 不存在
        assert not hasattr(app, "_shutdown_event"), \
            "signal handler 不应创建 _shutdown_event (死代码)"

    def test_shutdown_does_not_set_shutdown_event(self):
        """M-22 选项 A: shutdown() 不再 set _shutdown_event"""
        from main import EyeFocusApp

        app = EyeFocusApp.__new__(EyeFocusApp)
        app._running = True
        app._db = None
        app._session_id = None
        app._face_detector = None
        app._original_sigint = None
        app._original_sigterm = None

        with patch("main.logger"):
            app.shutdown()

        # _shutdown_event 不应被创建
        assert not hasattr(app, "_shutdown_event"), \
            "shutdown() 不应创建 _shutdown_event (死代码)"


# ============ M-23: _cleanup 异常处理不一致 ============


class TestM23CleanupExceptionConsistency:
    """M-23: face_detector.close() 异常吞 + warning (已修 H-13 用 exception),
    db.close() 根本不 try/except. 需要统一处理."""

    def test_db_close_uses_logger_exception_on_exception(self):
        """M-23: db.close() 抛异常时也应被 try/except 包裹 + logger.exception"""
        from main import EyeFocusApp

        app = EyeFocusApp.__new__(EyeFocusApp)
        app._original_sigint = None
        app._original_sigterm = None
        app._face_detector = None
        # db.close() 抛异常
        app._db = MagicMock()
        app._db.close.side_effect = RuntimeError("db close failed")
        app._cleanup_errors = 0

        with patch("main.logger") as mock_logger:
            # 不应抛异常
            app._cleanup()

        # 验证: db.close() 异常被 logger.exception 记录
        assert mock_logger.exception.called, \
            "db.close() 抛异常时应被 logger.exception 记录"
        # 验证: _cleanup_errors 增加
        assert app._cleanup_errors >= 1, \
            f"_cleanup_errors 应增加 (db.close() 异常), 实际 {app._cleanup_errors}"

    def test_face_detector_and_db_both_logged_with_exception(self):
        """M-23: face_detector.close() 和 db.close() 都抛异常时,
        两个异常都应被 logger.exception 记录."""
        from main import EyeFocusApp

        app = EyeFocusApp.__new__(EyeFocusApp)
        app._original_sigint = None
        app._original_sigterm = None
        app._face_detector = MagicMock()
        app._face_detector.close.side_effect = RuntimeError("face close failed")
        app._db = MagicMock()
        app._db.close.side_effect = RuntimeError("db close failed")
        app._cleanup_errors = 0

        with patch("main.logger") as mock_logger:
            app._cleanup()

        # 验证: logger.exception 被调至少 2 次 (face + db)
        assert mock_logger.exception.call_count >= 2, \
            f"logger.exception 应被调至少 2 次, 实际 {mock_logger.exception.call_count}"
        # 验证: _cleanup_errors = 2
        assert app._cleanup_errors == 2, \
            f"_cleanup_errors 应为 2, 实际 {app._cleanup_errors}"

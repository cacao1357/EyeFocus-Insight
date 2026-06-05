"""
tests/test_main_high_bugs.py — main.py 5 个 high bug 修复回归测试

H-13: _cleanup() 内 face_detector.close() 异常只 log warning，应该用 logger.exception
H-11: CameraManager.start() 在 isOpened()=False 时未 release cap
H-12: run_v4_2_calibration finally 块吞异常
H-01: signal handler 直接调 self.shutdown() 而非仅设 flag
H-02: CameraManager.start() 入口未 join 残留线程
"""

import logging
import os
import sys
import tempfile
import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch, call

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import EyeFocusApp, AppConfig, CameraManager


# ============ H-13: _cleanup() 异常用 logger.exception ============


class TestH13CleanupExceptionLogging:
    """H-13: _cleanup() 内 close() 异常时用 logger.exception 记录完整 traceback"""

    def test_face_detector_close_exception_uses_logger_exception(self, monkeypatch):
        """H-13: face_detector.close() 抛异常时使用 logger.exception 而非 logger.warning"""
        from main import EyeFocusApp

        app = EyeFocusApp.__new__(EyeFocusApp)
        # 模拟最小状态
        app._original_sigint = None
        app._original_sigterm = None
        app._db = None
        app._face_detector = MagicMock()
        app._face_detector.close.side_effect = RuntimeError("simulated close failure")
        app._cleanup_errors = 0

        # 捕获 logger 行为
        with patch("main.logger") as mock_logger:
            app._cleanup()

        # 验证: 用了 logger.exception (不是 logger.warning)
        # logger.exception 会自动加 traceback
        assert mock_logger.exception.called, "应使用 logger.exception 记录异常"
        # logger.warning 不应被用于记录该异常
        warning_calls = [
            c for c in mock_logger.warning.call_args_list
            if "close" in str(c).lower() or "FaceDetector" in str(c)
        ]
        assert not warning_calls, "不应使用 logger.warning 记录 close 异常"

    def test_cleanup_records_error_count(self, monkeypatch):
        """H-13: _cleanup() 记录 _cleanup_errors 计数"""
        from main import EyeFocusApp

        app = EyeFocusApp.__new__(EyeFocusApp)
        app._original_sigint = None
        app._original_sigterm = None
        app._db = None
        app._face_detector = MagicMock()
        app._face_detector.close.side_effect = RuntimeError("simulated close failure")

        # 初始 _cleanup_errors 不存在
        app._cleanup_errors = 0

        with patch("main.logger"):
            app._cleanup()

        # 验证 _cleanup_errors 被增加
        assert app._cleanup_errors >= 1, "_cleanup_errors 应记录异常次数"


# ============ H-11: CameraManager.start() 失败时 release cap ============


class TestH11CameraManagerStartFailure:
    """H-11: CameraManager.start() isOpened()=False 时必须 release cap 并置 None"""

    def test_start_release_cap_on_isopened_false(self):
        """H-11: VideoCapture 创建后 isOpened()=False 时，start() 应 release cap 且 _cap=None"""
        cm = CameraManager(camera_index=99)

        # 模拟 cv2.VideoCapture: isOpened() 返回 False
        with patch("cv2.VideoCapture") as mock_vc:
            fake_cap = MagicMock()
            fake_cap.isOpened.return_value = False
            mock_vc.return_value = fake_cap

            result = cm.start()

        # 验证: 启动失败
        assert result is False, "isOpened()=False 时 start() 应返回 False"

        # 验证: 释放 cap
        fake_cap.release.assert_called_once(), "应调用 release()"

        # 验证: _cap 被置为 None (避免悬挂引用)
        assert cm._cap is None, f"start() 失败后 _cap 应为 None, 实际 {cm._cap!r}"

    def test_start_success_does_not_release_cap(self):
        """H-11 边界: 成功时不应立即 release"""
        cm = CameraManager(camera_index=0)

        with patch("cv2.VideoCapture") as mock_vc:
            fake_cap = MagicMock()
            fake_cap.isOpened.return_value = True
            mock_vc.return_value = fake_cap

            result = cm.start()

        assert result is True
        # 成功时不应 release (线程还在使用)
        fake_cap.release.assert_not_called()
        # _cap 应保留
        assert cm._cap is fake_cap

        # Cleanup
        cm._running = False
        if cm._read_thread:
            cm._read_thread.join(timeout=2.0)


# ============ H-12: run_v4_2_calibration finally 异常处理 ============


class TestH12RunV42CalibrationFinally:
    """H-12: run_v4_2_calibration finally 块异常不应替换 try 块原始异常"""

    def test_finally_start_exception_does_not_replace_original(self):
        """H-12: calibration_module.run 抛异常 + camera_manager.start() 也抛异常时,
        两个异常都应被记录, start() 返回值被检查"""
        from main import EyeFocusApp
        import main as main_module
        import calibration as calibration_module_real

        app = EyeFocusApp.__new__(EyeFocusApp)
        app._session_id = "test_session"
        app._db = MagicMock()
        # 模拟 _camera_manager: is_running() False (需要重启), start() 抛异常
        app._camera_manager = MagicMock()
        app._camera_manager.is_running.return_value = False
        app._camera_manager.start.side_effect = RuntimeError("camera start failed")

        # 替换 calibration_module.run 为抛异常
        with patch.object(main_module.calibration_module, "run") as mock_run:
            mock_run.side_effect = RuntimeError("calibration failed")

            with patch("main.logger") as mock_logger:
                result = app.run_v4_2_calibration()

        # 验证: 返回 None (calibration 失败)
        assert result is None, f"calibration 抛异常时应返回 None, 实际 {result!r}"

        # 验证: 两个异常都被记录
        # calibration_module.run 抛的异常被外层 except 捕获
        # camera_manager.start() 抛的异常被 finally 内的 try/except 捕获
        assert mock_logger.exception.called, "logger.exception 应被调用记录异常"

        # 验证: start() 被调用过 (finally 试图重启)
        app._camera_manager.start.assert_called_once()

    def test_finally_start_failure_logged_not_re_raised(self):
        """H-12: finally 块内 start() 异常应被 try/except 捕获, 不应逃逸"""
        from main import EyeFocusApp
        import main as main_module

        app = EyeFocusApp.__new__(EyeFocusApp)
        app._session_id = "test_session"
        app._db = MagicMock()
        app._camera_manager = MagicMock()
        app._camera_manager.is_running.return_value = False
        app._camera_manager.start.side_effect = RuntimeError("start failed in finally")

        with patch.object(main_module.calibration_module, "run") as mock_run:
            mock_run.return_value = None  # 正常返回 None

            with patch("main.logger"):
                # 不应抛异常
                result = app.run_v4_2_calibration()

        assert result is None
        # start() 异常被吞掉 (catch 住)
        app._camera_manager.start.assert_called_once()


# ============ H-01: signal handler 不直接调 shutdown ============


class TestH01SignalHandlerSafety:
    """H-01: signal handler 只设 flag, 不直接调 shutdown()"""

    def test_signal_handler_only_sets_flags_not_shutdown(self):
        """H-01: _signal_handler 不调 self.shutdown(), 只设 _running=False + _shutdown_event.set()"""
        from main import EyeFocusApp

        app = EyeFocusApp.__new__(EyeFocusApp)
        app._running = True
        app._shutdown_event = threading.Event()

        # Mock shutdown 验证它不被调用
        app.shutdown = MagicMock()

        with patch("main.logger"):
            app._signal_handler(signal=2, frame=None)

        # 验证: shutdown() 不被直接调用
        app.shutdown.assert_not_called(), "signal handler 不应直接调 shutdown()"

        # 验证: _running 被设 False
        assert app._running is False, "_running 应被设 False"

        # 验证: _shutdown_event 被 set
        assert app._shutdown_event.is_set(), "_shutdown_event 应被 set"

    def test_main_loop_responds_to_shutdown_event(self):
        """H-01: _main_loop 的 _running 循环可被 _shutdown_event 截断
        (后续通过 _main_loop 内部实现验证)"""
        # 这条测试由 H-01 的 fix 实现保证 — main_loop 应在 _running=False 时退出
        # 由于 _main_loop 调用摄像头/数据库等较重, 这里仅验证 flag 行为
        from main import EyeFocusApp

        app = EyeFocusApp.__new__(EyeFocusApp)
        app._running = True
        app._shutdown_event = threading.Event()
        app.shutdown = MagicMock()

        with patch("main.logger"):
            app._signal_handler(signal=15, frame=None)

        # 双重保险: 既设 _running=False, 也 set _shutdown_event
        assert app._running is False
        assert app._shutdown_event.is_set()


# ============ H-02: CameraManager.start() 残留线程 join ============


class TestH02CameraManagerStartJoin:
    """H-02: CameraManager.start() 入口先 join 残留线程再覆盖 _cap"""

    def test_start_joins_existing_thread_before_overwriting(self):
        """H-02: start() 入口应先 join 残留线程, 再覆盖 _cap"""
        cm = CameraManager(camera_index=0)

        # 模拟: 第一次 start 成功, 留下 _read_thread
        with patch("cv2.VideoCapture") as mock_vc:
            fake_cap1 = MagicMock()
            fake_cap1.isOpened.return_value = True
            mock_vc.return_value = fake_cap1

            ok1 = cm.start()
            assert ok1 is True

        # 模拟残留线程还没退出 (join 不会立即返回)
        join_calls = []
        original_join = cm._read_thread.join
        def tracking_join(timeout=None):
            join_calls.append(timeout)
            # 不调用原始 join, 模拟卡住
            return None
        cm._read_thread.join = tracking_join

        # 第二次 start: 旧线程残留, 模拟 cap 还没释放完
        with patch("cv2.VideoCapture") as mock_vc2:
            fake_cap2 = MagicMock()
            fake_cap2.isOpened.return_value = True
            mock_vc2.return_value = fake_cap2

            # 设置第一次 thread 残留
            ok2 = cm.start()

        # 验证: 第二次 start 入口调了 join
        assert len(join_calls) >= 1, f"start() 入口应 join 残留线程, join_calls={join_calls}"
        # join timeout 应 >= 1.0 (新阈值)
        assert join_calls[0] >= 1.0, f"join timeout 应 >= 1.0, 实际 {join_calls[0]}"

        # 验证: 第二次 start 成功
        assert ok2 is True

        # Cleanup
        cm._running = False
        if cm._read_thread:
            cm._read_thread.join(timeout=2.0)

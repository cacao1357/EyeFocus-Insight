"""T-CAL-14 v4.2 集成测试 — 验证 main.py 与新 calibration 模块的接入点。

测试覆盖：
- run_v4_2_calibration 调用 calibration_module.run()
- 摄像头释放 / 重新启动
- 校准结果应用到 eye_detector / fatigue_analyzer
- 校准取消返回 None
- 异常时不崩溃
"""
import os
import sys
import tempfile
from datetime import datetime
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import EyeFocusApp, AppConfig
import calibration
from calibration.result import CalibrationResult, CalibrationSignal


def _make_mock_result():
    return CalibrationResult(
        session_id="test_session",
        timestamp=datetime(2026, 6, 3),
        signal=CalibrationSignal(
            ear_mean=0.30, ear_min=0.08, ear_mid=0.18,
            yaw_mean=0.0, yaw_range=(-15.0, 15.0),
            pitch_mean=0.0, pitch_range=(-10.0, 10.0),
            glasses_mode=False, timestamp=0.0,
        ),
        blink_rounds=[],
        final_adjustment_factor=1.0,
        final_blink_threshold=0.225,
        final_squint_threshold=0.225,
        baseline_blink_rate=15.0,
        cqs=1.0,
        is_accepted=True,
    )


def _make_app(tmp_path, monkeypatch):
    """构造一个最小 EyeFocusApp（mock 所有外部依赖）。"""
    import main as main_module
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
        camera_index=0, enable_calibration=False, data_dir=str(tmp_path),
    ))
    return app


def _make_mock_camera():
    """构造一个能跟踪 is_running 状态的 mock camera。"""
    state = {"running": True}
    cam = MagicMock()
    cam.is_running = MagicMock(side_effect=lambda: state["running"])
    cam.release = MagicMock(side_effect=lambda: state.update(running=False))
    cam.start = MagicMock(side_effect=lambda: state.update(running=True))
    return cam


def test_run_v4_2_calibration_method_exists():
    """v4.2 入口方法必须存在于 EyeFocusApp。"""
    assert hasattr(EyeFocusApp, 'run_v4_2_calibration')
    assert callable(EyeFocusApp.run_v4_2_calibration)


def test_run_v4_2_calibration_calls_calibration_run(tmp_path, monkeypatch):
    """run_v4_2_calibration 应调 calibration.run() 并返回其结果。"""
    app = _make_app(tmp_path, monkeypatch)
    app._camera_manager = _make_mock_camera()
    app._eye_detector = MagicMock()
    app._fatigue_analyzer = MagicMock()
    app._db = MagicMock()
    app._session_id = "s1"

    mock_result = _make_mock_result()
    with patch.object(calibration, 'run', return_value=mock_result) as mock_run:
        result = app.run_v4_2_calibration()

    # calibration.run 被调
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs['session_id'] == "s1"
    # 摄像头先释放后重启
    assert app._camera_manager.release.called
    assert app._camera_manager.start.called
    # 返回值正确
    assert result is mock_result


def test_run_v4_2_calibration_releases_camera(tmp_path, monkeypatch):
    """v4.2 流程必须先释放主程序摄像头。"""
    app = _make_app(tmp_path, monkeypatch)
    app._camera_manager = _make_mock_camera()
    app._eye_detector = None
    app._fatigue_analyzer = None
    app._db = None
    app._session_id = None

    with patch.object(calibration, 'run', return_value=None):
        app.run_v4_2_calibration()

    # 释放
    app._camera_manager.release.assert_called_once()
    # 重新启动
    app._camera_manager.start.assert_called_once()


def test_run_v4_2_calibration_skips_release_if_not_running(tmp_path, monkeypatch):
    """摄像头未启动时，run_v4_2_calibration 不应调 release()。"""
    app = _make_app(tmp_path, monkeypatch)
    # 构造一个 not running 的 camera mock（用 side_effect）
    cam = MagicMock()
    cam.is_running = MagicMock(return_value=False)
    app._camera_manager = cam
    app._eye_detector = None
    app._fatigue_analyzer = None
    app._db = None
    app._session_id = None

    with patch.object(calibration, 'run', return_value=None):
        app.run_v4_2_calibration()

    cam.release.assert_not_called()


def test_run_v4_2_calibration_cancelled_returns_none(tmp_path, monkeypatch):
    """calibration.run() 返回 None（取消）→ 主程序走默认基线。"""
    app = _make_app(tmp_path, monkeypatch)
    app._camera_manager = _make_mock_camera()
    app._eye_detector = MagicMock()
    app._fatigue_analyzer = MagicMock()
    app._db = None
    app._session_id = "s1"

    with patch.object(calibration, 'run', return_value=None):
        result = app.run_v4_2_calibration()

    assert result is None


def test_run_v4_2_calibration_exception_does_not_crash(tmp_path, monkeypatch):
    """calibration.run() 抛异常时，run_v4_2_calibration 不应崩。"""
    app = _make_app(tmp_path, monkeypatch)
    app._camera_manager = _make_mock_camera()
    app._eye_detector = None
    app._fatigue_analyzer = None
    app._db = None
    app._session_id = None

    with patch.object(calibration, 'run', side_effect=Exception("boom")):
        result = app.run_v4_2_calibration()

    # 异常被吞，返回 None
    assert result is None
    # finally 仍执行 — 摄像头应被重启
    app._camera_manager.start.assert_called()


def test_apply_v4_2_calibration_result_applies_thresholds(tmp_path, monkeypatch):
    """校准成功结果应被应用到 detector + fatigue_analyzer。"""
    app = _make_app(tmp_path, monkeypatch)
    app._eye_detector = MagicMock()
    app._fatigue_analyzer = MagicMock()
    app._db = MagicMock()
    app._session_id = "s1"

    result = _make_mock_result()
    app._apply_v4_2_calibration_result(result)

    # eye_detector.set_baseline 被调
    app._eye_detector.set_baseline.assert_called_once_with(0.30)
    # fatigue_analyzer.set_baseline_blink_rate 被调
    app._fatigue_analyzer.set_baseline_blink_rate.assert_called_once_with(15.0)
    # db.update_session 被调
    app._db.update_session.assert_called_once()

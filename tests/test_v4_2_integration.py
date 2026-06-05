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
from dataclasses import replace
from datetime import datetime
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import EyeFocusApp, AppConfig
import calibration
from calibration.result import CalibrationResult, CalibrationSignal


def _make_mock_result(
    final_adjustment_factor: float = 1.0,
    yaw_range: tuple = (-15.0, 15.0),
    pitch_range: tuple = (-10.0, 10.0),
):
    return CalibrationResult(
        session_id="test_session",
        timestamp=datetime(2026, 6, 3),
        signal=CalibrationSignal(
            ear_mean=0.30, ear_min=0.08, ear_mid=0.18,
            yaw_mean=0.0, yaw_range=yaw_range,
            pitch_mean=0.0, pitch_range=pitch_range,
            glasses_mode=False, timestamp=0.0,
        ),
        blink_rounds=[],
        final_adjustment_factor=final_adjustment_factor,
        final_blink_threshold=0.225 * final_adjustment_factor,
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


def test_apply_v4_2_calibration_result_applies_adjustment_factor_P0(tmp_path, monkeypatch):
    """P0: final_adjustment_factor 应被传给 eye_detector.set_adjustment_factor。"""
    app = _make_app(tmp_path, monkeypatch)
    app._eye_detector = MagicMock()
    app._fatigue_analyzer = MagicMock()
    app._db = MagicMock()
    app._session_id = "s1"

    # 模拟校准算出 90% 调整
    result = _make_mock_result(final_adjustment_factor=0.9)
    app._apply_v4_2_calibration_result(result)

    # P0: set_adjustment_factor 被调且参数正确
    app._eye_detector.set_adjustment_factor.assert_called_once_with(0.9)


def test_apply_v4_2_calibration_result_applies_head_pose_std_P1(tmp_path, monkeypatch):
    """P1: 头部姿态 yaw_range/pitch_range 应被转为 std 传给 focus_analyzer.set_baseline。"""
    app = _make_app(tmp_path, monkeypatch)
    app._eye_detector = MagicMock()
    app._fatigue_analyzer = MagicMock()
    app._focus_analyzer = MagicMock()  # P1
    app._db = MagicMock()
    app._session_id = "s1"

    # 模拟真机数据: yaw_range=(52.4, -52.0), pitch_range=(-48.7, 16.0)
    result = _make_mock_result(
        yaw_range=(52.4, -52.0),
        pitch_range=(-48.7, 16.0),
    )
    app._apply_v4_2_calibration_result(result)

    # P1: set_baseline 被调, std 应为 max/3
    # max(|52.4|, |52.0|) / 3 = 17.47
    # max(|-48.7|, |16.0|) / 3 = 16.23
    call_args = app._focus_analyzer.set_baseline.call_args
    assert call_args is not None
    ear_arg = call_args.args[0]
    yaw_std_arg = call_args.args[1]
    pitch_std_arg = call_args.args[2]
    assert ear_arg == pytest.approx(0.30, abs=0.001)
    assert yaw_std_arg == pytest.approx(17.47, abs=0.01)
    assert pitch_std_arg == pytest.approx(16.23, abs=0.01)


# ========== v4.3 集成: calibration_mode 默认 v4_2 ==========

def test_app_config_calibration_mode_default_v4_2(tmp_path, monkeypatch):
    """v4.3: AppConfig.calibration_mode 默认 'v4_2' (新模块), 替代 v3.x 默认路径"""
    from main import AppConfig
    config = AppConfig(camera_index=0)
    assert config.calibration_mode == "v4_2", (
        f"calibration_mode 默认应 'v4_2', 实际 '{config.calibration_mode}'"
    )


def test_start_calibration_flow_dispatches_to_v4_2_by_default(tmp_path, monkeypatch):
    """v4.3: start_calibration_flow() 默认调 run_v4_2_calibration(), 不再走 v3.x 协调器"""
    app = _make_app(tmp_path, monkeypatch)
    app.config.calibration_mode = "v4_2"
    app._calib_coordinator = MagicMock()  # v3.x 路径存在但不应被调
    app._calib_coordinator.start = MagicMock()

    # 模拟 v4.2 路径: 返回 CalibrationResult
    from calibration.result import CalibrationResult, CalibrationSignal
    mock_result = _make_mock_result()
    app.run_v4_2_calibration = MagicMock(return_value=mock_result)

    result = app.start_calibration_flow()

    # v4.2 路径被调
    app.run_v4_2_calibration.assert_called_once()
    # v3.x 协调器 NOT 被调
    app._calib_coordinator.start.assert_not_called()
    assert result is True
    print("  ✓ v4.3 calibration_mode=v4_2 默认走 v4.2 路径")


def test_start_calibration_flow_falls_back_to_v3_x(tmp_path, monkeypatch):
    """v4.3: calibration_mode='v3_x' 走旧 UserCalibrationManager 协调器 (deprecated 兼容)"""
    app = _make_app(tmp_path, monkeypatch)
    app.config.calibration_mode = "v3_x"
    app._calib_coordinator = MagicMock()
    app._calib_coordinator.start = MagicMock()
    app.run_v4_2_calibration = MagicMock()  # 不应被调
    # 模拟 overlay 让 v3.x 分支的 DEBUG 日志不出错
    app._overlay = MagicMock()
    app._overlay._calib_display = None  # v3.x 分支容忍 None

    result = app.start_calibration_flow()

    # v3.x 路径被调
    app._calib_coordinator.start.assert_called_once()
    # v4.2 NOT 被调
    app.run_v4_2_calibration.assert_not_called()
    assert result is True
    print("  ✓ v4.3 calibration_mode=v3_x fallback 工作")


def test_start_calibration_flow_v4_2_cancelled_returns_false(tmp_path, monkeypatch):
    """v4.3: v4.2 校准被用户取消时 (返回 None), start_calibration_flow 返回 False"""
    app = _make_app(tmp_path, monkeypatch)
    app.config.calibration_mode = "v4_2"
    app.run_v4_2_calibration = MagicMock(return_value=None)

    result = app.start_calibration_flow()

    app.run_v4_2_calibration.assert_called_once()
    assert result is False
    print("  ✓ v4.3 v4.2 取消 → start_calibration_flow 返回 False")

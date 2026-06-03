"""测试 Beep — 封装 winsound 调用，非 Windows 时降级。"""
import sys
import pytest
from unittest.mock import patch, MagicMock


def test_beep_methods_exist():
    from calibration.audio.beep import Beep
    b = Beep()
    assert callable(b.phase_start)
    assert callable(b.phase_success)
    assert callable(b.phase_failed)
    assert callable(b.countdown_tick)
    assert callable(b.calibration_complete)


def test_beep_phase_start_calls_winsound():
    mock_winsound = MagicMock()
    with patch.dict(sys.modules, {'winsound': mock_winsound}):
        # 重新 import 让 winsound mock 生效
        import importlib
        from calibration.audio import beep as beep_module
        importlib.reload(beep_module)
        b = beep_module.Beep()
        b.phase_start()
        mock_winsound.Beep.assert_called_once()
        # 参数应该是 (频率, 时长_ms)
        args = mock_winsound.Beep.call_args[0]
        assert len(args) == 2
        assert args[0] > 0  # 频率
        assert args[1] > 0  # 时长


def test_beep_calibration_complete_plays_2_tones():
    mock_winsound = MagicMock()
    with patch.dict(sys.modules, {'winsound': mock_winsound}):
        import importlib
        from calibration.audio import beep as beep_module
        importlib.reload(beep_module)
        b = beep_module.Beep()
        b.calibration_complete()
        # 双音上扬：调 2 次
        assert mock_winsound.Beep.call_count == 2


def test_beep_no_winsound_fallback_no_crash():
    """winsound 不可用时（非 Windows），所有方法 no-op 不崩溃。"""
    with patch.dict(sys.modules, {'winsound': None}):
        import importlib
        from calibration.audio import beep as beep_module
        importlib.reload(beep_module)
        b = beep_module.Beep()
        # 不应抛异常
        b.phase_start()
        b.phase_success()
        b.phase_failed()
        b.countdown_tick()
        b.calibration_complete()

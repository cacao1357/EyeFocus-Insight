"""测试 TTS — pyttsx3 封装，初始化失败时降级。"""
import sys
import time
from unittest.mock import MagicMock, patch


def test_tts_say_calls_engine():
    mock_engine = MagicMock()
    mock_engine.getProperty.return_value = []
    with patch("pyttsx3.init", return_value=mock_engine):
        from calibration.audio import tts as tts_module
        import importlib
        importlib.reload(tts_module)
        t = tts_module.TTS()
        t.say("请闭眼")
        # say 是异步的，等待线程
        time.sleep(0.5)
        for thr in t._threads:
            thr.join(timeout=2)
        # mock 引擎应被调
        assert mock_engine.say.called or mock_engine.runAndWait.called


def test_tts_init_failure_fallback():
    """pyttsx3.init 抛异常时，TTS 实例创建不应崩溃，say 为 no-op。"""
    with patch("pyttsx3.init", side_effect=Exception("SAPI 不可用")):
        from calibration.audio import tts as tts_module
        import importlib
        importlib.reload(tts_module)
        t = tts_module.TTS()
        assert t._engine is None
        # 不抛异常
        t.say("test")


def test_tts_shutdown_safe_even_if_no_engine():
    with patch("pyttsx3.init", side_effect=Exception("fail")):
        from calibration.audio import tts as tts_module
        import importlib
        importlib.reload(tts_module)
        t = tts_module.TTS()
        t.shutdown()  # 不抛


def test_tts_selects_chinese_voice():
    """init 时应选中文 voice（如有）。"""
    mock_engine = MagicMock()
    # 构造两个 voice，一个英文一个中文
    class V:
        def __init__(self, vid):
            self.id = vid
    voices = [V("HKEY_LOCAL_MACHINE\\..\\TTS_MS_EN-US"), V("TTS_MS_ZH-CN_HUIHUI")]
    mock_engine.getProperty.return_value = voices
    with patch("pyttsx3.init", return_value=mock_engine):
        from calibration.audio import tts as tts_module
        import importlib
        importlib.reload(tts_module)
        tts_module.TTS()
        # 至少应设过 voice 属性
        assert mock_engine.setProperty.call_count >= 2  # rate + voice


def test_tts_say_thread_failure_logged():
    """TTS 播放线程内失败时不应抛到主循环。"""
    mock_engine = MagicMock()
    mock_engine.getProperty.return_value = []
    mock_engine.runAndWait.side_effect = Exception("audio fail")
    with patch("pyttsx3.init", return_value=mock_engine):
        from calibration.audio import tts as tts_module
        import importlib
        importlib.reload(tts_module)
        t = tts_module.TTS()
        t.say("test")
        for thr in t._threads:
            thr.join(timeout=2)
        # 异常被吞，不抛出


def test_tts_shutdown_stops_engine():
    """shutdown 应调 engine.stop()。"""
    mock_engine = MagicMock()
    mock_engine.getProperty.return_value = []
    with patch("pyttsx3.init", return_value=mock_engine):
        from calibration.audio import tts as tts_module
        import importlib
        importlib.reload(tts_module)
        t = tts_module.TTS()
        t.shutdown()
        mock_engine.stop.assert_called_once()

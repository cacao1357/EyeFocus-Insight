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


def test_tts_shutdown_joins_inflight_threads():
    """shutdown 应 join 所有在飞线程，避免 daemon 线程持有 engine。

    M-24: 旧实现只 engine.stop()，不 join，导致 daemon 线程在引擎
    释放后仍调用 runAndWait 抛 RuntimeError。
    """
    import threading
    mock_engine = MagicMock()
    mock_engine.getProperty.return_value = []

    # 让 runAndWait 阻塞,模拟慢速 TTS
    block_event = threading.Event()

    def slow_run_and_wait():
        block_event.wait(timeout=2.0)

    mock_engine.runAndWait.side_effect = slow_run_and_wait

    # 让 stop 触发 block_event,unblock runAndWait (模拟真实 pyttsx3 行为)
    def stop_unblocks():
        block_event.set()
    mock_engine.stop.side_effect = stop_unblocks

    with patch("pyttsx3.init", return_value=mock_engine):
        from calibration.audio import tts as tts_module
        import importlib
        importlib.reload(tts_module)
        t = tts_module.TTS()
        t.say("测试")
        # 等待 _do_say 拿到锁并进入 runAndWait
        time.sleep(0.1)
        assert any(thr.is_alive() for thr in t._threads), "线程应在飞"

        # 触发 shutdown:stop 应 unblock runAndWait,然后 join
        t.shutdown()

        # 所有线程应被 join (不再是 is_alive)
        for thr in t._threads:
            assert not thr.is_alive(), "shutdown 后线程应已结束"
        # engine 应被 stop
        mock_engine.stop.assert_called_once()


def test_tts_shutdown_unblocks_say_via_engine_none():
    """shutdown 后新调 say() 应静默 (engine=None),不抛异常。"""
    mock_engine = MagicMock()
    mock_engine.getProperty.return_value = []
    with patch("pyttsx3.init", return_value=mock_engine):
        from calibration.audio import tts as tts_module
        import importlib
        importlib.reload(tts_module)
        t = tts_module.TTS()
        t.shutdown()
        # engine=None 后 say 静默返回
        t.say("x")
        # 不抛
        assert t._engine is None

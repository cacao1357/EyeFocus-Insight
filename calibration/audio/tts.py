"""calibration/audio/tts.py — pyttsx3 中文 TTS 封装

异步说话（不阻塞主循环）。初始化失败时 _engine=None，say() 静默。

设计依据：spec §2.6 + 决策 S2 中文 TTS。
"""
import logging
import threading
from typing import List, Optional

logger = logging.getLogger("eyefocus.calibration.audio")


class TTS:
    def __init__(self, rate: int = 180):
        self._engine = None
        self._lock = threading.Lock()
        self._threads: List[threading.Thread] = []
        try:
            import pyttsx3
            self._engine = pyttsx3.init()
            self._engine.setProperty('rate', rate)
            # 优先选中文音色
            for v in self._engine.getProperty('voices'):
                if hasattr(v, 'id') and ('chinese' in v.id.lower() or 'zh' in v.id.lower()):
                    self._engine.setProperty('voice', v.id)
                    break
        except Exception as e:
            logger.warning("TTS 初始化失败，将降级为静默: %s", e)
            self._engine = None

    def say(self, text: str) -> None:
        """异步说话，不阻塞主循环。"""
        if self._engine is None:
            return
        thr = threading.Thread(target=self._do_say, args=(text,), daemon=True)
        thr.start()
        self._threads.append(thr)
        # 清理已完成的线程
        self._threads = [t for t in self._threads if t.is_alive()]

    def _do_say(self, text: str) -> None:
        engine = self._engine  # 进入时捕获引用,避免 shutdown 后 None
        if engine is None:
            return
        with self._lock:
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as e:
                logger.warning("TTS 播放失败: %s", e)

    def shutdown(self) -> None:
        """关闭 TTS 引擎。

        顺序（M-24 修复）：
        1. 取出当前 engine 引用
        2. self._engine = None — 让新调 say() 静默（_do_say 入口检查）
        3. engine.stop() — 兜底,驱动层停掉当前 utterance 让 runAndWait 返回
        4. join 所有在飞线程（带 timeout）— 避免 daemon 线程持有
           已销毁的 engine 抛 RuntimeError
        """
        engine = self._engine
        self._engine = None
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass
        for t in self._threads:
            if t.is_alive():
                t.join(timeout=1.0)
        # 清理已结束的线程引用
        self._threads = [t for t in self._threads if t.is_alive()]

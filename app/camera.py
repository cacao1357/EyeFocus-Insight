"""
app/camera.py — 摄像头管理类

从 main.py strangler 提取，不改变行为。
"""

import logging
import threading
import time
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("eyefocus.main")


class CameraManager:
    """摄像头管理类 - 负责摄像头采集线程管理"""

    def __init__(self, camera_index: int = 0):
        self._camera_index = camera_index
        self._cap: Optional[cv2.VideoCapture] = None
        self._running: bool = False

        # 线程间共享数据
        self._latest_frame: np.ndarray = None
        self._latest_ret: bool = False
        self._frame_lock: threading.Lock = threading.Lock()

        # 读取线程
        self._read_thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        """启动摄像头

        Returns:
            True 如果启动成功
        """
        # H-02: 入口先 join 残留 read 线程, 避免旧线程在新 cap 替换后并发 read
        if self._read_thread is not None and self._read_thread.is_alive():
            self._read_thread.join(timeout=3.0)
            if self._read_thread.is_alive():
                logger.warning(
                    "CameraManager.start(): 残留 read 线程未在 3s 内退出, 继续启动"
                )

        self._cap = cv2.VideoCapture(self._camera_index, cv2.CAP_DSHOW)

        if not self._cap.isOpened():
            logger.error("无法打开摄像头 (index %d)", self._camera_index)
            # H-11: 失败时 release cap 并置 None, 避免悬挂引用泄漏
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
            return False

        self._running = True
        self._read_thread = threading.Thread(target=self._camera_read_loop, daemon=True)
        self._read_thread.start()

        logger.info("摄像头启动成功 (index %d)", self._camera_index)
        return True

    def _camera_read_loop(self) -> None:
        """后台线程读取摄像头"""
        while self._running:
            if self._cap is None:
                break
            ret, frame = self._cap.read()
            with self._frame_lock:
                self._latest_ret = ret
                self._latest_frame = frame
            time.sleep(0.01)  # 避免过度占用 CPU

    def get_frame(self) -> tuple:
        """获取最新帧（非阻塞）

        Returns:
            (ret, frame) 元组
        """
        with self._frame_lock:
            return self._latest_ret, self._latest_frame

    def release(self) -> None:
        """释放摄像头资源

        H-02 修复: 先 release cap 解阻塞 cap.read(), 再 join 线程,
        避免 join 超时后 cap 仍被线程占用。
        """
        self._running = False
        # 先 release cap → cap.read() 立即返回（可能空 tuple）
        if self._cap:
            self._cap.release()
            self._cap = None
        # 再 join 线程（此时 read 循环已退出或即将退出）
        if self._read_thread:
            self._read_thread.join(timeout=0.5)

    def stop(self) -> bool:
        """停止摄像头（保留 start() 重启能力）

        v4.0.2 配合 B3 修复: 验证摄像头后立即停止，main_loop 会再次 start。
        """
        self.release()
        logger.info("摄像头已释放")
        return True

    @property
    def is_running(self) -> bool:
        return self._running

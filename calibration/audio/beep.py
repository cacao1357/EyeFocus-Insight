"""calibration/audio/beep.py — winsound 蜂鸣封装

非 Windows 环境时所有方法 no-op + 日志警告。

设计依据：spec §2.5 + 决策 S2 蜂鸣 + TTS 双轨。
"""
import logging

logger = logging.getLogger("eyefocus.calibration.audio")

try:
    import winsound  # type: ignore[import]
    _HAS_WINSOUND = True
except ImportError:
    _HAS_WINSOUND = False
    logger.warning("winsound 不可用（非 Windows），蜂鸣音降级为 no-op")


class Beep:
    """语义化蜂鸣声接口。"""

    def phase_start(self) -> None:
        """阶段开始：短促高频。"""
        if _HAS_WINSOUND:
            winsound.Beep(1000, 200)

    def phase_success(self) -> None:
        """阶段成功：单声高音。"""
        if _HAS_WINSOUND:
            winsound.Beep(1500, 300)

    def phase_failed(self) -> None:
        """阶段失败：单声低音长。"""
        if _HAS_WINSOUND:
            winsound.Beep(300, 800)

    def countdown_tick(self) -> None:
        """倒计时最后 3 秒每秒一次。"""
        if _HAS_WINSOUND:
            winsound.Beep(600, 100)

    def calibration_complete(self) -> None:
        """校准完成：双音上扬。"""
        if _HAS_WINSOUND:
            winsound.Beep(800, 200)
            winsound.Beep(1200, 400)

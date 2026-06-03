"""calibration/phases/base.py — Phase ABC 与共用 dataclass

每个阶段实现统一接口：feed_frame / get_live_feedback / is_complete / evaluate。
阶段类不知道 UI / 音频 / 键盘 — 纯数据采集 + 评估。

设计依据：spec §2.2。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass(frozen=True)
class LiveFeedback:
    """阶段进行中给 UI 的实时反馈数据。"""
    remaining_sec: float
    sample_count: int
    quality_hint: str = ""        # 可选：实时引导文字


@dataclass(frozen=True)
class PhaseResult:
    """阶段结束时的评估结果。"""
    success: bool
    summary: Dict[str, Any]            # 采集统计（每阶段格式不同）
    failure_reason: Optional[str] = None
    failure_diagnosis: Optional[str] = None    # 给用户看的中文建议


class Phase(ABC):
    """所有阶段的抽象基类。"""

    name: str = ""
    duration_seconds: float = 0.0
    tts_intro: str = ""           # 阶段开始时 TTS 念
    tts_complete: str = ""        # 阶段成功结束时 TTS 念

    @abstractmethod
    def reset(self) -> None:
        """重置内部状态（重做时调用）。"""
        ...

    @abstractmethod
    def feed_frame(
        self,
        ear: Optional[float],
        yaw: Optional[float],
        pitch: Optional[float],
        timestamp: float,
    ) -> None:
        """每帧调用 — 接收当前帧 EAR/yaw/pitch（人脸丢失时为 None）。"""
        ...

    @abstractmethod
    def get_live_feedback(self, elapsed_sec: float) -> LiveFeedback:
        """获取实时反馈，UI 每帧调一次。"""
        ...

    @abstractmethod
    def is_complete(self, elapsed_sec: float) -> bool:
        """阶段是否到时完成。"""
        ...

    @abstractmethod
    def evaluate(self) -> PhaseResult:
        """阶段结束时评估成功/失败 + 给出摘要 + 失败诊断。"""
        ...

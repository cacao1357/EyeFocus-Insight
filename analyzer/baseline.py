"""
analyzer/baseline.py — 基线校准模块

提供 BaselineCalibrator 类，用于：
- 采集用户正常状态下的 EAR、头部姿态数据
- 计算 CQS (Calibration Quality Score) 评估校准质量
- 自动判断眼镜模式

CQS 公式：
  ratio_score = valid_count / total_count * 0.5
  cv_score = max(0, (1 - ear_cv * 3)) * 0.5
  cqs = min(1.0, ratio_score + cv_score)
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple

import numpy as np

from storage.models import BaselineResult, GlassesMode

logger = logging.getLogger("eyefocus.analyzer")


# 默认配置
DEFAULT_COLLECTION_DURATION = 7.0  # 秒
DEFAULT_TRIM_RATIO = 0.10  # 去掉头尾百分比
DEFAULT_MIN_VALID_FRAMES = 30
DEFAULT_CQS_THRESHOLD = 0.60


@dataclass
class CalibrationFrame:
    """校准期间的单个有效帧"""
    timestamp: float
    ear: float
    yaw: float
    pitch: float


@dataclass
class CalibrationStatus:
    """校准状态"""
    is_calibrating: bool
    progress: float  # 0.0 - 1.0
    elapsed_time: float
    collected_frames: int
    valid_frames: int
    current_cqs: float = 0.0


class BaselineCalibrator:
    """基线校准器

    使用方法：
        calibrator = BaselineCalibrator()
        calibrator.start()

        # 采集帧数据
        calibrator.add_frame(ear=0.25, yaw=2.0, pitch=-5.0)

        # 检查完成
        if calibrator.is_complete():
            result = calibrator.get_result()
    """

    def __init__(
        self,
        collection_duration: float = DEFAULT_COLLECTION_DURATION,
        trim_ratio: float = DEFAULT_TRIM_RATIO,
        min_valid_frames: int = DEFAULT_MIN_VALID_FRAMES,
        cqs_threshold: float = DEFAULT_CQS_THRESHOLD,
        yaw_thresh: float = 10.0,
        pitch_thresh: float = 20.0,
    ):
        """初始化基线校准器

        Args:
            collection_duration: 采集时长（秒）
            trim_ratio: 去掉头尾的比例
            min_valid_frames: 最小有效帧数
            cqs_threshold: CQS 通过阈值
            yaw_thresh: 有效帧的偏航角阈值（度）
            pitch_thresh: 有效帧的俯仰角阈值（度）
        """
        self.collection_duration = collection_duration
        self.trim_ratio = trim_ratio
        self.min_valid_frames = min_valid_frames
        self.cqs_threshold = cqs_threshold
        self.yaw_thresh = yaw_thresh
        self.pitch_thresh = pitch_thresh

        # 校准数据
        self._frames: List[CalibrationFrame] = []
        self._start_time: Optional[float] = None
        self._is_calibrating: bool = False
        self._is_complete: bool = False

        # 眼镜检测相关
        self._glasses_mode: GlassesMode = GlassesMode.UNKNOWN

    def start(self) -> None:
        """开始校准"""
        self._start_time = time.time()
        self._is_calibrating = True
        self._is_complete = False
        self._frames.clear()
        logger.info("基线校准开始，时长 %.1f 秒", self.collection_duration)

    def add_frame(
        self,
        ear: float,
        yaw: Optional[float] = None,
        pitch: Optional[float] = None,
        timestamp: Optional[float] = None,
    ) -> bool:
        """添加一帧校准数据

        Args:
            ear: 当前帧的 EAR 值
            yaw: 偏航角（度）
            pitch: 俯仰角（度）
            timestamp: 时间戳（秒），默认为从校准开始的时间

        Returns:
            是否接受此帧（True 表示有效帧）
        """
        if not self._is_calibrating:
            return False

        if timestamp is None:
            timestamp = time.time() - self._start_time

        # 检查是否为有效帧（头部姿态在阈值内）
        is_valid = True
        if yaw is not None and abs(yaw) > self.yaw_thresh:
            is_valid = False
        if pitch is not None and abs(pitch) > self.pitch_thresh:
            is_valid = False

        self._frames.append(CalibrationFrame(
            timestamp=timestamp,
            ear=ear,
            yaw=yaw if yaw is not None else 0.0,
            pitch=pitch if pitch is not None else 0.0,
        ))

        return is_valid

    def get_status(self) -> CalibrationStatus:
        """获取当前校准状态"""
        if not self._is_calibrating:
            return CalibrationStatus(
                is_calibrating=False,
                progress=0.0,
                elapsed_time=0.0,
                collected_frames=0,
                valid_frames=0,
            )

        elapsed = time.time() - self._start_time
        progress = min(1.0, elapsed / self.collection_duration)

        valid_frames = self._get_valid_frame_count()

        return CalibrationStatus(
            is_calibrating=True,
            progress=progress,
            elapsed_time=elapsed,
            collected_frames=len(self._frames),
            valid_frames=valid_frames,
            current_cqs=self._compute_cqs_preview(),
        )

    def _get_valid_frame_count(self) -> int:
        """获取有效帧数量"""
        if not self._frames:
            return 0

        # 按头部姿态过滤
        valid_count = 0
        for f in self._frames:
            if abs(f.yaw) <= self.yaw_thresh and abs(f.pitch) <= self.pitch_thresh:
                valid_count += 1

        return valid_count

    def _compute_cqs_preview(self) -> float:
        """预览当前 CQS（不含校准完成后的截断处理）"""
        if not self._frames:
            return 0.0

        valid_count = self._get_valid_frame_count()
        total_count = len(self._frames)

        ears = [f.ear for f in self._frames if abs(f.yaw) <= self.yaw_thresh and abs(f.pitch) <= self.pitch_thresh]

        if not ears or len(ears) < self.min_valid_frames:
            return 0.0

        ear_cv = float(np.std(ears)) / max(float(np.mean(ears)), 1e-6)

        ratio_score = valid_count / max(total_count, 1) * 0.5
        cv_score = max(0.0, (1.0 - ear_cv * 3.0)) * 0.5

        return round(min(1.0, ratio_score + cv_score), 3)

    def is_complete(self) -> bool:
        """检查校准是否完成"""
        if not self._is_calibrating:
            return self._is_complete

        elapsed = time.time() - self._start_time
        if elapsed >= self.collection_duration:
            self._finish()
            return True

        return False

    def _finish(self) -> None:
        """完成校准并计算结果"""
        self._is_calibrating = False
        self._is_complete = True

        if len(self._frames) < self.min_valid_frames:
            logger.warning("校准帧数不足: %d < %d", len(self._frames), self.min_valid_frames)
            return

        # 去掉头尾 trim_ratio%
        trim_count = int(len(self._frames) * self.trim_ratio)
        if trim_count > 0:
            sorted_frames = sorted(self._frames, key=lambda f: f.timestamp)
            trimmed = sorted_frames[trim_count:-trim_count] if trim_count < len(sorted_frames) else sorted_frames
        else:
            trimmed = self._frames

        # 按头部姿态过滤有效帧
        valid_frames = [
            f for f in trimmed
            if abs(f.yaw) <= self.yaw_thresh and abs(f.pitch) <= self.pitch_thresh
        ]

        if len(valid_frames) < self.min_valid_frames:
            logger.warning("校准有效帧不足: %d < %d", len(valid_frames), self.min_valid_frames)
            return

        # 计算统计值
        ears = [f.ear for f in valid_frames]
        yaws = [f.yaw for f in valid_frames]
        pitches = [f.pitch for f in valid_frames]

        ear_mean = float(np.mean(ears))
        ear_std = float(np.std(ears))
        yaw_std = float(np.std(yaws))
        pitch_std = float(np.std(pitches))

        # 计算 CQS
        ear_cv = ear_std / max(ear_mean, 1e-6)
        ratio_score = len(valid_frames) / max(len(self._frames), 1) * 0.5
        cv_score = max(0.0, (1.0 - ear_cv * 3.0)) * 0.5
        cqs = round(min(1.0, ratio_score + cv_score), 3)

        logger.info(
            "校准完成: CQS=%.3f, EAR=%.4f±%.4f, YAW_std=%.2f, PITCH_std=%.2f, 有效帧=%d/%d",
            cqs, ear_mean, ear_std, yaw_std, pitch_std, len(valid_frames), len(self._frames)
        )

    def get_result(self) -> Optional[BaselineResult]:
        """获取校准结果

        Returns:
            BaselineResult 对象，或 None（如果校准未通过）
        """
        if not self._is_complete:
            return None

        if len(self._frames) < self.min_valid_frames:
            return None

        # 去掉头尾
        trim_count = int(len(self._frames) * self.trim_ratio)
        sorted_frames = sorted(self._frames, key=lambda f: f.timestamp)
        trimmed = sorted_frames[trim_count:-trim_count] if trim_count < len(sorted_frames) else sorted_frames

        # 过滤有效帧
        valid_frames = [
            f for f in trimmed
            if abs(f.yaw) <= self.yaw_thresh and abs(f.pitch) <= self.pitch_thresh
        ]

        if len(valid_frames) < self.min_valid_frames:
            return None

        # 计算统计值
        ears = [f.ear for f in valid_frames]
        yaws = [f.yaw for f in valid_frames]
        pitches = [f.pitch for f in valid_frames]

        ear_mean = float(np.mean(ears))
        ear_std = float(np.std(ears))
        yaw_std = float(np.std(yaws))
        pitch_std = float(np.std(pitches))

        # CQS
        ear_cv = ear_std / max(ear_mean, 1e-6)
        ratio_score = len(valid_frames) / max(len(self._frames), 1) * 0.5
        cv_score = max(0.0, (1.0 - ear_cv * 3.0)) * 0.5
        cqs = round(min(1.0, ratio_score + cv_score), 3)

        is_valid = cqs >= self.cqs_threshold and len(valid_frames) >= self.min_valid_frames

        return BaselineResult(
            session_id="",  # 会在调用时填充
            is_valid=is_valid,
            cqs_score=cqs,
            ear_mean=ear_mean,
            ear_std=ear_std,
            yaw_std=yaw_std,
            pitch_std=pitch_std,
            valid_frame_count=len(valid_frames),
            total_frame_count=len(self._frames),
            glasses_mode=self._glasses_mode,
        )

    def cancel(self) -> None:
        """取消校准"""
        self._is_calibrating = False
        self._is_complete = False
        self._frames.clear()
        logger.info("校准已取消")

    def set_glasses_mode(self, mode: GlassesMode) -> None:
        """设置眼镜模式"""
        self._glasses_mode = mode
        logger.info("校准眼镜模式设置为: %s", mode.value)


def create_baseline_calibrator() -> BaselineCalibrator:
    """工厂函数：从 config 加载参数创建校准器"""
    from config import BASELINE, HEAD_POSE

    return BaselineCalibrator(
        collection_duration=BASELINE.collection_duration,
        trim_ratio=BASELINE.trim_ratio,
        min_valid_frames=BASELINE.min_valid_frames,
        cqs_threshold=BASELINE.cqs_threshold,
        yaw_thresh=HEAD_POSE.yaw_thresh,
        pitch_thresh=HEAD_POSE.pitch_thresh,
    )

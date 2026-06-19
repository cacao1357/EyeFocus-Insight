"""
app/processor.py — 帧处理器（FrameProcessor）

从 main.py strangler 提取，不改变行为。
"""

import logging
import time
from collections import deque
from typing import Callable, Deque, Optional

import numpy as np

from analyzer.focus import FocusAnalyzer
from analyzer.fatigue import FatigueAnalyzer
from analyzer.glasses import GlassesDetector
from analyzer.user_calibration import CalibrationState, UserCalibrationManager
from detector.eye_aspect import EyeAspectDetector
from detector.face_mesh import FaceMeshDetector
from detector.gaze import GazeDetector
from detector.light import LightDetector
from storage.db import DatabaseManager
from storage.models import BlinkRecord, FatigueRecord, FrameRecord, FocusRecord

logger = logging.getLogger("eyefocus.main")


class FrameProcessor:
    """帧处理器 - 负责帧处理流水线（检测->分析->存储）

    这个类处理单帧的所有分析逻辑，但不包括渲染和摄像头管理。
    """

    def __init__(
        self,
        face_detector: FaceMeshDetector,
        eye_detector: EyeAspectDetector,
        gaze_detector: GazeDetector,
        light_detector: LightDetector,
        glasses_detector: GlassesDetector,
        focus_analyzer: FocusAnalyzer,
        fatigue_analyzer: FatigueAnalyzer,
        calib_manager: Optional[UserCalibrationManager] = None,
        is_calibration_active: Optional[Callable[[], bool]] = None,
        db: Optional[DatabaseManager] = None,
        session_id: Optional[str] = None,
    ):
        self._face_detector = face_detector
        self._eye_detector = eye_detector
        self._gaze_detector = gaze_detector
        self._light_detector = light_detector
        self._glasses_detector = glasses_detector
        self._focus_analyzer = focus_analyzer
        self._fatigue_analyzer = fatigue_analyzer
        self._calib_manager = calib_manager
        self._is_calibration_active = is_calibration_active
        self._db = db
        self._session_id = session_id

        # 帧统计
        self._frame_count: int = 0

        # 眨眼写入索引（避免重复写入）
        self._last_written_blink_count: int = 0

        # 数据库写入节流
        self._last_frame_write_time: float = 0.0
        self._last_fatigue_write_time: float = 0.0
        self._last_focus_write_time: float = 0.0
        self._frame_write_interval: float = 1.0 / 15.0  # 最多 15 FPS 写入帧数据
        self._fatigue_write_interval: float = 1.0  # 最多每秒写入疲劳记录
        self._focus_write_interval: float = 30.0  # 每 30s 写入一次专注度记录

        # 多信号融合：头部姿态历史（用于检测晃动）
        self._yaw_history: Deque[float] = deque(maxlen=30)  # ~1秒历史
        self._pitch_history: Deque[float] = deque(maxlen=30)
        self._prev_landmarks: Optional[np.ndarray] = None  # 上一帧 landmarks

        # 头部姿态平滑滤波（滑动窗口均值，窗口大小 5 帧）
        self._smooth_yaw: Deque[float] = deque(maxlen=5)
        self._smooth_pitch: Deque[float] = deque(maxlen=5)

        # 最新分析结果（用于渲染）
        self._latest_focus_result = None
        self._latest_fatigue_result = None
        self._latest_gaze_score = 100.0
        self._latest_light_result = None
        self._latest_glasses_result = None
        self._latest_yaw: float = 0.0
        self._latest_pitch: float = 0.0
        self._latest_face_detected: bool = False
        self._latest_ear: float = 0.0

        # 低光照自适应标志
        self._low_light_active: bool = False
        self._saved_adjustment_factor: float = 1.0

        # 头部离屏检测
        self._head_away_threshold_yaw: float = 20.0
        self._head_away_threshold_pitch: float = 25.0
        self._head_away_start_time: Optional[float] = None
        self._cumulative_away_seconds: float = 0.0
        self._is_head_away: bool = False

        # 校准回调
        self._ear_callback: Optional[Callable[[], float]] = None
        self._head_pose_callback: Optional[Callable[[], tuple]] = None

    def process_frame(self, frame: np.ndarray) -> None:
        """处理单帧"""
        self._frame_count += 1
        timestamp_ms = int(time.time() * 1000)

        # v4.29: 异步人脸检测 — push_frame 排队, get_latest 非阻塞取上一帧结果
        self._face_detector.push_frame(frame, timestamp_ms)
        face_result = self._face_detector.get_latest()
        self._latest_face_detected = face_result.face_detected

        if not face_result.face_detected:
            if self._focus_analyzer is not None:
                frozen = self._focus_analyzer.analyze(
                    ear=0.0, yaw=0.0, pitch=0.0,
                    gaze_score=self._latest_gaze_score,
                    face_detected=False,
                )
                self._latest_focus_result = frozen
            return

        landmarks = face_result.landmarks

        current_yaw = face_result.yaw or 0.0
        current_pitch = face_result.pitch or 0.0
        self._yaw_history.append(current_yaw)
        self._pitch_history.append(current_pitch)

        self._smooth_yaw.append(current_yaw)
        self._smooth_pitch.append(current_pitch)
        smoothed_yaw = float(np.mean(self._smooth_yaw))
        smoothed_pitch = float(np.mean(self._smooth_pitch))

        # 头部离屏检测
        is_away = False
        if face_result.face_detected:
            if (abs(smoothed_yaw) > self._head_away_threshold_yaw or
                    abs(smoothed_pitch) > self._head_away_threshold_pitch):
                is_away = True

        if is_away:
            if not self._is_head_away:
                self._is_head_away = True
                self._head_away_start_time = time.time()
                logger.info("头部离屏: yaw=%.1f, pitch=%.1f（暂停分析）",
                            smoothed_yaw, smoothed_pitch)
        else:
            if self._is_head_away:
                away_dur = time.time() - self._head_away_start_time
                self._cumulative_away_seconds += away_dur
                logger.info("头部回屏: 离线 %.1fs, 累计 %.1fs",
                            away_dur, self._cumulative_away_seconds)
                self._is_head_away = False
                self._head_away_start_time = None

        # 头部姿态晃动检测
        head_pose_weight = 1.0
        if len(self._yaw_history) >= 10:
            yaw_std = float(np.std(self._yaw_history))
            pitch_std = float(np.std(self._pitch_history))
            if yaw_std > 3.0 or pitch_std > 3.0:
                max_std = max(yaw_std, pitch_std, 3.0)
                head_pose_weight = max(0.5, 1.0 - (max_std - 3.0) / 10.0)
            else:
                head_pose_weight = 1.0

        # 面部稳定性检测
        face_stability_weight = 1.0
        if self._prev_landmarks is not None and self._prev_landmarks.shape == landmarks.shape:
            landmark_movement = float(np.linalg.norm(landmarks - self._prev_landmarks))
            if landmark_movement > 10.0:
                face_stability_weight = max(0.3, 1.0 - (landmark_movement - 10.0) / 50.0)
            else:
                face_stability_weight = 1.0
        self._prev_landmarks = landmarks.copy()

        self._latest_yaw = smoothed_yaw
        self._latest_pitch = smoothed_pitch

        # EAR 计算
        self._eye_detector.set_head_pose_weight(head_pose_weight)
        self._eye_detector.set_face_stability_weight(face_stability_weight)
        eye_result = self._eye_detector.compute(landmarks, blendshapes=face_result.blendshapes)
        self._latest_ear = eye_result.ear_avg

        # Per-frame calibration data collection
        if self._is_calibration_active is not None and self._is_calibration_active():
            if self._calib_manager is not None and self._calib_manager.state == CalibrationState.AUTO_CALIB:
                self._calib_manager.add_frame(
                    ear=eye_result.ear_avg,
                    yaw=smoothed_yaw,
                    pitch=smoothed_pitch,
                )

        # 光照检测
        light_result = self._light_detector.analyze_frame(frame)
        self._latest_light_result = light_result

        # 低光照自适应
        if light_result.condition.value == "dark":
            if not getattr(self, '_low_light_active', False):
                self._low_light_active = True
                self._saved_adjustment_factor = self._eye_detector._adjustment_factor
                adj = max(0.7, self._saved_adjustment_factor * 0.9)
                self._eye_detector.set_adjustment_factor(adj)
                logger.info("低光照模式激活: adjustment_factor %.3f → %.3f",
                            self._saved_adjustment_factor, adj)
        else:
            if getattr(self, '_low_light_active', False):
                self._low_light_active = False
                saved = getattr(self, '_saved_adjustment_factor', 1.0)
                self._eye_detector.set_adjustment_factor(saved)
                logger.info("低光照模式解除: adjustment_factor 恢复 %.3f", saved)

        # 眼镜检测
        glasses_result = self._glasses_detector.detect(
            landmarks=landmarks,
            blendshapes=face_result.blendshapes,
        )
        self._latest_glasses_result = glasses_result

        # 视线检测
        gaze_result = self._gaze_detector.detect(
            landmarks=landmarks,
            head_pose_yaw=smoothed_yaw,
            head_pose_pitch=smoothed_pitch,
        )
        self._latest_gaze_score = gaze_result.gaze_concentration if gaze_result else 100.0

        # 离屏时跳过专注度/疲劳分析
        if self._is_head_away:
            return

        # 专注度分析
        focus_result = self._focus_analyzer.analyze(
            ear=eye_result.ear_avg,
            yaw=smoothed_yaw,
            pitch=smoothed_pitch,
            gaze_score=self._latest_gaze_score,
            brightness=light_result.brightness,
            face_detected=face_result.face_detected,
        )
        self._latest_focus_result = focus_result

        # 疲劳分析
        ear_nadir = None
        recent_blinks = self._eye_detector.get_blink_events(
            since_time=time.time() - 30.0
        )
        if recent_blinks:
            ear_nadir = recent_blinks[-1].ear_nadir

        fatigue_result = self._fatigue_analyzer.analyze(
            blink_rate=focus_result.blink_rate,
            ear_nadir=ear_nadir,
            head_stability=focus_result.head_score,
            avg_ear=eye_result.ear_avg,
            blink_flag=eye_result.is_blink,
        )
        self._latest_fatigue_result = fatigue_result

        # 存储帧记录
        current_time = time.time()
        if self._db and self._session_id and (current_time - self._last_frame_write_time) >= self._frame_write_interval:
            frame_record = FrameRecord(
                session_id=self._session_id,
                timestamp=current_time,
                ear_left=eye_result.ear_left,
                ear_right=eye_result.ear_right,
                ear_avg=eye_result.ear_avg,
                yaw=smoothed_yaw,
                pitch=smoothed_pitch,
                roll=face_result.roll or 0.0,
                gaze_score=focus_result.gaze_score,
                brightness=light_result.brightness,
                face_detected=face_result.face_detected,
                blendshapes=face_result.blendshapes,
            )
            self._db.write_frame(self._session_id, frame_record)
            self._last_frame_write_time = current_time

        # 存储眨眼事件
        if self._db and self._session_id:
            blink_events = self._eye_detector.get_blink_events()
            new_blinks = blink_events[self._last_written_blink_count:]
            for event in new_blinks:
                self._db.write_blink_event(
                    self._session_id,
                    BlinkRecord(
                        session_id=self._session_id,
                        start_timestamp=event.start_time,
                        end_timestamp=event.end_time,
                        duration_seconds=event.duration,
                        ear_nadir=event.ear_nadir,
                    )
                )
            self._last_written_blink_count = len(blink_events)

        # 存储疲劳记录
        if (self._db and self._session_id
                and self._latest_fatigue_result is not None
                and (current_time - self._last_fatigue_write_time) >= self._fatigue_write_interval):
            fatigue_record = FatigueRecord(
                session_id=self._session_id,
                timestamp=current_time,
                fatigue_level=self._latest_fatigue_result.fatigue_level,
                blink_rate=self._latest_fatigue_result.blink_rate,
                avg_ear_nadir=self._latest_fatigue_result.avg_ear_nadir,
                head_stability=self._latest_fatigue_result.head_stability,
                cumulative_fatigue_score=self._latest_fatigue_result.cumulative_fatigue,
            )
            self._db.write_fatigue_record(self._session_id, fatigue_record)
            self._last_fatigue_write_time = current_time

        # 存储专注度记录
        if (self._db and self._session_id
                and self._latest_focus_result is not None
                and (current_time - self._last_focus_write_time) >= self._focus_write_interval):
            fr = self._latest_focus_result
            focus_record = FocusRecord(
                session_id=self._session_id,
                window_start=current_time - 30.0,
                window_end=current_time,
                focus_score=fr.focus_score,
                eye_score=fr.eye_score,
                head_score=fr.head_score,
                gaze_score=fr.gaze_score,
                blink_rate=fr.blink_rate,
                avg_ear=self._latest_ear,
                avg_yaw=0.0,
                avg_pitch=0.0,
            )
            self._db.write_focus_record(self._session_id, focus_record)
            self._last_focus_write_time = current_time

    def get_current_ear(self) -> float:
        """获取当前 EAR 值（供校准回调使用）"""
        if self._eye_detector:
            return self._eye_detector.get_current_ear()
        return 0.0

    @property
    def away_seconds(self) -> float:
        """获取累计离屏时间（秒）"""
        if self._is_head_away and self._head_away_start_time is not None:
            return self._cumulative_away_seconds + (time.time() - self._head_away_start_time)
        return self._cumulative_away_seconds

    def get_head_pose(self) -> tuple:
        """获取当前头部姿态（供校准回调使用）"""
        return (self._latest_yaw, self._latest_pitch)

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def latest_focus_result(self):
        return self._latest_focus_result

    @property
    def latest_fatigue_result(self):
        return self._latest_fatigue_result

    @property
    def latest_gaze_score(self) -> float:
        return self._latest_gaze_score

    @property
    def latest_light_result(self):
        return self._latest_light_result

    @property
    def latest_glasses_result(self):
        return self._latest_glasses_result

    @property
    def latest_face_detected(self) -> bool:
        return self._latest_face_detected

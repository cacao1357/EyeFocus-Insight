"""
main.py — EyeFocus Insight 主程序入口

整合所有模块，实现：
- 摄像头视频流采集
- 人脸检测与关键点追踪
- 眨眼检测与疲劳分析
- 专注度实时评分
- GUI 叠加层显示
- 数据存储
- 安全退出

安全退出方案：
1. MediaPipe FaceLandmarker 运行在独立线程
2. 设置 daemon=True + join(timeout=5)
3. 超时后强制 terminate
4. 避免 os._exit() 实现干净退出
"""

# v4.0.2 修复 B4: 在 import mediapipe 之前禁用 Google telemetry 上报
# (absl logging 在 mediapipe import 时读取环境变量)
import logging
import os

# 必须先于其他 import 设置环境变量
os.environ.setdefault("GLOG_logtostderr", "0")
os.environ.setdefault("MEDIAPIPE_DISABLE_GPU", "1")
os.environ.setdefault("ABSL_CPP_MIN_LOG_LEVEL", "3")
# v4.4: PyQt5 平台插件路径 (pip 安装后 Qt 目录 vs Qt5 目录不一致)
_qt_pp = os.path.abspath(os.path.join(os.path.dirname(__file__),
    '.venv312/Lib/site-packages/PyQt5/Qt5/plugins'))
if os.path.isdir(_qt_pp):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', _qt_pp)

import signal
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from collections import deque
from typing import Deque, Optional, Callable

import cv2
import numpy as np

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import CAMERA
from analyzer.focus import FocusAnalyzer, create_focus_analyzer
from analyzer.voice_assistant import create_voice_assistant
from analyzer.reminder_engine import create_reminder_engine
from analyzer.gamification import create_gamification_engine
from analyzer.glasses import GlassesDetector, create_glasses_detector
from analyzer.fatigue import FatigueAnalyzer, create_fatigue_analyzer
from detector.face_mesh import FaceMeshDetector, create_face_mesh_detector
from detector.eye_aspect import EyeAspectDetector, create_eye_aspect_detector
from detector.gaze import GazeDetector, create_gaze_detector
from detector.light import LightDetector, create_light_detector
from analyzer.user_calibration import (
    UserCalibrationManager,
    CalibrationCallbacks,
    create_user_calibration_manager,
    CalibrationState,
)
from storage.models import CalibrationResult
import calibration as calibration_module  # v4.2: 新校准模块
from gui.overlay import FocusOverlay
from storage.db import DatabaseManager, create_database_manager
from storage.models import (
    BlinkRecord,
    FatigueRecord,
    FrameRecord,
    Session,
)


logger = logging.getLogger("eyefocus.main")


@dataclass
class AppConfig:
    """应用配置"""
    camera_index: int = CAMERA.index
    min_fps: float = CAMERA.min_fps
    enable_calibration: bool = True
    calibration_duration: float = 7.0
    data_dir: str = "data"
    # M-21: 摄像头帧尺寸 (校准模块需要)
    frame_width: int = 640
    frame_height: int = 480
    # 2026-06-05 v4.3 集成: 校准模块版本选择
    #   "v4_2" — 默认, 用 calibration/ 新模块 (5 phase + HEAD 4 sub-phase + 完整 blink counting)
    #   "v3_x" — 旧 analyzer/user_calibration.py 路径 (5 phase 但 HEAD 只 UP, 跳过 DOWN/LEFT/RIGHT)
    calibration_mode: str = "v4_2"
    # v4.4: PyQt5 UI 模式 (替换 OpenCV cv2.imshow 主循环)
    # v4.5.2: 默认启用 Qt 模式
    use_qt: bool = True
    # v4.10: 系统托盘 (仅 Qt 模式)
    enable_tray: bool = True


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
        # v4.4: timeout 1.0→0.5 (关闭卡顿, cap已先释放, 线程应快速退出)
        if self._read_thread:
            self._read_thread.join(timeout=0.5)

    def stop(self) -> bool:
        """停止摄像头（保留 start() 重启能力，等价于 release 但不删 self._camera_index）

        v4.0.2 配合 B3 修复: 验证摄像头后立即停止，main_loop 会再次 start。

        v4.3 fix: 移除 dead code (return True 在 logger.info 前, 日志永远不打印)
        """
        self.release()
        logger.info("摄像头已释放")
        return True

    @property
    def is_running(self) -> bool:
        return self._running


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
        calib_manager: Optional["UserCalibrationManager"] = None,
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
        self._prev_landmarks: Optional[np.ndarray] = None  # 上一帧 landmarks（用于检测面部晃动）

        # 头部姿态平滑滤波（滑动窗口均值，窗口大小 5 帧 ≈ 0.17s @30fps）
        self._smooth_yaw: Deque[float] = deque(maxlen=5)
        self._smooth_pitch: Deque[float] = deque(maxlen=5)

        # 最新分析结果（用于渲染）
        self._latest_focus_result = None
        self._latest_fatigue_result = None
        self._latest_gaze_score = 100.0
        self._latest_light_result = None
        self._latest_glasses_result = None
        self._latest_yaw: float = 0.0  # 最新头部偏航角
        self._latest_pitch: float = 0.0  # 最新头部俯仰角
        self._latest_face_detected: bool = False  # 人脸是否检测到
        self._latest_ear: float = 0.0  # v4.12: 最新 EAR 值

        # 低光照自适应标志
        self._low_light_active: bool = False
        self._saved_adjustment_factor: float = 1.0

        # 头部离屏检测（v4.8: 头位偏离超过阈值时暂停分析）
        self._head_away_threshold_yaw: float = 20.0   # 横向偏离 > 20° → 离屏
        self._head_away_threshold_pitch: float = 25.0  # 低头 > 25° → 离屏
        self._head_away_start_time: Optional[float] = None
        self._cumulative_away_seconds: float = 0.0
        self._is_head_away: bool = False

        # 校准回调
        self._ear_callback: Optional[Callable[[], float]] = None
        self._head_pose_callback: Optional[Callable[[], tuple]] = None

    def process_frame(self, frame: np.ndarray) -> None:
        """处理单帧

        Args:
            frame: BGR 格式 OpenCV 图像
        """
        self._frame_count += 1
        timestamp_ms = int(time.time() * 1000)

        # 人脸检测
        face_result = self._face_detector.detect_from_frame(frame, timestamp_ms)
        self._latest_face_detected = face_result.face_detected

        if not face_result.face_detected:
            # v4.13: 人脸丢失 — 仍调用 analyze(face_detected=False) 获取冻结分数
            if self._focus_analyzer is not None:
                frozen = self._focus_analyzer.analyze(
                    ear=0.0, yaw=0.0, pitch=0.0,
                    gaze_score=self._latest_gaze_score,
                    face_detected=False,
                )
                self._latest_focus_result = frozen
            return

        landmarks = face_result.landmarks

        # 多信号融合：更新头部姿态历史并计算权重
        current_yaw = face_result.yaw or 0.0
        current_pitch = face_result.pitch or 0.0
        self._yaw_history.append(current_yaw)
        self._pitch_history.append(current_pitch)

        # 滑动窗口平滑滤波（抑制帧间跳变）
        self._smooth_yaw.append(current_yaw)
        self._smooth_pitch.append(current_pitch)
        smoothed_yaw = float(np.mean(self._smooth_yaw))
        smoothed_pitch = float(np.mean(self._smooth_pitch))

        # ── v4.8: 头部离屏检测 ──
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
            # 离屏计数器累加（每帧一次，用于总计时）
        else:
            if self._is_head_away:
                away_dur = time.time() - self._head_away_start_time
                self._cumulative_away_seconds += away_dur
                logger.info("头部回屏: 离线 %.1fs, 累计 %.1fs",
                            away_dur, self._cumulative_away_seconds)
                self._is_head_away = False
                self._head_away_start_time = None

        # 头部姿态晃动检测：yaw/pitch 变化剧烈时降低 head_pose_weight
        head_pose_weight = 1.0
        if len(self._yaw_history) >= 10:
            yaw_std = float(np.std(self._yaw_history))
            pitch_std = float(np.std(self._pitch_history))
            if yaw_std > 3.0 or pitch_std > 3.0:
                max_std = max(yaw_std, pitch_std, 3.0)
                head_pose_weight = max(0.5, 1.0 - (max_std - 3.0) / 10.0)
            else:
                head_pose_weight = 1.0

        # 面部稳定性检测：landmarks 连续帧间位移超阈值时降低 face_stability_weight
        face_stability_weight = 1.0
        if self._prev_landmarks is not None and self._prev_landmarks.shape == landmarks.shape:
            landmark_movement = float(np.linalg.norm(landmarks - self._prev_landmarks))
            if landmark_movement > 10.0:
                face_stability_weight = max(0.3, 1.0 - (landmark_movement - 10.0) / 50.0)
            else:
                face_stability_weight = 1.0
        self._prev_landmarks = landmarks.copy()

        # 保存头部姿态（平滑后）供校准回调使用
        self._latest_yaw = smoothed_yaw
        self._latest_pitch = smoothed_pitch

        # EAR 计算
        self._eye_detector.set_head_pose_weight(head_pose_weight)
        self._eye_detector.set_face_stability_weight(face_stability_weight)
        eye_result = self._eye_detector.compute(landmarks, blendshapes=face_result.blendshapes)
        self._latest_ear = eye_result.ear_avg  # v4.12: 记录最新 EAR

        # Per-frame calibration data collection (T155)
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

        # ── v4.8: 离屏时跳过专注度/疲劳分析 ──
        if self._is_head_away:
            # 保持最新结果不变（不更新），不写入记录
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

        # 疲劳分析 - 获取最近眨眼的 ear_nadir
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

        # 存储帧记录（节流：最多 15 FPS）
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

        # 存储眨眼事件（只写入新产生的）
        if self._db and self._session_id:
            blink_events = self._eye_detector.get_blink_events()
            # 只写入上次之后的新眨眼事件
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

        # 存储疲劳记录（节流：最多每秒一次）
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

        # 存储专注度记录（节流：每 30s 一次，供 insights pipeline 使用）
        if (self._db and self._session_id
                and self._latest_focus_result is not None
                and (current_time - self._last_focus_write_time) >= self._focus_write_interval):
            from storage.models import FocusRecord
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


class CalibrationFlowCallbacks:
    """校准流程回调实现"""

    def __init__(self, app: 'EyeFocusApp'):
        self.app = app
        self._input_buffer: str = ""
        self._input_mode: bool = False

    def on_phase_start(self, phase: int, phase_name: str, instruction: str) -> None:
        """阶段开始"""
        self.app._overlay.show_calibration_phase(phase, phase_name, instruction)
        self._input_mode = False
        self._input_buffer = ""

    def on_countdown_tick(self, remaining: int) -> None:
        """倒计时更新"""
        self.app._overlay.update_calibration_countdown(remaining)

    def on_detected_signals_update(self, ear: float, yaw: float, pitch: float) -> None:
        """信号更新"""
        pass

    def on_phase_complete(self, phase: int, collected_data: dict) -> None:
        """阶段完成"""
        self.app._overlay.show_phase_complete(phase)

    def on_blink_round_start(self, round_num: int, total_rounds: int, duration: int) -> None:
        """眨眼轮开始"""
        self.app._overlay.show_blink_round(round_num, total_rounds, duration)

    def on_blink_round_tick(self, remaining: int, detected_blinks: int) -> None:
        """眨眼轮更新"""
        self.app._overlay.update_blink_round(remaining, detected_blinks)

    def on_blink_round_end(self, round_num: int, program_count: int) -> None:
        """眨眼轮结束，等待输入"""
        self.app._overlay.show_blink_input(round_num, program_count)
        self._input_mode = True
        self._input_buffer = ""

    def on_calibration_complete(self, result: CalibrationResult) -> None:
        """校准完成"""
        self.app._overlay.show_calibration_result(result)
        self._input_mode = False
        self._apply_calibration_result(result)

    def on_error(self, phase: int, message: str) -> None:
        """错误"""
        logger.error("校准错误 [阶段 %d]: %s", phase, message)

    def on_digit_input(self, digit: str) -> None:
        """数字输入"""
        if self._input_mode:
            # 限制输入长度，避免缓冲区溢出
            if len(self._input_buffer) < 3:
                self._input_buffer += digit
            else:
                self._input_buffer = self._input_buffer[-2:] + digit
            # 同步更新 overlay 显示
            self.app._overlay.update_input_buffer(self._input_buffer)

    def on_enter_pressed(self) -> None:
        """确认输入"""
        if hasattr(self.app, '_calib_manager') and self.app._calib_manager:
            # 检查校准管理器是否处于 BLINK_INPUT 状态
            from analyzer.user_calibration import CalibrationState
            if self.app._calib_manager.state == CalibrationState.BLINK_INPUT:
                try:
                    count = int(self._input_buffer) if self._input_buffer else 0
                    self.app._calib_manager.on_user_input(count)
                except ValueError:
                    logger.warning("无效输入: %s", self._input_buffer)
                # 输入已提交，立即清空状态
                self._input_buffer = ""
                self._input_mode = False
                return

        # 如果不在 BLINK_INPUT 状态，清空输入
        self._input_buffer = ""
        self._input_mode = False

    def _apply_calibration_result(self, result: CalibrationResult) -> None:
        """应用校准结果到各模块"""
        if hasattr(self.app, '_eye_detector') and self.app._eye_detector:
            self.app._eye_detector.set_baseline(result.signal.ear_mean)

        if result.baseline_blink_rate is not None and self.app._fatigue_analyzer is not None:
            self.app._fatigue_analyzer.set_baseline_blink_rate(result.baseline_blink_rate)
            logger.info("疲劳基线已应用: %.1f 次/分钟", result.baseline_blink_rate)

        if self.app._db and self.app._session_id:
            self.app._db.update_session(
                self.app._session_id,
                baseline_ear=result.signal.ear_mean,
                baseline_blink_rate=result.baseline_blink_rate,
                is_calibrated=True,
            )

        logger.info("校准结果已应用: EAR=%.4f, 眨眼阈值=%.4f",
                    result.signal.ear_mean, result.final_blink_threshold)


class CalibrationCoordinator:
    """校准流程协调器 - 负责校准流程与 UI 的协调

    这个类封装了：
    - UserCalibrationManager 的生命周期管理（start/tick/cancel）
    - UI 输入处理（数字输入、确认）
    - 实时数据回调（EAR、头部姿态）提供给校准管理器

    注意：校准协议回调（on_phase_start 等）由 CalibrationFlowCallbacks
    实现并传递给 UserCalibrationManager，数据回调由本类设置。
    """

    def __init__(
        self,
        calib_manager: UserCalibrationManager,
        overlay: FocusOverlay,
        app: "EyeFocusApp",
        eye_detector: Optional[EyeAspectDetector] = None,
        db: Optional[DatabaseManager] = None,
        session_id: Optional[str] = None,
    ):
        self._calib_manager = calib_manager
        self._overlay = overlay
        self._app = app
        self._eye_detector = eye_detector
        self._db = db
        self._session_id = session_id

        # 输入状态
        self._input_buffer: str = ""
        self._input_mode: bool = False

        # tick 计时器
        self._last_tick_time: float = 0.0

        # 设置实时数据回调（供校准管理器采集数据用）
        self._calib_manager.set_ear_callback(self._get_ear)
        self._calib_manager.set_head_pose_callback(self._get_head_pose)

    def _get_ear(self) -> float:
        """获取当前 EAR 值"""
        if self._eye_detector:
            return self._eye_detector.get_current_ear()
        return 0.0

    def _get_head_pose(self) -> tuple:
        """获取当前头部姿态（从 FrameProcessor 获取）"""
        fp = self._app._frame_processor
        return (fp._latest_yaw, fp._latest_pitch)

    def start(self) -> None:
        """启动校准流程"""
        # 清空残留输入状态
        self._input_buffer = ""
        self._input_mode = False

        # 重置 tick 计时器
        self._last_tick_time = time.time()

        self._calib_manager.start()
        logger.info("校准流程已启动, state=%s", self._calib_manager.state)

    def tick(self) -> None:
        """定时器触发（每秒调用一次）"""
        if self._calib_manager.state == CalibrationState.IDLE:
            return

        current_time = time.time()
        if current_time - self._last_tick_time >= 1.0:
            self._calib_manager.tick()
            self._last_tick_time = current_time

    def cancel(self) -> None:
        """取消校准"""
        if self._calib_manager:
            self._calib_manager.on_cancel()
        self._overlay.hide_calibration_ui()
        # 清空输入状态
        self._input_buffer = ""
        self._input_mode = False
        logger.info("校准已取消")

    def is_active(self) -> bool:
        """检查校准流程是否在进行中"""
        return self._calib_manager.state != CalibrationState.IDLE

    @property
    def state(self) -> CalibrationState:
        """当前校准状态"""
        return self._calib_manager.state

    @property
    def input_mode(self) -> bool:
        """是否处于输入模式"""
        return self._input_mode

    def handle_digit_input(self, digit: str) -> None:
        """处理数字输入"""
        if self._input_mode:
            # 限制输入长度，避免缓冲区溢出
            if len(self._input_buffer) < 3:
                self._input_buffer += digit
            else:
                self._input_buffer = self._input_buffer[-2:] + digit
            # 同步更新 overlay 显示
            self._overlay.update_input_buffer(self._input_buffer)

    def handle_enter_pressed(self) -> None:
        """确认输入"""
        if self._calib_manager and self._calib_manager.state == CalibrationState.BLINK_INPUT:
            try:
                count = int(self._input_buffer) if self._input_buffer else 0
                self._calib_manager.on_user_input(count)
            except ValueError:
                logger.warning("无效输入: %s", self._input_buffer)
            # 输入已提交，立即清空状态
            self._input_buffer = ""
            self._input_mode = False
            return

        # 如果不在 BLINK_INPUT 状态，清空输入
        self._input_buffer = ""
        self._input_mode = False


class EyeFocusApp:
    """EyeFocus Insight 主应用类 (Facade)

    整合所有模块，提供统一的接口。
    实际工作委托给：
    - CameraManager: 摄像头采集
    - FrameProcessor: 帧处理流水线
    - CalibrationCoordinator: 校准流程协调
    """

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or AppConfig()

        # 状态标志
        self._running: bool = False
        # v4.3 修复: 重新引入 _paused (M-22 误删了字段但 _render_frame 还在引用)
        # P 键切换, 不与窗口拖动混淆 (cv2.waitKey 拖窗口时返回 255 不触发)
        self._paused: bool = False
        # v4.4: 追踪最后检测到人脸的时间, 用于无脸检测红底白字横条
        self._last_face_time: Optional[float] = None
        # 人脸丢失自动暂停标志
        self._auto_paused_for_face_loss: bool = False
        # v4.13: 历史校准加载状态
        self._calib_loaded: bool = False

        # 子组件（保持与测试兼容的属性名）
        self._camera_manager: Optional[CameraManager] = None
        self._frame_processor: Optional[FrameProcessor] = None
        self._calib_coordinator: Optional[CalibrationCoordinator] = None

        # 直接暴露的组件引用（保持与测试兼容）
        self._face_detector: Optional[FaceMeshDetector] = None
        self._eye_detector: Optional[EyeAspectDetector] = None
        self._gaze_detector: Optional[GazeDetector] = None
        self._light_detector: Optional[LightDetector] = None
        self._overlay: Optional[FocusOverlay] = None
        self._focus_analyzer: Optional[FocusAnalyzer] = None
        self._glasses_detector: Optional[GlassesDetector] = None
        self._fatigue_analyzer: Optional[FatigueAnalyzer] = None
        self._db: Optional[DatabaseManager] = None
        self._current_session: Optional[Session] = None
        self._session_id: Optional[str] = None

        # 帧统计
        self._fps: float = 0.0
        self._fps_start_time: float = 0.0
        self._fps_frame_count: int = 0

        # 信号处理
        self._original_sigint: Optional[object] = None
        self._original_sigterm: Optional[object] = None

        # 校准相关（保持与测试兼容）
        self._calib_manager: Optional[UserCalibrationManager] = None
        self._calib_callbacks: Optional[CalibrationFlowCallbacks] = None

        # v4.4 按键确认状态
        self._confirm_quit_pending: bool = False     # 第一次按 Q, 等待第二次确认
        self._confirm_quit_time: float = 0.0          # 第一次按 Q 的时间戳
        self._confirm_cancel_pending: bool = False    # 第一次按 ESC (校准中), 等待确认
        self._confirm_cancel_time: float = 0.0
        # 按键反馈消息 (显示在画面中央, 1.5s后消失)
        self._feedback_text: Optional[str] = None
        self._feedback_until: float = 0.0
        # v4.4: 校准取消/跳过提示 (显示5s)
        self._calib_cancelled_msg: Optional[str] = None
        self._calib_cancelled_until: float = 0.0

        # v4.4: Qt UI 模式
        self._frame_buffer = None
        self._qt_window = None

    def initialize(self) -> bool:
        """初始化所有模块

        Returns:
            True 如果初始化成功
        """
        logger.info("EyeFocus Insight 初始化中...")

        try:
            # 初始化数据库
            self._db = create_database_manager(
                db_path=f"{self.config.data_dir}/eyefocus.db"
            )
            self._db.initialize()

            # v4.17: 会话开始时间（供语音/提醒使用）
            self._session_start_time = time.time()

            # 创建新会话
            self._session_id = self._db.create_session()
            self._current_session = self._db.get_session(self._session_id)

            # 初始化检测器
            self._face_detector = create_face_mesh_detector()
            self._eye_detector = create_eye_aspect_detector()
            self._gaze_detector = create_gaze_detector()
            self._light_detector = create_light_detector()

            # 初始化 GUI 叠加层
            self._overlay = FocusOverlay()

            # 初始化分析器
            self._focus_analyzer = create_focus_analyzer()
            # v4.13: 尝试加载历史校准（避免每次启动都提示未校准）
            self._load_last_calibration()
            # v4.14: 设置会话开始时间（用于衰减因子）
            self._focus_analyzer.set_session_start(time.time())
            self._glasses_detector = create_glasses_detector()
            self._fatigue_analyzer = create_fatigue_analyzer()

            # 连接分析器与检测器
            self._focus_analyzer.set_blink_detector(self._eye_detector)
            self._fatigue_analyzer.start()

            # v4.17: 语音反馈助手（从 config.yaml 读取开关状态）
            from config import get_yaml_value
            voice_enabled = get_yaml_value("voice", "enabled", default=True)
            self._voice_asst = create_voice_assistant(enabled=voice_enabled)

            # v4.17: 智能提醒引擎（回调延迟绑定）
            self._reminder_engine = create_reminder_engine(
                tray_callback=self._reminder_tray_notify,
                voice_callback=lambda text: self._voice_asst.say(text) if self._voice_asst else None,
            )

            # v4.17: 游戏化引擎
            self._gamification = create_gamification_engine(db=self._db)

            # 初始化校准管理器
            self._calib_callbacks = CalibrationFlowCallbacks(self)
            self._calib_manager = create_user_calibration_manager(
                callbacks=self._calib_callbacks,
                session_id=self._session_id,
            )

            # 初始化子组件
            self._camera_manager = CameraManager(self.config.camera_index)
            self._frame_processor = FrameProcessor(
                face_detector=self._face_detector,
                eye_detector=self._eye_detector,
                gaze_detector=self._gaze_detector,
                light_detector=self._light_detector,
                glasses_detector=self._glasses_detector,
                focus_analyzer=self._focus_analyzer,
                fatigue_analyzer=self._fatigue_analyzer,
                calib_manager=self._calib_manager,
                is_calibration_active=lambda: self.is_calibration_flow_active(),
                db=self._db,
                session_id=self._session_id,
            )
            self._calib_coordinator = CalibrationCoordinator(
                calib_manager=self._calib_manager,
                overlay=self._overlay,
                app=self,
                eye_detector=self._eye_detector,
                db=self._db,
                session_id=self._session_id,
            )

            logger.info("初始化完成 (session: %s)", self._session_id)

            # v4.0.2 修复 B3: 提前验证摄像头可用，避免 main_loop 才报错
            # 用户启动后看到黑屏无错误提示的问题
            if not self._camera_manager.start():
                logger.error(
                    "初始化失败: 摄像头 (index=%d) 无法打开，请检查设备连接或修改 config.camera_index",
                    self.config.camera_index,
                )
                # 关闭已分配的资源
                self.shutdown()
                return False
            # 立即 stop，main_loop 会再 start
            self._camera_manager.stop()
            return True

        except Exception as e:
            logger.error("初始化失败: %s", e, exc_info=True)
            return False

    def start(self) -> None:
        """启动主循环"""
        if self._running:
            logger.warning("应用已在运行中")
            return

        self._running = True
        self._fps_start_time = time.time()

        # 注册信号处理器
        self._register_signal_handlers()

        # 自动开始校准（Qt 模式下由 _start_qt_monitoring 处理）
        if self.config.enable_calibration and not self.config.use_qt:
            self.start_calibration_flow()

        # 启动主循环 (Qt 或 OpenCV)
        if self.config.use_qt:
            self._start_qt_monitoring()
        else:
            self._main_loop()

    def _main_loop(self) -> None:
        """主循环"""
        # 启动摄像头
        if not self._camera_manager.start():
            logger.error("摄像头启动失败")
            return

        try:
            while self._running:
                # 处理 cv2 窗口事件（每帧都调用）
                key = cv2.waitKey(1) & 0xFF
                if key != 255 and key != 0:  # 0 = 无键事件(Win), 255 = 无键事件(Unix)
                    logger.debug("Key pressed: %d", key)

                # 获取最新帧
                ret, frame = self._camera_manager.get_frame()

                if ret and frame is not None:
                    self._frame_processor.process_frame(frame)
                    # v4.4: 追踪最后检测到人脸的时间 (用于无脸检测红底白字横条)
                    if self._frame_processor.latest_face_detected:
                        self._last_face_time = time.time()
                    # FrameProcessor 是帧处理的单一数据源（v4.0 重构）。
                    # _render_frame 直接通过公开属性访问最新结果，无需镜像。
                    self._render_frame(frame)
                    self._update_fps()
                else:
                    self._render_frame_placeholder()

                # 校准流程定时器
                self._process_calibration_tick()

                # 键盘处理
                self._handle_keyboard(key)

        finally:
            self._running = False
            self._camera_manager.release()
            cv2.destroyAllWindows()
            self._cleanup()

    def _render_frame_placeholder(self) -> None:
        """无帧时渲染占位符（保持窗口响应）"""
        if self._overlay:
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            display = self._overlay.draw(placeholder, focus_score=None, fatigue_level=None)
            # v4.4: 占位符也绘制按键提示和确认弹窗
            self._draw_key_hints(display)
            # v4.4: Q 用 1s 自动退出; ESC 用 5s 超时取消
            if self._confirm_quit_pending:
                # 1s 内无取消键则自动退出
                if time.time() - self._confirm_quit_time > 1.0:
                    self._running = False
                    self._confirm_quit_pending = False
                self._draw_confirmation_overlay(display, "按 Q 退出 (1秒)", 1.0, self._confirm_quit_time)
            elif self._confirm_cancel_pending:
                self._draw_confirmation_overlay(display, "再按 ESC 确认取消校准", 5.0, self._confirm_cancel_time)
            if self._feedback_text and time.time() < self._feedback_until:
                self._draw_feedback_text(display, self._feedback_text)
            cv2.imshow("EyeFocus Insight", display)

    def _process_calibration_tick(self) -> None:
        """处理校准流程定时器"""
        if self._calib_coordinator:
            old_state = self._calib_coordinator.state
            self._calib_coordinator.tick()
            new_state = self._calib_coordinator.state
            if old_state != new_state:
                logger.info("校准状态变化: %s -> %s", old_state, new_state)

    def _start_qt_monitoring(self) -> None:
        """v4.7: 使用 PyQt5 窗口 + Qt 校准对话框"""
        import sys
        from PyQt5.QtWidgets import QApplication
        from gui.qt_window import EyeFocusWindow, FrameBuffer

        # 创建帧缓冲区 (CameraManager 写入, Qt 显示读取)
        self._frame_buffer = FrameBuffer()

        # 启动摄像头
        if not self._camera_manager.start():
            logger.error("Qt 模式: 摄像头启动失败")
            return

        # 帧健康计时
        self._last_valid_frame_time = time.time()
        self._first_frame_logged = False

        # ⚠️ QApplication 只能创建一次
        self._qt_app = QApplication(sys.argv)

        # ── Qt 校准对话框（自有摄像头，释放后等待足够时间）──
        if self.config.enable_calibration:
            self._camera_manager.release()
            import time as _wt; _wt.sleep(2.0)  # 等待驱动完全释放
            from gui.calibration_dialog import run_calibration_dialog
            calib_result = run_calibration_dialog(
                fd=self._face_detector, ed=self._eye_detector)
            if calib_result:
                self._apply_qt_calibration_result(calib_result)
            else:
                logger.info("校准被取消或失败，使用默认参数")
            # 重新启动摄像头
            if not self._camera_manager.start():
                logger.error("校准后摄像头重启失败")
                return
            # 重置帧健康计时
            self._last_valid_frame_time = time.time()
            self._first_frame_logged = False

        # 创建主窗口 (v4.10: 传入 enable_tray + app_ref 支持系统托盘)
        self._qt_window = EyeFocusWindow(
            self._frame_buffer,
            enable_tray=self.config.enable_tray,
            app_ref=self,
        )
        # v4.13: 已加载历史校准 → 隐藏未校准提示
        if getattr(self, '_calib_loaded', False):
            self._qt_window.set_calibration_prompt(False)

        # 初始化人脸丢失计时（Qt 模式下也需要跟踪）
        self._last_face_time = time.time()

        # 连接退出信号
        self._qt_window.exit_requested.connect(self._on_qt_exit)

        # 连接校准信号（复用 Qt 对话框）
        self._qt_window.calibrate_requested.connect(self._on_qt_calibrate)

        # 卡死防护：帧跳过守卫
        self._qt_frame_busy = False

        # 设置定时器驱动帧处理 (30fps)
        from PyQt5.QtCore import QTimer
        self._qt_timer = QTimer()
        self._qt_timer.timeout.connect(self._qt_process_frame)
        self._qt_timer.start(33)  # ~30fps

        # 校准取消消息
        if self._calib_cancelled_msg:
            self._calib_cancelled_msg = None

        # 显示窗口并启动事件循环
        self._qt_window.show()
        self._qt_window.start()
        self._qt_app.exec_()

        # 事件循环结束后清理
        logger.info("Qt 事件循环结束")
        self._running = False
        self._qt_timer.stop()
        self._camera_manager.release()
        self._cleanup()

    def _load_last_calibration(self) -> None:
        """v4.13: 从数据库加载最近一次校准数据，避免每次启动提示未校准。"""
        if self._db is None:
            return
        try:
            with self._db._get_cursor() as cur:
                cur.execute(
                    "SELECT baseline_ear, baseline_yaw_std, baseline_pitch_std "
                    "FROM sessions WHERE is_calibrated=1 AND baseline_ear IS NOT NULL "
                    "ORDER BY start_time DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row and row[0] is not None and row[0] > 0:
                    ear = float(row[0])
                    yaw_std = float(row[1]) if row[1] else None
                    pitch_std = float(row[2]) if row[2] else None
                    if self._focus_analyzer is not None:
                        self._focus_analyzer.set_baseline(ear, yaw_std, pitch_std)
                    if self._eye_detector is not None:
                        self._eye_detector.set_baseline(ear)
                    self._calib_loaded = True
                    logger.info("已加载历史校准: EAR=%.4f", ear)
                    return
        except Exception as e:
            logger.debug("加载历史校准失败（可能无历史数据）: %s", e)
        self._calib_loaded = False

    def _apply_qt_calibration_result(self, calib_result: dict) -> None:
        """应用 Qt 校准对话框的结果到各 detector。"""
        baseline_ear = calib_result.get("baseline_ear", 0.25)
        head_yaw = calib_result.get("head_yaw_range", 0.0)
        head_pitch = calib_result.get("head_pitch_range", 0.0)

        if self._eye_detector is not None:
            self._eye_detector.set_baseline(baseline_ear)
            logger.info("Qt 校准 EAR 基线已应用: %.4f", baseline_ear)

        if self._focus_analyzer is not None:
            self._focus_analyzer.set_baseline(
                ear=baseline_ear,
                yaw_std=head_yaw / 2.0 if head_yaw > 0 else None,
                pitch_std=head_pitch / 2.0 if head_pitch > 0 else None,
            )
            logger.info("Qt 校准专注度基线已应用: EAR=%.4f, yaw=%.1f, pitch=%.1f",
                        baseline_ear, head_yaw, head_pitch)

        if self._db and self._session_id:
            self._db.update_session(
                self._session_id,
                baseline_ear=baseline_ear,
                is_calibrated=True,
            )

        # v4.13: 校准完成后标记已校准 + 隐藏提示
        self._calib_loaded = True
        if self._qt_window is not None:
            self._qt_window.set_calibration_prompt(False)

    def _on_qt_calibrate(self) -> None:
        """Qt 窗口校准按钮处理"""
        logger.info("校准按钮点击 (Qt 模式)")

        # v4.16: 防止重复进入校准
        if getattr(self, '_calibrating', False):
            logger.warning("校准已在进行中，忽略重复请求")
            return
        self._calibrating = True

        self._qt_window.set_paused(True)
        try:
            self._camera_manager.release()
            import time as _wt; _wt.sleep(2.0)
            from gui.calibration_dialog import run_calibration_dialog
            calib_result = run_calibration_dialog(
                fd=self._face_detector, ed=self._eye_detector)
            if calib_result:
                self._apply_qt_calibration_result(calib_result)
            if not self._camera_manager.start():
                logger.error("校准后摄像头重启失败")
        except Exception as e:
            logger.error("校准过程异常: %s", e)
            import traceback
            traceback.print_exc()
        finally:
            self._calibrating = False
            self._qt_window.set_paused(False)

    def _qt_process_frame(self) -> None:
        """Qt 定时器回调: 处理一帧"""
        if not self._camera_manager or not self._camera_manager.is_running:
            return

        # 信号退出检测（Qt事件循环中 Ctrl+C 不生效，通过此途径检测 _running 标志）
        if not self._running:
            logger.info("Qt 模式检测到退出信号，退出事件循环")
            self._qt_app.quit()
            return

        # 卡死防护：上一帧还在处理中 → 跳过
        if self._qt_frame_busy:
            return
        self._qt_frame_busy = True

        try:
            ret, frame = self._camera_manager.get_frame()

            # 帧健康检测：无帧超过 5s 时只打日志（不重启，避免干扰摄像头初始化）
            if not ret or frame is None:
                now = time.time()
                last = getattr(self, '_last_valid_frame_time', 0)
                if last > 0 and now - last > 5.0 and not getattr(self, '_cam_health_warned', False):
                    self._cam_health_warned = True
                    logger.warning("Qt 模式: 摄像头已 %ds 无有效帧", int(now - last))
                return
            self._cam_health_warned = False

            # 有效帧到达
            self._last_valid_frame_time = time.time()

            # 第一帧日志
            if not getattr(self, '_first_frame_logged', False):
                self._first_frame_logged = True
                logger.info("Qt 模式: 首帧到达 (%d×%d)", frame.shape[1], frame.shape[0])

            # 处理帧 (检测+分析)
            self._frame_processor.process_frame(frame)

            # 直接推送帧到窗口显示（绕过 FrameBuffer timer 时序依赖）
            if hasattr(self, '_qt_window') and self._qt_window is not None:
                self._qt_window.show_frame(frame)

            # 更新 Qt 窗口的数据面板（圆环 + 卡片）
            if hasattr(self, '_qt_window') and self._qt_window is not None:
                # v4.17: 修复专注时长一直显示 "--" 的问题
                elapsed_min = (time.time() - self._session_start_time) / 60.0 if self._session_start_time else 0.0
                self._frame_processor.focus_duration_minutes = elapsed_min
                self._qt_window.update_data_from_processor(self._frame_processor, self._fps)

            # FPS
            self._update_fps()

            # 追踪最后检测到人脸的时间
            if self._frame_processor.latest_face_detected:
                self._last_face_time = time.time()

            # 人脸丢失 > 10s 自动暂停
            if not self._frame_processor.latest_face_detected and self._last_face_time is not None:
                lost_duration = time.time() - self._last_face_time
                if lost_duration > 10.0 and not self._qt_window.is_paused():
                    logger.info("人脸丢失 %.1fs → 自动暂停监测", lost_duration)
                    self._qt_window.set_paused(True)
                    self._qt_window.set_face_lost_warning(True)
                    self._auto_paused_for_face_loss = True
            # 人脸恢复 → 自动继续（仅限因丢失自动暂停的情况）
            elif self._frame_processor.latest_face_detected:
                if getattr(self, '_auto_paused_for_face_loss', False):
                    self._auto_paused_for_face_loss = False
                    self._qt_window.set_paused(False)
                    self._qt_window.set_face_lost_warning(False)
                    logger.info("人脸恢复 → 自动继续监测")

            # v4.10: 疲劳通知 (仅当启用托盘且非免打扰)
            if (hasattr(self, '_qt_window') and self._qt_window is not None
                    and getattr(self, '_frame_processor', None) is not None):
                fa = self._frame_processor.latest_fatigue_result
                if fa is not None:
                    level = fa.fatigue_level
                    level_str = level.value.upper() if hasattr(level, 'value') else str(level)
                    if level_str == 'HIGH':
                        # 每 60s 最多提醒一次，避免刷屏
                        now = time.time()
                        last = getattr(self, '_last_fatigue_notify_time', 0)
                        if now - last >= 60:
                            self._last_fatigue_notify_time = now
                            cumulative = getattr(fa, 'cumulative_fatigue_score', 0)
                            self._qt_window.show_fatigue_notification(
                                f"累积疲劳分数 {cumulative:.0f}，建议休息10-15分钟")

            # v4.17: 语音反馈 + 智能提醒
            fr = self._frame_processor.latest_focus_result
            fa = self._frame_processor.latest_fatigue_result
            focus_score = fr.focus_score if fr else 50.0
            focus_level = fr.focus_level.value if (fr and fr.focus_level) else None
            fatigue_level = None
            session_min = 0.0
            if fa is not None:
                fl = fa.fatigue_level
                fatigue_level = fl.value.upper() if hasattr(fl, 'value') else str(fl)
            if hasattr(self, '_session_start_time') and self._session_start_time:
                session_min = (time.time() - self._session_start_time) / 60.0

            if hasattr(self, '_voice_asst') and self._voice_asst is not None:
                self._voice_asst.on_tick(
                    focus_score=focus_score,
                    fatigue_level=fatigue_level,
                    session_minutes=session_min,
                    face_detected=self._frame_processor.latest_face_detected,
                )

            if hasattr(self, '_reminder_engine') and self._reminder_engine is not None:
                self._reminder_engine.check(
                    focus_score=focus_score,
                    focus_level=focus_level,
                    fatigue_level=fatigue_level,
                    session_minutes=session_min,
                    face_detected=self._frame_processor.latest_face_detected,
                )

            # v4.17: 专注度波线更新（每秒一次）
            spark_time = getattr(self, '_spark_update_time', 0)
            if time.time() - spark_time >= 1.0:
                self._spark_update_time = time.time()
                if hasattr(self, '_qt_window') and self._qt_window is not None:
                    self._qt_window.update_sparkline(focus_score)

            # v4.17: 游戏化状态更新（每 60s 一次，避免频繁 DB 查询）
            gamify_update = getattr(self, '_gamify_update_time', 0)
            if time.time() - gamify_update >= 60:
                self._gamify_update_time = time.time()
                if (hasattr(self, '_gamification') and self._gamification is not None
                        and hasattr(self, '_qt_window') and self._qt_window is not None):
                    streak = self._gamification.get_streak_days()
                    today_min = self._gamification.get_today_minutes()
                    self._qt_window.update_gamification(streak, today_min)
        finally:
            self._qt_frame_busy = False

    def _tray_cleanup(self) -> None:
        """v4.16: 强制清理托盘图标（应对程序异常退出时图标残留）"""
        try:
            if hasattr(self, '_qt_window') and self._qt_window is not None:
                if hasattr(self._qt_window, '_tray_icon') and self._qt_window._tray_icon is not None:
                    self._qt_window._tray_icon.hide()
                    self._qt_window._tray_icon = None
                    logger.debug("托盘图标已强制移除")
        except Exception as e:
            logger.debug("托盘图标移除异常 (忽略): %s", e)

    def _on_qt_exit(self) -> None:
        """Qt 退出信号处理"""
        logger.info("用户请求退出 (Qt)")
        # 先移除托盘图标，避免残留在系统托盘中
        if hasattr(self, '_qt_window') and self._qt_window is not None:
            if hasattr(self._qt_window, '_tray_icon') and self._qt_window._tray_icon is not None:
                self._qt_window._tray_icon.hide()
                logger.info("托盘图标已移除")
        self._qt_app.quit()

    def _handle_keyboard(self, key: int) -> None:
        """处理键盘输入

        Q 退出(按Q→"正在退出"→1s后退出, 按其他键取消)
        ESC 取消校准(二次确认) | C 校准 | P 暂停 | Tab 面板
        """
        now = time.time()

        # --- Q 处理 (最高优先级) ---
        if key == ord('q') or key == ord('Q'):
            if self._confirm_quit_pending:
                # 第二次按 Q → 立即退出
                logger.info("用户退出 (Q)")
                self._running = False
                self._confirm_quit_pending = False
            else:
                # 第一次按 Q → 启动 1s 倒计时
                self._confirm_quit_pending = True
                self._confirm_quit_time = now
                self._set_feedback("按 Q 退出... (1秒内按其他键取消)")
            return

        # 在 Q 倒计时中按了其他键 → 取消退出
        # ⚠️ key=255 (无按键) 时不取消, 否则每帧清 pending, 1s自动退出永不触发
        if self._confirm_quit_pending and key != 255 and key != 0:
            self._confirm_quit_pending = False
            self._set_feedback("已取消退出")
            # 不 return, 让其他按键处理继续（如 ESC 取消校准）

        # --- ESC 取消校准 (二次确认) ---
        if self._confirm_cancel_pending:
            if key == 27:
                logger.info("用户确认取消校准 (ESC×2)")
                self._confirm_cancel_pending = False
                self._cancel_calibration()
                self._set_feedback("校准已取消")
            else:
                self._confirm_cancel_pending = False
                self._set_feedback("已取消操作")
            return

        if key == 27:
            if self._calib_coordinator and (self._calib_coordinator.is_active()
                                           or self._calib_coordinator.input_mode):
                self._confirm_cancel_pending = True
                self._confirm_cancel_time = now
                self._set_feedback("再按 ESC 确认取消校准")
            return

        # 数字键和 Enter（仅在校准输入模式）
        if self._calib_coordinator and self._calib_coordinator.input_mode:
            if 48 <= key <= 57:
                digit = str(key - 48)
                self._calib_coordinator.handle_digit_input(digit)
                self._set_feedback(f"输入: {digit}")
            elif key == 13 or key == 10:
                self._calib_coordinator.handle_enter_pressed()
                self._set_feedback("已确认")
            return

        # C 键：启动校准
        if key == ord('c') or key == ord('C'):
            if self._calib_coordinator and not self._calib_coordinator.is_active():
                self.start_calibration_flow()
                self._set_feedback("启动校准...")
            return

        # P 键或空格：切换暂停
        if key == ord('p') or key == ord('P') or key == 32:
            self._paused = not self._paused
            state = "PAUSED" if self._paused else "RESUMED"
            logger.info("用户切换暂停: %s", state)
            self._set_feedback("⏸ 已暂停" if self._paused else "▶ 已恢复")
            return

        # Tab 键：切换极简/完整模式
        if key == 9:
            if hasattr(self._overlay, 'toggle_mode'):
                self._overlay.toggle_mode()
                self._set_feedback("面板切换")
            return

    def toggle_pause(self) -> None:
        """对外 API: 切换暂停 (供 GUI 按钮或测试用)"""
        self._paused = not self._paused
        logger.info("暂停状态: %s", "PAUSED" if self._paused else "RESUMED")

    def _render_frame(self, frame: np.ndarray) -> None:
        """渲染帧到窗口

        Args:
            frame: BGR 格式 OpenCV 图像
        """
        # 从 FrameProcessor 公开属性读取最新分析结果（v4.0 重构：单一数据源）
        focus_result = self._frame_processor.latest_focus_result
        fatigue_result = self._frame_processor.latest_fatigue_result
        light_result = self._frame_processor.latest_light_result
        glasses_result = self._frame_processor.latest_glasses_result
        face_detected = self._frame_processor.latest_face_detected

        # 构建校准进度
        calibration_progress = None
        if self.is_calibration_flow_active():
            # 校准流程 UI 由 FocusOverlay 内部处理
            # 这里传入 None 让 overlay 使用 CalibrationPhaseInfo 显示
            calibration_progress = None

        # 获取疲劳等级字符串
        fatigue_level_str = None
        if fatigue_result is not None:
            level = fatigue_result.fatigue_level
            fatigue_level_str = level.value.upper() if hasattr(level, 'value') else str(level)

        # 获取专注度分量
        eye_score = None
        head_score = None
        gaze_score_val = None
        focus_score_val = None
        if focus_result is not None:
            focus_score_val = focus_result.focus_score
            eye_score = focus_result.eye_score
            head_score = focus_result.head_score
            gaze_score_val = focus_result.gaze_score

        # 获取光照条件字符串
        light_condition_str = None
        if light_result is not None:
            light_condition_str = light_result.condition.value.upper()

        # 获取眼镜模式字符串
        glasses_str = None
        if glasses_result is not None:
            if glasses_result.is_glasses:
                glasses_str = "ON"
            else:
                glasses_str = "OFF"

        # v4.3: 设置顶层 MODE (CALIBRATING / MONITORING / PAUSED)
        if self.is_calibration_flow_active():
            self._overlay.set_mode("CALIBRATING")
        elif self._paused:
            self._overlay.set_mode("PAUSED")
        else:
            self._overlay.set_mode("MONITORING")

        # 使用 FocusOverlay 渲染 (v4.3: glasses + fps 传入, 不再外部 putText)
        display = self._overlay.draw(
            frame,
            focus_score=focus_score_val,
            fatigue_level=fatigue_level_str,
            eye_detected=face_detected,
            face_detected=face_detected,
            light_condition=light_condition_str,
            calibration=calibration_progress,
            eye_score=eye_score,
            head_score=head_score,
            gaze_score=gaze_score_val,
            glasses_str=glasses_str,
            fps=self._fps,
            last_face_time=self._last_face_time,  # v4.4: 无脸横幅
        )

        # v4.4: 底栏快捷键提示
        self._draw_key_hints(display)

        # v4.4: 按键确认弹窗 (Q退出 / ESC取消校准)
        if self._confirm_quit_pending:
            # 1s 内无取消键则自动退出
            if time.time() - self._confirm_quit_time > 1.0:
                self._running = False
                self._confirm_quit_pending = False
            self._draw_confirmation_overlay(display, "按 Q 退出 (1秒)", 1.0, self._confirm_quit_time)
        elif self._confirm_cancel_pending:
            self._draw_confirmation_overlay(display, "再按 ESC 确认取消校准", 5.0, self._confirm_cancel_time)

        # v4.4: 按键反馈文字
        if self._feedback_text and time.time() < self._feedback_until:
            self._draw_feedback_text(display, self._feedback_text)

        # v4.4: 校准取消/跳过提示
        if self._calib_cancelled_msg and time.time() < self._calib_cancelled_until:
            h, w = display.shape[:2]
            (tw, th), _ = cv2.getTextSize(self._calib_cancelled_msg, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            cv2.putText(display, self._calib_cancelled_msg, ((w - tw) // 2, h - 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
        elif self._calib_cancelled_msg and time.time() >= self._calib_cancelled_until:
            self._calib_cancelled_msg = None

        # 当人脸未检测到时，显示明确提示 (校准期间)
        if not face_detected and self.is_calibration_flow_active():
            cv2.putText(
                display,
                "请将面部对准摄像头",
                (display.shape[1] // 2 - 150, display.shape[0] // 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 255),
                2,
            )

        cv2.imshow("EyeFocus Insight", display)

    def _update_fps(self) -> None:
        """更新 FPS 计数"""
        self._fps_frame_count += 1
        elapsed = time.time() - self._fps_start_time

        if elapsed >= 1.0:
            self._fps = self._fps_frame_count / elapsed
            self._fps_frame_count = 0
            self._fps_start_time = time.time()

    # ============ v4.4 按键提示与反馈 ============

    def _draw_key_hints(self, frame: np.ndarray) -> None:
        """底栏快捷键提示 (半透明底条)"""
        h, w = frame.shape[:2]
        hints = "[Q]退出  [C]校准  [P]暂停  [Tab]面板"
        (tw, th), _ = cv2.getTextSize(hints, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        bar_h = th + 16
        # 半透明底条
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, h - bar_h), (w, h), (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, dst=frame)
        cv2.putText(frame, hints, (12, h - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (140, 140, 140), 1)

    def _draw_confirmation_overlay(self, frame: np.ndarray, msg: str,
                                    timeout: float, start_time: float) -> None:
        """按键确认覆盖层 (半透明背景 + 居中文字)"""
        elapsed = time.time() - start_time
        if elapsed > timeout:
            # 超时自动取消确认
            self._confirm_quit_pending = False
            self._confirm_cancel_pending = False
            return
        h, w = frame.shape[:2]
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, dst=frame)
        # 倒计时圆环 (3→0秒)
        remaining = max(0, int(timeout - elapsed))
        (tw, th), _ = cv2.getTextSize(msg, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        cv2.putText(frame, msg, ((w - tw) // 2, h // 2 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
        cv2.putText(frame, f"{remaining}s", ((w - 30) // 2, h // 2 + 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

    def _draw_feedback_text(self, frame: np.ndarray, text: str) -> None:
        """按键反馈文字 (屏幕中央闪过)"""
        if time.time() >= self._feedback_until:
            self._feedback_text = None
            return
        h, w = frame.shape[:2]
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        x = (w - tw) // 2
        y = h // 2 + 60  # 底部确认弹窗上方
        # 半透明背景
        overlay = frame.copy()
        cv2.rectangle(overlay, (x - 10, y - th - 10), (x + tw + 10, y + 10), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, dst=frame)
        cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    def _set_feedback(self, text: str, duration: float = 1.5) -> None:
        """设置按键反馈文字 (自动过期)"""
        self._feedback_text = text
        self._feedback_until = time.time() + duration

    def start_calibration_flow(self) -> bool:
        """启动用户校准流程

        2026-06-05 v4.3 集成: 按 config.calibration_mode 分发:
          - "v4_2" (默认): 调 run_v4_2_calibration() 接管摄像头 + UI + 音频
          - "v3_x": 调 _calib_coordinator.start() 走旧 UserCalibrationManager
        """
        mode = getattr(self.config, "calibration_mode", "v4_2")
        if mode == "v4_2":
            # v4.2 路径: 释放主程序摄像头让 calibration 模块独占, 完成后重启
            logger.info("校准流程启动 [mode=v4_2]: 调 calibration.run()")
            result = self.run_v4_2_calibration()
            if result is not None:
                logger.info("v4.2 校准成功: CQS=%.2f", result.cqs)
            else:
                logger.info("v4.2 校准被取消/失败, 使用默认基线")
                # v4.4: 显示提示
                self._calib_cancelled_msg = "未校准 — 使用默认参数监测中"
                self._calib_cancelled_until = time.time() + 5.0
            return result is not None

        # v3.x 兼容路径 (deprecated, 仅作为 fallback)
        logger.warning("校准流程启动 [mode=v3_x]: 走旧 UserCalibrationManager, "
                       "HEAD 姿态只 UP, 跳过 DOWN/LEFT/RIGHT, 建议改 config.calibration_mode='v4_2'")
        if self._calib_coordinator is None:
            logger.error("校准协调器未初始化")
            return False
        self._calib_coordinator.start()
        return True

    def _cancel_calibration(self) -> None:
        """取消校准"""
        if self._calib_coordinator:
            self._calib_coordinator.cancel()
        logger.info("校准已取消")

    def is_calibration_flow_active(self) -> bool:
        """检查校准流程是否在进行中"""
        if self._calib_coordinator is not None:
            return self._calib_coordinator.is_active()
        # 向后兼容：直接检查 _calib_manager
        if self._calib_manager is not None:
            return self._calib_manager.state != CalibrationState.IDLE
        return False

    def _register_signal_handlers(self) -> None:
        """注册信号处理器"""
        self._original_sigint = signal.signal(signal.SIGINT, self._signal_handler)
        self._original_sigterm = signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame) -> None:
        """信号处理

        H-01: 不在 signal handler 内调 self.shutdown() (内含 0.5s 阻塞 + 写盘 + 资源清理,
        异步不安全). 改为仅设 flag, 由 main_loop finally 块统一调 shutdown().
        M-22: 移除 _shutdown_event 死代码 (从未被 main_loop 读取, 仅 set 无用).
        """
        logger.info("收到信号 %d，准备退出...", signum)
        self._running = False

    def shutdown(self) -> None:
        """安全关闭应用

        M-20: _cleanup_done 标志防止 main_loop finally + shutdown() 双重清理.
        第二次 shutdown() 调用直接 return, 不重复 update_session / sleep / _cleanup.
        """
        if getattr(self, '_cleanup_done', False):
            return

        if not self._running:
            return

        logger.info("正在关闭...")
        self._running = False

        # 结束会话
        if self._db and self._session_id:
            self._db.update_session(
                self._session_id,
                end_time=datetime.now(),
                is_active=False,
            )

        # 等待主循环结束
        time.sleep(0.5)

        # 清理资源
        self._cleanup()

        # M-20: 标记已清理, 防止重复
        self._cleanup_done = True

        logger.info("已安全退出")

    # ── v4.17: 提醒引擎托盘回调 ──

    def _reminder_tray_notify(self, title: str, message: str) -> None:
        """提醒引擎的托盘通知回调（延迟绑定，运行时再取托盘引用）"""
        try:
            if hasattr(self, '_qt_window') and self._qt_window is not None:
                if hasattr(self._qt_window, '_tray_icon') and self._qt_window._tray_icon is not None:
                    self._qt_window._tray_icon.showMessage(
                        title, message,
                        self._qt_window._tray_icon.Information,
                        5000,
                    )
        except Exception:
            pass

    def _finalize_session(self) -> None:
        """结束当前会话并生成含 insights 的 HTML 报告。

        必须在 DB 关闭前调用。
        """
        if not self._db or not getattr(self, '_session_id', None):
            return

        try:
            # 0. 打印离屏统计
            if getattr(self, '_frame_processor', None) is not None:
                away = self._frame_processor.away_seconds
                if away > 0:
                    logger.info("会话离屏统计: 共 %.1f 秒", away)

            # 1. 更新会话结束时间
            self._db.update_session(
                self._session_id,
                end_time=datetime.now(),
                is_active=False,
            )

            # v4.17: 游戏化 - 更新每日统计与成就
            if hasattr(self, '_gamification') and self._gamification is not None:
                session = self._db.get_session(self._session_id)
                fr = self._frame_processor.latest_focus_result
                avg_focus = fr.focus_score if fr and fr.focus_score else 50.0
                new_ach = self._gamification.on_session_end(session, avg_focus)
                if new_ach:
                    names = ", ".join(f"{a.icon} {a.name}" for a in new_ach)
                    logger.info("🏅 新成就: %s", names)

            # 2. 生成含 insights 的 HTML 报告
            from reporter.report_html import create_html_generator
            import os

            generator = create_html_generator(self._db)
            html = generator.generate_report_with_insights(self._session_id)

            os.makedirs("reports", exist_ok=True)
            report_path = f"reports/{self._session_id}.html"
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(html)

            logger.info("会话报告已生成: %s", report_path)
        except Exception as e:
            logger.warning("生成会话报告失败: %s", e)

    def _cleanup(self) -> None:
        """清理资源

        顺序: 结束会话+生成报告 → 关闭检测器 → 关闭数据库.

        M-23: db.close() 也用 try/except + logger.exception 包裹 (与 face_detector.close() 一致).
        所有 close 异常累加到 _cleanup_errors 计数.
        """
        # 初始化错误计数 (供 M-23 累加)
        if not hasattr(self, '_cleanup_errors'):
            self._cleanup_errors = 0

        # 结束会话并生成报告（必须在 DB 关闭前）
        self._finalize_session()

        # v4.16: 强制移除托盘图标
        self._tray_cleanup()

        # v4.17: 关闭语音助手
        if hasattr(self, '_voice_asst') and self._voice_asst is not None:
            self._voice_asst.shutdown()

        # 恢复信号处理器
        if self._original_sigint:
            signal.signal(signal.SIGINT, self._original_sigint)
        if self._original_sigterm:
            signal.signal(signal.SIGTERM, self._original_sigterm)

        # 关闭检测器 — H-13: 异常用 logger.exception 记录完整 traceback
        if self._face_detector:
            try:
                self._face_detector.close()
            except Exception as e:
                self._cleanup_errors += 1
                logger.exception("FaceDetector.close() 异常: %s", e)

        # 关闭数据库 — M-23: 与 face_detector.close() 异常处理一致
        if self._db:
            try:
                self._db.close()
            except Exception as e:
                self._cleanup_errors += 1
                logger.exception("DatabaseManager.close() 异常: %s", e)

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running

    @property
    def is_calibrating(self) -> bool:
        """是否正在校准"""
        return self.is_calibration_flow_active()

    @property
    def fps(self) -> float:
        """当前 FPS"""
        return self._fps

    @property
    def session_id(self) -> Optional[str]:
        """当前会话 ID"""
        return self._session_id

    # ============ v4.2 新校准模块入口 ============

    def run_v4_2_calibration(self) -> Optional[CalibrationResult]:
        """v4.2: 调用新独立 calibration 模块（接管摄像头 + 自有 UI + 自有音频）。

        严格契约（spec 决策 X1）：成功 → 返回完整 CalibrationResult；取消/失败 → 返回 None。

        M-21: 显式传入 AppConfig.camera_index / frame 尺寸, 避免校准用默认 0 摄像头
        与主程序用户配置的外接摄像头不一致.

        Returns:
            CalibrationResult: 校准成功且用户在总结页确认
            None: 用户取消、阶段失败放弃、模块崩溃
        """
        logger.info("v4.2 校准模块启动 - 释放主程序摄像头")
        # 释放主程序摄像头 → 新模块独占
        if self._camera_manager is not None and self._camera_manager.is_running:
            self._camera_manager.release()

        # M-21: 构造 calibration Config, 显式传入主程序摄像头参数
        from calibration.config import CalibrationConfig
        calib_config = CalibrationConfig(
            camera_index=self.config.camera_index,
            frame_width=self.config.frame_width,
            frame_height=self.config.frame_height,
        )

        try:
            result = calibration_module.run(
                session_id=self._session_id or "main_session",
                config=calib_config,
                db=self._db,
            )
            # v4.4: 立即创建主窗口占位, 避免窗口切换黑屏
            cv2.namedWindow("EyeFocus Insight", cv2.WINDOW_AUTOSIZE)
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "正在启动监测模式...", (180, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.imshow("EyeFocus Insight", placeholder)
            cv2.waitKey(1)
            # v4.4: 用户点 × 关闭校准窗口 → 退出整个程序
            if result is None and calibration_module.is_exit_requested():
                logger.info("用户关闭校准窗口, 退出程序")
                self._running = False
                return None
            if result is not None:
                logger.info(
                    "v4.2 校准成功: EAR=%.4f, 眨眼率=%.2f/min, CQS=%.2f",
                    result.signal.ear_mean,
                    result.baseline_blink_rate,
                    result.cqs,
                )
                # 应用阈值到各 detector
                self._apply_v4_2_calibration_result(result)
            else:
                logger.info("v4.2 校准被用户取消或失败，使用默认基线")
            return result
        except Exception as e:
            logger.exception("v4.2 校准模块异常: %s", e)
            return None
        finally:
            # 重新获取主程序摄像头
            logger.info("v4.2 校准结束 - 重新启动主程序摄像头")
            if self._camera_manager is not None and not self._camera_manager.is_running:
                # H-12: 包 try/except 防止 finally 抛异常替换 try 块原始异常
                # 同时检查 start() 返回值
                try:
                    restart_ok = self._camera_manager.start()
                    if not restart_ok:
                        logger.error(
                            "v4.2 校准后重新启动主程序摄像头失败, "
                            "后续 main_loop 可能无法获取视频流"
                        )
                except Exception as restart_err:
                    logger.exception(
                        "v4.2 校准后重启主程序摄像头异常: %s", restart_err
                    )

    def _apply_v4_2_calibration_result(self, result: CalibrationResult) -> None:
        """应用 v4.2 校准结果到各 detector。"""
        if hasattr(self, '_eye_detector') and self._eye_detector is not None:
            self._eye_detector.set_baseline(result.signal.ear_mean)
            # P0: 接通 final_adjustment_factor (基于眨眼计数校准的检测误差补偿)
            if hasattr(self._eye_detector, 'set_adjustment_factor'):
                self._eye_detector.set_adjustment_factor(result.final_adjustment_factor)

        # P1: 头部姿态参数接通 — 让 focus_analyzer 的 head_score 反映用户的真实头动范围
        if (hasattr(self, '_focus_analyzer') and self._focus_analyzer is not None
                and hasattr(self._focus_analyzer, 'set_baseline')):
            from calibration.result import signal_to_head_pose_std
            yaw_std, pitch_std = signal_to_head_pose_std(result.signal)
            self._focus_analyzer.set_baseline(result.signal.ear_mean, yaw_std, pitch_std)
            logger.info("专注度基线已应用: EAR=%.4f, yaw_std=%.2f, pitch_std=%.2f",
                        result.signal.ear_mean, yaw_std, pitch_std)

        if (result.baseline_blink_rate is not None
                and hasattr(self, '_fatigue_analyzer')
                and self._fatigue_analyzer is not None):
            self._fatigue_analyzer.set_baseline_blink_rate(result.baseline_blink_rate)
            logger.info("疲劳基线已应用: %.1f 次/分钟", result.baseline_blink_rate)

        if self._db and self._session_id:
            self._db.update_session(
                self._session_id,
                baseline_ear=result.signal.ear_mean,
                baseline_blink_rate=result.baseline_blink_rate,
                is_calibrated=True,
            )

        # v4.13: 校准完成后标记已校准 + 隐藏提示
        self._calib_loaded = True
        if self._qt_window is not None:
            self._qt_window.set_calibration_prompt(False)

        logger.info(
            "v4.2 校准结果已应用: EAR=%.4f, 眨眼阈值=%.4f, adjustment=%.3f",
            result.signal.ear_mean,
            result.final_blink_threshold,
            result.final_adjustment_factor,
        )


def _check_single_instance() -> bool:
    """v4.16: 单实例锁 — PID + 时间戳双重验证。

    锁文件格式: "PID TIMESTAMP"
    1) PID 仍存活 → 拒绝
    2) 锁文件超过 30 秒且 PID 已死 → 视为残留锁，覆盖
    3) 任一检查失败 → 允许启动（不阻塞）
    """
    import atexit
    import ctypes
    import time as _time
    tmp = os.environ.get('TEMP', os.path.expanduser('~'))
    lock_file = os.path.join(tmp, 'eyefocus_instance.lock')
    try:
        if os.path.exists(lock_file):
            with open(lock_file, 'r') as f:
                content = f.read().strip()
            parts = content.split()
            old_pid = int(parts[0]) if parts else None
            old_ts = float(parts[1]) if len(parts) > 1 else 0
            if old_pid:
                alive = False
                try:
                    kernel32 = ctypes.windll.kernel32
                    h = kernel32.OpenProcess(0x0400, False, old_pid)
                    if h:
                        kernel32.CloseHandle(h)
                        alive = True
                except Exception:
                    pass
                if alive and (_time.time() - old_ts) < 30:
                    return False
        # 写新锁
        with open(lock_file, 'w') as f:
            f.write(f"{os.getpid()} {_time.time()}")
        atexit.register(lambda: os.path.exists(lock_file) and os.remove(lock_file))
        return True
    except Exception:
        return True


def main() -> None:
    """主函数"""
    # v4.16: 单实例检查
    if not _check_single_instance():
        print("EyeFocus Insight 已在运行中，请查看系统托盘。")
        sys.exit(0)

    # v4.0.2 修复 B4+B6: 屏蔽 MediaPipe Google telemetry 上报 + 统一 absl 日志风格
    # 1) 禁用 mediapipe 上报 (clearcut_uploader)
    os.environ.setdefault("GLOG_logtostderr", "0")
    os.environ.setdefault("MEDIAPIPE_DISABLE_GPU", "1")
    os.environ.setdefault("ABSL_CPP_MIN_LOG_LEVEL", "3")  # 只显示 ERROR
    # 2) 屏蔽 mediapipe python 日志
    logging.getLogger("mediapipe").setLevel(logging.ERROR)
    logging.getLogger("absl").setLevel(logging.ERROR)
    try:
        import absl.logging as _absl_log
        _absl_log.set_verbosity(_absl_log.ERROR)
    except ImportError:
        pass

    # 配置 logging
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # 创建并启动应用
    app = EyeFocusApp()

    if not app.initialize():
        logger.error("初始化失败，退出")
        sys.exit(1)

    try:
        app.start()
    except KeyboardInterrupt:
        logger.info("键盘中断")
    finally:
        app.shutdown()


if __name__ == "__main__":
    main()

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

        self._cap = cv2.VideoCapture(self._camera_index)

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
            self._read_thread.join(timeout=1.0)

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
        self._frame_write_interval: float = 1.0 / 15.0  # 最多 15 FPS 写入帧数据
        self._fatigue_write_interval: float = 1.0  # 最多每秒写入疲劳记录

        # 多信号融合：头部姿态历史（用于检测晃动）
        self._yaw_history: Deque[float] = deque(maxlen=30)  # ~1秒历史
        self._pitch_history: Deque[float] = deque(maxlen=30)
        self._prev_landmarks: Optional[np.ndarray] = None  # 上一帧 landmarks（用于检测面部晃动）

        # 最新分析结果（用于渲染）
        self._latest_focus_result = None
        self._latest_fatigue_result = None
        self._latest_gaze_score = 100.0
        self._latest_light_result = None
        self._latest_glasses_result = None
        self._latest_yaw: float = 0.0  # 最新头部偏航角
        self._latest_pitch: float = 0.0  # 最新头部俯仰角
        self._latest_face_detected: bool = False  # 人脸是否检测到

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
            # 人脸丢失
            return

        landmarks = face_result.landmarks

        # 多信号融合：更新头部姿态历史并计算权重
        current_yaw = face_result.yaw or 0.0
        current_pitch = face_result.pitch or 0.0
        self._yaw_history.append(current_yaw)
        self._pitch_history.append(current_pitch)

        # 头部姿态晃动检测：yaw/pitch 变化剧烈时降低 head_pose_weight
        head_pose_weight = 1.0
        if len(self._yaw_history) >= 10:
            yaw_std = float(np.std(self._yaw_history))
            pitch_std = float(np.std(self._pitch_history))
            # yaw_std > 3.0 或 pitch_std > 3.0 表示明显晃动（与校准基线阈值一致）
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
                # 位移越大，权重越低（最低 0.3）
                face_stability_weight = max(0.3, 1.0 - (landmark_movement - 10.0) / 50.0)
            else:
                face_stability_weight = 1.0
        self._prev_landmarks = landmarks.copy()

        # 保存头部姿态供校准回调使用
        self._latest_yaw = face_result.yaw or 0.0
        self._latest_pitch = face_result.pitch or 0.0

        # EAR 计算
        # 激活多信号融合：根据头部姿态和面部稳定性设置置信度权重
        self._eye_detector.set_head_pose_weight(head_pose_weight)
        self._eye_detector.set_face_stability_weight(face_stability_weight)
        eye_result = self._eye_detector.compute(landmarks)

        # Per-frame calibration data collection (T155)
        # 在 AUTO_CALIB 阶段，每帧将 EAR/yaw/pitch 推送给校准管理器，
        # 让其累积数据。完成时由 tick() 触发 _finalize_auto_calib()。
        if self._is_calibration_active is not None and self._is_calibration_active():
            if self._calib_manager is not None and self._calib_manager.state == CalibrationState.AUTO_CALIB:
                self._calib_manager.add_frame(
                    ear=eye_result.ear_avg,
                    yaw=self._latest_yaw,
                    pitch=self._latest_pitch,
                )

        # 光照检测
        light_result = self._light_detector.analyze_frame(frame)
        self._latest_light_result = light_result

        # 眼镜检测
        glasses_result = self._glasses_detector.detect(
            landmarks=landmarks,
            blendshapes=face_result.blendshapes,
        )
        self._latest_glasses_result = glasses_result

        # 视线检测
        gaze_result = self._gaze_detector.detect(
            landmarks=landmarks,
            head_pose_yaw=face_result.yaw or 0.0,
            head_pose_pitch=face_result.pitch or 0.0,
        )
        self._latest_gaze_score = gaze_result.gaze_concentration if gaze_result else 100.0

        # 专注度分析
        focus_result = self._focus_analyzer.analyze(
            ear=eye_result.ear_avg,
            yaw=face_result.yaw or 0.0,
            pitch=face_result.pitch or 0.0,
            gaze_score=self._latest_gaze_score,
            brightness=light_result.brightness,
            face_detected=face_result.face_detected,
        )
        self._latest_focus_result = focus_result

        # 疲劳分析 - 获取最近眨眼的 ear_nadir
        ear_nadir = None
        recent_blinks = self._eye_detector.get_blink_events(
            since_time=time.time() - 30.0  # 只取最近 30 秒内的眨眼
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
                yaw=face_result.yaw or 0.0,
                pitch=face_result.pitch or 0.0,
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

    def get_current_ear(self) -> float:
        """获取当前 EAR 值（供校准回调使用）"""
        if self._eye_detector:
            return self._eye_detector.get_current_ear()
        return 0.0

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
            self._glasses_detector = create_glasses_detector()
            self._fatigue_analyzer = create_fatigue_analyzer()

            # 连接分析器与检测器
            self._focus_analyzer.set_blink_detector(self._eye_detector)
            self._fatigue_analyzer.start()

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

        # 自动开始校准（如果启用）- 使用新的 UserCalibrationManager 流程
        if self.config.enable_calibration:
            self.start_calibration_flow()

        # 启动主循环
        self._main_loop()

    def _main_loop(self) -> None:
        """主循环"""
        # 启动摄像头
        if not self._camera_manager.start():
            logger.error("摄像头启动失败")
            return

        try:
            while self._running:
                # 检测主窗口是否被关闭 (×按钮)
                try:
                    if cv2.getWindowProperty("EyeFocus Insight", cv2.WND_PROP_VISIBLE) < 1:
                        logger.info("主窗口被关闭, 退出")
                        self._running = False
                        break
                except cv2.error:
                    self._running = False
                    break

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
            if self._confirm_quit_pending:
                self._draw_confirmation_overlay(display, "再按一次 Q 确认退出", 5.0, self._confirm_quit_time)
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

    def _handle_keyboard(self, key: int) -> None:
        """处理键盘输入 (v4.4: 确认弹窗 + 按键反馈)

        Q 退出(需二次确认) | ESC 取消校准(需二次确认) | P/Space 暂停
        C 启动校准 | Tab 切换面板 | 数字+Enter 校准输入
        """
        now = time.time()

        # --- 二次确认处理 (Q/ESC) ---
        # 如果正在等待 Q 确认, 第二次 Q → 退出; 其他键/超时 → 取消
        if self._confirm_quit_pending:
            if key == ord('q') or key == ord('Q'):
                logger.info("用户确认退出 (Q×2)")
                self._running = False
            else:
                self._confirm_quit_pending = False
                self._set_feedback("已取消退出")
            return

        # 如果正在等待 ESC 确认, 第二次 ESC → 取消校准
        if self._confirm_cancel_pending:
            if key == 27:  # ESC
                logger.info("用户确认取消校准 (ESC×2)")
                self._confirm_cancel_pending = False
                self._cancel_calibration()
                self._set_feedback("校准已取消")
            else:
                self._confirm_cancel_pending = False
                self._set_feedback("已取消操作")
            return

        # --- 正常按键处理 ---
        # ESC → 仅在校准激活时触发二次确认
        if key == 27:
            if self._calib_coordinator and (self._calib_coordinator.is_active()
                                           or self._calib_coordinator.input_mode):
                self._confirm_cancel_pending = True
                self._confirm_cancel_time = now
                self._set_feedback("再按 ESC 确认取消校准")
            return

        # Q → 触发二次确认
        if key == ord('q') or key == ord('Q'):
            self._confirm_quit_pending = True
            self._confirm_quit_time = now
            self._set_feedback("再按 Q 确认退出")
            return

        # 数字键和 Enter（仅在校准输入模式）
        if self._calib_coordinator and self._calib_coordinator.input_mode:
            if 48 <= key <= 57:  # 数字键 0-9
                digit = str(key - 48)
                self._calib_coordinator.handle_digit_input(digit)
                self._set_feedback(f"输入: {digit}")
            elif key == 13 or key == 10:  # Enter
                self._calib_coordinator.handle_enter_pressed()
                self._set_feedback("已确认")
            return

        # C 键：正常模式下启动校准
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

        # Tab 键：切换极简/完整模式 (阶段一)
        if key == 9:  # Tab
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
            self._draw_confirmation_overlay(display, "再按一次 Q 确认退出", 5.0, self._confirm_quit_time)
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

    def _cleanup(self) -> None:
        """清理资源

        M-23: db.close() 也用 try/except + logger.exception 包裹 (与 face_detector.close() 一致).
        所有 close 异常累加到 _cleanup_errors 计数.
        """
        # 初始化错误计数 (供 M-23 累加)
        if not hasattr(self, '_cleanup_errors'):
            self._cleanup_errors = 0

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

        logger.info(
            "v4.2 校准结果已应用: EAR=%.4f, 眨眼阈值=%.4f, adjustment=%.3f",
            result.signal.ear_mean,
            result.final_blink_threshold,
            result.final_adjustment_factor,
        )


def main() -> None:
    """主函数"""
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

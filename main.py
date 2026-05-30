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

import logging
import signal
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import cv2
import numpy as np

# 添加项目路径
sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")

from config import CAMERA
from analyzer.baseline import BaselineCalibrator, create_baseline_calibrator
from analyzer.focus import FocusAnalyzer, create_focus_analyzer
from analyzer.glasses import GlassesDetector, create_glasses_detector
from analyzer.fatigue import FatigueAnalyzer, create_fatigue_analyzer
from detector.face_mesh import FaceMeshDetector, create_face_mesh_detector
from detector.eye_aspect import EyeAspectDetector, create_eye_aspect_detector
from detector.gaze import GazeDetector, create_gaze_detector
from detector.light import LightDetector, create_light_detector
from gui.overlay import FocusOverlay, CalibrationProgress
from storage.db import DatabaseManager, create_database_manager
from storage.models import (
    BlinkEvent,
    FatigueLevel,
    FatigueRecord,
    FrameRecord,
    GlassesMode,
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


class EyeFocusApp:
    """EyeFocus Insight 主应用类

    整合所有检测器、分析器和存储模块。
    """

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or AppConfig()

        # 状态标志
        self._running: bool = False
        self._calibrating: bool = False
        self._paused: bool = False

        # 检测器
        self._face_detector: Optional[FaceMeshDetector] = None
        self._eye_detector: Optional[EyeAspectDetector] = None
        self._gaze_detector: Optional[GazeDetector] = None
        self._light_detector: Optional[LightDetector] = None

        # GUI 叠加层
        self._overlay: Optional[FocusOverlay] = None

        # 分析器
        self._calibrator: Optional[BaselineCalibrator] = None
        self._focus_analyzer: Optional[FocusAnalyzer] = None
        self._glasses_detector: Optional[GlassesDetector] = None
        self._fatigue_analyzer: Optional[FatigueAnalyzer] = None

        # 存储
        self._db: Optional[DatabaseManager] = None
        self._current_session: Optional[Session] = None
        self._session_id: Optional[str] = None

        # 帧统计
        self._frame_count: int = 0
        self._fps: float = 0.0
        self._fps_start_time: float = 0.0
        self._fps_frame_count: int = 0

        # 眨眼写入索引（避免重复写入）
        self._last_written_blink_count: int = 0

        # 线程管理
        self._detector_thread: Optional[threading.Thread] = None
        self._shutdown_event: threading.Event = threading.Event()

        # 信号处理
        self._original_sigint: Optional[object] = None
        self._original_sigterm: Optional[object] = None

        # 最新分析结果（用于渲染）
        self._latest_focus_result = None
        self._latest_fatigue_result = None
        self._latest_gaze_score = 100.0
        self._latest_light_result = None
        self._latest_glasses_result = None

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
            self._calibrator = create_baseline_calibrator()
            self._focus_analyzer = create_focus_analyzer()
            self._glasses_detector = create_glasses_detector()
            self._fatigue_analyzer = create_fatigue_analyzer()

            # 连接分析器与检测器
            self._focus_analyzer.set_blink_detector(self._eye_detector)
            self._fatigue_analyzer.start()

            logger.info("初始化完成 (session: %s)", self._session_id)
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

        # 自动开始校准（如果启用）
        if self.config.enable_calibration:
            self.start_calibration()

        # 启动主循环
        self._main_loop()

    def _main_loop(self) -> None:
        """主循环"""
        cap = cv2.VideoCapture(self.config.camera_index)

        if not cap.isOpened():
            logger.error("无法打开摄像头 (index %d)", self.config.camera_index)
            return

        try:
            while self._running:
                ret, frame = cap.read()
                if not ret:
                    continue

                # 处理帧
                self._process_frame(frame)

                # 显示（如果 GUI 可用）
                self._render_frame(frame)

                # 更新 FPS
                self._update_fps()

                # 检查退出键
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    logger.info("用户请求退出")
                    break

        finally:
            cap.release()
            cv2.destroyAllWindows()
            self._cleanup()

    def _process_frame(self, frame: np.ndarray) -> None:
        """处理单帧

        Args:
            frame: BGR 格式 OpenCV 图像
        """
        self._frame_count += 1
        timestamp_ms = int(time.time() * 1000)

        # 人脸检测
        face_result = self._face_detector.detect_from_frame(frame, timestamp_ms)

        if not face_result.face_detected:
            # 人脸丢失
            return

        landmarks = face_result.landmarks

        # EAR 计算
        eye_result = self._eye_detector.compute(landmarks)

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
        self._latest_gaze_score = gaze_result.gaze_score if gaze_result else 100.0

        # 校准中
        if self._calibrating:
            self._calibrator.add_frame(
                ear=eye_result.ear_avg,
                yaw=face_result.yaw,
                pitch=face_result.pitch,
            )

            if self._calibrator.is_complete():
                self._finish_calibration()

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
        recent_blinks = self._eye_detector.get_blink_events()
        if recent_blinks:
            ear_nadir = recent_blinks[-1].ear_nadir

        fatigue_result = self._fatigue_analyzer.analyze(
            blink_rate=focus_result.blink_rate,
            ear_nadir=ear_nadir,
            head_stability=focus_result.head_score,
        )
        self._latest_fatigue_result = fatigue_result

        # 存储帧记录
        if self._db and self._session_id:
            frame_record = FrameRecord(
                session_id=self._session_id,
                timestamp=time.time(),
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

        # 存储眨眼事件（只写入新产生的）
        if self._db and self._session_id:
            blink_events = self._eye_detector.get_blink_events()
            # 只写入上次之后的新眨眼事件
            new_blinks = blink_events[self._last_written_blink_count:]
            for event in new_blinks:
                self._db.write_blink_event(
                    self._session_id,
                    BlinkEvent(
                        session_id=self._session_id,
                        start_timestamp=event.start_time,
                        end_timestamp=event.end_time,
                        duration_seconds=event.duration,
                        ear_nadir=event.ear_nadir,
                    )
                )
            self._last_written_blink_count = len(blink_events)

        # 存储疲劳记录
        if self._db and self._session_id and self._latest_fatigue_result is not None:
            fatigue_record = FatigueRecord(
                session_id=self._session_id,
                timestamp=time.time(),
                fatigue_level=self._latest_fatigue_result.fatigue_level,
                blink_rate=self._latest_fatigue_result.blink_rate,
                avg_ear_nadir=self._latest_fatigue_result.avg_ear_nadir,
                head_stability=self._latest_fatigue_result.head_stability,
                cumulative_fatigue_score=self._latest_fatigue_result.cumulative_fatigue,
            )
            self._db.write_fatigue_record(self._session_id, fatigue_record)

    def _render_frame(self, frame: np.ndarray) -> None:
        """渲染帧到窗口

        Args:
            frame: BGR 格式 OpenCV 图像
        """
        # 构建校准进度
        calibration_progress = None
        if self._calibrating:
            status = self._calibrator.get_status()
            # 计算目标帧数（假设 30 FPS）
            total_frames = int(self.config.calibration_duration * 30)
            calibration_progress = CalibrationProgress(
                current=status.collected_frames,
                total=total_frames,
                cqs=status.current_cqs,
                is_complete=False,
            )

        # 获取疲劳等级字符串
        fatigue_level_str = None
        if self._latest_fatigue_result is not None:
            level = self._latest_fatigue_result.fatigue_level
            fatigue_level_str = level.value.upper() if hasattr(level, 'value') else str(level)

        # 获取专注度分量
        eye_score = None
        head_score = None
        gaze_score_val = None
        focus_score_val = None
        if self._latest_focus_result is not None:
            focus_score_val = self._latest_focus_result.focus_score
            eye_score = self._latest_focus_result.eye_score
            head_score = self._latest_focus_result.head_score
            gaze_score_val = self._latest_focus_result.gaze_score

        # 获取光照条件字符串
        light_condition_str = None
        if self._latest_light_result is not None:
            light_condition_str = self._latest_light_result.condition.value.upper()

        # 获取眼镜模式字符串
        glasses_str = None
        if self._latest_glasses_result is not None:
            if self._latest_glasses_result.is_glasses:
                glasses_str = "ON"
            else:
                glasses_str = "OFF"

        # 使用 FocusOverlay 渲染
        display = self._overlay.draw(
            frame,
            focus_score=focus_score_val,
            fatigue_level=fatigue_level_str,
            eye_detected=True,
            face_detected=True,
            light_condition=light_condition_str,
            calibration=calibration_progress,
            eye_score=eye_score,
            head_score=head_score,
            gaze_score=gaze_score_val,
        )

        # 在右上角显示眼镜状态
        if glasses_str:
            cv2.putText(
                display,
                f"Glasses: {glasses_str}",
                (self._overlay.config.width - 120, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
            )

        # 添加 FPS 显示（叠加层不包含 FPS）
        cv2.putText(
            display,
            f"FPS: {self._fps:.1f}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
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

    def _finish_calibration(self) -> None:
        """完成校准"""
        self._calibrating = False

        result = self._calibrator.get_result()
        if result and result.is_valid:
            # 更新会话
            if self._db and self._session_id:
                self._db.update_session(
                    self._session_id,
                    baseline_ear=result.ear_mean,
                    baseline_yaw_std=result.yaw_std,
                    baseline_pitch_std=result.pitch_std,
                    cqs_score=result.cqs_score,
                    is_calibrated=True,
                )

            # 更新分析器基线
            self._focus_analyzer.set_baseline(
                ear=result.ear_mean,
                yaw_std=result.yaw_std,
                pitch_std=result.pitch_std,
            )

            logger.info(
                "校准完成: CQS=%.3f, EAR=%.4f",
                result.cqs_score,
                result.ear_mean,
            )
        else:
            logger.warning("校准未通过，请重试")

    def start_calibration(self) -> bool:
        """开始校准

        Returns:
            True 如果成功开始校准
        """
        if not self._calibrating:
            self._calibrator.start()
            self._calibrating = True
            logger.info("开始校准...")
            return True
        return False

    def _register_signal_handlers(self) -> None:
        """注册信号处理器"""
        self._original_sigint = signal.signal(signal.SIGINT, self._signal_handler)
        self._original_sigterm = signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame) -> None:
        """信号处理"""
        logger.info("收到信号 %d，准备退出...", signum)
        self.shutdown()

    def shutdown(self) -> None:
        """安全关闭应用"""
        if not self._running:
            return

        logger.info("正在关闭...")
        self._running = False
        self._shutdown_event.set()

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

        logger.info("已安全退出")

    def _cleanup(self) -> None:
        """清理资源"""
        # 恢复信号处理器
        if self._original_sigint:
            signal.signal(signal.SIGINT, self._original_sigint)
        if self._original_sigterm:
            signal.signal(signal.SIGTERM, self._original_sigterm)

        # 关闭检测器（带超时）
        if self._face_detector:
            try:
                self._face_detector.close()
            except Exception as e:
                logger.warning("FaceDetector.close() 异常: %s", e)

        # 关闭数据库
        if self._db:
            self._db.close()

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running

    @property
    def is_calibrating(self) -> bool:
        """是否正在校准"""
        return self._calibrating

    @property
    def fps(self) -> float:
        """当前 FPS"""
        return self._fps

    @property
    def session_id(self) -> Optional[str]:
        """当前会话 ID"""
        return self._session_id


def main() -> None:
    """主函数"""
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

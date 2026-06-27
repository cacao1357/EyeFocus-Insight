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
os.environ.setdefault("MEDIAPIPE_DISABLE_GPU", "0")  # v4.33: 默认启用 GPU；出问题时设 =1 回退 CPU
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
from typing import Optional, Callable

# v4.26: 延迟到 initialize() 加载，避免模块级副作用

import cv2
import numpy as np

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import CAMERA
from analyzer.focus import FocusAnalyzer, create_focus_analyzer
# from analyzer.voice_assistant import create_voice_assistant  # v4.49+: 语音已移除
from analyzer.reminder_engine import create_reminder_engine
from analyzer.gamification import create_gamification_engine
from analyzer.pomodoro import create_pomodoro_engine
from analyzer.predictor import create_focus_predictor
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
    Session,
)

# v4.22: strangler 提取的 app 子包
from app.camera import CameraManager
from app.processor import FrameProcessor
from app.calibration import CalibrationFlowCallbacks, CalibrationCoordinator

# v4.22: Web 仪表盘
from webserver import WebDashboard


logger = logging.getLogger("eyefocus.main")

# v4.17: 全局异常捕获（防止未处理异常静默崩溃）
def _global_excepthook(exc_type, exc_value, exc_traceback):
    logger.critical("未捕获异常: %s: %s", exc_type.__name__, exc_value)
    import traceback
    traceback.print_exception(exc_type, exc_value, exc_traceback)
sys.excepthook = _global_excepthook


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


def _ensure_llama_dll():
    """v4.26: 在 initialize() 中提前加载 llama_cpp DLL，避免与 PyQt5/mediapipe DLL 冲突"""
    try:
        import llama_cpp  # noqa: F401
    except Exception:
        pass


def _warmup_llm_backend():
    """v4.26: 后台预热 AI 后端"""
    try:
        from config import get_yaml_value
        backend = get_yaml_value("ai", "backend", default="template")
        if backend == "template":
            return
        kwargs = {}
        if backend == "ollama":
            kwargs["base_url"] = get_yaml_value("ai", "ollama_url",
                                                 default="http://127.0.0.1:11434")
        elif backend == "local":
            kwargs["n_gpu_layers"] = -1
        from analyzer.llm_client import create_llm_client, warmup_client
        client = create_llm_client(backend, **kwargs)
        warmup_client(client)
    except Exception as e:
        logger = logging.getLogger("eyefocus.main")
        logger.debug("AI 预热跳过: %s", e)


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
        # v4.4: 追踪最后检测到人脸的时间, 用于无脸检测 UI 警告
        self._last_face_time: Optional[float] = None
        # v4.13: 历史校准加载状态
        self._calib_loaded: bool = False
        # v4.50: 校准持久化文件路径
        self._CALIBRATION_FILE: str = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "user_calibration.json"
        )
        # v4.33: 报告 HTML 时间缓存（5 分钟 TTL，检测中重复打开免重生成）
        self._report_html_cache: "Dict[str, tuple]" = {}  # {cache_key: (html, timestamp)}

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
        # v4.22: 会话启动时间（提前初始化，防 _qt_process_frame 竞态）
        self._session_start_time: float = 0.0

    def initialize(self) -> bool:
        """初始化所有模块

        Returns:
            True 如果初始化成功
        """
        logger.info("EyeFocus Insight 初始化中...")

        # v4.26: 从模块级移入，但仍早于 mediapipe/PyQt5
        _ensure_llama_dll()

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
            # v4.29: 启动异步检测管道（后台线程处理，主线程不阻塞）
            if self._face_detector is not None:
                self._face_detector.start_async()
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
            # v4.49+: 语音已移除
            # from config import get_yaml_value
            # voice_enabled = get_yaml_value("voice", "enabled", default=True)
            # self._voice_asst = create_voice_assistant(enabled=voice_enabled)
            self._voice_asst = None

            # v4.17: 智能提醒引擎（回调延迟绑定）
            self._reminder_engine = create_reminder_engine(
                tray_callback=self._reminder_tray_notify,
                # voice_callback=...,     # v4.49+: 语音已移除
            )

            # v4.17: 游戏化引擎
            self._gamification = create_gamification_engine(db=self._db)

            # v4.18: 番茄工作法（回调延迟绑定）
            self._pomodoro = create_pomodoro_engine(
                # voice_callback=...,     # v4.49+: 语音已移除
                pause_callback=lambda: self._pomodoro_pause(),
                resume_callback=lambda: self._pomodoro_resume(),
                notify_callback=lambda t, m: self._reminder_tray_notify(t, m),
            )

            # v4.24: 专注度趋势预测器
            self._focus_predictor = create_focus_predictor()

            # v4.22: Web 仪表盘（后台线程，不阻塞主程序）
            self._web_dashboard = WebDashboard(port=8080)
            if self._db is not None:
                self._web_dashboard.set_db(self._db)
            # v4.26: 注册 Web 控制回调
            self._web_dashboard.on("toggle_pause", lambda: self._qt_window.toggle_pause() if self._qt_window else None)
            self._web_dashboard.on("calibrate", lambda: self._qt_window.calibrate_requested.emit() if self._qt_window else None)
            self._web_dashboard.on("pause", lambda: self._qt_window.set_paused(True) if self._qt_window else None)
            self._web_dashboard.on("resume", lambda: self._qt_window.set_paused(False) if self._qt_window else None)
            self._web_dashboard.start()
            logger.info("Web 仪表盘: http://127.0.0.1:8080")

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

            # v4.26: 后台预热 LLM 模型（非阻塞）
            self._warmup_llm_model()

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

    def _warmup_llm_model(self) -> None:
        """v4.26: 后台线程预热 LLM 模型，不阻塞主流程"""
        import threading as _t
        _t.Thread(target=_warmup_llm_backend, daemon=True,
                   name="llm-warmup").start()

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
        # v4.27: 窗口隐藏到托盘后 settings dialog 关闭不退出
        self._qt_app.setQuitOnLastWindowClosed(False)
        # v4.22: 强制 Fusion 风格 + 浅色调色板（防止系统暗色模式导致黑背景不可读）
        from PyQt5.QtGui import QColor, QPalette
        from PyQt5.QtWidgets import QStyleFactory
        _fusion = QStyleFactory.create("Fusion")
        if _fusion is not None:
            self._qt_app.setStyle(_fusion)
        _p = self._qt_app.palette()
        _p.setColor(QPalette.Window, QColor(255, 255, 255))
        _p.setColor(QPalette.WindowText, QColor(35, 32, 30))       # Warm Ink
        _p.setColor(QPalette.Base, QColor(255, 255, 255))
        _p.setColor(QPalette.AlternateBase, QColor(244, 242, 238)) # Stone
        _p.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))
        _p.setColor(QPalette.ToolTipText, QColor(35, 32, 30))
        _p.setColor(QPalette.Text, QColor(35, 32, 30))
        _p.setColor(QPalette.Button, QColor(240, 240, 240))
        _p.setColor(QPalette.ButtonText, QColor(35, 32, 30))
        _p.setColor(QPalette.BrightText, QColor(255, 255, 255))
        _p.setColor(QPalette.Highlight, QColor(91, 74, 140))       # Iris
        _p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        self._qt_app.setPalette(_p)

        # ── Qt 校准对话框（自有摄像头，释放后等待足够时间）──
        if self.config.enable_calibration:
            self._camera_manager.release()
            import time as _wt; _wt.sleep(2.0)  # 等待驱动完全释放
            try:
                from gui.calibration_dialog import run_calibration_dialog
                calib_result = run_calibration_dialog(
                    fd=self._face_detector, ed=self._eye_detector)
                if calib_result:
                    self._apply_qt_calibration_result(calib_result)
                else:
                    logger.info("校准被取消或失败，使用默认参数")
            except Exception as e:
                logger.warning("校准对话框异常: %s，使用默认参数", e)
                import traceback
                traceback.print_exc()
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
            self._qt_window.set_calibration_status(True)

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

        # v4.36: 校准取消/跳过 → Qt Toast 持续显示，直到用户完成校准
        if self._calib_cancelled_msg:
            self._qt_window.set_uncalibrated_warning(True, self._calib_cancelled_msg)
            self._calib_cancelled_msg = None

        # 显示窗口并启动事件循环
        self._qt_window.show()
        self._qt_window.start()
        logger.debug("Qt 事件循环启动 (timer_active=%s)", self._qt_timer.isActive())
        exit_code = self._qt_app.exec_()

        # 事件循环结束后清理（带诊断日志）
        logger.info("Qt 事件循环结束 exit_code=%s — 开始清理", exit_code)
        self._running = False
        self._qt_timer.stop(); logger.debug("Step 1/4: 定时器已停")
        self._camera_manager.release(); logger.debug("Step 2/4: 摄像头已释放")
        self._cleanup(); logger.debug("Step 3/4: 资源清理完成")
        logger.info("Step 4/4: _start_qt_monitoring 返回，进程将退出")

    def _load_last_calibration(self) -> None:
        """v4.13: 从数据库加载最近一次校准数据，避免每次启动提示未校准。"""
        if self._db is None:
            return
        try:
            with self._db.get_cursor() as cur:
                cur.execute(
                    "SELECT baseline_ear, baseline_yaw_std, baseline_pitch_std, "
                    "baseline_blink_rate "
                    "FROM sessions WHERE is_calibrated=1 AND baseline_ear IS NOT NULL "
                    "ORDER BY start_time DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row and row[0] is not None and row[0] > 0:
                    ear = float(row[0])
                    yaw_std = float(row[1]) if row[1] else None
                    pitch_std = float(row[2]) if row[2] else None
                    blink_rate = float(row[3]) if len(row) > 3 and row[3] else None
                    if self._focus_analyzer is not None:
                        self._focus_analyzer.set_baseline(ear, yaw_std, pitch_std)
                    if self._eye_detector is not None:
                        self._eye_detector.set_baseline(ear)
                    if blink_rate and self._fatigue_analyzer is not None:
                        self._fatigue_analyzer.set_baseline_blink_rate(blink_rate)
                    self._calib_loaded = True
                    logger.info("已加载历史校准: EAR=%.4f, blink=%.1f", ear,
                                blink_rate or 0)
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

        yaw_std_qt = head_yaw / 2.0 if head_yaw > 0 else None
        pitch_std_qt = head_pitch / 2.0 if head_pitch > 0 else None

        if self._focus_analyzer is not None:
            self._focus_analyzer.set_baseline(
                ear=baseline_ear,
                yaw_std=yaw_std_qt,
                pitch_std=pitch_std_qt,
            )
            logger.info("Qt 校准专注度基线已应用: EAR=%.4f, yaw=%.1f, pitch=%.1f",
                        baseline_ear, head_yaw, head_pitch)

        # v4.39: 补存 yaw_std/pitch_std（Qt 校准无 blink_rate/cqs）
        if self._db and self._session_id:
            self._db.update_session(
                self._session_id,
                baseline_ear=baseline_ear,
                baseline_yaw_std=yaw_std_qt,
                baseline_pitch_std=pitch_std_qt,
                is_calibrated=True,
            )

        # v4.13: 校准完成后标记已校准 + 隐藏提示
        self._calib_loaded = True
        if self._qt_window is not None:
            self._qt_window.set_calibration_status(True)

    def _on_qt_calibrate(self) -> None:
        """Qt 窗口校准按钮处理"""
        logger.info("校准按钮点击 (Qt 模式)")

        # v4.16: 防止重复进入校准
        if getattr(self, '_calibrating', False):
            logger.warning("校准已在进行中，忽略重复请求")
            return
        self._calibrating = True

        self._qt_window.set_paused(True)
        # v4.31: 暂停主循环定时器，避免校准期间空转（每 33ms 无意义唤醒）
        if hasattr(self, '_qt_timer') and self._qt_timer is not None:
            self._qt_timer.stop()
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
            # 恢复主循环定时器
            if hasattr(self, '_qt_timer') and self._qt_timer is not None:
                self._qt_timer.start(33)

    def _qt_process_frame(self) -> None:
        """Qt 定时器回调: 处理一帧"""
        # v4.17: 调试日志 — 首次帧
        if not getattr(self, '_qt_frame_first_logged', False):
            self._qt_frame_first_logged = True
            logger.debug("_qt_process_frame 首次调用")

        # v4.19: 暂停时跳过处理
        # v4.49+: 番茄时钟移到暂停检查前，休息倒计时不受暂停影响
        if hasattr(self, '_pomodoro') and self._pomodoro is not None:
            self._pomodoro.tick()
            pomo_ui_time = getattr(self, '_pomo_ui_time', 0)
            if time.time() - pomo_ui_time >= 1.0:
                self._pomo_ui_time = time.time()
                if hasattr(self, '_qt_window') and self._qt_window is not None:
                    self._qt_window.update_pomodoro(self._pomodoro.get_status())
                    if hasattr(self._qt_window, '_tray_icon') and self._qt_window._tray_icon is not None:
                        st = self._pomodoro.state
                        if self._pomodoro._paused:
                            st = "PAUSED"
                        self._qt_window._tray_icon.set_pomodoro_state(st, self._pomodoro.count)

        if getattr(self, '_qt_window', None) is not None and self._qt_window.is_paused():
            return

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
                try:
                    # v4.26: 复用 face_mesh 已转换的 RGB 帧，省一次 cv2.cvtColor
                    rgb = getattr(self._face_detector, '_last_rgb_frame', None)
                    if rgb is not None:
                        self._qt_window.show_frame(rgb, is_rgb=True)
                    else:
                        self._qt_window.show_frame(frame)
                except RuntimeError:
                    # 窗口已在 C++ 层销毁 → 跳过（竞态保护）
                    return

            # 更新 Qt 窗口的数据面板（圆环 + 卡片）
            if hasattr(self, '_qt_window') and self._qt_window is not None:
                # v4.17: 修复专注时长一直显示 "--" 的问题
                elapsed_min = (time.time() - self._session_start_time) / 60.0 if self._session_start_time else 0.0
                self._frame_processor.focus_duration_minutes = elapsed_min
                try:
                    self._qt_window.update_data_from_processor(self._frame_processor, self._fps)
                except RuntimeError:
                    return

            # FPS
            self._update_fps()

            # v4.41: 追踪最后检测到人脸的时间 + UI 警告（不自动暂停）
            if self._frame_processor.latest_face_detected:
                self._last_face_time = time.time()
                # 人脸恢复 → 清除警告
                if hasattr(self, '_qt_window') and self._qt_window is not None:
                    try:
                        self._qt_window.set_face_lost_warning(False)
                    except RuntimeError:
                        pass
            elif self._last_face_time is not None:
                lost_duration = time.time() - self._last_face_time
                if lost_duration > 3.0:
                    # 人脸丢失 > 3s → 显示 UI 警告，但不暂停检测
                    if hasattr(self, '_qt_window') and self._qt_window is not None:
                        try:
                            self._qt_window.set_face_lost_warning(True)
                        except RuntimeError:
                            pass

            # v4.30: 疲劳通知已移至 ReminderEngine（合并通知路径 + 指数退避）
            # v4.10 旧路径移除，避免双通道弹窗

            # v4.17: 语音反馈 + 智能提醒 + 波线 + 游戏化
            try:
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

                # 语音                                # v4.49+: 语音已移除
                # if hasattr(self, '_voice_asst') and self._voice_asst is not None:
                #     self._voice_asst.on_tick(
                #         focus_score=focus_score, fatigue_level=fatigue_level,
                #         session_minutes=session_min,
                #         face_detected=self._frame_processor.latest_face_detected,
                #     )

                # 提醒
                if hasattr(self, '_reminder_engine') and self._reminder_engine is not None:
                    self._reminder_engine.check(
                        focus_score=focus_score, focus_level=focus_level,
                        fatigue_level=fatigue_level, session_minutes=session_min,
                        face_detected=self._frame_processor.latest_face_detected,
                    )

                # 波线 + 番茄（每秒一次）
                spark_time = getattr(self, '_spark_update_time', 0)
                if time.time() - spark_time >= 1.0:
                    self._spark_update_time = time.time()
                    if hasattr(self, '_qt_window') and self._qt_window is not None:
                        self._qt_window.update_sparkline(focus_score)
                    # v4.24: 专注度趋势预测
                    if hasattr(self, '_focus_predictor') and self._focus_predictor is not None:
                        self._focus_predictor.add_score(focus_score)
                    # v4.49+: 番茄 tick + UI 已移至暂停检查前，此处不再重复

                # v4.22: Web 仪表盘广播（每秒一次）
                if hasattr(self, '_web_dashboard') and self._web_dashboard is not None:
                    try:
                        pomo = self._pomodoro.get_status() if hasattr(self, '_pomodoro') and self._pomodoro is not None else None
                        ear = getattr(self._frame_processor, '_latest_ear', None)
                        pred = self._focus_predictor.get_stats() if hasattr(self, '_focus_predictor') and self._focus_predictor is not None else None
                        self._web_dashboard.broadcast({
                            "focus_score": focus_score,
                            "ear": ear,
                            "fatigue_level": fatigue_level,
                            "face_detected": self._frame_processor.latest_face_detected,
                            "session_minutes": session_min,
                            "session_start": getattr(self, '_session_start_time', None),
                            "pomodoro": pomo,
                            "trend": pred["arrow"] if pred else None,
                            "suggest_break": pred["suggest_break"] if pred else False,
                        })
                    except Exception as e:
                        logger.warning("Web 仪表盘广播异常: %s", e)

                # 游戏化（每 60s）
                gamify_update = getattr(self, '_gamify_update_time', 0)
                if time.time() - gamify_update >= 60:
                    self._gamify_update_time = time.time()
                    if (hasattr(self, '_gamification') and self._gamification is not None
                            and hasattr(self, '_qt_window') and self._qt_window is not None):
                        streak = self._gamification.get_streak_days()
                        today_min = self._gamification.get_today_minutes()
                        trend = self._focus_predictor.trend_arrow if hasattr(self, '_focus_predictor') else ""
                        self._qt_window.update_gamification(streak, today_min, trend)
            except Exception as e:
                logger.warning("语音/提醒/游戏化处理异常: %s", e)
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
        """Qt 退出信号处理

        停止顺序至关重要：先停定时器 → 再移除图标 → 最后 quit。
        如果先 quit 再停定时器，窗口 closeEvent 完成 → 定时器回调
        访问已销毁的 QWidget → C 层段错误（try/except 抓不住）。
        """
        logger.info("用户请求退出 (Qt) — 开始关闭顺序")
        # 0) 必须最先停定时器，否则后续 frame 回调访问已销毁窗口
        if hasattr(self, '_qt_timer') and self._qt_timer is not None:
            self._qt_timer.stop()
            logger.debug("Qt 定时器已停止")
        # 1) 移除托盘图标，避免残留在系统托盘中
        if hasattr(self, '_qt_window') and self._qt_window is not None:
            if hasattr(self._qt_window, '_tray_icon') and self._qt_window._tray_icon is not None:
                self._qt_window._tray_icon.hide()
                logger.info("托盘图标已移除")
        # 2) 退出事件循环
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

    # ── v4.18: 番茄工作法 ──

    def _pomodoro_pause(self) -> None:
        """番茄休息时暂停监测"""
        try:
            if hasattr(self, '_qt_window') and self._qt_window is not None:
                self._qt_window.set_paused(True)
                if hasattr(self, '_qt_window') and hasattr(self._qt_window, '_tray_icon'):
                    self._qt_window._tray_icon.set_paused_state(True)
        except Exception:
            pass

    def _pomodoro_resume(self) -> None:
        """番茄工作时恢复监测"""
        try:
            if hasattr(self, '_qt_window') and self._qt_window is not None:
                self._qt_window.set_paused(False)
                if hasattr(self, '_qt_window') and hasattr(self._qt_window, '_tray_icon'):
                    self._qt_window._tray_icon.set_paused_state(False)
        except Exception:
            pass

    # ── v4.17: 提醒引擎托盘回调 ──

    def _reminder_tray_notify(self, title: str, message: str) -> None:
        """v4.26: 恢复托盘提醒通知"""
        logger.debug("提醒引擎: [%s] %s", title, message)
        if hasattr(self, '_qt_window') and self._qt_window is not None:
            tray = getattr(self._qt_window, '_tray_icon', None)
            if tray is not None:
                try:
                    tray.showMessage(
                        f"EyeFocus Insight - {title}", message,
                        tray.Warning if "疲劳" in title or "注意" in title else tray.Information,
                        5000,
                    )
                except Exception:
                    pass

    # ── v4.18: 周报 ──

    def _error_report_html(self, error_msg: str) -> str:
        """生成错误占位报告（保证文件存在）"""
        return f"""<!DOCTYPE html><html><meta charset="utf-8"><body style="padding:40px;font-family:sans-serif">
<h2>⚠️ 报告生成失败</h2><p style="color:#666;">{error_msg}</p>
<p style="color:#999;font-size:12px;">EyeFocus Insight · {datetime.now()}</p>
</body></html>"""

    def _generate_weekly_report(self) -> None:
        """生成周报并在浏览器中打开"""
        try:
            from reporter.report_html import create_html_generator
            generator = create_html_generator(self._db)
            html = generator.generate_weekly_report()
            import os
            os.makedirs("reports", exist_ok=True)
            from datetime import datetime
            path = f"reports/weekly_{datetime.now().strftime('%Y%m%d')}.html"
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            os.startfile(os.path.abspath(path))
            logger.info("周报已生成: %s", path)
        except Exception as e:
            logger.warning("生成周报失败: %s", e)

    def generate_report_snapshot(self, force: bool = False) -> Optional[str]:
        """生成当前会话的报告快照（不终止会话）

        与 _finalize_session 不同：不设置 end_time/is_active=False。
        用于托盘"打开报告"操作。

        v4.33: 5 分钟时间缓存 — 检测中重复打开免重生成。
        v4.34: force=True 跳过缓存强制重生成（托盘主动请求时用）。

        Returns:
            报告文件路径，失败返回 None
        """
        if not self._db or not getattr(self, '_session_id', None):
            logger.warning("generate_report_snapshot: 无活动会话")
            return None

        import os, time as _time

        # v4.33: 检查时间缓存（仅检测中定时刷新用；手动请求走 force 跳过缓存）
        cache_key = f"{self._session_id}_snapshot"
        if not force and cache_key in self._report_html_cache:
            cached_html, cached_ts = self._report_html_cache[cache_key]
            if _time.time() - cached_ts < 300:  # 5 分钟 TTL
                logger.info("报告缓存命中 (%.0fs 前生成)，跳过重生成", _time.time() - cached_ts)
                os.makedirs("reports", exist_ok=True)
                report_path = f"reports/{self._session_id}.html"
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(cached_html)
                return os.path.abspath(report_path)
            else:
                del self._report_html_cache[cache_key]

        try:
            from reporter.report_html import create_html_generator

            generator = create_html_generator(self._db)
            today_str = datetime.now().strftime("%Y%m%d")
            if self._session_id.startswith(today_str):
                date_str = datetime.now().strftime("%Y-%m-%d")
                try:
                    html = generator.generate_daily_report(date_str)
                except Exception as e1:
                    logger.warning("日汇总报告异常: %s", e1)
                    html = None
                # v4.50: generate_daily_report 内部 catch-all 可能返回错误页，
                # 需检测并回退到单会话报告
                if html is None or "生成报告时出错" in html:
                    if html is not None:
                        logger.warning("日汇总报告返回错误页，回退到单会话报告")
                    try:
                        html = generator.generate_report_with_insights(self._session_id)
                    except Exception as e2:
                        try:
                            html = generator.generate_report(self._session_id)
                        except Exception as e3:
                            html = generator._error_html(str(e3))
            else:
                try:
                    html = generator.generate_report_with_insights(self._session_id)
                except Exception as e:
                    logger.warning("Insights 快照失败，回退到基础报告: %s", e)
                    try:
                        html = generator.generate_report(self._session_id)
                    except Exception as e2:
                        logger.error("基础报告也失败: %s", e2)
                        html = self._error_report_html(str(e2))

            # v4.33: 缓存 HTML（5 分钟 TTL）
            self._report_html_cache[cache_key] = (html, _time.time())
            # 限制缓存条目
            if len(self._report_html_cache) > 3:
                oldest = next(iter(self._report_html_cache))
                del self._report_html_cache[oldest]

            os.makedirs("reports", exist_ok=True)
            report_path = f"reports/{self._session_id}.html"
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(html)

            logger.info("报告快照已生成: %s (会话继续)", report_path)
            return os.path.abspath(report_path)
        except Exception as e:
            logger.warning("生成报告快照失败: %s", e)
            return None

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
                self._gamification.on_session_end(session, avg_focus)

            # 2. 生成含 insights 的 HTML 报告
            from reporter.report_html import create_html_generator
            import os

            generator = create_html_generator(self._db)
            try:
                html = generator.generate_report_with_insights(self._session_id)
            except Exception as e:
                logger.warning("Insights 报告失败，回退到基础报告: %s", e)
                try:
                    html = generator.generate_report(self._session_id)
                except Exception as e2:
                    logger.error("基础报告也失败: %s", e2)
                    html = self._error_report_html(str(e2))

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

        # v4.17: 关闭语音助手                    # v4.49+: 语音已移除
        # if hasattr(self, '_voice_asst') and self._voice_asst is not None:
        #     self._voice_asst.shutdown()

        # v4.22: 停止 Web 仪表盘
        if hasattr(self, '_web_dashboard') and self._web_dashboard is not None:
            try:
                self._web_dashboard.stop()
            except Exception:
                pass

        # 恢复信号处理器
        if self._original_sigint:
            signal.signal(signal.SIGINT, self._original_sigint)
        if self._original_sigterm:
            signal.signal(signal.SIGTERM, self._original_sigterm)

        # 关闭检测器 — H-13: 异常用 logger.exception 记录完整 traceback
        if self._face_detector:
            try:
                self._face_detector.stop_async()  # v4.29: 先停异步线程
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
        logger.info("v4.2 校准模块启动 - 释放主程序摄像头 + 暂停人脸检测")
        # v4.33: 先停止主检测器异步 worker，避免校准期间两个 FaceLandmarker 双倍显存
        _fd = getattr(self, '_face_detector', None)
        if _fd is not None:
            try:
                _fd.stop_async()
            except Exception:
                pass
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
            logger.info("v4.2 校准结束 - 重新启动主程序摄像头 + 恢复人脸检测")
            # v4.33: 先重启摄像头，再恢复人脸检测异步 worker
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
            # v4.33: 摄像头重启后恢复人脸检测异步 worker
            _fd = getattr(self, '_face_detector', None)
            if _fd is not None:
                try:
                    _fd.start_async()
                except Exception:
                    pass

    def _apply_v4_2_calibration_result(self, result: CalibrationResult) -> None:
        """应用 v4.2 校准结果到各 detector。"""
        if hasattr(self, '_eye_detector') and self._eye_detector is not None:
            self._eye_detector.set_baseline(result.signal.ear_mean)
            # P0: 接通 final_adjustment_factor (基于眨眼计数校准的检测误差补偿)
            if hasattr(self._eye_detector, 'set_adjustment_factor'):
                self._eye_detector.set_adjustment_factor(result.final_adjustment_factor)
            if hasattr(self._focus_analyzer, 'set_adjustment_factor'):
                self._focus_analyzer.set_adjustment_factor(result.final_adjustment_factor)

        # P1: 头部姿态参数接通 — 让 focus_analyzer 的 head_score 反映用户的真实头动范围
        yaw_std = pitch_std = None
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

        # v4.39: 完整持久化校准数据（yaw_std/pitch_std/cqs/glasses_mode）
        if self._db and self._session_id:
            self._db.update_session(
                self._session_id,
                baseline_ear=result.signal.ear_mean,
                baseline_blink_rate=result.baseline_blink_rate,
                baseline_yaw_std=yaw_std,
                baseline_pitch_std=pitch_std,
                cqs_score=result.cqs,
                glasses_mode="with_glasses" if result.signal.glasses_mode else "without_glasses",
                is_calibrated=True,
            )

        # v4.13: 校准完成后标记已校准 + 更新状态
        self._calib_loaded = True
        if self._qt_window is not None:
            self._qt_window.set_calibration_status(True)

        # v4.50: 校准数据持久化到文件
        self._save_calibration_to_file(result)

        logger.info(
            "v4.2 校准结果已应用: EAR=%.4f, 眨眼阈值=%.4f, adjustment=%.3f",
            result.signal.ear_mean,
            result.final_blink_threshold,
            result.final_adjustment_factor,
        )

    def _save_calibration_to_file(self, result: "CalibrationResult") -> None:
        """v4.50: 将校准结果保存到 JSON 文件，方便跨会话复用。"""
        import json
        try:
            from calibration.result import signal_to_head_pose_std
            yaw_std, pitch_std = signal_to_head_pose_std(result.signal)
        except Exception:
            yaw_std = pitch_std = None

        data = {
            "ear_mean": result.signal.ear_mean,
            "yaw_std": yaw_std,
            "pitch_std": pitch_std,
            "baseline_blink_rate": result.baseline_blink_rate,
            "blink_threshold": result.final_blink_threshold,
            "squint_threshold": result.final_squint_threshold,
            "adjustment_factor": result.final_adjustment_factor,
            "cqs": result.cqs,
            "glasses_mode": result.signal.glasses_mode,
            "timestamp": datetime.now().isoformat(),
        }
        try:
            os.makedirs(os.path.dirname(self._CALIBRATION_FILE), exist_ok=True)
            with open(self._CALIBRATION_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("校准数据已持久化: %s", self._CALIBRATION_FILE)
        except Exception as e:
            logger.warning("保存校准数据失败: %s", e)

    def apply_saved_calibration(self) -> bool:
        """v4.50: 从文件加载已保存的校准数据并应用到各模块。

        由托盘菜单"应用已有校准数据"调用。
        若无校准数据文件，显示提示。
        """
        import json
        if not os.path.exists(self._CALIBRATION_FILE):
            logger.warning("无已保存的校准数据: %s", self._CALIBRATION_FILE)
            if self._qt_window is not None:
                from PyQt5.QtWidgets import QSystemTrayIcon
                try:
                    self._qt_window.show_calibration_not_found()
                except Exception:
                    pass
            return False

        try:
            with open(self._CALIBRATION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("读取校准数据失败: %s", e)
            return False

        ear = data.get("ear_mean")
        yaw_std = data.get("yaw_std")
        pitch_std = data.get("pitch_std")
        blink_rate = data.get("baseline_blink_rate")

        if ear is None or ear <= 0:
            logger.warning("校准数据无效: ear_mean 缺失或为零")
            return False

        # 应用到各 detector
        if self._eye_detector is not None:
            self._eye_detector.set_baseline(ear)
            adj = data.get("adjustment_factor")
            if adj and hasattr(self._eye_detector, 'set_adjustment_factor'):
                self._eye_detector.set_adjustment_factor(adj)

        if self._focus_analyzer is not None and hasattr(self._focus_analyzer, 'set_baseline'):
            self._focus_analyzer.set_baseline(ear, yaw_std, pitch_std)
            adj = data.get("adjustment_factor")
            if adj and hasattr(self._focus_analyzer, 'set_adjustment_factor'):
                self._focus_analyzer.set_adjustment_factor(adj)

        if blink_rate and self._fatigue_analyzer is not None:
            self._fatigue_analyzer.set_baseline_blink_rate(blink_rate)

        # 持久化到当前会话 DB
        if self._db and self._session_id:
            from storage.models import GlassesMode
            gm = data.get("glasses_mode")
            if gm == "with_glasses":
                glasses_mode_enum = GlassesMode.WITH_GLASSES
            elif gm == "without_glasses":
                glasses_mode_enum = GlassesMode.WITHOUT_GLASSES
            else:
                glasses_mode_enum = None

            self._db.update_session(
                self._session_id,
                baseline_ear=ear,
                baseline_blink_rate=blink_rate,
                baseline_yaw_std=yaw_std,
                baseline_pitch_std=pitch_std,
                cqs_score=data.get("cqs"),
                glasses_mode=glasses_mode_enum,
                is_calibrated=True,
            )

        self._calib_loaded = True
        if self._qt_window is not None:
            self._qt_window.set_calibration_status(True)

        logger.info("已从文件加载校准数据: EAR=%.4f, blink=%.1f", ear, blink_rate or 0)
        return True


def _check_single_instance() -> bool:
    """v4.25: 单实例锁 — 三重验证

    1. Named Mutex（内核级别，进程崩溃自动释放）
    2. PID 文件（交叉验证进程 exe 名，防 PID 重用误判）
    3. 兜底：任一验证失败 → 放行（不阻塞启动）
    """
    import ctypes
    import os as _os
    try:
        kernel32 = ctypes.windll.kernel32
        MUTEX_NAME = "Local\\EyeFocus-Insight-Instance"

        # ── 1) Named Mutex ──
        mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not mutex:
            return True  # 创建失败 → 放行
        exists = kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS

        if not exists:
            # 首次运行：写 PID 文件供交叉验证
            _write_instance_pid()
            return True

        # ── 2) Mutex 已存在 → PID 交叉验证 ──
        kernel32.CloseHandle(mutex)
        if _verify_previous_instance():
            return False  # 前一个实例确实还活着
        # 3) 前一个实例已死（僵尸/崩溃）→ 覆盖
        _write_instance_pid()
        return True

    except Exception:
        return True  # 兜底：放行


def _instance_pid_path() -> str:
    """PID 文件路径（系统临时目录）"""
    import os
    tmp = os.environ.get('TEMP', os.path.expanduser('~'))
    return os.path.join(tmp, '.eyefocus_pid')


def _write_instance_pid() -> None:
    """写入当前 PID 到文件"""
    import os
    try:
        pid_path = _instance_pid_path()
        os.makedirs(os.path.dirname(pid_path), exist_ok=True)
        with open(pid_path, 'w') as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def _verify_previous_instance() -> bool:
    """验证前一个实例是否仍在运行

    读取 PID 文件 → 检查进程是否存在 → 检查 exe 名是否匹配。
    只有三者都匹配才视为"前一个实例还活着"。
    """
    import os
    import ctypes
    pid_path = _instance_pid_path()

    if not os.path.exists(pid_path):
        return False  # 无 PID 文件 → 旧实例已退出

    try:
        with open(pid_path, 'r') as f:
            old_pid_str = f.read().strip()
        old_pid = int(old_pid_str)
    except (ValueError, OSError):
        return False

    if old_pid == os.getpid():
        return True  # 同一进程（不应发生）

    # 检查进程是否存在 — PROCESS_QUERY_LIMITED_INFORMATION
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, old_pid)
    if not h:
        return False  # 进程已不存在

    try:
        # 检查 exe 路径是否包含 eyefocus
        buf = ctypes.create_unicode_buffer(260)
        size = ctypes.c_ulong(260)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            exe_path = buf.value[:size.value]
            if 'eyefocus' in exe_path.lower() or 'EyeFocus' in exe_path:
                return True  # 确实是前一个 EyeFocus 实例
    finally:
        kernel32.CloseHandle(h)

    return False  # PID 被其他程序复用


def main() -> None:
    """主函数"""
    # v4.16: 单实例检查
    if not _check_single_instance():
        print("EyeFocus Insight 已在运行中，请查看系统托盘。")
        sys.exit(0)

    # v4.0.2 修复 B4+B6: 屏蔽 MediaPipe Google telemetry 上报 + 统一 absl 日志风格
    # 1) 禁用 mediapipe 上报 (clearcut_uploader)
    os.environ.setdefault("GLOG_logtostderr", "0")
    os.environ.setdefault("MEDIAPIPE_DISABLE_GPU", "0")  # v4.33: 默认启用 GPU；出问题时设 =1 回退 CPU
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
    # 强制退出进程（防止非 daemon 线程 / Qt 引用环阻塞退出）
    logger.info("应用关闭完成，退出进程")
    sys.exit(0)


if __name__ == "__main__":
    main()

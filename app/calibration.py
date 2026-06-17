"""
app/calibration.py — 校准流程回调与协调器

从 main.py strangler 提取，不改变行为。
"""

import logging
import time
from typing import Optional

from analyzer.user_calibration import CalibrationState, UserCalibrationManager
from detector.eye_aspect import EyeAspectDetector
from gui.overlay import FocusOverlay
from storage.db import DatabaseManager
from storage.models import CalibrationResult

logger = logging.getLogger("eyefocus.main")


class CalibrationFlowCallbacks:
    """校准流程回调实现"""

    def __init__(self, app: 'EyeFocusApp'):  # noqa: F821 — forward ref, resolved at runtime
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
            if len(self._input_buffer) < 3:
                self._input_buffer += digit
            else:
                self._input_buffer = self._input_buffer[-2:] + digit
            self.app._overlay.update_input_buffer(self._input_buffer)

    def on_enter_pressed(self) -> None:
        """确认输入"""
        if hasattr(self.app, '_calib_manager') and self.app._calib_manager:
            from analyzer.user_calibration import CalibrationState
            if self.app._calib_manager.state == CalibrationState.BLINK_INPUT:
                try:
                    count = int(self._input_buffer) if self._input_buffer else 0
                    self.app._calib_manager.on_user_input(count)
                except ValueError:
                    logger.warning("无效输入: %s", self._input_buffer)
                self._input_buffer = ""
                self._input_mode = False
                return

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
    """校准流程协调器 - 负责校准流程与 UI 的协调"""

    def __init__(
        self,
        calib_manager: UserCalibrationManager,
        overlay: FocusOverlay,
        app: "EyeFocusApp",  # noqa: F821 — forward ref, resolved at runtime
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

        self._input_buffer: str = ""
        self._input_mode: bool = False
        self._last_tick_time: float = 0.0

        self._calib_manager.set_ear_callback(self._get_ear)
        self._calib_manager.set_head_pose_callback(self._get_head_pose)

    def _get_ear(self) -> float:
        if self._eye_detector:
            return self._eye_detector.get_current_ear()
        return 0.0

    def _get_head_pose(self) -> tuple:
        fp = self._app._frame_processor
        return (fp._latest_yaw, fp._latest_pitch)

    def start(self) -> None:
        self._input_buffer = ""
        self._input_mode = False
        self._last_tick_time = time.time()
        self._calib_manager.start()
        logger.info("校准流程已启动, state=%s", self._calib_manager.state)

    def tick(self) -> None:
        if self._calib_manager.state == CalibrationState.IDLE:
            return
        current_time = time.time()
        if current_time - self._last_tick_time >= 1.0:
            self._calib_manager.tick()
            self._last_tick_time = current_time

    def cancel(self) -> None:
        if self._calib_manager:
            self._calib_manager.on_cancel()
        self._overlay.hide_calibration_ui()
        self._input_buffer = ""
        self._input_mode = False
        logger.info("校准已取消")

    def is_active(self) -> bool:
        return self._calib_manager.state != CalibrationState.IDLE

    @property
    def state(self) -> CalibrationState:
        return self._calib_manager.state

    @property
    def input_mode(self) -> bool:
        return self._input_mode

    def handle_digit_input(self, digit: str) -> None:
        if self._input_mode:
            if len(self._input_buffer) < 3:
                self._input_buffer += digit
            else:
                self._input_buffer = self._input_buffer[-2:] + digit
            self._overlay.update_input_buffer(self._input_buffer)

    def handle_enter_pressed(self) -> None:
        if self._calib_manager and self._calib_manager.state == CalibrationState.BLINK_INPUT:
            try:
                count = int(self._input_buffer) if self._input_buffer else 0
                self._calib_manager.on_user_input(count)
            except ValueError:
                logger.warning("无效输入: %s", self._input_buffer)
            self._input_buffer = ""
            self._input_mode = False
            return

        self._input_buffer = ""
        self._input_mode = False

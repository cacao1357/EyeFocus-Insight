"""calibration/flow.py — CalibrationFlow 编排器

单线程主循环 + 状态机：
  WAITING_TO_START_PHASE → PHASE_RUNNING → PHASE_SUMMARY_(SUCCESS|FAILED)
  → 推进/重做/跳过/取消 → 下一阶段 → ... → FINAL_SUMMARY → DONE / CANCELLED

设计依据：spec §3.1 主循环 + §3.2 状态机。
"""
import logging
import time
from datetime import datetime
from typing import List, Optional

import cv2

from calibration.audio.beep import Beep
from calibration.audio.tts import TTS
from calibration.config import CalibrationConfig
from calibration.input_handler import InputHandler
from calibration.phases.auto_baseline import AutoBaselinePhase
from calibration.phases.base import Phase, PhaseResult
from calibration.phases.blink_count import BlinkCountPhase, BlinkCountState
from calibration.phases.closed_eyes import ClosedEyesPhase
from calibration.phases.head_pose import HeadPosePhase
from calibration.phases.squint import SquintPhase
from calibration.result import (
    BlinkCalibrationRound, CalibrationResult, CalibrationSignal,
)
from calibration.ui.layout import compose
from calibration.ui.panel import (
    FlowState, Panel, PhaseDisplayInfo, UIAction,
)

logger = logging.getLogger("eyefocus.calibration.flow")

WINDOW_NAME = "EyeFocus 校准"


class CalibrationFlow:
    """完整校准流程编排。"""

    def __init__(self, session_id: str, config: CalibrationConfig):
        self.session_id = session_id
        self.config = config

        self._state: FlowState = FlowState.WAITING_TO_START_PHASE
        self._current_phase_index: int = 0
        self._current_phase: Optional[Phase] = None
        self._phase_start_time: float = 0.0
        self._phase_results: List[Optional[PhaseResult]] = [None] * 5
        self._input_buffer: str = ""
        self._cancelled: bool = False
        self._done: bool = False
        self._user_accepted: bool = False
        self._consecutive_failures: int = 0

        # 子系统（运行时注入；测试时 mock）
        self._cap = None
        self._face_detector = None
        self._beep = Beep()
        self._tts = TTS(rate=config.tts_rate) if config.audio_enabled else _MutedTTS()
        self._panel = Panel(width=640, height=config.ui_panel_height_px)
        self._input: Optional[InputHandler] = None

        # 初始化第 0 阶段
        self._current_phase = self._build_phase(0)

    def run(self) -> Optional[CalibrationResult]:
        """主入口 — 阻塞运行直到完成 / 取消 / 异常。"""
        try:
            self._setup()
            while not (self._done or self._cancelled):
                self._tick_once()
            return self._compute_result() if self._user_accepted else None
        except Exception:
            logger.exception("校准流程崩溃")
            return None
        finally:
            self._teardown()

    def _setup(self) -> None:
        self._cap = cv2.VideoCapture(0)
        if not self._cap.isOpened():
            raise RuntimeError("无法打开摄像头")
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
        # panel_y_offset = 视频区高度（480）。cv2 鼠标事件返回 composed 坐标，
        # button.rect 是 panel 局部坐标。InputHandler 内部做转换（BUG-2 修复）。
        self._input = InputHandler(WINDOW_NAME, panel_y_offset=480)
        # 初始化 face detector（沿用主项目模块，默认参数与 main.py 一致）
        from detector.face_mesh import create_face_mesh_detector
        self._face_detector = create_face_mesh_detector()

    def _teardown(self) -> None:
        if self._cap is not None:
            self._cap.release()
        try:
            cv2.destroyWindow(WINDOW_NAME)
        except Exception:
            pass
        self._tts.shutdown()

    def _tick_once(self) -> None:
        """一帧主循环。"""
        ret, frame = self._cap.read()
        if not ret:
            return

        # 检测
        ear, yaw, pitch = self._extract_metrics(frame)

        # 喂当前阶段
        if self._state == FlowState.PHASE_RUNNING and self._current_phase is not None:
            elapsed = time.time() - self._phase_start_time
            self._current_phase.feed_frame(ear, yaw, pitch, elapsed)

            # 特殊：BlinkCount 阶段处理用户输入触发
            if isinstance(self._current_phase, BlinkCountPhase):
                round_elapsed = elapsed - (self._current_phase.current_round - 1) * self.config.blink_round_seconds
                if round_elapsed >= self.config.blink_round_seconds:
                    self._current_phase.on_round_time_up()
                    self._state = FlowState.BLINK_INPUT_AWAITING
                    self._tts.say("请输入你眨眼的次数")
            else:
                if self._current_phase.is_complete(elapsed):
                    self._on_phase_time_up()

        # 渲染
        info = self._build_display_info()
        panel_img = self._panel.render(info)
        composed = compose(frame, panel_img)
        cv2.imshow(WINDOW_NAME, composed)

        # 注册按钮 + 收输入
        self._input.register_buttons(self._panel.get_buttons(info))
        action, digit = self._input.poll(self._state)

        # 检查窗口被关
        try:
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                self._cancelled = True
                return
        except cv2.error:
            self._cancelled = True
            return

        self._handle_action(action, digit)

    def _extract_metrics(self, frame):
        """从帧中提取 EAR/yaw/pitch（沿用主项目模块）。

        BUG-4 修复：必须用 detect_from_frame(frame, timestamp_ms)，
        实际方法名是 detect_from_frame (不是 detect)。
        """
        if self._face_detector is None:
            return (None, None, None)
        try:
            timestamp_ms = int(time.time() * 1000)
            face_result = self._face_detector.detect_from_frame(frame, timestamp_ms)
        except Exception:
            return (None, None, None)
        if not face_result or not getattr(face_result, 'detected', False):
            return (None, None, None)
        ear, yaw, pitch = None, None, None
        try:
            from detector.eye_aspect import compute_ear_from_landmarks
            ear = compute_ear_from_landmarks(face_result.landmarks)
        except Exception:
            pass
        try:
            from detector.head_pose import compute_head_pose_from_matrix
            yaw, pitch, _roll = compute_head_pose_from_matrix(face_result.transformation_matrix)
        except Exception:
            pass
        return (ear, yaw, pitch)

    def _handle_action(self, action: UIAction, digit: Optional[str]) -> None:
        if action == UIAction.NONE:
            return
        if action == UIAction.CANCEL:
            self._cancelled = True
            self._tts.say("已取消校准")
            return

        if self._state == FlowState.WAITING_TO_START_PHASE:
            if action == UIAction.PROCEED:
                self._start_phase()
        elif self._state == FlowState.PHASE_SUMMARY_SUCCESS:
            if action == UIAction.PROCEED:
                self._advance_to_next_phase()
            elif action == UIAction.RETRY_PHASE:
                if self._current_phase is not None:
                    self._current_phase.reset()
                self._state = FlowState.PHASE_RUNNING
                self._phase_start_time = time.time()
        elif self._state == FlowState.PHASE_SUMMARY_FAILED:
            if action == UIAction.RETRY_PHASE:
                self._consecutive_failures += 1
                if self._current_phase is not None:
                    self._current_phase.reset()
                self._state = FlowState.PHASE_RUNNING
                self._phase_start_time = time.time()
            elif action == UIAction.SKIP_PHASE:
                self._consecutive_failures = 0
                self._advance_to_next_phase()
        elif self._state == FlowState.BLINK_INPUT_AWAITING:
            self._handle_blink_input_action(action, digit)
        elif self._state == FlowState.FINAL_SUMMARY:
            if action == UIAction.PROCEED:
                self._done = True
                self._user_accepted = True
            elif action == UIAction.RETRY_PHASE:
                # 重新校准：清状态回阶段 0
                self._current_phase_index = 0
                self._current_phase = self._build_phase(0)
                self._phase_results = [None] * 5
                self._consecutive_failures = 0
                self._state = FlowState.WAITING_TO_START_PHASE

    def _handle_blink_input_action(self, action, digit) -> None:
        if action == UIAction.DIGIT and digit is not None:
            self._input_buffer += digit
        elif action == UIAction.BACKSPACE and self._input_buffer:
            self._input_buffer = self._input_buffer[:-1]
        elif action == UIAction.SUBMIT and self._input_buffer:
            assert isinstance(self._current_phase, BlinkCountPhase)
            try:
                count = int(self._input_buffer)
            except ValueError:
                return
            accepted = self._current_phase.on_user_input(count)
            if accepted:
                self._input_buffer = ""
                if self._current_phase.state == BlinkCountState.DONE:
                    # 整个 BlinkCountPhase 完成
                    result = self._current_phase.evaluate()
                    self._phase_results[self._current_phase_index] = result
                    self._state = FlowState.PHASE_SUMMARY_SUCCESS if result.success else FlowState.PHASE_SUMMARY_FAILED
                else:
                    # 下一轮继续
                    self._state = FlowState.PHASE_RUNNING
                    self._phase_start_time = time.time()

    def _start_phase(self) -> None:
        self._state = FlowState.PHASE_RUNNING
        self._phase_start_time = time.time()
        self._beep.phase_start()
        if self._current_phase is not None and self._current_phase.tts_intro:
            self._tts.say(self._current_phase.tts_intro)

    def _on_phase_time_up(self) -> None:
        if self._current_phase is None:
            return
        result = self._current_phase.evaluate()
        self._phase_results[self._current_phase_index] = result
        if result.success:
            self._state = FlowState.PHASE_SUMMARY_SUCCESS
            self._beep.phase_success()
            self._consecutive_failures = 0
            if self._current_phase.tts_complete:
                self._tts.say(self._current_phase.tts_complete)
        else:
            self._state = FlowState.PHASE_SUMMARY_FAILED
            self._beep.phase_failed()
            if result.failure_diagnosis:
                self._tts.say(result.failure_diagnosis)

    def _advance_to_next_phase(self) -> None:
        self._current_phase_index += 1
        if self._current_phase_index >= 5:
            self._state = FlowState.FINAL_SUMMARY
            self._beep.calibration_complete()
            self._tts.say("校准完成")
        else:
            self._current_phase = self._build_phase(self._current_phase_index)
            self._state = FlowState.WAITING_TO_START_PHASE

    def _build_phase(self, index: int) -> Phase:
        c = self.config
        if index == 0:
            return AutoBaselinePhase(c.auto_baseline_seconds)
        if index == 1:
            baseline = self._get_baseline_ear()
            return ClosedEyesPhase(c.closed_eyes_seconds, c.open_eyes_verify_seconds,
                                  baseline, c.closed_eyes_min_ratio)
        if index == 2:
            baseline = self._get_baseline_ear()
            ear_min = self._get_ear_min()
            return SquintPhase(c.squint_seconds, baseline, c.squint_baseline_ratio, ear_min)
        if index == 3:
            return HeadPosePhase(c.head_direction_seconds, c.head_direction_min_degrees)
        if index == 4:
            baseline = self._get_baseline_ear()
            ear_min = self._get_ear_min()
            return BlinkCountPhase(c.blink_round_seconds, c.blink_rounds_count,
                                  baseline, ear_min, c.blink_count_min, c.blink_count_max)
        raise ValueError(f"Invalid phase index {index}")

    def _get_baseline_ear(self) -> float:
        r0 = self._phase_results[0]
        return r0.summary["ear_mean"] if (r0 and r0.success) else 0.30

    def _get_ear_min(self) -> float:
        r1 = self._phase_results[1]
        return r1.summary["ear_min"] if (r1 and r1.success) else 0.08

    def _build_display_info(self) -> PhaseDisplayInfo:
        if self._current_phase is None:
            return PhaseDisplayInfo(state=self._state, phase_index=1, phase_total=5,
                                    phase_name="", instruction="")
        elapsed = time.time() - self._phase_start_time if self._state == FlowState.PHASE_RUNNING else 0.0
        fb = self._current_phase.get_live_feedback(elapsed)
        info = PhaseDisplayInfo(
            state=self._state,
            phase_index=self._current_phase_index + 1,
            phase_total=5,
            phase_name=self._current_phase.name,
            instruction=self._current_phase.tts_intro,
            remaining_sec=fb.remaining_sec,
            sample_count=fb.sample_count,
            quality_hint=fb.quality_hint,
        )
        # 摘要状态时填 summary_text
        if self._state in (FlowState.PHASE_SUMMARY_SUCCESS, FlowState.PHASE_SUMMARY_FAILED):
            r = self._phase_results[self._current_phase_index]
            if r is not None:
                if r.success:
                    info.summary_text = " ".join(f"{k}={v}" for k, v in list(r.summary.items())[:3])
                else:
                    info.summary_text = r.failure_diagnosis or ""
        # BLINK_INPUT 时填检出数 + 输入缓冲
        if self._state == FlowState.BLINK_INPUT_AWAITING and isinstance(self._current_phase, BlinkCountPhase):
            info.program_blink_count = self._current_phase.get_round_detected_blinks()
            info.user_input_buffer = self._input_buffer
        # FINAL 时填总结
        if self._state == FlowState.FINAL_SUMMARY:
            info.final_summary = self._build_final_summary_dict()
        return info

    def _build_final_summary_dict(self) -> dict:
        baseline_ear = self._get_baseline_ear()
        baseline_blink_rate = 15.0
        r4 = self._phase_results[4]
        if r4 and r4.success:
            baseline_blink_rate = r4.summary.get("baseline_blink_rate", 15.0)
        return {
            "EAR 基线": f"{baseline_ear:.3f}",
            "眨眼阈值": f"{baseline_ear * 0.75:.3f}",
            "眨眼率": f"{baseline_blink_rate:.1f}/min",
            "CQS": f"{self._compute_cqs():.2f}",
        }

    def _compute_cqs(self) -> float:
        passed = sum(1 for r in self._phase_results if r is not None and r.success)
        return passed / 5.0

    def _compute_result(self) -> Optional[CalibrationResult]:
        if self._cancelled or not self._user_accepted:
            return None
        r0 = self._phase_results[0]
        if r0 is None or not r0.success:
            return None
        signal = CalibrationSignal(
            ear_mean=r0.summary["ear_mean"],
            ear_min=self._get_ear_min(),
            ear_mid=self._get_ear_mid(),
            yaw_mean=r0.summary.get("yaw_mean", 0.0),
            yaw_range=self._get_yaw_range(),
            pitch_mean=r0.summary.get("pitch_mean", 0.0),
            pitch_range=self._get_pitch_range(),
            glasses_mode=False,  # T-CAL-XX 后续可接 glasses detector
            timestamp=time.time(),
        )
        r4 = self._phase_results[4]
        rounds = list(r4.summary["rounds"]) if (r4 and r4.success) else []
        final_adj = r4.summary.get("final_adjustment_factor", 1.0) if (r4 and r4.success) else 1.0
        baseline_blink_rate = r4.summary.get("baseline_blink_rate", 15.0) if (r4 and r4.success) else 15.0
        return CalibrationResult(
            session_id=self.session_id,
            timestamp=datetime.now(),
            signal=signal,
            blink_rounds=rounds,
            final_adjustment_factor=final_adj,
            final_blink_threshold=signal.ear_mean * 0.75 * final_adj,
            final_squint_threshold=signal.ear_mean * 0.75,
            baseline_blink_rate=baseline_blink_rate,
            cqs=self._compute_cqs(),
            is_accepted=self._user_accepted,
        )

    def _get_ear_mid(self) -> float:
        r2 = self._phase_results[2]
        return r2.summary["ear_mid"] if (r2 and r2.success) else self._get_baseline_ear() * 0.75

    def _get_yaw_range(self) -> tuple:
        r3 = self._phase_results[3]
        if r3 and r3.success:
            return (r3.summary["yaw_left_max"], r3.summary["yaw_right_max"])
        return (-15.0, 15.0)

    def _get_pitch_range(self) -> tuple:
        r3 = self._phase_results[3]
        if r3 and r3.success:
            return (r3.summary["pitch_up_max"], r3.summary["pitch_down_max"])
        return (-10.0, 10.0)


class _MutedTTS:
    """audio_enabled=False 时的占位。"""
    def say(self, text: str) -> None:
        pass
    def shutdown(self) -> None:
        pass

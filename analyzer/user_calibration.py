"""
analyzer/user_calibration.py — 用户校准管理器

提供 UserCalibrationManager 类：
- 事件驱动状态机
- 6 阶段校准流程
- 回调接口通知外部

阶段：
0. 自动基线采集（7秒）
1. 闭眼校准（5秒）
2. 睁眼恢复（3秒）
3. 眯眼校准（8秒）
4. 头部姿态（12秒）
5. 眨眼计数（3轮×20秒）
"""

import logging
import math
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, List, Optional, Callable
from datetime import datetime

from storage.models import CalibrationSignal, BlinkCalibrationRound, CalibrationResult

logger = logging.getLogger("eyefocus.analyzer")


# 默认阶段配置
DEFAULT_PHASES = {
    "auto_calib": 7,       # 阶段0：自动基线采集
    "closed_eyes": 5,      # 阶段1：闭眼校准
    "open_eyes": 3,        # 阶段2：睁眼恢复
    "squint": 8,           # 阶段3：眯眼校准
    "head_pose": 12,       # 阶段4：头部姿态
    # 阶段5：眨眼计数（动态，blink_rounds × blink_duration）
}

# 眨眼/眯眼判定阈值
BLINK_DURATION_THRESHOLD = 0.4  # 400ms


class CalibrationCallbacks(Protocol):
    """校准过程回调接口"""

    def on_phase_start(self, phase: int, phase_name: str, instruction: str) -> None:
        """新阶段开始"""
        ...

    def on_countdown_tick(self, remaining: int) -> None:
        """倒计时每秒更新"""
        ...

    def on_detected_signals_update(self, ear: float, yaw: float, pitch: float) -> None:
        """实时信号更新"""
        ...

    def on_phase_complete(self, phase: int, collected_data: dict) -> None:
        """阶段完成"""
        ...

    def on_blink_round_start(self, round_num: int, total_rounds: int, duration: int) -> None:
        """眨眼校准轮开始"""
        ...

    def on_blink_round_tick(self, remaining: int, detected_blinks: int) -> None:
        """眨眼校准轮每秒更新"""
        ...

    def on_blink_round_end(self, round_num: int, program_count: int) -> None:
        """眨眼校准轮结束，等待用户输入"""
        ...

    def on_calibration_complete(self, result: CalibrationResult) -> None:
        """校准全部完成"""
        ...

    def on_error(self, phase: int, message: str) -> None:
        """校准过程出错"""
        ...


class CalibrationState(StrEnum):
    """校准状态枚举"""
    IDLE = "idle"
    AUTO_CALIB = "auto_calib"
    CLOSED_EYES = "closed_eyes"
    OPEN_EYES = "open_eyes"
    SQUINT = "squint"
    HEAD_UP = "head_up"
    HEAD_DOWN = "head_down"
    HEAD_LEFT = "head_left"
    HEAD_RIGHT = "head_right"
    BLINK_COUNTING = "blink_counting"
    BLINK_INPUT = "blink_input"
    FINISHED = "finished"
    ERROR = "error"


@dataclass
class SignalCollector:
    """信号采集器（用于阶段0）"""
    ears: List[float] = field(default_factory=list)
    yaws: List[float] = field(default_factory=list)
    pitches: List[float] = field(default_factory=list)
    ear_min: float = 999.0
    yaw_left_max: float = -math.inf
    yaw_right_max: float = math.inf
    pitch_up_max: float = -math.inf
    pitch_down_max: float = math.inf


class BlinkRoundCollector:
    """眨眼轮采集器"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.start_time: Optional[float] = None
        self.detected_blinks: int = 0
        self.detected_squints: int = 0
        self._in_blink: bool = False
        self._blink_start_time: Optional[float] = None

    def record_frame(self, ear: float, ear_threshold: float, squint_threshold: float, current_time: float):
        """记录一帧数据"""
        if ear < squint_threshold:
            if not self._in_blink:
                self._in_blink = True
                self._blink_start_time = current_time
        else:
            if self._in_blink and self._blink_start_time is not None:
                duration = current_time - self._blink_start_time
                if duration < BLINK_DURATION_THRESHOLD:
                    self.detected_blinks += 1
                else:
                    self.detected_squints += 1
                self._in_blink = False
                self._blink_start_time = None


class UserCalibrationManager:
    """用户校准管理器（事件驱动）"""

    def __init__(
        self,
        callbacks: CalibrationCallbacks,
        blink_rounds: int = 3,
        blink_duration: int = 20,
        phases: dict = None,
        session_id: Optional[str] = None,
    ):
        self.callbacks = callbacks
        self.blink_rounds = blink_rounds
        self.blink_duration = blink_duration
        self.phases = phases or DEFAULT_PHASES.copy()
        self._session_id = session_id

        self._state = CalibrationState.IDLE
        self._current_phase = 0
        self._signal_collector = SignalCollector()
        self._blink_collector = BlinkRoundCollector()
        self._blink_rounds_data: List[BlinkCalibrationRound] = []

        self._phase_start_time: Optional[float] = None
        self._current_blink_round = 0
        self._squint_ear_values: List[float] = []

        self._get_ear_callback: Optional[Callable[[], float]] = None
        self._get_head_pose_callback: Optional[Callable[[], tuple]] = None
        self._get_blink_count_callback: Optional[Callable[[], int]] = None

    def set_ear_callback(self, callback: Callable[[], float]) -> None:
        """设置获取实时 EAR 的回调"""
        self._get_ear_callback = callback

    def set_head_pose_callback(self, callback: Callable[[], tuple]) -> None:
        """设置获取实时头部姿态的回调"""
        self._get_head_pose_callback = callback

    def set_blink_detector_callback(self, callback: Callable[[], int]) -> None:
        """设置获取眨眼次数的回调"""
        self._get_blink_count_callback = callback

    @property
    def state(self) -> str:
        """当前状态"""
        return self._state

    @property
    def current_phase(self) -> int:
        """当前阶段号"""
        return self._current_phase

    def start(self) -> None:
        """开始校准流程"""
        if self._state != CalibrationState.IDLE:
            logger.warning("校准已在进行中")
            return

        self._reset()
        self._state = CalibrationState.AUTO_CALIB
        self._current_phase = 0
        self._phase_start_time = time.time()

        phase_name, instruction = self._get_phase_info(0)
        self.callbacks.on_phase_start(0, phase_name, instruction)
        logger.info("校准开始: 阶段0 自动基线采集")

    def on_user_ready(self) -> None:
        """用户按 Enter确认"""
        if self._state == CalibrationState.AUTO_CALIB:
            self._run_auto_calib()

    def add_frame(self, ear: float, yaw: float, pitch: float) -> bool:
        """每帧采集数据（用于 AUTO_CALIB 阶段）

        在 _process_frame() 中每帧调用，而不是依赖 tick() 每秒调用。

        Args:
            ear: 当前帧的 EAR 值
            yaw: 偏航角（度）
            pitch: 俯仰角（度）

        Returns:
            是否被接受（True 表示有效帧）
        """
        if self._state != CalibrationState.AUTO_CALIB:
            return False

        elapsed = time.time() - self._phase_start_time

        # 采集 EAR 数据
        self._signal_collector.ears.append(ear)
        if ear < self._signal_collector.ear_min:
            self._signal_collector.ear_min = ear

        # 采集头部姿态数据
        self._signal_collector.yaws.append(yaw)
        self._signal_collector.pitches.append(pitch)

        # 每秒更新倒计时回调
        remaining = int(self.phases["auto_calib"] - elapsed)
        if remaining >= 0:
            self.callbacks.on_countdown_tick(remaining)

        # 检查是否完成（7秒到后自动推进）
        if elapsed >= self.phases["auto_calib"]:
            self.callbacks.on_phase_complete(0, {
                "ear_mean": sum(self._signal_collector.ears) / len(self._signal_collector.ears) if self._signal_collector.ears else 0,
                "frame_count": len(self._signal_collector.ears),
            })
            # BUG FIX: Phase 0 (AUTO_CALIB) 完成时需要调用 on_user_ready()
            # 来确保校准结果被正确处理，而不是直接 transition
            # on_user_ready() 会调用 _run_auto_calib() 处理自动校准完成逻辑
            self.on_user_ready()
            return True

        return True

    def on_user_input(self, user_blink_count: int) -> None:
        """用户输入眨眼次数"""
        if self._state != CalibrationState.BLINK_INPUT:
            logger.warning("不在输入状态，忽略输入")
            return
        self._record_blink_round(user_blink_count)

    def on_cancel(self) -> None:
        """用户取消校准"""
        logger.info("用户取消校准")
        self._state = CalibrationState.IDLE
        self._reset()

    def get_current_round_blinks(self) -> int:
        """获取当前轮检测到的眨眼次数"""
        return self._blink_collector.detected_blinks

    def get_current_round_squints(self) -> int:
        """获取当前轮检测到的眯眼次数"""
        return self._blink_collector.detected_squints

    def get_result(self) -> Optional[CalibrationResult]:
        """获取校准结果（仅在 FINISHED 状态有效）"""
        if self._state != CalibrationState.FINISHED:
            return None
        return self._compute_result()

    def _reset(self) -> None:
        """重置内部状态"""
        self._signal_collector = SignalCollector()
        self._blink_collector.reset()
        self._blink_rounds_data.clear()
        self._current_blink_round = 0
        self._squint_ear_values.clear()

    def _get_phase_info(self, phase: int) -> tuple:
        """获取阶段信息"""
        phases = [
            ("自动基线采集", "请保持自然睁眼，系统将自动采集数据..."),
            ("闭眼校准", "请闭眼并保持 5 秒..."),
            ("睁眼恢复", "请睁眼并保持 3 秒..."),
            ("眯眼校准", "请故意眯眼并保持 2-3 秒..."),
            ("头部姿态", "请按照指示移动头部..."),
            ("眨眼计数校准", "即将开始眨眼计数..."),
        ]
        if phase < len(phases):
            return phases[phase]
        return ("未知", "")

    def _run_auto_calib(self) -> None:
        """执行自动基线采集阶段"""
        elapsed = time.time() - self._phase_start_time
        remaining = int(self.phases["auto_calib"] - elapsed)

        if remaining > 0:
            self.callbacks.on_countdown_tick(remaining)

        if self._get_ear_callback:
            ear = self._get_ear_callback()
            self._signal_collector.ears.append(ear)
            if ear < self._signal_collector.ear_min:
                self._signal_collector.ear_min = ear

        if self._get_head_pose_callback:
            yaw, pitch = self._get_head_pose_callback()
            self._signal_collector.yaws.append(yaw)
            self._signal_collector.pitches.append(pitch)

        if elapsed >= self.phases["auto_calib"]:
            self.callbacks.on_phase_complete(0, {
                "ear_mean": sum(self._signal_collector.ears) / len(self._signal_collector.ears) if self._signal_collector.ears else 0,
                "frame_count": len(self._signal_collector.ears),
            })
            self._transition_to_next_phase()

    def tick(self) -> None:
        """定时器触发（每秒调用一次）"""
        if self._state == CalibrationState.IDLE or self._state == CalibrationState.FINISHED:
            return

        elapsed = time.time() - self._phase_start_time
        current_phase_duration = self._get_current_phase_duration()

        # AUTO_CALIB 阶段需要特殊处理（收集数据并自动推进）
        if self._state == CalibrationState.AUTO_CALIB:
            remaining = int(self.phases["auto_calib"] - elapsed)
            if remaining >= 0:
                self.callbacks.on_countdown_tick(remaining)
            self._run_auto_calib()
            return

        # BLINK_COUNTING 阶段：每秒采集眨眼数据
        if self._state == CalibrationState.BLINK_COUNTING:
            self._collect_blink_counting_data()
            if elapsed >= current_phase_duration:
                self._on_blink_counting_complete()
            return

        # 其他阶段：统一倒计时 + 数据采集
        if current_phase_duration > 0:
            remaining = int(current_phase_duration - elapsed)
            if remaining >= 0:
                self.callbacks.on_countdown_tick(remaining)

        self._collect_phase_data()

        if elapsed >= current_phase_duration:
            if current_phase_duration > 0:
                self._on_phase_complete()

    def _get_current_phase_duration(self) -> float:
        """获取当前阶段的时长"""
        if self._state == CalibrationState.AUTO_CALIB:
            return self.phases["auto_calib"]
        elif self._state == CalibrationState.CLOSED_EYES:
            return self.phases["closed_eyes"]
        elif self._state == CalibrationState.OPEN_EYES:
            return self.phases["open_eyes"]
        elif self._state == CalibrationState.SQUINT:
            return self.phases["squint"]
        elif self._state in (CalibrationState.HEAD_UP, CalibrationState.HEAD_DOWN,
                             CalibrationState.HEAD_LEFT, CalibrationState.HEAD_RIGHT):
            return self.phases["head_pose"] / 4
        elif self._state == CalibrationState.BLINK_COUNTING:
            return self.blink_duration
        return 0

    def _collect_phase_data(self) -> None:
        """在当前阶段采集数据"""
        if self._state == CalibrationState.CLOSED_EYES:
            if self._get_ear_callback:
                ear = self._get_ear_callback()
                if ear < self._signal_collector.ear_min:
                    self._signal_collector.ear_min = ear

        elif self._state == CalibrationState.SQUINT:
            if self._get_ear_callback:
                ear = self._get_ear_callback()
                self._squint_ear_values.append(ear)

        elif self._state == CalibrationState.HEAD_UP:
            if self._get_head_pose_callback:
                _, pitch = self._get_head_pose_callback()
                if pitch < self._signal_collector.pitch_up_max:
                    self._signal_collector.pitch_up_max = pitch

        elif self._state == CalibrationState.HEAD_DOWN:
            if self._get_head_pose_callback:
                _, pitch = self._get_head_pose_callback()
                if pitch > self._signal_collector.pitch_down_max:
                    self._signal_collector.pitch_down_max = pitch

        elif self._state == CalibrationState.HEAD_LEFT:
            if self._get_head_pose_callback:
                yaw, _ = self._get_head_pose_callback()
                if yaw < self._signal_collector.yaw_left_max:
                    self._signal_collector.yaw_left_max = yaw

        elif self._state == CalibrationState.HEAD_RIGHT:
            if self._get_head_pose_callback:
                yaw, _ = self._get_head_pose_callback()
                if yaw > self._signal_collector.yaw_right_max:
                    self._signal_collector.yaw_right_max = yaw

        elif self._state == CalibrationState.BLINK_COUNTING:
            pass

    def _on_phase_complete(self) -> None:
        """阶段完成处理"""
        if self._state == CalibrationState.CLOSED_EYES:
            self.callbacks.on_phase_complete(1, {"ear_min": self._signal_collector.ear_min})

        elif self._state == CalibrationState.OPEN_EYES:
            self.callbacks.on_phase_complete(2, {})

        elif self._state == CalibrationState.SQUINT:
            if self._squint_ear_values:
                squint_ear = sum(self._squint_ear_values) / len(self._squint_ear_values)
            else:
                squint_ear = self._signal_collector.ear_min * 1.5
            self.callbacks.on_phase_complete(3, {"squint_ear": squint_ear})

        elif self._state == CalibrationState.HEAD_RIGHT:
            self.callbacks.on_phase_complete(4, {})

        self._transition_to_next_phase()

    def _collect_blink_counting_data(self) -> None:
        """BLINK_COUNTING 阶段：每秒采集眨眼数据"""
        if self._get_ear_callback:
            ear = self._get_ear_callback()
            # 计算阈值（使用基线 EAR）
            ear_mean = sum(self._signal_collector.ears) / len(self._signal_collector.ears) if self._signal_collector.ears else 0.25
            blink_threshold = ear_mean * 0.75
            squint_threshold = ear_mean * 0.90
            current_time = time.time() - self._phase_start_time
            self._blink_collector.record_frame(ear, blink_threshold, squint_threshold, current_time)

            # 更新 UI 显示
            detected = self._blink_collector.detected_blinks
            remaining = int(self.blink_duration - (time.time() - self._phase_start_time))
            self.callbacks.on_blink_round_tick(remaining, detected)

    def _on_blink_counting_complete(self) -> None:
        """眨眼计数阶段完成"""
        program_count = self._blink_collector.detected_blinks
        self.callbacks.on_blink_round_end(self._current_blink_round, program_count)
        self._state = CalibrationState.BLINK_INPUT
        logger.info("眨眼计数轮 %d 完成，检测到 %d 次眨眼，等待用户输入",
                   self._current_blink_round, program_count)

    def _transition_to_next_phase(self) -> None:
        """转换到下一阶段"""
        self._current_phase += 1
        self._phase_start_time = time.time()

        if self._current_phase == 1:
            self._state = CalibrationState.CLOSED_EYES
        elif self._current_phase == 2:
            self._state = CalibrationState.OPEN_EYES
        elif self._current_phase == 3:
            self._state = CalibrationState.SQUINT
        elif self._current_phase == 4:
            self._state = CalibrationState.HEAD_UP
        elif self._current_phase == 5:
            self._current_blink_round = 1
            self._blink_collector.reset()
            self._state = CalibrationState.BLINK_COUNTING
            self.callbacks.on_blink_round_start(1, self.blink_rounds, self.blink_duration)
        else:
            self._state = CalibrationState.FINISHED
            result = self._compute_result()
            self.callbacks.on_calibration_complete(result)
            return

        phase_name, instruction = self._get_phase_info(self._current_phase)
        self.callbacks.on_phase_start(self._current_phase, phase_name, instruction)

    def _record_blink_round(self, user_count: int) -> None:
        """记录一轮眨眼校准数据"""
        program_count = self._blink_collector.detected_blinks
        squint_count = self._blink_collector.detected_squints

        if user_count > 0:
            error_rate = (user_count - program_count) / user_count
            adjustment = 1.0 + error_rate
        else:
            error_rate = 0.0
            adjustment = 1.0

        adjustment = max(0.7, min(1.3, adjustment))

        round_data = BlinkCalibrationRound(
            round_index=self._current_blink_round,
            duration_seconds=self.blink_duration,
            user_blink_count=user_count,
            program_blink_count=program_count,
            program_squint_count=squint_count,
            error_rate=error_rate,
            adjustment_factor=adjustment,
        )
        self._blink_rounds_data.append(round_data)

        if self._current_blink_round < self.blink_rounds:
            self._current_blink_round += 1
            self._blink_collector.reset()
            self._state = CalibrationState.BLINK_COUNTING
            self.callbacks.on_blink_round_start(
                self._current_blink_round,
                self.blink_rounds,
                self.blink_duration
            )
        else:
            self._state = CalibrationState.FINISHED
            result = self._compute_result()
            self.callbacks.on_calibration_complete(result)

    def _compute_result(self) -> CalibrationResult:
        """计算校准结果"""
        ear_mean = sum(self._signal_collector.ears) / len(self._signal_collector.ears) if self._signal_collector.ears else 0.25
        ear_min = self._signal_collector.ear_min if self._signal_collector.ear_min != 999.0 else ear_mean * 0.3

        squint_threshold = ear_mean * 0.75

        if self._blink_rounds_data:
            adjustments = [r.adjustment_factor for r in self._blink_rounds_data]
            final_adjustment = sum(adjustments) / len(adjustments)
        else:
            final_adjustment = 1.0

        final_blink_threshold = ear_mean * 0.75 * final_adjustment

        signal = CalibrationSignal(
            ear_mean=ear_mean,
            ear_min=ear_min,
            ear_mid=squint_threshold,
            yaw_mean=sum(self._signal_collector.yaws) / len(self._signal_collector.yaws) if self._signal_collector.yaws else 0.0,
            yaw_range=(self._signal_collector.yaw_left_max, self._signal_collector.yaw_right_max),
            pitch_mean=sum(self._signal_collector.pitches) / len(self._signal_collector.pitches) if self._signal_collector.pitches else 0.0,
            pitch_range=(self._signal_collector.pitch_up_max, self._signal_collector.pitch_down_max),
            glasses_mode=False,
            timestamp=time.time(),
        )

        return CalibrationResult(
            session_id=self._session_id or "",
            timestamp=datetime.now(),
            signal=signal,
            blink_rounds=self._blink_rounds_data.copy(),
            final_adjustment_factor=final_adjustment,
            final_blink_threshold=final_blink_threshold,
            final_squint_threshold=squint_threshold,
            is_accepted=True,
            notes="",
        )


def create_user_calibration_manager(callbacks: CalibrationCallbacks, session_id: Optional[str] = None) -> UserCalibrationManager:
    """工厂函数：创建用户校准管理器"""
    return UserCalibrationManager(callbacks=callbacks, session_id=session_id)

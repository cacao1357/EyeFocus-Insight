"""
tests/test_user_calibration.py — 用户校准模块单元测试
"""

import time
import pytest
from unittest.mock import Mock, MagicMock

from analyzer.user_calibration import (
    UserCalibrationManager,
    CalibrationCallbacks,
    CalibrationState,
    SignalCollector,
    BlinkRoundCollector,
    BLINK_DURATION_THRESHOLD,
)
from storage.models import CalibrationSignal, BlinkCalibrationRound


class MockCallbacks:
    """模拟回调"""
    def __init__(self):
        self.events = []
        self.last_phase = None
        self.last_countdown = 0
        self.last_blink_round_end = None
        self.last_result = None

    def on_phase_start(self, phase: int, phase_name: str, instruction: str):
        self.events.append(("phase_start", phase, phase_name))
        self.last_phase = phase

    def on_countdown_tick(self, remaining: int):
        self.events.append(("countdown", remaining))
        self.last_countdown = remaining

    def on_detected_signals_update(self, ear: float, yaw: float, pitch: float):
        pass

    def on_phase_complete(self, phase: int, collected_data: dict):
        self.events.append(("phase_complete", phase))

    def on_blink_round_start(self, round_num: int, total_rounds: int, duration: int):
        self.events.append(("blink_round_start", round_num, total_rounds))

    def on_blink_round_tick(self, remaining: int, detected_blinks: int):
        self.events.append(("blink_round_tick", remaining, detected_blinks))

    def on_blink_round_end(self, round_num: int, program_count: int):
        self.events.append(("blink_round_end", round_num, program_count))
        self.last_blink_round_end = (round_num, program_count)

    def on_calibration_complete(self, result):
        self.events.append(("calibration_complete",))
        self.last_result = result

    def on_error(self, phase: int, message: str):
        self.events.append(("error", phase, message))


class TestSignalCollector:
    """SignalCollector 测试"""

    def test_init(self):
        sc = SignalCollector()
        assert sc.ears == []
        assert sc.ear_min == 999.0

    def test_record_ear(self):
        sc = SignalCollector()
        sc.ears = [0.3, 0.35, 0.32]
        assert len(sc.ears) == 3


class TestBlinkRoundCollector:
    """BlinkRoundCollector 测试"""

    def test_init(self):
        brc = BlinkRoundCollector()
        brc.reset()
        assert brc.detected_blinks == 0
        assert brc.detected_squints == 0

    def test_short_blink(self):
        """测试短闭眼（眨眼）"""
        brc = BlinkRoundCollector()
        current_time = time.time()

        # 闭眼
        brc.record_frame(ear=0.1, ear_threshold=0.25, squint_threshold=0.2,
                         current_time=current_time)
        assert brc._in_blink == True

        # 快速睁眼（眨眼）
        brc.record_frame(ear=0.35, ear_threshold=0.25, squint_threshold=0.2,
                         current_time=current_time + 0.2)
        assert brc.detected_blinks == 1
        assert brc.detected_squints == 0

    def test_long_blink(self):
        """测试长闭眼（眯眼）"""
        brc = BlinkRoundCollector()
        current_time = time.time()

        # 闭眼
        brc.record_frame(ear=0.1, ear_threshold=0.25, squint_threshold=0.2,
                         current_time=current_time)
        # 长闭眼（眯眼）
        brc.record_frame(ear=0.15, ear_threshold=0.25, squint_threshold=0.2,
                         current_time=current_time + 0.5)
        assert brc._in_blink == True
        # 睁眼
        brc.record_frame(ear=0.35, ear_threshold=0.25, squint_threshold=0.2,
                         current_time=current_time + 0.5 + BLINK_DURATION_THRESHOLD)
        assert brc.detected_squints == 1
        assert brc.detected_blinks == 0


class TestUserCalibrationManager:
    """UserCalibrationManager 测试"""

    def test_init(self):
        callbacks = MockCallbacks()
        mgr = UserCalibrationManager(callbacks=callbacks)
        assert mgr.state == CalibrationState.IDLE
        assert mgr.current_phase == 0

    def test_start(self):
        callbacks = MockCallbacks()
        mgr = UserCalibrationManager(callbacks=callbacks)
        mgr.start()
        assert mgr.state == CalibrationState.AUTO_CALIB
        assert len(callbacks.events) > 0
        assert callbacks.events[0][0] == "phase_start"

    def test_cancel(self):
        callbacks = MockCallbacks()
        mgr = UserCalibrationManager(callbacks=callbacks)
        mgr.start()
        mgr.on_cancel()
        assert mgr.state == CalibrationState.IDLE

    def test_get_result_before_finish(self):
        callbacks = MockCallbacks()
        mgr = UserCalibrationManager(callbacks=callbacks)
        assert mgr.get_result() is None

    def test_blink_round_input(self):
        callbacks = MockCallbacks()
        mgr = UserCalibrationManager(callbacks=callbacks, blink_rounds=1, blink_duration=1)

        # 手动设置到 BLINK_INPUT 状态
        mgr._state = CalibrationState.BLINK_INPUT
        mgr._current_blink_round = 1
        mgr._blink_collector.detected_blinks = 5

        mgr.on_user_input(user_blink_count=6)

        # 应该切换到 FINISHED（只有1轮）
        assert mgr.state == CalibrationState.FINISHED
        assert len(mgr._blink_rounds_data) == 1
        assert mgr._blink_rounds_data[0].user_blink_count == 6
        assert mgr._blink_rounds_data[0].program_blink_count == 5

    def test_head_pose_phase_with_yaw_pitch_only(self):
        """v4.0.1 回归: phases 用 head_yaw + head_pitch (无 head_pose) 不应 KeyError (B2)"""
        callbacks = MockCallbacks()
        # 配置中无 head_pose key（v4.0.1 修复后必须支持）
        mgr = UserCalibrationManager(
            callbacks=callbacks,
            blink_rounds=2,
            blink_duration=0.1,
            phases={
                "auto_calib": 0.1, "closed_eyes": 0.1, "open_eyes": 0.1,
                "squint": 0.1,
                "head_yaw": 0.4, "head_pitch": 0.4,  # 故意无 head_pose
                "blink_counting": 0.1,
            },
        )
        # 推进到 HEAD_UP，触发 _get_current_phase_duration
        mgr._state = CalibrationState.HEAD_UP
        mgr._phase_start_time = time.time()  # 触发 tick 不会立即推进
        dur = mgr._get_current_phase_duration()
        # 期望: (0.4 + 0.4) / 4 = 0.2
        assert dur == pytest.approx(0.2), f"head_pose 阶段时长计算错误: {dur}"

    def test_head_pose_phase_with_combined_key(self):
        """v4.0.1 回归: phases 含 head_pose 旧 key 仍可工作 (B2 兼容)"""
        callbacks = MockCallbacks()
        mgr = UserCalibrationManager(
            callbacks=callbacks,
            blink_rounds=2,
            blink_duration=0.1,
            phases={
                "auto_calib": 0.1, "closed_eyes": 0.1, "open_eyes": 0.1,
                "squint": 0.1, "head_pose": 0.4,  # 旧 key
                "blink_counting": 0.1,
            },
        )
        mgr._state = CalibrationState.HEAD_UP
        dur = mgr._get_current_phase_duration()
        assert dur == pytest.approx(0.1), f"head_pose=0.4 应/4=0.1, 实际 {dur}"


class TestPhaseInfoDynamic:
    """v4.0.2 回归: 校准文案动态渲染 (B5)"""

    def test_default_phase_info_no_hardcoded_seconds(self):
        """默认配置下文案含正确秒数 (B5 不再硬编码 5/3/2-3)"""
        from unittest.mock import MagicMock
        mgr = UserCalibrationManager(callbacks=MagicMock())  # 默认 7/5/3/8
        # 阶段 1: 闭眼 5 秒
        _, instr = mgr._get_phase_info(1)
        assert "5" in instr, f"闭眼文案应含 5 秒, 实际: {instr}"
        assert "闭眼" in instr
        # 阶段 2: 睁眼 3 秒
        _, instr = mgr._get_phase_info(2)
        assert "3" in instr, f"睁眼文案应含 3 秒, 实际: {instr}"
        # 阶段 3: 眯眼 8 秒
        _, instr = mgr._get_phase_info(3)
        assert "8" in instr, f"眯眼文案应含 8 秒, 实际: {instr}"

    def test_custom_phase_info_uses_custom_seconds(self):
        """自定义 phases 时文案应动态同步 (B5 核心)"""
        from unittest.mock import MagicMock
        mgr = UserCalibrationManager(
            callbacks=MagicMock(),
            phases={
                "auto_calib": 1, "closed_eyes": 10, "open_eyes": 7,
                "squint": 4, "head_pose": 8, "blink_counting": 1,
            },
        )
        # 闭眼: 10 秒
        _, instr = mgr._get_phase_info(1)
        assert "10" in instr, f"闭眼 10 秒文案未同步: {instr}"
        # 睁眼: 7 秒
        _, instr = mgr._get_phase_info(2)
        assert "7" in instr, f"睁眼 7 秒文案未同步: {instr}"
        # 眯眼: 4 秒
        _, instr = mgr._get_phase_info(3)
        assert "4" in instr, f"眯眼 4 秒文案未同步: {instr}"
        # 头部: 8/4 = 2 秒每方向
        _, instr = mgr._get_phase_info(4)
        assert "2" in instr, f"头部 2 秒每方向文案未同步: {instr}"

    def test_phase_info_out_of_range_returns_unknown(self):
        """超界 phase 返回 ('未知', '')"""
        from unittest.mock import MagicMock
        mgr = UserCalibrationManager(callbacks=MagicMock())
        name, instr = mgr._get_phase_info(99)
        assert name == "未知"
        assert instr == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
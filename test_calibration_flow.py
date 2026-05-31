"""
test_calibration_flow.py — 校准状态机测试

验证 UserCalibrationManager.tick() 是否正确推进状态机。
"""
import time
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analyzer.user_calibration import (
    UserCalibrationManager,
    CalibrationState,
    CalibrationCallbacks,
)
from storage.models import CalibrationResult


class MockCallbacks:
    """模拟校准回调"""
    def __init__(self):
        self.events = []

    def on_phase_start(self, phase: int, phase_name: str, instruction: str):
        self.events.append(f"phase_start:{phase}:{phase_name}")
        print(f"[回调] 阶段 {phase} 开始: {phase_name}")

    def on_countdown_tick(self, remaining: int):
        pass  # 忽略倒计时

    def on_detected_signals_update(self, ear: float, yaw: float, pitch: float):
        pass

    def on_phase_complete(self, phase: int, collected_data: dict):
        self.events.append(f"phase_complete:{phase}")
        print(f"[回调] 阶段 {phase} 完成")

    def on_blink_round_start(self, round_num: int, total_rounds: int, duration: int):
        self.events.append(f"blink_round_start:{round_num}")
        print(f"[回调] 眨眼轮开始: {round_num}/{total_rounds}")

    def on_blink_round_tick(self, remaining: int, detected_blinks: int):
        pass

    def on_blink_round_end(self, round_num: int, program_count: int):
        self.events.append(f"blink_round_end:{round_num}:{program_count}")
        print(f"[回调] 眨眼轮结束: {round_num}, 检测到 {program_count} 次")

    def on_calibration_complete(self, result: CalibrationResult):
        self.events.append("calibration_complete")
        print(f"[回调] 校准完成! EAR={result.signal.ear_mean:.4f}")

    def on_error(self, phase: int, message: str):
        print(f"[错误] 阶段 {phase}: {message}")


class MockEarCallback:
    """模拟 EAR 回调"""
    def __init__(self):
        self.ear_value = 0.3

    def __call__(self):
        return self.ear_value


class MockHeadPoseCallback:
    """模拟头部姿态回调"""
    def __call__(self):
        return (0.5, -2.0)  # yaw=0.5, pitch=-2.0


def test_calibration_flow():
    """测试校准流程"""
    print("=" * 60)
    print("用户校准流程测试")
    print("=" * 60)

    callbacks = MockCallbacks()
    manager = UserCalibrationManager(
        callbacks=callbacks,
        blink_rounds=2,  # 减少轮数加快测试
        blink_duration=5,  # 减少时长加快测试
    )

    # 设置回调
    ear_cb = MockEarCallback()
    head_cb = MockHeadPoseCallback()
    manager.set_ear_callback(ear_cb)
    manager.set_head_pose_callback(head_cb)

    # 启动校准
    print("\n[1] 启动校准...")
    manager.start()

    # 验证状态转换
    print(f"[2] 初始状态: {manager.state}")
    assert manager.state == CalibrationState.AUTO_CALIB, f"期望 AUTO_CALIB，实际 {manager.state}"

    # 模拟 tick() 调用推进状态机（每秒调用一次）
    print("\n[3] 模拟 tick() 推进状态机...")
    last_state = manager.state
    tick_count = 0
    import unittest.mock as mock

    # 模拟时间流逝：每次 tick 相当于过了 1 秒
    fake_time = time.time()

    with mock.patch('time.time', return_value=fake_time):
        while manager.state not in (CalibrationState.FINISHED, CalibrationState.IDLE):
            # 模拟时间前进 1 秒
            fake_time += 1.0
            with mock.patch('time.time', return_value=fake_time):
                manager.tick()
            tick_count += 1

            if manager.state != last_state:
                print(f"    状态变化: {last_state} -> {manager.state}")
                last_state = manager.state

            # 安全检查：避免无限循环
            if tick_count > 100:
                print("[错误] tick() 次数过多，可能状态机卡住")
                break

            # 加速：EAR 回调返回眯眼值使眯眼阶段快速通过
            if manager.state == CalibrationState.CLOSED_EYES:
                ear_cb.ear_value = 0.05  # 眯眼
            else:
                ear_cb.ear_value = 0.3  # 正常睁眼

            # 在 blink_input 状态提供用户输入
            if manager.state == CalibrationState.BLINK_INPUT:
                manager.on_user_input(3)  # 用户输入眨眼 3 次

    print(f"\n[4] 校准完成，耗时 {tick_count} 次 tick")
    print(f"    最终状态: {manager.state}")

    # 验证结果
    if manager.state == CalibrationState.FINISHED:
        result = manager.get_result()
        if result:
            print(f"\n[5] 校准结果:")
            print(f"    EAR 均值: {result.signal.ear_mean:.4f}")
            print(f"    眨眼阈值: {result.final_blink_threshold:.4f}")
            print(f"    眯眼阈值: {result.final_squint_threshold:.4f}")
            print(f"    调整因子: {result.final_adjustment_factor:.3f}")
            print(f"    眨眼轮数: {len(result.blink_rounds)}")
            print("\n[OK] 校准状态机工作正常!")
            return True
        else:
            print("\n[FAIL] 校准结果为空")
            return False
    else:
        print(f"\n[FAIL] 校准未完成，最终状态: {manager.state}")
        return False


if __name__ == "__main__":
    success = test_calibration_flow()
    sys.exit(0 if success else 1)

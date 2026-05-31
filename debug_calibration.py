"""
调试脚本：诊断校准和眨眼检测问题
"""
import sys
sys.path.insert(0, '.')

import time
import numpy as np
import cv2

from config import CAMERA
from detector.face_mesh import create_face_mesh_detector
from detector.eye_aspect import create_eye_aspect_detector
from analyzer.user_calibration import UserCalibrationManager, CalibrationCallbacks, CalibrationState


class DebugCallbacks:
    """调试用回调"""
    def on_phase_start(self, phase, phase_name, instruction):
        print(f"[回调] 阶段开始: {phase} - {phase_name}")
        print(f"[回调] 指示: {instruction}")

    def on_countdown_tick(self, remaining):
        print(f"[回调] 倒计时: {remaining}s")

    def on_detected_signals_update(self, ear, yaw, pitch):
        pass  # 太频繁，不打印

    def on_phase_complete(self, phase, collected_data):
        print(f"[回调] 阶段完成: {phase}, 数据: {collected_data}")

    def on_blink_round_start(self, round_num, total_rounds, duration):
        print(f"[回调] 眨眼轮开始: {round_num}/{total_rounds}, 时长: {duration}s")

    def on_blink_round_tick(self, remaining, detected_blinks):
        print(f"[回调] 眨眼轮 tick: 剩余{remaining}s, 检测到{detected_blinks}次眨眼")

    def on_blink_round_end(self, round_num, program_count):
        print(f"[回调] 眨眼轮结束: 第{round_num}轮, 程序计数: {program_count}")

    def on_calibration_complete(self, result):
        print(f"[回调] 校准完成!")
        print(f"  EAR均值: {result.signal.ear_mean:.4f}")
        print(f"  EAR最小: {result.signal.ear_min:.4f}")
        print(f"  最终眨眼阈值: {result.final_blink_threshold:.4f}")

    def on_error(self, phase, message):
        print(f"[回调] 错误: 阶段{phase} - {message}")


def main():
    print("=" * 60)
    print("EyeFocus Insight 调试诊断")
    print("=" * 60)

    # 初始化检测器
    print("\n[1] 初始化检测器...")
    face_detector = create_face_mesh_detector()
    eye_detector = create_eye_aspect_detector()

    print(f"    初始 EAR 阈值: {eye_detector.ear_threshold:.4f}")
    print(f"    睁眼阈值: {eye_detector.open_threshold:.4f}")

    # 初始化校准管理器
    print("\n[2] 初始化校准管理器...")
    callbacks = DebugCallbacks()
    calib_manager = UserCalibrationManager(callbacks=callbacks, blink_rounds=3, blink_duration=5)
    calib_manager.set_ear_callback(lambda: eye_detector.get_current_ear())
    calib_manager.set_head_pose_callback(lambda: (0.0, 0.0))

    # 打开摄像头
    print("\n[3] 打开摄像头...")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("    [错误] 无法打开摄像头!")
        return

    # 等待摄像头稳定
    for i in range(5):
        cap.read()
        time.sleep(0.1)

    print("    摄像头已准备好")

    # 开始校准
    print("\n[4] 开始校准流程...")
    calib_manager.start()
    print(f"    校准状态: {calib_manager.state}")

    # 主循环
    print("\n[5] 进入主循环 (10秒)...")
    start_time = time.time()
    frame_count = 0

    try:
        while time.time() - start_time < 10:
            ret, frame = cap.read()
            if not ret:
                print("    [警告] 无法读取帧")
                continue

            frame_count += 1
            timestamp_ms = int(time.time() * 1000)

            # 人脸检测
            face_result = face_detector.detect_from_frame(frame, timestamp_ms)

            if not face_result.face_detected:
                if frame_count % 30 == 0:
                    print(f"    [帧{frame_count}] 未检测到人脸")
                time.sleep(0.03)
                continue

            # EAR 计算
            eye_result = eye_detector.compute(face_result.landmarks)

            # 校准数据采集
            if calib_manager.state == CalibrationState.AUTO_CALIB:
                calib_manager.add_frame(
                    ear=eye_result.ear_avg,
                    yaw=face_result.yaw or 0.0,
                    pitch=face_result.pitch or 0.0,
                )

            # 每秒打印一次状态
            elapsed = int(time.time() - start_time)
            if time.time() - start_time >= elapsed:
                recent_blinks = eye_detector.get_blink_events(since_time=start_time)
                print(f"    [秒{elapsed}] 帧{frame_count} | EAR: {eye_result.ear_avg:.4f} | "
                      f"眨眼阈值: {eye_detector.ear_threshold:.4f} | "
                      f"睁眼阈值: {eye_detector.open_threshold:.4f} | "
                      f"眨眼事件: {len(recent_blinks)} | "
                      f"校准状态: {calib_manager.state}")

            # 显示帧（缩小窗口）
            display = cv2.resize(frame, (320, 240))
            cv2.imshow("Debug", display)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("    用户按Q退出")
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()

    # 输出结果
    print("\n" + "=" * 60)
    print("诊断结果")
    print("=" * 60)

    # 检查采集的数据
    collector = calib_manager._signal_collector
    print(f"\n采集的数据:")
    print(f"  EAR 数据点: {len(collector.ears)}")
    if collector.ears:
        print(f"  EAR 均值: {np.mean(collector.ears):.4f}")
        print(f"  EAR 最小: {min(collector.ears):.4f}")
        print(f"  EAR 最大: {max(collector.ears):.4f}")
        print(f"  YAW 数据点: {len(collector.yaws)}")
        print(f"  PITCH 数据点: {len(collector.pitches)}")

    # 检查眨眼事件
    all_blinks = eye_detector.get_blink_events()
    print(f"\n眨眼事件:")
    print(f"  总数: {len(all_blinks)}")
    for i, blink in enumerate(all_blinks[:5]):
        print(f"    眨眼{i+1}: duration={blink.duration:.3f}s, nadir={blink.ear_nadir:.4f}")

    # 分析问题
    print("\n问题分析:")
    if len(collector.ears) < 100:
        print("  [!] 采集的数据点太少 (< 100)")

    if eye_detector.ear_threshold > 0.3:
        print(f"  [!] EAR 阈值过高 ({eye_detector.ear_threshold:.4f})")
    elif eye_detector.ear_threshold < 0.2:
        print(f"  [!] EAR 阈值过低 ({eye_detector.ear_threshold:.4f})")

    # 检查阈值是否合理
    if collector.ears:
        mean_ear = np.mean(collector.ears)
        expected_threshold = mean_ear * 0.75
        print(f"\n阈值分析:")
        print(f"  采集的 EAR 均值: {mean_ear:.4f}")
        print(f"  期望眨眼阈值 (均值×0.75): {expected_threshold:.4f}")
        print(f"  当前眨眼阈值: {eye_detector.ear_threshold:.4f}")
        print(f"  当前睁眼阈值 (均值×0.90): {mean_ear * 0.90:.4f}")

        if mean_ear < eye_detector.ear_threshold:
            print("  [!] 警告: EAR均值 < 眨眼阈值，会导致持续触发眨眼!")


if __name__ == "__main__":
    main()

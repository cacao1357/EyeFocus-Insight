"""
test_qt_monitor.py — PyQt5 监测模式快速验证

直接启动 Qt 窗口显示摄像头画面+分析数据。
不需走完整校准流程。
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui import EyeFocusWindow, FrameBuffer
from detector.face_mesh import create_face_mesh_detector
from detector.eye_aspect import create_eye_aspect_detector
from analyzer.focus import create_focus_analyzer
from analyzer.fatigue import create_fatigue_analyzer

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
import cv2
import numpy as np


def main():
    # 初始化组件
    print("初始化检测器...")
    face_detector = create_face_mesh_detector()
    eye_detector = create_eye_aspect_detector()
    focus_analyzer = create_focus_analyzer()
    focus_analyzer.set_blink_detector(eye_detector)
    fatigue_analyzer = create_fatigue_analyzer()
    fatigue_analyzer.start()

    # 摄像头
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("摄像头无法打开")
        return

    # Qt 窗口
    app = QApplication(sys.argv)
    frame_buffer = FrameBuffer()
    window = EyeFocusWindow(frame_buffer)
    window.setWindowTitle("EyeFocus Insight (Qt Test)")

    # FPS
    fps_counter = [0]
    fps_last = [time.time()]
    fps_val = [0.0]

    def update_frame():
        ret, frame = cap.read()
        if not ret:
            return

        # 检测
        timestamp_ms = int(time.time() * 1000)
        face_result = face_detector.detect_from_frame(frame, timestamp_ms)

        face_detected = False
        if face_result and face_result.face_detected:
            face_detected = True
            eye_detector.compute(face_result.landmarks)
            ear = eye_detector.get_current_ear()
            blink_events = eye_detector.get_blink_events(since_time=time.time() - 30)

            focus_result = focus_analyzer.analyze(
                ear_avg=ear, face_detected=True,
                face_results=face_result,
            )
            fatigue_result = fatigue_analyzer.analyze(
                blink_rate=focus_result.blink_rate if focus_result else 0,
                avg_ear=ear, blink_flag=False,
            )

            # 更新 Qt 窗口
            fatigue_level = None
            focus_score = None
            if fatigue_result:
                level = fatigue_result.fatigue_level
                fatigue_level = level.value.upper() if hasattr(level, 'value') else str(level)
            if focus_result:
                focus_score = focus_result.focus_score

            window.update_data(
                focus_score=focus_score,
                fatigue_level=fatigue_level,
                face_detected=face_detected,
                eye_detected=face_detected,
                fps=fps_val[0],
            )

        # 写帧到缓冲区
        frame_buffer.write(frame)

        # FPS
        fps_counter[0] += 1
        elapsed = time.time() - fps_last[0]
        if elapsed >= 1.0:
            fps_val[0] = fps_counter[0] / elapsed
            fps_counter[0] = 0
            fps_last[0] = time.time()

    timer = QTimer()
    timer.timeout.connect(update_frame)
    timer.start(33)  # ~30fps

    window.show()
    print("Qt 窗口已启动。按 Q 退出。")
    app.exec_()

    # 清理
    timer.stop()
    cap.release()
    face_detector.close()
    print("已退出")


if __name__ == "__main__":
    main()

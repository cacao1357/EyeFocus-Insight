"""
angle_live.py — 实时头部姿态角度显示 spike

显示 MediaPipe 检测到的实时 yaw/pitch/roll 数值，
让用户对比实际转头幅度与检测值，确定偏差规律。

用法：".venv312/Scripts/python.exe" -X utf8 spike/angle_live.py
按 Q 退出
"""
import sys, os, time, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
from detector.face_mesh import create_face_mesh_detector


def main():
    fd = create_face_mesh_detector()
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("摄像头无法打开")
        return

    print("=" * 60)
    print("实时头部姿态角度显示")
    print("请转头对比检测值与实际幅度")
    print("按 Q 退出")
    print("=" * 60)

    cv2.namedWindow("Angle Live", cv2.WINDOW_AUTOSIZE)
    font = cv2.FONT_HERSHEY_SIMPLEX

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                continue

            h, w = frame.shape[:2]
            timestamp_ms = int(time.time() * 1000)
            face_result = fd.detect_from_frame(frame, timestamp_ms)

            yaw = pitch = roll = None
            face_detected = False
            if face_result and face_result.face_detected:
                face_detected = True
                yaw = getattr(face_result, 'yaw', None)
                pitch = getattr(face_result, 'pitch', None)
                roll = getattr(face_result, 'roll', None)

            # 显示检测结果
            if face_detected:
                # 大号角度数字
                texts = [
                    f"YAW (转头):   {yaw:>6.1f}°" if yaw is not None else "YAW: N/A",
                    f"PITCH (点头): {pitch:>6.1f}°" if pitch is not None else "PITCH: N/A",
                    f"ROLL (侧倾):  {roll:>6.1f}°" if roll is not None else "ROLL: N/A",
                ]
                for i, t in enumerate(texts):
                    cv2.putText(frame, t, (30, 60 + i * 50),
                                font, 1.0, (0, 255, 0), 2)

                # 指南针式 yaw 指示
                cx, cy = w // 2, h - 120
                cv2.circle(frame, (cx, cy), 60, (100, 100, 100), 2)
                if yaw is not None:
                    angle_rad = math.radians(yaw)
                    ex = int(cx + 50 * math.sin(angle_rad))
                    ey = int(cy - 50 * math.cos(angle_rad))
                    cv2.line(frame, (cx, cy), (ex, ey), (0, 255, 255), 3)
                    cv2.circle(frame, (ex, ey), 8, (0, 0, 255), -1)
                cv2.putText(frame, "YAW", (cx - 20, cy + 80),
                            font, 0.5, (180, 180, 180), 1)

                # pitch 指示 (上下)
                px, py = w - 100, h // 2
                cv2.putText(frame, "PITCH", (px - 30, py + 80),
                            font, 0.5, (180, 180, 180), 1)
                cv2.circle(frame, (px, py), 40, (100, 100, 100), 2)
                if pitch is not None:
                    p_rad = math.radians(pitch)
                    pex = px
                    pey = py + int(40 * math.sin(p_rad))
                    cv2.line(frame, (px, py), (pex, pey), (255, 255, 0), 3)
                    cv2.circle(frame, (pex, pey), 6, (0, 165, 255), -1)
            else:
                cv2.putText(frame, "No face detected", (30, 60),
                            font, 1.0, (0, 0, 255), 2)

            cv2.imshow("Angle Live", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        fd.close()


if __name__ == "__main__":
    main()

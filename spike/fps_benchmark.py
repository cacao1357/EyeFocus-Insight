"""
S1: FPS 基准测试 (FPS Benchmark)
验证 MediaPipe Face Mesh + 3D 头部姿态估计在目标平台上的实时性能。

用法: python spike/fps_benchmark.py
验收: 运行 >= 2 分钟，平均 FPS >= 25，结果保存到 spike/s1_result.json
"""

import json
import logging
import os
import sys
import time
from typing import List

import cv2
import mediapipe as mp
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import BENCHMARK, CAMERA
from spike.common import (
    camera_context,
    cleanup_exit,
    compute_ear_from_landmarks,
    create_face_landmarker,
    extract_landmarks,
    get_camera_matrix,
    opencv_windows,
    setup_logging,
    solve_head_pose_from_matrix,
)

logger = logging.getLogger("eyefocus.spike")

WINDOW_NAME = "S1: FPS Benchmark"


def main() -> None:
    setup_logging()
    face_landmarker = create_face_landmarker()

    with camera_context(CAMERA.index) as cap:
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        camera_matrix = get_camera_matrix(frame_w, frame_h)

        logger.info("FPS 基准测试开始")
        logger.info(
            "目标: 运行 >= %.0f 分钟, 平均 FPS >= %.0f",
            BENCHMARK.min_duration / 60,
            CAMERA.min_fps,
        )
        logger.info("按 Q 提前退出")
        print()

        fps_window: List[float] = []
        confidence_window: List[float] = []
        start_time = time.time()
        frame_count = 0
        prev_timestamp = start_time
        pass_message_printed = False

        with opencv_windows(WINDOW_NAME):
            while True:
                ret, frame = cap.read()
                if not ret:
                    continue

                from mediapipe import Image
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
                current_timestamp = int((time.time() - start_time) * 1000)
                result = face_landmarker.detect_for_video(mp_image, current_timestamp)

                yaw, pitch, roll = None, None, None
                face_detected = False

                pts = extract_landmarks(result, frame_w, frame_h)
                if pts is not None:
                    face_detected = True
                    # Use MediaPipe's built-in transformation matrix for head pose
                    if (
                        result.facial_transformation_matrixes is not None
                        and result.facial_transformation_matrixes[0] is not None
                    ):
                        matrix = np.array(
                            result.facial_transformation_matrixes[0]
                        ).flatten()
                        yaw, pitch, roll = solve_head_pose_from_matrix(matrix)
                    else:
                        yaw, pitch, roll = None, None, None

                now = time.time()
                elapsed_total = now - start_time
                frame_count += 1

                dt = now - prev_timestamp
                prev_timestamp = now

                if dt > 0:
                    fps_window.append(1.0 / dt)
                    if len(fps_window) > BENCHMARK.fps_window_size:
                        fps_window.pop(0)

                confidence_window.append(1.0 if face_detected else 0.0)
                if len(confidence_window) > BENCHMARK.fps_window_size:
                    confidence_window.pop(0)

                avg_fps = np.mean(fps_window) if fps_window else 0
                avg_conf = np.mean(confidence_window) if confidence_window else 0
                remaining = max(0, BENCHMARK.min_duration - elapsed_total)

                if yaw is not None:
                    sys.stdout.write(
                        f"\r  FPS: {avg_fps:5.1f} | Conf: {avg_conf:.2f} | "
                        f"Frame: {frame_count:5d} | Elapsed: {elapsed_total:.0f}s | "
                        f"Need: {remaining:.0f}s | Yaw: {yaw:6.1f}"
                    )
                else:
                    sys.stdout.write(
                        f"\r  FPS: {avg_fps:5.1f} | Conf: {avg_conf:.2f} | "
                        f"Frame: {frame_count:5d} | Elapsed: {elapsed_total:.0f}s | "
                        f"Need: {remaining:.0f}s | Yaw:    N/A"
                    )
                sys.stdout.flush()

                bar_w = int(min(1.0, elapsed_total / BENCHMARK.min_duration) * 50)
                bar = "#" * bar_w + "-" * (50 - bar_w)

                display = frame.copy()
                cv2.putText(
                    display,
                    f"FPS Benchmark: [{bar}] {remaining:.0f}s remaining",
                    (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2,
                )
                cv2.putText(
                    display,
                    f"FPS: {avg_fps:.1f}  |  Conf: {avg_conf:.2f}",
                    (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1,
                )
                if yaw is not None:
                    cv2.putText(
                        display,
                        f"Yaw:{yaw:6.1f}  Pitch:{pitch:6.1f}  Roll:{roll:6.1f}",
                        (20, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1,
                    )
                cv2.putText(
                    display, "[Q] to quit",
                    (20, frame_h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128, 128, 128), 1,
                )
                cv2.imshow(WINDOW_NAME, display)

                if elapsed_total >= BENCHMARK.min_duration and not pass_message_printed:
                    logger.info(
                        "%.0f 分钟达标! 按 Q 退出", BENCHMARK.min_duration / 60
                    )
                    pass_message_printed = True

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

    # face_landmarker.close() intentionally omitted — MediaPipe's close()
    # blocks indefinitely. os._exit() (via cleanup_exit) bypasses this.

    avg_fps_val = float(np.mean(fps_window)) if fps_window else 0
    min_fps_val = float(np.min(fps_window)) if fps_window else 0
    max_fps_val = float(np.max(fps_window)) if fps_window else 0
    avg_conf_val = float(np.mean(confidence_window)) if confidence_window else 0
    fps_pass = avg_fps_val >= CAMERA.min_fps

    result_dict = {
        "spike": "S1_fps_benchmark",
        "duration_s": round(elapsed_total, 1),
        "total_frames": frame_count,
        "fps_avg": round(avg_fps_val, 2),
        "fps_min": round(min_fps_val, 2),
        "fps_max": round(max_fps_val, 2),
        "confidence_avg": round(avg_conf_val, 3),
        "resolution": f"{frame_w}x{frame_h}",
        "pass": fps_pass,
    }

    output_path = os.path.join(os.path.dirname(__file__), "s1_result.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_dict, f, indent=2, ensure_ascii=False)

    print("\n")
    print("=" * 50)
    print("       S1: FPS 基准测试结果")
    print("=" * 50)
    for k, v in result_dict.items():
        print(f"  {k:>16s}: {v}")
    print("=" * 50)
    print(f"\n结果已保存到: {output_path}")

    if fps_pass:
        logger.info("帧率达标 (>= %.0f FPS)", CAMERA.min_fps)
    else:
        logger.error("帧率不达标，请检查硬件加速 / 考虑跳帧策略")

    cleanup_exit(0 if fps_pass else 1)


if __name__ == "__main__":
    main()

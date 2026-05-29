"""
S3: 头部姿态 3D 验证 (Head Pose 3D Validation)
验证 solvePnP 在正视/低头/左转/回归四种方向下的角度稳定性和回归漂移。

用法: python spike/head_pose_proto.py
验收: 正视 yaw_std < 3° 且 pitch_std < 3°
"""

import json
import logging
import os
import sys
import time
from typing import Dict, List

import cv2
import mediapipe as mp
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import CAMERA, HEAD_POSE, HEAD_POSE_PROTO
from spike.common import (
    camera_context,
    cleanup_exit,
    create_face_landmarker,
    extract_landmarks,
    get_camera_matrix,
    opencv_windows,
    setup_logging,
    solve_head_pose_from_matrix,
)

logger = logging.getLogger("eyefocus.spike")

WINDOW_NAME = "S3: Head Pose 3D Validation"


def main() -> None:
    setup_logging()
    face_landmarker = create_face_landmarker()

    with camera_context(CAMERA.index) as cap:
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        camera_matrix = get_camera_matrix(frame_w, frame_h)

        phase_results: Dict[str, dict] = {}
        phase_idx = 0
        collected_yaw: List[float] = []
        collected_pitch: List[float] = []
        collected_roll: List[float] = []
        phase_start = time.time()
        global_start = time.time()
        quit_requested = False

        logger.info("头部姿态 3D 验证开始 (4 阶段)")
        print()

        with opencv_windows(WINDOW_NAME):
            while phase_idx < len(HEAD_POSE_PROTO.phases) and not quit_requested:
                ret, frame = cap.read()
                if not ret:
                    continue

                from mediapipe import Image
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
                current_timestamp = int((time.time() - global_start) * 1000)
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

                if face_detected and yaw is not None:
                    collected_yaw.append(yaw)
                    collected_pitch.append(pitch)
                    collected_roll.append(roll)

                elapsed = time.time() - phase_start
                remaining = max(0, HEAD_POSE_PROTO.phase_duration - elapsed)

                phase_info = HEAD_POSE_PROTO.phases[phase_idx]
                bar_w = int((elapsed / HEAD_POSE_PROTO.phase_duration) * 50)
                bar = "#" * bar_w + "-" * (50 - bar_w)

                if yaw is not None:
                    sys.stdout.write(
                        f"\r  {phase_info['name']} [{bar}] {remaining:.1f}s | "
                        f"Yaw:{yaw:6.1f} | N:{len(collected_yaw):4d}"
                    )
                else:
                    sys.stdout.write(
                        f"\r  {phase_info['name']} [{bar}] {remaining:.1f}s | "
                        f"Yaw:   N/A | N:{len(collected_yaw):4d}"
                    )
                sys.stdout.flush()

                display = frame.copy()
                cv2.putText(
                    display,
                    f"{phase_info['name']} [{bar}]",
                    (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2,
                )
                cv2.putText(
                    display,
                    f"Instruction: {phase_info['instruction']}",
                    (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1,
                )
                if yaw is not None:
                    cv2.putText(
                        display,
                        f"Yaw:{yaw:6.1f}  Pitch:{pitch:6.1f}  Roll:{roll:6.1f}",
                        (20, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1,
                    )
                    arrow_yaw = " <--" if yaw < -2 else (" -->" if yaw > 2 else " ^")
                    arrow_pitch = " v" if pitch < -2 else (" ^" if pitch > 2 else " --")
                    cv2.putText(
                        display,
                        f"Direction: Yaw{arrow_yaw}  Pitch{arrow_pitch}",
                        (20, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1,
                    )
                cv2.putText(
                    display, "[Q] to quit",
                    (20, frame_h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128, 128, 128), 1,
                )
                cv2.imshow(WINDOW_NAME, display)

                if elapsed >= HEAD_POSE_PROTO.phase_duration:
                    phase_name = phase_info["name"]
                    arr_yaw = np.array(collected_yaw)
                    arr_pitch = np.array(collected_pitch)
                    arr_roll = np.array(collected_roll)

                    phase_results[phase_name] = {
                        "frames": len(arr_yaw),
                        "yaw_mean": round(float(np.mean(arr_yaw)), 2),
                        "yaw_std": round(float(np.std(arr_yaw)), 2),
                        "pitch_mean": round(float(np.mean(arr_pitch)), 2),
                        "pitch_std": round(float(np.std(arr_pitch)), 2),
                        "roll_mean": round(float(np.mean(arr_roll)), 2),
                        "roll_std": round(float(np.std(arr_roll)), 2),
                    }

                    print(
                        f"\n  -> 完成: yaw_mean={phase_results[phase_name]['yaw_mean']:.1f}, "
                        f"yaw_std={phase_results[phase_name]['yaw_std']:.2f}, "
                        f"pitch_mean={phase_results[phase_name]['pitch_mean']:.1f}, "
                        f"pitch_std={phase_results[phase_name]['pitch_std']:.2f}"
                    )

                    collected_yaw.clear()
                    collected_pitch.clear()
                    collected_roll.clear()
                    phase_idx += 1
                    phase_start = time.time()

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    logger.info("用户提前终止。")
                    quit_requested = True
                    break

        # After with block exits, opencv_windows.__exit__ runs (windows cleaned up)
        # camera_context.__exit__ runs (camera released)

    # face_landmarker.close() intentionally omitted — MediaPipe's close()
    # blocks indefinitely on its internal thread join. os._exit() (via
    # cleanup_exit) bypasses this bug; OS reclaims all resources on exit.

    if quit_requested:
        cleanup_exit(0)

    p1 = phase_results[HEAD_POSE_PROTO.phases[0]["name"]]
    p4 = phase_results[HEAD_POSE_PROTO.phases[3]["name"]]

    drift_yaw = round(p4["yaw_mean"] - p1["yaw_mean"], 2)
    drift_pitch = round(p4["pitch_mean"] - p1["pitch_mean"], 2)

    frontal_yaw_std = p1["yaw_std"]
    frontal_pitch_std = p1["pitch_std"]
    frontal_pass = (
        frontal_yaw_std < HEAD_POSE.frontal_yaw_std_thresh
        and frontal_pitch_std < HEAD_POSE.frontal_pitch_std_thresh
    )

    result_dict = {
        "spike": "S3_head_pose",
        "phases": phase_results,
        "drift": {
            "yaw_drift": drift_yaw,
            "pitch_drift": drift_pitch,
        },
        "frontal_pass": frontal_pass,
    }

    output_path = os.path.join(os.path.dirname(__file__), "s3_result.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_dict, f, indent=2, ensure_ascii=False)

    print("\n")
    print("=" * 60)
    print("       S3: 头部姿态 3D 验证结果")
    print("=" * 60)
    for name, r in phase_results.items():
        print(f"  {name}:")
        print(f"    yaw  (mean/std): {r['yaw_mean']:7.2f} / {r['yaw_std']:5.2f}")
        print(f"    pitch(mean/std): {r['pitch_mean']:7.2f} / {r['pitch_std']:5.2f}")
        print(f"    roll (mean/std): {r['roll_mean']:7.2f} / {r['roll_std']:5.2f}")
    print("  回归漂移:")
    print(f"    yaw  drift: {drift_yaw:+.2f}°")
    print(f"    pitch drift: {drift_pitch:+.2f}°")
    print("=" * 60)

    if frontal_pass:
        logger.info("正视抖动在阈值范围内 (< %.0f°)", HEAD_POSE.frontal_yaw_std_thresh)
    else:
        logger.error(
            "正视抖动超标: yaw_std=%.2f, pitch_std=%.2f",
            frontal_yaw_std,
            frontal_pitch_std,
        )
    print(f"\n结果已保存到: {output_path}")

    cleanup_exit(0 if frontal_pass else 1)


if __name__ == "__main__":
    main()

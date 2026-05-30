"""
S2: 基线校准算法原型 (Baseline Calibration Prototype)
实现自适应基线校准算法：7秒采集 → 三级过滤 → 截尾均值 → CQS评分 → 眼镜检测。

用法: python spike/baseline_proto.py [--label <name>]
  --label: 可选标签，如 "no_glasses", "with_glasses", "run1"
  结果保存到 spike/s2_result.json 和 spike/results/D1/s2_blendshapes_<label>.json

验收: 3次校准 baseline_ear CV < 10%, CQS PASS >= 80%

修复记录:
  - 消除重复代码，使用 spike/common.py 中的统一算法实现
  - 修复: os._exit() 在 with 块内导致窗口/摄像头无法正确清理的问题
  - 新增: Blendshapes 数据采集功能
"""

import sys
import os
import time
import json
import logging
import argparse

import cv2
import mediapipe as mp
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import BASELINE, EYE, HEAD_POSE
from spike.common import (
    camera_context,
    cleanup_exit,
    compute_ear_from_landmarks,
    create_face_landmarker,
    extract_landmarks,
    get_camera_matrix,
    normalize_yaw,
    opencv_windows,
    setup_logging,
    solve_head_pose_from_matrix,
)

logger = logging.getLogger("eyefocus.spike")
WINDOW_NAME = "S2: Baseline Calibration"


def collect_baseline_data(cap, face_landmarker, camera_matrix, frame_w, frame_h):
    """采集基线数据，返回 (ear_sequence, blendshapes_sequence, total_frames, valid_frames)。"""
    ear_sequence = []
    blendshapes_sequence = []
    total_frames = 0
    valid_frames = 0
    start_time = time.time()

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

            ear_avg = 0.0
            face_detected = False
            is_valid = False

            pts = extract_landmarks(result, frame_w, frame_h)
            if pts is not None:
                face_detected = True
                # Collect blendshapes if available
                frame_blendshapes = None
                if result.face_blendshapes and result.face_blendshapes[0]:
                    # blendshapes is a list of Blendshapes objects with .category_name and .score
                    bs = result.face_blendshapes[0]
                    frame_blendshapes = [(b.category_name, b.score) for b in bs]

                # Use MediaPipe's built-in transformation matrix for head pose
                if (
                    result.facial_transformation_matrixes is not None
                    and result.facial_transformation_matrixes[0] is not None
                ):
                    matrix = np.array(
                        result.facial_transformation_matrixes[0]
                    ).flatten()
                    raw_yaw, pitch, _ = solve_head_pose_from_matrix(matrix)
                else:
                    raw_yaw, pitch = None, None

                # Handle ±180° boundary: normalize raw yaw so threshold check works
                # for all frontal-face angles (e.g. 177° → -3°, -177° → 3°)
                yaw = normalize_yaw(raw_yaw) if raw_yaw is not None else None

                if yaw is not None and abs(yaw) <= HEAD_POSE.yaw_thresh and abs(pitch) <= HEAD_POSE.pitch_thresh:
                    ear_avg, ear_valid = compute_ear_from_landmarks(pts)
                    if ear_avg >= EYE.ear_min:
                        is_valid = True
                        valid_frames += 1
                        ear_sequence.append(ear_avg)
                        if frame_blendshapes is not None:
                            blendshapes_sequence.append(frame_blendshapes)

            total_frames += 1
            elapsed = time.time() - start_time
            remaining = max(0, BASELINE.collection_duration - elapsed)

            sys.stdout.write(
                f"\r  剩余: {remaining:.1f}s | EAR: {ear_avg:.4f} | "
                f"Valid: {valid_frames}/{total_frames} | Face: {'Y' if face_detected else 'N'}"
            )
            sys.stdout.flush()

            bar_w = int((elapsed / BASELINE.collection_duration) * 50)
            bar = "#" * bar_w + "-" * (50 - bar_w)

            display = frame.copy()
            cv2.putText(display, f"Calibrating: [{bar}] {remaining:.1f}s",
                        (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.putText(display, f"EAR: {ear_avg:.4f}  |  Valid: {valid_frames}/{total_frames}",
                        (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
            cv2.putText(display, "[Q] to quit",
                        (20, frame_h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128, 128, 128), 1)
            cv2.imshow(WINDOW_NAME, display)

            if elapsed >= BASELINE.collection_duration:
                break

            if cv2.waitKey(1) & 0xFF == ord('q'):
                return None, None, None, None, True  # quit requested

    return ear_sequence, blendshapes_sequence, total_frames, valid_frames, False


def compute_baseline_stats(ear_sequence, total_frames, valid_frames):
    """计算基线统计值和 CQS。"""
    ear_arr = np.array(ear_sequence)

    n_trim = max(1, int(len(ear_arr) * BASELINE.trim_ratio))
    ear_sorted = np.sort(ear_arr)
    ear_trimmed = ear_sorted[n_trim:-n_trim] if len(ear_sorted) > 2 * n_trim else ear_sorted

    baseline_ear = float(np.mean(ear_trimmed))
    ear_cv = float(np.std(ear_arr) / np.mean(ear_arr)) if np.mean(ear_arr) > 0 else 1.0
    ear_variance = float(np.var(ear_arr))

    # CQS from spike/common.py
    from spike.common import calc_cqs
    cqs = calc_cqs(valid_frames, total_frames, ear_cv)
    glasses_mode = ear_variance > EYE.glasses_variance_thresh

    return baseline_ear, ear_cv, ear_variance, cqs, glasses_mode


def main():
    import mediapipe as mp
    from mediapipe import Image

    parser = argparse.ArgumentParser(description="S2 基线校准")
    parser.add_argument("--label", type=str, default="default",
                        help="标签，如 'no_glasses', 'with_glasses', 'run1'")
    args = parser.parse_args()

    setup_logging()
    logger.info("基线校准开始")
    logger.info(f"采集时长: {BASELINE.collection_duration}s")
    logger.info(f"标签: {args.label}")
    logger.info("请保持正常坐姿，自然注视屏幕。")
    print()

    face_landmarker = create_face_landmarker()

    with camera_context(0) as cap:
        if not cap.isOpened():
            logger.error("无法打开摄像头 (index 0)")
            cleanup_exit(1)

        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        camera_matrix = get_camera_matrix(frame_w, frame_h)

        ear_sequence, blendshapes_sequence, total_frames, valid_frames, quit_req = collect_baseline_data(
            cap, face_landmarker, camera_matrix, frame_w, frame_h
        )

        if quit_req:
            logger.info("用户提前终止。")
            cleanup_exit(0)

    # face_landmarker.close() intentionally omitted — MediaPipe's close()
    # blocks indefinitely. os._exit() (via cleanup_exit) bypasses this.

    if ear_sequence is None or len(ear_sequence) < BASELINE.min_valid_frames:
        logger.error("有效帧数不足 (< %d)，请重试。", BASELINE.min_valid_frames)
        cleanup_exit(1)

    baseline_ear, ear_cv, ear_variance, cqs, glasses_mode = compute_baseline_stats(
        ear_sequence, total_frames, valid_frames
    )

    result_dict = {
        "spike": "S2_baseline_proto",
        "total_frames": total_frames,
        "valid_frames": valid_frames,
        "valid_ratio": round(valid_frames / max(total_frames, 1), 3),
        "ear_raw_count": len(ear_sequence),
        "baseline_ear": round(baseline_ear, 4),
        "ear_cv": round(ear_cv, 3),
        "ear_variance": round(ear_variance, 6),
        "cqs": cqs,
        "cqs_pass": cqs >= BASELINE.cqs_threshold,
        "glasses_mode": glasses_mode,
        "params": {
            "yaw_thresh": HEAD_POSE.yaw_thresh,
            "pitch_thresh": HEAD_POSE.pitch_thresh,
            "ear_min": EYE.ear_min,
            "trim_ratio": BASELINE.trim_ratio,
            "glasses_variance_thresh": EYE.glasses_variance_thresh,
        },
    }

    output_path = os.path.join(os.path.dirname(__file__), "s2_result.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_dict, f, indent=2, ensure_ascii=False)

    # Save blendshapes data
    blendshapes_output_path = None
    if blendshapes_sequence:
        blendshapes_result = {
            "spike": "S2_blendshapes",
            "label": args.label,
            "total_frames": total_frames,
            "valid_frames": valid_frames,
            "baseline_ear": round(baseline_ear, 4),
            "ear_cv": round(ear_cv, 3),
            "cqs": cqs,
            "cqs_pass": cqs >= BASELINE.cqs_threshold,
            "blendshapes_count": len(blendshapes_sequence),
            "sample_blendshapes": blendshapes_sequence[:5] if blendshapes_sequence else [],
            "blendshapes_names": [b[0] for b in blendshapes_sequence[0]] if blendshapes_sequence else [],
        }
        # Save to results/D1 directory
        results_dir = os.path.join(os.path.dirname(__file__), "results", "D1")
        os.makedirs(results_dir, exist_ok=True)
        blendshapes_output_path = os.path.join(results_dir, f"s2_blendshapes_{args.label}.json")
        with open(blendshapes_output_path, "w", encoding="utf-8") as f:
            json.dump(blendshapes_result, f, indent=2, ensure_ascii=False)

    print("\n")
    print("=" * 50)
    print("       S2: 基线校准结果")
    print("=" * 50)
    print(f"  总帧数:        {result_dict['total_frames']}")
    print(f"  有效帧数:      {result_dict['valid_frames']} ({result_dict['valid_ratio']:.1%})")
    print(f"  EAR 均值:     {result_dict['baseline_ear']:.4f}")
    print(f"  EAR CV:       {result_dict['ear_cv']:.3f}")
    print(f"  EAR 方差:     {result_dict['ear_variance']:.6f}")
    print(f"  CQS:          {result_dict['cqs']:.3f} {'[PASS]' if result_dict['cqs_pass'] else '[FAIL]'}")
    print(f"  眼镜模式:     {'是' if result_dict['glasses_mode'] else '否'}")
    print("=" * 50)
    print(f"\n结果已保存到: {output_path}")
    if blendshapes_output_path:
        print(f"Blendshapes 已保存到: {blendshapes_output_path}")
        print(f"  - 有效帧数: {len(blendshapes_sequence)}")
        if blendshapes_sequence:
            print(f"  - Blendshapes 维度: {len(blendshapes_sequence[0])}")
            print(f"  - 前5个特征: {[b[0] for b in blendshapes_sequence[0][:5]]}")

    cleanup_exit(0)


if __name__ == "__main__":
    main()

"""
S5: EAR 方差采集 (EAR Variance Collection)
为眼镜自动检测确定经验阈值（glasses_mode 触发阈值）。

用法: python spike/ear_variance.py [--label "no_glasses"|"with_glasses"]
验收: 输出正常/戴眼镜用户的 EAR 方差分布，确定推荐阈值

修复记录:
  - 添加头部姿态三级过滤（与 S2 一致），确保采集稳定正视状态下的 EAR
  - 修复: sys.exit() 在 with 块内导致窗口/摄像头无法正确清理的问题

D2 任务：分别以 --label "no_glasses" 和 --label "with_glasses" 运行 3 次。
"""

import argparse
import json
import logging
import os
import sys
import time

import cv2
import mediapipe as mp
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import CAMERA, EAR_VARIANCE, EYE, HEAD_POSE
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
    solve_head_pose,
)

logger = logging.getLogger("eyefocus.spike")
WINDOW_NAME = "S5: EAR Variance Collection"


def main() -> None:
    setup_logging()
    quit_requested = False

    parser = argparse.ArgumentParser(description="S5: EAR 方差采集")
    parser.add_argument(
        "--label",
        type=str,
        default="unknown",
        choices=["no_glasses", "with_glasses", "unknown"],
        help="当前用户的眼镜状态标签",
    )
    args = parser.parse_args()

    face_landmarker = create_face_landmarker()

    with camera_context(CAMERA.index) as cap:
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        camera_matrix = get_camera_matrix(frame_w, frame_h)

        logger.info("EAR 方差采集开始 (标签: %s)", args.label)
        logger.info("采集时长: %.0fs", EAR_VARIANCE.collection_duration)
        logger.info("请保持正常坐姿，自然注视屏幕。")
        print()

        ear_sequence: list = []
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

                pts = extract_landmarks(result, frame_w, frame_h)
                if pts is not None:
                    face_detected = True
                    raw_yaw, pitch, _ = solve_head_pose(pts, camera_matrix)

                    # Handle ±180° boundary: normalize raw yaw so threshold check works
                    yaw = normalize_yaw(raw_yaw) if raw_yaw is not None else None

                    if (
                        yaw is not None
                        and abs(yaw) <= HEAD_POSE.yaw_thresh
                        and abs(pitch) <= HEAD_POSE.pitch_thresh
                    ):
                        ear_avg, ear_valid = compute_ear_from_landmarks(pts)
                        if ear_valid:
                            valid_frames += 1
                            ear_sequence.append(ear_avg)

                total_frames += 1
                elapsed = time.time() - start_time
                remaining = max(0, EAR_VARIANCE.collection_duration - elapsed)

                sys.stdout.write(
                    f"\r  剩余: {remaining:.1f}s | EAR: {ear_avg:.4f} | "
                    f"Face: {'Y' if face_detected else 'N'} | "
                    f"Valid: {valid_frames}/{total_frames}"
                )
                sys.stdout.flush()

                bar_w = int((elapsed / EAR_VARIANCE.collection_duration) * 50)
                bar = "#" * bar_w + "-" * (50 - bar_w)

                display = frame.copy()
                cv2.putText(
                    display,
                    f"Collecting: [{bar}] {remaining:.1f}s",
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2,
                )
                cv2.putText(
                    display,
                    f"Label: {args.label} | EAR: {ear_avg:.4f} | Valid: {valid_frames}/{total_frames}",
                    (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1,
                )
                cv2.imshow(WINDOW_NAME, display)

                if elapsed >= EAR_VARIANCE.collection_duration:
                    break

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    logger.info("用户提前终止。")
                    quit_requested = True
                    break

        # opencv_windows.__exit__ runs here (window cleaned up)
        # camera_context.__exit__ runs here (camera released)

    # face_landmarker.close() intentionally omitted — MediaPipe's close()
    # blocks indefinitely. os._exit() (via cleanup_exit) bypasses this.

    if quit_requested:
        cleanup_exit(0)

    ear_arr = np.array(ear_sequence)

    if len(ear_arr) < 30:
        logger.error("有效帧数不足 (< 30)，请重试。")
        cleanup_exit(1)

    window_variances = []
    for i in range(0, len(ear_arr) - EAR_VARIANCE.variance_window + 1, EAR_VARIANCE.variance_window):
        win = ear_arr[i : i + EAR_VARIANCE.variance_window]
        window_variances.append(float(np.var(win)))

    overall_var = float(np.var(ear_arr))
    overall_std = float(np.std(ear_arr))
    overall_mean = float(np.mean(ear_arr))

    result_dict = {
        "spike": "S5_ear_variance",
        "label": args.label,
        "total_frames": total_frames,
        "valid_frames": valid_frames,
        "valid_ratio": round(valid_frames / max(total_frames, 1), 3),
        "ear_mean": round(overall_mean, 4),
        "ear_std": round(overall_std, 4),
        "ear_variance": round(overall_var, 6),
        "window_variances": [round(v, 6) for v in window_variances],
        "window_variance_mean": round(float(np.mean(window_variances)), 6),
        "window_variance_max": round(float(np.max(window_variances)), 6),
        "window_variance_std": round(float(np.std(window_variances)), 6),
        "window_count": len(window_variances),
        "params": {
            "yaw_thresh": HEAD_POSE.yaw_thresh,
            "pitch_thresh": HEAD_POSE.pitch_thresh,
            "ear_min": EYE.ear_min,
            "variance_window": EAR_VARIANCE.variance_window,
        },
    }

    print("\n")
    print("=" * 50)
    print(f"       S5: EAR 方差采集 ({args.label})")
    print("=" * 50)
    print(f"  总帧数:        {result_dict['total_frames']}")
    print(f"  有效帧数:      {result_dict['valid_frames']} ({result_dict['valid_ratio']:.1%})")
    print(f"  EAR 均值:      {result_dict['ear_mean']:.4f}")
    print(f"  EAR 标准差:    {result_dict['ear_std']:.4f}")
    print(f"  EAR 总体方差:  {result_dict['ear_variance']:.6f}")
    print(f"  滑窗方差均值:  {result_dict['window_variance_mean']:.6f}")
    print(f"  滑窗方差最大值: {result_dict['window_variance_max']:.6f}")
    print("=" * 50)

    output_path = os.path.join(
        os.path.dirname(__file__), f"s5_result_{args.label}.json"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_dict, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存到: {output_path}")

    if args.label == "with_glasses" and result_dict["window_variance_mean"] < 0.001:
        logger.warning("戴眼镜用户方差偏低，可能眼镜框未干扰 MediaPipe 关键点。")
    elif args.label == "no_glasses" and result_dict["window_variance_mean"] > 0.003:
        logger.warning("正常用户方差偏高，可能光线/姿态影响。请确保校准期间保持稳定。")

    cleanup_exit(0)


if __name__ == "__main__":
    main()

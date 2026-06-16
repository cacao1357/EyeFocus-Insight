"""
spike/ear_vs_blendshape.py — EAR vs Blendshape 精度对比测试 (v4)

Pillow 渲染中文大字 + 声音提示。按空格开始，跟着提示做。
"""

import csv
import logging
import os
import sys
import time
from datetime import datetime

import cv2
import numpy as np

logging.basicConfig(level=logging.WARNING)

from mediapipe import Image as MpImage, ImageFormat as MpImageFormat
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core import base_options as mp_base_options

# ── Pillow 中文渲染 ──
from PIL import Image, ImageDraw, ImageFont

# 找一个中文字体
_CJK_FONTS = [
    "C:/Windows/Fonts/msyh.ttc",       # Microsoft YaHei
    "C:/Windows/Fonts/simhei.ttf",      # SimHei
    "C:/Windows/Fonts/msyhbd.ttc",      # YaHei Bold
    "/System/Library/Fonts/PingFang.ttc",
]
FONT_PATH = next((f for f in _CJK_FONTS if os.path.exists(f)), None)

# 声音
try:
    import winsound
    def beep(freq, dur):
        winsound.Beep(freq, dur)
except ImportError:
    def beep(*_):
        print("\a", end="", flush=True)

# 模型路径
_MODEL_PATHS = [
    os.path.join(os.path.dirname(__file__), "..", "face_landmarker.task"),
    os.path.join(os.getcwd(), "face_landmarker.task"),
    os.path.join(os.path.dirname(__file__), "face_landmarker.task"),
]
MODEL_PATH = next((p for p in _MODEL_PATHS if os.path.exists(p)), None)
if not MODEL_PATH:
    print("找不到 face_landmarker.task"); sys.exit(1)

# EAR
LEFT_EYE = np.array([33, 160, 158, 133, 153, 144])
RIGHT_EYE = np.array([362, 385, 387, 263, 380, 373])

def ear(pts, idxs):
    p = pts[idxs]
    a = np.linalg.norm(p[1] - p[5])
    b = np.linalg.norm(p[2] - p[4])
    c = np.linalg.norm(p[0] - p[3])
    return float((a + b) / (2.0 * c)) if c > 1e-6 else 0.0

def get_bs(result):
    d = {}
    if result.face_blendshapes and result.face_blendshapes[0]:
        for bs in result.face_blendshapes[0]:
            k = getattr(bs, 'display_name', None) or getattr(bs, 'category_name', None) or str(bs.index)
            d[k] = bs.score
    return d

PHASES = [
    ("正面睁眼 — 正对屏幕，正常睁眼看摄像头", 5),
    ("正面闭眼 — 轻轻闭上双眼", 5),
    ("右转30度睁眼 — 头向右转30度，睁大眼睛", 5),
    ("右转30度闭眼 — 保持右转，闭上眼睛", 5),
    ("低头睁眼 — 低头看桌面方向，睁大眼睛", 5),
    ("低头闭眼 — 保持低头，闭上眼睛", 5),
    ("右转60度睁眼 — 头向右转到最大，睁眼", 5),
    ("右转60度闭眼 — 保持右转，闭上眼睛", 5),
]


def put_chinese(frame, text, y, size=40, color=(0, 255, 0), shadow=True):
    """用 Pillow 在 OpenCV frame 上画中文"""
    h, w = frame.shape[:2]
    # OpenCV BGR → PIL RGB
    pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    font = ImageFont.truetype(FONT_PATH, size) if FONT_PATH else ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = (w - tw) // 2

    if shadow:
        draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=color)

    # PIL → OpenCV BGR
    frame[:] = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "..", "reports")
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, f"ear_vs_blendshape_{datetime.now():%Y%m%d_%H%M%S}.csv")

    # MediaPipe
    opts = vision.FaceLandmarkerOptions(
        base_options=mp_base_options.BaseOptions(model_asset_path=MODEL_PATH),
        output_face_blendshapes=True,
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    detector = vision.FaceLandmarker.create_from_options(opts)

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("无法打开摄像头"); sys.exit(1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    cv2.namedWindow("EAR vs Blendshape", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("EAR vs Blendshape", cv2.WND_PROP_TOPMOST, 1)

    ts = [0]
    rows = []
    frame_n = 0

    def read():
        nonlocal frame_n
        ret, frame = cap.read()
        if not ret:
            return None, None
        frame_n += 1; ts[0] += 33
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_img = MpImage(image_format=MpImageFormat.SRGB, data=rgb)
        return frame, detector.detect_for_video(mp_img, ts[0])

    # ── 启动画面 ──
    for _ in range(30):
        cap.read()
    for _ in range(200):
        frame, _ = read()
        if frame is None:
            continue
        # 半黑底
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (frame.shape[1], frame.shape[0]), (0, 0, 0), -1)
        frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)
        put_chinese(frame, "按 SPACE 开始测试", frame.shape[0] // 2 - 50, 50, (0, 255, 0))
        put_chinese(frame, "全程约1分钟，跟着提示做", frame.shape[0] // 2 + 20, 28, (200, 200, 200))
        cv2.imshow("EAR vs Blendshape", frame)
        k = cv2.waitKey(50)
        if k == 32:
            break
        if k == ord("q"):
            cap.release(); cv2.destroyAllWindows(); detector.close(); return

    # ── 逐阶段 ──
    for phase_text, duration in PHASES:
        if "—" in phase_text:
            title, hint = phase_text.split("—", 1)
        else:
            title, hint = phase_text, ""
        title = title.strip()
        hint = hint.strip()
        key = title.replace(" ", "_")

        # 倒计时
        for i in range(3, 0, -1):
            frame, _ = read()
            if frame is None:
                continue
            overlay = frame.copy()
            cv2.rectangle(overlay, (0, 0), (frame.shape[1], frame.shape[0]), (0, 0, 0), -1)
            frame = cv2.addWeighted(overlay, 0.6, frame, 0.4, 0)
            put_chinese(frame, f"下一项：{title}", frame.shape[0] // 2 - 90, 40, (255, 255, 0))
            put_chinese(frame, str(i), frame.shape[0] // 2 - 20, 120, (0, 255, 0))
            put_chinese(frame, hint, frame.shape[0] // 2 + 60, 28, (200, 200, 200))
            cv2.imshow("EAR vs Blendshape", frame)
            cv2.waitKey(200)
            if i <= 2:
                beep(500 + i * 200, 100)
        beep(880, 150)

        # 采集阶段
        start_t = time.time()
        while time.time() - start_t < duration:
            frame, result = read()
            if frame is None:
                continue
            remain = int(duration - (time.time() - start_t))
            ear_l = ear_r = 0.0
            bs_l = bs_r = -1.0
            fd = False
            if result and result.face_landmarks and result.face_landmarks[0]:
                fd = True
                lm = np.array([(p.x * frame.shape[1], p.y * frame.shape[0])
                               for p in result.face_landmarks[0]])
                ear_l = ear(lm, LEFT_EYE)
                ear_r = ear(lm, RIGHT_EYE)
                bs = get_bs(result)
                bs_l = bs.get("eyeBlinkLeft", -1.0)
                bs_r = bs.get("eyeBlinkRight", -1.0)

            rows.append({
                "frame": frame_n, "phase": key,
                "ear_avg": round((ear_l + ear_r) / 2, 4),
                "bs_eyeBlinkLeft": round(bs_l, 4),
                "bs_eyeBlinkRight": round(bs_r, 4),
                "face_detected": fd,
            })

            put_chinese(frame, title, frame.shape[0] // 2 - 70, 48, (0, 255, 0))
            put_chinese(frame, f"倒计时 {remain} 秒", frame.shape[0] // 2, 42, (255, 255, 0))
            put_chinese(frame, f"EAR={(ear_l+ear_r)/2:.3f}  BS左={bs_l:.2f}  BS右={bs_r:.2f}",
                       frame.shape[0] // 2 + 70, 28, (200, 200, 200))
            cv2.imshow("EAR vs Blendshape", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                cap.release(); cv2.destroyAllWindows(); detector.close(); return

        beep(660, 200)
        time.sleep(0.2)
        beep(880, 300)

    cap.release(); cv2.destroyAllWindows(); detector.close()

    # ── 汇总 ──
    if not rows:
        print("未采集到数据"); return
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader(); w.writerows(rows)
    print(f"\n✅ CSV: {csv_path}")

    print("\n" + "=" * 85)
    print(f"{'阶段':<25s} {'帧':>4s} {'EAR均值':>8s} {'EAR_std':>7s} {'BS左':>8s} {'BS右':>8s} {'误判%':>6s}")
    print("-" * 85)
    for phase_text, _ in PHASES:
        title = phase_text.split("—")[0].strip()
        key = title.replace(" ", "_")
        sub = [r for r in rows if r["phase"] == key]
        if not sub:
            continue
        ev = [r["ear_avg"] for r in sub if r["face_detected"]]
        bl = [r["bs_eyeBlinkLeft"] for r in sub if r["bs_eyeBlinkLeft"] >= 0]
        br = [r["bs_eyeBlinkRight"] for r in sub if r["bs_eyeBlinkRight"] >= 0]
        em = np.mean(ev) if ev else 0
        es = np.std(ev) if ev else 0
        bm = np.mean(bl) if bl else -1
        brm = np.mean(br) if br else -1
        if "睁眼" in title:
            bad = sum(1 for r in sub if r["bs_eyeBlinkLeft"] > 0.5 or r["bs_eyeBlinkRight"] > 0.5)
        else:
            bad = sum(1 for r in sub if r["ear_avg"] > 0.2)
        rate = bad / len(sub) * 100 if sub else 0
        print(f"{title:<25s} {len(sub):>4d} {em:>8.4f} {es:>7.4f} {bm:>8.4f} {brm:>8.4f} {rate:>5.1f}%")
    print("=" * 85)


if __name__ == "__main__":
    main()

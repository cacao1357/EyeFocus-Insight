"""S-CAL-1 单阶段 spike — 跑 closed_eyes 单阶段确认 UI/TTS。

用法:
    .venv312/Scripts/python.exe -m calibration.tests.spike.spike_single_phase
"""
import logging
import os
import sys

os.environ.setdefault("GLOG_logtostderr", "0")
os.environ.setdefault("MEDIAPIPE_DISABLE_GPU", "1")
os.environ.setdefault("ABSL_CPP_MIN_LOG_LEVEL", "3")

logging.basicConfig(level=logging.INFO)

from calibration.phases.closed_eyes import ClosedEyesPhase
from calibration.config import CalibrationConfig


def main():
    """单阶段演示：构造一个 ClosedEyesPhase，喂合成 EAR 数据，看 TTS 路径。"""
    cfg = CalibrationConfig()
    p = ClosedEyesPhase(
        closed_duration_seconds=cfg.closed_eyes_seconds,
        verify_duration_seconds=cfg.open_eyes_verify_seconds,
        baseline_ear=0.30,
        min_ratio=cfg.closed_eyes_min_ratio,
    )
    print(f"Phase: {p.name}")
    print(f"  tts_intro    = {p.tts_intro}")
    print(f"  tts_complete = {p.tts_complete}")
    print(f"  duration     = {p.duration_seconds}s")

    # 喂合成数据：闭眼 5s + 睁眼 3s
    print("\n--- 喂合成 EAR 数据 ---")
    for i in range(int(cfg.closed_eyes_seconds * 30)):
        p.feed_frame(ear=0.10, yaw=0, pitch=0, timestamp=i / 30.0)
    for i in range(int(cfg.open_eyes_verify_seconds * 30)):
        p.feed_frame(ear=0.30, yaw=0, pitch=0,
                     timestamp=cfg.closed_eyes_seconds + i / 30.0)

    r = p.evaluate()
    print(f"\n--- 评估结果 ---")
    print(f"  success: {r.success}")
    print(f"  summary: {r.summary}")
    print(f"  failure_reason: {r.failure_reason}")

    # 验证 BUG 3 修复：tts_complete 含"睁眼"
    if "睁眼" in p.tts_complete:
        print("\n✅ BUG 3 修复确认：tts_complete 包含'睁眼'")
    else:
        print("\n❌ BUG 3 修复未生效")
        sys.exit(1)

    if r.success:
        print("✅ 单阶段数据采集逻辑 OK")
    else:
        print("❌ 单阶段评估失败")
        sys.exit(1)


if __name__ == "__main__":
    main()

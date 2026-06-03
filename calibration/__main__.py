"""python -m calibration 入口 — 独立运行校准模块，不依赖主程序。

用法：
    python -m calibration              # 使用默认 session_id
    python -m calibration <session_id>
"""
import logging
import os
import sys

# 同 main.py：屏蔽 MediaPipe telemetry
os.environ.setdefault("GLOG_logtostderr", "0")
os.environ.setdefault("MEDIAPIPE_DISABLE_GPU", "1")
os.environ.setdefault("ABSL_CPP_MIN_LOG_LEVEL", "3")

logging.basicConfig(level=logging.INFO,
                    format="[%(asctime)s %(levelname)s %(name)s] %(message)s")

from calibration import run, CalibrationConfig


def main():
    sid = sys.argv[1] if len(sys.argv) > 1 else "standalone_test"
    print(f"启动独立校准 (session={sid})")
    config = CalibrationConfig()
    result = run(session_id=sid, config=config)
    if result is None:
        print("❌ 用户取消 / 失败 / 异常 — 返回 None")
        sys.exit(1)
    print("✅ 校准成功完成")
    print(f"  EAR 基线: {result.signal.ear_mean:.4f}")
    print(f"  眨眼阈值: {result.final_blink_threshold:.4f}")
    print(f"  眨眼率: {result.baseline_blink_rate:.2f}/min")
    print(f"  CQS: {result.cqs:.2f}")
    sys.exit(0)


if __name__ == "__main__":
    main()

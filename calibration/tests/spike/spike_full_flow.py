"""S-CAL-2 全流程 spike — 跑完整 5 阶段（需真机摄像头）。

用法:
    .venv312/Scripts/python.exe -m calibration.tests.spike.spike_full_flow

注意：此脚本需真实摄像头 + 用户按 UI 操作。
本 spike 验证 BUG 1/4/5/6/7 是否修复（从用户角度）。
"""
import logging
import os
import sys

os.environ.setdefault("GLOG_logtostderr", "0")
os.environ.setdefault("MEDIAPIPE_DISABLE_GPU", "1")
os.environ.setdefault("ABSL_CPP_MIN_LOG_LEVEL", "3")

logging.basicConfig(level=logging.INFO)

from calibration import run, CalibrationConfig


def main():
    """完整流程演示。需要真机摄像头 + 用户按 UI 操作。"""
    print("=" * 60)
    print("S-CAL-2 全流程 spike")
    print("=" * 60)
    print("提示：跑此 spike 需打开摄像头 + 真人按 UI 操作。")
    print("     BUG 1 验证：眨眼计数轮必须检出非零数字")
    print("     BUG 4 验证：头部姿态 4 段独立 TTS 指令")
    print("     BUG 5 验证：每阶段显示实时反馈")
    print("     BUG 6 验证：每阶段需点'开始'才推进")
    print("     BUG 7 验证：FINAL_SUMMARY 等待用户确认")
    print()

    sid = sys.argv[1] if len(sys.argv) > 1 else "spike_full"
    config = CalibrationConfig()
    result = run(session_id=sid, config=config)
    if result is None:
        print("\n❌ 流程未完成（取消或异常）")
        sys.exit(1)
    print("\n✅ 校准完成")
    print(f"  EAR 基线: {result.signal.ear_mean:.4f}")
    print(f"  眨眼阈值: {result.final_blink_threshold:.4f}")
    print(f"  CQS: {result.cqs:.2f}")


if __name__ == "__main__":
    main()

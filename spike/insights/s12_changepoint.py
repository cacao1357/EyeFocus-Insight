"""spike/insights/s12_changepoint.py — S12 变点检测原型

输入：合成 1h focus_score 时序，含已知断崖（15min, 40min 处）
方法：ruptures.Pelt(model='rbf') + 自动调 penalty
输出：检测到的变点 + 与真实断崖的时间误差
"""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import ruptures as rpt

from spike.insights._common import gen_focus_timeseries_with_drops, save_result, save_png


def run_spike(target_breakpoints_per_hour=4, error_threshold_s=30, seed=42):
    print("=== S12 变点检测 spike ===")

    # 1. 合成 1h focus_score，含 2 个已知断崖
    n_seconds = 3600
    sample_hz = 1  # 调整：从 2 Hz 降为 1 Hz（plan 中 2 Hz 配 rbf model 太慢，O(n²)）
    true_drops = [900, 2400]  # 15min, 40min（秒）
    signal = gen_focus_timeseries_with_drops(
        n_seconds=n_seconds, sample_hz=sample_hz,
        drop_points=true_drops, seed=seed,
    )
    print(f"输入：{len(signal)} 点 ({n_seconds}s × {sample_hz}Hz)")
    print(f"真实断崖：{true_drops} (秒)")

    # 2. 30s 滑动均值平滑
    window = 30 * sample_hz  # 30s 窗口
    smoothed = np.convolve(signal, np.ones(window) / window, mode='same')

    # 3. PELT — 调整：model='l2' 替代 'rbf'（rbf 在 n=3600+ 极慢，O(n²)）
    # 我们的断崖是均值阶跃，l2 模型（piecewise constant mean）正好适用
    print("\n--- PELT 调 penalty (model='l2') ---")
    sigma_sq = np.var(smoothed)
    n = len(smoothed)
    model_name = "l2"

    best_penalty = None
    best_bkps = None
    best_n_bkps = None
    n_bkps_by_c = {}
    for c in [1.0, 2.0, 3.0, 5.0, 8.0, 12.0]:
        penalty = c * np.log(n) * sigma_sq
        algo = rpt.Pelt(model=model_name).fit(smoothed)
        bkps = algo.predict(pen=penalty)
        # 末尾 bkps[-1] = len(signal)，不算变点
        n_real_bkps = len(bkps) - 1
        n_bkps_by_c[c] = n_real_bkps
        print(f"  penalty_c={c}: {n_real_bkps} 个变点")
        # 优先选接近 target 的
        if best_bkps is None or (
            abs(n_real_bkps - target_breakpoints_per_hour) <
            abs(best_n_bkps - target_breakpoints_per_hour)
        ):
            best_penalty = c
            best_bkps = bkps
            best_n_bkps = n_real_bkps

    detected_seconds = [bkp / sample_hz for bkp in best_bkps[:-1]]
    print(f"\n最终 penalty_c = {best_penalty}, 检测到 {best_n_bkps} 个变点")
    print(f"检测到变点（秒）：{[f'{t:.0f}' for t in detected_seconds]}")

    # 4. 与真实断崖匹配（每个真实断崖找最近的检测点）
    matches = []
    for true_t in true_drops:
        if detected_seconds:
            closest = min(detected_seconds, key=lambda d: abs(d - true_t))
            err = abs(closest - true_t)
        else:
            closest = None
            err = float("inf")
        matches.append({"true_t": true_t, "detected_t": closest, "error_s": err})
        print(f"  真实 {true_t}s → 检测 {closest}s (误差 {err:.0f}s)")

    max_error = max(m["error_s"] for m in matches)

    # 5. 可视化
    times = np.arange(len(signal)) / sample_hz
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(times, signal, alpha=0.4, label="raw")
    ax.plot(times, smoothed, label="smoothed (30s)", color="orange")
    for true_t in true_drops:
        ax.axvline(true_t, color="green", linestyle="--",
                   label=f"true @ {true_t}s")
    for det_t in detected_seconds:
        ax.axvline(det_t, color="red", linestyle=":",
                   label=f"detected @ {det_t:.0f}s")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("focus_score")
    ax.set_title(f"S12 PELT changepoint (model={model_name}, "
                 f"penalty_c={best_penalty}, {best_n_bkps} bkps, "
                 f"max_err={max_error:.0f}s)")
    ax.legend(loc="lower left", fontsize=8)
    png_path = save_png("s12_changepoint", fig)
    plt.close(fig)
    print(f"可视化已保存: {png_path}")

    # 6. 门禁：所有真实断崖必须被检出且误差 < threshold
    all_detected = all(m["detected_t"] is not None for m in matches)
    overall_pass = all_detected and (max_error < error_threshold_s)
    print(f"\n=== 门禁 ===")
    print(f"所有真实断崖被检出: {'PASS' if all_detected else 'FAIL'}")
    print(f"最大误差 < {error_threshold_s}s: "
          f"{'PASS' if max_error < error_threshold_s else 'FAIL'} "
          f"({max_error:.0f}s)")
    print(f"总体: {'PASS' if overall_pass else 'FAIL'}")

    result = {
        "spike": "S12_changepoint",
        "n_seconds": n_seconds,
        "sample_hz": sample_hz,
        "true_drops": true_drops,
        "detected_seconds": [float(t) for t in detected_seconds],
        "matches": [{"true_t": m["true_t"],
                     "detected_t": float(m["detected_t"]) if m["detected_t"] else None,
                     "error_s": float(m["error_s"])} for m in matches],
        "max_error_s": float(max_error),
        "best_penalty_c": float(best_penalty),
        "n_bkps": best_n_bkps,
        "n_bkps_by_penalty_c": {str(c): int(n) for c, n in n_bkps_by_c.items()},
        "error_threshold_s": error_threshold_s,
        "overall_pass": bool(overall_pass),
        "recommended_params": {
            "penalty_c": float(best_penalty),
            "smoothing_window_sec": 30,
            "min_segment_sec": 60,
            "model": model_name,
        },
        "visualization": png_path,
    }
    json_path = save_result("s12_changepoint", result)
    print(f"JSON 已保存: {json_path}")
    return result


if __name__ == "__main__":
    result = run_spike()
    exit(0 if result["overall_pass"] else 1)

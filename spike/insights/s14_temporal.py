"""spike/insights/s14_temporal.py — S14 时序分解原型

输入：14 天小时聚合 focus_score，含已知日内规律（9-11 峰，15-16 谷，19-20 小峰）
方法：statsmodels STL(period=24, robust=True)
输出：daily_pattern[24] + peak_hours top 3 与真实位置对比
"""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from statsmodels.tsa.seasonal import STL

from spike.insights._common import gen_hourly_focus_with_daily_pattern, save_result, save_png


def run_spike(n_days=14, peak_error_threshold_h=1, low_error_threshold_h=1, seed=42):
    print("=== S14 时序分解 spike ===")

    # 1. 合成 14 天数据
    series = gen_hourly_focus_with_daily_pattern(n_days=n_days, seed=seed)
    print(f"输入：{len(series)} 小时 ({n_days} 天)")

    # 真实 pattern：9-11 峰 (~85)，15-16 谷 (~55)，19-20 小峰 (~75)
    true_peaks_top1 = 10  # 9-11 的中点
    true_lows_top1 = 15   # 15-16 的中点

    # 2. STL 分解
    stl = STL(series, period=24, robust=True).fit()
    print("STL fit OK")

    # 3. 提取日内 pattern
    daily_pattern = np.zeros(24)
    counts = np.zeros(24)
    for ts, val in stl.seasonal.items():
        h = ts.hour
        daily_pattern[h] += val
        counts[h] += 1
    daily_pattern = np.where(counts > 0, daily_pattern / counts, 0)

    # 加入 trend 末段均值，得到绝对曲线
    overall_mean = stl.trend.iloc[-24:].mean()
    daily_curve = daily_pattern + overall_mean

    print("\n小时 pattern (前 6 高):")
    sorted_h = np.argsort(daily_curve)[::-1]
    for h in sorted_h[:6]:
        print(f"  {h:02d}:00 -> {daily_curve[h]:.1f}")

    # 4. 找 peak 与 low
    peak_top3 = sorted_h[:3].tolist()
    low_top3 = sorted_h[-3:].tolist()
    print(f"\nPeak hours top 3: {peak_top3}")
    print(f"Low hours top 3:  {low_top3}")

    # 5. 与真实位置对比
    err_peak = min(abs(p - true_peaks_top1) for p in peak_top3)
    err_low = min(abs(l - true_lows_top1) for l in low_top3)
    print(f"\nPeak top1 与真实 ({true_peaks_top1}h) 误差: {err_peak}h")
    print(f"Low top1 与真实 ({true_lows_top1}h) 误差: {err_low}h")

    # 6. 可视化
    fig, axes = plt.subplots(2, 1, figsize=(14, 8))
    axes[0].plot(series.index, series.values, alpha=0.5, label="raw hourly")
    axes[0].plot(stl.trend.index, stl.trend.values, label="trend")
    axes[0].set_title(f"S14 input + trend ({n_days} days)")
    axes[0].legend()

    axes[1].bar(range(24), daily_curve, alpha=0.7)
    axes[1].axvline(true_peaks_top1, color="green", linestyle="--",
                    label=f"true peak ~{true_peaks_top1}h")
    axes[1].axvline(true_lows_top1, color="red", linestyle="--",
                    label=f"true low ~{true_lows_top1}h")
    axes[1].set_xlabel("Hour of day")
    axes[1].set_ylabel("focus_score")
    axes[1].set_title("Daily pattern (STL seasonal + trend)")
    axes[1].legend()

    png_path = save_png("s14_temporal", fig)
    plt.close(fig)
    print(f"可视化已保存: {png_path}")

    # 7. 门禁
    overall_pass = err_peak <= peak_error_threshold_h and err_low <= low_error_threshold_h
    print(f"\n=== 门禁 ===")
    print(f"Peak 误差 <= {peak_error_threshold_h}h: "
          f"{'PASS' if err_peak <= peak_error_threshold_h else 'FAIL'} ({err_peak}h)")
    print(f"Low  误差 <= {low_error_threshold_h}h: "
          f"{'PASS' if err_low <= low_error_threshold_h else 'FAIL'} ({err_low}h)")
    print(f"总体: {'PASS' if overall_pass else 'FAIL'}")

    result = {
        "spike": "S14_temporal",
        "n_days": n_days,
        "n_hours": len(series),
        "true_peak_top1": true_peaks_top1,
        "true_low_top1": true_lows_top1,
        "detected_peak_top3": peak_top3,
        "detected_low_top3": low_top3,
        "peak_error_h": int(err_peak),
        "low_error_h": int(err_low),
        "daily_curve": [float(v) for v in daily_curve],
        "peak_error_threshold_h": peak_error_threshold_h,
        "low_error_threshold_h": low_error_threshold_h,
        "overall_pass": bool(overall_pass),
        "recommended_params": {
            "period": 24,
            "robust": True,
            "min_days_for_stl": 7,
            "histogram_fallback_threshold_days": 7,
        },
        "visualization": png_path,
    }
    json_path = save_result("s14_temporal", result)
    print(f"JSON 已保存: {json_path}")
    return result


if __name__ == "__main__":
    result = run_spike()
    exit(0 if result["overall_pass"] else 1)

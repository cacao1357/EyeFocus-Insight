"""spike/insights/s15_attribution.py — S15 关联分析原型

输入：合成 frames 数据（含 light_level、hour、focus_score、blink_rate）
方法：
  - Welch's t-test (光照差 vs 正常 → focus 对比)
  - Spearman 相关 (blink_rate ↔ focus)
  - ANOVA + eta² (24 小时段 → focus 差异)
  - Cohen's d 效应量
输出：findings 列表 + 各因素 effect_size
"""
import json
import numpy as np
import pandas as pd
from scipy import stats

from spike.insights._common import save_result


def gen_frames(n_per_condition=500, seed=42):
    """生成合成 frames 数据（不依赖真实 DB）。
    光照差时 focus 平均降 15 分；blink 与 focus 负相关。
    """
    rng = np.random.default_rng(seed)
    rows = []

    # 光照差：~focus 65，blink 1.4
    for _ in range(n_per_condition):
        focus = rng.normal(65, 10)
        blink = rng.normal(1.4, 0.2)
        rows.append({"light_level": "dark", "focus_score": focus,
                     "blink_rate": blink, "hour": int(rng.uniform(8, 22))})

    # 光照正常：~focus 80，blink 1.0
    for _ in range(n_per_condition):
        focus = rng.normal(80, 8)
        blink = rng.normal(1.0, 0.15)
        rows.append({"light_level": "normal", "focus_score": focus,
                     "blink_rate": blink, "hour": int(rng.uniform(8, 22))})

    df = pd.DataFrame(rows)
    return df


def compute_cohens_d(a, b):
    pooled_std = np.sqrt((a.std() ** 2 + b.std() ** 2) / 2)
    return (a.mean() - b.mean()) / pooled_std if pooled_std > 0 else 0


def run_spike(p_threshold=0.05, effect_threshold=0.3, seed=42):
    print("=== S15 关联分析 spike ===")

    df = gen_frames(n_per_condition=500, seed=seed)
    print(f"输入：{len(df)} 行 × {len(df.columns)} 列")
    print(df.describe())

    findings = []

    # 1. Welch's t-test: 光照差 vs 正常
    dark = df[df["light_level"] == "dark"]["focus_score"]
    normal = df[df["light_level"] == "normal"]["focus_score"]
    t_stat, p_val = stats.ttest_ind(dark, normal, equal_var=False)
    d = compute_cohens_d(dark, normal)
    diff = float(normal.mean() - dark.mean())
    print(f"\n光照对比: t={t_stat:.3f}, p={p_val:.2e}, Cohen's d={d:.3f}, "
          f"光照差 focus 比正常低 {diff:.1f}")
    if p_val < p_threshold and abs(d) > effect_threshold:
        findings.append({
            "factor": "光照条件",
            "comparison": "dark vs normal",
            "test": "Welch t-test",
            "statistic": float(t_stat),
            "p_value": float(p_val),
            "effect_size_cohens_d": float(d),
            "description": f"光照差时专注度比正常低 {diff:.1f} 分 (p={p_val:.2e}, d={d:.2f})",
            "suggestion": "环境光照差会显著降低专注度，建议改善照明",
        })

    # 2. Spearman 相关: blink_rate ↔ focus
    rho, p_val2 = stats.spearmanr(df["blink_rate"], df["focus_score"])
    print(f"\nblink_rate ~ focus_score: rho={rho:.3f}, p={p_val2:.2e}")
    if p_val2 < p_threshold and abs(rho) > effect_threshold:
        findings.append({
            "factor": "眨眼率",
            "comparison": "blink_rate vs focus_score",
            "test": "Spearman",
            "statistic": float(rho),
            "p_value": float(p_val2),
            "effect_size_correlation": float(rho),
            "description": f"眨眼率与专注度{'负' if rho < 0 else '正'}相关 (rho={rho:.2f})",
            "suggestion": "眨眼频率升高常预示疲劳，注意疲劳信号",
        })

    # 3. ANOVA: hour → focus（24 个组中只看有数据的）
    hour_groups = [df[df["hour"] == h]["focus_score"] for h in range(24)]
    hour_groups = [g for g in hour_groups if len(g) >= 30]
    if len(hour_groups) >= 3:
        f_stat, p_val3 = stats.f_oneway(*hour_groups)
        # eta² 简化计算
        grand_mean = df["focus_score"].mean()
        ss_between = sum(len(g) * (g.mean() - grand_mean) ** 2 for g in hour_groups)
        ss_total = ((df["focus_score"] - grand_mean) ** 2).sum()
        eta_sq = ss_between / ss_total if ss_total > 0 else 0
        print(f"\n时段对比 ANOVA: F={f_stat:.2f}, p={p_val3:.2e}, eta²={eta_sq:.3f}")
        # ANOVA 效应量门槛 eta² > 0.06 (中等以上)
        if p_val3 < p_threshold and eta_sq > 0.06:
            findings.append({
                "factor": "工作时段",
                "test": "ANOVA",
                "statistic": float(f_stat),
                "p_value": float(p_val3),
                "effect_size_eta_squared": float(eta_sq),
                "description": f"不同时段专注度差异显著 (eta²={eta_sq:.2f})",
                "suggestion": "工作时段对专注度影响显著，关注高效时段安排",
            })

    print(f"\n发现 {len(findings)} 个显著关联")
    for f in findings:
        print(f"  OK {f['factor']}: {f['description']}")
        print(f"    建议: {f['suggestion']}")

    # 4. 门禁：至少 1 个 finding
    overall_pass = len(findings) >= 1
    print(f"\n=== 门禁 ===")
    print(f">= 1 个 p<{p_threshold} + |effect|>{effect_threshold}: "
          f"{'PASS' if overall_pass else 'FAIL'} (n={len(findings)})")

    result = {
        "spike": "S15_attribution",
        "n_rows": len(df),
        "findings": findings,
        "p_threshold": p_threshold,
        "effect_threshold": effect_threshold,
        "overall_pass": bool(overall_pass),
        "recommended_params": {
            "p_value_threshold": p_threshold,
            "min_effect_size_cohens_d": effect_threshold,
            "min_effect_size_eta_squared": 0.06,
            "min_samples_per_group": 30,
            "top_n_findings": 5,
        },
    }
    json_path = save_result("s15_attribution", result)
    print(f"JSON 已保存: {json_path}")
    return result


if __name__ == "__main__":
    result = run_spike()
    exit(0 if result["overall_pass"] else 1)

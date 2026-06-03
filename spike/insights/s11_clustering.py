"""spike/insights/s11_clustering.py — S11 聚类分析原型验证

输入：合成 32 sessions（4 种已知模式 × 8）
方法：KMeans + StandardScaler + 自动选 k (silhouette ∈ [2,6])
输出：选出的 k + silhouette + 聚类标签 + 与真实模式的对齐度
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import numpy as np
import matplotlib
matplotlib.use("Agg")  # 无 GUI 环境
import matplotlib.pyplot as plt

from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score
from sklearn.decomposition import PCA

from _common import gen_synthetic_sessions, sessions_to_matrix, save_result, save_png


def run_spike(k_range=(2, 6), silhouette_threshold=0.25, alignment_threshold=75.0, target_k=4, seed=42):
    print("=== S11 聚类分析 spike ===")

    # 1. 合成 32 sessions（4 模式 × 8）
    sessions = gen_synthetic_sessions(n_per_mode=8, seed=seed)
    X, feature_names = sessions_to_matrix(sessions)
    print(f"输入：{len(sessions)} sessions × {len(feature_names)} 特征")

    # 真实模式标签（用于对齐度评估）
    true_labels = []
    for s in sessions:
        parts = s.session_id.split("_")
        if parts[1] == "early":
            true_labels.append(0)
        elif parts[1] == "afternoon":
            true_labels.append(1)
        elif parts[1] == "evening":
            true_labels.append(2)
        else:  # flow
            true_labels.append(3)
    true_labels = np.array(true_labels)

    # 2. 标准化
    X_scaled = StandardScaler().fit_transform(X)

    # 3. 对每个 k 跑 KMeans，记录 silhouette + 与真实模式的对齐度
    print("\n--- KMeans 评估各 k ---")
    k_results = {}
    for k in range(k_range[0], k_range[1] + 1):
        model = KMeans(n_clusters=k, n_init=10, random_state=seed)
        labels = model.fit_predict(X_scaled)
        sc = silhouette_score(X_scaled, labels)

        # 与真实模式对齐度（最佳 cluster→mode 映射）
        from collections import Counter
        c2m = {}
        for c in range(k):
            members = true_labels[labels == c]
            if len(members) > 0:
                c2m[c] = Counter(members).most_common(1)[0][0]
        aligned = sum(1 for i, c in enumerate(labels) if c2m.get(c) == true_labels[i])
        align_pct = aligned / len(sessions) * 100
        k_results[k] = {"silhouette": sc, "alignment_pct": align_pct, "labels": labels}
        print(f"  k={k}: silhouette = {sc:.4f}, alignment = {align_pct:.1f}%")

    # 4. 选择评估 k：
    #    优先 target_k（4），若 silhouette 过低且其他 k 显著更好则降级
    #    但仍以"4 模式可被恢复"为门禁，故主要看 target_k
    eval_k = target_k
    eval_data = k_results[eval_k]
    best_k = max(k_results.keys(), key=lambda k: k_results[k]["alignment_pct"])
    best_alignment = k_results[best_k]["alignment_pct"]

    print(f"\n评估 k = {eval_k}: silhouette = {eval_data['silhouette']:.4f}, "
          f"alignment = {eval_data['alignment_pct']:.1f}%")
    print(f"对齐度最高 k = {best_k}: {best_alignment:.1f}%")

    # 5. PCA 降维可视化（用 target_k 的结果）
    pca = PCA(n_components=2)
    X_2d = pca.fit_transform(X_scaled)
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    for label, name in [(0, "Early Peak"), (1, "Afternoon Tired"),
                       (2, "Evening Distracted"), (3, "Flow")]:
        mask = true_labels == label
        axes[0].scatter(X_2d[mask, 0], X_2d[mask, 1], label=name, alpha=0.7)
    axes[0].set_title("True modes (synthetic)")
    axes[0].legend()

    eval_labels = eval_data["labels"]
    for c in range(eval_k):
        mask = eval_labels == c
        axes[1].scatter(X_2d[mask, 0], X_2d[mask, 1], label=f"cluster {c}", alpha=0.7)
    axes[1].set_title(f"KMeans k={eval_k} (silhouette {eval_data['silhouette']:.3f}, "
                       f"align {eval_data['alignment_pct']:.0f}%)")
    axes[1].legend()

    plt.tight_layout()
    png_path = save_png("s11_clustering", fig)
    plt.close(fig)
    print(f"可视化已保存: {png_path}")

    # 6. 门禁判定：target_k=4 必须 silhouette > threshold AND alignment > threshold
    silhouette_pass = eval_data["silhouette"] > silhouette_threshold
    alignment_pass = eval_data["alignment_pct"] > alignment_threshold
    overall_pass = silhouette_pass and alignment_pass

    print(f"\n=== 门禁 (k={eval_k}) ===")
    print(f"silhouette > {silhouette_threshold}: {'PASS' if silhouette_pass else 'FAIL'} "
          f"({eval_data['silhouette']:.4f})")
    print(f"对齐度 > {alignment_threshold}%: {'PASS' if alignment_pass else 'FAIL'} "
          f"({eval_data['alignment_pct']:.1f}%)")
    print(f"总体: {'PASS' if overall_pass else 'FAIL'}")

    # 7. 保存结果
    result = {
        "spike": "S11_clustering",
        "n_sessions": len(sessions),
        "k_range": list(k_range),
        "target_k": eval_k,
        "silhouette_scores_by_k": {str(k): float(v["silhouette"]) for k, v in k_results.items()},
        "alignment_pct_by_k": {str(k): float(v["alignment_pct"]) for k, v in k_results.items()},
        "best_k_by_alignment": int(best_k),
        "best_alignment_pct": float(best_alignment),
        "eval_k_silhouette": float(eval_data["silhouette"]),
        "eval_k_alignment_pct": float(eval_data["alignment_pct"]),
        "silhouette_threshold": silhouette_threshold,
        "alignment_threshold": alignment_threshold,
        "overall_pass": bool(overall_pass),
        "recommended_params": {
            "k_range": list(k_range),
            "target_k": eval_k,
            "silhouette_threshold": silhouette_threshold,
            "alignment_threshold": alignment_threshold,
            "min_sessions_for_clustering": 10,
            "random_state": seed,
        },
        "visualization": png_path,
    }
    json_path = save_result("s11_clustering", result)
    print(f"JSON 已保存: {json_path}")
    return result


if __name__ == "__main__":
    result = run_spike()
    exit(0 if result["overall_pass"] else 1)

"""spike/insights/s13_anomaly.py — S13 异常检测原型

输入：32 合成 session 作为基线 + 1 人造异常 session（眨眼率 ×3）
方法：IsolationForest + z-score 归因
输出：anomaly_score / 归因 top 3 / 是否命中人造特征
"""
import json
from copy import deepcopy
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from spike.insights._common import (
    SyntheticSession, gen_synthetic_sessions, sessions_to_matrix, save_result,
)


def run_spike(seed=42, contamination=0.1):
    print("=== S13 异常检测 spike ===")

    # 1. 32 个基线 session
    baseline_sessions = gen_synthetic_sessions(n_per_mode=8, seed=seed)
    X_hist, feature_names = sessions_to_matrix(baseline_sessions)
    print(f"基线：{len(baseline_sessions)} sessions × {len(feature_names)} 特征")

    # 2. 人造异常 session — 取 flow 模式但 blink ×3 + perclos ×5
    base = deepcopy(baseline_sessions[-1])  # 取一个 flow 模式
    base.session_id = "anomaly_today"
    base.blink_rate_baseline_ratio *= 3.0  # 异常：眨眼 3 倍
    base.avg_perclos *= 5.0                # 异常：PERCLOS 5 倍
    today_sessions = [base]
    X_today, _ = sessions_to_matrix(today_sessions)
    print(f"人造异常：blink_rate × 3, perclos × 5")

    # 3. 标准化 + 训练
    scaler = StandardScaler().fit(X_hist)
    X_hist_s = scaler.transform(X_hist)
    X_today_s = scaler.transform(X_today)

    iso = IsolationForest(contamination=contamination, n_estimators=100, random_state=seed)
    iso.fit(X_hist_s)

    # 4. 评估今日
    anomaly_score = float(iso.score_samples(X_today_s)[0])
    is_anomaly = int(iso.predict(X_today_s)[0]) == -1
    print(f"\n今日 anomaly_score = {anomaly_score:.4f}")
    print(f"判定 is_anomaly = {is_anomaly}")

    # 5. 归因：z-score
    hist_mean = X_hist.mean(axis=0)
    hist_std = X_hist.std(axis=0) + 1e-9
    z_scores = (X_today.flatten() - hist_mean) / hist_std
    top_idx = np.argsort(np.abs(z_scores))[::-1][:3]
    top_factors = [{
        "feature": feature_names[i],
        "today_value": float(X_today[0, i]),
        "baseline_mean": float(hist_mean[i]),
        "z_score": float(z_scores[i]),
    } for i in top_idx]

    print("\n归因 top 3:")
    for f in top_factors:
        print(f"  {f['feature']}: today={f['today_value']:.3f}, "
              f"baseline_mean={f['baseline_mean']:.3f}, z={f['z_score']:+.2f}")

    # 6. 门禁：异常应被识别 + top 3 中至少 1 个含 'blink' 或 'perclos'
    target_features = {"blink_rate_baseline_ratio", "avg_perclos"}
    attribution_hit = any(f["feature"] in target_features for f in top_factors)
    overall_pass = is_anomaly and attribution_hit

    print(f"\n=== 门禁 ===")
    print(f"is_anomaly = True: {'PASS' if is_anomaly else 'FAIL'}")
    print(f"归因命中 blink/perclos: {'PASS' if attribution_hit else 'FAIL'}")
    print(f"总体: {'PASS' if overall_pass else 'FAIL'}")

    result = {
        "spike": "S13_anomaly",
        "n_historical_sessions": len(baseline_sessions),
        "anomaly_features_injected": ["blink_rate_baseline_ratio × 3",
                                       "avg_perclos × 5"],
        "anomaly_score": anomaly_score,
        "is_anomaly": is_anomaly,
        "top_factors": top_factors,
        "attribution_hit": attribution_hit,
        "overall_pass": bool(overall_pass),
        "recommended_params": {
            "contamination": contamination,
            "n_estimators": 100,
            "z_threshold_for_attribution": 1.5,
            "min_baseline_sessions": 15,
        },
    }
    json_path = save_result("s13_anomaly", result)
    print(f"JSON 已保存: {json_path}")
    return result


if __name__ == "__main__":
    result = run_spike()
    exit(0 if result["overall_pass"] else 1)

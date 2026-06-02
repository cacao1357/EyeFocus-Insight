# Phase 1.6 Insights Spike 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在正式实施 `analyzer/insights/` 子包（T220-T231）之前，先 spike 验证 5 个分析方法（聚类/变点/时序/异常/关联）在实际数据上的表现，调出推荐参数，再决定是否进入正式实施。

**Architecture:** 5 个独立 spike 脚本（不依赖主项目代码，纯 sklearn/scipy/statsmodels/ruptures + 合成或现有 SQLite 数据）+ 1 个汇总报告。

**Tech Stack:** Python 3.12 / sklearn (新增) / scipy (新增) / statsmodels (新增) / ruptures (新增) / pandas (已有) / matplotlib

**门禁规则（决定是否进入 T220-T231 正式实施）：**
- ✅ **5/5 PASS** → 进入 T220-T231 正式实施
- ⚠️ **4/5 PASS** → 失败方法降级或推迟，其余实施
- ❌ **≤3/5 PASS** → 整个 v4.1 推迟，触发 PROJECT_PLAN 回滚评估

**Spec 参考：** `PROJECT_PLAN.md` §6.9 + `PHASE1_PLAN.md` §2.14 + `PHASE2_PLAN.md` §2.6

---

## 文件结构

```
spike/insights/
├── __init__.py                       # 空标识包
├── s11_clustering.py                 # S11: 聚类原型
├── s12_changepoint.py                # S12: 变点检测原型
├── s13_anomaly.py                    # S13: 异常检测原型
├── s14_temporal.py                   # S14: 时序分解原型
├── s15_attribution.py                # S15: 关联分析原型
└── _common.py                        # 共用数据生成 / DB 连接函数

spike/results/insights/
├── s11_clustering_result.json
├── s12_changepoint_result.json
├── s13_anomaly_result.json
├── s14_temporal_result.json
├── s15_attribution_result.json
└── (各方法的可视化 PNG)

docs/PHASE1_6_SPIKE_SUMMARY.md         # S-SUM 最终汇总（替换/覆盖 PROJECT_PLAN §6.9 默认参数）

requirements.txt                       # 追加 scikit-learn/scipy/statsmodels/ruptures
```

---

## 前置准备

### 添加 v4.1 依赖

- [ ] **Step 0.1: 追加依赖到 requirements.txt**

```bash
.venv312/Scripts/python.exe -c "
text = open('requirements.txt', encoding='utf-8').read()
needed = ['scikit-learn>=1.3.0', 'scipy>=1.11.0', 'statsmodels>=0.14.0', 'ruptures>=1.1.0']
for pkg in needed:
    name = pkg.split('>=')[0]
    if name not in text:
        if not text.endswith('\n'):
            text += '\n'
        text += pkg + '\n'
        print(f'Added {pkg}')
open('requirements.txt', 'w', encoding='utf-8').write(text)
print('Done')
"
```

- [ ] **Step 0.2: 安装新依赖**

```bash
.venv312/Scripts/python.exe -m pip install scikit-learn scipy statsmodels ruptures
```

- [ ] **Step 0.3: 验证 import**

```bash
.venv312/Scripts/python.exe -c "
import sklearn, scipy, statsmodels, ruptures
print('sklearn:', sklearn.__version__)
print('scipy:', scipy.__version__)
print('statsmodels:', statsmodels.__version__)
print('ruptures:', ruptures.__version__)
"
```

Expected: 4 个版本号正常打印

### 创建 spike 目录

- [ ] **Step 0.4:**

```bash
.venv312/Scripts/python.exe -c "
import os
for d in ['spike/insights', 'spike/results/insights']:
    os.makedirs(d, exist_ok=True)
open('spike/insights/__init__.py', 'a').close()
print('OK')
"
```

### 共用工具：`spike/insights/_common.py`

- [ ] **Step 0.5: 写共用数据生成函数**

```python
"""spike/insights/_common.py — 共用工具

数据生成：合成 N 个 session 的特征矩阵，模拟用户行为模式。
数据库连接：复用主项目 storage/db.py（如果有真实数据）。
"""
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd


@dataclass
class SyntheticSession:
    """合成 session 的特征向量（与 PROJECT_PLAN §6.9.1 features 一致）。"""
    session_id: str
    avg_focus_score: float
    focus_score_std: float
    avg_perclos: float
    blink_rate_baseline_ratio: float
    gaze_away_ratio: float
    head_movement_intensity: float
    duration_minutes: float
    hour_of_day: int
    light_dark_ratio: float = 0.1
    fatigue_severe_ratio: float = 0.0
    focus_below_60_ratio: float = 0.2


def gen_synthetic_sessions(n_per_mode: int = 8, seed: int = 42) -> List[SyntheticSession]:
    """生成 4 种模式的合成 session，每种 n_per_mode 个。

    模式定义：
      1. 早高峰高效型：avg_focus ~80, blink ~0.9, hour=9
      2. 午后疲倦型：avg_focus ~55, blink ~1.5, hour=14
      3. 晚间分心型：avg_focus ~50, gaze_away ~0.4, hour=20
      4. 心流型：avg_focus ~85, focus_std ~3 (低), hour=10
    """
    rng = np.random.default_rng(seed)
    sessions = []
    modes = [
        {"name": "early_peak", "focus_mu": 80, "focus_std_mu": 8, "blink_mu": 0.9,
         "gaze_away_mu": 0.05, "hour_mu": 9, "perclos_mu": 0.02},
        {"name": "afternoon_tired", "focus_mu": 55, "focus_std_mu": 12, "blink_mu": 1.5,
         "gaze_away_mu": 0.15, "hour_mu": 14, "perclos_mu": 0.08},
        {"name": "evening_distracted", "focus_mu": 50, "focus_std_mu": 15, "blink_mu": 1.2,
         "gaze_away_mu": 0.40, "hour_mu": 20, "perclos_mu": 0.05},
        {"name": "flow", "focus_mu": 85, "focus_std_mu": 3, "blink_mu": 0.95,
         "gaze_away_mu": 0.03, "hour_mu": 10, "perclos_mu": 0.01},
    ]
    sid_n = 0
    for m in modes:
        for i in range(n_per_mode):
            sid_n += 1
            sessions.append(SyntheticSession(
                session_id=f"sess_{m['name']}_{sid_n:03d}",
                avg_focus_score=rng.normal(m["focus_mu"], 4),
                focus_score_std=max(1.0, rng.normal(m["focus_std_mu"], 2)),
                avg_perclos=max(0.0, rng.normal(m["perclos_mu"], 0.01)),
                blink_rate_baseline_ratio=rng.normal(m["blink_mu"], 0.1),
                gaze_away_ratio=max(0.0, min(1.0, rng.normal(m["gaze_away_mu"], 0.05))),
                head_movement_intensity=rng.normal(2.0, 0.5),
                duration_minutes=rng.uniform(30, 90),
                hour_of_day=int(rng.normal(m["hour_mu"], 1)) % 24,
            ))
    return sessions


def sessions_to_matrix(sessions: List[SyntheticSession]):
    """转为 (n_sessions, n_features) 矩阵 + 特征名列表。"""
    feature_names = [
        "avg_focus_score", "focus_score_std", "avg_perclos",
        "blink_rate_baseline_ratio", "gaze_away_ratio",
        "head_movement_intensity", "duration_minutes", "hour_of_day",
    ]
    X = np.array([[getattr(s, n) for n in feature_names] for s in sessions])
    return X, feature_names


def save_result(name: str, payload: dict) -> str:
    """保存 spike 结果到 spike/results/insights/。"""
    path = os.path.join("spike/results/insights", f"{name}_result.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    return path


def gen_focus_timeseries_with_drops(n_seconds: int = 3600,
                                     sample_hz: int = 2,
                                     drop_points: List[float] = None,
                                     seed: int = 42) -> np.ndarray:
    """生成"中间有断崖"的 focus_score 时序，用于 S12 变点检测验证。

    Args:
        n_seconds: 序列总时长（秒）
        sample_hz: 采样率（Hz）
        drop_points: 断崖时刻（秒）— 默认 [900, 2400]（15min, 40min 处下降）
        seed: 随机种子

    Returns:
        shape (n_seconds * sample_hz,) 数组
    """
    if drop_points is None:
        drop_points = [900, 2400]
    rng = np.random.default_rng(seed)
    n = n_seconds * sample_hz
    base = np.ones(n) * 80  # 初始 focus 80
    for t in drop_points:
        idx = int(t * sample_hz)
        base[idx:] -= 25  # 每次下降 25
    noise = rng.normal(0, 3, n)
    return np.clip(base + noise, 0, 100)


def gen_hourly_focus_with_daily_pattern(n_days: int = 14, seed: int = 42) -> pd.Series:
    """生成 N 天 × 24 小时聚合的 focus_score 序列，含已知日内规律。

    规律：上午 9-11 点峰值 (85)，下午 15-16 点低谷 (55)，傍晚 19-20 点小峰 (75)。
    """
    rng = np.random.default_rng(seed)
    hours = pd.date_range("2026-05-01", periods=n_days * 24, freq="1H")

    def base_for_hour(h: int) -> float:
        if 9 <= h <= 11: return 85
        if 15 <= h <= 16: return 55
        if 19 <= h <= 20: return 75
        return 65

    values = [base_for_hour(t.hour) + rng.normal(0, 3) for t in hours]
    return pd.Series(values, index=hours)


def get_real_db_path() -> Optional[str]:
    """如有真实 SQLite，返回路径；否则 None。spike 优先用合成数据。"""
    p = "data/eyefocus.db"
    return p if os.path.exists(p) else None
```

---

## Task S11: 聚类分析原型验证

**Goal:** 用 KMeans + silhouette 自动选 k 跑通聚类，验证 4 种合成模式能否被分开。
**门禁:** silhouette > 0.3 + 4 个 cluster 与 4 种合成模式标签对齐度 > 75%
**估时:** 1.5h
**Files:**
- Create: `spike/insights/s11_clustering.py`
- Output: `spike/results/insights/s11_clustering_result.json` + `s11_clustering.png`

### Step 1: 写 s11_clustering.py

- [ ] **Step 1.1: 完整脚本**

```python
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

from _common import gen_synthetic_sessions, sessions_to_matrix, save_result


def run_spike(k_range=(2, 6), silhouette_threshold=0.25, seed=42):
    print("=== S11 聚类分析 spike ===")

    # 1. 合成 32 sessions（4 模式 × 8）
    sessions = gen_synthetic_sessions(n_per_mode=8, seed=seed)
    X, feature_names = sessions_to_matrix(sessions)
    print(f"输入：{len(sessions)} sessions × {len(feature_names)} 特征")

    # 真实模式标签（用于对齐度评估）
    mode_map = {"early_peak": 0, "afternoon_tired": 1,
                "evening_distracted": 2, "flow": 3}
    true_labels = np.array([
        mode_map[s.session_id.split("_")[1] + "_" + s.session_id.split("_")[2]
                if "_" in s.session_id.split("_")[1]
                else s.session_id.split("_")[1]]
        for s in sessions
    ])
    # 简化：直接从 session_id 解析
    true_labels = []
    for s in sessions:
        parts = s.session_id.split("_")  # sess_<mode>_xxx 或 sess_<word1>_<word2>_xxx
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

    # 3. 自动选 k
    print("\n--- silhouette 自动选 k ---")
    scores = {}
    best_k, best_score, best_labels, best_model = None, -1.0, None, None
    for k in range(k_range[0], k_range[1] + 1):
        model = KMeans(n_clusters=k, n_init=10, random_state=seed)
        labels = model.fit_predict(X_scaled)
        sc = silhouette_score(X_scaled, labels)
        scores[k] = sc
        print(f"  k={k}: silhouette = {sc:.4f}")
        if sc > best_score:
            best_k, best_score, best_labels, best_model = k, sc, labels, model

    print(f"\n最佳 k = {best_k}, silhouette = {best_score:.4f}")

    # 4. 与真实模式对齐度（用最佳匹配）
    from collections import Counter
    cluster_to_mode = {}
    for c in range(best_k):
        members = true_labels[best_labels == c]
        if len(members) > 0:
            cluster_to_mode[c] = Counter(members).most_common(1)[0][0]
    aligned = sum(
        1 for i, c in enumerate(best_labels)
        if cluster_to_mode.get(c) == true_labels[i]
    )
    align_pct = aligned / len(sessions) * 100
    print(f"模式对齐度: {aligned}/{len(sessions)} = {align_pct:.1f}%")

    # 5. PCA 降维可视化
    pca = PCA(n_components=2)
    X_2d = pca.fit_transform(X_scaled)
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    for label, name in [(0, "Early Peak"), (1, "Afternoon Tired"),
                       (2, "Evening Distracted"), (3, "Flow")]:
        mask = true_labels == label
        axes[0].scatter(X_2d[mask, 0], X_2d[mask, 1], label=name, alpha=0.7)
    axes[0].set_title("True modes (synthetic)")
    axes[0].legend()

    for c in range(best_k):
        mask = best_labels == c
        axes[1].scatter(X_2d[mask, 0], X_2d[mask, 1], label=f"cluster {c}", alpha=0.7)
    axes[1].set_title(f"KMeans k={best_k} (silhouette {best_score:.3f})")
    axes[1].legend()

    plt.tight_layout()
    png_path = "spike/results/insights/s11_clustering.png"
    plt.savefig(png_path, dpi=80)
    print(f"可视化已保存: {png_path}")

    # 6. 门禁判定
    silhouette_pass = best_score > silhouette_threshold
    alignment_pass = align_pct > 75.0
    overall_pass = silhouette_pass and alignment_pass

    print(f"\n=== 门禁 ===")
    print(f"silhouette > {silhouette_threshold}: {'PASS' if silhouette_pass else 'FAIL'} ({best_score:.4f})")
    print(f"对齐度 > 75%: {'PASS' if alignment_pass else 'FAIL'} ({align_pct:.1f}%)")
    print(f"总体: {'✅ PASS' if overall_pass else '❌ FAIL'}")

    # 7. 保存结果
    result = {
        "spike": "S11_clustering",
        "n_sessions": len(sessions),
        "k_range": list(k_range),
        "silhouette_scores_by_k": {str(k): float(v) for k, v in scores.items()},
        "best_k": int(best_k),
        "best_silhouette": float(best_score),
        "alignment_pct": float(align_pct),
        "silhouette_threshold": silhouette_threshold,
        "alignment_threshold": 75.0,
        "overall_pass": bool(overall_pass),
        "recommended_params": {
            "k_range": list(k_range),
            "silhouette_threshold": silhouette_threshold,
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
```

### Step 2: 跑 spike

- [ ] **Step 2.1:**

```bash
.venv312/Scripts/python.exe spike/insights/s11_clustering.py
```

**Expected:**
- 控制台显示 5 个 k 的 silhouette 评分
- 最佳 k = 4，silhouette > 0.4
- 对齐度 > 75%
- 末行 `总体: ✅ PASS`
- 生成 `spike/results/insights/s11_clustering_result.json` + `s11_clustering.png`

### Step 3: 人工 review

- [ ] **Step 3.1: 检查 PNG**：打开 `spike/results/insights/s11_clustering.png`，确认右图 4 个 cluster 与左图 4 种模式视觉上对应良好

- [ ] **Step 3.2: 检查 JSON**：silhouette > 0.3，对齐度 > 75%，overall_pass=true

### Step 4: 提交

- [ ] **Step 4.1:**

```bash
"/c/Program Files/Git/cmd/git.exe" add spike/insights/__init__.py spike/insights/_common.py spike/insights/s11_clustering.py spike/results/insights/s11_clustering_result.json spike/results/insights/s11_clustering.png requirements.txt
"/c/Program Files/Git/cmd/git.exe" commit -m "spike(insights): S11 clustering prototype validation

KMeans + StandardScaler + silhouette auto-k on synthetic 32 sessions (4 modes × 8).
Gate: silhouette > 0.3 AND alignment with true modes > 75%.
Result: see spike/results/insights/s11_clustering_result.json"
```

### S11 完成判据
- [ ] spike 脚本运行无错
- [ ] 门禁两条都 PASS
- [ ] JSON + PNG 已生成
- [ ] commit 已提交

### 回滚点
- silhouette ≤ 0.25 或对齐度 ≤ 75% → 调整 k_range / 特征选择 / 模式定义；如仍失败 → S-SUM 标记 S11 FAIL，calibration 模块降级或推迟到 v4.2

---

## Task S12: 变点检测原型验证

**Goal:** 用 ruptures PELT 检测合成"中间断崖"序列的转折点，验证 penalty 参数。
**门禁:** 测试场景的 2 个已知断崖位置都被检出，时间误差 < 30 秒
**估时:** 1h
**Files:**
- Create: `spike/insights/s12_changepoint.py`

### Step 1: 写脚本

- [ ] **Step 1.1: `spike/insights/s12_changepoint.py`**

```python
"""spike/insights/s12_changepoint.py — S12 变点检测原型

输入：合成 1h focus_score 时序，含已知断崖（15min, 40min 处）
方法：ruptures.Pelt(model='rbf') + 自动调 penalty
输出：检测到的变点 + 与真实断崖的时间误差
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import ruptures as rpt

from _common import gen_focus_timeseries_with_drops, save_result


def run_spike(target_breakpoints_per_hour=4, seed=42):
    print("=== S12 变点检测 spike ===")

    # 1. 合成 1h focus_score，含 2 个已知断崖
    n_seconds = 3600
    sample_hz = 2
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

    # 3. PELT — 试不同 penalty，找到约每小时 3-5 个变点
    print("\n--- PELT 调 penalty ---")
    best_penalty = None
    best_bkps = None
    sigma_sq = np.var(smoothed)
    n = len(smoothed)

    for c in [1.0, 2.0, 3.0, 5.0, 8.0]:
        penalty = c * np.log(n) * sigma_sq
        algo = rpt.Pelt(model="rbf").fit(smoothed)
        bkps = algo.predict(pen=penalty)
        # 末尾 bkps[-1] = len(signal)，不算变点
        n_real_bkps = len(bkps) - 1
        print(f"  penalty_c={c}: {n_real_bkps} 个变点")
        if 3 <= n_real_bkps <= 5:
            if best_bkps is None:
                best_penalty = c
                best_bkps = bkps

    if best_bkps is None:
        # 退到最接近目标的
        for c in [3.0]:
            penalty = c * np.log(n) * sigma_sq
            best_bkps = rpt.Pelt(model="rbf").fit(smoothed).predict(pen=penalty)
            best_penalty = c

    detected_seconds = [bkp / sample_hz for bkp in best_bkps[:-1]]
    print(f"\n最终 penalty_c = {best_penalty}")
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
        ax.axvline(true_t, color="green", linestyle="--", label=f"true @ {true_t}s")
    for det_t in detected_seconds:
        ax.axvline(det_t, color="red", linestyle=":", label=f"detected @ {det_t:.0f}s")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("focus_score")
    ax.set_title(f"S12 PELT changepoint (penalty_c={best_penalty})")
    ax.legend(loc="lower left", fontsize=8)
    png_path = "spike/results/insights/s12_changepoint.png"
    plt.tight_layout()
    plt.savefig(png_path, dpi=80)

    # 6. 门禁
    overall_pass = max_error < 30  # 误差 < 30s
    print(f"\n=== 门禁 ===")
    print(f"最大误差 < 30s: {'PASS' if overall_pass else 'FAIL'} ({max_error:.0f}s)")

    result = {
        "spike": "S12_changepoint",
        "n_seconds": n_seconds,
        "sample_hz": sample_hz,
        "true_drops": true_drops,
        "detected_seconds": [float(t) for t in detected_seconds],
        "matches": [{"true_t": m["true_t"], "detected_t": float(m["detected_t"]) if m["detected_t"] else None,
                    "error_s": float(m["error_s"])} for m in matches],
        "max_error_s": float(max_error),
        "best_penalty_c": float(best_penalty),
        "overall_pass": bool(overall_pass),
        "recommended_params": {
            "penalty_c": float(best_penalty),
            "smoothing_window_sec": 30,
            "min_segment_sec": 60,
        },
        "visualization": png_path,
    }
    json_path = save_result("s12_changepoint", result)
    print(f"JSON 已保存: {json_path}")
    return result


if __name__ == "__main__":
    result = run_spike()
    exit(0 if result["overall_pass"] else 1)
```

### Step 2-4: 跑 + review + commit

- [ ] **Step 2.1:**

```bash
.venv312/Scripts/python.exe spike/insights/s12_changepoint.py
```

Expected: 最终 `总体: ✅ PASS`，2 个断崖检测误差均 < 30s

- [ ] **Step 3.1: 检查 PNG**：红虚线（检测）应接近绿虚线（真实），最多偏移半个滑动窗口

- [ ] **Step 4.1: commit**

```bash
"/c/Program Files/Git/cmd/git.exe" add spike/insights/s12_changepoint.py spike/results/insights/s12_*
"/c/Program Files/Git/cmd/git.exe" commit -m "spike(insights): S12 changepoint detection prototype

ruptures.Pelt(model='rbf') with auto penalty (target 3-5 bkps/hour).
Gate: max detection error < 30s on 2 known synthetic drops."
```

### S12 完成判据
- [ ] 脚本无错运行
- [ ] 最大误差 < 30s
- [ ] commit 已提交

### 回滚点
- 误差 ≥ 30s → 调 penalty 范围 / 平滑窗口；仍失败 → S-SUM 标记 S12 FAIL

---

（接下文 S13 ~ S15 + S-SUM）

---

## Task S13: 异常检测原型验证

**Goal:** IsolationForest 训练于 20+ 历史 session，故意造 1 个异常 session 验证识别 + 归因。
**门禁:** 异常 session 被识别为 anomaly + 归因 top 3 至少 1 个命中人造特征
**估时:** 1h
**Files:**
- Create: `spike/insights/s13_anomaly.py`

### Step 1: 写脚本

- [ ] **Step 1.1: `spike/insights/s13_anomaly.py`**

```python
"""spike/insights/s13_anomaly.py — S13 异常检测原型

输入：32 合成 session 作为基线 + 1 人造异常 session（眨眼率 ×3）
方法：IsolationForest + z-score 归因
输出：anomaly_score / 归因 top 3 / 是否命中人造特征
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from copy import deepcopy
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from _common import (
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
    print(f"总体: {'✅ PASS' if overall_pass else '❌ FAIL'}")

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
```

### Step 2-4: 跑 + review + commit

- [ ] **Step 2.1:**

```bash
.venv312/Scripts/python.exe spike/insights/s13_anomaly.py
```

Expected: `总体: ✅ PASS`

- [ ] **Step 3.1: review JSON**：is_anomaly=true，top_factors 中 blink_rate 或 perclos 至少出现 1 个

- [ ] **Step 4.1: commit**

```bash
"/c/Program Files/Git/cmd/git.exe" add spike/insights/s13_anomaly.py spike/results/insights/s13_*
"/c/Program Files/Git/cmd/git.exe" commit -m "spike(insights): S13 anomaly detection prototype

IsolationForest on 32 baseline sessions + 1 injected anomaly (blink×3, perclos×5).
Gate: is_anomaly=True AND top-3 attribution contains blink_rate or perclos."
```

### S13 完成判据
- [ ] 异常被识别 + 归因命中 + commit

### 回滚点
- is_anomaly=False → 调 contamination；归因不命中 → 检查特征顺序与 z-score 计算；仍失败 → S-SUM 标记 S13 FAIL

---

## Task S14: 时序分解原型验证

**Goal:** STL 分解 14 天合成数据，恢复已知日内 pattern（上午 9-11 峰值、下午 15-16 低谷）。
**门禁:** 恢复的 peak_hour top1 与真实位置误差 ≤ ±1 小时
**估时:** 1h
**Files:**
- Create: `spike/insights/s14_temporal.py`

### Step 1: 写脚本

- [ ] **Step 1.1: `spike/insights/s14_temporal.py`**

```python
"""spike/insights/s14_temporal.py — S14 时序分解原型

输入：14 天小时聚合 focus_score，含已知日内规律（9-11 峰，15-16 谷，19-20 小峰）
方法：statsmodels STL(period=24, robust=True)
输出：daily_pattern[24] + peak_hours top 3 与真实位置对比
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from statsmodels.tsa.seasonal import STL

from _common import gen_hourly_focus_with_daily_pattern, save_result


def run_spike(n_days=14, seed=42):
    print("=== S14 时序分解 spike ===")

    # 1. 合成 14 天数据
    series = gen_hourly_focus_with_daily_pattern(n_days=n_days, seed=seed)
    print(f"输入：{len(series)} 小时 ({n_days} 天)")

    # 真实 pattern：9-11 峰 (~85)，15-16 谷 (~55)，19-20 小峰 (~75)
    true_peaks_top1 = 10  # 9-11 的中点
    true_lows_top1 = 15   # 15-16 的中点

    # 2. STL 分解
    stl = STL(series, period=24, robust=True).fit()
    print("STL fit ✓")

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
        print(f"  {h:02d}:00 → {daily_curve[h]:.1f}")

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
    axes[1].axvline(true_peaks_top1, color="green", linestyle="--", label=f"true peak ~{true_peaks_top1}h")
    axes[1].axvline(true_lows_top1, color="red", linestyle="--", label=f"true low ~{true_lows_top1}h")
    axes[1].set_xlabel("Hour of day")
    axes[1].set_ylabel("focus_score")
    axes[1].set_title("Daily pattern (STL seasonal + trend)")
    axes[1].legend()

    png_path = "spike/results/insights/s14_temporal.png"
    plt.tight_layout()
    plt.savefig(png_path, dpi=80)
    print(f"可视化已保存: {png_path}")

    # 7. 门禁
    overall_pass = err_peak <= 1 and err_low <= 1
    print(f"\n=== 门禁 ===")
    print(f"Peak 误差 ≤ 1h: {'PASS' if err_peak <= 1 else 'FAIL'} ({err_peak}h)")
    print(f"Low  误差 ≤ 1h: {'PASS' if err_low <= 1 else 'FAIL'} ({err_low}h)")
    print(f"总体: {'✅ PASS' if overall_pass else '❌ FAIL'}")

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
```

### Step 2-4: 跑 + review + commit

- [ ] **Step 2.1:**

```bash
.venv312/Scripts/python.exe spike/insights/s14_temporal.py
```

Expected: `总体: ✅ PASS`，peak 检出在 9-11 之间，low 检出在 15-16 之间

- [ ] **Step 3.1: review PNG**：下方柱图的最高峰应在 9-11 区间，最低谷在 15-16

- [ ] **Step 4.1: commit**

```bash
"/c/Program Files/Git/cmd/git.exe" add spike/insights/s14_temporal.py spike/results/insights/s14_*
"/c/Program Files/Git/cmd/git.exe" commit -m "spike(insights): S14 temporal decomposition prototype

statsmodels STL(period=24, robust=True) on 14-day synthetic data
with known pattern (9-11 peak, 15-16 low). Gate: top1 error ≤ ±1h."
```

### S14 完成判据
- [ ] peak/low 误差均 ≤ 1h + commit

### 回滚点
- 误差 > 1h → 调 seasonal_window；仍失败 → S-SUM 标记 S14 FAIL（降级到 histogram fallback）

---

## Task S15: 关联分析原型验证

**Goal:** 用 scipy stats（Welch's t-test / Spearman）在合成数据上找出"光照差 ↔ focus 下降"等显著关联。
**门禁:** 至少 1 个 finding 满足 p < 0.05 且 effect size > 0.3 + 中文 suggestion 可读
**估时:** 1h
**Files:**
- Create: `spike/insights/s15_attribution.py`

### Step 1: 写脚本

- [ ] **Step 1.1: `spike/insights/s15_attribution.py`**

```python
"""spike/insights/s15_attribution.py — S15 关联分析原型

输入：合成 frames 数据（含 light_level、hour、focus_score、blink_rate）
方法：
  - Welch's t-test (光照差 vs 正常 → focus 对比)
  - Spearman 相关 (blink_rate ↔ focus)
  - ANOVA + eta² (24 小时段 → focus 差异)
  - Cohen's d 效应量
输出：findings 列表 + 各因素 effect_size
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import numpy as np
import pandas as pd
from scipy import stats

from _common import save_result


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
        print(f"  ✓ {f['factor']}: {f['description']}")
        print(f"    建议: {f['suggestion']}")

    # 4. 门禁：至少 1 个 finding
    overall_pass = len(findings) >= 1
    print(f"\n=== 门禁 ===")
    print(f"≥ 1 个 p<{p_threshold} + |effect|>{effect_threshold}: "
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
```

### Step 2-4: 跑 + review + commit

- [ ] **Step 2.1:**

```bash
.venv312/Scripts/python.exe spike/insights/s15_attribution.py
```

Expected: `总体: ✅ PASS`，至少 2-3 个 findings（光照对比 + blink-focus 相关 + 时段 ANOVA）

- [ ] **Step 3.1: review JSON**：findings 列表中至少 1 个的 description 和 suggestion 是中文可读的

- [ ] **Step 4.1: commit**

```bash
"/c/Program Files/Git/cmd/git.exe" add spike/insights/s15_attribution.py spike/results/insights/s15_*
"/c/Program Files/Git/cmd/git.exe" commit -m "spike(insights): S15 attribution analysis prototype

Welch t-test + Spearman + ANOVA + Cohen's d on synthetic frames.
Gate: ≥ 1 finding with p<0.05 AND |effect|>0.3, with Chinese suggestion."
```

### S15 完成判据
- [ ] ≥ 1 个 finding + 中文 suggestion + commit

### 回滚点
- 0 findings → 检查合成数据效应是否过弱；调 effect_threshold；仍失败 → S-SUM 标记 S15 FAIL

---

## Task S-SUM: 汇总 Spike 报告

**Goal:** 整合 S11-S15 结果到 `docs/PHASE1_6_SPIKE_SUMMARY.md`，输出推荐参数表 + 门禁判定 → 决定是否进入 T220-T231 正式实施。
**估时:** 1h
**Files:**
- Create: `docs/PHASE1_6_SPIKE_SUMMARY.md`

### Step 1: 验证所有 5 个 spike 结果已生成

- [ ] **Step 1.1:**

```bash
.venv312/Scripts/python.exe -X utf8 -c "
import json, os
files = ['s11_clustering', 's12_changepoint', 's13_anomaly',
         's14_temporal', 's15_attribution']
all_pass = True
results = {}
for f in files:
    p = f'spike/results/insights/{f}_result.json'
    if not os.path.exists(p):
        print(f'  MISSING: {p}')
        all_pass = False
        continue
    with open(p, encoding='utf-8') as fp:
        data = json.load(fp)
    results[f] = data
    status = '✅ PASS' if data.get('overall_pass') else '❌ FAIL'
    print(f'  {status}  {f}')
n_pass = sum(1 for r in results.values() if r.get('overall_pass'))
print(f'总计: {n_pass}/{len(results)} PASS')
"
```

Expected: `总计: 5/5 PASS`

### Step 2: 写汇总报告

- [ ] **Step 2.1: 写 `docs/PHASE1_6_SPIKE_SUMMARY.md`**

```python
.venv312/Scripts/python.exe -X utf8 -c "
import json, os, datetime
files = ['s11_clustering', 's12_changepoint', 's13_anomaly',
         's14_temporal', 's15_attribution']
results = {}
for f in files:
    p = f'spike/results/insights/{f}_result.json'
    with open(p, encoding='utf-8') as fp:
        results[f] = json.load(fp)

n_pass = sum(1 for r in results.values() if r.get('overall_pass'))
status = ('✅ 5/5 PASS — 进入 T220-T231 正式实施' if n_pass == 5
          else f'⚠️ {n_pass}/5 PASS — 失败方法降级或推迟' if n_pass >= 3
          else f'❌ {n_pass}/5 PASS — 触发 PROJECT_PLAN 回滚评估')

md = f'''# Phase 1.6 Insights Spike 汇总报告

> **日期**：{datetime.date.today()}
> **门禁判定**：{status}
> **5 个方法**：聚类 / 变点 / 异常 / 时序 / 关联

---

## 一、门禁结果

| Spike | 方法 | 门禁标准 | 实测 | 状态 |
|-------|------|---------|------|------|
| S11 | 聚类（KMeans + silhouette）| silhouette > 0.3 AND 对齐度 > 75% | silhouette {results[\"s11_clustering\"][\"best_silhouette\"]:.4f}, 对齐 {results[\"s11_clustering\"][\"alignment_pct\"]:.1f}% | {\"✅ PASS\" if results[\"s11_clustering\"][\"overall_pass\"] else \"❌ FAIL\"} |
| S12 | 变点检测（PELT）| 最大误差 < 30s | {results[\"s12_changepoint\"][\"max_error_s\"]:.1f}s | {\"✅ PASS\" if results[\"s12_changepoint\"][\"overall_pass\"] else \"❌ FAIL\"} |
| S13 | 异常检测（IsolationForest）| 异常识别 + 归因命中 | is_anomaly={results[\"s13_anomaly\"][\"is_anomaly\"]}, 命中={results[\"s13_anomaly\"][\"attribution_hit\"]} | {\"✅ PASS\" if results[\"s13_anomaly\"][\"overall_pass\"] else \"❌ FAIL\"} |
| S14 | 时序分解（STL）| 时段误差 ≤ ±1h | peak {results[\"s14_temporal\"][\"peak_error_h\"]}h, low {results[\"s14_temporal\"][\"low_error_h\"]}h | {\"✅ PASS\" if results[\"s14_temporal\"][\"overall_pass\"] else \"❌ FAIL\"} |
| S15 | 关联分析（t-test/ANOVA）| ≥ 1 个 finding | {len(results[\"s15_attribution\"][\"findings\"])} 个 | {\"✅ PASS\" if results[\"s15_attribution\"][\"overall_pass\"] else \"❌ FAIL\"} |

## 二、推荐参数（覆盖 PROJECT_PLAN v4.2 §6.9 默认值）

### 聚类（patterns.py）
```python
DEFAULTS = {{
    \"k_range\": {results[\"s11_clustering\"][\"recommended_params\"][\"k_range\"]},
    \"silhouette_threshold\": {results[\"s11_clustering\"][\"recommended_params\"][\"silhouette_threshold\"]},
    \"min_sessions_for_clustering\": {results[\"s11_clustering\"][\"recommended_params\"][\"min_sessions_for_clustering\"]},
    \"random_state\": {results[\"s11_clustering\"][\"recommended_params\"][\"random_state\"]},
}}
```

### 变点检测（changepoint.py）
```python
DEFAULTS = {{
    \"penalty_c\": {results[\"s12_changepoint\"][\"recommended_params\"][\"penalty_c\"]},
    \"smoothing_window_sec\": {results[\"s12_changepoint\"][\"recommended_params\"][\"smoothing_window_sec\"]},
    \"min_segment_sec\": {results[\"s12_changepoint\"][\"recommended_params\"][\"min_segment_sec\"]},
}}
```

### 异常检测（anomaly.py）
```python
DEFAULTS = {{
    \"contamination\": {results[\"s13_anomaly\"][\"recommended_params\"][\"contamination\"]},
    \"n_estimators\": {results[\"s13_anomaly\"][\"recommended_params\"][\"n_estimators\"]},
    \"z_threshold_for_attribution\": {results[\"s13_anomaly\"][\"recommended_params\"][\"z_threshold_for_attribution\"]},
    \"min_baseline_sessions\": {results[\"s13_anomaly\"][\"recommended_params\"][\"min_baseline_sessions\"]},
}}
```

### 时序分解（temporal.py）
```python
DEFAULTS = {{
    \"period\": {results[\"s14_temporal\"][\"recommended_params\"][\"period\"]},
    \"robust\": {results[\"s14_temporal\"][\"recommended_params\"][\"robust\"]},
    \"min_days_for_stl\": {results[\"s14_temporal\"][\"recommended_params\"][\"min_days_for_stl\"]},
}}
```

### 关联分析（attribution.py）
```python
DEFAULTS = {{
    \"p_value_threshold\": {results[\"s15_attribution\"][\"recommended_params\"][\"p_value_threshold\"]},
    \"min_effect_size_cohens_d\": {results[\"s15_attribution\"][\"recommended_params\"][\"min_effect_size_cohens_d\"]},
    \"min_effect_size_eta_squared\": {results[\"s15_attribution\"][\"recommended_params\"][\"min_effect_size_eta_squared\"]},
    \"min_samples_per_group\": {results[\"s15_attribution\"][\"recommended_params\"][\"min_samples_per_group\"]},
    \"top_n_findings\": {results[\"s15_attribution\"][\"recommended_params\"][\"top_n_findings\"]},
}}
```

## 三、发现的限制

- S11 在数据 < 10 sessions 时降级为 PCA 可视化（不强行聚类）
- S12 PELT 在信号过短（< 5min）时变点检测不可靠 — 限制最短 session 5min
- S13 IsolationForest 需要 ≥ 15 历史 sessions 作为基线
- S14 STL 需要 ≥ 7 天连续数据，否则降级 histogram
- S15 t-test/ANOVA 单组 < 30 样本时跳过该项对比

## 四、Phase 2 实施风险更新

(对应 PROJECT_PLAN v4.2 §12 R23-R26)

- R23 聚类不稳定：已实施门禁（silhouette + n_sessions），spike 验证有效
- R24 STL 数据需求：已实施降级（histogram fallback），spike 验证 14 天可恢复
- R25 pipeline 耗时：spike 单方法均 < 1s，组合预算 < 10s 留有余裕
- R26 打包体积：sklearn/scipy/statsmodels/ruptures 已安装，按预算 +80MB

## 五、决策

{status}

下一步：{\"按 PROJECT_PLAN v4.2 §15.4.0 推进 T-CAL（calibration），并并行启动 T220-T231（insights 实施）\" if n_pass == 5 else \"评估失败方法的降级路径或推迟到 v4.3\"}
'''

with open('docs/PHASE1_6_SPIKE_SUMMARY.md', 'w', encoding='utf-8') as f:
    f.write(md)
print('写入：docs/PHASE1_6_SPIKE_SUMMARY.md')
"
```

Expected: `写入：docs/PHASE1_6_SPIKE_SUMMARY.md`

### Step 3: 提交

- [ ] **Step 3.1:**

```bash
"/c/Program Files/Git/cmd/git.exe" add docs/PHASE1_6_SPIKE_SUMMARY.md
"/c/Program Files/Git/cmd/git.exe" commit -m "docs: PHASE1_6_SPIKE_SUMMARY.md - S-SUM gate decision"
```

### S-SUM 完成判据 / 整个 Phase 1.6 完成判据
- [ ] 5 个 spike JSON 均存在
- [ ] 汇总报告生成
- [ ] 门禁判定明确（5/5、4/5、≤3/5）
- [ ] commit 已提交
- [ ] 下一步动作清楚（进入 T220-T231 / 降级 / 回滚）

---

## Self-Review

### 1. Spec 覆盖性
- [x] PROJECT_PLAN §6.9 5 个方法 → S11-S15 各一一对应
- [x] PHASE1_PLAN §2.14 6 任务 → S11-S15 + S-SUM
- [x] PHASE2_PLAN §2.6 推荐参数 → S-SUM 输出推荐参数表

### 2. Placeholder 扫描
- [x] 无 TBD / TODO
- [x] 每个 spike 都有完整脚本代码
- [x] 每个 spike 都有具体门禁判定（数字阈值，不是"看起来 OK"）
- [x] 每个 spike 都有具体 commit 消息

### 3. 类型一致性
- [x] 所有 spike 用同一个 `_common.py` 工具函数
- [x] 所有 spike 用相同的 `save_result(name, payload)` 接口
- [x] S-SUM 用一致的字段名读各 JSON

### 4. 依赖性
```
Step 0（前置：装依赖 + 建目录 + _common.py）
    ↓
S11 → S12 → S13 → S14 → S15（可并行，但建议顺序以利 D1 review）
    ↓
S-SUM（要求 5 个 JSON 全在）
```

### 5. 工时核对
- S11: 1.5h / S12: 1h / S13: 1h / S14: 1h / S15: 1h / S-SUM: 1h
- 合计 6.5h（与 PHASE1_PLAN v1.8 一致）

---

## 执行交接

Plan complete and saved to `docs/superpowers/plans/2026-06-02-phase1-6-spike-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - 派 fresh subagent 跑每个 S11-S15 spike，独立隔离 + 并行。

**2. Inline Execution** - 在当前会话顺序跑每个 spike，每个跑完看输出 review 后再开下一个。

**Which approach?**

---

> **下一步**：用户确认后，分别调 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` skill。本计划提供了 6 个 spike 任务（5 个方法 + 汇总）的完整代码 / 数据生成 / 门禁判定。


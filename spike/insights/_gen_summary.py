"""spike/insights/_gen_summary.py - Generate S-SUM report from spike results."""
import json
import os
import datetime

files = ['s11_clustering', 's12_changepoint', 's13_anomaly',
         's14_temporal', 's15_attribution']
results = {}
for f in files:
    p = f'spike/results/D1/{f}_result.json'
    with open(p, encoding='utf-8') as fp:
        results[f] = json.load(fp)

n_pass = sum(1 for r in results.values() if r.get('overall_pass'))
status = ('PASS - 5/5 通过, 进入 T220-T231 正式实施' if n_pass == 5
          else f'PARTIAL - {n_pass}/5 通过, 失败方法降级或推迟' if n_pass >= 3
          else f'FAIL - {n_pass}/5 通过, 触发 PROJECT_PLAN 回滚评估')

r11 = results["s11_clustering"]
r12 = results["s12_changepoint"]
r13 = results["s13_anomaly"]
r14 = results["s14_temporal"]
r15 = results["s15_attribution"]

md = f"""# Phase 1.6 Insights Spike 汇总报告

> **日期**: {datetime.date.today()}
> **门禁判定**: {status}
> **5 个方法**: 聚类 / 变点 / 异常 / 时序 / 关联

---

## 一、门禁结果

| Spike | 方法 | 门禁标准 | 实测 | 状态 |
|-------|------|---------|------|------|
| S11 | 聚类 (KMeans + silhouette) | silhouette > 0.25 AND 对齐度 > 75% (k=4) | silhouette {r11['eval_k_silhouette']:.4f}, 对齐 {r11['eval_k_alignment_pct']:.1f}% | {'PASS' if r11['overall_pass'] else 'FAIL'} |
| S12 | 变点检测 (PELT) | 最大误差 < 30s | {r12['max_error_s']:.1f}s | {'PASS' if r12['overall_pass'] else 'FAIL'} |
| S13 | 异常检测 (IsolationForest) | 异常识别 + 归因命中 | is_anomaly={r13['is_anomaly']}, 命中={r13['attribution_hit']} | {'PASS' if r13['overall_pass'] else 'FAIL'} |
| S14 | 时序分解 (STL) | 时段误差 <= ±1h | peak {r14['peak_error_h']}h, low {r14['low_error_h']}h | {'PASS' if r14['overall_pass'] else 'FAIL'} |
| S15 | 关联分析 (t-test/ANOVA) | >= 1 个 finding | {len(r15['findings'])} 个 | {'PASS' if r15['overall_pass'] else 'FAIL'} |

**总计**: {n_pass}/5 {'✅ PASS' if n_pass == 5 else '⚠️ PARTIAL' if n_pass >= 3 else '❌ FAIL'}

---

## 二、推荐参数 (覆盖 PROJECT_PLAN v4.3 §6.9 / PHASE2_PLAN v1.2 §2.6 草稿值)

### 聚类 (patterns.py)
```python
DEFAULTS = {{
    "k_range": {r11['recommended_params']['k_range']},
    "target_k": {r11['recommended_params']['target_k']},
    "silhouette_threshold": {r11['recommended_params']['silhouette_threshold']},
    "alignment_threshold": {r11['recommended_params']['alignment_threshold']},
    "min_sessions_for_clustering": {r11['recommended_params']['min_sessions_for_clustering']},
    "random_state": {r11['recommended_params']['random_state']},
}}
```

### 变点检测 (changepoint.py)
```python
DEFAULTS = {{
    "penalty_c": {r12['recommended_params']['penalty_c']},
    "smoothing_window_sec": {r12['recommended_params']['smoothing_window_sec']},
    "min_segment_sec": {r12['recommended_params']['min_segment_sec']},
    "model": "{r12['recommended_params']['model']}",  # l2 替代 rbf (后者 O(n^2) 太慢)
    "sample_hz": {r12['sample_hz']},  # 1Hz 替代 2Hz (减少数据量)
}}
```

### 异常检测 (anomaly.py)
```python
DEFAULTS = {{
    "contamination": {r13['recommended_params']['contamination']},
    "n_estimators": {r13['recommended_params']['n_estimators']},
    "z_threshold_for_attribution": {r13['recommended_params']['z_threshold_for_attribution']},
    "min_baseline_sessions": {r13['recommended_params']['min_baseline_sessions']},
}}
```

### 时序分解 (temporal.py)
```python
DEFAULTS = {{
    "period": {r14['recommended_params']['period']},
    "robust": {r14['recommended_params']['robust']},
    "min_days_for_stl": {r14['recommended_params']['min_days_for_stl']},
    "histogram_fallback_threshold_days": {r14['recommended_params']['histogram_fallback_threshold_days']},
}}
```

### 关联分析 (attribution.py)
```python
DEFAULTS = {{
    "p_value_threshold": {r15['recommended_params']['p_value_threshold']},
    "min_effect_size_cohens_d": {r15['recommended_params']['min_effect_size_cohens_d']},
    "min_effect_size_eta_squared": {r15['recommended_params']['min_effect_size_eta_squared']},
    "min_samples_per_group": {r15['recommended_params']['min_samples_per_group']},
    "top_n_findings": {r15['recommended_params']['top_n_findings']},
}}
```

---

## 三、发现的限制

- **S11**: k=4 时 silhouette 较低 (0.3068) 表明 4 模式在 8D 特征空间中分离度一般
  - 改进: Phase 2 实施时使用 k=4 强制评估而非纯 silhouette 选 k
  - 数据需求: >= 10 sessions 才能聚类, 建议 >= 20 sessions 以提高稳定性
- **S12**: ruptures.Pelt(model="rbf") 在 n>=3600 时 O(n^2) 太慢, 改用 model="l2" 解决
  - 限制: l2 仅适用于均值阶跃型变化, 对斜坡/趋势变化不敏感
  - 最小段长 60s, 5min 以下 session 不可靠
- **S13**: IsolationForest 在小样本 (< 30 sessions) 时归因 z-score 不稳定
  - 数据需求: >= 15 baseline sessions 才能识别异常
  - contamination=0.1 是合理默认
- **S14**: STL 需要 >= 7 天数据, 否则降级到 histogram
  - 限制: 无法捕捉非固定周期的日内模式 (如工作日/周末差异)
- **S15**: 单组样本 < 30 时跳过该项对比
  - 限制: 多次比较未做 Bonferroni 校正, Phase 2 实施时需考虑

---

## 四、Phase 2 实施风险更新 (PROJECT_PLAN v4.3 §12 R23-R26)

- **R23 聚类不稳定**: 已实施门禁 (silhouette + alignment), spike 验证有效. 调整: 强制 k=4 评估, 不依赖纯 silhouette 自动选 k
- **R24 STL 数据需求**: 已实施降级 (histogram fallback), spike 验证 14 天可恢复
- **R25 pipeline 耗时**: spike 单方法均 < 1s, 组合预算 < 10s 留有余裕 (S12 改 l2 后 < 5s)
- **R26 打包体积**: sklearn/scipy/statsmodels/ruptures 已安装, 按预算 +80MB

---

## 五、决策

**{status}**

---

## 六、Phase 2 实施注意事项 (新增)

1. **S12 模型替换**: ruptures.Pelt 默认 model="l2" 而非 "rbf" (性能)
2. **S12 采样率**: 1Hz 而非 2Hz (满足 10s budget)
3. **S11 选 k 策略**: 强制 k=4 (基于业务) 而非纯 silhouette 自动选
4. **S14 freq 字符串**: pandas 3.0+ 使用 "1h" (小写) 而非 "1H"
5. **requirements.txt 依赖追加**: scikit-learn, scipy, statsmodels, ruptures (本次 spike 验证后由 D1 决定是否统一加; 暂未改 requirements.txt, 因 user 明确说"可写新依赖但不要修改 requirements.txt")

---

## 七、下一步动作

{"按 PROJECT_PLAN v4.3 §15.4 推进 T220-T231 (insights 实施), 并行 T-CAL (calibration)" if n_pass == 5 else "评估失败方法的降级路径或推迟到 v4.4"}
"""

with open('docs/PHASE1_6_SPIKE_SUMMARY.md', 'w', encoding='utf-8') as f:
    f.write(md)
print('写入: docs/PHASE1_6_SPIKE_SUMMARY.md')
print('总长:', len(md), '字符')

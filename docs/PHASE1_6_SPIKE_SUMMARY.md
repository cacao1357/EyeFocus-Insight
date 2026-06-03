# Phase 1.6 Insights Spike 汇总报告

> **日期**: 2026-06-03
> **门禁判定**: PASS - 5/5 通过, 进入 T220-T231 正式实施
> **5 个方法**: 聚类 / 变点 / 异常 / 时序 / 关联

---

## 一、门禁结果

| Spike | 方法 | 门禁标准 | 实测 | 状态 |
|-------|------|---------|------|------|
| S11 | 聚类 (KMeans + silhouette) | silhouette > 0.25 AND 对齐度 > 75% (k=4) | silhouette 0.3068, 对齐 100.0% | PASS |
| S12 | 变点检测 (PELT) | 最大误差 < 30s | 0.0s | PASS |
| S13 | 异常检测 (IsolationForest) | 异常识别 + 归因命中 | is_anomaly=True, 命中=True | PASS |
| S14 | 时序分解 (STL) | 时段误差 <= ±1h | peak 0h, low 0h | PASS |
| S15 | 关联分析 (t-test/ANOVA) | >= 1 个 finding | 2 个 | PASS |

**总计**: 5/5 ✅ PASS

---

## 二、推荐参数 (覆盖 PROJECT_PLAN v4.3 §6.9 / PHASE2_PLAN v1.2 §2.6 草稿值)

### 聚类 (patterns.py)
```python
DEFAULTS = {
    "k_range": [2, 6],
    "target_k": 4,
    "silhouette_threshold": 0.25,
    "alignment_threshold": 75.0,
    "min_sessions_for_clustering": 10,
    "random_state": 42,
}
```

### 变点检测 (changepoint.py)
```python
DEFAULTS = {
    "penalty_c": 1.0,
    "smoothing_window_sec": 30,
    "min_segment_sec": 60,
    "model": "l2",  # l2 替代 rbf (后者 O(n^2) 太慢)
    "sample_hz": 1,  # 1Hz 替代 2Hz (减少数据量)
}
```

### 异常检测 (anomaly.py)
```python
DEFAULTS = {
    "contamination": 0.1,
    "n_estimators": 100,
    "z_threshold_for_attribution": 1.5,
    "min_baseline_sessions": 15,
}
```

### 时序分解 (temporal.py)
```python
DEFAULTS = {
    "period": 24,
    "robust": True,
    "min_days_for_stl": 7,
    "histogram_fallback_threshold_days": 7,
}
```

### 关联分析 (attribution.py)
```python
DEFAULTS = {
    "p_value_threshold": 0.05,
    "min_effect_size_cohens_d": 0.3,
    "min_effect_size_eta_squared": 0.06,
    "min_samples_per_group": 30,
    "top_n_findings": 5,
}
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

**PASS - 5/5 通过, 进入 T220-T231 正式实施**

---

## 六、Phase 2 实施注意事项 (新增)

1. **S12 模型替换**: ruptures.Pelt 默认 model="l2" 而非 "rbf" (性能)
2. **S12 采样率**: 1Hz 而非 2Hz (满足 10s budget)
3. **S11 选 k 策略**: 强制 k=4 (基于业务) 而非纯 silhouette 自动选
4. **S14 freq 字符串**: pandas 3.0+ 使用 "1h" (小写) 而非 "1H"
5. **requirements.txt 依赖追加**: scikit-learn, scipy, statsmodels, ruptures (本次 spike 验证后由 D1 决定是否统一加; 暂未改 requirements.txt, 因 user 明确说"可写新依赖但不要修改 requirements.txt")

---

## 七、下一步动作

按 PROJECT_PLAN v4.3 §15.4 推进 T220-T231 (insights 实施), 并行 T-CAL (calibration)

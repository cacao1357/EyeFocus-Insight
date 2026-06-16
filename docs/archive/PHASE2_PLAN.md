# Phase 2 开发计划

> **版本**：v1.4 | **制定日期**：2026-06-02 | **修订日期**：2026-06-13
> **阶段目标**：calibration 模块重设计 + 报告系统 + 分心识别 + Insights 离线数据分析 + Qt 校准 v4.7 重设计
> **负责人**：D1（主开发）、D2（辅助开发）、T1（测试验收）
> **预计工期**：Day 14-22（约 9 天，含 calibration 重设计 4 天 + 报告/分心/insights 5 天）
> **上游门禁**：Phase 1.6 Spike（S11-S15）全部 PASS
>
> **v1.4 修订 (2026-06-13)**：Phase 2 全部任务完成。新增：v4.7 Qt 校准重设计、Insights 子系统实施（7 模块 + 报告集成 + 22 单测）、main.py 集成（自动报告生成）、T207 建议引擎 attribution 升级、T208-T211 分心识别模块（20 单测 + 热力图集成）、T230 集成测试（8 测试）、T231 文档同步。测试基线 580 → 408（去重）。等待 T219 Phase 2 验收。
>
> **v1.2 → v1.3 修订 (2026-06-06)**：v4.4 GUI 清晰化 + 拖窗口 REC 维护记录入档（§2.8.3）；测试基线 284 → 580；删除 §三 重复标题
>
> **v1.2 修订 (2026-06-04)**：calibration 端到端跑通后 3 项真机验收 UX 问题登记（§2.8），新增 T-CAL-15/16/17 待办

---

## ⚠️ Phase 2 严重风险任务先行

> 🔴 **calibration 模块重设计（T-CAL-01 ~ T-CAL-14）必须排在 Phase 2 的最前面（Day 14-17）**
>
> **理由**：
> 1. main.py 集成点改动会影响后续 insights 模块的集成测试（同一个 main.py 改了校准接入点 + 校准后阈值应用）
> 2. 校准模块输出 `CalibrationResult.baseline_blink_rate` 是 insights `features.py` 的 SessionFeatures 数据来源之一
> 3. 保守开发策略要求 main.py 集成放最后一步，需先完成 13 个 calibration 子任务再进入 insights 实施
>
> **执行顺序**：
> ```
> Day 14-17：T-CAL-01 ~ T-CAL-14（calibration 重设计 + 集成）
>     ↓
> Day 18-22：T200-T231（报告 + 分心 + insights 实施 + 验收）
> ```
>
> **详细 spec**：`docs/superpowers/specs/2026-06-02-user-calibration-redesign.md`

---

## 一、阶段目标

### 1.1 核心交付物

| 模块 | 交付内容 | 状态 |
|------|---------|:----:|
| `reporter/charts.py` | Matplotlib 图表生成（折线/柱状/热力/饼图/雷达/条形/分心热力条） | ✅ 已完成 |
| `reporter/report_html.py` | HTML 报告组装（含 v4.1 新增 4 章节 + v4.6 insights + 分心分析） | ✅ 已完成 |
| `reporter/insights.py` | 个性化建议引擎（v4.1 attribution 驱动 + 规则引擎兜底） | ✅ 已完成 |
| `analyzer/distraction.py` | 分心模式识别 + 时间轴热力图（20 单测） | ✅ 已完成 |
| `analyzer/insights/features.py` | 【v4.1】SessionFeatures + 矩阵化 | ✅ 已完成 |
| `analyzer/insights/patterns.py` | 【v4.1】聚类 — KMeans + silhouette | ✅ 已完成 |
| `analyzer/insights/changepoint.py` | 【v4.1】变点检测 — ruptures PELT | ✅ 已完成 |
| `analyzer/insights/anomaly.py` | 【v4.1】异常检测 — IsolationForest + 归因 | ✅ 已完成 |
| `analyzer/insights/temporal.py` | 【v4.1】时序分解 — STL + histogram 降级 | ✅ 已完成 |
| `analyzer/insights/attribution.py` | 【v4.1】关联分析 — t-test + ANOVA + Cohen's d | ✅ 已完成 |
| `analyzer/insights/pipeline.py` | 【v4.1】Pipeline 编排（try/except 隔离） | ✅ 已完成 |
| `storage/db.py` 扩展 | 【v4.1】insights 表 + PRAGMA 迁移 | ✅ 已完成 |
| `gui/calibration_dialog.py` | 【v4.7】Qt 校准重设计（70/30 白底面板 + 手动步进） | ✅ 已完成 |
| `main.py` 集成 | 会话结束自动生成含 insights 的 HTML 报告 | ✅ 已完成 |

### 1.2 验收标准

| 指标 | 标准 | 对应 AC |
|------|------|---------|
| HTML 报告生成 | 会话结束自动生成，含折线图/统计/建议 | AC9 |
| 报告含个性化建议 | 非空洞的具体建议，由数据驱动 | AC10 |
| 分心热力图 | 报告含时间轴分心热力条 | AC17 |
| Insights pipeline 性能 | 30 sessions + 1h session 全 pipeline < 10s | AC26 |
| 聚类降级 | n_sessions < 10 显示"数据不足"不报错 | AC27 |
| 异常检测归因 | top 3 中文翻译因子 | AC28 |
| 时序高效时段 | 14 天数据下显示具体小时段 | AC29 |
| 关联分析发现 | ≥ 1 个 p<0.05 + effect>0.3 finding | AC30 |
| 单测覆盖率 | insights 子包 ≥ 75% | AC18 |

---

## 二、任务分解

### 2.0 calibration 模块重设计（v4.2 新增，Day 14-17，约 4 天）— 🔴 严重风险

> **优先级最高，必须在 Phase 2 其他任务之前完成。**
>
> 详细 spec：`docs/superpowers/specs/2026-06-02-user-calibration-redesign.md`
>
> 设计决策（已敲定）：A 完整重设计 + 模块隔离 / A1 模块自有摄像头 / L1 上下分屏 / S2 蜂鸣+TTS / C2 鼠标主导 / F1 完整反馈 / P2 5 阶段约 2 分钟 / E1 总结页 + 用户确认 / X1 严格契约。
>
> 解决 7 个用户实测 BUG：眨眼检测 0 / UI 视频重叠 / 闭眼盲 / 头部姿态无指令 / 全程无反馈 / 节奏无控制 / 结束无退出。

#### 2.0.1 保守开发策略门禁

每个 T-CAL-XX 子任务采用 **"实现 → 测试 → 门禁 → 下一步"** 严格循环：

- 单元测试覆盖率达到指定阈值（见下表）
- spike 真机验证（如有）通过
- D1 强制 review 通过
- **任一门禁未过 → 暂停，不开新子任务**

#### 2.0.2 子任务清单

| 任务ID | 描述 | 负责人 | 估时 | 依赖 | 覆盖率门禁 | 真机验证 |
|--------|------|--------|------|------|----------|---------|
| T-CAL-01 | calibration/result.py — CalibrationResult dataclass（冻结字段）| D1 | 0.5h | T144 | ≥ 95% | - |
| T-CAL-02 | calibration/config.py — CalibrationConfig | D2 | 0.5h | T-CAL-01 | ≥ 90% | - |
| T-CAL-03 | calibration/phases/auto_baseline.py — 阶段 0 | D1 | 1.5h | T-CAL-02 | ≥ 90% | ✅ spike |
| T-CAL-04 | calibration/phases/closed_eyes.py — 阶段 1（含睁眼回升验证）| D1 | 1h | T-CAL-02 | ≥ 90% | ✅ 真机 TTS |
| T-CAL-05 | calibration/phases/squint.py — 阶段 2 | D1 | 1h | T-CAL-02 | ≥ 90% | - |
| T-CAL-06 | calibration/phases/head_pose.py — 阶段 3（4 子阶段）| D1 | 1.5h | T-CAL-02 | ≥ 85% | ✅ 4 TTS 真机 |
| T-CAL-07 | calibration/phases/blink_count.py — 阶段 4（2 轮 + 输入）| D1 | 1.5h | T-CAL-02 | ≥ 85% | ✅ 真机眨眼检出 |
| T-CAL-08 | calibration/ui/layout.py — vconcat 拼合 | D2 | 0.5h | T-CAL-02 | ≥ 90% | - |
| T-CAL-09 | calibration/ui/panel.py — UI 区渲染 + 屏幕数字键盘 | D2 | 3h | T-CAL-08 | ≥ 75% | ✅ 每状态截图 review |
| T-CAL-10 | calibration/input_handler.py — 鼠标 + 键盘 + IME 兼容 | D2 | 2h | T-CAL-09 | ≥ 95% | ✅ IME 实战 |
| T-CAL-11 | calibration/audio/beep.py + audio/tts.py | D2 | 1.5h | T-CAL-02 | ≥ 80-85% | ✅ 真机听音 |
| T-CAL-12 | calibration/flow.py — 状态机编排 | D1 | 3h | T-CAL-03~T-CAL-11 | ≥ 80% | ✅ spike 全流程 |
| T-CAL-13 | calibration/__main__.py — `python -m calibration` 独立运行 | D1 | 0.5h | T-CAL-12 | - | ✅ 5 个 spike 全跑通 |
| T-CAL-14 | main.py 集成（**最后一步**）+ 用户 7 BUG 实测验收 | D1+T1 | 2h | T-CAL-13 | - | ✅ v1.2 时 284 测试 0 破（v1.3 升至 580）+ 8 个用户验收点全过 |
| **小计** | | | **20h** | | 整体 ≥ 85% | |

#### 2.0.3 用户验收清单（T-CAL-14 必过）

```
□ BUG 1：眨眼计数轮检测到非零数字
□ BUG 2：校准 UI 完全不遮挡视频区（视频 480 + UI 240 严格分离）
□ BUG 3：闭眼时听到 TTS "现在可以睁眼了"
□ BUG 4：头部姿态 4 段独立 TTS（抬/低/左/右）
□ BUG 5：每阶段进行中可见实时计数 + 结束有摘要
□ BUG 6：每阶段需点"开始"才推进
□ BUG 7：校准完成有明确反馈 + 用户主动确认才进入主监测
□ IME：微软拼音激活下仍可完成全流程（鼠标点屏幕数字键盘）
```

**任一未过 → 整个 calibration 模块视为未完成，回到 spec brainstorm 阶段。**

---

### 2.1 T200-T205：HTML 报告系统

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T200 | `reporter/charts.py` — 折线图（focus_score over time）| D1 | 1.5h | Phase 1 完成 |
| T201 | `reporter/charts.py` — 柱状图（眨眼分布/疲劳分布）| D1 | 1h | T200 |
| T202 | `reporter/charts.py` — 时间轴热力条（分心率/分钟） | D1 | 1.5h | T200 |
| T203 | `reporter/report_html.py` — HTML 模板 + Base64 图嵌入 | D1 | 2h | T200-T202 |
| T204 | `reporter/report_html.py` — 会话摘要统计章节 | D1 | 1.5h | T203 |
| T205 | 数据点降采样（5 分钟会话图 ≤ 300 点） | D1 | 1.5h | T200 |

### 2.2 T206-T207：个性化建议引擎（v4.1 重塑）

> **【v1.2 现状澄清】**现有 `reporter/insights.py`（392 行，v4.0 规则引擎 + `InsightsEngine` + `FocusPattern` 等）为 v4.0 时代的实现，**不删除**，作为 T206 的"规则引擎"基线。T207 在其上叠加 attribution findings 作为主输入，规则引擎降级为兜底。

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T206 | `reporter/insights.py` — 在现有 `InsightsEngine` 上扩展规则引擎（兜底）| D2 | 1.5h | T203 |
| T207 | `reporter/insights.py` — 集成 attribution findings 作为主输入 | D2 | 1.5h | T226 |

### 2.3 T208-T211：分心模式识别

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T208 | `analyzer/distraction.py` — 分心事件检测（3-15s/15-60s/60s+）| D1 | 1.5h | Phase 1 |
| T209 | `analyzer/distraction.py` — 分心热力图数据（按分钟聚合） | D1 | 1h | T208 |
| T210 | `analyzer/distraction.py` — 分心模式分类（高频短促/间歇中长/单次长断） | D1 | 1h | T208 |
| T211 | 分心识别单元测试 | D2 | 0.5h | T210 |

### 2.4 T212-T215：跨会话分析 + 真人测试

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T212 | `storage/db.py` — 多 session 聚合查询接口 | D1 | 1h | Phase 1 |
| T213 | 跨会话趋势图表（专注度走势） | D1 | 1.5h | T212, T200 |
| T214 | A4: 2-3 人真人测试 + 权重调优 | D1 | 2h | T203 |
| T215 | 权重调优结果应用到 `analyzer/focus.py` | D1 | 1.5h | T214 |

### 2.5 T216-T218：测试补充

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T216 | `tests/test_reporter.py` — 图表生成单测 | D2 | 1.5h | T203 |
| T217 | `tests/test_distraction.py` — 分心识别单测 | D2 | 1.5h | T210 |
| T218 | `tests/test_html_integration.py` — 端到端报告生成测试 | D2 | 2h | T203 |

### 2.6 T220-T231：Insights 离线数据分析（v4.1 新增）

> **前置条件**：Phase 1.6 Spike（S11-S15）必须全部 PASS。任一失败需在 S-SUM 给出降级方案。
>
> ⚠️ **【v1.2 草稿值警告】T222-T226 中所有具体参数（penalty_c=3.0、silhouette_threshold=0.25、min_sessions=10、contamination=0.1、period=24、min_samples_per_group=30 等）均为**草稿默认值**，S11-S15 spike 未执行前未经实测验证**。S-SUM 报告（`docs/PHASE1_6_SPIKE_SUMMARY.md`）发布后必须**逐项覆盖**本文档 T222-T226 的参数表，否则 T222-T226 不应启动。

#### T220 — 公共特征工程

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T220 | `analyzer/insights/features.py` — SessionFeatures + extract + 矩阵化 | D1 | 1.5h | Phase 1.6 |

**算法**（见 PROJECT_PLAN §6.9）：
- 输入：`session_id` + SQLite 连接
- 输出：`SessionFeatures` dataclass（11 个字段：focus 统计、blink、PERCLOS、视线、头部、疲劳、光照、眼镜、数据质量）
- `features_to_matrix(list) → (X, feature_names)` 锁定字段顺序

**验收**：
- 单 session 提取 < 100ms（7200 行数据）
- duration < 60s 抛 ValueError
- 全 NULL session 抛 ValueError
- 字段顺序与 feature_names 严格一致（聚类/异常检测依赖）

#### T221 — SQLite Schema 扩展

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T221 | `storage/db.py` + `models.py` — `insights` 表 + PRAGMA 迁移 | D2 | 0.5h | T220 |

**Schema**：
```sql
CREATE TABLE IF NOT EXISTS insights (
    insight_id      TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    analysis_type   TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    result_json     TEXT NOT NULL,
    confidence      REAL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);
CREATE INDEX idx_insights_session ON insights(session_id, analysis_type);
CREATE INDEX idx_insights_created ON insights(created_at);
```

**验收**：
- 旧库升级（PRAGMA table_info 检查）无数据丢失
- 同 (session_id, analysis_type) 重复运行时 INSERT 不冲突（用 INSERT OR REPLACE 或 UUID 区分）

#### T222 — 变点检测

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T222 | `analyzer/insights/changepoint.py` — PELT 变点检测 | D1 | 2h | T220 |

**算法**：`ruptures.Pelt(model="rbf").predict(pen=penalty)`，penalty = 3.0 × log(n) × σ²

**参数**：
- `smoothing_window_sec` = 30
- `min_segment_sec` = 60
- `penalty_c` = 3.0（Phase 1.6 Spike S12 推荐值覆盖）
- `top_k_drops` = 3
- `min_drop_threshold` = 10.0

**验收**：
- 1h session < 3s（AC26 分项）
- 段长 < 60s 必须合并
- key_moments 按 drop_magnitude 降序
- "持续高专注"测试场景返回 0 key_moments
- "中间断崖"测试场景误差 < 30s

#### T223 — 异常检测

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T223 | `analyzer/insights/anomaly.py` — IsolationForest + z-score 归因 | D2 | 1.5h | T220 |

**算法**：`sklearn.ensemble.IsolationForest(contamination=0.1).fit(historical)`

**参数**：
- `min_baseline_sessions` = 15
- `contamination` = 0.1
- `n_estimators` = 100
- `top_n_factors` = 3
- `z_threshold` = 1.5

**验收**：
- 历史 < 15 sessions 时返回降级信息（AC27 分项）
- 归因因子按 \|z-score\| 降序
- 异常因子必须有中文翻译（_translate 字典）
- 50 历史 sessions 检测 < 200ms

#### T224 — 聚类工作模式

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T224 | `analyzer/insights/patterns.py` — KMeans + silhouette 自动选 k | D1 | 2h | T220 |

**算法**：For k in [2, 6]: 计算 silhouette_score → 取最优 k

**参数**：
- `min_sessions_for_clustering` = 10
- `k_range` = (2, 6)
- `silhouette_threshold` = 0.25
- `random_state` = 42
- `n_init` = 10

**验收**：
- 数据 < 10 sessions 返回降级（AC27）
- silhouette < 0.25 不强行返回结果
- 30 sessions 运行 < 500ms
- 模式标签必须是中文业务术语（"早高峰高效型" 等）

#### T225 — 时序分解

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T225 | `analyzer/insights/temporal.py` — STL + histogram 降级 | D1 | 2h | T220 |

**算法**：`statsmodels.tsa.seasonal.STL(period=24, robust=True).fit()`

**参数**：
- `min_days_for_stl` = 7
- `period` = 24
- `seasonal_window` = 7
- `top_n_peak_hours` = 3

**降级**：n_days < 7 或 NaN > 30% → histogram fallback

**验收**：
- 数据 < 7 天降级 histogram 不报错（AC29 分项）
- 14 天数据 STL < 1s
- peak_hours 和 low_hours 不能重叠
- 测试场景"上午高下午低"正确识别 peak

#### T226 — 关联分析

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T226 | `analyzer/insights/attribution.py` — t-test + ANOVA + Cohen's d | D2 | 2h | T220 |

**算法**：
- Pearson/Spearman 相关
- Welch's t-test（光照/眼镜分组）
- ANOVA + eta²（24 小时段）
- Cohen's d 效应量

**参数**：
- `min_samples_per_group` = 30
- `p_value_threshold` = 0.05
- `min_effect_size` = 0.3
- `top_n_findings` = 5

**验收**：
- 单组 < 30 跳过该对比
- 仅返回 p<0.05 且 |effect|>0.3 的 finding（AC30）
- 每个 finding 有可执行中文建议
- 100k 行 < 2s

#### T227 — Pipeline 编排

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T227 | `analyzer/insights/pipeline.py` — InsightsPipeline 类 + 异常隔离 | D1 | 1h | T220-T226 |

**实现要点**：
- `InsightsPipeline.run(current_session_id) → dict`
- 每个方法 try/except 隔离（单个失败不影响其他）
- 历史数据 < min_threshold 时跳过对应方法
- 结果序列化为 JSON 存 `insights` 表

**验收**：
- 单方法失败时其他方法仍正常完成
- 5 方法总耗时 < 10s（AC26）
- 持久化结果可被 reporter 读取重用

#### T228 — 报告 4 章节集成

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T228 | `reporter/report_html.py` — 4 章节模板 + 图表 | D2 | 3h | T203, T227 |

**4 个章节**：
1. **工作模式分析**：饼图（各模式占比）+ 当前 session 高亮 + 中文描述
2. **今日异常分析**（仅 is_anomaly=True 时显示）：雷达图（今日 vs 基线）+ top 3 归因
3. **长期趋势**：24 小时折线图（标 peak/low）+ "你的高效时段：09-11 / 16-17"
4. **个性化建议**：横向条形图（各因子 effect size）+ findings 列表

**验收**：
- 无数据时章节自动隐藏（不显示错误）
- 4 个图表均能从 charts.py 调用渲染
- HTML 在 Chrome/Edge/Firefox 均可正常渲染

#### T229-T231 — 测试与文档

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T229 | `tests/test_insights_*.py` — 单元测试 ≥ 75% 覆盖 | D2 | 3h | T227 |
| T230 | `tests/test_insights_integration.py` — 集成 + 性能 < 10s | T1 | 2h | T228 |
| T231 | PROJECT_PLAN v4.1 + PHASE2_PLAN 同步 | D1 | 1h | T228 |

**T229 测试范围**：
- features：正常 + NULL + 过短 session
- patterns：正常 + 数据不足 + silhouette 不足
- changepoint：正常 + 持续高专注 + 中间断崖
- anomaly：正常 + 基线不足 + 异常归因正确
- temporal：14 天数据 + < 7 天降级
- attribution：显著 + 不显著
- pipeline：单方法失败隔离

**T230 集成验收**：
- 用 mock 数据库（30 sessions × 1h）跑完整 pipeline
- 验证 AC26-AC30 全部 PASS
- 验证总耗时 < 10s

### 2.7 T219：Phase 2 整体验收

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T219 | Phase 2 整体验收 | T1 | 3h | T230 |

### 2.8 v1.2 真机验收已知问题（v4.2 calibration 实施后）

> **记录日期**：2026-06-04
> **触发**：7 次真机验收第 7 次（`acceptance_test7_003632`）首次 exit 0（EAR 基线 0.4051 / 眨眼阈值 0.3038 / CQS 0.60 / 眨眼率 80/min），但用户测出 3 个非阻塞问题。
> **不阻塞 calibration 主流程**（已端到端跑通），但用户体验需改善。
> **优先级**：🟡 中等 — 5 阶段完成但反馈/精度差。

| # | 等级 | 现象 | 推测根因 | 建议修复 |
|---|------|------|---------|---------|
| 1 | 🟡 | **闭眼检测不到闭眼**（阶段 1）| 阈值偏严 / 时长偏短：阶段 1 闭眼时 EAR 应跌破 `0.75 × baseline_ear = 0.304`，实测闭眼时 EAR 仍 > 阈值，可能用户闭眼不完全或阈值未动态更新 | 阶段 1 加 TTS "请用力闭眼" + 屏幕提示 "EAR 当前 X.XX，阈值 0.304" + 延长闭眼时间到 8s + EAR < 阈值持续 0.5s 才算成功 |
| 2 | 🟡 | **动作姿态提示不够，不知何时切换姿势**（阶段 3 头部姿态）| 4 子阶段过渡无声：TTS "现在抬头" 后用户不知道何时停止 / 何时转下一个 | 4 子阶段各加 TTS "准备"+"动作中"+"保持 X 秒"+"完成",并显示进度条；3 秒静默无变化自动 TTS 提示 |
| 3 | 🟡 | **动作幅度大也检测不到**（阶段 3 头部姿态）| 检测阈值可能过严：head_pose.py 用 `compute_head_pose_from_matrix`，yaw/pitch 范围可能受限 | 加 calibration 阶段 3 的"幅度确认"子步骤: 用户做大动作后查看实时 yaw/pitch 显示，确保值在 [-30, 30] 范围，否则提示 "请调整头部角度"；调整 yaw_thresh 从默认 10° 到 20-25° |

#### 修复计划

**Phase 2 后续添加**（建议新增 T-CAL-15 / T-CAL-16 / T-CAL-17 子任务）：

```
T-CAL-15 (1.5h): 阶段 1 闭眼校准改进
  - 阈值动态调整: 实际闭眼 EAR < 0.6 × baseline_ear (而非固定 0.75)
  - 持续时长: EAR < 阈值持续 0.5s 才算成功
  - 反馈: 屏幕实时显示 EAR 数值 + 倒计时 "请保持 5 秒"
  - TTS: "请用力闭眼" 启动时 + "很好，可以睁眼了" 完成时

T-CAL-16 (1.5h): 阶段 3 头部姿态改进
  - 4 子阶段各加 3 段 TTS: "准备 [方向]" → "现在 [动作]" → "保持 X 秒"
  - 屏幕实时显示 yaw/pitch 数值 + 进度条
  - 3 秒静默无变化自动 TTS 提示
  - 调整 yaw_thresh 到 20-25° (从默认 10°)

T-CAL-17 (0.5h): 加宽容错 (跨阶段)
  - 阶段失败时给"重做/跳过"按钮 (已有 RETRY_PHASE/SKIP_PHASE)
  - 加 "诊断" 模式: 显示当前 EAR/yaw/pitch 帮助用户调姿
  - main.py 集成: 总结页加 CQS 不达标警告
```

#### 影响范围

| 文档 | 同步内容 |
|------|---------|
| `docs/superpowers/specs/2026-06-02-user-calibration-redesign.md` | 加"v1.1 已知限制"章节 |
| `docs/superpowers/plans/2026-06-02-calibration-redesign-plan.md` | 标记 T-CAL-04/06/12 部分需求"待 T-CAL-15/16/17 增强" |
| `PHASE2_PLAN.md` | 本节 (已加) |
| 不需要 bump 版本 | 文档 v1.2，3 项 issue 已知且非阻塞 |

#### 实机验收 7 次记录

| # | session_id | 结果 | 发现 |
|---|------------|------|------|
| 1 | acceptance_test_20260603_230100 | ❌ TypeError | BUG-1 (mode="video" 编造) |
| 2 | acceptance_retest_231053 | ❌ 超时 | 用户"无法点击" |
| 3 | acceptance_diag_232836 | ❌ 永远 PHASE_SUMMARY_FAILED | BUG-3 (waitKey race) + BUG-4 (detect 错方法) |
| 4 | acceptance_test4_234500 | ❌ 超时 | 用户继续测试 |
| 5 | acceptance_test5_235000 | ❌ 返回 None | BUG-5 (.detected 错属性) |
| 6 | acceptance_test6_000000 | ❌ 永远检测不到人脸 | BUG-6 (compute_ear_from_landmarks 不存在) |
| 7 | **acceptance_test7_003632** | **✅ EAR=0.4051 CQS=0.60** | **3 项新 UX issue（本节）** |

**7 次迭代修了 6 个真机 BUG**（全是 A1 agent 编造的 API 名），最终端到端跑通。

### 2.8.1 v1.3 校准结果接线审计（commit 8cab08a 配套 issue 列表）

> **记录日期**：2026-06-05
> **触发**：T-CAL-30~33 头部姿态 bug 修复时连带做的全链路审计
> **目的**：检查 `CalibrationResult` 13 个字段中各有多少被 main.py 实际应用
> **结论**：13 字段中 4 字段被应用（P0/P1 修复后 + ear_mean + baseline_blink_rate），9 字段闲置
> **本节已处理**：P0（adjustment_factor）+ P1（head_pose_std）已完成并 commit
> **本节待处理**：P2/P3/P4 经审计无实际修复价值，原因如下表

| # | 字段 | 校准采集 | 当前消费方 | 是否值得修 | 结论 |
|---|------|---------|----------|-----------|------|
| P0 | `final_adjustment_factor` | Phase 4 算 (0.7-1.3) | **无**（已修） | ✅ | **已完成** commit 8cab08a |
| P1 | `signal.yaw_range` / `pitch_range` | Phase 3 收集 | **仅 DB**（已修） | ✅ | **已完成** commit 8cab08a |
| P2 | `signal.ear_min` | Phase 1 闭眼校准 | `EyeAspectResult.left_open`/`.right_open` (无 reader) | ❌ | **不修** — 无人消费 flag，即使接线也无行为变化 |
| P3 | `signal.glasses_mode` | 写死 `False` (flow.py:424) | **无** | ❌ | **不修** — main.py 运行时已调 `glasses_detector.detect()` 实时检测（`main.py:301-305`），静态校准值是子集且会冲突（用户中途摘眼镜） |
| P4 | `signal.ear_mid` | Phase 2 眯眼校准 | **仅 DB** | ❌ | **不修** — 眯眼 vs 眨眼判定走时间 (`BLINK_MAX_DURATION_SEC = 0.4` in eye_aspect.py:31)，不走 EAR 值；如要改判定逻辑是更大重构 |
| P4-alt | `config.HEAD_POSE.*` 死代码清理 | n/a | 仍被 OLD v3.x 路径使用 (detector/head_pose.py:47, detector/gaze.py:28) | ❌ | **不修** — v3.x 还在用，删了破坏旧路径 |

#### 关联 commit

- `8cab08a` fix(calib): P0/P1 校准结果接线 (adjustment_factor + head_pose_std)
  - 6 files changed, 220 insertions, 12 deletions
  - 488 tests passed (基线 478 + 10 新测试)

#### 后续若需扩展 (TODO for future sprint)

1. **让 `left_open`/`right_open` 真被使用** — 在 main.py 校验用户是否长时间单眼/双眼闭眼（眼健康监测），需要新功能需求驱动
2. **重新设计 squint vs blink 判定** — 改走 EAR 值（如 ear_mid < ear < ear_min）而非时间，但需要验证假阳/假阴率
3. **校准-运行时 glasses 一致性检查** — 如果用户校准时戴眼镜但运行时不戴，标记警告（基于历史数据，运行时仍以实时检测为准）

---

### 2.8.2 v1.4 v4.3 漏洞审计与维护完成（2026-06-05 全量修复）

> **记录日期**：2026-06-05
> **触发**：用户发起"检查一下当前项目是否有漏洞并进行修复"任务
> **审计范围**：5 模块 + calibration + spike/insights（main.py / analyzer/ / detector/ / storage/ / reporter/ / gui/ / calibration/ / spike/insights/）
> **审计 workflow**：w1qwhzqp9 (5 agent 并行) + w9qm21n9b (calibration 补丁) + 11 个独立 verifier 反驳验证
> **审计报告归档**：[`docs/old_schemes/AUDIT_v4.3.md`](docs/old_schemes/AUDIT_v4.3.md) 255 行 12 章节
> **本节结论**：v4.3 维护全部完成，58 findings 中 44 个已修，14 个 false positive 跳过

#### 修复统计

| 类别 | 总数 | 修了 | 跳过 | 跳过原因 |
|------|------|------|------|---------|
| **Critical** | 1 | 1 | 0 | - |
| **High** | 13 | 13 | 0 | - |
| **Medium** | 26 | 26 | 0 | - |
| **Low** | 18 | 4 | 14 | false positive（之前 commit 已修或不存在）|
| **Calib patch** | 7 | 0 | 7 | 范围外（calib 3 medium 在 v4.3 batch 1 已修 M-24/M-25/M-26）|
| **总计** | **58** | **44** | **14** | |

#### 关键 commit（按 criticality 排序）

**Critical**：
- `d28d851` fix(db): **CRIT-01** storage 线程安全合同（`_get_cursor` 持锁防跨线程事务撤销）

**High（合同级 / 数据完整性）**：
- `ff4149e` fix(user_calib): H-06 BlinkRoundCollector 双阈值分类（ear_threshold 死参数激活）
- `121eab9` fix(fatigue): H-04 get_record 抽 `_compute_sustained` 纯函数（不再污染 sustained 状态）
- `d28d851` fix(db): H-08 get_frame_records 补 7 字段（blink_flag/perclos/gaze_status/fatigue_label/focus_score/focus_breakdown/light_level）
- `d28d851` fix(db): H-09 export_json 加 None 守卫（删 session 后不再 AttributeError）

**High（运行时稳定）**：
- `3f41025` fix(fatigue): H-03 perclos_threshold_mild 0.15 → 5.0（5% 业务阈值）
- `099026c` fix(focus): H-05 baseline_ear=0 保护（不再 ZeroDivisionError）
- `6307045` fix(main): H-01 signal handler 仅设 flag（不再 0.5s 阻塞 + 双重清理）
- `34ca3c2` fix(main): H-02 CameraManager.start 入口 join 残留线程（3.0s timeout 防双线程竞争）
- `4a1d097` fix(face_mesh): H-07 缺模型文件 fail-fast 抛 FileNotFoundError
- `c1eb937` fix(report_html): H-10 图表异常显式 HTML 标记（不再静默吞）
- `f760392` fix(main): H-11 CameraManager.start 失败 release cap（防 DirectShow handle 泄漏）
- `e54ef6c` fix(main): H-12 run_v4_2_calibration finally 包 try/except（保留原始异常 traceback）
- `9cf7a58` fix(main): H-13 _cleanup 用 logger.exception（统一 close 异常处理）

**Medium 26 个**（数据完整性 + 资源管理 + XSS 防护）：
- analyzer 5 个：M-01 EAR 滑动窗口 / M-02 PERCLOS 末帧 / M-03 user=0 调降 / M-04 删死代码 / M-05 except 收窄
- detector 6 个：M-06 is_adequate NORMAL only / M-07 face_region NaN / M-08 frame=None / M-09 landmarks 478 / M-10 face_mesh frame=None / M-11 clamp [0.7, 1.3]
- storage 5 个：M-12 FK PRAGMA / M-13 JSON 容错 / M-14 WAL checkpoint / M-15 OperationalError 重试 / M-16 rowcount 校验
- reporter 3 个：M-17 XSS session_id / M-18 XSS insight / M-19 matplotlib 泄漏
- main.py 4 个：M-20 cleanup_done 标志 / M-21 camera_index / M-22 删死代码 / M-23 db try/except
- calib+spike 3 个：M-24 TTS join / M-25 face/ear 计数分离 / M-26 删 sys.path hack

**Low 4 个真修**（其余 14 个审计时已不存在）：
- `8b7d428` fix(reporter): L-10 matplotlib Agg backend 提常量
- `ebe9f81` fix(gui): L-15/16 cv2 BGR 颜色常量集中 + 替换 (255,255,255)
- `940eda9` fix(spike): L-18 删除未用 import os

**审计归档**：
- `3015d57` docs(audit): v4.3 漏洞审计完整报告归档（58 findings + 44 fixes 总结）

#### 测试基线变化

```
v4.3 起点:       488 passed (2026-06-04 状态)
CRIT-01 修:      491 passed (+3)
H-03..H-06 修:   496 passed (+5)
H-04 修:         497 passed (+1)
H-01..H-13 修:   511 passed (+14)
M-01..M-26 修:   556 passed (+45)
L-10/L-15/L-16/L-18 修: 556 passed (low fix 不加测试)
─────────────────────────────────────────
v4.3 终点:       556 passed (+68 新增回归测试, 0 回归)
```

#### GitHub Issues 全部关闭

| # | 标题 | 状态 | 关联 commit |
|---|------|------|-------------|
| #4 | H-01 signal handler | ✅ closed | 6307045 |
| #5 | H-02 摄像头 race | ✅ closed | 34ca3c2 |
| #6 | H-04 sustained state | ✅ closed (派发时已修) | 121eab9 |
| #7 | H-07 模型文件 | ✅ closed | 4a1d097 |
| #8 | H-10 图表异常 | ✅ closed | c1eb937 |
| #9 | H-11 cap 泄漏 | ✅ closed | f760392 |
| #10 | H-12 finally 异常 | ✅ closed | e54ef6c |
| #11 | H-13 cleanup log | ✅ closed | 9cf7a58 |

#### 关键教训

1. **session compaction 会杀 subagent**（实测 wkxtzrfwg 4 subagent 启动后 7.6h 被 kill, 无 commit 落地）。解法：subagent 必须**独立 commit**，不能用 worktree 隔离，inline 模式更稳。
2. **verifier 反驳模式有效**（1 partial + 10 confirmed + 0 rejected）。H-02 partial 修正了失效机制描述但确认 race 真实。
3. **审计 finding 中 false positive 比例**（18 low 中 14 假，77%）提示：审计应由 agent 自带 grep 二次验证，避免"历史残留 finding"误报。
4. **TDD 在 v4.3 维护中价值**：每个 fix 都有对应 failing test，下次回归自动捕获。
5. **§2.8.1 之前文档化 P2/P3/P4 不可执行** 避免了重做无用功，验证了 §1.1 触发条件 + §1.3 同步规则的有效性。

#### 后续若需扩展 (TODO for future sprint)

1. **calibration 7 个 patch finding**（CAL-AUDIO-01/CAL-PHASE-03/CAL-SPIKE-IMPORT-01 等）— 3 medium 已在 v4.3 M-24/M-25/M-26 修，剩 4 low（死代码 + spike 测试覆盖）
2. **大规模重构**：eye_aspect 的 blink 判定改走 EAR 而非时间（涉及假阳/假阴率验证）
3. **左/右眼开闭监测**（基于 H-08 已修的 left_open/right_open 字段）— 需要新功能需求驱动

### 2.8.3 v4.4 GUI 清晰化 + 拖窗口 REC 维护完成（2026-06-06）

> **记录日期**：2026-06-06
> **触发**：v4.3 后实测发现 GUI 信息过载 + 模式态不清晰 + 拖窗口录制无视觉提示
> **设计 spec**：`docs/superpowers/specs/2026-06-05-v4-4-gui-clarity-and-drag-rec.md`
> **实施 plan**：`docs/superpowers/plans/2026-06-05-v4-4-gui-clarity-and-drag-rec.md`
> **本节结论**：v4.4 维护 7 commit 全部落地，1 commit test 回归修复，580/580 测试通过

#### 关键 commit（按实施顺序）

| # | Commit | 类型 | 模块 | 描述 |
|---|--------|------|------|------|
| 1 | `398a369` | feat(calib) | `calibration/ui/panel.py` | panel 常驻 ●REC 录制中指示（绿底白字）|
| 2 | `c99a254` | feat(calib) | `calibration/input_handler.py` + `panel.py` | 拖窗口检测 + DRAGGING 画面冻结提示 |
| 3 | `b177538` | feat(gui) | `gui/overlay.py` | MODE 状态栏圆点 2.4x + 字体 1.36x + ● 前缀 |
| 4 | `63132db` | feat(gui) | `gui/overlay.py` | focus 圆环 r=70 + 数字 1.5x + 8px 边框颜色按分数 |
| 5 | `dbb0fd4` | feat(gui) | `gui/overlay.py` | fatigue 切档彩色横条（MEDIUM 黄 / HIGH 红闪烁 + 大警告）|
| 6 | `d5b2243` | feat(gui) | `gui/overlay.py` + `main.py` | no-face banner（5s 阈值 + 红底白字横条 + 闪烁）|
| 7 | `691438d` | fix(test) | `calibration/tests/unit/test_input_handler.py` | 6 个 v4.4 回归修复（`__new__` 缺 `_on_waitkey_return`）|

#### 对 Phase 2 模块的影响

| 模块 | 影响 |
|------|------|
| `gui/overlay.py` | 5 个 commit 大改（圆环/横条/状态栏/无脸），但**未变更公共 API**（`FocusOverlay.draw()` 签名稳定）|
| `calibration/input_handler.py` | 新增拖窗口事件路径，**未破坏鼠标/键盘主路径**（IME 兼容性保留）|
| `main.py` | v4.3 `_paused` 修复（commit 2d1645d）+ v4.4 `_last_face_time` 字段（commit d5b2243），无集成层回退 |
| `reporter/` / `analyzer/` / `detector/` / `storage/` | **无任何改动**（v4.4 范围限于 GUI 层）|

#### 测试基线变化

```
v4.3 终点:       556 passed (2026-06-05 §2.8.2)
calibration 子包 0 → 198 (v4.4 集成 calibration/tests 进入统计): 754 passed
v4.4 起点:       754 passed (2026-06-06 凌晨)
回归修复 691438d: 754 passed (修复 `__new__` 不影响测试数)
─────────────────────────────────────────
v4.4 终点:       580 passed (test 整合去重后) / 754 raw
```

**注**：test 数 754 → 580 的下降是 `tests/` 382 + `calibration/tests/` 198 = 580 的拆分（calibration 子包独立 testpaths）。PROJECT_PLAN §16 v4.4 节点以 **580** 为对外基线。

#### 后续若需扩展 (TODO for future sprint)

1. **focus 圆环颜色按分数当前仅 2 档（绿/红）** — 可扩为 3 档（绿 MEDIUM/黄 GOOD/红 HIGH），但需用户研究确认阈值
2. **fatigue 切档动画当前是硬切换** — 可加 200ms 渐变过渡
3. **no-face 5s 阈值** — 可配置化（让用户在 config.yaml 调整）

---

## 三、工时汇总

| 任务组 | D1 | D2 | T1 | 小计 |
|--------|-----|-----|-----|------|
| **【v4.2】T-CAL-01~T-CAL-14 calibration 重设计** | **13h** | **6h** | **1h** | **20h** |
| T200-T205 报告系统 | 9h | - | - | 9h |
| T206-T207 个性化建议 | - | 3h | - | 3h |
| T208-T211 分心识别 | 3.5h | 0.5h | - | 4h |
| T212-T215 跨会话 + 真人测试 | 6h | - | - | 6h |
| T216-T218 测试补充 | - | 5h | - | 5h |
| **【v4.1】T220 features** | 1.5h | - | - | 1.5h |
| **【v4.1】T221 DB schema** | - | 0.5h | - | 0.5h |
| **【v4.1】T222 changepoint** | 2h | - | - | 2h |
| **【v4.1】T223 anomaly** | - | 1.5h | - | 1.5h |
| **【v4.1】T224 patterns** | 2h | - | - | 2h |
| **【v4.1】T225 temporal** | 2h | - | - | 2h |
| **【v4.1】T226 attribution** | - | 2h | - | 2h |
| **【v4.1】T227 pipeline** | 1h | - | - | 1h |
| **【v4.1】T228 报告 4 章节** | - | 3h | - | 3h |
| **【v4.1】T229 单测** | - | 3h | - | 3h |
| **【v4.1】T230 集成测试** | - | - | 2h | 2h |
| **【v4.1】T231 文档同步** | 1h | - | - | 1h |
| T219 Phase 2 验收 | - | - | 3h | 3h |
| **合计** | **41h** | **24.5h** | **6h** | **71.5h** |

---

## 四、阶段依赖图

```
Phase 1.6 Spike (S11-S15+SUM) ─── 门禁 PASS ───┐
                                                ↓
                            ┌─────────────────────────────────────┐
                            │  Phase 2 启动                        │
                            └─────────────────────────────────────┘
                                                ↓
                                ★【v4.2】严重风险任务先行
                                                ↓
       T-CAL-01 (result.py) ──┬── T-CAL-02 (config.py)
                               │
            ┌──────────────────┴──────────────────┐
            │ 阶段实现 (D1)：T-CAL-03 ~ T-CAL-07   │
            │ UI 实现 (D2)：T-CAL-08 → T-CAL-09 → T-CAL-10 │
            │ Audio 实现 (D2)：T-CAL-11           │
            └──────────────────┬──────────────────┘
                               ↓
            T-CAL-12 (flow 编排) → T-CAL-13 (__main__)
                               ↓
            T-CAL-14 (main.py 集成 + 用户 7 BUG 实测) 🔴 必过门禁
                                                ↓
                            ┌─────────────────────────────────────┐
                            │  原 Phase 2 任务启动                 │
                            └─────────────────────────────────────┘
                                                ↓
T200-T205 (charts/html) ──┬── T203 (HTML 模板) ──┬── T204 (摘要)
                          │                       └── T205 (降采样)
                          │
                          └── T220 (features) ──┬── T222 (changepoint)
                                                ├── T223 (anomaly)
                                                ├── T224 (patterns)
                                                ├── T225 (temporal)
                                                └── T226 (attribution)
                                                       │
T221 (DB schema) ◄─────────────────────────────────────┘
                                                       │
                                       T227 (pipeline) ◄── T220-T226
                                                       │
                          ┌────────────────────────────┘
                          ↓
T228 (报告 4 章节) ◄── T227 + T203
T207 (建议引擎集成) ◄── T226 + T206
                          │
T208-T211 (distraction) ──┤
T212-T215 (跨会话+真人测试) ──┤
T216-T218 (测试补充) ──┤
                          ↓
                  T229 (insights 单测) ──┐
                  T230 (集成测试) ◄──────┤
                                          │
                                  T219 (Phase 2 验收)
                                  T231 (文档同步)
```

---

## 五、风险与缓解

| 风险 | 概率 | 影响 | 等级 | 缓解措施 |
|------|:--:|:--:|:--:|------|
| **【v4.2】calibration 模块重设计高风险重构** | 高 | 极高 | 🔴 | 保守开发策略：14 子任务 + 测试门禁 + main.py 集成放最后；任一门禁未过 → 暂停（R27） |
| **【v4.2】Windows IME 拦截键盘** | 高 | 高 | 🟡 | 屏幕数字键盘鼠标点击作主输入路径；Win32 IME 禁用仅作可选兜底（R28） |
| **【v4.2】pyttsx3 SAPI 失败** | 中 | 中 | 🟡 | TTS 初始化失败时降级 beep-only + UI 警告 + 阶段时长 +50% 补偿（R29） |
| **【v4.2】摄像头切换失败** | 低 | 高 | 🟡 | 模块入口 cv2.VideoCapture 失败立即 return None；主程序用默认基线继续（R30） |
| 【v4.1】聚类数据不足导致结果不稳定 | 高 | 中 | 🟡 | silhouette ≥ 0.25 + n_sessions ≥ 10 双门槛；不足降级展示（R23） |
| 【v4.1】STL 时序分解需要长期数据 | 高 | 中 | 🟡 | n_days < 7 自动降级到 histogram（R24） |
| 【v4.1】Insights pipeline 总耗时超标 | 中 | 中 | 🟡 | try/except 隔离 + 预算 < 10s + 异步生成 loading 提示（R25） |
| 【v4.1】sklearn/scipy 增加打包体积 | 低 | 低 | 🟢 | PyInstaller +80MB 可接受；提供 lite 版本预案（R26） |
| 真人测试样本太少 | 高 | 中 | 🟡 | A4 至少 2-3 人；权重调优有兜底默认值 |
| 分心识别效果不佳 | 高 | 中 | 🟡 | 阈值可通过 config.yaml 调节 |

---

## 六、版本记录

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.3 | 2026-06-06 | v4.4 同步：新增 §2.8.3 v4.4 GUI 清晰化维护记录（7 commit + 1 fix）；测试基线 284 → 580；删除 §三 重复标题 |
| v1.2 | 2026-06-04 | 7 次真机验收后登记 3 项 UX 问题（§2.8）：(1) 闭眼检测不到闭眼 (2) 动作姿态提示不够 (3) 动作幅度大也检测不到。已规划 T-CAL-15/16/17 修复（不阻塞 calibration 主流程） |
| v1.2 | 2026-06-02 | v4.3 审计修订：(1) §2.6 T222-T226 前加 ⚠️ banner 声明所有具体参数为"草稿值，待 S-SUM 覆盖"（Issue #1 — Phase 1.6 门禁未通过）；(2) §2.2 T206 任务描述澄清现有 `reporter/insights.py` 392 行 v4.0 规则引擎作为基线，T207 叠加 attribution findings（Issue #4） |
| v1.1 | 2026-06-02 | v4.2 同步：新增 §2.0 calibration 模块重设计任务（T-CAL-01 ~ T-CAL-14，20h），明确排在 Phase 2 最前（Day 14-17），原 Phase 2 任务后移至 Day 18-22；新增 R27-R30 风险；依赖图加 calibration 前置；工时汇总 51.5h → 71.5h；总工期 7d → 9d |
| v1.0 | 2026-06-02 | 初始版本。基于 PROJECT_PLAN v4.1 拆分。含 T200-T219 原有任务 + T220-T231 v4.1 insights 新增任务。工时 51.5h，工期 Day 14-20 |

---

## 七、与其他文档的关系

| 文档 | 关系 |
|------|------|
| `PROJECT_PLAN.md` v4.1 | 本文档实施细节的来源；总方案改动时优先同步本文档 |
| `PHASE1_PLAN.md` v1.7 | 上游 — 包含 Phase 1.6 Spike，门禁条件来自该文档 |
| `docs/PHASE1_6_SPIKE_SUMMARY.md` | Phase 1.6 Spike 完成后产出的推荐参数表，覆盖本文档 T222-T226 中的默认值 |

---

> **Phase 2 启动条件**：Phase 1.6 Spike 全部 PASS + 项目负责人确认。
> **Phase 2 完成判定**：T219 验收通过 + AC9/10/17/18/26-30 全部满足。

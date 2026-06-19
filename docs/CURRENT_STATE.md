# EyeFocus Insight — 系统当前状态 v4.29

> 生成日期：2026-06-19
> 目的：单一事实源，所有 spec/plan 以本文档为准。
> 检测算法优化计划见本文 §七。

---

## 一、版本演进

| 版本 | 日期 | 核心变更 |
|------|------|---------|
| v4.26 | 06-17 | 全面优化 — 面板刷新/报告重设计/AI分析增强/性能优化 |
| v4.27 | 06-18 | API 设置对话框 + 前端AI状态轮询 + 多提供商支持 |
| v4.28 | 06-19 | AI CLI 独立模块 + L3 深度分析 + 12维安全审计 |
| v4.29 | 06-19 | 托盘精简(3监测按钮+番茄单按钮) / 报告建议重构(去掉对话+图表移入数据tab+建议丰富) / 性能优化(Qt冗余重绘缓存) / Pipeline并行化(face_mesh async) / Web控制扩展(settings端点) / 全局安全审计(36→72分) |
| v4.35 | 06-19 | 算法精度 v4 — adjustment_factor 接入 FocusAnalyzer / Fatigue 分数连续化 / avg_focus 时间加权 / 动态权重(光照/姿态感知) / 建议阈值用户适配(从历史分布加载) |

---

## 二、模块状态

| 模块 | 行数 | 状态 | 说明 |
|------|------|------|------|
| `main.py` | ~1590 | 稳定 | Qt 主循环，不做大重构 |
| `detector/` | ~550 | 稳定 | face_mesh 已加 async 并行(producer-consumer) |
| `app/processor.py` | ~400 | 稳定 | 帧处理编排，已接入 face_mesh async |
| `analyzer/focus.py` | ~660 | v4.35 增强 | 动态权重 + adjustment_factor 感知 + 时间加权 avg_focus |
| `analyzer/fatigue.py` | ~260 | v4.35 增强 | 连续分数映射(替代3级跳变) + 时间基 EMA |
| `reporter/insights.py` | ~900 | v4.35 增强 | 用户个性化阈值(从历史分布加载) |
| `analyzer/user_calibration.py` | ~650 | 稳定 | v4.2 重设计，真机 CQS=1.0 验收 |
| `analyzer/llm_client.py` | ~400 | 稳定 | OpenAI 兼容 API 封装，多提供商 |
| `analyzer/ai_cli/` | ~370 | NEW | 独立命令行 AI 对话模块 |
| `analyzer/insights/` | ~1200 | 稳定 | PELT/IsolationForest/KMeans/STL 离线分析管道 |
| `storage/` | ~500 | 稳定 | SQLite + WAL，busy_timeout=3000 |
| `gui/` | ~1500 | 稳定 | Qt 白底风格，不主动重构 |
| `webserver/` | ~680 | 稳定 | aiohttp + WebSocket 实时推送 |
| `reporter/` | ~1900 | 稳定 | HTML 报告(模板+insights+AI) |
| `calibration/` | ~1500 | 稳定 | v4.2 独立模块，全测试通过 |

---

## 三、Spec 审计清单

| Spec 文件 | 声称状态 | 实际状态 | 处理 |
|-----------|---------|---------|------|
| `superpowers/specs/2026-06-02-user-calibration-redesign.md` | ✅ 已实施 | ✅ 已实施 | **保持** — 与实际一致 |
| `superpowers/specs/2026-06-05-v4-4-gui-clarity-and-drag-rec.md` | 未声明 | ✅ v4.4 已实施 | **标记完成** |
| `superpowers/specs/2026-06-17-v4-26-report-ui-refresh.md` | 待拍板 | ⏳ 部分实施(v4.29) | **保持** — tab结构已改，深层视觉设计未动 |
| `superpowers/specs/2026-06-18-v4-26-main-panel-refresh.md` | 待拍板 | ❌ 用户否决 | **移入 archive** |
| `superpowers/plans/2026-05-31-t148-user-calibration-plan.md` | 未声明 | 🗑 T148实测全部失效 | **移入 archive** |
| `superpowers/plans/2026-06-02-calibration-redesign-plan.md` | 未声明 | ✅ v4.2 已实施 | **标记完成** |
| `superpowers/plans/2026-06-02-phase1-6-spike-plan.md` | 未声明 | ✅ Insights 已实现 | **标记完成** |
| `superpowers/plans/2026-06-05-v4-4-gui-clarity-and-drag-rec.md` | 未声明 | ✅ v4.4 已实施 | **标记完成** |

---

## 四、检测算法现状（防止重复建议）

### 4.1 EAR 基线
- ✅ 自动采集：前2分钟 `_collect_ear_auto_baseline()`，中位数 vs 默认0.25，差异>15%时自动应用
- ✅ 显式校准：`set_baseline(ear, yaw_std, pitch_std)` 由 v4.2 calibration 调用
- ✅ 眨眼阈值：`squint_threshold = ear_mean × 0.75` + `adjustment_factor` 来自校准

### 4.2 专注度评分
- ✅ EMA 平滑：下降 α=0.4（快）/ 恢复 α=0.2（慢）
- ✅ 窗口统计：15s 滑动窗口，FOCUSED≤3s偏离 / DISTRACTED≥8s偏离
- ✅ 会话衰减：前30min无衰减，之后线性降至85%
- ✅ 权重：eye=70% / head=20% / gaze=10%（固定）
- ✅ 头部渐变惩罚：舒适区 yaw≤12°/pitch≤15° 不扣分，之后线性缩放
- ✅ 人脸丢失冻结：保持最后分数不归零

### 4.3 疲劳分析
- ✅ 长闭眼计数：只统计 >0.5s 事件（忽略快眨眼）
- ✅ 3min 滚动窗口：≤3次→RESTED, ≥8次→TIRED
- ✅ 累积疲劳 EMA：0.95×prev + 0.05×current（仅有调用时衰减）

### 4.4 校准模块
- ✅ 5 阶段流程：闭眼→睁眼→眨眼→头姿→完成
- ✅ 输出：EAR均值/阈值/调整因子/头姿范围/眨眼率基线
- ✅ 接入：EyeAspectDetector(ear + adjustment_factor) / FocusAnalyzer(ear, yaw_std, pitch_std) / FatigueAnalyzer(blink_rate)

### 4.5 已关闭缺口（v4.35）

| # | 问题 | 修复版本 | 改动 |
|---|------|---------|------|
| 1 | `FatigueAnalyzer.cumulative_fatigue` 3 级跳变 | v4.35 | 连续锚点插值映射，疲劳曲线平滑 |
| 2 | 权重固定不随场景变 | v4.35 | `_compute_dynamic_weights()` 光照/姿态感知 |
| 3 | `adjustment_factor` 未接入 FocusAnalyzer | v4.35 | 偏差阈值 `0.15/adj_factor` + `set_adjustment_factor()` |

---

## 五、文档清理记录

| 操作 | 文件 |
|------|------|
| 🗄 移入 archive | `docs/superpowers/specs/2026-06-18-v4-26-main-panel-refresh.md` |
| 🗄 移入 archive | `docs/superpowers/plans/2026-05-31-t148-user-calibration-plan.md` |
| ✅ 标记完成 | `docs/superpowers/specs/2026-06-05-v4-4-gui-clarity-and-drag-rec.md` |
| ✅ 标记完成 | `docs/superpowers/plans/2026-06-02-calibration-redesign-plan.md` |
| ✅ 标记完成 | `docs/superpowers/plans/2026-06-02-phase1-6-spike-plan.md` |
| ✅ 标记完成 | `docs/superpowers/plans/2026-06-05-v4-4-gui-clarity-and-drag-rec.md` |

---

## 六、架构决策记录

- Qt 主窗口不做大重构（已稳定）
- 检测器架构保持 sync + async 双模式（sync 供 calibration，async 供主帧循环）
- 所有 API key 仅存 config.yaml（已 gitignored）+ 推荐 `.env` 覆盖
- 报告用模板+insights+AI 三层，优先级：模板>insights>AI

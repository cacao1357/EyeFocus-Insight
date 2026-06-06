# `reporter/` — 报告生成

> v4.0+ 稳定 + 持续增强 | 测试覆盖 ~80% | 状态：✅ 活跃

**职责**：**会话报告生成**——从 SQLite 读 session/frame/blink/focus/fatigue 数据 + 嵌入 Base64 图表 + 个性化建议文本 → 输出 HTML 报告到 `reports/<session_id>.html`。

## 公共 API（`__init__.py` 单入口）

```python
from reporter import create_html_generator, create_chart_generator, create_insights_engine

# HTML 报告
gen = create_html_generator(db_manager)
html_path = gen.generate_report(session_id="abc-123")
# → 写入 reports/abc-123.html

# 仅图表
chart = create_chart_generator()
fig = chart.plot_focus_timeline(focus_records, save_path=None)  # 返回 matplotlib Figure

# 仅建议
engine = create_insights_engine()
insights: list[Insight] = engine.generate(session_id)
```

| 公共符号 | 职责 |
|---------|------|
| `ChartGenerator` / `create_chart_generator()` | Matplotlib 图表（focus 趋势、眨眼分布、疲劳切档）|
| `InsightsEngine` / `create_insights_engine()` / `Insight` | 规则引擎：基于 focus_score 阈值生成个性化建议 |
| `HTMLReportGenerator` / `create_html_generator()` / `ReportData` | 完整 HTML 报告（图表 + 文本）|

## 子模块

| 文件 | 行数 | 职责 |
|------|------|------|
| `charts.py` | 365 | Matplotlib 图表（focus 趋势、眨眼分布、疲劳切档）|
| `insights.py` | 392 | 规则引擎（v4.0 392 行，v4.1 拟叠加 attribution findings）|
| `report_html.py` | 670 | HTML 报告渲染 + Base64 图表嵌入 + 模板 |

## 输出位置

- HTML 报告：`reports/<session_id>.html`（`.gitignore` 中 `reports/*.html` 忽略）
- 图表 PNG：`reports/<session_id>_*.png`（`reports/*.png` 忽略）
- 离线分析结果：写 `insights` 表（SQLite，**未跟踪**）

## 测试入口

```bash
pytest tests/test_reporter.py -v
```

## v4.1 增强计划（⏳ 未实施）

`PHASE2_PLAN.md` v1.3 §2.6 T220-T231 规划 5 个离线分析方法（KMeans 聚类、PELT 变点、IsolationForest 异常、STL 时序、关联分析）作为 `analyzer/insights/` 子包，**T207 通过 `InsightsEngine` 集成**到报告生成。

## 职责澄清（v1.1）

| 维度 | `analyzer/insights/`（计划）| `reporter/`（当前）|
|------|---------------------------|------------------|
| 角色 | 离线数据分析（5 方法）| HTML 报告渲染 |
| 触发时机 | 会话结束 | 报告生成时（用户按 Q 退出或主动查看）|
| 副作用 | 写 `insights` 表 | 写 `reports/*.html` |
| 现有实现 | ⏳ 待实现 | ✅ `reporter/insights.py` 392 行规则引擎已存在 |

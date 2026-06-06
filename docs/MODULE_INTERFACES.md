# EyeFocus Insight — 模块边界标准

> **版本**：v1.2 | **日期**：2026-06-06 | **作者**：D1
> **目的**：定义模块边界标准，防止再次出现 T148 式"模块设计 → 主程序耦合 → 实测全部失效"的失败链。
> **不重构现状**：本文档**不要求**对已稳定的现有代码做重构（main.py 等），仅约束**新增模块**和**整体重做的模块**（如 v4.2 calibration）。
> **v1.1 → v1.2 修订**：v4.4 GUI 清晰化后 `gui/overlay.py` 校准 UI 状态同步；main.py 实际行数更新；calibration 测试覆盖实测 198 个；calibration 数据契约覆盖率补说明

---

## 一、为什么需要这个文档

### 1.1 T148 失败教训

2026-06-02 用户实测 T148 用户辅助校准发现 7 个核心问题，"功能完全实现不了"。事后审计真正原因**不是项目目录不模块化**（detector/analyzer/storage/reporter/gui 已分目录），而是：

1. 模块状态机暴露给 main.py，控制反转方向错了
2. 模块 UI 派遣到 gui/overlay.py，三处耦合在同一流程
3. 输入/输出契约靠回调隐式约定，没沉淀成 dataclass
4. 模块**不能独立运行 / 独立测试**——必须 main.py 喂帧 + 催 tick
5. 真机集成验证**没有在 main.py 之外发生过**——设计阶段没人单跑过

### 1.2 防恶化策略

本文档采用 **"立标准防恶化"** 而非 **"推倒重做"**：

- ✅ 锁定**新增模块**的设计标准（v4.2 calibration / v4.1 insights 范式）
- ✅ 整体重做的模块按新标准（如 v4.2 calibration）
- ❌ 不要求重构已经稳定的现有模块（main.py / detector/ / gui/overlay.py 等）
- ❌ 不追求"全项目统一架构"（风险 > 收益）

---

## 二、每个核心模块的接口契约与对齐度

### 2.1 `detector/`（5 个文件）

| 项 | 内容 |
|----|------|
| 输入 | `cv2` 帧 (np.ndarray BGR) |
| 输出 | 模块特定 dataclass（如 `FaceDetectionResult`、`EyeAspectResult`）|
| 副作用 | 无（纯函数式或仅累积内部统计）|
| 资源管理 | 不持有摄像头；MediaPipe 模型由各 detector 单例持有 |
| 测试覆盖 | 当前 79-100% |
| **对齐度** | ⭐⭐⭐⭐ 已基本符合 |
| **待办** | 无强制重构。新增 detector 必须 dataclass 输出 |

### 2.2 `analyzer/`（4 个核心 + insights/ 子包）

#### 2.2.1 baseline.py / focus.py / fatigue.py / glasses.py / distraction.py

| 项 | 内容 |
|----|------|
| 输入 | DetectionResult dataclass + 累积状态 |
| 输出 | AnalysisResult dataclass（focus_score / fatigue_label 等）|
| 副作用 | 内部状态机（窗口缓冲区、EMA 平滑等）|
| 资源管理 | 状态生命周期归 main.py |
| 测试覆盖 | 当前 45-93% |
| **对齐度** | ⭐⭐⭐ 状态生命周期归 main.py（技术债，已知）|
| **待办** | 不强制重构。新增 analyzer 优先使用 insights/ 子包模式 |

#### 2.2.2 `analyzer/insights/`（v4.1 范本）

| 项 | 内容 |
|----|------|
| 输入 | `sqlite3.Connection` + session_id |
| 输出 | `InsightResults` dict（持久化到 `insights` 表）|
| 副作用 | SQLite 写入 |
| 资源管理 | 自有 pipeline 编排（features → 5 个分析方法 → 结果聚合）|
| 入口 | `analyzer/insights/pipeline.py::run()` |
| 独立运行 | 可（接受 conn 参数，可 mock）|
| 测试覆盖 | 计划 ≥ 75% |
| **对齐度** | ⭐⭐⭐⭐⭐ 范本 |

> **【v1.1 职责澄清】**`analyzer/insights/` 是**离线分析层**——消费 SQLite 历史数据 → 运行 5 个统计/ML 方法 → 把结果持久化到 `insights` 表。**不直接生成报告文本/图表**。下游消费方见 §2.5 reporter。

### 2.3 `calibration/`（v4.2 新增范本）

| 项 | 内容 |
|----|------|
| 输入 | session_id + Optional[CalibrationConfig] + Optional[DatabaseManager] |
| 输出 | `Optional[CalibrationResult]`（成功才返回完整结果）|
| 副作用 | 独占摄像头 + 自有 cv2 窗口 + 音频反馈 + DB 写入 |
| 资源管理 | **自有摄像头**（主程序 release → 模块 acquire → 模块 release → 主程序 re-acquire）|
| 入口 | `calibration.run(session_id)` |
| 独立运行 | ✅ `python -m calibration` 单跑全流程 |
| 测试覆盖 | 计划 ≥ 85% 整体，95% 数据契约；**实测 198 测试**（v4.4 节点：`calibration/tests/unit/` 14 文件 + `integration/` 4 文件 + `spike/` 2 文件）|
| 失败/取消 | 返回 None（严格契约 X1），不抛异常 |
| **对齐度** | ⭐⭐⭐⭐⭐ 范本 |

### 2.4 `storage/`

| 项 | 内容 |
|----|------|
| 输入 | dataclass models（Session / Frame / CalibrationResult 等）|
| 输出 | dataclass models / None |
| 副作用 | SQLite 读写（WAL 模式）|
| 资源管理 | `DatabaseManager` 类管理连接 |
| 测试覆盖 | 63% |
| **对齐度** | ⭐⭐⭐⭐ |
| **待办** | 不强制重构。新表/新查询遵循现有 repository 模式 |

### 2.5 `reporter/`

| 项 | 内容 |
|----|------|
| 输入 | session_id + sqlite3.Connection |
| 输出 | HTML 文件路径 |
| 副作用 | 写文件到 `reports/` |
| 资源管理 | Matplotlib 图表生成 |
| 入口 | `reporter.generate_report(session_id)` |
| 测试覆盖 | 待 Phase 2 实现后补 |
| **对齐度** | ⭐⭐⭐⭐ |
| **待办** | Phase 2 新增 4 章节时遵循 insights pipeline 接入模式 |

> **【v1.1 职责澄清】**`reporter/` 是**报告渲染层**——从 SQLite 读数据 + 从 `insights` 表读离线分析结果 → 渲染 HTML 报告 + 嵌入 Base64 图表 + 生成个性化建议文本。
>
> **与 `analyzer/insights/` 关系**：
>
> | 项 | `analyzer/insights/`（分析层）| `reporter/`（报告层）|
> |----|---------------------------|------------------|
> | 角色 | 离线数据分析（5 方法）| HTML 报告渲染（图表 + 文本）|
> | 触发时机 | 会话结束，pipeline.run() 一次性跑完 | 报告生成时（用户按 Q 退出或主动查看）|
> | 副作用 | 写 `insights` 表（结构化结果）| 写 `reports/*.html`（人类可读）|
> | 输入 | session_id + conn | session_id + conn + 读 `insights` 表 |
> | 输出 | `InsightResults` dict | HTML 路径 |
> | 现有实现 | ⏳ 待实现（Phase 2 T220-T231）| ✅ `reporter/insights.py` v4.0 规则引擎已存在（392 行）|
>
> **当前（v4.0 + v4.3 中间态）**：`reporter/insights.py` 中的 `InsightsEngine` 是 v4.0 规则引擎（基于 focus_score 阈值生成建议），**不是** v4.1 离线分析。v4.1 实施时**不删除**现有规则引擎，作为 T206 的"规则兜底"；v4.1 attribution findings（T226）通过 T207 集成作为主输入。

### 2.6 `gui/overlay.py`

| 项 | 内容 |
|----|------|
| 输入 | 每帧数据（focus_score / fatigue_level / 关键点等）+ overlay 状态 |
| 输出 | 渲染后的帧（np.ndarray）|
| 副作用 | `cv2.imshow` |
| 资源管理 | OpenCV 窗口 |
| 测试覆盖 | 63%（`tests/test_gui.py` v4.4 新增 4 测试）|
| **对齐度** | ⭐⭐⭐ **v4.4 改进**：(1) 校准 UI 已迁至 `calibration/ui/panel.py`（v4.2 完成），主监测 UI 在 `gui/overlay.py` 独立；(2) MODE 状态栏圆点 2.4x + 字体 1.36x + ● 前缀（commit `b177538`）；(3) focus 圆环 r=70 + 数字 1.5x + 8px 边框颜色按分数（commit `63132db`）；(4) fatigue 切档彩色横条 MEDIUM 黄 / HIGH 红闪烁（commit `dbb0fd4`）；(5) no-face banner 5s 阈值（commit `d5b2243`）|
| **待办** | v4.2 自然清理已完成；v4.4 主要为视觉清晰化，无结构性变更 |

### 2.7 `main.py`

| 项 | 内容 |
|----|------|
| 角色 | app composer / 主循环 / 信号处理 / 资源生命周期 |
| 行数 | **1343 行**（v4.4 节点，含 CameraManager / FrameProcessor / EyeFocusApp 三个内部类；v4.3 时 1169 行 → v4.4 +174 行主要来自无脸横幅 + 状态栏渲染 + 集成层调整）|
| 已知技术债 | 上帝对象 — 主循环 + 帧处理 + 摄像头管理 + 应用生命周期都在一个文件 |
| 历史 | v4.0/v4.0.1/v4.0.2/v4.3/v4.4 五轮 bug 修复 + 真机稳定 |
| **对齐度** | ⭐ 极低 |
| **处理方式** | **不重构**——重构风险（5-10 个新 bug + FPS 回归 + 测试破损 30-50%）> 收益（讲故事好听）|
| **未来** | 如未来确需重构，采用 strangler 模式分批拆 `app/camera_service.py`、`app/frame_processor.py`；不允许"一次重做"|

---

## 三、新模块强制开发规范

任何 **新增** 的独立功能模块（如未来的 Streamlit Dashboard、Ollama 集成、新分析子包等）**必须**遵循以下规范：

### 3.1 目录结构

```
<module_name>/
├── __init__.py          # 暴露公共 API
├── __main__.py          # `python -m <module_name>` 独立运行入口
├── <core>.py            # 核心逻辑
├── config.py            # 模块配置（dataclass）
├── result.py            # 输出契约（dataclass）
└── tests/
    ├── unit/            # 单元测试（mock 外部依赖）
    ├── integration/     # 集成测试（多组件协同）
    └── spike/           # 真机/合成数据 spike 验证
```

### 3.2 接口要求

| 要求 | 说明 |
|------|------|
| **公共 API 单一入口** | `__init__.py` 中明确导出 `run()` 或主类，禁止暴露内部实现 |
| **独立运行** | `python -m <module>` 能完整跑通核心流程（可接受 mock 输入）|
| **资源自有或显式接收** | 摄像头/DB/窗口等资源**不从全局拿**——要么模块自己 acquire+release，要么作为参数显式传入 |
| **数据契约 = dataclass** | 输入/输出均为 dataclass，禁止 tuple 或自由格式 dict |
| **错误返回 None / Optional** | 失败、取消、资源不可用等场景 **返回 None**，**不抛异常**给上层 |
| **可独立测试** | 单元测试不能依赖 main.py 或其他模块的运行时实例 |

### 3.3 测试要求

| 项 | 门禁 |
|----|------|
| 数据契约（result.py / config.py） | 覆盖率 ≥ 95% |
| 核心逻辑 | 覆盖率 ≥ 85% |
| UI 渲染 | 覆盖率 ≥ 75% |
| 整体 | 覆盖率 ≥ 75% |
| spike 真机验证 | 每个对外功能至少 1 个 spike 脚本 |

### 3.4 集成接入要求

| 项 | 说明 |
|----|------|
| 主程序接入点 | main.py 中**一行**调用：`result = module.run(...)`；不允许在 main.py 中暴露模块内部状态 |
| 失败处理 | 主程序对 None 返回值有明确降级路径 |
| 资源切换 | 如模块独占资源（如摄像头），主程序应有 release → call → re-acquire 模式 |

---

## 四、PR Review 检查清单

新模块 PR 必须 D1 review，确认以下全部 ✅：

```
□ 目录结构符合 §3.1
□ __init__.py 暴露明确公共 API
□ __main__.py 可独立运行
□ 输入/输出均为 dataclass
□ 资源管理符合 §3.2（自有或显式接收）
□ 失败返回 None 不抛异常
□ 单元测试覆盖率达 §3.3 门禁
□ 至少 1 个 spike 脚本真机验证
□ main.py 集成 ≤ 1 行公共 API 调用
□ 无对其他模块内部实现的依赖（仅通过公共 API）
□ 模块对齐度更新到 §2 表格
```

---

## 五、规范应用矩阵

| 情况 | 是否走本规范 | 备注 |
|------|------------|------|
| 完全新增的功能模块 | ✅ 强制 | 必须按 v4.2 范式 |
| 整体重做的模块（如 v4.2 calibration）| ✅ 强制 | 按 v4.2 范式 |
| 修复现有模块的 bug | ❌ 不强制 | 沿用模块现有风格 |
| 现有模块新增小功能 | ❌ 不强制 | 沿用模块现有风格 |
| 现有模块明显有问题（如 T148）| 🟡 评估 | 评估是否值得整体重做；如重做，必须按本规范 |

---

## 六、版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.2 | 2026-06-06 | v4.4 同步：§2.3 calibration 测试覆盖从"计划 ≥85%"更新为"实测 198 测试"；§2.6 gui/overlay.py 对齐度从 ⭐⭐ 升 ⭐⭐⭐（v4.4 5 个 commit 视觉清晰化，v4.2 校准 UI 迁移已生效）；§2.7 main.py 行数 1169 → 1343（v4.3 → v4.4 增长 174 行来自无脸横幅 + 状态栏 + 集成层）；历史轮次 v4.0/v4.0.1/v4.0.2 → v4.0/v4.0.1/v4.0.2/v4.3/v4.4 |
| v1.1 | 2026-06-02 | v4.3 审计修订：§2.2.2 末尾 + §2.5 末尾新增"职责澄清"段落（Issue #5 — analyzer/insights/ vs reporter/insights.py 命名空间错位）；含两者关系对照表（角色/触发/副作用/输入/输出/现有实现）|
| v1.0 | 2026-06-02 | 初稿 — 由 brainstorm 会话定型（C 方案）。锁定 7 个核心模块对齐度，约束新增模块走 v4.2 范式 |

---

## 七、参考

- v4.2 calibration 范本：`docs/superpowers/specs/2026-06-02-user-calibration-redesign.md`
- v4.1 insights 范本：`PROJECT_PLAN.md` §6.9 + `PHASE2_PLAN.md` §2.6
- 项目总方案：`PROJECT_PLAN.md` v4.2
- 阶段计划：`PHASE1_PLAN.md` v1.8 + `PHASE2_PLAN.md` v1.1

# EyeFocus Insight — Claude Code 项目规范

## 项目版本管理规则

### 触发版本更新的条件

**当发生以下情况时，必须更新总方案（PROJECT_PLAN.md）并同步迭代对应阶段方案：**

| 触发条件 | 示例 | 影响范围 |
|---------|------|---------|
| **实测数据与方案预想不符** | S2 CQS 公式过严，实测 0/3 PASS | 总方案算法参数、阈值、验收标准 |
| **技术方案重大调整** | solvePnP 废弃，改用 MediaPipe 内置矩阵 | 总方案架构、风险列表、任务清单 |
| **新增或删除功能模块** | 新增 `detector/light.py` 光照检测 | 总方案模块列表、Phase 1 任务清单 |
| **里程碑延后或取消** | 眼镜检测 DEPRECATED，推迟 Phase 1 任务 | 总方案时间线、风险列表 |
| **硬件/环境条件变化** | RTX 5070 可用，引入双轨开发策略 | 总方案开发策略、团队配置 |
| **关键假设被证伪** | EAR 方差法无法区分眼镜用户 | 总方案眼镜检测方案、风险 R6/R15 |

### 总方案（PROJECT_PLAN.md）版本管理

**每次修改 `PROJECT_PLAN.md` 必须执行以下步骤：**

1. **归档旧版本**
   - 将当前 `PROJECT_PLAN.md` 复制到 `docs/old_schemes/PROJECT_PLAN_v{N}.md`
   - 版本号 N = 旧版本号 + 1（例如 v2 → v3）

2. **版本命名**
   - 文件名格式：`PROJECT_PLAN_v{N}.md`（如 `PROJECT_PLAN_v3.md`）
   - 文件内第一行版本号同步更新为 `v{N}.0`

3. **变更记录**
   - 在新方案的 `PROJECT_PLAN.md` 中，保留并扩展"版本迭代记录"章节
   - 在章节开头新增当前版本的变更记录，包含：
     - 变更日期
     - 变更原因
     - 具体变更明细表格（章节 | 原始方案 | 更新方案 | 变更原因）
     - v{N-1} → v{N} 关键决策记录

**正确流程示例**（v2 → v3）：

```
当前状态：
  PROJECT_PLAN.md (v2.0)
  docs/old_schemes/PROJECT_PLAN_v1_original.md

执行修改 v2 → v3：
  1. cp PROJECT_PLAN.md docs/old_schemes/PROJECT_PLAN_v2.md
  2. 修改 PROJECT_PLAN.md（版本号改为 v3.0）
  3. 在 PROJECT_PLAN.md 的"版本迭代记录"中添加 v3.0 章节

最终状态：
  PROJECT_PLAN.md (v3.0) ← 当前生效版本
  docs/old_schemes/PROJECT_PLAN_v1_original.md
  docs/old_schemes/PROJECT_PLAN_v2.md
```

### 阶段方案同步更新规则

**总方案（PROJECT_PLAN.md）版本更新时，必须同步检查并更新以下文档：**

| 文档 | 同步内容 | 版本规则 |
|------|---------|---------|
| `PHASE0_PLAN.md` | 当前执行阶段的执行记录、实测结果、Bug 修复 | 跟随 PROJECT_PLAN 版本 |
| `PHASE0_SUMMARY.md` | 验证报告、实测数据、关键发现 | 跟随 PROJECT_PLAN 版本 |
| `docs/PHASE{N}_PLAN.md` | 当对应阶段执行时，同步更新实测结果 | 跟随 PROJECT_PLAN 版本 |

**同步更新要求**：
- 总方案版本升级后（如 v2 → v3），对应阶段方案的版本号同步更新
- 版本记录章节追加新版本条目
- 新方案末尾"版本迭代记录"中说明与上一版本的差异

**版本联动示例**（Phase 0 完成后触发）：

```
触发事件：Phase 0 全部完成，S2 Bug 修复，眼镜检测方案 DEPRECATED

检查范围：
  PROJECT_PLAN.md    → 版本 v2 → v3，新增眼镜检测方案、光照检测、双轨策略
  PHASE0_PLAN.md    → 版本 v1 → v2，更新实测结果、S2 Bug 修复、Gate Check
  PHASE0_SUMMARY.md → 版本 v1，新增眼镜检测失效分析、光照感知分析

结果：
  三份文档版本统一为 v3/v2/v1（总方案最高）
```

### 文档更新规范

| 文档 | 修改时要求 |
|------|---------|
| `PROJECT_PLAN.md` | 必须遵循上述版本管理规则 |
| `PHASE0_SUMMARY.md` | 版本号跟随 PROJECT_PLAN.md 版本更新 |
| spike 脚本结果 | 存入 `spike/results/{成员代号}/` 子目录 |
| 旧方案 | 统一存放在 `docs/old_schemes/` 目录 |

### 目录结构规范

```
EyeFocus Insight/
├── PROJECT_PLAN.md              ← 当前生效的总方案（最新版本）
├── PHASE0_SUMMARY.md            ← Phase 0 验证报告
├── docs/
│   └── old_schemes/            ← 旧版本方案归档
│       ├── PROJECT_PLAN_v1_original.md
│       └── PROJECT_PLAN_v2.md
└── spike/
    └── results/                ← spike 测试结果
        ├── D1/
        ├── D2/
        └── T1/
```

### 快速命令

```bash
# 归档当前版本并开始修改（当前版本 v2，计划升级到 v3）
cp PROJECT_PLAN.md docs/old_schemes/PROJECT_PLAN_v2.md

# 同步更新阶段方案（归档旧版本 + 更新版本号 + 追加变更记录）
cp PHASE0_PLAN.md docs/old_schemes/PHASE0_PLAN_v1.md
# 然后修改 PHASE0_PLAN.md 版本号和变更记录

# 然后修改 PROJECT_PLAN.md（版本号改为 v3.0）
```

### 版本号对应关系

| 总方案版本 | PHASE0 方案 | PHASE0 报告 |
|-----------|-------------|-------------|
| v1.0 | v1.0 | v1.0 |
| v2.0 | v1.0 | v1.0 |
| v3.0 | v2.0 | v1.0 |

**规则**：总方案版本号 = 最高版本号；阶段方案在对应阶段执行时同步更新到最新

### 版本号规则

- 格式：`v{Major}.{Minor}`
- 每次修改总方案：Major + 1，Minor 归零
- 日常小修订（如仅更新 PHASE0_SUMMARY）：仅更新 Minor（如 v3.0 → v3.1）
- Phase 里程碑完成后：可选择升级 Major 版本

### 当前版本

- **PROJECT_PLAN.md**：v3.3（2026-05-30）— 新增 §6.8 眨眼检测算法改进
- **PHASE1_PLAN.md**：v1.1（2026-05-30）— 新增 T145-T147 眨眼算法改进任务
- **PHASE0_SUMMARY.md**：v3.0（2026-05-30）— Phase 0 验证报告

### 归档目录

```
docs/old_schemes/
├── PROJECT_PLAN_v1.md        # 初始版本
├── PROJECT_PLAN_v2.md        # Phase 0 验证后修订版
├── PROJECT_PLAN_v3.md        # 双轨开发策略 + 光照/眼镜检测增强
├── PHASE0_PLAN_v2.md        # Phase 0 执行计划 v2.0
└── PHASE0_SUMMARY_v1.md     # Phase 0 验证报告 v1.0
└── （当前版本为 PROJECT_PLAN.md，即 v3.3）
```

---

## Git 协作规则

### 分支与合并策略

| 场景 | 规则 |
|------|------|
| **功能分支提交** | 合并到 `main` 后**直接删除分支**（已启用 `delete-branch-on-merge`） |
| **PR 合并** | 项目负责人（D1）拥有直接合并权限，**直接 Merge PR 到 main**，无需 Code Review |
| **远程推送** | 如果可以合并到 main，直接推送并合并；不需要创建 PR |

**操作流程**：
```bash
# 1. 切换到 main 并拉取最新
git checkout main && git pull origin main

# 2. 创建功能分支（如果需要）
git checkout -b feat/xxx

# 3. 提交并推送到远程
git add . && git commit -m "feat: xxx" && git push

# 4. 直接合并到 main（负责人权限）
git checkout main && git merge --no-ff feat/xxx && git branch -d feat/xxx
```

---

## 开发环境硬件配置（主开发者 D1）

> 用于参考开发可行性和性能估算

| 项目 | 规格 |
|------|------|
| **笔记本型号** | Lenovo 型号待确认 |
| **CPU** | AMD Ryzen 9 8945HX |
| **规格** | 16 核心 / 32 线程 |
| **内存** | 32 GB |
| **GPU** | NVIDIA GeForce RTX 5070 Laptop |
| **显存** | 8 GB GDDR7（当前空闲约 6.4 GB）|
| **算力** | CC 12.0 (Blackwell) |
| **驱动版本** | 592.47 |
| **CUDA Toolkit** | 12.8 |
| **PyTorch** | 2.11.0 + cu128（.venv312 环境）|
| **主项目环境** | Python 3.12.4（.venv312 环境）|

**Python 环境**：
- `.venv312`（Python 3.12 + PyTorch 2.11 + CUDA 12.8）— 统一环境，包含主项目依赖和 GPU 支持

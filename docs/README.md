# `docs/` — 项目级文档

> 团队共享规范 | 状态：✅ 活跃

**职责**：项目级（非个人）规范、spike 总结、真机验收报告、设计 spec/plan。与 `CLAUDE.md`（本地规则，已 gitignore）严格区分。

## 目录结构

```
docs/
├── README.md                       # 本文件
├── MODULE_INTERFACES.md            # 模块边界标准（v1.2 团队规范）
├── PHASE1_6_SPIKE_SUMMARY.md       # Phase 1.6 S11-S15 探针结论
├── REAL_MACHINE_TEST_v4.3.md       # v4.3 真机验收报告（CQS=1.00）
├── old_schemes/                    # 历史归档（按版本号保留）
│   ├── PROJECT_PLAN_v1.md
│   ├── PROJECT_PLAN_v2.md
│   ├── PROJECT_PLAN_v3.md
│   ├── PROJECT_PLAN_v3.4.md
│   ├── PROJECT_PLAN_v4.0.md
│   ├── PROJECT_PLAN_v4.0.1.md
│   ├── PROJECT_PLAN_v4.0.2.md
│   ├── PROJECT_PLAN_v4.1.md
│   ├── PROJECT_PLAN_v4.2.md
│   ├── PROJECT_PLAN_v4.3.md        # v4.4 完成后归档
│   ├── PHASE0_PLAN_v2.md
│   ├── PHASE0_SUMMARY_v1.md
│   ├── PHASE1_PLAN_v1.4.md
│   ├── PHASE1_PLAN_v1.5.md
│   ├── T148_USER_CALIBRATION_DESIGN_v1.0.md
│   └── AUDIT_v4.3.md
└── superpowers/                    # 团队共享设计文档（与 .superpowers/ 本地 brainstorm 区分）
    ├── specs/                      # 设计 spec
    │   ├── 2026-06-02-user-calibration-redesign.md  # ✅ 已实施
    │   └── 2026-06-05-v4-4-gui-clarity-and-drag-rec.md  # ✅ 已实施
    └── plans/                      # 实施 plan
        ├── 2026-05-31-t148-user-calibration-plan.md  # ⚠️ 已被 v4.2 取代
        ├── 2026-06-02-calibration-redesign-plan.md  # ✅ 已实施
        ├── 2026-06-02-phase1-6-spike-plan.md         # ✅ S11-S15 PASS
        └── 2026-06-05-v4-4-gui-clarity-and-drag-rec.md  # ✅ 已实施
```

## 关键文档导航

| 需求 | 文档 |
|------|------|
| 模块边界规范 | `MODULE_INTERFACES.md` v1.2（v4.4 GUI 清晰化已同步）|
| 总体方案 | `../PROJECT_PLAN.md` v4.4 |
| Phase 1 计划 | `../PHASE1_PLAN.md` v2.0 |
| Phase 2 计划 | `../PHASE2_PLAN.md` v1.3 |
| Phase 0 总结 | `../PHASE0_SUMMARY.md` v3.2 |
| 测试指南 | `../TESTING_GUIDE.md` |
| v4.3 真机验收 | `REAL_MACHINE_TEST_v4.3.md` |
| Phase 1.6 spike 结论 | `PHASE1_6_SPIKE_SUMMARY.md` |

## 跟踪策略

| 路径 | 跟踪 | 说明 |
|------|------|------|
| `docs/*.md` | ✅ | 项目级规范 |
| `docs/old_schemes/*.md` | ✅ | 历史归档（按版本号保留）|
| `docs/superpowers/specs/*.md` | ✅ | 团队设计 spec |
| `docs/superpowers/plans/*.md` | ✅ | 团队实施 plan |
| `.superpowers/` | ❌ | 本地 brainstorm 工具目录（已 .gitignore）|
| `CLAUDE.md` | ❌ | 本地 Claude 规则（已 .gitignore）|

## 本地 vs 项目的边界（容易混淆）

| 路径 | 性质 | 是否上传 |
|------|------|---------|
| `docs/superpowers/` | 项目团队共享 | ✅ 上传 |
| `.superpowers/` | 本地 Claude 工具 | ❌ 不上传（gitignore）|
| `CLAUDE.md` | 本地规则 | ❌ 不上传（gitignore）|
| `MEMORY.md` | Claude 记忆索引 | ❌ 不上传（gitignore）|
| `docs/MODULE_INTERFACES.md` | 项目团队规范 | ✅ 上传 |

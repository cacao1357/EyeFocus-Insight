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
├── API.md                          # API 参考
├── ARCHITECTURE.md                 # 架构说明
├── DEV_GUIDE.md                    # 开发者指南
├── PYQT5_MIGRATION.md              # PyQt5 迁移记录
├── USER_GUIDE.md                   # 用户指南
├── old_schemes/                    # 历史归档（保留在 git 历史中，工作树已移除）
└── superpowers/                    # 团队共享设计文档（与 .superpowers/ 本地 brainstorm 区分）
    ├── specs/                      # 设计 spec
    └── plans/                      # 实施 plan
```

## 关键文档导航

| 需求 | 文档 |
|------|------|
| 模块边界规范 | `MODULE_INTERFACES.md` v1.2 |
| 架构说明 | `ARCHITECTURE.md` |
| API 参考 | `API.md` |
| 用户指南 | `USER_GUIDE.md` |
| 开发者指南 | `DEV_GUIDE.md` |

## 跟踪策略

| 路径 | 跟踪 | 说明 |
|------|------|------|
| `docs/*.md` | ✅ | 项目级规范 |
| `docs/old_schemes/` | ❌ (历史归档) | 保留在 git 历史中，工作树已移除 |
| `docs/superpowers/` | ✅ | 团队设计文档 |
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

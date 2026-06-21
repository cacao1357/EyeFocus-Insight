# docs/ — 项目文档

> 本目录包含项目的公开文档。

## 目录结构

```
docs/
├── README.md                       # 本文件（目录导览）
├── ARCHITECTURE.md                 # 架构说明（模块分层 / 数据流 / 通信机制）
├── MODULE_INTERFACES.md            # 模块边界规范（v4.2 模块范本）
├── API.md                          # 公共 API 参考
├── USER_GUIDE.md                   # 用户使用指南
└── DEV_GUIDE.md                    # 开发者贡献指南
```

子包内部的详细文档：

| 子包 | README 路径 |
|------|------------|
| analyzer | [`analyzer/README.md`](../analyzer/README.md) |
| detector | [`detector/README.md`](../detector/README.md) |
| gui | [`gui/README.md`](../gui/README.md) |
| storage | [`storage/README.md`](../storage/README.md) |
| reporter | [`reporter/README.md`](../reporter/README.md) |
| calibration | [`calibration/README.md`](../calibration/README.md) |
| spike | [`spike/README.md`](../spike/README.md) |
| tests | [`tests/README.md`](../tests/README.md) |

## 文档导航

| 你想了解... | 看这个 |
|------------|--------|
| 项目整体架构 | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| 模块边界规范 | [`MODULE_INTERFACES.md`](MODULE_INTERFACES.md) |
| 公共 API | [`API.md`](API.md) |
| 如何使用软件 | [`USER_GUIDE.md`](USER_GUIDE.md) |
| 如何贡献代码 | [`DEV_GUIDE.md`](DEV_GUIDE.md) |
| 跑测试 / CI | [`tests/README.md`](../tests/README.md) |

## 约定

- `docs/` 下文档使用 Markdown，UTF-8 + LF 行尾（见 `.gitattributes`）
- 模块子包 README 描述该子包特有的设计与使用细节
- 历史归档已移出工作树，需要时通过 git 历史访问
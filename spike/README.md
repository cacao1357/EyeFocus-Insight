# `spike/` — 一次性探针

> 状态：⚠️ **约定不维护**（一次性探针，非产品代码）

**职责**：算法/性能/集成验证脚本。**不入主测试套件**（`pytest` 默认不收集 `spike_*.py`），独立 `python spike/xxx.py` 跑。

## 目录结构

```
spike/
├── baseline_proto.py        # S2 EAR 基线验证
├── head_pose_proto.py       # S3 头部姿态验证
├── ear_variance.py          # S4 EAR 方差（眼镜检测预研）
├── fps_benchmark.py         # 帧率基准
├── face_landmarker.task     # MediaPipe 模型（首次运行自动下载，已 .gitignore）
├── s2_result.json           # 机器生成结果（已 .gitignore）
├── common.py                # 探针共享工具
├── insights/                # Phase 1.6 Insights 5 方法验证 (S11-S15)
│   ├── _common.py
│   ├── s11_clustering.py
│   ├── s12_changepoint.py
│   ├── s13_anomaly.py
│   ├── s14_temporal.py
│   ├── s15_attribution.py
│   └── _gen_summary.py
└── results/                 # 探针产物
    └── D1/                  # D1 真机测试结果（手写 .txt 报告 + 机器生成 .png/.json）
```

## 跟踪策略（`.gitignore`）

| 类型 | 状态 |
|------|------|
| `spike/*.py` | ✅ 跟踪（探针代码）|
| `spike/face_landmarker.task` | ❌ 忽略（MediaPipe 模型本地缓存）|
| `spike/s2_result.json` | ❌ 忽略（机器产物）|
| `spike/results/**/*.json` | ❌ 忽略（机器产物）|
| `spike/results/**/*.png` | ❌ 忽略（v4.4 决定，机器产物）|
| `spike/results/**/*.txt` | ✅ 跟踪（手写报告，留档）|

## 跑探针

```bash
.venv312/Scripts/python.exe spike/baseline_proto.py
.venv312/Scripts/python.exe spike/head_pose_proto.py
.venv312/Scripts/python.exe spike/insights/s11_clustering.py
```

详见 `TESTING_GUIDE.md`。

## 已知限制

- 不进 `tests/`，**没有 CI 强制门禁**
- 不主动维护，发现问题不修 — 重写或废弃
- 跨平台未验证（部分依赖 Windows 摄像头）

## 关联文档

- `TESTING_GUIDE.md` — 完整 spike 跑测指南
- `docs/PHASE1_6_SPIKE_SUMMARY.md` — Phase 1.6 S11-S15 探针结论
- `docs/old_schemes/PROJECT_PLAN_v4.1.md` §6.9 — 探针在 v4.1 计划的原始定位

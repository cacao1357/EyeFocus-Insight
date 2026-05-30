# EyeFocus Insight — 项目问题报告

**生成日期**：2026-05-30　　　**基于分支**：`feat/phase0-spike`　　　**阶段**：Phase 0 完成后

---

## 目录

- [1. 严重问题（Blockers）](#1-严重问题blockers)
- [2. 中等问题（Warnings）](#2-中等问题warnings)
- [3. 轻微问题（Info）](#3-轻微问题info)
- [4. 测试缺失清单](#4-测试缺失清单)
- [5. 已知 Bug 追踪](#5-已知-bug-追踪)
- [6. Phase 0 遗留待办](#6-phase-0-遗留待办)
- [7. 风险矩阵](#7-风险矩阵)

---

## 1. 严重问题（Blockers）

### 🔴 B1 — 5 个核心模块全部为空壳

| 属性 | 内容 |
|------|------|
| **位置** | `detector/`、`analyzer/`、`storage/`、`reporter/`、`gui/` |
| **现状** | 每个目录仅包含空的 `__init__.py`，无任何实现代码 |
| **影响** | 项目当前除 spike 验证脚本外无可运行的产品代码。`main.py` 入口也不存在 |
| **计划应对** | Phase 1 T100-T134 任务，共 51.5 工时 |
| **建议** | 优先实现 `detector/` 模块（作为下游依赖），再依次实现 `analyzer/` → `gui/` → `main.py` 骨架 |

### 🔴 B2 — `os._exit()` 暴力退出绕过 MediaPipe 死锁

| 属性 | 内容 |
|------|------|
| **位置** | `spike/fps_benchmark.py`、`spike/baseline_proto.py`、`spike/head_pose_proto.py`、`spike/ear_variance.py` |
| **根因** | `FaceLandmarker.close()` 调用时 XNNPACK 后台线程不退出，导致程序永久阻塞 |
| **当前做法** | 所有 spike 脚本在退出时直接调用 `os._exit()`，不执行任何清理 |
| **影响** | 生产代码（`main.py`）不能使用 `os._exit()`，必须实现安全退出 |
| **计划应对** | Phase 1 实现线程超时强杀：设置 daemon 线程 + `join(timeout=N)` + 超时后强制 terminate |

### 🔴 B3 — `main.py` 主入口未创建

| 属性 | 内容 |
|------|------|
| **位置** | 项目根目录 |
| **现状** | 不存在。项目无统一启动入口 |
| **影响** | 无法作为应用程序运行。所有功能散落在 spike 脚本中 |
| **计划应对** | Phase 1 T130 任务 |

---

## 2. 中等问题（Warnings）

### 🟡 W1 — 4 个 spike 脚本存在大量重复代码

| 属性 | 内容 |
|------|------|
| **位置** | `spike/fps_benchmark.py`、`spike/baseline_proto.py`、`spike/head_pose_proto.py`、`spike/ear_variance.py` |
| **重复模式** | 摄像头初始化 → MediaPipe 推理循环 → 头部姿态提取 → 结果保存的主循环结构高度相似 |
| **影响** | 维护成本高，修复一处问题需改多处；Phase 1 可能重复造轮子 |
| **建议** | 在启动 Phase 1 前，将公共循环模式提取为 `common.py` 中的通用函数或类 |

### 🟡 W2 — `sys.path.insert()` hack 解决导入路径

| 属性 | 内容 |
|------|------|
| **位置** | 多个 spike 脚本开头 |
| **代码模式** | `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` |
| **影响** | 不标准的模块导入方式，Phase 1 正式模块间导入会出问题 |
| **建议** | Phase 1 使用标准 Python 包结构 + 可编辑安装（`pip install -e .`） |

### 🟡 W3 — `solve_head_pose_from_matrix()` 无测试覆盖

| 属性 | 内容 |
|------|------|
| **位置** | `spike/common.py` — `solve_head_pose_from_matrix()` |
| **现状** | 这是当前实际使用的头部姿态方案（替代已废弃的 solvePnP），但 18 个测试无一覆盖 |
| **测试文件** | `tests/test_common.py` 只测试了旧的 `solve_head_pose()` |
| **影响** | 当前方案的正确性没有自动化保障 |

### 🟡 W4 — `.gitignore` 缺失

| 属性 | 内容 |
|------|------|
| **位置** | 项目根目录 |
| **现状** | 不存在 `.gitignore` 文件 |
| **证据** | `git status` 显示 `__pycache__/`、`.venv312/`、`*.pyc` 等应被忽略的文件出现在 untracked 中 |
| **影响** | 容易误提交构建产物、虚拟环境、IDE 配置等无关文件 |

### 🟡 W5 — 眼镜自动检测方案存在残余风险

| 属性 | 内容 |
|------|------|
| **背景** | S5 EAR 方差法已确认失效并标记 DEPRECATED。S9 Blendshapes 方案在受控条件下表现良好（眯眼比率 0.40 vs 0.91） |
| **风险** | 眯眼比率差异在更多样本中缩小至 3.3%，且需与光照变化区分 |
| **当前对策** | Blendshapes + 眼角距离双保险 + 手动开关兜底 |
| **建议** | Phase 1 实现后需进行多人多场景测试（D2、T1 当前为空） |

---

## 3. 轻微问题（Info）

### 🟢 I1 — 内联 import 不标准

| 属性 | 内容 |
|------|------|
| **位置** | 多个函数体内 |
| **代码** | `from mediapipe import Image` 在函数内部导入 |
| **影响** | 不影响功能，但不符合 PEP 8 规范。spike 中可接受，Phase 1 应移入文件顶部 |

### 🟢 I2 — `data/`、`reports/`、`assets/` 目录为空

| 属性 | 内容 |
|------|------|
| **影响** | 目前无影响，Phase 1 运行时需创建对应的目录自动生成逻辑 |

### 🟢 I3 — D2 和 T1 测试结果目录为空

| 属性 | 内容 |
|------|------|
| **位置** | `spike/results/D2/`、`spike/results/T1/` |
| **含义** | 仅 D1 完成了实际测试。第二人和多时段的测试数据缺失 |
| **影响** | 算法普适性仅单人验证 |

### 🟢 I4 — 无 CI/CD 配置

| 属性 | 内容 |
|------|------|
| **影响** | 无自动化测试流水线，回归风险随代码量增长累积 |

### 🟢 I5 — 无 `pyproject.toml` 或 `setup.py`

| 属性 | 内容 |
|------|------|
| **现状** | 仅有 `requirements.txt` |
| **影响** | 项目无法以标准方式安装为可编辑包 |

---

## 4. 测试缺失清单

### 4.1 已覆盖（18 个测试）

| 测试类 | 测试数 | 覆盖函数 |
|--------|:-----:|------|
| `TestModelPoints` | 4 | `MODEL_POINTS` 坐标 |
| `TestSolveHeadPose` | 5 | `solve_head_pose()`（已废弃方案） |
| `TestCalculateEar` | 4 | `calculate_ear()` |
| `TestCalcCqs` | 5 | `calc_cqs()` |
| `TestGetCameraMatrix` | 4 | `get_camera_matrix()` |
| **合计** | **18** | 5 个函数 |

### 4.2 未覆盖（关键函数）

| 函数 | 文件 | 重要性 | 备注 |
|------|------|:-----:|------|
| `solve_head_pose_from_matrix()` | `spike/common.py` | 🔴 高 | **当前实际使用的头部姿态方案**，无任何测试 |
| `normalize_yaw()` | `spike/common.py` | 🟡 中 | yaw 角度归一化 |
| `compute_ear_from_landmarks()` | `spike/common.py` | 🟡 中 | 从 MediaPipe 关键点坐标计算 EAR |
| `extract_landmarks()` | `spike/common.py` | 🟡 中 | 468 点提取 |
| `create_face_landmarker()` | `spike/common.py` | 🟢 低 | 需模型文件，难以单测 |
| `camera_context()` | `spike/common.py` | 🟢 低 | 上下文管理器 |
| `opencv_windows()` | `spike/common.py` | 🟢 低 | 上下文管理器 |

### 4.3 整体覆盖率

| 维度 | 数据 |
|------|------|
| 预估代码覆盖率 | **30-40%**（仅 `common.py` 中约一半纯函数） |
| 集成测试 | **0**（D1 为手动真人测试，非自动化） |
| 系统测试 | **0** |

---

## 5. 已知 Bug 追踪

| ID | 描述 | 严重程度 | 状态 | 修复方案 |
|----|------|:--:|:--:|------|
| KB-1 | `FaceLandmarker.close()` 因 XNNPACK 线程不退出而永久阻塞 | 🔴 高 | 未修复 | Phase 1 实现线程超时强杀 |
| KB-2 | solvePnP + 自定义 3D 模型返回 yaw=-80°（完全错误） | 🟡 中 | 已废弃 | 转用 MediaPipe 内置 `facial_transformation_matrixes` |
| KB-3 | CQS 公式 `ear_cv * 5` 过于严格，导致合格率过低 | 🟢 低 | 已修复 | 改为 `ear_cv * 3` |
| KB-4 | `baseline_proto.py:193` 硬编码 0.70 阈值 | 🟢 低 | 已修复 | 改为读取 `config.py` 的 `BASELINE.cqs_threshold` |
| KB-5 | EAR 方差法无法区分眼镜用户（反而戴眼镜方差更低） | 🟡 中 | 已废弃 | S5→DEPRECATED，转 Blendshapes 方案 |

---

## 6. Phase 0 遗留待办

| # | 描述 | 优先级 | 目标 Phase |
|---|------|:--:|:--:|
| T-1 | 眼镜自动检测实现（Blendshapes + 眼角距离双保险 + 手动保底） | 🔴 高 | Phase 1 |
| T-2 | `main.py` 安全退出方案（替代 `os._exit()`） | 🔴 高 | Phase 1 |
| T-3 | 疲劳检测先用启发式阈值过渡 | 🟡 中 | Phase 1 |
| T-4 | Blendshapes 眼镜检测精度需更多样本验证 | 🟡 中 | Phase 1 |
| T-5 | EPA 虹膜面积作为辅助指标探索 | 🟢 低 | Phase 2 |
| T-6 | 疲劳 LSTM 模型数据收集 | 🟢 低 | Phase 2 |

---

## 7. 风险矩阵

| 风险 | 概率 | 影响 | 等级 | 缓解措施 |
|------|:--:|:--:|:--:|------|
| 眼镜自动检测准确率不足 | 中 | 高 | 🔴 | Blendshapes + 眼角距离双保险 + 手动兜底 |
| MediaPipe close() 无官方修复 | 高 | 中 | 🟡 | 线程超时强杀 |
| Phase 1 51.5 工时估算偏乐观 | 中 | 高 | 🔴 | 优先关键路径，非核心功能可降级 |
| 疲劳检测缺训练数据 | 高 | 中 | 🟡 | 先用启发式阈值 |
| 不同光照/角度下检测不稳定 | 中 | 中 | 🟡 | 光照检测 + 告警 + 过滤 |
| PyInstaller 打包 MediaPipe 模型文件 | 中 | 中 | 🟡 | 提前验证（Phase 1 初期） |
| 多人/多场景普适性未验证 | 中 | 中 | 🟡 | 补充 D2/T1 测试数据 |

---

*本报告仅整理问题，不包含修改建议以外的任何代码变更。*

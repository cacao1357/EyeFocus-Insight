# EyeFocus Insight

眼动追踪与疲劳检测系统。基于 MediaPipe Face Mesh 实现实时 EAR 眨眼检测和头部姿态分析。

---

## 环境要求

- Python 3.10+
- Windows 10/11（其他平台未测试）

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/cacao1357/EyeFocus-Insight.git
cd EyeFocus-Insight
```

### 2. 创建虚拟环境

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Linux/macOS
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 下载 MediaPipe 模型

首次运行前需下载 Face Mesh 模型文件：

**方式一：自动下载（推荐）**

运行 `python main.py` 启动时若未检测到模型会自动从 [MediaPipe assets](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task) 加载（v4.0+）。

**方式二：手动下载**

1. 下载 [face_landmarker.task](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task)
2. 放入项目根目录（v4.0+ 已从 `spike/` 迁移至根目录）

### 5. 运行程序

```bash
# 主程序（自动校准 + 实时检测，OpenCV GUI）
python main.py

# Qt GUI 模式（推荐）：校准对话框 + 监测窗口
python test_qt_monitor.py

# 运行测试
python -m pytest tests/ --tb=line -q

# 帧率基准测试
python spike/fps_benchmark.py

# 基线校准（7秒采集）
python spike/baseline_proto.py

# 头部姿态验证（4阶段）
python spike/head_pose_proto.py
```

---

## 项目结构

```
EyeFocus-Insight/
├── config.py           # 集中配置管理
├── main.py             # 主程序入口
├── requirements.txt    # 依赖列表
├── face_landmarker.task  # MediaPipe 模型（运行时下载，不入仓）
├── detector/           # 检测器模块
│   ├── face_mesh.py    # MediaPipe 人脸网格
│   ├── eye_aspect.py   # EAR 眨眼检测
│   ├── head_pose.py    # 头部姿态检测
│   ├── gaze.py         # 视线方向检测
│   ├── euler_utils.py  # 头部姿态矩阵解算
│   └── light.py        # 光照条件感知
├── analyzer/           # 分析器模块
│   ├── focus.py        # 专注度分析
│   ├── fatigue.py      # 疲劳分析
│   ├── glasses.py      # 眼镜检测
│   └── user_calibration.py  # 用户多轮校准（v1.3+）
├── calibration/        # 校准子系统（v4.2+ 整体重做，按 v4.2 范式开发）
│   ├── phases/         # 4 阶段校准（中心/角度/距离/眨眼）
│   ├── audio/          # 校准提示音
│   └── ui/             # 校准 UI 组件
├── analyzer/insights/  # 数据洞察子包（v4.1+）
├── storage/            # 存储模块
│   ├── models.py       # 数据模型定义
│   └── db.py           # SQLite 数据库层
├── gui/                # Qt GUI 模块
│   ├── qt_window.py    # 主监测窗口（v4.5+）
│   ├── calibration_dialog.py  # 校准对话框（v4.7 重设计）
│   ├── qt_overlay.py   # Apple Health 风格叠加组件
│   ├── video_label.py  # 摄像头画面显示
│   └── overlay.py      # OpenCV 实时叠加层（旧路径备用）
├── analyzer/insights/  # 离线分析子系统（v4.1+：聚类/变点/异常/时序/归因）
├── reporter/           # 报告生成（v1.4+）
│   ├── report_html.py  # HTML 报告（含 9 章节 + insights 集成）
│   ├── charts.py       # Matplotlib 图表（含 4 种 insights 图表）
│   └── insights.py     # 个性化建议引擎
├── spike/              # Phase 0 验证脚本
│   ├── fps_benchmark.py        # S1: 帧率测试
│   ├── baseline_proto.py       # S2: 基线校准
│   ├── head_pose_proto.py      # S3: 头部姿态
│   ├── ear_variance.py         # S5: EAR 方差
│   ├── insights/              # Insights spike 验证（S11-S15）
│   └── results/               # 测试结果
├── tests/              # 单元与集成测试（380+ 用例，含 insights 22 个）
├── docs/               # 文档
│   ├── old_schemes/    # 旧版本方案归档
│   └── superpowers/    # 详细设计文档
├── test_qt_monitor.py  # Qt GUI 启动脚本（v4.6.2+）
├── PROJECT_PLAN.md     # 总规划方案（v4.6）
├── PHASE0_PLAN.md      # Phase 0 执行计划
├── PHASE0_SUMMARY.md   # Phase 0 验证报告
├── PHASE1_PLAN.md      # Phase 1 开发计划（v2.0）
└── PHASE2_PLAN.md      # Phase 2 开发计划（v1.3）
```

---

## 核心技术

| 技术 | 用途 |
|------|------|
| MediaPipe Face Mesh (468点) | 人脸关键点检测 |
| facial_transformation_matrixes | 头部姿态 (yaw/pitch/roll) |
| EAR (Eye Aspect Ratio) | 眨眼检测 |
| CQS (Calibration Quality Score) | 校准质量评分 |

---

## 当前进度

**v4.6** — Insights 离线分析子系统 + v4.7 Qt 校准对话框重设计完成。

总规划见 [PROJECT_PLAN.md](./PROJECT_PLAN.md)。Phase 0 验证见 [PHASE0_SUMMARY.md](./PHASE0_SUMMARY.md)。Phase 1 任务见 [PHASE1_PLAN.md](./PHASE1_PLAN.md)。Phase 2 任务见 [PHASE2_PLAN.md](./PHASE2_PLAN.md)。

| 版本 | 内容 | 测试 |
|------|------|------|
| **v3.4** | 帧处理重构（FrameProcessor 统一） | 251 |
| **v4.0** | 10 个审计发现修复 | 275 |
| **v4.0.1** | 实测 bug 修复（create_session 冲突 / head_pose KeyError） | 279 |
| **v4.0.2** | UX 实测 4 bug 修复 | 284 |
| **v4.1** | `analyzer/insights/` 离线分析子包（聚类/变点/异常/时序/归因） | 284 |
| **v4.2** | `calibration/` 模块重做（T148 7 BUG 解决） | 284 |
| **v4.3** | 集成校准 + GUI 重设计 + 44 audit fixes | 556 |
| **v4.4** | GUI 清晰化（圆环/疲劳横条/MODE 圆点/无脸检测横条）+ 拖窗口 REC | **580** |
| **v4.5** | Qt 校准对话框（数据驱动阈值 + 3 轮眨眼验证闭环 + 检测器共享） | **580** |
| **v4.6** | Qt 校准 v4.7 重设计（70/30 白底面板 + 手动步进） + Insights 子系统实现 | 380+ |

### 关键性能指标

| 指标 | 目标 | 实测 |
|------|------|------|
| 端到端帧率 | ≥ 30 FPS | **70-109 FPS** |

### 关键性能指标（v4.3 沿用）

| 指标 | 目标 | 实测 |
|------|------|------|
| 端到端帧率 | ≥ 30 FPS | **70-109 FPS** |
| 单帧延迟 | ≤ 33 ms | **9.2 ms** |
| 启动时间 | < 1 s | **27-52 ms** |
| MediaPipe 推理 | < 15 ms | **7.0 ms (XNNPACK CPU)** |
| 摄像头检出 | 100% | 100% (5/5 秒) |
| 持续运行 5s | 无崩溃 | ✅ |

### 已知限制

- **B4 部分**：MediaPipe C++ `W0000` 警告仍出现（mediapipe 0.10.35 绕 env var，不影响功能）
- **GUI 渲染逻辑测试**：CLI 环境无法验证像素输出；v4.3+ 采用源码字符串验证（如 `_draw_no_face_banner` 方法存在性 + 关键参数）覆盖渲染分支。完整视觉验证仍需 Windows GUI 桌面实机

---

## 团队成员

| 角色 | 职责 |
|------|------|
| D1 | 主开发者 — 核心算法实现 |
| D2 | 辅助开发者 — 参数调优与测试 |
| T1 | 测试者 — 依赖验证与环境测试 |

---

## License

MIT

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
# 主程序（自动校准 + 实时检测）
python main.py

# 帧率基准测试
python spike/fps_benchmark.py

# 基线校准（7秒采集）
python spike/baseline_proto.py

# 头部姿态验证（4阶段）
python spike/head_pose_proto.py

# EAR 方差采集
python spike/ear_variance.py --label no_glasses
python spike/ear_variance.py --label with_glasses
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
├── gui/                # GUI 模块
│   └── overlay.py      # 实时叠加层
├── reporter/           # 报告生成（v1.4+）
├── spike/              # Phase 0 验证脚本
│   ├── fps_benchmark.py        # S1: 帧率测试
│   ├── baseline_proto.py       # S2: 基线校准
│   ├── head_pose_proto.py      # S3: 头部姿态
│   ├── ear_variance.py         # S5: EAR 方差
│   ├── common.py               # 共享算法实现
│   └── results/                # 测试结果（按成员分类；.json 输出不入仓，.txt 分析报告入仓）
│       └── D1/                 # D1 已落盘的 6 份手写分析报告（s4/s5/s6/s7/s9/s10）
├── tests/              # 单元与集成测试（382 个）
├── docs/               # 文档
│   └── old_schemes/    # 旧版本方案归档
├── PROJECT_PLAN.md     # 总规划方案（v4.3）
├── PHASE0_PLAN.md      # Phase 0 执行计划
├── PHASE0_SUMMARY.md   # Phase 0 验证报告
├── PHASE1_PLAN.md      # Phase 1 开发计划（v1.9）
└── PHASE2_PLAN.md      # Phase 2 开发计划（v1.2）
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

**v4.4** — GUI 清晰化 + 拖窗口 REC + 无脸检测横条完成。

总规划见 [PROJECT_PLAN.md](./PROJECT_PLAN.md)。Phase 0 验证见 [PHASE0_SUMMARY.md](./PHASE0_SUMMARY.md)。Phase 1 任务见 [PHASE1_PLAN.md](./PHASE1_PLAN.md)。Phase 2 任务见 [PHASE2_PLAN.md](./PHASE2_PLAN.md)。

| 版本 | 内容 | 测试 |
|------|------|------|
| **v3.4** | 帧处理重构（FrameProcessor 统一） | 251 |
| **v4.0** | 10 个审计发现修复（死代码/基线接线/AND-confidence/光照边界） | 275 |
| **v4.0.1** | 实测新发现 2 bug（create_session 同微秒冲突 / head_pose phases KeyError） | 279 |
| **v4.0.2** | UX 实测 4 bug（无效摄像头/Mediapipe telemetry/动态文案/日志风格） | 284 |
| **v4.1** | `analyzer/insights/` 子包（v4.1 范式） | 290 |
| **v4.2** | `calibration/` 整体重做（T148 7 BUG 解决，按 v4.2 范式 6 条硬约束） | 300 |
| **v4.3** | 集成 v4.2 校准到默认流程 + GUI 重设计 + 44 audit fixes | 380 |
| **v4.4** | GUI 清晰化（focus 圆环 r=70 / fatigue 切档彩色横条 / MODE 圆点 2.4x） + 拖窗口检测 + DRAGGING 提示 + panel 常驻 ●REC + 无脸检测红底白字横条 | **382** |

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

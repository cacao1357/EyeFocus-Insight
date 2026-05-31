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

运行任意 spike 脚本会自动下载模型到 `spike/face_landmarker.task`。

**方式二：手动下载**

1. 下载 [face_landmarker.task](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task)
2. 放入 `spike/` 目录

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
├── detector/           # 检测器模块
│   ├── face_mesh.py    # MediaPipe 人脸网格
│   ├── eye_aspect.py   # EAR 眨眼检测
│   ├── head_pose.py    # 头部姿态检测
│   ├── gaze.py         # 视线方向检测
│   └── light.py        # 光照条件感知
├── analyzer/           # 分析器模块
│   ├── baseline.py      # 基线校准
│   ├── focus.py        # 专注度分析
│   ├── fatigue.py      # 疲劳分析
│   ├── glasses.py      # 眼镜检测
│   └── user_calibration.py  # 用户多轮校准
├── storage/            # 存储模块
│   ├── models.py       # 数据模型定义
│   └── db.py          # SQLite 数据库层
├── gui/                # GUI 模块
│   └── overlay.py      # 实时叠加层
├── spike/             # Phase 0 验证脚本
│   ├── fps_benchmark.py        # S1: 帧率测试
│   ├── baseline_proto.py       # S2: 基线校准
│   ├── head_pose_proto.py      # S3: 头部姿态
│   ├── ear_variance.py         # S5: EAR 方差
│   ├── common.py               # 共享算法实现
│   └── results/                # 测试结果（按成员分类）
│       ├── D1/
│       ├── D2/
│       └── T1/
├── docs/               # 文档
│   └── old_schemes/    # 旧版本方案归档
├── PHASE0_PLAN.md      # Phase 0 执行计划
├── PHASE0_SUMMARY.md   # Phase 0 验证报告
└── PHASE1_PLAN.md      # Phase 1 开发计划
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

**Phase 1 开发阶段** — MVP 核心功能实现中。

Phase 0 验证结果见 [PHASE0_SUMMARY.md](./PHASE0_SUMMARY.md)。

| 检查项 | 状态 |
|--------|------|
| S1 帧率 (≥25 FPS) | ✅ PASS |
| S2 基线校准 | ✅ PASS |
| S3 头部姿态 | ✅ PASS |
| S4 过滤参数审查 | ✅ 完成 |
| S5 EAR 方差分析 | ✅ 完成 |
| S6 依赖验证 | ✅ PASS |
| S7 光照测试 | ✅ PASS |

**Phase 1 任务** 见 [PHASE1_PLAN.md](./PHASE1_PLAN.md)。

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

# 测试指南

本文档说明如何运行 EyeFocus Insight 的各项 spike 验证测试。

---

## 环境准备

### 1. 克隆并进入项目

```bash
git clone https://github.com/cacao1357/EyeFocus-Insight.git
cd EyeFocus-Insight
# main 分支已包含 v4.4 全部 commit（feat/phase0-spike 已合并）
```

### 2. 创建虚拟环境

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 确认摄像头可用

```bash
python -c "import cv2; cap=cv2.VideoCapture(0); print('OK' if cap.isOpened() else 'FAIL'); cap.release()"
```

---

## 测试项目

### S1 — 帧率基准测试

**目的**：验证 FPS 是否达到 ≥ 25 的目标。

**运行**：
```bash
python spike/fps_benchmark.py
```

**验收**：运行约 2 分钟后自动停止，输出 `pass: True` 即通过。

**查看结果**：`spike/s1_result.json`

---

### S2 — 基线校准

**目的**：采集个人 EAR 基线值，验证 CQS 评分。

**运行**（连续 3 次）：
```bash
python spike/baseline_proto.py
```

每次运行约 10 秒，结束后将 `spike/s2_result.json` 重命名为 `spike/s2_result_1.json`（依此类推）。

**验收**：
- 3 次校准的 EAR CV < 10%
- 至少 2/3 次 CQS ≥ 0.60（v4.0 起阈值从 0.70 改为 0.60，参见 PROJECT_PLAN §1.6 决策 #6）

---

### S3 — 头部姿态验证

**目的**：验证头部姿态检测的稳定性（正视抖动 < ±3°）。

**运行**：
```bash
python spike/head_pose_proto.py
```

**操作**：按屏幕提示完成 4 个阶段（正视 → 低头 → 左转 → 恢复正视），每阶段 5 秒。

**验收**：
- Phase 1（正视屏幕）yaw_std < 3° 且 pitch_std < 3°

**查看结果**：`spike/s3_result.json`

---

### S4 — 过滤参数审查

由 D1/D2 根据 S2 结果分析，本成员无需执行。

---

### S5 — EAR 方差采集

**目的**：采集不戴眼镜/戴眼镜时的 EAR 方差数据。

**运行**（不戴眼镜 × 3 次）：
```bash
python spike/ear_variance.py --label no_glasses
```
每次运行后将 `spike/s5_result_no_glasses.json` 备份保存。

**运行**（戴眼镜 × 3 次）：
```bash
python spike/ear_variance.py --label with_glasses
```

**查看结果**：`spike/s5_result_no_glasses.json`、`spike/s5_result_with_glasses.json`

---

### S6 — 依赖完整性验证

**目的**：确认全新环境下所有依赖可正常安装和导入。

**运行**：
```bash
# 删除旧 .venv（如有）
rmdir /s /q .venv

# 创建新环境并安装
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 验证导入
python -c "import cv2; import mediapipe; import numpy; import pandas; import matplotlib; print('All OK')"
```

**验收**：无报错即为通过。

---

### S7 — 光照联合验证

**目的**：验证戴眼镜/不戴眼镜在不同光照条件下的 FPS 表现。

**运行**（4 种组合，每种 ≥ 2 分钟）：

```bash
# 1. 戴眼镜 + 台灯光源近
python spike/fps_benchmark.py

# 2. 戴眼镜 + 不开台灯（暗环境）
python spike/fps_benchmark.py

# 3. 不戴眼镜 + 台灯光源近
python spike/fps_benchmark.py

# 4. 不戴眼镜 + 不开台灯（暗环境）
python spike/fps_benchmark.py
```

每次运行后保存 `spike/s1_result.json` 为对应文件：
- `spike/s7a_with_glasses_bright.json`
- `spike/s7b_with_glasses_dark.json`
- `spike/s7c_no_glasses_bright.json`
- `spike/s7d_no_glasses_dark.json`

**验收**：所有 4 种组合的 FPS ≥ 20。

---

## 测试结果管理

### 文件夹结构

所有测试结果保存在 `spike/results/` 目录下，按成员分类：

```
spike/results/
├── D1/
│   ├── s1_result.json              # S1 帧率测试
│   ├── s2_result.json              # S2 基线校准（最新）
│   ├── s2_result_1.json           # S2 Run 1
│   ├── s2_result_2.json           # S2 Run 2
│   ├── s3_result.json             # S3 头部姿态
│   ├── s4_review.txt              # S4 过滤参数审查
│   ├── s5_result_no_glasses.json  # S5 不戴眼镜（最新）
│   ├── s5_result_with_glasses.json # S5 戴眼镜（最新）
│   ├── s5_threshold.txt           # S5 阈值建议
│   ├── s6_issues.txt              # S6 依赖验证
│   ├── s7a_with_glasses_bright.json  # S7 戴眼镜+明亮
│   ├── s7b_with_glasses_dark.json    # S7 戴眼镜+暗环境
│   ├── s7c_no_glasses_bright.json    # S7 不戴眼镜+明亮
│   ├── s7d_no_glasses_dark.json      # S7 不戴眼镜+暗环境
│   └── s7_lighting_report.txt      # S7 光照报告
├── D2/
│   └── （D2 成员测试结果）
└── T1/
    └── （T1 成员测试结果）
```

### 提交测试结果

1. 在 `spike/results/` 下创建以自己名字命名的文件夹（首次）
2. 每次测试完成后，将 `spike/` 下生成的 JSON/TXT 文件移入自己的文件夹
3. 运行多条测试时，可按日期或测试名称重命名文件
4. 汇总结果后更新到团队共享文档

**示例：**

```bash
# 首次：创建自己的文件夹（用 Python 避免 Windows Git Bash 缺 mkdir）
python -X utf8 -c "import os; os.makedirs('spike/results/D2', exist_ok=True)"

# 测试完成后：移动文件到自己的文件夹（用 Python 避免 Windows Git Bash 缺 mv）
python -X utf8 -c "import shutil; shutil.move('spike/s1_result.json', 'spike/results/D2/')"
python -X utf8 -c "import shutil; shutil.move('spike/s2_result.json', 'spike/results/D2/s2_result_1.json')"
```

---

## 通用操作说明

### 窗口控制
- 所有脚本显示 OpenCV 窗口
- 按 `Q` 键提前退出
- 窗口关闭自动结束（部分脚本）

### 结果文件
测试结果自动保存到 `spike/` 目录下的 JSON 文件。
如需保留多次运行结果，请在下次运行前手动备份或重命名。

### 常见问题

| 问题 | 解决 |
|------|------|
| 摄像头无法打开 | 检查 `cv2.VideoCapture(0)` 的 index，或尝试 `cap=cv2.VideoCapture(1)` |
| 导入报错 | 确认已激活 `.venv`，并完成 `pip install -r requirements.txt` |
| 脚本运行卡住 | 按 `Q` 退出，或关闭 OpenCV 窗口 |
| MediaPipe 下载慢 | 可手动下载 face_landmarker.task 放入 spike/ 目录 |

---

## 测试记录模板

测试完成后，可在团队沟通中按以下格式汇报：

```
S1: [PASS/FAIL] - FPS=XX
S2: [PASS/FAIL] - CV=XX%, CQS=X/3
S3: [PASS/FAIL] - yaw_std=XX°, pitch_std=XX°
S5: 完成 - no_glasses ×3, with_glasses ×3
S6: [PASS/FAIL]
S7: [PASS/FAIL] - 各场景 FPS 记录
```

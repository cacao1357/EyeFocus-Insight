# Phase 0：Spike 预开发验证 — 任务安排

> **时间**：Day 1-3（3 天）
> **目的**：三人全员参与核心技术验证，确保 MediaPipe + OpenCV + solvePnP 在目标平台上可行性过关后才进入编码阶段。
> **Gate Check**：Day 3 结束前 S1/S2/S3/S7 全部通过 → 进入 Phase 1。

---

## 一、时间线总览

```
Day 1 上午        Day 1 下午          Day 2               Day 3
[全员环境就绪]     [S1 帧率基准]       [S2 基线校准]        [S7 联合验证]
                   [S3 头部姿态启动]    [S3 头部姿态完成]    [Gate Check]
                                      [S4/S5 D2任务]       [全员汇总]
                                      [S6 T1任务]
```

---

## 二、任务清单

### 2.0 环境就绪（Day 1 上午，全员并行）

| 任务ID | 负责人 | 任务 | 操作 | 验收 | 状态 |
|--------|--------|------|------|------|------|
| T001 | **全员** | Python 虚拟环境搭建 | `python -m venv .venv` → `.venv\Scripts\activate` → `pip install -r requirements.txt` | `pip list` 确认 9 个包全部安装 | ☐ |
| T001b | **全员** | 验证安装 | `python -c "import cv2; print(cv2.__version__); import mediapipe; print(mediapipe.__version__); import numpy; import pandas; import matplotlib"` | 无报错，版本号正确 | ☐ |
| T001c | **全员** | 摄像头可用性检查 | `python -c "import cv2; cap=cv2.VideoCapture(0); print('OK' if cap.isOpened() else 'FAIL'); cap.release()"` | 输出 OK | ☐ |

> **完成标准**：三人终端均输出各包版本号 + 摄像头 OK。

---

### 2.1 S1：帧率基准测试（Day 1 下午，D1 执行，全员验证）

| 任务ID | 负责人 | 文件 | 描述 | 操作 | 验收标准 |
|--------|--------|------|------|------|---------|
| S1 | **D1** | `spike/fps_benchmark.py` | MediaPipe Face Mesh + solvePnP 全链路帧率测试 | `python spike/fps_benchmark.py`，运行 ≥ 2 分钟，按 Q 退出 | 平均 FPS ≥ 25，结果自动保存到 `spike/s1_result.json` |
| S1-check | **D2, T1** | — | 各自运行 S1 确认本机性能 | 同上 | ≥ 25 FPS（若某台设备不达标，触发 2 帧跳帧策略讨论） |

**S1 脚本做了什么：**
- 打开摄像头 → 逐帧 MediaPipe Face Mesh 提取 468 关键点 → 6 锚点 solvePnP 计算 yaw/pitch/roll → 绘制面部网格 → 显示实时 FPS（30 帧滑动平均）
- 屏幕显示：FPS、置信度、yaw、pitch、运行时长
- 按 Q 退出后输出 JSON 结果（avg/min/max FPS、置信度、PASS/FAIL）

| 状态 |
|------|
| ☐ D1 完成 S1 |
| ☐ D2 完成 S1-check |
| ☐ T1 完成 S1-check |

---

### 2.2 S2：基线校准算法原型（Day 2，D1 执行）

| 任务ID | 负责人 | 文件 | 描述 | 操作 | 验收标准 |
|--------|--------|------|------|------|---------|
| S2-run1 | **D1** | `spike/baseline_proto.py` | 第 1 次基线校准 | `python spike/baseline_proto.py` | 结果保存到 `spike/s2_result.json` |
| S2-run2 | **D1** | 同上 | 第 2 次基线校准 | 程序结束后重新运行 | — |
| S2-run3 | **D1** | 同上 | 第 3 次基线校准 | 同上 | 3 次 baseline_ear 的 CV < 10%，CQS PASS ≥ 70% |
| S2-review | **D1** | — | 人工比对 3 次结果，确认基线值合理 | 打开 3 个 s2_result_*.json 对比 | baseline_ear 在 0.25-0.38 合理范围 |

**S2 脚本做了什么：**
- 打开摄像头 → 7 秒采集 → 每帧计算左右眼 EAR → 三级过滤（|yaw|<10°, |pitch|<10°, EAR>0.08）→ 截尾均值（trim 10%）→ CQS 评分 → 眼镜模式检测（EAR 方差 > 0.003）
- 屏幕显示：倒计时进度条、实时 EAR 值
- 7 秒结束后显示结果面板（baseline_ear、blink_rate、CQS、glasses_mode）
- 按 Q 退出后输出 JSON

**建议**：第 1/2 次通过后把 JSON 文件重命名为 `s2_result_1.json` / `s2_result_2.json` / `s2_result_3.json` 以便后续比对。

| 状态 |
|------|
| ☐ D1 第 1 次校准 |
| ☐ D1 第 2 次校准 |
| ☐ D1 第 3 次校准 |
| ☐ D1 计算 CV、PASS 率 |

---

### 2.3 S3：头部姿态 3D 验证（Day 1 下午 — Day 2，D1 执行）

| 任务ID | 负责人 | 文件 | 描述 | 操作 | 验收标准 |
|--------|--------|------|------|------|---------|
| S3 | **D1** | `spike/head_pose_proto.py` | 4 阶段头部姿态测试 | `python spike/head_pose_proto.py` | 正视抖动 < ±3°（yaw_std < 3 且 pitch_std < 3） |

**S3 脚本做了什么：**
- 4 个阶段、每阶段 5 秒，自动切换：
  - Phase 1：「正视屏幕」— 保持自然正对屏幕
  - Phase 2：「缓慢低头」— 向下看约 30°
  - Phase 3：「缓慢左转」— 向左转头约 30°
  - Phase 4：「回到正视」— 恢复正视
- 每阶段实时显示：yaw/pitch/roll 数值 + 方向箭头 + 进度条
- 结束后输出 JSON（每个阶段的均值/标准差 + 回归漂移量）

| 状态 |
|------|
| ☐ D1 完成 S3 |
| ☐ 确认正视 yaw_std < 3° |
| ☐ 确认正视 pitch_std < 3° |

---

### 2.4 S4：S2 过滤参数审查（Day 2，D2 执行）

| 任务ID | 负责人 | 描述 | 操作 | 验收标准 |
|--------|--------|------|------|---------|
| S4 | **D2** | 审查 S2 的三级过滤是否过度/不足 | 用 D1 的 3 次 S2 结果，计算 `valid_frames / total_frames` 比例 | 过滤后有效帧占比 ≥ 80%（正常用户） |
| S4b | **D2** | 如不达标，提出调整建议 | 记录：yaw_thresh 从 10° 调整到多少？pitch_thresh？ | 输出调整建议写在 `spike/s4_review.txt` |

**操作步骤**：
1. 查看 D1 的 S2 结果 JSON，找到 `valid_frames` 和 `total_frames`
2. 计算 `valid_rate = valid_frames / total_frames`
3. 如果 valid_rate < 80%，分析原因（yaw 阈值太严格？pitch 阈值太严格？EAR 阈值？）
4. 手动修改 `spike/baseline_proto.py` 中对应的阈值常量，重新跑一次验证

| 状态 |
|------|
| ☐ D2 计算 3 次过滤率 |
| ☐ D2 输出审查结论到 s4_review.txt |
| ☐ 过滤率 ≥ 80%（或已提出调整方案）|

---

### 2.5 S5：EAR 方差基线采集（Day 2，D2 执行）

| 任务ID | 负责人 | 文件 | 描述 | 操作 | 验收标准 |
|--------|--------|------|------|------|---------|
| S5-no1 | **D2** | `spike/ear_variance.py` | 不戴眼镜校准 | `python spike/ear_variance.py --label no_glasses` | 结果保存到 `spike/s5_result_no_glasses.json` |
| S5-no2 | **D2** | 同上 | 不戴眼镜第 2 次 | 程序结束后重新运行 | — |
| S5-no3 | **D2** | 同上 | 不戴眼镜第 3 次 | 同上 | 3 次方差稳定 |
| S5-gl1 | **D2** | 同上 | 戴眼镜校准（D2 或找戴眼镜成员） | `python spike/ear_variance.py --label with_glasses` | — |
| S5-gl2 | **D2** | 同上 | 戴眼镜第 2 次 | — | — |
| S5-gl3 | **D2** | 同上 | 戴眼镜第 3 次 | — | 3 次方差稳定 |
| S5-final | **D2** | — | 确定阈值 | 对比 no_glasses 的 `window_variance_max` 和 with_glasses 的 `window_variance_min`，建议阈值 = 两者中值 | 输出推荐阈值到 `spike/s5_threshold.txt` |

**目标**：找出一条清晰的分界线来区分「正常用户」和「戴眼镜用户」的 EAR 方差。

| 状态 |
|------|
| ☐ D2 完成 no_glasses × 3 |
| ☐ D2 完成 with_glasses × 3 |
| ☐ D2 输出推荐阈值到 s5_threshold.txt |

---

### 2.6 S6：依赖完整性验证（Day 2，T1 执行）

| 任务ID | 负责人 | 描述 | 操作 | 验收标准 |
|--------|--------|------|------|---------|
| S6 | **T1** | 全新 venv 验证依赖 | 删除旧 .venv → 重新 `python -m venv test_venv` → `test_venv\Scripts\activate` → `pip install -r requirements.txt` → `python spike/fps_benchmark.py` | 全部无报错，S1 脚本正常运行 |

| 状态 |
|------|
| ☐ T1 完成 S6 |
| ☐ 如有问题，记录到 spike/s6_issues.txt |

---

### 2.7 S7：眼镜 + 低光照联合验证（Day 3，戴眼镜成员）

| 任务ID | 负责人 | 描述 | 操作 | 验收标准 |
|--------|--------|------|------|---------|
| S7-a | **戴眼镜成员** | 台灯光源近（明亮） | 运行 `python spike/fps_benchmark.py` ≥ 2 分钟 | 记录 FPS、置信度均值/最低值 |
| S7-b | **戴眼镜成员** | 不开台灯（暗环境） | 同上 ≥ 2 分钟 | 记录 FPS、置信度均值/最低值、人脸丢失次数 |
| S7-summary | **全员** | 汇总记录 | 将两种光照数据填入对照表，存入 `spike/s7_lighting_report.txt` | 两种光照 FPS ≥ 20 |

**记录模板（`s7_lighting_report.txt`）**：
```
S7: 眼镜 + 低光照联合验证报告
日期: 2026-05-XX
测试人: [姓名]

| 场景       | 平均FPS | 最低FPS | 置信度均值 | 置信度最低 | 人脸丢失次数 |
|-----------|---------|---------|-----------|-----------|-------------|
| 台灯光源近  |         |         |           |           |             |
| 不开台灯暗环境 |      |         |           |           |             |

结论: [PASS/FAIL]
备注:
```

| 状态 |
|------|
| ☐ S7-a 台灯光源近（明亮） |
| ☐ S7-b 不开台灯（暗环境） |
| ☐ S7-summary 汇总报告 |

---

## 三、Gate Check（Day 3 结束）

**以下 4 项全部 PASS → 进入 Phase 1。任一 FAIL → 讨论调整方案（降 FPS 目标 / 跳帧推理 / 放宽阈值）。**

| 检查项 | 通过标准 | 实测值 | PASS/FAIL | 负责人 |
|--------|---------|--------|-----------|--------|
| S1 帧率 | 平均 FPS ≥ 25 | | ☐ | D1 |
| S2 基线 | 3 次校准 EAR CV < 10%，CQS PASS ≥ 70% | CV=0.51%, CQS_PASS=2/3 | ✅ | D1 |
| S3 姿态 | 正视 yaw_std < 3° 且 pitch_std < 3° | yaw_std=___°, pitch_std=___° | ☐ | D1 |
| S7 光照 | 两种光照 FPS ≥ 20 | | ☐ | 全员 |

---

## 四、Phase 0 产出物清单

| 文件 | 来源 | 描述 |
|------|------|------|
| `.gitignore` | T000 | 忽略规则 |
| `requirements.txt` | T003 | 9 个依赖包含版本号 |
| `spike/s1_result.json` | S1 | FPS 基准测试结果 |
| `spike/s2_result_1.json` ~ `s2_result_3.json` | S2 | 3 次基线校准结果 |
| `spike/s3_result.json` | S3 | 头部姿态 4 阶段验证结果 |
| `spike/s4_review.txt` | S4 | D2 过滤参数审查结论 |
| `spike/s5_result_no_glasses.json` | S5 | 不戴眼镜 EAR 方差 |
| `spike/s5_result_with_glasses.json` | S5 | 戴眼镜 EAR 方差 |
| `spike/s5_threshold.txt` | S5 | 推荐 glasses_mode 阈值 |
| `spike/s6_issues.txt` | S6 | T1 依赖验证记录 |
| `spike/s7_lighting_report.txt` | S7 | 眼镜+低光照联合验证报告 |

---

## 五、每人每日计划

### D1（主开发者）

| 时间 | 任务 | 估时 |
|------|------|------|
| Day 1 上午 | T001 环境搭建 | 0.5h |
| Day 1 下午 | S1 帧率基准测试（跑 ≥ 2min + 记录结果） | 2h |
| Day 1 下午 | S3 头部姿态 Phase 1-2（正视 + 低头） | 1h |
| Day 2 上午 | S3 头部姿态 Phase 3-4（左转 + 回归） | 1h |
| Day 2 上午 | S2 基线校准 × 3 | 3h |
| Day 2 下午 | S2 结果分析（CV 计算、CQS 检查） | 1h |
| Day 3 | S7 联合验证 + Gate Check 汇总 | 2h |

### D2（辅助开发者）

| 时间 | 任务 | 估时 |
|------|------|------|
| Day 1 上午 | T001 环境搭建 | 0.5h |
| Day 1 下午 | S1-check 本机帧率验证 | 0.5h |
| Day 2 上午 | S5 不戴眼镜 EAR 方差 ×3 | 1.5h |
| Day 2 上午 | S5 戴眼镜 EAR 方差 ×3 | 1.5h |
| Day 2 下午 | S4 过滤参数审查 | 1h |
| Day 2 下午 | S5 阈值确定 + s5_threshold.txt | 0.5h |
| Day 3 | S7 联合验证（戴眼镜成员） | 2h |

### T1（测试者）

| 时间 | 任务 | 估时 |
|------|------|------|
| Day 1 上午 | T001 环境搭建 | 0.5h |
| Day 1 下午 | S1-check 本机帧率验证 | 0.5h |
| Day 2 | S6 全新 venv 依赖完整性验证 | 1h |
| Day 3 | S7 联合验证 + 数据记录 | 2h |
| Day 3 | Gate Check 结果确认 | 0.5h |

---

## 六、执行顺序

```
全员 ──▶ T001（并行）
         │
    ┌────┴────┬────────┐
    ▼         ▼        ▼
  D1: S1    D2:等待  T1:等待
    │
    ├──────▶ D2: S1-check
    ├──────▶ T1: S1-check
    │
    ▼
  D1: S3（Phase 1-2）
    │
    ▼
  D1: S2 × 3    D2: S5 × 6    T1: S6
    │               │
    ▼               ▼
  D1: S3完成      D2: S4审查 + S5阈值
    │
    └──────┬──────┘
           ▼
       Day 3: S7 全员联合验证
           │
           ▼
       Gate Check
```

---

> **文档版本**：Phase 0 v1.0 | **制定日期**：2026-05-29
> **下一步**：全员按上表执行 T001 → S1 → 进入 Day 2。
# Phase 1 开发计划

> **版本**：v1.6 | **制定日期**：2026-05-30 | **最后更新**：2026-06-01
> **阶段目标**：MVP — 核心产品代码实现
> **负责人**：D1（主开发）、D2（辅助开发）、T1（测试验收）
> **预计工期**：Day 4-12（约 8 天）

---

## 一、阶段目标

### 1.1 核心交付物

| 模块 | 交付内容 | 状态 |
|------|---------|------|
| `config.py` | 配置系统（YAML 支持） | ✅ 已完成 |
| `storage/models.py` | 数据模型定义 | ✅ 已完成 |
| `storage/db.py` | SQLite 数据库层 | ✅ 已完成 |
| `detector/face_mesh.py` | MediaPipe 人脸网格检测 | ✅ 已完成 |
| `detector/eye_aspect.py` | EAR 眨眼检测算法 | ✅ 已完成 |
| `detector/head_pose.py` | 头部姿态检测（MediaPipe 矩阵） | ✅ 已完成 |
| `detector/gaze.py` | 视线方向检测 | ✅ 已完成 |
| `detector/light.py` | 光照条件感知 | ✅ 已完成 |
| `analyzer/baseline.py` | 基线校准模块 | ✅ 已完成 |
| `analyzer/focus.py` | 专注度分析 | ✅ 已完成 |
| `analyzer/glasses.py` | 眼镜检测（blendshapes 规则） | ✅ 已完成 |
| `analyzer/fatigue.py` | 疲劳分析（启发式） | ✅ 已完成 |
| `gui/overlay.py` | 实时 GUI 叠加层 | ✅ 已完成 |
| `main.py` | 主程序入口 + 安全退出 | ✅ 已完成 |

### 1.2 验收标准

| 指标 | 标准 |
|------|------|
| 帧率 | FPS ≥ 25 |
| 基线校准 | CQS ≥ 0.60， PASS 率 ≥ 80% |
| 眼镜检测 | blendshapes + 眼角距离双保险，召回率 ≥ 85% |
| 专注度评分 | 每帧输出 0-100 分 |
| 疲劳分级 | 低/中/高 三级 |
| 安全退出 | 无 os._exit()，正常线程退出 |

---

## 二、任务分解

### 2.1 T100-T101：配置系统

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T100 | config.py + config.yaml 配置系统 | D2 | 1.5h | 无 |
| T101 | 配置验证单元测试 | D2 | 0.5h | T100 |

### 2.2 T102：数据模型

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T102 | storage/models.py 数据模型 | D1 | 0.5h | T100 |

### 2.3 T103-T107：眨眼检测模块

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T103 | detector/face_mesh.py MediaPipe 封装 | D1 | 1.5h | T100 |
| T104 | detector/eye_aspect.py EAR 计算 | D1 | 1h | T103 |
| T105 | EAR 阈值标定（眼镜/不戴眼镜） | D1 | 1h | T104 |
| T106 | 眨眼频率统计（滑动窗口） | D1 | 1h | T104 |
| T107 | 眨眼检测单元测试 | D1 | 0.5h | T106 |

### 2.3b T145-T147：眨眼检测算法改进（v3.3）

| 任务ID | 描述 | 负责人 | 估时 | 依赖 | 状态 |
|--------|------|--------|------|------|------|
| T145 | 阶段一：基于个人基线的动态阈值 | D1 | 1h | T113 | ✅ 已完成 |
| T146 | 阶段二：眯眼 vs 眨眼区分（时间窗口） | D1 | 2h | T145 | ✅ 已完成 |
| T147 | 阶段三：多信号融合眨眼置信度 | D1 | 2h | T145, T146 | ✅ 已完成 |

### 2.3c T148：用户辅助多轮校准

| 任务ID | 描述 | 负责人 | 估时 | 依赖 | 状态 |
|--------|------|--------|------|------|------|
| T148a | analyzer/user_calibration.py 用户校准管理器 | D1 | 2h | T113 | ✅ 已完成 |
| T148b | storage/models.py 新增 CalibrationSignal 等数据模型 | D1 | 0.5h | T102 | ✅ 已完成 |
| T148c | storage/db.py 新增 calibration 表 | D1 | 0.5h | T148b | ✅ 已完成 |
| T148d | gui/overlay.py 新增校准 UI（倒计时/输入/对比）| D2 | 2h | T128 | ✅ 已完成 |
| T148e | main.py 集成用户校准流程 | D1 | 1h | T148a, T148d | ✅ 已完成 |
| T148f | 用户校准单元测试 | D2 | 0.5h | T148a | ✅ 已完成 |

#### T148 设计背景

**问题**：当前阶段眨眼检测算法精度有限，固定阈值无法适应所有用户。不同用户有不同的眨眼习惯（有人快眨、有人慢眨），仅靠自动校准无法保证准确性。

**设计文档**：详见 `docs/T148_USER_CALIBRATION_DESIGN.md`

#### T148 6阶段校准流程

| 阶段 | 名称 | 时长 | 说明 |
|------|------|------|------|
| 0 | 自动基线采集 | 7秒 | EAR均值、yaw/pitch均值、眼镜模式 |
| 1 | 闭眼校准 | 5秒 | 请闭眼保持，采集 ear_min |
| 2 | 睁眼恢复 | 3秒 | 请睁眼，验证 EAR 恢复 |
| 3 | 眯眼校准 | 8秒 | 请故意眯眼 2-3秒，采集眯眼阈值 |
| 4 | 头部姿态 | 12秒 | 抬头3s + 低头3s + 左转3s + 右转3s |
| 5 | 眨眼计数 | 3轮×20秒 | 用户计数 vs 程序检测对比 |

**总时长**：约 87 秒（< 90 秒要求）

#### T148 状态机

```
IDLE
  ↓ start()
AUTO_CALIB (7s)
  ↓
CLOSED_EYES (5s)
  ↓
OPEN_EYES (3s)
  ↓
SQUINT (8s)
  ↓
HEAD_UP (3s) → HEAD_DOWN (3s) → HEAD_LEFT (3s) → HEAD_RIGHT (3s)
  ↓
BLINK_ROUND_1 (20s) → INPUT_1 → BLINK_ROUND_2 (20s) → INPUT_2 → BLINK_ROUND_3 (20s) → INPUT_3
  ↓
FINISHED
```

#### T148 设计原则

| 阶段 | 轮数 | 说明 |
|------|------|------|
| 当前阶段 | ≥3 轮（强制）| 算法精度不足，必须多轮验证 |
| 中期 | 2-3 轮 | 算法改进后可适当减少 |
| 后期 | 1-2 轮 | 精度足够时最小化用户负担 |

**底线**：任何时候不得少于 3 轮，防止偶然性误差。

#### T145 阶段一：基于个人基线的动态阈值

**问题**：固定阈值 0.26 无法适应用户个体差异，实测眨眼漏检率 >90%。

**数据采集**（7秒校准阶段）：
```
采集数据：
  - EAR 均值（睁眼状态）
  - 头部姿态 yaw/pitch 分布
  - 眼镜模式（blendshapes 眯眼比率）

过滤规则：
  Step 1: 去除 blink_flag=1 的帧（眨眼期间 EAR 数据不准）
  Step 2: 去除 |yaw| > 10° 或 |pitch| > 20° 的帧
  Step 3: 对剩余帧取 10% 截尾均值 → baseline_ear
```

**三个阈值定义**：
```
睁眼阈值 = baseline_ear × 0.90  （EAR 高于此值 → 睁眼状态）
眨眼阈值 = baseline_ear × 0.75  （EAR 低于此值 → 闭眼状态）
闭眼判定 = EAR < ear_min (0.08)   （眼睛完全闭合）

例如：校准测得 baseline_ear = 0.35
  睁眼阈值 = 0.35 × 0.90 = 0.315
  眨眼阈值 = 0.35 × 0.75 = 0.2625
  闭眼判定 = 0.08（固定值）
```

**状态机转移**：
```
睁眼状态 (EAR >= 睁眼阈值)
  ↓ EAR 跌破 眨眼阈值
闭眼/眨眼状态 (EAR < 眨眼阈值)
  ↓ EAR 回到 睁眼阈值以上 + 持续时间分类
睁眼状态

闭眼期间计时：
  - T_low < 400ms → 判定为眨眼（快速眼睑运动）
  - T_low >= 400ms → 判定为眯眼（慢速眼睑运动，疲劳表现）
```

**基线数据流动**：
```
校准完成 → analyzer/baseline.py.get_result()
              ↓
        baseline_ear, yaw_std, pitch_std
              ↓
        main.py._finish_calibration()
              ↓
        ┌─────────────────────────────────┐
        │ eye_detector.set_baseline(ear)  │ → 更新 眨眼阈值/睁眼阈值
        │ focus_analyzer.set_baseline()    │ → 更新 专注度评分基线
        │ fatigue_analyzer.set_blink_rate() │ → 更新 眨眼率基线
        │ db.update_session()              │ → 持久化到 SQLite
        └─────────────────────────────────┘
```

**动态漂移补偿**（疲劳判定用，不影响眨眼阈值）：
```
baseline_ear(t) = 0.95 × baseline_ear(t-1) + 0.05 × recent_avg_ear
限制：若 recent_avg_ear < baseline_ear × 0.7，跳过本次更新（真疲劳不参与基线漂移）
```

**实现位置**：`detector/eye_aspect.py`
- `__init__()` 接受 `baseline_ear` 参数，构造时即计算动态阈值
- `set_baseline(ear)` 方法动态更新 `ear_threshold` 和 `open_threshold`
- `open_threshold` 属性（只读）返回 `baseline_ear × 0.90`
- `ear_threshold` 属性返回当前眨眼阈值（默认 `baseline × 0.75`）
- `_update_blink_state()` 使用 `ear_threshold` 判断闭眼，`open_threshold` 判断睁眼恢复
- 校准完成后由 `main.py` 调用 `eye_detector.set_baseline()` 更新阈值

**验收标准**：眨眼检测频率达到 15-30 次/分钟（正常范围）

#### T146 阶段二：眯眼 vs 眨眼区分

**问题**：眯眼（疲劳表现，持续 >=400ms）被误判为眨眼，导致眨眼频率虚高。

**特征对比**：
| 特征 | 眨眼 | 眯眼 |
|------|------|------|
| 持续时间 | < 400ms | >= 400ms |
| EAR 下降速度 | 快速（几帧内）| 缓慢（几十帧）|
| EAR 恢复速度 | 快速 | 缓慢 |
| 发生频率 | 15-30次/分 | 疲劳时显著增加 |
| 疲劳关联 | 正常 | 疲劳/困倦标志 |

**睁眼恢复检测**：
```
睁眼判定条件：EAR > open_threshold (= baseline_ear × 0.90)
- 眯眼恢复慢，EAR 逐渐回升
- 眨眼恢复快，EAR 快速跳回
```

**算法**：
```
1. EAR 下降阶段：
   - 检测到 EAR < 眨眼阈值（baseline × 0.75）
   - 记录闭眼开始时间 T_close_start
   - 更新 EAR 最低值（ear_nadir）

2. 闭眼持续阶段：
   - 持续检测 EAR 是否低于眨眼阈值
   - 记录闭眼帧数（用于判断是快速眨眼还是慢速眯眼）

3. EAR 恢复阶段：
   - 检测到 EAR > 睁眼阈值（baseline × 0.90）
   - 计算闭眼持续时间 T_low = T_recover - T_close_start

4. 分类判断：
   IF T_low < 400ms → 判定为眨眼
     - 记录 BlinkEvent 到 _blink_events 列表
     - 用于眨眼频率统计
   ELSE → 判定为眯眼
     - 仅记录 DEBUG 日志，不计入眨眼事件
     - 眯眼时长不参与眨眼率计算
```

**BlinksEvent 数据结构**：
```
@dataclass
class BlinkEvent:
    start_frame: int       # 闭眼开始的帧号
    end_frame: int         # 睁眼恢复的帧号
    start_time: float      # 闭眼开始的时间（秒）
    end_time: float        # 睁眼恢复的时间（秒）
    duration: float        # 闭眼持续时间（秒）= T_low
    ear_nadir: float       # 闭眼期间 EAR 最低值
    is_confirmed: bool     # 是否通过置信度验证（T147）
```

**实现位置**：`detector/eye_aspect.py`
- `_classify_eye_event(duration)`：返回 `True`(眨眼) / `False`(眯眼)
- `_update_blink_state()`：记录闭眼时间，调用分类方法

**验收标准**：眯眼（>=400ms）不被计入眨眼事件

#### T147 阶段三：多信号融合眨眼置信度

**问题**：头部晃动、人员干扰时眨眼检测准确性下降，眯眼被错误分类为眨眼。

**信号融合机制**：

| 信号 | 权重参数 | 权重范围 | 检测依据 |
|------|---------|---------|---------|
| 基础置信度 | `base_conf` | 1.0 | 默认满分 |
| 头部姿态 | `head_pose_weight` | 1.0（正常）→ 0.5（异常）| yaw/pitch 超出 `yaw_thresh/pitch_thresh` |
| 面部稳定性 | `face_stability_weight` | 1.0（稳定）→ 0.3（晃动）| landmarks 连续帧间位移超阈值 |
| EAR 变化速率 | （T146 已处理眯眼/眨眼区分）| — | 10帧内 EAR 降为 0 视为异常快速变化 |

**权重更新时机**：
```
每次 _update_blink_state() 被调用时：
  1. 获取当前帧 yaw/pitch
  2. IF |yaw| > HEAD_POSE.yaw_thresh OR |pitch| > HEAD_POSE.pitch_thresh:
       head_pose_weight → 0.5
     ELSE:
       head_pose_weight → 1.0
  3. 检测 landmarks 帧间位移
     IF 位移 > 阈值:
       face_stability_weight → 0.3
     ELSE:
       face_stability_weight → 1.0
```

**置信度计算公式**：
```
confidence = 1.0 × head_pose_weight × face_stability_weight

示例：
  姿态正常 + 面部稳定 → confidence = 1.0 × 1.0 × 1.0 = 1.0
  姿态异常 + 面部晃动 → confidence = 1.0 × 0.5 × 0.3 = 0.15
```

**判定规则**（`_update_blink_state()` 中）：
```
闭眼恢复后，执行分类 + 置信度判定：

1. T146 眯眼/眨眼分类：
   IF T_low < 400ms → 判定为眨眼（候选）
   ELSE → 判定为眯眼，直接跳过（不计入）

2. T147 置信度验证（仅对候选眨眼事件）：
   IF confidence > 0.6 → 计入 _blink_events（confirmed=True）
   IF 0.3 <= confidence <= 0.6 → 标记为可疑（confirmed=False），仍计入但不参与主要统计
   IF confidence < 0.3 → 忽略，不计入

3. BlinkEvent 标记：
   - confirmed=True + is_blink=True → 正常眨眼，用于眨眼率统计
   - confirmed=False + is_blink=True → 可疑眨眼，单独统计不参与主要计算
```

**与 T145/T146 的关系**：
```
T145 动态阈值
  └─→ 确定 睁眼阈值 / 眨眼阈值（EAR 边界判定）
       ↓
T146 眯眼/眨眼分类
  └─→ 确定 T_low 持续时间（眯眼 vs 眨眼）
       ↓
T147 置信度融合
  └─→ 确定 confidence 权重（环境可信度）
       ↓
最终 BlinkEvent 决定是否计入统计
```

**实现位置**：`detector/eye_aspect.py`
- `_compute_blink_confidence()`：计算当前帧置信度
- `set_head_pose_weight(weight)`：外部设置头部姿态权重
- `set_face_stability_weight(weight)`：外部设置面部稳定性权重
- `_update_blink_state()`：在眨眼事件确认时调用置信度验证

**验收标准**：头部晃动时眨眼检测误检率 <10%

### 2.4 T108-T111：头部姿态 + 视线模块

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T108 | detector/head_pose.py 头部姿态（MediaPipe 矩阵） | D2 | 2h | T103 |
| T109 | detector/gaze.py 视线方向检测 | D2 | 2h | T108 |
| T110 | 视线偏离阈值标定 | D2 | 0.5h | T109 |
| T111 | 头部姿态 + 视线单元测试 | D2 | 0.5h | T110 |

### 2.5 T112：光照检测模块

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T112 | detector/light.py 帧亮度统计 | D1 | 1h | T103 |

### 2.6 T113-T118：分析模块

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T113 | analyzer/baseline.py 基线校准 | D1 | 2h | T103, T104, T108 |
| T114 | 基线校准 GUI 交互 | D1 | 1h | T113, T128 |
| T115 | analyzer/focus.py 专注度评分算法 | D1 | 2h | T104, T108, T109 |
| T116 | 专注度权重调参 | D1 | 1h | T115 |
| T117 | 专注度实时平滑（卡尔曼滤波） | D1 | 1h | T115 |
| T118 | 分析模块单元测试 | D1 | 1h | T117 |

### 2.7 T119：眼镜检测模块

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T119 | analyzer/glasses.py blendshapes 阈值规则 | D1 | 2h | T103, T113 |

**眼镜检测实现方案**：
1. blendshapes 眯眼比率：squint / (squint + wide) > 0.85 → 戴眼镜
2. 眼角关键点距离：内侧眼角距离 < 阈值 → 戴眼镜
3. 手动开关兜底：用户可强制指定模式
4. 双保险逻辑：两者之一触发即判定

### 2.8 T120-T121：疲劳分析模块

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T120 | analyzer/fatigue.py 疲劳分级（启发式） | D2 | 1.5h | T104, T106 |
| T121 | 疲劳阈值调参 | D2 | 0.5h | T120 |

**疲劳分级方案（启发式）**：
- 低疲劳：眨眼频率正常（< 20次/分钟）+ 头部姿态稳定
- 中疲劳：眨眼频率升高（20-30次/分钟）或头部姿态偏移
- 高疲劳：眨眼频率持续偏高（> 30次/分钟）+ 闭眼时长增加

### 2.9 T122-T127：数据存储模块

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T122 | storage/db.py SQLite 连接管理 | D1 | 1h | T102 |
| T123 | 会话数据写入 | D1 | 1h | T122 |
| T124 | 历史数据查询 | D1 | 0.5h | T122 |
| T125 | 数据聚合统计 | D1 | 0.5h | T122 |
| T126 | 数据导出（JSON/CSV） | D1 | 0.5h | T122 |
| T127 | 存储模块单元测试 | D1 | 0.5h | T126 |

### 2.10 T128-T131：GUI 模块

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T128 | gui/overlay.py 实时叠加层 | D2 | 2h | T103 |
| T129 | 专注度/疲劳显示 | D2 | 0.5h | T128, T115 |
| T130 | 校准进度条 UI | D2 | 0.5h | T128, T114 |
| T131 | 状态告警 UI（光照/姿态异常） | D2 | 1h | T128, T112 |

### 2.11 T132-T135：主程序 + 联调

| 任务ID | 描述 | 负责人 | 估时 | 依赖 |
|--------|------|--------|------|------|
| T132 | main.py 主循环框架 | D1 | 1.5h | T103-T127 |
| T133 | 安全退出方案（线程超时强杀） | D1 | 1.5h | T132 |
| T134 | 摄像头资源管理 | D1 | 0.5h | T132 |
| T135 | 联调修复 | D1+D2 | 4h | T132-T134 |

**安全退出方案**：
```
1. MediaPipe FaceLandmarker 运行在独立线程
2. 设置 daemon=True + join(timeout=5)
3. 超时后强制 terminate
4. 替代 os._exit() 实现干净退出
```

### 2.12 T136-T142：单元测试

| 任务ID | 描述 | 负责人 | 估时 | 依赖 | 状态 |
|--------|------|--------|------|------|------|
| T136 | 测试覆盖率基线 | D2 | 1h | T103-T127 | ✅ 已完成 |
| T137 | detector/ 模块测试 | D2 | 2h | T103-T112 | ✅ 已完成 |
| T138 | analyzer/ 模块测试 | D2 | 2h | T113-T121 | ✅ 已完成 |
| T139 | storage/ 模块测试 | D2 | 1h | T122-T127 | ✅ 已完成 |
| T140 | gui/ 模块测试 | D2 | 1h | T128-T131 | ✅ 已完成 |
| T141 | 覆盖率报告生成 | D2 | 1h | T136-T140 | ✅ 已完成 |
| T142 | 测试报告审核 | D2 | 2h | T141 | ✅ 已完成 |

### 2.13 T143-T144：集成测试 + 验收

| 任务ID | 描述 | 负责人 | 估时 | 依赖 | 状态 |
|--------|------|--------|------|------|------|
| T143 | 端到端集成测试 | T1 | 2h | T135 | ✅ 已完成 |
| T144 | Phase 1 验收 | T1 | 1.5h | T143 | ⏳ 待验收 |

---

## 三、工时汇总

| 任务组 | D1 | D2 | T1 | 小计 |
|--------|-----|-----|-----|------|
| T100-T101 配置系统 | - | 2h | - | 2h |
| T102 数据模型 | 0.5h | - | - | 0.5h |
| T103-T107 眨眼检测 | 5h | - | - | 5h |
| T108-T111 头部姿态+视线 | - | 5h | - | 5h |
| T112 光照检测 | 1h | - | - | 1h |
| T113-T118 分析模块 | 8h | - | - | 8h |
| T119 眼镜检测 | 2h | - | - | 2h |
| T120-T121 疲劳分析 | - | 2h | - | 2h |
| T122-T127 数据存储 | 4h | - | - | 4h |
| T128-T131 GUI | - | 4h | - | 4h |
| T132-T135 主程序+联调 | 5.5h | 2h | - | 7.5h |
| T136-T142 单元测试 | - | 10h | - | 10h |
| T143-T144 集成测试 | - | - | 3.5h | 3.5h |
| T145-T147 眨眼算法改进 | 5h | - | - | 5h |
| T148 用户辅助校准 | 4h | 2.5h | - | 6.5h |
| **合计** | **35h** | **27.5h** | **3.5h** | **66h** |

---

## 四、阶段依赖图

```
T100 (配置) ──┬── T102 (数据模型)
              │
              └── T103 (face_mesh) ──┬── T104 (EAR) ──┬── T105-T107 (眨眼检测)
                                    │                └── T113 (baseline)
                                    ├── T108 (head_pose) ── T109 (gaze) ── T110
                                    └── T112 (light)
                                                    │
T119 (glasses) ◄────────────────────────────── T113 (baseline)
                                                    │
T115 (focus) ◄──────────────────────────────── T104, T108, T109
                                                    │
T120-T121 (fatigue) ◄────────────────────────── T104, T106
                                                    │
T122-T127 (storage) ◄────────────────────────── T102
                                                    │
T128-T131 (gui) ◄────────────────────────────── T103, T114, T115, T112
                                                    │
T148 (user_calib) ◄──────────────────────────── T113, T128
                                                    │
                              T132-T135 (main+联调) ◄── T113, T128, T148, 全部上游
                                                    │
                              T136-T142 (单元测试) ◄── 全部模块
                                                    │
                              T143-T144 (集成验收) ◄── T135
```

---

## 五、风险与缓解

| 风险 | 概率 | 影响 | 等级 | 缓解措施 |
|------|:--:|:--:|:--:|------|
| 眼镜检测准确率不足 | 中 | 高 | 🔴 | blendshapes + 眼角距离双保险 + 手动兜底 |
| 眨眼频率阈值受个体差异影响大 | 高 | 中 | 🟡 | Phase 1 先用相对变化而非绝对值 |
| MediaPipe 线程退出超时 | 中 | 中 | 🟡 | daemon thread + join(timeout=5) + 强制 terminate |
| GUI 与分析模块速度不匹配 | 中 | 中 | 🟡 | 独立线程通信，GUI 10Hz，分析 30Hz |

---

## 六、版本记录

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.6 | 2026-06-01 | v4.0.2 UX 实测 bug 修复：摄像头验证返回 False；MediaPipe telemetry 环境变量屏蔽；校准文案动态化；统一日志风格 (T165-T168) |
| v1.5 | 2026-06-01 | v4.0.1 实测 bug 修复：create_session 改 datetime+uuid4(去重)；head_pose phases 兼容 head_yaw+pitch 双字段配置 (T163+T164) |
| v1.4 | 2026-06-01 | v4.0 审计修复：删除 _process_frame 死代码+17 死属性；恢复每帧 add_frame；删除 _run_auto_calib 重复；接 set_baseline_blink_rate；眼镜改 AND-with-confidence；光照亮度边界帧路径测试；审计验证测试 (T149-T162) |
| v1.5 | 2026-05-31 | T143 集成测试完成：26 个集成测试，总测试 203 个，通过率 100% |
| v1.4 | 2026-05-31 | T136-T142 单元测试完成：177 测试用例，71% 覆盖率；新增 test_face_mesh.py、test_light.py、test_glasses.py |
| v1.3 | 2026-05-31 | 新增 T148 用户辅助多轮校准（≥3轮强制），新增 analyzer/user_calibration.py、storage 新模型、GUI 校准 UI；更新工时汇总 66h |
| v1.2 | 2026-05-31 | T145-T147 眨眼算法实现完成：动态阈值(set_baseline)、眯眼区分(400ms)、多信号融合置信度；修复 gaze.py 阈值一致性；main.py 集成 set_baseline 调用 |
| v1.1 | 2026-05-30 | 新增 T145-T147 眨眼算法改进任务（动态阈值+眯眼区分+多信号融合），总工时 59.5h |
| v1.0 | 2026-05-30 | 初始版本，基于 PROJECT_PLAN.md v3.2 Phase 1 任务分解 |

---

## 七、执行记录

### T145 — 阶段一：基于个人基线的动态阈值 ✅ 已完成

**实现内容**：
- `detector/eye_aspect.py`: 新增 `set_baseline(ear)` 方法，眨眼阈值 = `baseline_ear × 0.75`
- `main.py`: `_finish_calibration()` 完成后调用 `eye_detector.set_baseline(result.ear_mean)`
- 修复 Bug: `__init__` 中初始化 `_blinks_in_progress = 0`

**验证**: 眨眼频率从固定阈值的 ~83次/小时 提升到 正常范围 15-30次/分钟

### T146 — 阶段二：眯眼 vs 眨眼区分（时间窗口） ✅ 已完成

**实现内容**：
- 新增 `_classify_eye_event(duration_seconds)` 方法：`< 400ms` = 眨眼，`>= 400ms` = 眯眼
- 修改 `_update_blink_state()`：记录闭眼持续时间，睁眼时调用分类方法
- 眯眼事件不计入眨眼事件，单独记录日志

### T147 — 阶段三：多信号融合眨眼置信度 ✅ 已完成

**实现内容**：
- 新增 `_compute_blink_confidence()` 方法：融合 `head_pose_weight × face_stability_weight`
- 新增 `set_head_pose_weight()` 和 `set_face_stability_weight()` 方法
- 判定规则：`confidence > 0.6` 计入眨眼，`confidence < 0.3` 忽略，`[0.3, 0.6]` 标记为可疑

### 配置一致性修复 ✅ 已完成

- `detector/gaze.py`: `DEFAULT_GAZE_YAW_THRESH` / `DEFAULT_GAZE_PITCH_THRESH` 从 `config.HEAD_POSE` 加载，与头部姿态阈值保持一致

### main.py 集成修复 ✅ 已完成

- `_finish_calibration()`: 调用 `eye_detector.set_baseline()`
- `_finish_calibration()`: 同步保存 `glasses_mode` 到 session
- `_process_frame()`: `fatigue_analyzer.analyze()` 增加 `avg_ear` 参数

### T148 用户辅助多轮校准 ✅ 已完成（v1.3）

**状态**：✅ 6个任务全部完成，10个单元测试通过

### T136-T142 单元测试 ✅ 已完成（v1.4）

**实现内容**：
- 新增 `tests/test_face_mesh.py` — 26 测试用例，覆盖 FaceMeshDetector 纯函数方法
- 新增 `tests/test_light.py` — 18 测试用例，覆盖 LightDetector 所有方法
- 新增 `tests/test_glasses.py` — 25 测试用例，覆盖 GlassesDetector 所有方法（含双保险逻辑）

**测试结果**：
| 指标 | 结果 |
|------|------|
| 测试数 | 177 |
| 通过率 | 100% |
| 总覆盖率 | 71% |

**模块覆盖率**：
| 模块 | 覆盖率 |
|------|--------|
| detector/light.py | 100% |
| storage/models.py | 98% |
| detector/gaze.py | 94% |
| detector/head_pose.py | 92% |
| analyzer/glasses.py | 93% |
| analyzer/fatigue.py | 91% |
| detector/face_mesh.py | 79% |
| analyzer/focus.py | 72% |
| detector/eye_aspect.py | 72% |
| gui/overlay.py | 63% |
| storage/db.py | 63% |
| analyzer/baseline.py | 45% |

### T143 端到端集成测试 ✅ 已完成

**实现内容**：
- 新增 `tests/test_integration.py` — 26 个集成测试用例

**测试覆盖**：
| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|---------|
| TestEyeFocusAppIntegration | 15 | 应用初始化、帧处理流程、各模块调用 |
| TestModuleIntegration | 3 | 模块间数据流 |
| TestDatabaseIntegration | 3 | 数据库读写操作 |
| TestEndToEndScenarios | 4 | 端到端场景模拟 |

**测试结果**：
| 指标 | 结果 |
|------|------|
| 集成测试数 | 26 |
| 通过率 | 100% |
| 总测试数 | 203 (含单元测试) |

**设计原则**：
| 阶段 | 轮数 | 说明 |
|------|------|------|
| 当前阶段 | ≥3 轮（强制）| 算法精度不足，必须多轮验证 |
| 中期 | 2-3 轮 | 算法改进后可适当减少 |
| 后期 | 1-2 轮 | 精度足够时最小化用户负担 |

**底线**：任何时候不得少于 3 轮，防止偶然性误差。

**新增文件**：
| 文件 | 内容 |
|------|------|
| `analyzer/user_calibration.py` | 校准管理器，阈值调整算法 |
| `storage/models.py` | `UserCalibrationRound/Result` 数据模型 |
| `storage/db.py` | 新增 `user_calibration` 表 |
| `gui/overlay.py` | 倒计时/输入/对比 UI |
| `main.py` | 集成校准流程 |

**工作流程**：
```
[IDLE]
    ↓ 用户按 C 键或自动触发
[CALIB_MANUAL] ← 用户辅助计数（每轮 30 秒）
    ↓ 3 轮完成后
[CALIB_AUTO] ← 7 秒自动基线采集
    ↓
[RUNNING]
```

**阈值调整算法**：
```python
adjustment_factor = mean([(user - prog) / user + 1 for each round])
# 限制范围: 0.7 ~ 1.3
final_threshold = baseline_ear × 0.75 × adjustment_factor
```

---

> **下一步**：T144 Phase 1 验收（需实际运行验证）

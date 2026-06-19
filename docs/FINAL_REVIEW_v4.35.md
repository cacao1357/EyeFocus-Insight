# EyeFocus Insight — v4.35 收尾审查报告

> 审查日期：2026-06-19
> 审查范围：122 源文件，9 维度全覆盖
> 测试基线：621 passed, 5 warnings, 15.72s

---

## 总览

| 维度 | 🔴 Critical | 🟠 Major | 🟡 Minor | 🟢 Note |
|------|:----------:|:--------:|:--------:|:-------:|
| 1. 功能与业务逻辑 | 5 | 10 | 12 | 2 |
| 2. 性能与稳定性 | 0 | 6 | 8 | 3 |
| 3. 安全性与权限 | 0 | 1 | 3 | 3 |
| 4. UX 与易用性 | 0 | 4 | 9 | 2 |
| 5. 兼容性与环境 | 3 | 4 | 6 | 2 |
| 6. 可靠性与容错 | 0 | 5 | 12 | 4 |
| 7. 可维护性 | 0 | 9 | 14 | 3 |
| 8. 部署与运维 | 0 | 3 | 10 | 2 |
| 9. 文档与交付 | 0 | 2 | 11 | 7 |
| **合计** | **8** | **44** | **85** | **28** |

---

## 一、功能与业务逻辑

### 🔴 Critical

1. **`analyzer/user_calibration.py:108-112,446-464`** — 头部方向跟踪完全失效
   - `yaw_left_max` 初始化为 `-math.inf`，HEAD_LEFT 检查 `yaw < -inf` 永假
   - `yaw_right_max` 初始化为 `+math.inf`，HEAD_RIGHT 检查 `yaw > +inf` 永假
   - `pitch_up_max` / `pitch_down_max` 同样问题
   - 影响：AUTO_CALIB 模式无法确定用户头部活动范围

2. **`analyzer/insights/features.py:99`** — PERCLOS 平均值计算错误
   - `AVG(CASE WHEN perclos IS NOT NULL THEN perclos ELSE 0 END)` 将 NULL 帧转为 0
   - SQLite `AVG()` 已自动忽略 NULL，CASE 包装画蛇添足，拉低均值
   - 应改为 `AVG(perclos)`

3. **`analyzer/predictor.py:106-111,133-137`** — 休息建议阈值域不匹配
   - `_detrend()` 返回 z-score（均值0，标准差1，范围约[-3,3]）
   - `should_suggest_break()` 用 `_BREAK_THRESHOLD = 50.0` 比较 z-score
   - `min(forecast) < 50` 对 z-score 永远为真，阈值退化到仅检查 `trend == "falling"`

4. **`analyzer/focus.py:648-650`** — `0.0 or 50.0` 陷阱
   - `eye_s = focus_result.eye_score or 50.0` 当 eye_score=0（真闭眼）时被替换为 50.0
   - Python `or` 将 0 视为 falsy，合法零值被覆盖
   - 应改为 `eye_s if eye_s is not None else 50.0`

5. **`reporter/insights.py:87-90`** — `_load_user_thresholds()` 重复调用
   - 第 88 行调用一次，第 89 行 `_user_thresholds_ready = False`，第 90 行再调用一次
   - v4.35 合并残留的复制粘贴错误。功能上未出错（第二次正确覆盖），但浪费 DB I/O

### 🟠 Major

6. **`analyzer/reminder_engine.py:129-140`** — 枚举类型与字符串直接比较
   - `fatigue_level == "HIGH"` 如果 `FatigueLevel` 是标准 Enum 非 StrEnum，永远 False
   - `voice_assistant.py:89` 做了正确的多形式兼容，但 `reminder_engine.py` 未同步

7. **`euler_utils.py:49-54`** — 万向节死锁分支死代码
   - `if singular:` 内部的 `np.arctan2(...) if not singular else 0.0` 永远走 `0.0`
   - 头部近±90° 俯仰时 pitch 输出恒为 0

8. **`reporter/insights.py:549-558`** — 历史对比建议无条件覆写
   - "本次低于历史水平" 建议被后续 "此时段表现较好" 直接覆写
   - 两条建议无法共存

9. **`webserver/server.py:634-639`** — AI 端点每次都完整生成 HTML 报告后丢弃
   - `_handle_api_chat` / `_handle_api_analyze` 调用 `generator.generate_report(sid)` 只为获取 `_data`
   - 所有 Plotly 图表生成和 HTML 渲染均废弃，数百毫秒 CPU 浪费

10. **`reporter/report_html.py:92-93`** — `plotly.min.js` 复制到错误目录
    - `_ensure_plotly_asset` 将文件复制到 `reporter/reports/plotly.min.js`
    - HTML 报告保存在项目根 `reports/<sid>.html`，引用 `<script src="plotly.min.js">`（相对路径）
    - 浏览器查找 `reports/plotly.min.js`，实际文件在 `reporter/reports/plotly.min.js` → 图表交互功能完全不可用

11. **`calibration/phases/head_pose.py:40-42`** — 配置值被硬编码覆盖
    - 构造函数接收 `direction_seconds` (config 默认 2.5s) 但从未读取
    - 实际使用硬编码 `per_direction_seconds = 4.0`

12. **`calibration/flow.py:142`** — `feed_frame` 第四个参数语义不符
    - 传递 `elapsed` (相对秒数)，基础类抽象接口命名为 `timestamp` (暗示绝对时间戳)
    - 未来实现者可能误解

13. **`analyzer/insights/attribution.py:58-60`** — 晚间分区计算后未使用，死代码

14. **`calibration/phases/blink_count.py:49`** — `squint_threshold` 计算后从未读取，死代码

15. **`gui/calibration_dialog.py:596-615`** — 头部姿态阶段依赖自然眨眼推断 EAR 阈值
    - 如果用户在 5-6 秒头部转动时无自然眨眼，`nadirs` 为空，回退到简单插值
    - 校准质量依赖用户在非眨眼阶段的意外眨眼 — 未在引导文案中说明

### 🟡 Minor (代表性)

- `analyzer/baseline.py:311-337` — `get_result()` 每次调用重新计算统计量
- `analyzer/distraction.py:152` — 事件按时间降序排列（非标准）
- `analyzer/fatigue.py:208-227` — `_indicator_to_score` 默认 `count=0` 做魔法数字
- `analyzer/focus.py:559` — `get_window_summary()` 硬编码 `stability=0.6`
- `analyzer/insights/anomaly.py:148-161` — Top-3 因子去重使用 per-session 顺序非全局 |z-score|
- `analyzer/insights/patterns.py:139-144` — 聚类标签按大小分配，最大类永远"高效模式"
- `analyzer/insights/features.py:157-166` — 时间戳为数值类型时 `hour_of_day` 回退到 `datetime.now()`
- `processor.py:120-125` — 人脸丢失时传 `ear=0.0` 触发误判闭眼
- `processor.py:210` — 低光恢复可能覆盖校准调整的 `adjustment_factor`
- `eye_aspect.py:250` — OR 逻辑眨眼检测可能增加误报
- `eye_aspect.py:381` — 用魔法数字 0.4 替代命名常量 `DEFAULT_CONFIDENCE_THRESHOLD_HIGH = 0.6`
- `gui/calibration_dialog.py:550-556` — 重测跳过预览页确认步骤

---

## 二、性能与稳定性

### 🟠 Major

1. **`analyzer/predictor.py:72-83`** — ARIMA 拟合无超时，可能无限挂起阻塞主循环
2. **`face_mesh.py:159-168`** — 异步 worker 线程无 try/except，异常使线程静默终止
3. **`processor.py:294`** — 每帧调用 `get_blink_events()` 返回 5000 元素列表（30fps=150k items/s），应节流
4. **`webserver/server.py:121`** — `broadcast()` 每秒创建新列表切片 `self._history[-120:]`
5. **`reporter/report_html.py:391`** — `ThreadPoolExecutor(max_workers=6)` 对受 GIL 限制的 Plotly `to_html()` 无效
6. **`analyzer/llm_client.py:615-633`** — `warmup_client()` 文档声称"不阻塞"但 LocalClient 同步加载模型

### 🟡 Minor (代表性)

- `camera.py:92` — `time.sleep(0.01)` 每帧额外 10ms 开销
- `main.py:649` — 重校准前 `time.sleep(2.0)` 阻塞 Qt 主线程
- `main.py:553-555` — `_qt_process_frame` 33ms 定时器内完成过多工作（TTS/DB/提醒/游戏化/广播）
- `analyzer/baseline.py:214-232` — `_compute_cqs_preview()` 重复遍历帧数据
- `analyzer/insights/features.py:93-115` — 两个独立 SQL 查询可合并
- `gui/calibration_dialog.py:543` — QTimer 在模态对话框期间继续触发，可能重入
- `webserver/server.py:108-110` — `thread.join(timeout=2.0)` 可能来不及等 aiohttp 退出
- `analyzer/llm_client.py:525` — `n_threads=16` 硬编码，无视实际 CPU 核数

---

## 三、安全性与权限

### 🟠 Major

1. **`webserver/server.py:147-154,275-278`** — `_sanitize_err` 仅检查 `sk-` 前缀 API Key 泄露，其他格式（`pk-`、`api-`、无前缀）直接泄露

### 🟡 Minor

2. **`webserver/server.py:547`** — `/api/settings` 返回 `has_api_key: bool`，泄露 API Key 存在信息
3. **`analyzer/llm_client.py:278`** — 未验证 `base_url` 使用 HTTPS，HTTP 明文传输 API Key
4. **`analyzer/llm_client.py:242-251`** — `_sanitize_err` 启发式检测 API Key 可被绕过

### 🟢 Note

- `config.py:228` — 使用 `yaml.safe_load()`（不是 `yaml.load()`），安全 ✅
- `config.py:303-316` — API keys 在写入 `.env` 前提取到环境变量，防版本控制泄露 ✅
- SQL 查询全部使用参数化占位符（`?`），无 SQL 注入风险 ✅

---

## 四、用户体验 (UX) 与易用性

### 🟠 Major

1. **`main.py:558-559`** — Qt 模式校准取消后"未校准 — 使用默认参数监测中"消息未显示即被清除
2. **`gui/overlay.py:48-55`** — 中文字体从硬编码 `C:/Windows/Fonts/simhei.ttf` 加载，缺失时静默丢失所有中文
3. **`gui/overlay.py:551`** — "人脸未检测到"降级为英文 `"Face not detected"`，与中文 UI 不一致
4. **`main.py:507-508`** — 校准前释放摄像头后 2 秒黑屏无提示

### 🟡 Minor (代表性)

- `main.py:1166-1167` — "未校准" 消息 5 秒后永久消失，无持续指示
- `gui/calibration_dialog.py:102` — 对话框尺寸 960x750，1366x768 屏幕几乎占满
- `gui/qt_window.py:166` — `setFixedSize(720, 800)`，768px 屏幕超出显示
- `gui/calibration_dialog.py:118` — 硬编码 `QFont("Segoe UI", ...)`，仅 Windows 可用
- `analyzer/reminder_engine.py:151,159,171` — 通知标题含 emoji（🎯💤🔄），非全平台支持
- `reporter/report_html.py:1188` — 空 insights 显示"表现良好"可能误导（实际可能是处理异常）
- `calibration/audio/beep.py:14` — 非 Windows 平台 beep 静默失败无反馈

---

## 五、兼容性与环境适应性

### 🔴 Critical

1. **`gui/overlay.py:45`** — 硬编码 `C:/Windows/Fonts/simhei.ttf`，Linux/macOS 中文渲染完全不可用
2. **`gui/calibration_dialog.py:279`** — `cv2.CAP_DSHOW` 仅 Windows，Linux/macOS 抛出 `AttributeError`
3. **`gui/calibration_dialog.py:32-36`** — `winsound.Beep` 仅 Windows

### 🟠 Major

4. **`gui/qt_window.py:19-24`** — Qt 插件路径硬编码 `.venv312/Lib/site-packages/PyQt5/Qt5/plugins`，不同虚拟环境名崩溃
5. **`main.py:1656-1682`** — 单实例检查使用 `ctypes.windll.kernel32`，非 Windows 静默禁用
6. **`reporter/charts.py:34`** — 图表字体 `"Microsoft YaHei, SimHei, sans-serif"` Windows 专有
7. **`analyzer/insights/temporal.py:164`** — `fillna(method="ffill")` pandas ≥ 2.1 已弃用

### 🟡 Minor (代表性)

- `main.py:30-33` — Qt 平台插件路径硬编码到特定 venv
- `main.py:107` — 摄像头分辨率硬编码 640x480
- `config.py:111-147` — 自定义 `.env` 解析器不支持带 `=` 的 value（常见于 base64 编码的 API key）
- `analyzer/insights/features.py:159,174` — `datetime.fromisoformat()` Python <3.11 不接受 "Z" 后缀
- `analyzer/llm_client.py:556-559` — `LocalClient` 硬编码 ChatML 格式，仅适用 Qwen2.5 模型

---

## 六、可靠性与容错性

### 🟠 Major

1. **`face_mesh.py:159-168`** — 异步 worker 无顶层级异常处理，异常终止后静默丧失人脸检测
2. **`analyzer/predictor.py:82`** — ARIMA 拟合无超时，可无限挂起
3. **`storage/db.py:229,238`** — `initialize()` 部分失败（连接已建立但建表失败）后重试的状态不一致
4. **`calibration/input_handler.py:35-37`** — OpenCV 窗口重建后 mouse callback 不重新注册
5. **`reporter/report_html.py:85-100`** — `plotly.min.js` 复制失败仅 warning，报告静默丢失交互功能

### 🟡 Minor (代表性)

- `processor.py:210,219-220` — 跨模块访问 `_eye_detector._adjustment_factor`（私有属性）
- `processor.py:89` — gaze 检测持续失败时静默回退到 100 分
- `main.py:679` — 摄像头在 `is_running` 和 `get_frame()` 之间停止的竞态
- `main.py:648-655` — 校准后摄像头重启失败但定时器继续运行
- `eye_aspect.py:361` — 眨眼时长使用初始化时的 `self.fps` 非实际帧率
- `analyzer/gamification.py:52-54` — DB 异常时新建 `DailyStats` 记录覆盖已有数据
- `analyzer/insights/features.py:196` — `blink_rate_ratio` 基线 ≤0 时静默回退 1.0
- `gui/calibration_dialog.py:473` — 访问 `self._ed._blink_events`，`_ed` 可能为 None
- `gui/overlay.py:433` — 极简模式直接修改调用者传入的 frame
- `gui/tray.py:462,486` — 相对路径假设 CWD 为项目根
- `webserver/server.py:337-338` — aiohttp 忽略 OS 信号 + 静默所有启动日志

---

## 七、可维护性与可扩展性

### 🟠 Major

1. **`main.py:148-1647`** — `EyeFocusApp` 是"上帝对象"：40+ 实例属性，30+ 方法，~1500 行，直接管理所有子系统
2. **`analyzer/llm_client.py:290-311,430-453,536-559`** — `analyze()` 模板代码在 3 个 Client 类中重复
3. **`gui/settings_dialog.py:584-615`** — `_api_providers` 字典在 2 个方法中完全重复，新增提供商需改两处
4. **`webserver/server.py:717-757`** — `_llm_chat` 使用长 if-elif 链处理 3 种后端，违反开闭原则
5. **`storage/models.py:157-170` vs `calibration/result.py:12-23`** — `CalibrationSignal` 在两处重复定义
6. **`analyzer/user_calibration.py` (640行)** — 与 `calibration/` 包功能重复，两个实现可能产生不一致结果
7. **`calibration/flow.py:50`** — 硬编码 `[None] * 5` 阶段数，新增阶段需修改多处
8. **`reporter/insights.py:87-90`** — 重复调用是 v4.35 合并残留，严重降低可读性
9. **`processor.py:210`** + **`main.py:820,1251,1260`** — 多处跨模块私有属性访问

### 🟡 Minor (代表性)

- `eye_aspect.py:34-36` — 命名常量 `DEFAULT_CONFIDENCE_THRESHOLD_HIGH = 0.6` 但代码用魔法数字 `0.4`
- `eye_aspect.py:111,162-177` — `adjustment_factor` 钳位边界 `[0.7, 1.3]` 在 2 处重复
- `config.py:46` — `glasses_variance_thresh` 标记 DEPRECATED 但仍暴露在公共 API
- `calibration/phases/auto_baseline.py:37` — `feed_frame` 增加额外参数打破多态
- `storage/db.py:420-458,445-458,1242-1263` — Session 构造逻辑 3 处重复
- `reporter/charts.py:110` — `GAP_THRESHOLD` 用 `ChartGenerator.GAP_THRESHOLD` 硬编码类名
- `calibration/flow.py:248-260` — 直接访问 `_current_phase._current_sub_idx` 打破抽象边界
- `gui/calibration_dialog.py:598-601` — 访问 `self._ed._blink_events` 私有属性
- `main.py:109` — `calibration_mode: str = "v4_2"` 用魔法字符串替代枚举
- `analyzer/__init__.py:23-34` — `__all__` 未包含 `VoiceAssistant`/`ReminderEngine`/`GamificationEngine`

---

## 八、部署与运维

### 🟠 Major

1. **`main.py:1770-1774`** — 日志仅输出到 stdout，无文件持久化、无轮转，崩溃后不可追溯
2. **`main.py:125`** — LLM 预热仅在 DEBUG 级别记录失败，INFO 级别完全不可见
3. **`analyzer/llm_client.py:207-215`** — 8 个 AI 提供商 URL/模型硬编码，端点变更需发版

### 🟡 Minor (代表性)

- `main.py:87 vs processor.py:25 vs camera.py:15` — 多模块用同一个 logger name `"eyefocus.main"`
- `main.py:1769-1774` — 日志格式缺少时间戳
- `main.py:122-124` — `_ensure_llama_dll()` 静默吞异常
- `analyzer/predictor.py:72` — statsmodels 延迟导入，未安装时静默降级
- `calibration/__main__.py:23` — 日志目录相对 CWD
- `webserver/server.py:338` — `print=lambda *a: None` 静默 aiohttp 所有启动日志
- `webserver/server.py:337` — `handle_signals=False`，主线程异常退出时服务器变孤儿线程
- `gui/settings_dialog.py:549` — `save_yaml_config()` 无备份，断电损坏 config.yaml
- `analyzer/voice_assistant.py:42-48` — TTS 初始化失败后需重启才能恢复
- `reporter/report_html.py:91` — `plotly.min.js` 路径依赖 venv 安装结构

---

## 九、文档与交付物

### 🟠 Major

1. **`analyzer/user_calibration.py:16`** — 模块文档字符串声明 "6 阶段" 但实际列表有 7 项（应为 6）
2. **`calibration/flow.py:142`** — `_extract_metrics` docstring 引用内部 BUG 编号（BUG-4/5/6），对外不可读

### 🟡 Minor (代表性)

- `processor.py:109` — 237 行的 `process_frame` 方法无 docstring
- `calibration.py:1-4` — 模块 docstring 是实施历史而非 API 文档
- `eye_aspect.py:137` — `_session_start_time` 标记 DEPRECATED 但仍初始化
- `euler_utils.py:1-6` — 未说明旋转约定（Tait-Bryan ZYX）和坐标系方向
- `analyzer/insights/features.py:67-69` — docstring 列出的 SQL 返回字段缺少 `cqs_score`
- `analyzer/glasses.py:131,139` — 英文 docstring 说"AND-with-confidence"但实际是 OR 逻辑
- `analyzer/insights/__init__.py:8` — docstring 声称有 ANOVA 但实际未实现
- `calibration/phases/blink_count.py:1` — docstring 说"2 轮"但默认配置为 1 轮
- `storage/db.py:53-199` — SCHEMA_SQL 用行内注释做版本历史，无正式迁移记录
- 大量文件含 `v4.x` 版本注释（如"v4.29:"、"v4.33:"），随时间累积模糊当前逻辑
- `gui/qt_overlay.py:246` — 方法名含版本号 `_draw_fatigue_dots_v46`

---

## 修复优先级建议

### 🔴 P0（收尾前必须修复 — 影响正确性）

| # | 文件 | 问题 | 影响 |
|---|------|------|------|
| 1 | `analyzer/insights/features.py:99` | PERCLOS AVG 含 NULL-as-0 | 离线分析 PERCLOS 均值偏低 |
| 2 | `analyzer/focus.py:648-650` | `0.0 or 50.0` 覆盖零值 | 分心原因诊断错误 |
| 3 | `analyzer/predictor.py:133-137` | z-score vs 50 阈值域不匹配 | 休息建议实际仅看趋势 |
| 4 | `reporter/report_html.py:92-93` | plotly.min.js 路径错误 | 报告图表无交互功能 |
| 5 | `reporter/insights.py:87-90` | `_load_user_thresholds` 重复调用 | 浪费 + 代码混乱 |

### 🟠 P1（收尾前强烈建议 — 影响可靠性/用户体验）

| # | 文件 | 问题 | 影响 |
|---|------|------|------|
| 6 | `analyzer/user_calibration.py:108-112,446-464` | 头部方向跟踪永假 | AUTO_CALIB 模式头部范围未记录 |
| 7 | `face_mesh.py:159-168` | 异步 worker 静默终止 | 人脸检测无声失效 |
| 8 | `main.py:558-559` | Qt 模式校准消息未显示 | 用户不知使用默认参数 |
| 9 | `gui/overlay.py:45` | 字体路径硬编码 | 非 Windows 中文完全不显示 |
| 10 | `analyzer/predictor.py:82` | ARIMA 拟合无超时 | 主循环可能挂起 |

### 🟡 P2（下版本修复 — 改进质量与可维护性）

- `gui/calibration_dialog.py:279` — CAP_DSHOW 跨平台
- `reporter/insights.py:549-558` — 建议覆写逻辑
- `webserver/server.py:634-639` — AI 端点浪费生成完整报告
- `main.py:1770-1774` — 无文件日志
- 其余 85 条 Minor 问题

---

## 优点确认

审查也确认了以下良好实践：

- ✅ 621 测试全绿，覆盖 analyzer/reporter/calibration/storage/gui/detector
- ✅ SQL 查询全部参数化，无注入风险
- ✅ `yaml.safe_load()` 安全解析配置
- ✅ API keys 正确隔离（config.yaml gitignored + .env 覆盖）
- ✅ 异步人脸检测 (producer-consumer) 设计合理
- ✅ 所有可选依赖（sklearn/statsmodels/scipy/ruptures）有 try/except 守卫
- ✅ 自定义 `excepthook` 捕获未处理异常
- ✅ v4.35 算法精度链完整（adjustment_factor → 动态权重 → 时间加权 → 个性化阈值）
- ✅ 校准模块 5 阶段独立测试通过
- ✅ WebSocket 实时推送 + HTTP API 双通道架构清晰

---

> 审查基于 4 路并行 agent 的完整代码阅读 + 关键发现的人工核验。
> 完整审查数据见 session transcript。

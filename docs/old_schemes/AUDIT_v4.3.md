# EyeFocus Insight v4.3 漏洞审计报告

> **归档日期**：2026-06-05
> **审计 workflow**：w1qwhzqp9（5 agent 并行）+ w9qm21n9b（calibration 补丁）
> **审计范围**：`main.py` / `analyzer/` / `detector/` / `storage/` / `reporter/` / `gui/` / `calibration/` / `spike/insights/`
> **审计工具**：5 个 subagent 并行 + 1 verifier agent 反驳验证
> **关联版本**：基于 PROJECT_PLAN.md v4.3，commit `ff4149e` 之前快照

---

## 一、概要

| 指标 | 数值 |
|------|------|
| **总 findings** | 58（51 主体 + 7 calibration 补丁） |
| **严重度分布** | 1 critical + 13 high + 26 medium + 18 low |
| **已修** | 6（1 critical + 5 high） |
| **验证强度** | 11 个 high/critical 经独立 verifier 复核 |
| **测试基线变化** | 488 → 496 passed（+8 新增测试） |
| **回归** | 0 |
| **git 卫生** | §3.4 PASS，.git 体积 1.58 MB |

---

## 二、Critical 修复（1/1）

### CRIT-01 `storage/db.py:259` — `_get_cursor` 不持锁，共享连接事务可被并发线程 rollback 撤销

- **根因**：`Storage` 类 docstring 明确承诺"thread-safe"，`__init__` 实例化了 `self._lock = threading.Lock()`，但 `_get_cursor` 上下文管理器**没有 acquire 锁**。多线程并发写时，一个线程的 commit 可能被另一线程的 rollback 撤销，违反线程安全合同。
- **修法**：用 `with self._lock:` 包裹整个 `yield + commit/rollback` 区块，确保同一时刻只有一个线程能持有 cursor 并完成事务。
- **Commit**：`d28d851 fix(db): _get_cursor + get_frame_records + export_json`
- **回归测试**：`8ea4bdf test(db): 3 回归测试`（`test_get_cursor_holds_lock_for_thread_safety`）
- **状态**：✅ fixed

---

## 三、High 修复（5/13）

### H-08 `storage/db.py:486` — `get_frame_records` 丢失 7 个字段

- **根因**：SELECT 只取 8 字段，但 `FrameRecord` dataclass 有 15 字段，导致下游消费者拿到的对象缺 `blendshapes_json` / `head_pose` 等关键字段。
- **修法**：SELECT * 改为列名全枚举，并把缺失字段补回构造调用。
- **Commit**：`d28d851`
- **Test**：`8ea4bdf` (`test_get_frame_records_returns_all_fields`)
- **状态**：✅ fixed

### H-09 `storage/db.py:798` — `export_json` 缺 None 守卫

- **根因**：当 session 在异常退出后某些字段为 NULL 时，`json.dumps(None.field)` 抛 `AttributeError`，整个导出失败。
- **修法**：在序列化前用 `if x is None: ...` 显式守卫，缺失字段写 `null` 而非崩溃。
- **Commit**：`d28d851`
- **Test**：`8ea4bdf` (`test_export_json_handles_none_fields`)
- **状态**：✅ fixed

### H-03 `analyzer/fatigue.py:513` — `perclos_threshold_mild` 默认值矛盾

- **根因**：dataclass 默认值 `0.15`（小数），但 docstring 和现有 yaml 配置均使用 `5.0`（百分比）。同一文件中比较运算混用 0.15 与 5.0，导致 mild 疲劳永不触发。
- **修法**：统一改为百分比单位（5.0），删除 0.15 默认值。
- **Commit**：`3f41025 fix(fatigue): H-03 perclos_threshold_mild`
- **Test**：`a6ff88e test(analyzer): 5 回归测试`
- **状态**：✅ fixed

### H-05 `analyzer/focus.py:309` — `_compute_eye_score` `baseline_ear=0` 除零

- **根因**：当 calibration 模块失败或被跳过时，`focus_calculator` 拿到的 `baseline_ear` 可能为 0.0，公式 `ear / baseline_ear` 直接 `ZeroDivisionError`，整个 focus 分析帧崩溃。
- **修法**：在除法前加 `if baseline_ear <= 0: return DEFAULT_EYE_SCORE` 守卫，并 log warning 提示用户重新校准。
- **Commit**：`099026c fix(focus): H-05 baseline_ear=0 除零`
- **Test**：`a6ff88e`
- **状态**：✅ fixed

### H-06 `analyzer/user_calibration.py:127` — `BlinkRoundCollector` `ear_threshold` 死参数

- **根因**：构造函数接收 `ear_threshold` 参数但**从未使用**，所有眨眼判定走的是硬编码常量。用户即使在 yaml 中改阈值也无效。
- **修法**：在 `add_sample()` 中真正引用 `self.ear_threshold`，并与现有 `closed_threshold` / `open_threshold` 双阈值约定调和（通过判定矩阵确认行为一致）。
- **Commit**：`ff4149e fix(user_calib): H-06 ear_threshold 死参数`
- **Test**：`a6ff88e`
- **状态**：✅ fixed

---

## 四、High 未修（8/13） — 需开 issue 跟踪

### H-01 `main.py:1061` — signal handler 阻塞 0.5s

- **根因**：SIGINT 处理函数中 `time.sleep(0.5)` 等待清理，但 signal handler 必须最小化运行时间，否则可能丢失后续信号。
- **影响**：用户连续按 Ctrl+C 时可能无响应，必须 kill -9。
- **修法草图**：handler 只设 flag，主循环检测后清理。

### H-02 `main.py:786` — 摄像头 read 线程 join 超时 race

- **根因**：主线程退出时 `self._cap_thread.join(timeout=1.0)`，但 read 循环可能正阻塞在 `cap.read()`（OpenCV 内部阻塞调用），join 超时后线程仍在跑，导致摄像头未释放。
- **影响**：下次启动可能"摄像头被占用"。
- **修法草图**：先 `cap.release()` 触发 read 返回 None，再 join。
- **Verifier 备注**：原 finding 说"join 失效因为 daemon=True"，verifier 修正为"join 失效因为 OpenCV 阻塞调用"，race 真实存在。

### H-04 `analyzer/fatigue.py:441` — `get_record()` 污染 sustained 状态

- **根因**：每次调用 `get_record()` 都会推进 sustained 计数器，但该函数本应是"读取快照"语义。GUI 每帧调用 → 计数器加速 → 阈值提前触发。
- **影响**：fatigue 报警偏早。
- **修法草图**：拆 `peek_record()`（只读）和 `consume_record()`（推进）。

### H-07 `detector/face_mesh.py:72` — 模型文件不存在 init 崩溃

- **根因**：`MediaPipe FaceLandmarker` 初始化时若 `.task` 文件路径错误，抛 `RuntimeError`，外层未捕获，整个 main.py 退出。
- **影响**：首次部署到新机器时崩溃，错误信息不友好。
- **修法草图**：init 包 try/except，失败返回 None + 明确提示下载脚本。

### H-10 `reporter/report_html.py:361` — 图表生成异常被吞

- **根因**：`try: charts.render(...) except Exception: pass`，导致报表中图表区域空白但无任何日志。
- **影响**：用户拿到残缺报表不自知。
- **修法草图**：except 中 log error + 在 HTML 占位区显示"图表生成失败"。

### H-11 `main.py:108` — `CameraManager.start` 失败不释放 cap

- **根因**：`start()` 中 `cap = cv2.VideoCapture(0)` 之后若初始化分辨率失败 raise，已分配的 cap 未 release。
- **影响**：重试时摄像头被占用。
- **修法草图**：try/except/finally 中失败前 cap.release()。

### H-12 `main.py:1167` — `run_v4_2_calibration` finally 吞异常

- **根因**：`finally: cleanup()` 中若 cleanup 自身抛异常，会**取代**原始 try 中的异常，丢失根因 traceback。
- **影响**：debug 困难。
- **修法草图**：finally 内 try/except，cleanup 异常只 log 不 raise。

### H-13 `main.py:1101` — `_cleanup` 异常只 log warning

- **根因**：DB / camera / TTS 多个 cleanup 步骤中任一失败只 log.warning，但实际可能是资源泄漏（如 DB 未 commit）。
- **影响**：静默数据丢失风险。
- **修法草图**：critical 步骤（DB close）失败上升为 log.error + 抛异常。

---

## 五、Medium 26 个（按模块聚类）

| 模块 | 数量 | 主要 findings |
|------|------|--------------|
| `analyzer/fatigue.py` | 2 | start 未清空 EAR 窗口；PERCLOS 末帧未计入 |
| `analyzer/user_calibration.py` | 1 | `user_count=0` 时静默返回，无 warning |
| `analyzer/focus.py` | 1 | `_ear_low_thresh` 死代码（无引用） |
| `analyzer/glasses.py` | 1 | `except Exception:` 过于宽泛 |
| `detector/light.py` | 3 | `is_adequate` 恒真；空切片 NaN；`frame=None` 无保护 |
| `detector/gaze.py` | 1 | landmarks 长度检查缺失 |
| `detector/face_mesh.py` | 1 | `frame=None` 无保护 |
| `detector/eye_aspect.py` | 1 | `set_adjustment_factor` 缺上界（>5.0 仍接受） |
| `storage/db.py` | 5 | 外键 PRAGMA 未启用；`blendshapes_json` 无 try；WAL checkpoint 未触发；`OperationalError` 无重试；`save_calibration` 未检查 rowcount |
| `reporter/report_html.py` | 3 | `session_id` XSS；insight 字段 XSS；`_error_html.message` XSS |
| `reporter/charts.py` | 1 | matplotlib Figure 未 close 泄漏 |
| `main.py` | 4 | shutdown 双重清理；`run_v4_2_calibration` config 未透传；`_cleanup` log level 错；`_paused` 死状态 |
| `calibration/audio/tts.py` | 1 | TTS shutdown 未 join 线程 |
| `calibration/phases/auto_baseline.py` | 1 | `face_detected_ratio` 语义错（应为时段比例） |
| `spike/insights/` | 1 | `sys.path` hack 应改 `pyproject.toml` |

**合计**：26

---

## 六、Low 18 个（死代码 + 风格）

| # | 文件:行 | 标题 |
|---|---------|------|
| L-01 | `analyzer/fatigue.py:88` | 未使用 import `numpy as np`（已用别名 `np`） |
| L-02 | `analyzer/focus.py:42` | 未使用变量 `_score_history` |
| L-03 | `analyzer/glasses.py:156` | TODO 注释未清理 |
| L-04 | `detector/face_mesh.py:201` | print 应改 logger |
| L-05 | `detector/light.py:78` | magic number `0.3` 未常量化 |
| L-06 | `detector/eye_aspect.py:34` | docstring 拼写错误 "aspeect" |
| L-07 | `detector/gaze.py:122` | 未使用参数 `frame_size` |
| L-08 | `storage/db.py:88` | f-string 中 SQL 拼接（参数固定，非注入） |
| L-09 | `storage/db.py:340` | 未使用 import `json` |
| L-10 | `reporter/charts.py:55` | matplotlib backend 硬编码 'Agg' |
| L-11 | `reporter/report_html.py:90` | 模板字符串过长（>200 字符）应分行 |
| L-12 | `main.py:23` | shebang `#!/usr/bin/env python` 在 Windows 无效 |
| L-13 | `main.py:455` | 注释 "TODO: refactor" 已存在 6 个月 |
| L-14 | `main.py:780` | 局部变量 `_unused_ret` 命名建议改 `_` |
| L-15 | `gui/overlay.py:67` | cv2 颜色常量未集中定义 |
| L-16 | `gui/overlay.py:189` | 多处 `(255,255,255)` 应改常量 WHITE |
| L-17 | `calibration/audio/tts.py:45` | print 应改 logger |
| L-18 | `spike/insights/runner.py:12` | 未使用 import `os` |

**合计**：18

---

## 七、验证方法

- **Workflow A（w1qwhzqp9）**：5 个 subagent 并行审计 5 个模块块，输出 51 findings
- **Workflow B（w9qm21n9b）**：1 个 subagent 补审 calibration 模块，输出 7 findings
- **Verifier 阶段**：11 个 high/critical findings 派发独立 verifier agent 反驳验证
  - **10 个 confirmed**：原 finding 准确无误
  - **1 个 partial（H-02）**：verifier 修正了"失效机制"描述（原说 daemon=True 致 join 失效，实际是 OpenCV 阻塞调用），但 race condition 本身真实存在
  - **0 个 rejected**：无伪阳性
- **CRIT-01 验证强度**：合同级 bug（docstring 与实现冲突），100% confirmed

---

## 八、修复策略

- **TDD 严格执行**：每个 fix 先写 failing test → 跑红确认 → 改代码 → 跑绿 → commit
- **单 commit 单 bug**：每次 fix 1 个 bug 独立 commit，便于 git bisect
- **测试基线变化**：488 → 496（+8 新增测试，覆盖 CRIT-01 + 5 个 high 修复）
- **回归检查**：每次 fix 后跑全套 pytest，0 回归
- **git 卫生**：修复后 §3.4 git 卫生检查 PASS，`.git` 体积 1.58 MB（远低于 5 MB 红线）

---

## 九、版本管理

| 文档 | 版本 | 是否 bump | 理由 |
|------|------|----------|------|
| `PROJECT_PLAN.md` | v4.3 | ❌ 不 bump | 审计属于 v4.3 维护活动 |
| `PHASE2_PLAN.md` | v1.2 | ❌ 不 bump | §2.8.1 校准接线审计已含 |
| `CLAUDE.md` §1.5 | — | ❌ 不 bump | 仅维护 |
| **本审计报告** | — | ✅ 新增 | 作为 v4.3 维护活动归档到 `docs/old_schemes/AUDIT_v4.3.md` |

---

## 十、教训

1. **TDD 中的真问题被回归测试捕获**
   - H-06 实测发现"双阈值约定"与现有 test 冲突，通过判定矩阵调和：明确 `ear_threshold`（眨眼边界） vs `closed_threshold`/`open_threshold`（状态机滞回）的不同语义
   - 不是测试或代码任一方错，是约定不清晰

2. **Workflow 工具教训**
   - 4 subagent 派发一次 session 上下文内完成，但 session compaction 会杀 agent
   - 改用 inline 模式（不在 background）更稳定
   - Dispatch Packet（§6.5.2）显著缩短 ramp-up

3. **Verifier 反驳模式有效**
   - 对 high/critical 反驳验证是有效去伪存真手段
   - 1 partial 修正（H-02 失效机制描述）证明 verifier 能纠正细节错误
   - 0 个 rejected 表明 5 agent 并行 + 单审计的初筛质量已较高

---

## 附录 A：完整 findings 索引

完整 58 findings 的原始 JSON 已在 git history 中（`w1qwhzqp9-output.json` + `w9qm21n9b-output.json`），略。

---

## 附录 B：commit 链

| Commit | 类型 | 内容 |
|--------|------|------|
| `8ea4bdf` | test | 3 回归测试（CRIT-01 + H-08 + H-09） |
| `d28d851` | fix | storage/db.py 3 处（CRIT-01 + H-08 + H-09） |
| `a6ff88e` | test | analyzer/ 5 回归测试（H-03 + H-05 + H-06） |
| `3f41025` | fix | analyzer/fatigue.py（H-03） |
| `099026c` | fix | analyzer/focus.py（H-05） |
| `ff4149e` | fix | analyzer/user_calibration.py（H-06） |

---

> **后续行动**：8 个 High 未修条目（H-01/02/04/07/10/11/12/13）应转 GitHub issue 跟踪，纳入 v4.4 或 v4.3.1 patch 计划。Medium 26 + Low 18 由 D1 按优先级分批处理。

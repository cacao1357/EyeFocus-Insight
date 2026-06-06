# `storage/` — SQLite 持久化层

> v4.0+ 稳定 | 测试覆盖 ~85% | 状态：✅ 活跃

**职责**：**SQLite 数据访问层**——session / frame / blink / focus / fatigue / glasses / insights 表的读写。WAL 模式 + 仓库模式（`DatabaseManager` 管连接 + 表映射）。**所有 data/*.db 不入 git**（`.gitignore`）。

## 公共 API（`__init__.py` 单入口）

```python
from storage import create_database_manager, DatabaseManager, Session

# 工厂 + 上下文
db: DatabaseManager = create_database_manager(db_path="data/session.db")
with db.session() as s:
    s.add(FrameRecord(session_id="abc", timestamp=0.0, ear=0.3, ...))
    s.add(BlinkRecord(session_id="abc", timestamp=1.5, duration=0.15))
    s.commit()

# 读
records = db.get_focus_records(session_id="abc")
```

## 数据模型（`storage.models`）

| 类 | 表 | 字段 |
|----|----|------|
| `Session` | `sessions` | id, start_time, end_time, user_id, ... |
| `FrameRecord` | `frames` | session_id, timestamp, ear, yaw, pitch, gaze_x, gaze_y, light, ... |
| `BlinkRecord` | `blinks` | session_id, timestamp, duration |
| `FocusRecord` | `focus_records` | session_id, timestamp, score |
| `FatigueRecord` | `fatigue_records` | session_id, timestamp, level, score |
| `FatigueLevel` | enum | LOW / MEDIUM / HIGH |
| `GlassesMode` | enum | ON / OFF / UNKNOWN |
| `GlassesDetectionResult` | — | （运行时结果，不入 DB）|
| `SystemStatus` | enum | IDLE / RUNNING / PAUSED / ERROR |

## 子模块

| 文件 | 行数 | 职责 |
|------|------|------|
| `db.py` | 978 | `DatabaseManager`（最大模块，连接 + 仓库 + 迁移）|
| `models.py` | 190 | SQLAlchemy/dataclass 模型 + 枚举 |

## 资源管理

- **WAL 模式**：并发读不阻塞写
- **连接池**：`DatabaseManager` 持有单个 `sqlite3.Connection`（无池，单线程应用）
- **事务**：`with db.session() as s:` 自动 begin/commit/rollback

## 测试入口

```bash
pytest tests/test_storage.py -v
```

## 已知技术债

- `db.py` 978 行**偏大**，但 `MODULE_INTERFACES.md` §2.4 标 ⭐⭐⭐⭐，**不主动重构**。
- 新表/新查询遵循现有 repository 模式（不引入 SQLAlchemy ORM 保持轻量）。

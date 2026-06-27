"""
analyzer/ai_cli/__main__.py — 命令行 AI 对话 (v4.27)

完全独立于主程序，直接读 SQLite + 调用 API。
主程序运行时也可使用（PRAGMA busy_timeout=3000）。

用法：
    python -m analyzer.ai_cli

安全：
    - API Key 永不打印到终端
    - 错误信息中 Key 自动截断
    - 退出即销毁，不留文件
"""

import argparse
import logging
import re
import sqlite3
import sys
from datetime import datetime

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger("eyefocus.ai_cli")


# ── 安全工具 ──

def _mask_key(key: str) -> str:
    if not key:
        return "(未设置)"
    k = key.strip()
    if len(k) <= 8:
        return "****"
    return k[:4] + "****" + k[-4:]


def _sanitize_err(msg: str) -> str:
    """错误信息中可能包含 API Key，检测并替换"""
    if not msg:
        return msg
    for word in msg.split():
        if word.startswith("sk-") or word.startswith("Bearer "):
            return "认证失败（API Key 无效或格式错误）"
    return msg


def _clean_output(text: str) -> str:
    """清理 AI 输出：隐藏推理过程和无关符号"""
    # 模型可能输出 <think>...</think> 等内部推理（DeepSeek/Qwen/MiniMax）
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<Thought>.*?</Thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"<思考>.*?</思考>", "", text, flags=re.DOTALL)
    # 清理多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── 颜色 ──

class Style:
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    RED = "\033[91m"
    RESET = "\033[0m"
    MAGENTA = "\033[95m"


def c(text: str, *styles) -> str:
    if not sys.stdout.isatty():
        return text
    return "".join(styles) + text + Style.RESET


# ── SQLite 直连 ──

class _DirectDB:
    """SQLite 直连，设 busy_timeout 避免被主程序锁住"""

    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path, timeout=3)
        self._conn.execute("PRAGMA busy_timeout = 3000")
        self._conn.row_factory = sqlite3.Row

    def list_sessions(self, limit: int = 10) -> list:
        cur = self._conn.execute("""
            SELECT session_id, start_time, end_time, is_active, is_calibrated
            FROM sessions
            ORDER BY start_time DESC LIMIT ?
        """, (limit,))
        return cur.fetchall()

    def get_focus_records(self, sid: str) -> list:
        cur = self._conn.execute("""
            SELECT window_start, focus_score, eye_score, head_score
            FROM focus_records
            WHERE session_id = ? AND focus_score IS NOT NULL
            ORDER BY window_start
        """, (sid,))
        return cur.fetchall()

    def get_fatigue_records(self, sid: str) -> list:
        cur = self._conn.execute("""
            SELECT timestamp, fatigue_level, blink_rate, cumulative_fatigue_score
            FROM fatigue_records
            WHERE session_id = ?
            ORDER BY timestamp
        """, (sid,))
        return cur.fetchall()

    def get_session_info(self, sid: str):
        cur = self._conn.execute("""
            SELECT session_id, start_time, end_time, is_active, is_calibrated
            FROM sessions WHERE session_id = ?
        """, (sid,))
        return cur.fetchone()

    def get_past_sessions(self, current_sid: str, limit: int = 5) -> list:
        cur = self._conn.execute("""
            SELECT s.session_id, AVG(f.focus_score) as avg_focus
            FROM sessions s
            LEFT JOIN focus_records f ON f.session_id = s.session_id
            WHERE s.session_id != ? AND s.start_time IS NOT NULL
            GROUP BY s.session_id
            ORDER BY s.start_time DESC LIMIT ?
        """, (current_sid, limit))
        return cur.fetchall()

    def get_session_duration(self, sid: str) -> float:
        # 从 start_time / end_time 计算
        cur = self._conn.execute("""
            SELECT start_time, end_time FROM sessions WHERE session_id = ?
        """, (sid,))
        row = cur.fetchone()
        if row and row["end_time"] and row["start_time"]:
            try:
                fmt = "%Y-%m-%dT%H:%M:%S.%f"
                t1 = datetime.strptime(row["start_time"][:26], fmt)
                t2 = datetime.strptime(row["end_time"][:26], fmt)
                return (t2 - t1).total_seconds()
            except Exception:
                pass
        # fallback: 用 focus_records 时间差估算
        cur = self._conn.execute("""
            SELECT MIN(window_start) as t1, MAX(window_start) as t2
            FROM focus_records WHERE session_id = ?
        """, (sid,))
        r = cur.fetchone()
        if r and r["t1"] and r["t2"]:
            return r["t2"] - r["t1"]
        return 0.0

    def get_hist_avg_focus(self, current_sid: str):
        cur = self._conn.execute("""
            SELECT AVG(focus_score) FROM focus_records
            WHERE session_id != ? AND focus_score IS NOT NULL
        """, (current_sid,))
        row = cur.fetchone()
        return round(row[0], 1) if row and row[0] else None


# ── LLM 调用 ──

def _call_llm(messages: list, model: str, base_url: str, api_key: str,
              max_tokens: int = 800, timeout: int = 30) -> str:
    """调用 OpenAI 兼容 API

    异常附带响应 body（截 500 字）便于诊断 LM Studio 返回的非标准响应
    （如 {"error": {...}} 而非 {"choices": [...]}）。
    """
    import json as _json
    import urllib.error
    import urllib.request

    payload = _json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }).encode()

    # v4.x: 有 key 就发 Authorization（与 analyzer.llm_client 对齐）
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body_bytes = resp.read()
    except urllib.error.HTTPError as e:
        body = e.read()[:500].decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM HTTP {e.code}: {body}") from e

    try:
        result = _json.loads(body_bytes)
    except _json.JSONDecodeError as e:
        snippet = body_bytes[:500].decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM 响应非 JSON ({e!r}); body={snippet}") from e

    try:
        raw = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        snippet = body_bytes[:500].decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM 响应缺字段 ({e!r}); body={snippet}") from e
    return _clean_output(raw)


# ── 数据计算 ──

def _compute_deep_data(db: _DirectDB, session_row) -> dict:
    """从原始 DB 数据计算 L3 深度分析字典"""
    sid = session_row["session_id"]
    start = session_row["start_time"]
    session_date = start if isinstance(start, str) else ""

    fr = db.get_focus_records(sid)
    fat_r = db.get_fatigue_records(sid)
    dur = db.get_session_duration(sid)

    scores = [r["focus_score"] for r in fr if r["focus_score"]]
    avg_focus = round(sum(scores) / len(scores), 0) if scores else 50.0
    dur_min = int(dur / 60)

    # 三段
    n = len(fr)
    third = max(1, n // 3)
    def _avg_slice(start, end):
        seg = [r["focus_score"] for r in fr[start:end] if r["focus_score"]]
        return round(sum(seg) / len(seg), 0) if seg else avg_focus
    seg_s = _avg_slice(0, third)
    seg_m = _avg_slice(third, 2*third) if n > third else avg_focus
    seg_e = _avg_slice(-third, None)

    # 疲劳分布
    total_f = max(len(fat_r), 1)
    high = sum(1 for r in fat_r if r["fatigue_level"] == "HIGH")
    mid = sum(1 for r in fat_r if r["fatigue_level"] == "MEDIUM")
    low = sum(1 for r in fat_r if r["fatigue_level"] == "LOW")
    f_high = round(high / total_f * 100)
    f_mid = round(mid / total_f * 100)
    f_low = round(low / total_f * 100)

    # 专注悬崖
    cliffs = []
    prev = None
    for r in fr:
        sc = r["focus_score"]
        if prev is not None and sc is not None:
            drop = prev - sc
            if drop >= 15:
                minute = int(r["window_start"] // 60)
                cliffs.append(f"第{minute}分: {prev:.0f}→{sc:.0f} (-{drop:.0f}分)")
        prev = sc if sc is not None else prev

    # 疲劳演变
    fatigue_steps = []
    last_level = None
    for r in fat_r:
        level = r["fatigue_level"]
        if level != last_level:
            minute = int(r["timestamp"] // 60)
            fatigue_steps.append(f"第{minute}分 {level}")
            last_level = level

    # 分心分布
    dist_count = sum(1 for r in fr if r["focus_score"] is not None and r["focus_score"] < 60)
    if dist_count > 0 and dur > 0:
        half = dur / 2
        first_half = sum(1 for r in fr if r["focus_score"] is not None and r["focus_score"] < 60 and r["window_start"] <= half)
        second_half = dist_count - first_half
        if second_half > first_half:
            dist_pattern = f"{dist_count}次低分，后段集中（{second_half}/{dist_count}次）"
        else:
            dist_pattern = f"{dist_count}次低分，分布均匀"
    else:
        dist_pattern = "无显著分心"

    # 历史对比
    past_rows = db.get_past_sessions(sid)
    past_lines = []
    if past_rows:
        past_lines.append(f"近 {len(past_rows)} 次会话：")
        for r in past_rows:
            af = r["avg_focus"]
            if af:
                past_lines.append(f"- 专注度 {af:.0f}/100")
        past_avgs = [r["avg_focus"] for r in past_rows if r["avg_focus"]]
        if past_avgs:
            mean_past = sum(past_avgs) / len(past_avgs)
            diff = avg_focus - mean_past
            if abs(diff) > 3:
                arrow = "↑ 高于" if diff > 0 else "↓ 低于"
                past_lines.append(f"本次 {arrow} 历史平均 ({mean_past:.0f}) {diff:+.0f} 分")

    hist_avg = db.get_hist_avg_focus(sid) or 60

    return {
        "session_date": session_date[:16] if len(session_date) >= 16 else session_date,
        "duration": dur_min,
        "avg_focus": avg_focus,
        "hist_avg_focus": hist_avg,
        "seg_start": seg_s, "seg_mid": seg_m, "seg_end": seg_e,
        "fatigue_high_pct": f_high, "fatigue_mid_pct": f_mid, "fatigue_low_pct": f_low,
        "distractions": dist_count,
        "focus_cliffs": "\n".join(cliffs[:5]) or "无显著专注悬崖",
        "fatigue_evolution": " → ".join(fatigue_steps) or "疲劳无变化",
        "dist_pattern": dist_pattern,
        "past_sessions_summary": "\n".join(past_lines) if past_lines else "无历史数据",
    }


def _build_context(d: dict) -> str:
    """构建对话上下文文本"""
    s, e = d["seg_start"], d["seg_end"]
    trend = "上升" if e > s else ("下降" if s > e else "平稳")
    ctx = (
        f"## 会话数据\n"
        f"- 日期：{d['session_date']}\n"
        f"- 时长：{d['duration']} 分钟\n"
        f"- 平均专注度：{d['avg_focus']}/100\n"
        f"- 历史平均：{d['hist_avg_focus']}/100\n"
        f"- 趋势：前段 {d['seg_start']} → 中段 {d['seg_mid']} → 后段 {d['seg_end']} ({trend})\n"
        f"- 疲劳：高 {d['fatigue_high_pct']}% / 中 {d['fatigue_mid_pct']}% / 低 {d['fatigue_low_pct']}%\n"
        f"- 分心：{d['distractions']} 次\n"
    )
    for key, label in [("focus_cliffs", "专注悬崖"), ("fatigue_evolution", "疲劳演变"),
                       ("dist_pattern", "分心分布"), ("past_sessions_summary", "历史对比")]:
        val = d.get(key, "")
        if val and "无" not in str(val)[:5]:
            ctx += f"\n{label}：\n{val}\n"
    return ctx


# ── 主流程 ──

def main():
    parser = argparse.ArgumentParser(description="EyeFocus AI 命令行对话")
    parser.add_argument("--db", default="data/eyefocus.db", help="数据库路径")
    parser.add_argument("--no-color", action="store_true", help="禁用颜色")
    args = parser.parse_args()

    if args.no_color:
        for attr in dir(Style):
            if not attr.startswith("_"):
                setattr(Style, attr, "")

    print()
    print(c("  ╭─────────────────────────────╮", Style.DIM, Style.BOLD))
    print(c("  │  EyeFocus Insight · AI 对话  │", Style.DIM, Style.BOLD))
    print(c("  ╰─────────────────────────────╯", Style.DIM, Style.BOLD))
    print()

    # ── 读取配置 ──
    try:
        from config import get_yaml_value
        from analyzer.secrets import get_api_key, is_loopback_url
        api_key = get_api_key() or ""
        base_url = get_yaml_value("ai", "api_url", default="https://api.deepseek.com/v1")
        model = get_yaml_value("ai", "api_model", default="deepseek-chat")
        backend = get_yaml_value("ai", "backend", default="template")
    except Exception as e:
        print(c(f"  ✗ 读取配置失败: {e}", Style.RED))
        sys.exit(1)

    if not api_key:
        print(c("  ✗ API Key 未配置。请先在托盘菜单 → API 设置 中配置。", Style.RED))
        sys.exit(1)
    if backend == "template":
        print(c("  ✗ 当前后端为模板模式，请在设置中切换到 API 模式。", Style.RED))
        sys.exit(1)

    print(f"  API: {c('已配置', Style.GREEN)} ({_mask_key(api_key)})")
    print(f"  后端: {c(backend, Style.CYAN)}")
    print(f"  模型: {c(model, Style.MAGENTA)}")
    if base_url.startswith("http://") and not is_loopback_url(base_url):
        print(c(f"  ⚠ API 地址使用 HTTP（非 loopback），将明文传输 Key！建议改用 HTTPS。", Style.RED))
    print()

    # ── 连接数据库 ──
    try:
        import os as _os
        db_path = args.db
        if not _os.path.exists(db_path) and not _os.path.isabs(db_path):
            db_path = _os.path.join(_os.path.dirname(__file__), "..", "..", db_path)
        db = _DirectDB(db_path)
        print(c(f"  DB: {_os.path.basename(db_path)}", Style.DIM))
    except Exception as e:
        print(c(f"  ✗ 数据库连接失败: {e}", Style.RED))
        print(c("  提示：关闭 EyeFocus 主程序后可避免锁冲突。", Style.DIM))
        sys.exit(1)

    # ── 列会话 ──
    print(c("  ⟳ 读取会话...", Style.DIM))
    try:
        sessions = db.list_sessions(10)
    except Exception as e:
        print(c(f"  ✗ 读取失败（数据库忙）: {e}", Style.RED))
        print(c("  请关闭 EyeFocus 主程序后重试。", Style.YELLOW))
        sys.exit(1)

    if not sessions:
        print(c("  ✗ 无历史会话。请先运行主程序进行监测。", Style.RED))
        sys.exit(1)

    print(c(f"  最近 {len(sessions)} 条会话：", Style.BOLD))
    for i, s in enumerate(sessions, 1):
        st = s["start_time"][:16] if s["start_time"] else "???"
        dur = db.get_session_duration(s["session_id"])
        print(f"  {c(f'{i}.', Style.DIM)} {st}  {c(f'{int(dur/60)}分', Style.DIM)}  {s['session_id'][:8]}")
    print()

    # ── 选会话 ──
    choice = input(c("输入编号或 session_id > ", Style.CYAN)).strip()
    if not choice:
        return
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(sessions):
            sid = sessions[idx]["session_id"]
        else:
            print(c("✗ 无效编号", Style.RED))
            return
    else:
        sid = choice

    session_row = db.get_session_info(sid)
    if not session_row:
        print(c("✗ 未找到会话", Style.RED))
        return

    # ── L3 深度分析 ──
    print(c("  ⟳ 计算 L3 深度分析...", Style.DIM))
    deep_data = _compute_deep_data(db, session_row)
    context = _build_context(deep_data)

    DEEP_SYSTEM_PROMPT = (
        "你是一个专注力分析教练，像朋友一样聊天。基于时序数据做深度模式分析。\n\n"
        "分析结构：\n"
        "1. 一句话总结 + 整体评分\n"
        "2. 发现 1-2 个具体模式，每个引用 2+ 数字\n"
        "3. 与历史对比，指出改善/退步\n"
        "4. 给 1 个可执行建议（含具体时间点）\n"
        "5. 鼓励一句\n\n"
        "铁律：每句话都有数字支撑，不确定说\"数据不足\"，用中文口语化"
    )

    messages = [
        {"role": "system", "content": DEEP_SYSTEM_PROMPT},
        {"role": "user", "content": f"你正在分析一个会话。数据如下：\n\n{context}\n\n请分析这次会话的表现。"},
    ]

    # 第一次调用 L3 分析
    print(c("  ⟳ 正在生成 L3 分析...", Style.DIM))
    try:
        analysis = _call_llm(messages, model, base_url, api_key, max_tokens=1000, timeout=60)
        print()
        print(c("  ════════════════════════════════", Style.DIM))
        for line in analysis.split("\n"):
            print(f"  {line}")
        print(c("  ════════════════════════════════", Style.DIM))
        messages.append({"role": "assistant", "content": analysis})
        print()
    except Exception as e:
        err = _sanitize_err(str(e))
        print(c(f"  ✗ 分析失败: {err}", Style.YELLOW))
        print(c("  仍然可以对话，但 AI 没有上下文。", Style.DIM))
        print()

    # ── 交互式对话 ──
    print(c("  ══ 进入对话（输入 q / exit 退出）══", Style.DIM))
    print()

    while True:
        try:
            q = input(c("你 > ", Style.CYAN))
        except (EOFError, KeyboardInterrupt):
            print()
            break

        q = q.strip()
        if not q:
            continue
        if q.lower() in ("exit", "quit", "q", "退出"):
            break

        messages.append({"role": "user", "content": q})

        try:
            print(c("AI > ", Style.GREEN), end="", flush=True)
            reply = _call_llm(messages, model, base_url, api_key, max_tokens=800, timeout=30)
            print(reply)
            messages.append({"role": "assistant", "content": reply})
        except Exception as e:
            err = _sanitize_err(str(e))
            print(c(f"✗ {err}", Style.RED))

    print()
    print(c("  再见。", Style.DIM))


if __name__ == "__main__":
    main()

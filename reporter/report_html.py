"""
reporter/report_html.py — HTML 报告生成模块

从数据库读取会话数据，生成包含专注度/疲劳统计的 HTML 报告。
支持中文显示，图表以 base64 编码嵌入。

报告结构：
1. 摘要统计
2. 专注度趋势图
3. 眨眼频率分布图
4. 疲劳等级时间线图
5. 个性化建议
"""

import base64
import logging
import os as _os
from dataclasses import dataclass
from datetime import datetime
from html import escape as html_escape
from io import BytesIO
from typing import List, Optional

from storage.db import DatabaseManager
from storage.models import FocusRecord, FatigueRecord, FatigueLevel, BlinkRecord, Session

from reporter.charts import ChartGenerator, create_chart_generator

# v4.26: 从外部 CSS 文件加载样式
_CSS_PATH = _os.path.join(_os.path.dirname(__file__), "style.css")
try:
    with open(_CSS_PATH, encoding="utf-8") as _f:
        _CSS_CONTENT = _f.read()
    _CSS_TAG = f"<style>\n{_CSS_CONTENT}\n</style>"
except Exception:
    _CSS_CONTENT = ""
    _CSS_TAG = "<style></style>"
from reporter.insights import InsightsEngine, Insight, create_insights_engine

# v4.1: 可选 insights 集成
try:
    from analyzer.insights import InsightsResult as _InsightsResult
    HAS_INSIGHTS = True
except ImportError:
    _InsightsResult = None
    HAS_INSIGHTS = False

logger = logging.getLogger("eyefocus.reporter")


@dataclass
class ReportData:
    """报告数据容器 (v4.39: +distraction_records)"""
    session: Session
    focus_records: List[FocusRecord]
    fatigue_records: List[FatigueRecord]
    blink_records: List[BlinkRecord]
    frame_records: List  # v4.13: FrameRecord 列表（头姿散点图用）
    avg_focus: float
    avg_blink_rate: float
    total_duration: float
    fatigue_level: FatigueLevel
    distraction_records: List = None  # v4.39: 分心事件列表（有默认值，放最后）


# v4.32: 模块级图表缓存 — 同一天内重复打开报告免重新生成 Plotly
_chart_html_cache: "Dict[str, Dict[str, str]]" = {}

class HTMLReportGenerator:
    """HTML 报告生成器

    使用方法：
        generator = HTMLReportGenerator(db_manager)
        html_content = generator.generate_report(session_id)
    """

    # CSS 样式 (v4.26: 从 style.css 文件加载)
    CSS_STYLE = _CSS_TAG

    # Plotly JS — v4.36: 内联以确保离线可用，回退到外部引用
    PLOTLY_JS = '<script src="plotly.min.js"></script>'  # 默认值，模块加载后内联覆盖

    # v4.29: 报告内对话已移除（保留模板建议）

    @staticmethod
    def _load_plotly_js() -> str:
        """v4.36: 加载 plotly.min.js 为内联 <script> 标签"""
        import os as _os
        import plotly as _plotly
        src = _os.path.join(_os.path.dirname(_plotly.__file__), 'package_data', 'plotly.min.js')
        if _os.path.exists(src):
            with open(src, 'r', encoding='utf-8') as _f:
                content = _f.read()
            logger.debug("plotly.min.js 已内联 (%.1f KB)", len(content) / 1024)
            return f'<script>{content}</script>'
        logger.warning("plotly.min.js 未找到，回退到外部引用")
        return '<script src="plotly.min.js"></script>'

    JS_SCRIPT = """
        <script>
        function switchTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(function(el) {
                el.classList.remove('active');
            });
            document.querySelectorAll('.tab-btn').forEach(function(el) {
                el.classList.remove('active');
            });
            document.getElementById('tab-' + tabId).classList.add('active');
            document.querySelector('.tab-btn[data-tab="' + tabId + '"]').classList.add('active');
            // v4.16: Plotly charts in hidden tabs have zero size — resize after display
            setTimeout(function() {
                var charts = document.querySelectorAll('#tab-' + tabId + ' .js-plotly-plot');
                charts.forEach(function(el) {
                    try { Plotly.Plots.resize(el); } catch(e) {}
                });
            }, 100);
        }
        </script>
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        chart_generator: Optional[ChartGenerator] = None,
        insights_engine: Optional[InsightsEngine] = None,
    ):
        """初始化报告生成器

        Args:
            db_manager: 数据库管理器实例
            chart_generator: 图表生成器实例
            insights_engine: 建议引擎实例
        """
        self.db = db_manager
        self.chart_gen = chart_generator or create_chart_generator()
        # v4.10: 传递 db 给建议引擎（用于历史对比）
        self.insights_engine = insights_engine or create_insights_engine(db=db_manager)

    def generate_report(self, session_id: str) -> str:
        """生成完整 HTML 报告

        Args:
            session_id: 会话 ID

        Returns:
            HTML 字符串
        """
        # v4.16: 确保 plotly.min.js 本地资产可用
        # v4.36: plotly.min.js 已内联，无需复制外部文件

        if not self.db:
            return self._error_html("数据库管理器未初始化")

        # 获取会话信息
        session = self.db.get_session(session_id)
        if not session:
            return self._error_html(f"未找到会话: {session_id}")

        # 获取数据
        focus_records = self.db.get_focus_records(session_id)
        fatigue_records = self.db.get_fatigue_records(session_id)
        blink_records = self.db.get_blink_events(session_id)
        # v4.13: 取帧记录（头姿散点图用），采样控制性能
        all_frames = self.db.get_frame_records(session_id)
        frame_records = all_frames[::max(1, len(all_frames) // 500)] if len(all_frames) > 500 else all_frames

        # v4.11: 数据不足时显示占位页（v4.22: 阈值 3→2，因生成报告不再终止会话）
        if len(focus_records) < 2:
            return self._render_insufficient_data(session_id)

        # 计算统计信息
        avg_focus = self._calc_avg_focus(focus_records)
        avg_blink_rate = self._calc_avg_blink_rate(focus_records)
        total_duration = session.duration_seconds() or 0.0
        fatigue_level = self._determine_fatigue_level(fatigue_records)

        # v4.24: 存储数据供 AI 摘要使用
        report_data = self._data = ReportData(
            session=session,
            focus_records=focus_records,
            fatigue_records=fatigue_records,
            blink_records=blink_records,
            frame_records=frame_records,
            avg_focus=avg_focus,
            avg_blink_rate=avg_blink_rate,
            total_duration=total_duration,
            fatigue_level=fatigue_level,
        )

        # 生成图表
        charts = self._generate_charts(report_data)

        # v4.38: 查询同日其他会话（L2 同日对比）
        same_day_sessions = []
        try:
            today_str = session.start_time.strftime("%Y-%m-%d")
            same_day_sessions = self.db.get_sessions_by_date_range(
                today_str, today_str) if self.db else []
        except Exception:
            pass

        # 生成建议
        insights = self.insights_engine.analyze(
            focus_records=focus_records,
            fatigue_records=fatigue_records,
            avg_focus=avg_focus,
            avg_blink_rate=avg_blink_rate,
            session_duration=total_duration,
            session_id=session.session_id,
            session_start_time=session.start_time.timestamp(),
            blink_records=blink_records,
            same_day_sessions=same_day_sessions,
        )

        # 渲染 HTML
        return self._render_html(report_data, charts, insights)

    def generate_daily_report(self, date_str: str) -> str:
        """生成当天所有会话的合并汇总报告

        Args:
            date_str: "YYYY-MM-DD"

        Returns:
            HTML 字符串
        """
        if not self.db:
            return self._error_html("数据库管理器未初始化")

        try:
            data = self.db.get_daily_merged_data(date_str)
            if not data:
                return self._error_html(f"未找到 {date_str} 的数据")

            sessions = data["sessions"]
            focus_records = data["focus_records"]
            if not sessions or len(focus_records) < 2:
                return self._render_insufficient_data(f"daily_{date_str}")

            # 构造合成 Session（占位，total_duration 从 merge 数据来）
            from datetime import datetime
            first = sessions[0]
            last = sessions[-1]
            baseline_blink = None
            calibrated = [s for s in sessions if s.is_calibrated and s.baseline_blink_rate]
            if calibrated:
                baseline_blink = calibrated[-1].baseline_blink_rate
            # v4.37: 用首个真实会话时间，非午夜（Bug #5）
            real_start = first.start_time if first.start_time else datetime.strptime(date_str, "%Y-%m-%d")
            combined_session = Session(
                session_id=f"daily_{date_str}",
                start_time=real_start,
                end_time=last.end_time or datetime.now(),
                baseline_blink_rate=baseline_blink,
                is_calibrated=bool(calibrated),
            )

            avg_focus = self._calc_avg_focus(focus_records)
            avg_blink_rate = self._calc_avg_blink_rate(focus_records)
            total_duration = data["total_duration"]
            fatigue_level = self._determine_fatigue_level(data["fatigue_records"])
            # v4.37: 计算最长单次会话时长（用于日汇总建议）
            max_session_duration = max(
                (s.end_time - s.start_time).total_seconds()
                for s in sessions if s.end_time
            ) if sessions else 0.0

            report_data = self._data = ReportData(
                session=combined_session,
                focus_records=focus_records,
                fatigue_records=data["fatigue_records"],
                blink_records=data["blink_records"],
                frame_records=data["frame_records"],
                avg_focus=avg_focus,
                avg_blink_rate=avg_blink_rate,
                total_duration=total_duration,
                fatigue_level=fatigue_level,
            )

            charts = self._generate_charts(report_data)
            insights = self.insights_engine.analyze(
                focus_records=focus_records,
                fatigue_records=data["fatigue_records"],
                avg_focus=avg_focus,
                avg_blink_rate=avg_blink_rate,
                session_duration=total_duration,
                session_id=combined_session.session_id,
                session_start_time=combined_session.start_time.timestamp(),
                is_daily=True,
                session_count=len(sessions),
                max_session_duration=max_session_duration,
                blink_records=data["blink_records"],
            )
            return self._render_daily_html(report_data, charts, insights, len(sessions))
        except Exception as e:
            logger.error("生成日汇总报告失败: %s", e)
            return self._error_html(f"生成日汇总报告失败: {e}")

    def _render_daily_html(self, data: ReportData, charts: dict,
                           insights: List[Insight], session_count: int) -> str:
        """日汇总报告的 HTML（头部加会话数提示）"""
        html = self._render_html(data, charts, insights)
        safe_sid = html_escape(data.session.session_id)
        old = f'会话 ID: {safe_sid} |'
        new = (f'📅 当日汇总 · {session_count} 个会话 &nbsp;|&nbsp;'
               f'<span style="font-size:11px;color:var(--quiet)">'
               f'会话 ID: {safe_sid} |')
        html = html.replace(old, new, 1)
        return html

    def generate_report_from_data(
        self,
        session: Session,
        focus_records: List[FocusRecord],
        fatigue_records: List[FatigueRecord],
        blink_records: List[BlinkRecord],
        frame_records: Optional[List] = None,
    ) -> str:
        """从数据对象生成报告（不依赖数据库）

        Args:
            session: 会话对象
            focus_records: 专注度记录列表
            fatigue_records: 疲劳记录列表
            blink_records: 眨眼事件列表
        """
        # v4.36: plotly.min.js 已内联，无需复制外部文件

        # 计算统计信息
        avg_focus = self._calc_avg_focus(focus_records)
        avg_blink_rate = self._calc_avg_blink_rate(focus_records)
        total_duration = session.duration_seconds() or 0.0
        fatigue_level = self._determine_fatigue_level(fatigue_records)

        # v4.24: 存储数据供 AI 摘要使用
        report_data = self._data = ReportData(
            session=session,
            focus_records=focus_records,
            fatigue_records=fatigue_records,
            blink_records=blink_records,
            frame_records=frame_records or [],
            avg_focus=avg_focus,
            avg_blink_rate=avg_blink_rate,
            total_duration=total_duration,
            fatigue_level=fatigue_level,
        )

        # 生成图表
        charts = self._generate_charts(report_data)

        # 生成建议
        insights = self.insights_engine.analyze(
            focus_records=focus_records,
            fatigue_records=fatigue_records,
            avg_focus=avg_focus,
            avg_blink_rate=avg_blink_rate,
            session_duration=total_duration,
            session_id=session.session_id,
            session_start_time=session.start_time.timestamp(),
            blink_records=blink_records,
        )

        # 渲染 HTML
        return self._render_html(report_data, charts, insights)

    def _generate_charts(self, data: ReportData) -> dict:
        """生成所有图表（v4.32: 图表缓存 + 6 线程并行）

        每个图表独立 try/except，失败不互相影响。返回值结构:
            {name: {"data": base64_str | None, "error": str | None}}
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # v4.32: 缓存键 = (会话ID, 各表记录数) — 同数据集命中缓存，免 Plotly 重渲染
        sid = data.session.session_id
        cache_key = (
            sid,
            len(data.focus_records),
            len(data.fatigue_records),
            len(data.frame_records),
        )
        if cache_key in _chart_html_cache:
            logger.debug("图表缓存命中: %s", sid)
            return _chart_html_cache[cache_key]

        charts = {}
        has_focus = bool(data.focus_records)

        # 定义图表任务 (name, gen_fn, has_data)
        tasks = [
            ("focus_trend",
             lambda: self.chart_gen.generate_focus_trend_chart(data.focus_records),
             has_focus),
            ("blink_rate",
             lambda: self.chart_gen.generate_blink_rate_chart(
                 data.focus_records,
                 baseline_blink_rate=data.session.baseline_blink_rate,
             ),
             has_focus),
            ("fatigue_timeline",
             lambda: self.chart_gen.generate_fatigue_timeline(data.fatigue_records),
             bool(data.fatigue_records)),
            ("session_colorbar",
             lambda: self.chart_gen.generate_session_colorbar(data.focus_records),
             has_focus),
            ("head_pose_scatter",
             lambda: self.chart_gen.generate_head_pose_scatter(data.frame_records),
             bool(data.frame_records)),
        ]

        # 并行生成 5 个 Plotly 图表（纯 CPU 无 DB I/O）
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {}
            for name, gen_fn, has_data in tasks:
                if not has_data:
                    charts[name] = {"data": None, "error": None}
                    continue
                futures[executor.submit(gen_fn)] = name

            for future in as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    if isinstance(result, bytes):
                        charts[name] = {"data": self._bytes_to_base64(result), "error": None}
                    else:
                        charts[name] = {"data": result, "error": None}
                except Exception as e:
                    logger.error("生成图表 %s 失败: %s", name, e)
                    charts[name] = {"data": None, "error": str(e)}

        # 日历热力图 — 串行（内部调用 self.db，避免线程竞争）
        try:
            charts["calendar_heatmap"] = {
                "data": self._generate_calendar_chart(),
                "error": None,
            }
        except Exception as e:
            logger.warning("日历热力图生成失败: %s", e)
            charts["calendar_heatmap"] = {"data": None, "error": str(e)}

        # v4.32: 缓存图表结果（同数据集再打开免重渲染）
        _chart_html_cache[cache_key] = charts
        # 限制缓存 ≤ 5 条目，防内存增长
        if len(_chart_html_cache) > 5:
            oldest = next(iter(_chart_html_cache))
            del _chart_html_cache[oldest]

        return charts

    # ── v4.17: 日历热力图 ──

    def _generate_calendar_chart(self) -> str:
        """生成专注日历热力图"""
        try:
            all_stats = self.db.get_all_daily_stats()
            if not all_stats:
                return self.chart_gen._empty_html("无历史数据")
            daily_list = [
                {"date": s.date, "minutes": s.total_focus_minutes}
                for s in all_stats
            ]
            return self.chart_gen.generate_calendar_heatmap(daily_list)
        except Exception as e:
            logger.warning("日历热力图生成失败: %s", e)
            return self.chart_gen._empty_html("生成失败")

    def _render_html(
        self,
        data: ReportData,
        charts: dict,
        insights: List[Insight],
    ) -> str:
        """v4.26: 3 标签页（🎯 此刻 + 🔬 模式 + ⏭ 下一步）"""
        session = data.session

        safe_session_id = html_escape(session.session_id)

        # 将原始 chart data 渲染为 HTML
        charts_for_render = {k: v for k, v in charts.items() if k != "insights_charts"}
        charts_html = self._render_charts(charts_for_render)
        # v4.29: 洞察图表并入数据 tab
        insights_charts_html = charts.get("insights_charts", "")

        # 各 tab HTML
        overview_html = self._render_overview_tab(data, charts_html)
        analysis_html = self._render_analysis_tab(charts_html, insights_charts_html)
        suggestions_html = self._render_insights_tab(insights)
        next_steps_html = self._render_next_steps()

        html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EyeFocus Insight 专注度分析报告</title>
    {self.CSS_STYLE}
    {self.PLOTLY_JS}
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>EyeFocus Insight 专注度分析报告</h1>
            <div class="subtitle">
                会话 ID: {safe_session_id} | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </div>
        </div>

        <div class="tab-bar">
            <button class="tab-btn active" data-tab="overview" onclick="switchTab('overview')">📊 概览</button>
            <button class="tab-btn" data-tab="analysis" onclick="switchTab('analysis')">📋 数据</button>
            <button class="tab-btn" data-tab="suggestions" onclick="switchTab('suggestions')">💡 建议</button>
        </div>

        <div id="tab-overview" class="tab-content active">{overview_html}</div>
        <div id="tab-analysis" class="tab-content">{analysis_html}</div>
        <div id="tab-suggestions" class="tab-content">{suggestions_html}{next_steps_html}</div>

        <div class="footer">
            EyeFocus Insight v4.29 | 自动生成专注度分析报告 | 会话 {safe_session_id[:12]}
        </div>
    </div>
    {self.JS_SCRIPT}
</body>
</html>"""
        return html

    def _compute_overview_stats(self, data: ReportData) -> dict:
        """计算概览页统计数据 + 与历史对比"""
        stats = {
            "avg_focus": data.avg_focus,
            "duration": data.total_duration,
            "blink_rate": data.avg_blink_rate,
            "fatigue_level": data.fatigue_level,
            "total_records": len(data.focus_records),
            "hist_avg_focus": None,
            "focus_change": None,
        }

        # 有效专注率: FOCUSED 记录占比
        focused_count = sum(1 for r in data.focus_records if r.focus_score >= 80)
        stats["focus_rate"] = (focused_count / max(1, len(data.focus_records))) * 100

        # 与历史对比（v4.30: 每个会话等权重平均，长会话不主导）
        if self.db and data.session.session_id:
            try:
                sid = data.session.session_id
                if sid.startswith("daily_"):
                    exclude_where = "AND date(s.start_time) != ?"
                    exclude_val = sid.replace("daily_", "")
                else:
                    exclude_where = "AND s.session_id != ?"
                    exclude_val = sid

                with self.db.get_cursor() as cur:
                    cur.execute(f"""
                        SELECT AVG(session_avg) FROM (
                            SELECT AVG(f.focus_score) AS session_avg
                            FROM sessions s
                            JOIN focus_records f ON s.session_id = f.session_id
                            WHERE f.focus_score IS NOT NULL {exclude_where}
                            GROUP BY s.session_id
                        )
                    """, (exclude_val,))
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        stats["hist_avg_focus"] = round(row[0], 1)
                        stats["focus_change"] = round(data.avg_focus - row[0], 1)
            except Exception:
                pass

        return stats

    def _render_overview_tab(self, data: ReportData, charts: dict) -> str:
        """v4.15: Quiet Focus 美学 — Hero数字 + 精简卡片"""
        stats = self._compute_overview_stats(data)
        parts = []

        # ── Hero 数字 ──
        avg_focus = stats["avg_focus"]
        if avg_focus >= 70:
            hero_color = "var(--sage-600)"
        elif avg_focus >= 50:
            hero_color = "var(--amber-600)"
        else:
            hero_color = "var(--rose-600)"

        parts.append(f'''
            <div class="focus-hero">
                <div class="hero-ring"></div>
                <div class="hero-value" style="color:{hero_color}">{avg_focus:.0f}</div>
                <div class="hero-label">平均专注度</div>
            </div>''')

        if stats["focus_change"] is not None:
            arrow = "↑" if stats["focus_change"] >= 0 else "↓"
            dc = "var(--sage-600)" if stats["focus_change"] >= 0 else "var(--rose-600)"
            parts.append(
                f'<div class="hero-compare" style="color:{dc}">'
                f'{arrow} {abs(stats["focus_change"]):.0f} vs 历史平均 {stats["hist_avg_focus"]:.0f}'
                f'</div>'
            )

        # ── 统计卡片 ──
        duration_str = self._format_duration(stats["duration"])
        blink_val = stats["blink_rate"]
        focused_count = sum(1 for r in data.focus_records if r.focus_score >= 80)
        total_records = len(data.focus_records)
        focus_rate = (focused_count / max(1, total_records)) * 100

        fatigue_map = {"LOW": "低", "MEDIUM": "中", "HIGH": "高"}
        fl = fatigue_map.get(stats["fatigue_level"].name, "--")

        cards = [
            ("⏱ 监测时长", duration_str, f"{total_records} 条记录"),
            ("👁 眨眼频率", f"{blink_val:.1f}", "次/分钟"),
            ("😊 疲劳等级", fl, ""),
            ("📊 有效专注率", f"{focus_rate:.0f}%", f"{focused_count}/{total_records} 段"),
        ]

        parts.append('<div class="stats-grid">')
        for label, val, sub in cards:
            sub_html = f'<div class="stat-sub">{sub}</div>' if sub else ""
            parts.append(
                f'<div class="stat-card">'
                f'<div class="stat-value">{val}</div>'
                f'<div class="stat-label">{label}</div>'
                f'{sub_html}'
                f'</div>'
            )
        parts.append('</div>')

        # ── 会话时间色条 ──
        colorbar = charts.get("session_colorbar")
        if colorbar:
            parts.append('<div class="card"><h2>会话专注分布</h2>' + colorbar + "</div>")

        # ── v4.25: 本周聚合（周报嵌入概览）──
        weekly_html = self._render_weekly_summary()
        if weekly_html:
            parts.append(weekly_html)

        # v4.33: AI 分析速览已移除

        # ── v4.33: 数据更新时间标注 ──
        from datetime import datetime as _dt
        now_str = _dt.now().strftime("%H:%M:%S")
        parts.append(f'''
            <div style="text-align:center;color:var(--quiet);font-size:10px;
                        padding:8px 0 4px 0;opacity:0.7;">
            📊 数据更新至 {now_str} · 5分钟内重复打开免重新生成
            </div>''')

        return "\n".join(parts)

    # ════════════════════════════════════════════
    # v4.25: 周聚合（嵌入主报告概览 Tab）
    # ════════════════════════════════════════════
    def _compute_weekly_stats(self):
        """计算本周聚合统计数据（v4.30: 按天汇总）"""
        if not self.db:
            return None
        from datetime import datetime, timedelta
        today = datetime.now()
        week_ago = (today - timedelta(days=7))
        week_ago_str = week_ago.strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")

        sessions = self.db.get_sessions_by_date_range(week_ago_str, today_str)
        if not sessions:
            return None

        # 按天分组
        from collections import defaultdict
        day_groups = defaultdict(list)
        for sess in sessions:
            if sess.end_time is None:
                continue  # 跳过未结束的孤立会话
            day_key = sess.start_time.strftime("%Y-%m-%d")
            day_groups[day_key].append(sess)

        if not day_groups:
            return None

        # v4.31: 批量获取所有会话的专注度记录（单次查询，消除 N+1）
        all_sids = [s.session_id for s in sessions if s.end_time is not None]
        focus_map = self.db.get_focus_records_batch(all_sids)

        total_minutes = 0.0
        days_list = []

        for day_key in sorted(day_groups, reverse=True):
            day_sessions = day_groups[day_key]
            day_dur = 0.0
            day_scores = []
            for sess in day_sessions:
                dur = sess.duration_seconds() or 0.0
                day_dur += dur
                records = focus_map.get(sess.session_id, [])
                if records:
                    valid = [r.focus_score for r in records if r.focus_score is not None]
                    day_scores.extend(valid)

            total_minutes += day_dur / 60.0
            day_avg = sum(day_scores) / len(day_scores) if day_scores else 0.0
            days_list.append({
                "date": day_key,
                "label": datetime.strptime(day_key, "%Y-%m-%d").strftime("%m-%d"),
                "duration": day_dur / 60.0,
                "score": day_avg,
                "count": len(day_sessions),
            })

        avg_score = sum(d["score"] for d in days_list) / max(1, len(days_list))

        return {
            "total_minutes": total_minutes,
            "avg_score": avg_score,
            "session_count": sum(d["count"] for d in days_list),
            "days_active": len(days_list),
            "sessions": days_list,
            "range": f"{week_ago.strftime('%m-%d')} ~ {today.strftime('%m-%d')}",
        }

    def _render_weekly_summary(self) -> str:
        """渲染本周聚合卡片（嵌入概览 Tab）"""
        stats = self._compute_weekly_stats()
        if not stats or stats["session_count"] < 1:
            return ""

        # Hero 数字
        hero = (
            f'<div style="display:flex;gap:24px;flex-wrap:wrap;padding:12px 0;">'
            f'<div style="text-align:center;flex:1;min-width:80px;">'
            f'<div style="font-family:Georgia,serif;font-size:32px;color:var(--iris);">{stats["total_minutes"]:.0f}</div>'
            f'<div style="font-size:11px;color:var(--quiet);">总专注(分钟)</div></div>'
            f'<div style="text-align:center;flex:1;min-width:80px;">'
            f'<div style="font-family:Georgia,serif;font-size:32px;color:var(--sage);">{stats["avg_score"]:.0f}</div>'
            f'<div style="font-size:11px;color:var(--quiet);">平均专注度</div></div>'
            f'<div style="text-align:center;flex:1;min-width:80px;">'
            f'<div style="font-family:Georgia,serif;font-size:32px;color:var(--amber);">{stats["session_count"]}</div>'
            f'<div style="font-size:11px;color:var(--quiet);">会话数</div></div>'
            f'<div style="text-align:center;flex:1;min-width:80px;">'
            f'<div style="font-family:Georgia,serif;font-size:32px;color:var(--ink);">{stats["days_active"]}</div>'
            f'<div style="font-size:11px;color:var(--quiet);">活跃天数</div></div>'
            f'</div>'
        )

        # 按天明细表（v4.30: 每天一行，含会话数）
        rows = "".join(
            f'<tr><td>{s["label"]}</td><td>{s["duration"]:.0f}分</td>'
            f'<td>{s["score"]:.0f}分</td><td style="color:var(--quiet);font-size:11px;">×{s["count"]}</td></tr>'
            for s in stats["sessions"][:10]
        )
        table = f"""
        <table class="detail-table" style="margin-top:8px;">
            <tr><th style="text-align:left;color:var(--quiet);font-weight:500;font-size:11px;">日期</th>
                <th style="text-align:left;color:var(--quiet);font-weight:500;font-size:11px;">时长</th>
                <th style="text-align:left;color:var(--quiet);font-weight:500;font-size:11px;">专注度</th>
                <th style="text-align:left;color:var(--quiet);font-weight:500;font-size:11px;">会话</th></tr>
            {rows}
        </table>""" if stats["sessions"] else ""

        return f"""
        <div class="card" style="border-left:2px solid var(--iris);">
            <h2>📊 本周统计 <span style="font-size:11px;color:var(--quiet);font-weight:400;">{stats["range"]}</span></h2>
            {hero}
            {table}
        </div>"""

    def _render_analysis_tab(self, charts: dict, insights_charts_html: str = "") -> str:
        """v4.29: 数据 Tab — 图表(标准+洞察) + 原始数据"""
        parts = []

        # ── v4.17: 专注日历热力图 ──
        cal_html = charts.get("calendar_heatmap", "")
        if cal_html:
            parts.append(
                '<div class="card"><h2>📅 专注日历</h2>'
                '<p class="card-desc">历史每日专注时长分布</p>'
                + cal_html + "</div>"
            )

        sections = [
            ("专注度趋势",
             "全程专注度变化。绿/橙/红背景对应专注/一般/分心，参考线 70 分为良好线。",
             "focus_trend"),
            ("疲劳趋势",
             "累积疲劳分数。≥60 为严重疲劳信号，建议休息。",
             "fatigue_timeline"),
            ("眨眼频率",
             "眨眼频率与个人基线对比。高于基线 1.5 倍标红（疲劳信号）。",
             "blink_rate"),
            ("头部姿态变化",
             "头部偏离正位的角度变化。绿色区域为正常范围（≤20°），右上角为舒适区占比。",
             "head_pose_scatter"),
        ]

        for title, desc, key in sections:
            chart_html = charts.get(key, '<div class="no-data">无数据</div>')
            parts.append(f'''
            <div class="card">
                <h2>{title}</h2>
                <div class="card-desc">{desc}</div>
                {chart_html}
            </div>''')

        # v4.29: 洞察图表移入数据 tab
        if insights_charts_html:
            parts.append(insights_charts_html)

        return "\n".join(parts)

    def _compute_llm_data(self, data: ReportData) -> dict:
        """v4.26: 构造丰富的分析数据字典（LLM + 模板共用）"""
        fr = data.focus_records or []
        dur = data.total_duration or 0.0
        avg = data.avg_focus or 50.0
        fatigue_recs = data.fatigue_records or []

        # 三段专注
        third = max(1, len(fr) // 3)
        seg_start = self._calc_avg_focus(fr[:third]) if len(fr) >= third else avg
        seg_mid = self._calc_avg_focus(fr[third:2*third]) if len(fr) >= 2*third else avg
        seg_end = self._calc_avg_focus(fr[-third:]) if len(fr) >= third else avg

        # 疲劳分布
        total_f = max(len(fatigue_recs), 1)
        high_cnt = sum(1 for r in fatigue_recs if r.fatigue_level.name == "HIGH")
        mid_cnt = sum(1 for r in fatigue_recs if r.fatigue_level.name == "MEDIUM")
        low_cnt = sum(1 for r in fatigue_recs if r.fatigue_level.name == "LOW")
        fatigue_high_pct = round(high_cnt / total_f * 100, 0)
        fatigue_mid_pct = round(mid_cnt / total_f * 100, 0)
        fatigue_low_pct = round(low_cnt / total_f * 100, 0)

        # v4.39: 分心统计 — 从低专注记录直接计数（不再依赖缺失的 distraction_records）
        low_focus = [r for r in fr if r.focus_score is not None and r.focus_score < 60]
        dist_count = len(low_focus)
        # 分心原因分解（从 FocusRecord 的 eye/head/gaze score 估算）
        head_pct = gaze_pct = 0
        if dist_count > 0:
            avg_head = sum(r.head_score or 0 for r in low_focus) / len(low_focus)
            avg_gaze = sum(r.gaze_score or 0 for r in low_focus) / len(low_focus)
            total_hg = avg_head + avg_gaze
            if total_hg > 0:
                head_pct = round(avg_head / total_hg * 100)
                gaze_pct = 100 - head_pct

        # 疲劳等级
        fl = getattr(data, 'fatigue_level', None)
        fatigue_str = fl.name.upper() if fl and hasattr(fl, 'name') else "LOW"

        # 历史平均
        hist_avg = None
        if self.db and data.session:
            try:
                with self.db.get_cursor() as cur:
                    cur.execute("""
                        SELECT AVG(focus_score) FROM focus_records
                        WHERE session_id != ? AND focus_score IS NOT NULL
                    """, (data.session.session_id,))
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        hist_avg = round(row[0], 1)
            except Exception:
                pass

        return {
            "duration": int(dur / 60),
            "avg_focus": round(avg, 0),
            "baseline": 60,
            "hist_avg_focus": hist_avg or 60,
            "seg_start": round(seg_start, 0),
            "seg_mid": round(seg_mid, 0),
            "seg_end": round(seg_end, 0),
            "fatigue": fatigue_str,
            "fatigue_high_pct": fatigue_high_pct,
            "fatigue_mid_pct": fatigue_mid_pct,
            "fatigue_low_pct": fatigue_low_pct,
            "distractions": dist_count,
            "head_pct": head_pct,
            "gaze_pct": gaze_pct,
            "dist_peak_hour": "",
            "pomo_count": 0,
            "streak": 0,
        }

    # ── v4.27: L3 级深度分析数据 ──

    def _compute_deep_llm_data(self, data: ReportData, session_start: float = 0.0) -> dict:
        """构造 L3 级深度分析数据字典（含时序模式 + 历史对比）

        v4.37: session_start 用于计算相对分钟偏移，避免 Unix 时间戳 //60 产生荒谬值。
        """
        base = self._compute_llm_data(data)
        fr = data.focus_records or []
        dur = data.total_duration or 0.0
        avg = data.avg_focus or 50.0

        # 确保 session_start 有效
        if session_start == 0.0 and data.session and data.session.start_time:
            try:
                session_start = data.session.start_time.timestamp()
            except Exception:
                pass

        # 1. 专注悬崖（>15 分降幅）
        cliffs = []
        prev_score = None
        for r in fr:
            if prev_score is not None and r.focus_score is not None:
                drop = prev_score - r.focus_score
                if drop >= 15:
                    # v4.37: 相对偏移而非 Unix 时间戳直接除 60
                    offset = int((r.window_start - session_start) // 60) if (r.window_start and session_start) else 0
                    cliffs.append(f"第{offset}分: {prev_score:.0f}→{r.focus_score:.0f} (-{drop:.0f}分)")
            prev_score = r.focus_score if r.focus_score is not None else prev_score

        # 2. 疲劳演变时间线
        fatigue_steps = []
        last_level = None
        for r in (data.fatigue_records or []):
            level = r.fatigue_level.name if hasattr(r.fatigue_level, 'name') else str(r.fatigue_level)
            if level != last_level:
                # v4.37: 相对偏移而非 Unix 时间戳直接除 60
                offset = int((r.timestamp - session_start) // 60) if (r.timestamp and session_start) else 0
                fatigue_steps.append(f"第{offset}分 {level}")
                last_level = level

        # 3. 分心分布（v4.39: 使用相对偏移）
        dist_count = base.get("distractions", 0)
        if dist_count > 0 and dur > 0:
            half = dur / 2
            first_half = sum(1 for r in fr
                          if r.focus_score is not None and r.focus_score < 60
                          and (r.window_start - session_start) <= half)
            second_half = dist_count - first_half
            if second_half > first_half:
                dist_pattern = f"{dist_count}次分心，后段集中（{second_half}/{dist_count}次低分）"
            else:
                dist_pattern = f"{dist_count}次分心，前后段分布均匀"
        else:
            dist_pattern = "无显著分心事件"

        # 4. 历史对比
        past_summary = self._get_past_sessions_summary(data.session, avg)

        # 会话日期
        session_date = ""
        if data.session and data.session.start_time:
            try:
                session_date = data.session.start_time.strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass

        base.update({
            "session_date": session_date,
            "focus_cliffs": "\n".join(cliffs[:5]) or "无显著专注悬崖（>15分降幅）",
            "fatigue_evolution": " → ".join(fatigue_steps) or "疲劳等级无变化",
            "dist_pattern": dist_pattern,
            "past_sessions_summary": past_summary,
        })
        return base

    def _get_past_sessions_summary(self, session, current_avg: float) -> str:
        """v4.39: 查询过去若干次会话的摘要对比（修复不存在的列）"""
        if not self.db or not session:
            return "无历史数据"
        try:
            with self.db.get_cursor() as cur:
                # sessions 表无 avg_focus/duration_seconds，需 JOIN focus_records
                cur.execute("""
                    SELECT s.session_id, s.start_time, s.end_time,
                           AVG(f.focus_score) as avg_focus
                    FROM sessions s
                    LEFT JOIN focus_records f ON s.session_id = f.session_id
                    WHERE s.session_id != ? AND s.end_time IS NOT NULL
                    GROUP BY s.session_id
                    ORDER BY s.start_time DESC LIMIT 5
                """, (session.session_id,))
                rows = cur.fetchall()
                if not rows:
                    return "无历史数据"

            from datetime import datetime
            lines = [f"近 {len(rows)} 次会话数据："]
            past_avgs = []
            for row in rows:
                sid, st_str, et_str, avg_s = row
                if avg_s is None:
                    continue
                past_avgs.append(avg_s)
                dur_min = 0
                try:
                    st = datetime.fromisoformat(st_str) if st_str else None
                    et = datetime.fromisoformat(et_str) if et_str else None
                    if st and et:
                        dur_min = int((et - st).total_seconds() / 60)
                except Exception:
                    pass
                lines.append(f"- 专注度 {avg_s:.0f}/100，时长 {dur_min}分钟")

            if past_avgs:
                mean_past = sum(past_avgs) / len(past_avgs)
                diff = current_avg - mean_past
                if abs(diff) > 3:
                    direction = "↑ 高于" if diff > 0 else "↓ 低于"
                    lines.append(f"本次 {direction} 历史平均 ({mean_past:.0f}) {diff:+.0f} 分")

            return "\n".join(lines)
        except Exception:
            return "历史数据查询失败"

    def _ai_mode_enabled(self) -> bool:
        """检查 AI 模式是否开启"""
        try:
            from config import get_yaml_value
            return get_yaml_value("ai", "mode", default=True)
        except Exception:
            return True

    def _generate_ai_summary(self) -> str:
        """生成 AI 分析摘要

        AI 模式关闭时只返回空字符串。
        开启时优先使用已配置的 LLM 后端，不可用时回退到内置模板。
        结果按 session_id 缓存，避免重复生成。
        """
        if not self._ai_mode_enabled():
            return ""

        data = self._data if hasattr(self, '_data') and self._data else None
        if not data or not data.session:
            return ""
        sid = data.session.session_id

        # v4.26: 结果缓存（同一 session 只生成一次）
        if not hasattr(self.__class__, '_ai_cache'):
            self.__class__._ai_cache = {}
        _cache = self.__class__._ai_cache
        if sid in _cache:
            return _cache[sid]

        # ── v4.27: L3 深度分析（仅 openai 等支持 deep_analyze 的后端） ──
        backend = "template"
        try:
            from config import get_yaml_value
            backend = get_yaml_value("ai", "backend", default="template")
        except Exception:
            pass

        if backend != "template":
            from analyzer.llm_client import OpenAICompatibleClient
            deep_data = self._compute_deep_llm_data(data)
            result = self._try_llm_deep(deep_data)
            if result:
                _cache[sid] = result
                return result

        # ── 标准 LLM 后端 ──
        llm_data = self._compute_llm_data(data)
        result = self._try_llm_backend(llm_data)
        if result:
            _cache[sid] = result
            return result

        # ── 内置模板 ──
        result = self._generate_template_summary(data, llm_data)
        _cache[sid] = result
        return result

    def _try_llm_backend(self, llm_data: dict) -> str:
        """尝试 LLM 后端（Ollama/Local），超时或不可用时返回空"""
        try:
            from config import get_yaml_value
            from concurrent.futures import ThreadPoolExecutor as _TPE, TimeoutError as _TO
            from analyzer.llm_client import create_llm_client

            backend = get_yaml_value("ai", "backend", default="template")
            if backend == "template":
                return ""

            kwargs = {}
            if backend == "ollama":
                kwargs["base_url"] = get_yaml_value("ai", "ollama_url",
                                                     default="http://127.0.0.1:11434")
            elif backend == "local":
                kwargs["model_key"] = get_yaml_value("ai", "model_key", default="qwen2.5:1.5b")
            elif backend == "openai":
                kwargs["api_key"] = get_yaml_value("ai", "api_key", default="")
                kwargs["base_url"] = get_yaml_value("ai", "api_url", default="https://api.deepseek.com/v1")
                kwargs["model"] = get_yaml_value("ai", "api_model", default="deepseek-chat")
            client = create_llm_client(backend, **kwargs)
            if not client.available:
                logger.info("AI 分析: %s 不可用，回退模板", client.name)
                return ""

            with _TPE(max_workers=1) as _pool:
                _fut = _pool.submit(client.analyze, llm_data)
                result = _fut.result(timeout=15)
            if result and result.strip():
                logger.info("AI 分析: %s 生成成功", client.name)
                return result.strip()
        except _TO:
            logger.warning("AI 分析: LLM 超时 (15s)，回退模板")
        except Exception:
            logger.debug("AI 分析: LLM 异常，回退模板", exc_info=True)
        return ""

    def _try_llm_deep(self, llm_data: dict) -> str:
        """v4.27: 尝试 L3 深度分析（deep_analyze），超时或不可用时返回空"""
        try:
            from config import get_yaml_value
            from concurrent.futures import ThreadPoolExecutor as _TPE, TimeoutError as _TO
            from analyzer.llm_client import create_llm_client

            backend = get_yaml_value("ai", "backend", default="template")
            if backend == "template":
                return ""

            kwargs = {}
            if backend == "openai":
                kwargs["api_key"] = get_yaml_value("ai", "api_key", default="")
                kwargs["base_url"] = get_yaml_value("ai", "api_url", default="https://api.deepseek.com/v1")
                kwargs["model"] = get_yaml_value("ai", "api_model", default="deepseek-chat")
            else:
                # 非 API 后端不支持 deep_analyze → 让标准路径处理
                return ""

            client = create_llm_client(backend, **kwargs)
            if not client.available:
                logger.info("AI 深度分析: %s 不可用，回退标准分析", client.name)
                return ""

            with _TPE(max_workers=1) as _pool:
                _fut = _pool.submit(client.deep_analyze, llm_data)
                result = _fut.result(timeout=30)
            if result and result.strip():
                logger.info("AI 深度分析: %s 生成成功", client.name)
                return result.strip()
        except _TO:
            logger.warning("AI 深度分析: LLM 超时 (30s)，回退标准分析")
        except Exception:
            logger.debug("AI 深度分析: LLM 异常，回退标准分析", exc_info=True)
        return ""

    def _generate_template_summary(self, data: ReportData, d: dict) -> str:
        """v4.26: 增强版内置模板分析"""
        import html as _html

        avg = d["avg_focus"]
        # v4.37: 检测日汇总
        is_daily = bool(data.session and data.session.session_id.startswith("daily_"))
        parts = []

        # ── 整体评价 ──
        label = "当日" if is_daily else "本次会话"
        if avg >= 80:
            parts.append(f"{label}专注度 {avg:.0f} 分，表现优秀。")
        elif avg >= 65:
            parts.append(f"{label}专注度 {avg:.0f} 分，整体良好。")
        elif avg >= 50:
            parts.append(f"{label}专注度 {avg:.0f} 分，处于中等水平。")
        else:
            parts.append(f"{label}专注度 {avg:.0f} 分，偏低。")

        # ── 历史对比 ──
        hist = d.get("hist_avg_focus", 0)
        if hist and abs(avg - hist) > 3:
            parts.append(
                f"{'高于' if avg > hist else '低于'}近期平均 ({hist:.0f} 分)"
                f"，差值 {abs(avg - hist):.0f} 分。")

        # ── 趋势 ──
        s, e = d["seg_start"], d["seg_end"]
        if abs(s - e) > 8:
            if s > e:
                parts.append(f"前半段高于后半段 {s-e:.0f} 分，中途可能需要安排一次休息。")
            else:
                parts.append("后半段专注度上升，状态渐入佳境。")

        # ── 疲劳 ──
        hp = d["fatigue_high_pct"]
        if hp > 30:
            parts.append(f"高疲劳占比 {hp:.0f}%，疲劳信号较多，建议保证睡眠。")
        elif hp > 10:
            parts.append("有间歇性疲劳信号，注意定时起身眨眼。")

        # ── 分心 ──
        dc = d["distractions"]
        if dc > 8:
            cause = "头部偏移是主要原因" if d["head_pct"] >= d["gaze_pct"] else "视线偏离是主要因素"
            parts.append(f"分心 {dc} 次偏多（{cause}），可尝试关闭通知或使用番茄钟。")
        elif dc > 3:
            parts.append(f"分心 {dc} 次。")

        # ── 时长 ──
        dur = d["duration"]
        if is_daily:
            if dur >= 90:
                parts.append(f"当日累计工作 {dur} 分钟（多会话），注意规律休息。")
        else:
            if dur >= 90:
                parts.append(f"连续工作 {dur} 分钟，注意规律休息。")

        # ── 建议 ──
        suggestions = []
        if avg < 55:
            suggestions.append("缩短单次工作时长，配合番茄钟提高专注。")
        if hp > 20:
            suggestions.append("每小时起身活动 2 分钟，缓解疲劳累积。")
        if dc > 10:
            suggestions.append("分心偏多，尝试关闭通知、使用降噪耳机。")
        if dur > 120 and avg < 60:
            suggestions.append("长时间低效不如短时高效，试试 45 分钟深度工作。")
        if suggestions:
            parts.append("建议：" + "".join(suggestions))

        return "。" if not parts else _html.escape("".join(parts))

    def _render_insights_tab(self, insights: List[Insight]) -> str:
        """v4.29: 建议 Tab — 模板个性化建议（已移除 AI 对话/分析摘要/图表）"""
        parts = []

        # ── 个性化建议（模板引擎生成） ──
        insights_html = self._render_insights(insights) if insights else ""
        if insights_html:
            parts.append(f'''
                <div class="card">
                    <h2>💡 个性化建议</h2>
                    <p class="card-desc">基于本会话数据生成的多维分析与改善建议</p>
                    {insights_html}
                </div>''')
        else:
            parts.append('''
                <div class="card">
                    <h2>💡 个性化建议</h2>
                    <div class="no-data">本次会话表现良好，未检测到需要调整的问题</div>
                </div>''')

        return "\n".join(parts)

    # ── v4.26: 下一步行动面板 ──

    def _render_next_steps(self) -> str:
        """渲染下一步行动面板"""
        return """
        <div class="next-steps">
            <h2>⏭ 下一步</h2>
            <div class="next-step-item">
                <span class="step-icon">📊</span>
                <span>开始一次新的专注监测会话</span>
            </div>
            <div class="next-step-item">
                <span class="step-icon">📈</span>
                <span>查看数据分析 Tab 了解详细趋势</span>
            </div>
            <div class="next-step-item">
                <span class="step-icon">⚙</span>
                <span>调整监测设置优化专注体验</span>
            </div>
        </div>
        """

    def _calc_session_avg_focus(self, session_id: str):
        """获取会话平均专注度"""
        try:
            records = self.db.get_focus_records(session_id) if self.db else []
            if records:
                scores = [r.focus_score for r in records if r.focus_score is not None]
                if scores:
                    return round(sum(scores) / len(scores), 0)
        except Exception:
            pass
        return None

    def _render_about_tab(self, session_id: str = "") -> str:
        """渲染关于 Tab (v4.18: +最近会话)"""
        safe_sid = html_escape(session_id)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # v4.18: 最近会话列表
        recent_html = ""
        try:
            if self.db:
                sessions = self.db.list_sessions()[:8]
                if sessions:
                    rows = ""
                    for s in sessions:
                        dur = s.duration_seconds()
                        dur_str = f"{int(dur//60)}分钟" if dur else "--"
                        d = s.start_time.strftime("%m-%d %H:%M")
                        sid_short = s.session_id[:8]
                        avg = self._calc_session_avg_focus(s.session_id)
                        icon = "🟢" if (avg and avg >= 70) else "🟡" if (avg and avg >= 40) else "⚪"
                        cal = "✓" if s.is_calibrated else ""
                        rows += f"<tr><td>{icon}</td><td>{d}</td><td>{dur_str}</td><td>{avg or '--'}</td><td style='color:#ccc;font-size:10px;'>{sid_short}{cal}</td></tr>"
                    recent_html = f"""
            <div class="card">
                <h2>📋 最近会话</h2>
                <table class="detail-table">
                    <tr><th style="text-align:left;color:var(--quiet);font-weight:500;font-size:11px;"></th>
                        <th style="text-align:left;color:var(--quiet);font-weight:500;font-size:11px;">时间</th>
                        <th style="text-align:left;color:var(--quiet);font-weight:500;font-size:11px;">时长</th>
                        <th style="text-align:left;color:var(--quiet);font-weight:500;font-size:11px;">专注度</th>
                        <th style="text-align:left;color:var(--quiet);font-weight:500;font-size:11px;">ID</th></tr>
                    {rows}
                </table>
            </div>"""
        except Exception:
            pass

        return f"""
            <div class="card">
                <h2>EyeFocus Insight</h2>
                <p style="color:#666;font-size:14px;line-height:1.8;margin-bottom:16px;">
                    EyeFocus Insight 是一款基于计算机视觉的专注度监测与分析系统。
                    利用 MediaPipe Face Landmarker 实时追踪人脸 478 个关键点，
                    结合眼部纵横比 (EAR) 与 Blendshape 多信号融合算法，
                    实现高精度的眼部状态检测和疲劳分析。
                </p>
            </div>

            <div class="card">
                <h2>核心技术</h2>
                <div class="about-grid">
                    <div class="about-card">
                        <div class="ac-title">MediaPipe Face Landmarker</div>
                        <div class="ac-desc">478 个面部关键点实时追踪，52 种面部表情系数 (Blendshape) 输出</div>
                    </div>
                    <div class="about-card">
                        <div class="ac-title">多信号融合眼部检测</div>
                        <div class="ac-desc">Blendshape 主信号 + EAR 备选，对头部姿态变化不敏感，准确率 99%+</div>
                    </div>
                    <div class="about-card">
                        <div class="ac-title">离线分析引擎</div>
                        <div class="ac-desc">KMeans 聚类、PELT 变点检测、IsolationForest 异常检测、STL 时序分解</div>
                    </div>
                    <div class="about-card">
                        <div class="ac-title">多维度报告</div>
                        <div class="ac-desc">专注度趋势、疲劳分析、眨眼检测、高效时段分析、异常会话检测</div>
                    </div>
                </div>
            </div>

            {recent_html}

            <div class="card">
                <h2>技术栈</h2>
                <div>
                    <span class="tech-badge">Python 3.12</span>
                    <span class="tech-badge">MediaPipe 0.10</span>
                    <span class="tech-badge">PyQt5</span>
                    <span class="tech-badge">OpenCV</span>
                    <span class="tech-badge">NumPy</span>
                    <span class="tech-badge">SciPy</span>
                    <span class="tech-badge">scikit-learn</span>
                    <span class="tech-badge">Matplotlib</span>
                    <span class="tech-badge">SQLite</span>
                    <span class="tech-badge">PyTorch (CUDA 12.8)</span>
                </div>
            </div>

            <div class="card">
                <h2>会话详情</h2>
                <table class="detail-table">
                    <tr><td>会话 ID</td><td>{safe_sid}</td></tr>
                    <tr><td>检测引擎</td><td>MediaPipe Face Landmarker (GPU)</td></tr>
                    <tr><td>校准方式</td><td>个人基线校准 (EAR + 头位)</td></tr>
                    <tr><td>生成时间</td><td>{now_str}</td></tr>
                </table>
            </div>
        """

    def _render_insights(self, insights: List[Insight]) -> str:
        """v4.38: 渲染建议列表，>5 条时 Top 5 优先展示，其余折叠"""
        if not insights:
            return ""

        _ALLOWED_SEVERITY = {"info", "warning", "alert"}
        folded = len(insights) > 5
        visible = insights[:5] if folded else insights
        hidden = insights[5:] if folded else []

        def _render_items(ins_list):
            items = []
            for insight in ins_list:
                severity_class = (
                    insight.severity if insight.severity in _ALLOWED_SEVERITY else "info"
                )
                safe_title = html_escape(insight.title)
                safe_description = html_escape(insight.description)
                safe_suggestion = html_escape(insight.suggestion)
                badge_html = f'<span class="severity-badge {severity_class}">{severity_class.upper()}</span>'
                items.append(f"""
                    <li class="insight-item {severity_class}">
                        <div class="title">{badge_html}{safe_title}</div>
                        <div class="description">{safe_description}</div>
                        <div class="suggestion">💡 {safe_suggestion}</div>
                    </li>
                """)
            return "\n".join(items)

        html = f"<ul class='insights-list'>\n{_render_items(visible)}\n</ul>"
        if hidden:
            hidden_html = _render_items(hidden)
            html += (
                f"\n<details class='insights-fold'>"
                f"<summary>📋 更多 {len(hidden)} 条建议</summary>"
                f"<ul class='insights-list'>{hidden_html}</ul>"
                f"</details>"
            )
        return html

    def _render_insight_items(self, insights: List[Insight]) -> str:
        """v4.38: 渲染建议 <li> 项，>5 条时折叠其余"""
        if not insights:
            return ""
        _ALLOWED_SEVERITY = {"info", "warning", "alert"}
        folded = len(insights) > 5
        visible = insights[:5] if folded else insights
        hidden = insights[5:] if folded else []

        def _li(items_list):
            result = []
            for insight in items_list:
                severity_class = (
                    insight.severity if insight.severity in _ALLOWED_SEVERITY else "info"
                )
                safe_title = html_escape(insight.title)
                safe_description = html_escape(insight.description)
                safe_suggestion = html_escape(insight.suggestion)
                badge_html = f'<span class="severity-badge {severity_class}">{severity_class.upper()}</span>'
                result.append(f"""
                <li class="insight-item {severity_class}">
                    <div class="title">{badge_html}{safe_title}</div>
                    <div class="description">{safe_description}</div>
                    <div class="suggestion">💡 {safe_suggestion}</div>
                </li>""")
            return "\n".join(result)

        html = _li(visible)
        if hidden:
            html += (f"\n<details class='insights-fold'>"
                     f"<summary>📋 更多 {len(hidden)} 条建议</summary>"
                     f"<ul class='insights-list'>{_li(hidden)}</ul>"
                     f"</details>")
        return html

    def _render_charts(self, charts: dict) -> dict:
        """将图表数据转换为 HTML。

        v4.16: Plotly 图表输出为 HTML 字符串，直接嵌入。
        输入 charts 结构 (来自 _generate_charts):
            {name: {"data": html_str | None, "error": str | None}}
        """
        result = {}
        for name, info in charts.items():
            data = info.get("data") if isinstance(info, dict) else None
            error = info.get("error") if isinstance(info, dict) else None
            if error:
                result[name] = (
                    f'<div class="chart-error">'
                    f'图表生成失败 ({name}): {error}'
                    f'</div>'
                )
            elif data:
                # v4.16: data 是 Plotly HTML 字符串或纯 HTML
                result[name] = (
                    f'<div class="chart-container">'
                    f'{data}'
                    f'</div>'
                )
            else:
                result[name] = '<div class="no-data">无数据</div>'
        return result

    def _bytes_to_base64(self, data: bytes) -> str:
        """将字节数据转换为 base64 字符串"""
        return base64.b64encode(data).decode('utf-8')

    def _calc_avg_focus(self, focus_records: List[FocusRecord]) -> float:
        """v4.35: 时间加权平均专注度（非简单记录数平均）

        每个记录的权重 = window_end - window_start（秒）。
        采样不均匀时（人脸丢失恢复/间隙），长窗口段自然占更大权重。
        均匀采样下等价于简单平均。
        """
        if not focus_records:
            return 0.0
        total_weight = 0.0
        weighted_sum = 0.0
        for r in focus_records:
            if r.focus_score is not None:
                dt = max(1.0, (r.window_end or 0) - (r.window_start or 0))
                weighted_sum += r.focus_score * dt
                total_weight += dt
        if total_weight <= 0:
            return 0.0
        return weighted_sum / total_weight

    def _calc_avg_blink_rate(self, focus_records: List[FocusRecord]) -> float:
        """计算平均眨眼频率（过滤 None 值）"""
        if not focus_records:
            return 0.0
        rates = [r.blink_rate for r in focus_records if r.blink_rate is not None]
        if not rates:
            return 0.0
        return sum(rates) / len(rates)

    def _determine_fatigue_level(self, fatigue_records: List[FatigueRecord]) -> FatigueLevel:
        """确定主要疲劳等级"""
        if not fatigue_records:
            return FatigueLevel.LOW

        # 统计各等级出现次数
        level_counts = {FatigueLevel.LOW: 0, FatigueLevel.MEDIUM: 0, FatigueLevel.HIGH: 0}
        for record in fatigue_records:
            level_counts[record.fatigue_level] = level_counts.get(record.fatigue_level, 0) + 1

        # 返回出现最多的等级
        return max(level_counts, key=level_counts.get)

    # ── v4.1 Insights 集成 ──────────────────────────────────

    # ════════════════════════════════════════════
    # v4.18: 周报
    # ════════════════════════════════════════════
    def generate_weekly_report(self) -> str:
        """生成最近 7 天的周报

        Returns:
            HTML 字符串
        """
        if not self.db:
            return self._error_html("数据库未初始化")

        from datetime import datetime, timedelta
        today = datetime.now()
        week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")

        sessions = self.db.get_sessions_by_date_range(week_ago, today_str)
        if len(sessions) < 2:
            return self._error_html("本周数据不足（至少需要 2 个会话才能生成周报）")

        # 按天聚合统计（v4.30）
        from collections import defaultdict
        day_groups = defaultdict(list)
        for sess in sessions:
            if sess.end_time is None:
                continue
            day_key = sess.start_time.strftime("%Y-%m-%d")
            day_groups[day_key].append(sess)

        if not day_groups:
            return self._error_html("本周无已完成会话")

        total_minutes = 0.0
        session_list = []
        for day_key in sorted(day_groups, reverse=True):
            day_sessions = day_groups[day_key]
            day_dur = 0.0
            day_scores = []
            for sess in day_sessions:
                dur = sess.duration_seconds() or 0.0
                day_dur += dur
                records = self.db.get_focus_records(sess.session_id)
                if records:
                    for r in records:
                        if r.focus_score is not None:
                            day_scores.append(r.focus_score)
            total_minutes += day_dur / 60.0
            day_avg = sum(day_scores) / len(day_scores) if day_scores else 0.0
            from datetime import datetime as _dt
            session_list.append({
                "date": _dt.strptime(day_key, "%Y-%m-%d").strftime("%m-%d"),
                "duration": day_dur / 60.0,
                "score": day_avg,
                "count": len(day_sessions),
            })

        avg_score = sum(s["score"] for s in session_list) / max(1, len(session_list))
        days_active = len(session_list)

        # 日历热力图数据
        all_stats = self.db.get_all_daily_stats()
        daily_list = [
            {"date": s.date, "minutes": s.total_focus_minutes}
            for s in all_stats
        ]

        # 生成日历热力图
        cal_html = ""
        try:
            cal_html = self.chart_gen.generate_calendar_heatmap(daily_list)
        except Exception as e:
            logger.warning("周报日历图失败: %s", e)

        # 构建 HTML
        rows = "".join(
            f'<tr><td>{s["date"]}</td>'
            f'<td>{s["duration"]:.0f}分钟</td>'
            f'<td>{s["score"]:.0f}分</td>'
            f'<td style="color:var(--quiet);font-size:12px;">×{s["count"]}</td></tr>'
            for s in session_list[:7]
        )

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>专注周报 - {week_ago} ~ {today_str}</title>
<style>
    :root {{ --bg: #FEFDFB; --ink: #23201E; --quiet: #8B8680; --line: #E6E2DC;
             --iris: #5B4A8C; --sage: #5A8A6D; --amber: #C9843A; --rose: #B55C5C; }}
    body {{ font-family: "Microsoft YaHei","Segoe UI",sans-serif; background: var(--bg);
           color: var(--ink); max-width: 720px; margin: 0 auto; padding: 32px 20px; }}
    h1 {{ font-family: Georgia,serif; font-size: 28px; font-weight: 400;
          margin-bottom: 4px; color: var(--ink); }}
    .subtitle {{ color: var(--quiet); font-size: 13px; margin-bottom: 28px; }}
    .hero {{ display: flex; gap: 24px; margin-bottom: 28px; flex-wrap: wrap; }}
    .hero-item {{ text-align: center; flex: 1; min-width: 80px; }}
    .hero-item .num {{ font-family: Georgia,serif; font-size: 36px; color: var(--iris); }}
    .hero-item .lbl {{ font-size: 11px; color: var(--quiet); margin-top: 2px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin: 16px 0; }}
    th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--line); }}
    th {{ color: var(--quiet); font-size: 11px; font-weight: 500; }}
    .footer {{ text-align: center; color: #ccc; font-size: 11px; margin-top: 36px; }}
</style></head><body>
    <h1>📊 专注周报</h1>
    <p class="subtitle">{week_ago} ~ {today_str}</p>

    <div class="hero">
        <div class="hero-item"><div class="num">{total_minutes:.0f}</div><div class="lbl">总专注(分钟)</div></div>
        <div class="hero-item"><div class="num">{avg_score:.0f}</div><div class="lbl">平均专注度</div></div>
        <div class="hero-item"><div class="num">{sum(s["count"] for s in session_list)}</div><div class="lbl">总会话</div></div>
        <div class="hero-item"><div class="num">{days_active}</div><div class="lbl">活跃天数</div></div>
    </div>

    <h2 style="font-size:16px;font-weight:400;border-bottom:1px solid var(--line);padding-bottom:8px;">📅 专注日历</h2>
    <div style="margin:12px 0;">{cal_html}</div>

    <h2 style="font-size:16px;font-weight:400;border-bottom:1px solid var(--line);padding-bottom:8px;">📋 每日明细</h2>
    <table><tr><th>日期</th><th>时长</th><th>专注度</th><th>会话</th></tr>{rows}</table>

    <div class="footer">EyeFocus Insight · 自动生成</div>
</body></html>"""
        return html

    def generate_report_with_insights(
        self,
        session_id: str,
        insights_result: Optional["_InsightsResult"] = None,
    ) -> str:
        """生成含离线分析章节的 HTML 报告 (v4.9: Tab 布局兼容)。

        Args:
            session_id: 会话 ID
            insights_result: 可选，Insights Pipeline 结果（为 None 时自动运行）

        Returns:
            HTML 字符串
        """
        # v4.36: plotly.min.js 已内联，无需复制外部文件
        if not HAS_INSIGHTS:
            return self.generate_report(session_id)
        if not self.db:
            return self._error_html("数据库管理器未初始化")

        if insights_result is None:
            from analyzer.insights import run_pipeline
            try:
                insights_result = run_pipeline(self.db, session_id)
            except Exception as e:
                logger.warning("Insights pipeline 运行失败: %s — 回退到基础报告", e)
                return self._inject_insights_notice(
                    self.generate_report(session_id), str(e))

        # 1. 获取会话数据
        session = self.db.get_session(session_id)
        if not session:
            return self._error_html(f"未找到会话: {session_id}")
        focus_records = self.db.get_focus_records(session_id)
        fatigue_records = self.db.get_fatigue_records(session_id)
        blink_records = self.db.get_blink_events(session_id)
        # v4.13: 帧记录（头姿散点图用）
        all_frames = self.db.get_frame_records(session_id)
        frame_records = all_frames[::max(1, len(all_frames) // 500)] if len(all_frames) > 500 else all_frames

        avg_focus = self._calc_avg_focus(focus_records)
        avg_blink_rate = self._calc_avg_blink_rate(focus_records)
        total_duration = session.duration_seconds() or 0.0
        fatigue_level = self._determine_fatigue_level(fatigue_records)

        report_data = ReportData(
            session=session, focus_records=focus_records,
            fatigue_records=fatigue_records, blink_records=blink_records,
            frame_records=frame_records,
            avg_focus=avg_focus, avg_blink_rate=avg_blink_rate,
            total_duration=total_duration, fatigue_level=fatigue_level,
        )

        # 2. 生成常规图表
        charts = self._generate_charts(report_data)

        # 3. 生成 insights 图表
        insight_charts_data = self._generate_insights_charts(insights_result)

        # 4. 分心热力图
        distraction_result = None
        distraction_html = None
        try:
            from analyzer.distraction import analyze_distraction
            distraction_result = analyze_distraction(self.db, session_id)
            if distraction_result.detected:
                from reporter.charts import create_chart_generator
                cg = create_chart_generator()
                raw = cg.generate_distraction_heatmap(
                    distraction_result.heatmap,
                    distraction_result.heatmap_labels,
                    pattern_type=distraction_result.pattern_description or "",
                )
                # v4.16: Plotly 返回 HTML 字符串
                distraction_html = raw if isinstance(raw, str) else self._bytes_to_base64(raw)
        except Exception as e:
            logger.warning("分心热力图生成失败: %s", e)

        # 5. 渲染 insights 章节 HTML → 放入 charts dict
        charts["insights_charts"] = self._render_insights_sections(
            insights_result, insight_charts_data,
            distraction_result=distraction_result,
            distraction_html=distraction_html,
        )

        # v4.39: 查询同日其他会话
        same_day_sessions = []
        try:
            today_str = session.start_time.strftime("%Y-%m-%d")
            same_day_sessions = self.db.get_sessions_by_date_range(
                today_str, today_str) if self.db else []
        except Exception:
            pass

        # 6. 规则引擎建议 + attribution 发现
        rule_insights = self.insights_engine.analyze(
            focus_records=focus_records, fatigue_records=fatigue_records,
            avg_focus=avg_focus, avg_blink_rate=avg_blink_rate,
            session_duration=total_duration,
            session_id=session_id,
            session_start_time=session.start_time.timestamp(),
            blink_records=blink_records,
            same_day_sessions=same_day_sessions,
        )
        if insights_result.attribution_findings:
            try:
                from reporter.insights import attribution_findings_to_insights
                attr_list = attribution_findings_to_insights(
                    insights_result.attribution_findings)
                rule_insights.extend(attr_list)
            except Exception:
                pass

        # 7. 用新 Tab 布局渲染
        return self._render_html(report_data, charts, rule_insights)

    @staticmethod
    def _inject_insights_notice(html: str, error: str = "") -> str:
        """v4.26: 在基础报告中注入 insights 不可用提示"""
        notice = (
            '<div class="card" style="border-left:2px solid var(--amber-600);">'
            '<h2>📊 高级分析暂不可用</h2>'
            '<div class="card-desc">'
            '离线数据分析管道未能完成。'
            f'{f" 原因: {html_escape(error)}" if error else ""}'
            '<br>查看常规指标和图表了解本次会话概况。'
            '</div></div>'
        )
        return html.replace(
            '<div class="tab-bar">',
            f'{notice}<div class="tab-bar">'
        )

    def _generate_insights_charts(self, insights: "_InsightsResult") -> dict:
        """生成 insights 章节所需的 4 个图表。"""
        charts = {}

        def _safe_chart(name: str, gen_fn):
            try:
                raw = gen_fn()
                # v4.16: Plotly 返回 HTML 字符串
                if isinstance(raw, bytes):
                    charts[name] = {"data": self._bytes_to_base64(raw), "error": None}
                else:
                    charts[name] = {"data": raw, "error": None}
            except Exception as e:
                logger.warning("insights 图表 %s 失败: %s", name, e)
                charts[name] = {"data": None, "error": str(e)}

        # 1. 聚类饼图
        if insights.patterns_result:
            _safe_chart("pattern_pie", lambda: self.chart_gen.generate_pattern_pie_chart(
                insights.patterns_result.get("pattern_labels", {}),
                insights.patterns_result.get("cluster_sizes", []),
            ))
        else:
            charts["pattern_pie"] = {"data": None, "error": None}

        # 2. 异常因子条形图
        if insights.anomaly_result and insights.anomaly_result.get("top_factors"):
            _safe_chart("anomaly_bar", lambda: self.chart_gen.generate_anomaly_bar_chart(
                insights.anomaly_result["top_factors"],
            ))
        else:
            charts["anomaly_bar"] = {"data": None, "error": None}

        # 3. 时序折线图
        if insights.temporal_result and insights.temporal_result.get("hourly_pattern"):
            _safe_chart("temporal_line", lambda: self.chart_gen.generate_temporal_line_chart(
                insights.temporal_result["hourly_pattern"],
                insights.temporal_result.get("peak_hours", []),
                insights.temporal_result.get("low_hours", []),
            ))
        else:
            charts["temporal_line"] = {"data": None, "error": None}

        # 4. 关联分析条形图
        if insights.attribution_findings:
            _safe_chart("attribution_bar", lambda: self.chart_gen.generate_attribution_bar_chart(
                insights.attribution_findings,
            ))
        else:
            charts["attribution_bar"] = {"data": None, "error": None}

        return charts

    def _render_insights_sections(
        self,
        insights: "_InsightsResult",
        charts: dict,
        distraction_result=None,
        distraction_html: str = "",
    ) -> str:
        """渲染 4+1 个 insights HTML 章节。"""
        sections = []

        def _chart_html(name: str, title: str, desc: str = "") -> str:
            info = charts.get(name, {})
            data = info.get("data") if isinstance(info, dict) else None
            error = info.get("error") if isinstance(info, dict) else None
            if error:
                return f'<div class="chart-error">图表生成失败: {error}</div>'
            elif data:
                # v4.16: Plotly 返回 HTML 字符串，直接嵌入
                if isinstance(data, str) and ('plotly' in data.lower() or '<div' in data):
                    return f'<div class="chart-container">{data}</div>'
                # 兼容旧 base64 PNG
                return (
                    f'<div class="chart-container">'
                    f'<img src="data:image/png;base64,{data}" alt="{title}">'
                    f'</div>'
                )
            return '<div class="no-data">数据不足，暂不展示</div>'

        # 章节 1: 工作模式聚类
        pr = insights.patterns_result
        if pr:
            sizes = pr.get("cluster_sizes", [])
            labels = pr.get("pattern_labels", {})
            summary = (
                f"共发现 {pr.get('n_clusters', 0)} 种工作模式，"
                f"轮廓系数 {pr.get('silhouette', 0):.3f}。"
            )
            sections.append(f"""
        <div class="card">
            <h2>📊 工作模式分析</h2>
            <p style="color:#666;margin-bottom:10px;">{summary}</p>
            {_chart_html("pattern_pie", "工作模式分布")}
            <ul style="color:#666;font-size:13px;">
                {"".join(f'<li>{l}</li>' for l in labels.values())}
            </ul>
        </div>""")

        # 章节 2: 异常检测
        ar = insights.anomaly_result
        if ar and ar.get("anomaly_count", 0) > 0:
            factors = ar.get("top_factors", [])
            factors_html = "、".join(f"<strong>{f}</strong>" for f in factors) if factors else "无显著异常因子"
            sections.append(f"""
        <div class="card">
            <h2>🔍 异常会话检测</h2>
            <p style="color:#666;margin-bottom:10px;">
                在 {ar.get('n_sessions', 0)} 个历史会话中发现
                <span style="color:#dc3545;font-weight:bold;">{ar.get('anomaly_count', 0)}</span>
                个异常会话。主要异常特征：{factors_html}
            </p>
            {_chart_html("anomaly_bar", "异常因子")}
        </div>""")

        # 章节 3: 时序分解
        tr = insights.temporal_result
        if tr:
            peak_text = "、".join(tr.get("peak_hours", [])) if tr.get("peak_hours") else "未检测到明显高效时段"
            low_text = "、".join(tr.get("low_hours", [])) if tr.get("low_hours") else "未检测到明显低效时段"
            method_label = "STL 分解" if tr.get("method") == "stl" else "直方图分析"
            sections.append(f"""
        <div class="card">
            <h2>⏰ 高效时段分析</h2>
            <p style="color:#666;margin-bottom:10px;">
                基于 {tr.get('n_days', 0)} 天数据（{method_label}），
                高效时段：<span style="color:#28a745;font-weight:bold;">{peak_text}</span> ｜
                低效时段：<span style="color:#dc3545;font-weight:bold;">{low_text}</span>
            </p>
            {_chart_html("temporal_line", "日内专注度模式")}
        </div>""")

        # 章节 4: 关联分析
        afs = insights.attribution_findings
        if afs:
            findings_html = "".join(
                f'<li style="margin-bottom:8px;padding:8px;background:#f8f9fa;'
                f'border-radius:6px;border-left:3px solid #667eea;">'
                f'<strong>{f.get("factor", "未知因子")}</strong>：{f.get("summary", "")}'
                f' (p={f.get("p_value", 0):.3f})</li>'
                for f in afs
            )
            sections.append(f"""
        <div class="card">
            <h2>📈 关联分析</h2>
            <p style="color:#666;margin-bottom:10px;">以下因素与专注度存在统计显著关联：</p>
            {_chart_html("attribution_bar", "关联分析")}
            <ul style="list-style:none;padding:0;">
                {findings_html}
            </ul>
        </div>""")

        # 章节 5: 分心分析（可选）
        if distraction_result and distraction_result.detected:
            pattern_info = distraction_result.pattern_description or "无显著模式"
            sections.append(f"""
        <div class="card">
            <h2>👀 分心分析</h2>
            <p style="color:#666;margin-bottom:10px;">
                检测到 <span style="color:#dc3545;font-weight:bold;">{distraction_result.total_events}</span>
                次分心事件（总分心 {distraction_result.total_distraction_seconds:.0f} 秒），
                短分心 {distraction_result.short_events} 次、
                中分心 {distraction_result.medium_events} 次、
                长分心 {distraction_result.long_events} 次。
            </p>
            <p style="color:#666;font-size:13px;margin-bottom:10px;">📌 {pattern_info}</p>
            {f'<div class="chart-container">{distraction_html}</div>' if distraction_html else '<div class="no-data">无数据</div>'}
        </div>""")

        return "\n".join(sections)

    def _format_duration(self, seconds: float) -> str:
        """格式化时长（自动按小时/分钟/秒分级）"""
        if seconds <= 0:
            return "0秒"
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}小时{minutes}分"
        if minutes > 0:
            return f"{minutes}分{secs}秒"
        return f"{secs}秒"

    def _get_stat_class(self, value: float, good_threshold: float, warning_threshold: float) -> str:
        """获取统计样式类"""
        if value >= good_threshold:
            return "good"
        elif value >= warning_threshold:
            return "warning"
        return "danger"

    def _get_blink_stat_class(self, blink_rate: float) -> str:
        """获取眨眼频率样式类"""
        if blink_rate < 20:
            return "good"
        elif blink_rate < 30:
            return "warning"
        return "danger"

    def _render_insufficient_data(self, session_id: str) -> str:
        """数据不足时的占位页面"""
        safe_sid = html_escape(session_id)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>数据收集中 - EyeFocus Insight</title>
    {self.CSS_STYLE}
    <style>
        .collecting {{
            text-align: center; padding: 80px 20px; background: white;
            border-radius: 12px; margin-top: 20px;
        }}
        .collecting .icon {{ font-size: 64px; margin-bottom: 20px; }}
        .collecting h2 {{ font-size: 22px; color: #444; margin-bottom: 12px; }}
        .collecting p {{ font-size: 15px; color: #999; line-height: 1.8; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>EyeFocus Insight 专注度分析报告</h1>
            <div class="subtitle">会话 ID: {safe_sid} | 生成时间: {now_str}</div>
        </div>
        <div class="collecting">
            <div class="icon">⏳</div>
            <h2>数据收集中</h2>
            <p>
                当前会话数据尚不足（< 2 个采样周期），请稍后查看。<br>
                监测运行约 1 分钟后数据将自动可用。<br><br>
                提示：点击"打开报告"<strong>不会中断正在进行的监测</strong>，
                您可以随时回来查看最新数据。
            </p>
            <p style="margin-top:16px;font-size:13px;color:#bbb;">
                继续监测，待数据充足后重新点击"打开报告"
            </p>
        </div>
        <div class="footer">EyeFocus Insight | 自动生成的专注度分析报告</div>
    </div>
</body>
</html>"""

    def _error_html(self, message: str) -> str:
        """错误页面 HTML（message 经过 HTML 转义防 XSS）"""
        from html import escape as _html_escape
        return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>错误 - EyeFocus 报告</title>
    <style>
        body {{ font-family: sans-serif; padding: 40px; text-align: center; }}
        .error {{ color: #dc3545; font-size: 24px; margin-bottom: 20px; }}
        .message {{ color: #666; }}
    </style>
</head>
<body>
    <div class="error">⚠ 生成报告时出错</div>
    <div class="message">{_html_escape(message)}</div>
</body>
</html>
"""


# v4.36: 类定义后内联 plotly.min.js，使报告 100% 离线可用
try:
    HTMLReportGenerator.PLOTLY_JS = HTMLReportGenerator._load_plotly_js()
except Exception as _e:
    logger.warning("plotly.min.js 内联失败，使用外部引用: %s", _e)


def create_html_generator(
    db_manager: Optional[DatabaseManager] = None,
) -> HTMLReportGenerator:
    """工厂函数：创建 HTML 报告生成器"""
    return HTMLReportGenerator(db_manager=db_manager)

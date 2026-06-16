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
from dataclasses import dataclass
from datetime import datetime
from html import escape as html_escape
from io import BytesIO
from typing import List, Optional

from storage.db import DatabaseManager
from storage.models import FocusRecord, FatigueRecord, FatigueLevel, BlinkRecord, Session

from reporter.charts import ChartGenerator, create_chart_generator
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
    """报告数据容器 (v4.13: +frame_records)"""
    session: Session
    focus_records: List[FocusRecord]
    fatigue_records: List[FatigueRecord]
    blink_records: List[BlinkRecord]
    frame_records: List  # v4.13: FrameRecord 列表（头姿散点图用）
    avg_focus: float
    avg_blink_rate: float
    total_duration: float
    fatigue_level: FatigueLevel


class HTMLReportGenerator:
    """HTML 报告生成器

    使用方法：
        generator = HTMLReportGenerator(db_manager)
        html_content = generator.generate_report(session_id)
    """

    # CSS 样式 (v4.8: 多 Tab 布局)
    CSS_STYLE = """
        <style>
            /* ═══════════════════════════════════════
               Quiet Focus · 精密仪器美学
               Palette: Warm Ink · Stone · Iris · Sage
               ═══════════════════════════════════════ */
            :root {
                --ink: #23201E;
                --stone: #F4F2EE;
                --card: #FEFDFB;
                --iris: #5B4A8C;
                --sage: #5A8A6D;
                --amber: #C9843A;
                --rose: #B55C5C;
                --quiet: #8B8680;
                --line: #E6E2DC;
                --line-light: #F0EDE8;
            }
            * { margin: 0; padding: 0; box-sizing: border-box; }

            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif;
                line-height: 1.55; color: var(--ink); background: var(--stone);
                padding: 32px 20px; -webkit-font-smoothing: antialiased;
            }
            .container { max-width: 780px; margin: 0 auto; }

            /* ── Header · 顶部 Iris accent 条 ── */
            .header {
                padding: 0 0 28px 0; margin-bottom: 0;
                border-bottom: 1px solid var(--line);
                position: relative;
            }
            .header::before {
                content: ''; display: block; width: 100%; height: 3px;
                background: var(--iris); margin-bottom: 24px;
            }
            .header h1 {
                font-family: Georgia, 'Times New Roman', 'SimSun', serif;
                font-size: 22px; font-weight: 400; color: var(--ink);
                letter-spacing: -0.3px; margin-bottom: 4px;
            }
            .header .subtitle {
                font-size: 12px; color: var(--quiet); font-weight: 400;
            }

            /* ── Tab 导航 · 文字+下划线 ── */
            .tab-bar {
                display: flex; gap: 28px; padding: 14px 0; margin-bottom: 24px;
                border-bottom: 1px solid var(--line); overflow-x: auto;
                -webkit-overflow-scrolling: touch;
            }
            .tab-btn {
                padding: 4px 0; border: none; background: none; cursor: pointer;
                font-size: 13px; color: var(--quiet); font-weight: 500;
                font-family: inherit; position: relative; transition: color 0.15s;
                white-space: nowrap; letter-spacing: 0.1px;
            }
            .tab-btn:hover { color: var(--ink); }
            .tab-btn.active { color: var(--iris); }
            .tab-btn.active::after {
                content: ''; position: absolute; bottom: -15px; left: 0; right: 0;
                height: 2px; background: var(--iris); border-radius: 1px;
            }
            .tab-content { display: none; }
            .tab-content.active { display: block; }

            /* ── Hero 数字 · Iris 环形装饰 ── */
            .focus-hero {
                text-align: center; padding: 40px 0 32px; position: relative;
            }
            .focus-hero .hero-ring {
                width: 140px; height: 140px; border-radius: 50%;
                border: 1px solid var(--line);
                position: absolute; top: 50%; left: 50%;
                transform: translate(-50%, -50%);
                pointer-events: none;
            }
            .focus-hero .hero-ring::after {
                content: ''; width: 152px; height: 152px; border-radius: 50%;
                border: 1px solid var(--line-light);
                position: absolute; top: -7px; left: -7px;
            }
            .focus-hero .hero-value {
                font-family: Georgia, 'Times New Roman', 'SimSun', serif;
                font-size: 88px; line-height: 1; font-weight: 400;
                letter-spacing: -3px; margin-bottom: 4px; position: relative; z-index: 1;
            }
            .focus-hero .hero-label {
                font-size: 12px; color: var(--quiet); letter-spacing: 3px;
                text-transform: uppercase; font-weight: 500; position: relative; z-index: 1;
            }
            .focus-hero .hero-compare {
                margin-top: 10px; font-size: 13px; font-weight: 500; position: relative; z-index: 1;
            }

            /* ── 统计卡片 ── */
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
                gap: 1px; background: var(--line); border: 1px solid var(--line);
                margin-bottom: 24px;
            }
            .stat-card {
                background: var(--card); padding: 20px 16px; text-align: center;
            }
            .stat-card .stat-value {
                font-family: Georgia, 'Times New Roman', 'SimSun', serif;
                font-size: 28px; line-height: 1.15; font-weight: 400;
            }
            .stat-card .stat-label { font-size: 11px; color: var(--quiet); margin-top: 6px; }
            .stat-card .stat-sub {
                font-size: 11px; color: var(--quiet); margin-top: 3px; font-weight: 500;
            }

            /* ── 通用卡片 · 左 accent + hover ── */
            .card {
                background: var(--card); padding: 24px 24px 24px 22px;
                margin-bottom: 1px;
                border: 1px solid var(--line);
                border-left: 2px solid var(--line);
                transition: border-left-color 0.3s, box-shadow 0.3s;
            }
            .card:hover {
                border-left-color: var(--iris);
                box-shadow: 0 1px 6px rgba(0,0,0,0.03);
            }
            .card h2 {
                font-family: Georgia, 'Times New Roman', 'SimSun', serif;
                font-size: 15px; font-weight: 400; color: var(--ink);
                margin-bottom: 16px; padding-bottom: 10px;
                border-bottom: 1px solid var(--line-light);
                letter-spacing: -0.1px;
            }
            .card .card-desc {
                font-size: 12px; color: var(--quiet); margin-bottom: 14px; line-height: 1.6;
            }

            /* ── 图表 (v4.16: Plotly 交互式) ── */
            .chart-container { margin: 0; overflow: hidden; }
            .chart-container .plotly-graph-div { width: 100% !important; }
            .chart-container .js-plotly-plot { max-width: 100%; }
            .no-data { text-align: center; color: #ccc; padding: 36px; font-size: 13px; }
            .chart-error {
                text-align: center; color: var(--rose); background: #FDF8F6;
                border: 1px solid #F0D0CC; padding: 16px; margin: 8px 0;
                font-size: 12px;
            }

            /* ── 历史对比 ── */
            .compare-box {
                display: flex; gap: 24px; flex-wrap: wrap; padding: 16px 0;
                margin-bottom: 20px; border-bottom: 1px solid var(--line-light);
            }
            .compare-item { text-align: center; flex: 1; min-width: 80px; }
            .compare-item .label { font-size: 11px; color: var(--quiet); }
            .compare-item .value {
                font-family: Georgia, 'Times New Roman', 'SimSun', serif;
                font-size: 24px; font-weight: 400; line-height: 1.2;
            }
            .compare-item .delta { font-size: 12px; font-weight: 500; }

            /* ── 建议列表 ── */
            .insights-list { list-style: none; }
            .insight-item {
                padding: 16px 20px; margin-bottom: 1px;
                border-left: 2px solid transparent;
                background: var(--card); border-bottom: 1px solid var(--line-light);
            }
            .insight-item.alert { border-left-color: var(--rose); }
            .insight-item.warning { border-left-color: var(--amber); }
            .insight-item.info { border-left-color: var(--iris); }
            .insight-item .title { font-weight: 600; margin-bottom: 3px; font-size: 13px; }
            .insight-item .description { font-size: 12px; color: var(--quiet); margin-bottom: 4px; }
            .insight-item .suggestion {
                font-size: 12px; color: var(--ink); margin-top: 6px;
                padding: 6px 12px; background: #F9F8F6;
            }
            .severity-badge {
                display: inline-block; padding: 1px 6px; font-size: 9px;
                font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;
                margin-right: 8px; vertical-align: middle;
            }
            .severity-badge.alert { background: var(--rose); color: #fff; }
            .severity-badge.warning { background: var(--amber); color: #fff; }
            .severity-badge.info { background: var(--iris); color: #fff; }

            /* ── 关于 Tab ── */
            .about-grid {
                display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 1px; background: var(--line); border: 1px solid var(--line);
            }
            .about-card {
                background: var(--card); padding: 16px 18px;
            }
            .about-card .ac-title { font-size: 12px; font-weight: 600; color: var(--ink); }
            .about-card .ac-desc { font-size: 11px; color: var(--quiet); margin-top: 4px; line-height: 1.5; }
            .tech-badge {
                display: inline-block; padding: 3px 10px; font-size: 11px;
                background: #F5F3F0; color: var(--quiet); margin: 2px 4px 2px 0;
            }

            /* ── v4.17: 成就徽章 ── */
            .achieve-row { display: flex; gap: 12px; flex-wrap: wrap; }
            .achieve-badge {
                display: flex; flex-direction: column; align-items: center;
                padding: 14px 16px; min-width: 90px;
                background: #FAF9F7; border: 1px solid var(--line);
                border-radius: 8px; text-align: center;
            }
            .achieve-badge .achieve-icon { font-size: 26px; margin-bottom: 4px; }
            .achieve-badge .achieve-name {
                font-size: 12px; font-weight: 600; color: var(--ink);
            }
            .achieve-badge .achieve-desc { font-size: 10px; color: var(--quiet); margin-top: 2px; }

            /* ── 页脚 ── */
            .footer {
                text-align: center; color: #ccc; font-size: 11px;
                margin-top: 36px; padding: 20px; letter-spacing: 0.2px;
            }

            /* ── 会话详情表 ── */
            .detail-table { width: 100%; border-collapse: collapse; font-size: 12px; }
            .detail-table td { padding: 8px 0; }
            .detail-table td:first-child { color: var(--quiet); width: 100px; }

            /* ── 数据不足页 ── */
            .collecting {
                text-align: center; padding: 64px 20px; background: var(--card);
                border: 1px solid var(--line);
            }
            .collecting .icon { font-size: 48px; margin-bottom: 16px; }
            .collecting h2 { font-size: 18px; color: var(--ink); margin-bottom: 8px; }
            .collecting p { font-size: 13px; color: var(--quiet); line-height: 1.7; }
        </style>
    """

    # Tab 切换 JS
    PLOTLY_JS = '<script src="plotly.min.js"></script>'

    @staticmethod
    def _ensure_plotly_asset(report_dir: str) -> None:
        """v4.16: 复制 plotly.min.js 到报告目录（确保离线可用）"""
        import os as _os
        import shutil
        import plotly as _plotly
        src = _os.path.join(_os.path.dirname(_plotly.__file__), 'package_data', 'plotly.min.js')
        dst = _os.path.join(report_dir, 'plotly.min.js')
        if not _os.path.exists(dst) and _os.path.exists(src):
            try:
                shutil.copy2(src, dst)
                logger.debug("plotly.min.js 已复制到报告目录")
            except Exception as e:
                logger.warning("复制 plotly.min.js 失败: %s", e)

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
        self._ensure_plotly_asset("reports")

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

        # v4.11: 数据不足时显示占位页
        if len(focus_records) < 3:
            return self._render_insufficient_data(session_id)

        # 计算统计信息
        avg_focus = self._calc_avg_focus(focus_records)
        avg_blink_rate = self._calc_avg_blink_rate(focus_records)
        total_duration = session.duration_seconds() or 0.0
        fatigue_level = self._determine_fatigue_level(fatigue_records)

        # 生成报告数据
        report_data = ReportData(
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

        # 生成建议
        insights = self.insights_engine.analyze(
            focus_records=focus_records,
            fatigue_records=fatigue_records,
            avg_focus=avg_focus,
            avg_blink_rate=avg_blink_rate,
            session_duration=total_duration,
            session_id=session.session_id,
            session_start_time=session.start_time.timestamp(),
        )

        # 渲染 HTML
        return self._render_html(report_data, charts, insights)

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
        self._ensure_plotly_asset("reports")

        # 计算统计信息
        avg_focus = self._calc_avg_focus(focus_records)
        avg_blink_rate = self._calc_avg_blink_rate(focus_records)
        total_duration = session.duration_seconds() or 0.0
        fatigue_level = self._determine_fatigue_level(fatigue_records)

        # 生成报告数据
        report_data = ReportData(
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
        )

        # 渲染 HTML
        return self._render_html(report_data, charts, insights)

    def _generate_charts(self, data: ReportData) -> dict:
        """生成所有图表

        每个图表独立 try/except，失败不互相影响。返回值结构:
            {name: {"data": base64_str | None, "error": str | None}}

        - data != None, error == None: 成功
        - data == None, error == None:  无数据（按业务逻辑跳过）
        - data == None, error != None:  生成失败（异常被记录，HTML 渲染会
          显示 chart-error 标记，让用户/调用方知道是失败不是无数据）

        H-10 修复: 原代码一个 try/except 包全部 4 个图表，任一失败时
        charts dict 部分缺失但调用方无任何反馈，HTML 只能看到一片空白。
        """
        charts = {}

        # 每个图表独立 try/except + always populate entry (即使失败)
        def _try_chart(name, gen_fn, has_data):
            """v4.16: Plotly 返回 HTML 字符串，直接使用。"""
            if not has_data:
                charts[name] = {"data": None, "error": None}
                return
            try:
                result = gen_fn()
                # v4.16: Plotly 返回 HTML 字符串；session_colorbar 也返回 HTML
                if isinstance(result, bytes):
                    charts[name] = {"data": self._bytes_to_base64(result), "error": None}
                else:
                    charts[name] = {"data": result, "error": None}
            except Exception as e:
                logger.error("生成图表 %s 失败: %s", name, e)
                charts[name] = {"data": None, "error": str(e)}

        _try_chart(
            "focus_trend",
            lambda: self.chart_gen.generate_focus_trend_chart(data.focus_records),
            has_data=bool(data.focus_records),
        )
        _try_chart(
            "blink_rate",
            lambda: self.chart_gen.generate_blink_rate_chart(data.focus_records),
            has_data=bool(data.focus_records),
        )
        _try_chart(
            "fatigue_timeline",
            lambda: self.chart_gen.generate_fatigue_timeline(data.fatigue_records),
            has_data=bool(data.fatigue_records),
        )
        _try_chart(
            "session_colorbar",
            lambda: self.chart_gen.generate_session_colorbar(data.focus_records),
            has_data=bool(data.focus_records),
        )
        _try_chart(
            "head_pose_scatter",
            lambda: self.chart_gen.generate_head_pose_scatter(data.frame_records),
            has_data=bool(data.frame_records),
        )

        # v4.17: 日历热力图
        _try_chart(
            "calendar_heatmap",
            lambda: self._generate_calendar_chart(),
            has_data=True,
        )

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
        """v4.13: 4标签页布局（概览 + 数据分析 + 改善建议 + 关于）"""
        session = data.session

        safe_session_id = html_escape(session.session_id)

        # 将原始 chart data 渲染为 HTML（insights_charts 是原生HTML字符串，跳过渲染）
        charts_for_render = {k: v for k, v in charts.items() if k != "insights_charts"}
        charts_html = self._render_charts(charts_for_render)
        if "insights_charts" in charts:
            charts_html["insights_charts"] = charts["insights_charts"]

        # 各 tab HTML
        overview_html = self._render_overview_tab(data, charts_html)
        analysis_html = self._render_analysis_tab(charts_html)
        suggestions_html = self._render_insights_tab(charts_html, insights)
        about_html = self._render_about_tab(session_id=safe_session_id)

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
            <button class="tab-btn" data-tab="analysis" onclick="switchTab('analysis')">📈 数据分析</button>
            <button class="tab-btn" data-tab="suggestions" onclick="switchTab('suggestions')">🔍 改善建议</button>
            <button class="tab-btn" data-tab="about" onclick="switchTab('about')">ℹ️ 关于</button>
        </div>

        <div id="tab-overview" class="tab-content active">{overview_html}</div>
        <div id="tab-analysis" class="tab-content">{analysis_html}</div>
        <div id="tab-suggestions" class="tab-content">{suggestions_html}</div>
        <div id="tab-about" class="tab-content">{about_html}</div>

        <div class="footer">EyeFocus Insight | 自动生成的专注度分析报告</div>
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

        # 与历史对比
        if self.db and data.session.session_id:
            try:
                with self.db._get_cursor() as cur:
                    cur.execute("""
                        SELECT AVG(focus_score) FROM focus_records
                        WHERE session_id != ? AND focus_score IS NOT NULL
                    """, (data.session.session_id,))
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
            hero_color = "#5A8A6D"
        elif avg_focus >= 50:
            hero_color = "#C9843A"
        else:
            hero_color = "#B55C5C"

        parts.append(f'''
            <div class="focus-hero">
                <div class="hero-ring"></div>
                <div class="hero-value" style="color:{hero_color}">{avg_focus:.0f}</div>
                <div class="hero-label">平均专注度</div>
            </div>''')

        if stats["focus_change"] is not None:
            arrow = "↑" if stats["focus_change"] >= 0 else "↓"
            dc = "#5A8A6D" if stats["focus_change"] >= 0 else "#B55C5C"
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

        # ── v4.17: 专注日历热力图 ──
        cal_html = charts.get("calendar_heatmap", "")
        if cal_html:
            parts.append(
                '<div class="card"><h2>📅 专注日历</h2>'
                '<p class="card-desc">历史每日专注时长分布（GitHub 贡献图风格）</p>'
                + cal_html + "</div>"
            )

        # ── v4.17: 成就徽章 ──
        achievements_html = self._render_achievements()
        if achievements_html:
            parts.append(
                '<div class="card"><h2>🏅 成就</h2>'
                + achievements_html + "</div>"
            )

        return "\n".join(parts)

    # ── v4.17: 成就渲染 ──

    def _render_achievements(self) -> str:
        """渲染成就徽章行（从 daily_stats 读取数据）"""
        try:
            all_stats = self.db.get_all_daily_stats() if self.db else []
            if not all_stats:
                return ""

            total_minutes = sum(s.total_focus_minutes for s in all_stats)
            total_sessions = sum(s.session_count for s in all_stats)
            dates = sorted(set(s.date for s in all_stats), reverse=True)

            # 计算连续天数
            streak = 0
            from datetime import datetime, timedelta
            check = datetime.now().date()
            for d in dates:
                sd = datetime.strptime(d, "%Y-%m-%d").date()
                if sd == check:
                    streak += 1
                    check -= timedelta(days=1)
                elif sd == check:
                    break
                else:
                    break

            # 构建成就列表
            achievements = []

            # 总时长成就
            if total_minutes >= 3000:  # 50h
                achievements.append(("🚀", "专注强者", f"累计 {total_minutes/60:.0f} 小时"))
            elif total_minutes >= 600:  # 10h
                achievements.append(("📈", "累积进步", f"累计 {total_minutes/60:.0f} 小时"))
            else:
                achievements.append(("🌟", "初次专注", f"{total_sessions} 次会话"))

            # 连续成就
            if streak >= 30:
                achievements.append(("👑", "专注满贯", f"连续 {streak} 天"))
            elif streak >= 7:
                achievements.append(("💎", "坚持不懈", f"连续 {streak} 天"))
            elif streak >= 3:
                achievements.append(("🔥", "初露锋芒", f"连续 {streak} 天"))

            # 最长单次
            best = max((s.longest_session_minutes for s in all_stats), default=0)
            if best >= 180:
                achievements.append(("🏆", "专注大师", f"单次 {best:.0f} 分钟"))
            elif best >= 60:
                achievements.append(("💪", "专注达人", f"单次 {best:.0f} 分钟"))
            elif best >= 30:
                achievements.append(("⏱", "专注入门", f"单次 {best:.0f} 分钟"))

            if not achievements:
                return ""

            cards_html = ""
            for icon, name, desc in achievements:
                cards_html += (
                    f'<div class="achieve-badge">'
                    f'<span class="achieve-icon">{icon}</span>'
                    f'<span class="achieve-name">{name}</span>'
                    f'<span class="achieve-desc">{desc}</span>'
                    f'</div>'
                )

            return f'<div class="achieve-row">{cards_html}</div>'
        except Exception as e:
            logger.debug("成就渲染跳过: %s", e)
            return ""

    def _render_analysis_tab(self, charts: dict) -> str:
        """v4.15: 数据分析 Tab"""
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

        parts = []
        for title, desc, key in sections:
            chart_html = charts.get(key, '<div class="no-data">无数据</div>')
            parts.append(f'''
            <div class="card">
                <h2>{title}</h2>
                <div class="card-desc">{desc}</div>
                {chart_html}
            </div>''')

        return "\n".join(parts)

    def _render_insights_tab(self, charts: dict, insights: List[Insight]) -> str:
        """v4.13: 改善建议 Tab（统一所有建议 + 高级图表）"""
        insights_html = self._render_insights(insights) if insights else ""
        insights_charts = charts.get('insights_charts', "")

        return f"""
            <div class="card">
                <h2>个性化建议</h2>
                {insights_html if insights_html else '<div class="no-data">未检测到明显问题</div>'}
            </div>
            {insights_charts}
        """

    def _render_about_tab(self, session_id: str = "") -> str:
        """渲染关于 Tab"""
        safe_sid = html_escape(session_id)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
        """渲染建议列表"""
        if not insights:
            return ""

        # M-18: severity 白名单, 防止恶意 severity 注入 class 属性
        _ALLOWED_SEVERITY = {"info", "warning", "alert"}
        items = []
        for insight in insights:
            severity_class = (
                insight.severity if insight.severity in _ALLOWED_SEVERITY else "info"
            )
            # M-18: title/description/suggestion 来自数据, 需 escape
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

        return f"<ul class='insights-list'>\n" + "\n".join(items) + "\n</ul>"

    def _render_insight_items(self, insights: List[Insight]) -> str:
        """仅渲染建议列表的 <li> 项（不带 <ul> 包装），用于注入已有章节。"""
        if not insights:
            return ""
        _ALLOWED_SEVERITY = {"info", "warning", "alert"}
        items = []
        for insight in insights:
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
                </li>""")

        return "\n".join(items)

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
        """计算平均专注度"""
        if not focus_records:
            return 0.0
        return sum(r.focus_score for r in focus_records) / len(focus_records)

    def _calc_avg_blink_rate(self, focus_records: List[FocusRecord]) -> float:
        """计算平均眨眼频率"""
        if not focus_records:
            return 0.0
        return sum(r.blink_rate for r in focus_records) / len(focus_records)

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
        self._ensure_plotly_asset("reports")
        if not HAS_INSIGHTS:
            return self.generate_report(session_id)
        if not self.db:
            return self._error_html("数据库管理器未初始化")

        if insights_result is None:
            from analyzer.insights import run_pipeline
            try:
                insights_result = run_pipeline(self.db, session_id)
            except Exception as e:
                logger.warning("Insights pipeline 自动运行失败: %s", e)
                return self.generate_report(session_id)

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

        # 6. 规则引擎建议 + attribution 发现
        rule_insights = self.insights_engine.analyze(
            focus_records=focus_records, fatigue_records=fatigue_records,
            avg_focus=avg_focus, avg_blink_rate=avg_blink_rate,
            session_duration=total_duration,
            session_id=session_id,
            session_start_time=session.start_time.timestamp(),
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
        """格式化时长"""
        if seconds <= 0:
            return "0秒"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
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
                当前会话数据尚不足（< 3 个采样周期），请稍后查看。<br>
                监测运行约 2 分钟后数据将自动可用。
            </p>
            <p style="margin-top:16px;font-size:13px;color:#bbb;">
                您也可以关闭窗口继续监测，之后再次点击"打开报告"
            </p>
        </div>
        <div class="footer">EyeFocus Insight | 自动生成的专注度分析报告</div>
    </div>
</body>
</html>"""

    def _error_html(self, message: str) -> str:
        """错误页面 HTML"""
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
    <div class="message">{message}</div>
</body>
</html>
"""


def create_html_generator(
    db_manager: Optional[DatabaseManager] = None,
) -> HTMLReportGenerator:
    """工厂函数：创建 HTML 报告生成器"""
    return HTMLReportGenerator(db_manager=db_manager)

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

logger = logging.getLogger("eyefocus.reporter")


@dataclass
class ReportData:
    """报告数据容器"""
    session: Session
    focus_records: List[FocusRecord]
    fatigue_records: List[FatigueRecord]
    blink_records: List[BlinkRecord]
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

    # CSS 样式
    CSS_STYLE = """
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif;
                line-height: 1.6;
                color: #333;
                background: #f5f7fa;
                padding: 20px;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
            }
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 30px;
                border-radius: 10px;
                margin-bottom: 20px;
            }
            .header h1 {
                font-size: 28px;
                margin-bottom: 10px;
            }
            .header .subtitle {
                opacity: 0.9;
                font-size: 14px;
            }
            .card {
                background: white;
                border-radius: 10px;
                padding: 20px;
                margin-bottom: 20px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.05);
            }
            .card h2 {
                font-size: 18px;
                color: #444;
                border-bottom: 2px solid #667eea;
                padding-bottom: 10px;
                margin-bottom: 15px;
            }
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-bottom: 20px;
            }
            .stat-box {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 8px;
                text-align: center;
            }
            .stat-box .value {
                font-size: 32px;
                font-weight: bold;
                color: #667eea;
            }
            .stat-box .label {
                font-size: 12px;
                color: #666;
                text-transform: uppercase;
            }
            .stat-box.good .value { color: #28a745; }
            .stat-box.warning .value { color: #ffc107; }
            .stat-box.danger .value { color: #dc3545; }
            .chart-container {
                text-align: center;
                margin: 20px 0;
            }
            .chart-container img {
                max-width: 100%;
                height: auto;
                border-radius: 8px;
            }
            .insights-list {
                list-style: none;
            }
            .insight-item {
                padding: 15px;
                margin-bottom: 10px;
                border-radius: 8px;
                border-left: 4px solid;
            }
            .insight-item.alert {
                background: #fff5f5;
                border-color: #dc3545;
            }
            .insight-item.warning {
                background: #fffaf0;
                border-color: #ffc107;
            }
            .insight-item.info {
                background: #f0f7ff;
                border-color: #667eea;
            }
            .insight-item .title {
                font-weight: bold;
                margin-bottom: 5px;
            }
            .insight-item .description {
                font-size: 14px;
                color: #666;
                margin-bottom: 8px;
            }
            .insight-item .suggestion {
                font-size: 14px;
                color: #333;
                padding: 8px 12px;
                background: rgba(255,255,255,0.5);
                border-radius: 4px;
            }
            .severity-badge {
                display: inline-block;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
                text-transform: uppercase;
                margin-left: 10px;
            }
            .severity-badge.alert { background: #dc3545; color: white; }
            .severity-badge.warning { background: #ffc107; color: #333; }
            .severity-badge.info { background: #667eea; color: white; }
            .footer {
                text-align: center;
                color: #999;
                font-size: 12px;
                margin-top: 30px;
                padding: 20px;
            }
            .summary-chart {
                max-width: 600px;
                margin: 0 auto;
            }
            .no-data {
                text-align: center;
                color: #999;
                padding: 40px;
            }
            .chart-error {
                text-align: center;
                color: #dc3545;
                background: #fff5f5;
                border: 1px solid #f5c6cb;
                border-radius: 8px;
                padding: 20px;
                margin: 10px 0;
            }
        </style>
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
        self.insights_engine = insights_engine or create_insights_engine()

    def generate_report(self, session_id: str) -> str:
        """生成完整 HTML 报告

        Args:
            session_id: 会话 ID

        Returns:
            HTML 字符串
        """
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
        )

        # 渲染 HTML
        return self._render_html(report_data, charts, insights)

    def generate_report_from_data(
        self,
        session: Session,
        focus_records: List[FocusRecord],
        fatigue_records: List[FatigueRecord],
        blink_records: List[BlinkRecord],
    ) -> str:
        """从数据对象生成报告（不依赖数据库）

        Args:
            session: 会话对象
            focus_records: 专注度记录列表
            fatigue_records: 疲劳记录列表
            blink_records: 眨眼事件列表

        Returns:
            HTML 字符串
        """
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
            """单个图表生成包装。始终在 charts 中放条目。"""
            if not has_data:
                charts[name] = {"data": None, "error": None}
                return
            try:
                raw = gen_fn()
                charts[name] = {"data": self._bytes_to_base64(raw), "error": None}
            except Exception as e:
                logger.error("生成图表 %s 失败: %s", name, e)
                charts[name] = {"data": None, "error": str(e)}

        _try_chart(
            "focus_trend",
            lambda: self.chart_gen.generate_focus_trend_chart(data.focus_records),
            has_data=bool(data.focus_records),
        )
        _try_chart(
            "blink_distribution",
            lambda: self.chart_gen.generate_blink_rate_distribution(
                data.blink_records, data.focus_records
            ),
            has_data=bool(data.focus_records or data.blink_records),
        )
        _try_chart(
            "fatigue_timeline",
            lambda: self.chart_gen.generate_fatigue_timeline(data.fatigue_records),
            has_data=bool(data.fatigue_records),
        )
        _try_chart(
            "summary",
            lambda: self.chart_gen.generate_summary_chart(
                avg_focus=data.avg_focus,
                avg_blink_rate=data.avg_blink_rate,
                fatigue_level=data.fatigue_level,
                total_duration=data.total_duration,
            ),
            has_data=bool(data.focus_records),
        )

        return charts

    def _render_html(
        self,
        data: ReportData,
        charts: dict,
        insights: List[Insight],
    ) -> str:
        """渲染 HTML 页面"""
        session = data.session

        # 格式化时间
        start_time = session.start_time.strftime("%Y-%m-%d %H:%M:%S")
        end_time = session.end_time.strftime("%Y-%m-%d %H:%M:%S") if session.end_time else "进行中"
        duration_str = self._format_duration(data.total_duration)

        # M-17: session_id 来自外部，需 html_escape 防止 XSS
        safe_session_id = html_escape(session.session_id)

        # 专注度等级
        focus_class = self._get_stat_class(data.avg_focus, 70, 50)
        blink_class = self._get_blink_stat_class(data.avg_blink_rate)

        # 生成建议 HTML
        insights_html = self._render_insights(insights)

        # 图表 HTML
        charts_html = self._render_charts(charts)

        html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EyeFocus 专注度分析报告</title>
    {self.CSS_STYLE}
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>EyeFocus Insight 专注度分析报告</h1>
            <div class="subtitle">
                会话 ID: {safe_session_id} | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </div>
        </div>

        <!-- 统计摘要 -->
        <div class="card">
            <h2>会话摘要</h2>
            <div class="stats-grid">
                <div class="stat-box {focus_class}">
                    <div class="value">{data.avg_focus:.1f}</div>
                    <div class="label">平均专注度</div>
                </div>
                <div class="stat-box {blink_class}">
                    <div class="value">{data.avg_blink_rate:.1f}</div>
                    <div class="label">眨眼频率 (次/分)</div>
                </div>
                <div class="stat-box">
                    <div class="value">{duration_str}</div>
                    <div class="label">会话时长</div>
                </div>
                <div class="stat-box">
                    <div class="value">{len(data.focus_records)}</div>
                    <div class="label">专注度记录数</div>
                </div>
            </div>
        </div>

        <!-- 摘要图表 -->
        {charts_html.get('summary', '')}

        <!-- 专注度趋势 -->
        <div class="card">
            <h2>专注度趋势分析</h2>
            {charts_html.get('focus_trend', '<div class="no-data">无数据</div>')}
        </div>

        <!-- 眨眼分析 -->
        <div class="card">
            <h2>眨眼频率分析</h2>
            {charts_html.get('blink_distribution', '<div class="no-data">无数据</div>')}
        </div>

        <!-- 疲劳分析 -->
        <div class="card">
            <h2>疲劳趋势分析</h2>
            {charts_html.get('fatigue_timeline', '<div class="no-data">无数据</div>')}
        </div>

        <!-- 个性化建议 -->
        <div class="card">
            <h2>个性化建议</h2>
            {insights_html if insights_html else '<div class="no-data">未检测到明显问题</div>'}
        </div>

        <!-- 会话详情 -->
        <div class="card">
            <h2>会话详情</h2>
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px; color: #666;">会话 ID</td>
                    <td style="padding: 8px;">{safe_session_id}</td>
                </tr>
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px; color: #666;">开始时间</td>
                    <td style="padding: 8px;">{start_time}</td>
                </tr>
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px; color: #666;">结束时间</td>
                    <td style="padding: 8px;">{end_time}</td>
                </tr>
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px; color: #666;">校准状态</td>
                    <td style="padding: 8px;">{'已校准' if session.is_calibrated else '未校准'}</td>
                </tr>
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px; color: #666;">眼镜模式</td>
                    <td style="padding: 8px;">{session.glasses_mode.value}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; color: #666;">CQS 分数</td>
                    <td style="padding: 8px;">{session.cqs_score or 'N/A'}</td>
                </tr>
            </table>
        </div>

        <div class="footer">
            EyeFocus Insight | 自动生成的专注度分析报告
        </div>
    </div>
</body>
</html>
"""
        return html

    def _render_insights(self, insights: List[Insight]) -> str:
        """渲染建议列表"""
        if not insights:
            return ""

        items = []
        for insight in insights:
            severity_class = insight.severity
            badge_html = f'<span class="severity-badge {severity_class}">{severity_class.upper()}</span>'

            items.append(f"""
                <li class="insight-item {severity_class}">
                    <div class="title">{badge_html}{insight.title}</div>
                    <div class="description">{insight.description}</div>
                    <div class="suggestion">💡 {insight.suggestion}</div>
                </li>
            """)

        return f"<ul class='insights-list'>\n" + "\n".join(items) + "\n</ul>"

    def _render_charts(self, charts: dict) -> dict:
        """将图表数据转换为 HTML。

        输入 charts 结构 (来自 _generate_charts):
            {name: {"data": base64_str | None, "error": str | None}}

        渲染规则:
        - data != None → <div class="chart-container"><img ...></div>
        - data == None, error != None → <div class="chart-error">图表生成失败 ({name}): {error}</div>
        - data == None, error == None → <div class="no-data">无数据</div>
        """
        result = {}
        for name, info in charts.items():
            data = info.get("data") if isinstance(info, dict) else None
            error = info.get("error") if isinstance(info, dict) else None
            if error:
                # H-10: 失败时显式标记，让用户/调用方知道是生成失败不是无数据
                result[name] = (
                    f'<div class="chart-error">'
                    f'图表生成失败 ({name}): {error}'
                    f'</div>'
                )
            elif data:
                result[name] = (
                    f'<div class="chart-container">'
                    f'<img src="data:image/png;base64,{data}" alt="{name}">'
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

# reporter package
"""
reporter 模块 — 报告生成功能

提供 HTML 报告生成、图表绘制和个性化建议功能。

主要组件：
- HTMLReportGenerator: 生成完整的 HTML 分析报告
- ChartGenerator: 使用 Matplotlib 生成专注度趋势图、眨眼分布图等
- InsightsEngine: 基于数据分析生成个性化改善建议

使用方法：
    from reporter import create_html_generator

    # 方式1: 从数据库生成报告
    generator = create_html_generator(db_manager)
    html = generator.generate_report(session_id)

    # 方式2: 直接从数据生成报告
    html = generator.generate_report_from_data(
        session=session,
        focus_records=focus_list,
        fatigue_records=fatigue_list,
        blink_records=blink_list,
    )
"""

from reporter.charts import ChartGenerator, create_chart_generator
from reporter.insights import Insight, InsightsEngine, create_insights_engine
from reporter.report_html import HTMLReportGenerator, ReportData, create_html_generator

__all__ = [
    # 图表生成
    'ChartGenerator',
    'create_chart_generator',
    # 建议引擎
    'InsightsEngine',
    'create_insights_engine',
    'Insight',
    # HTML 报告
    'HTMLReportGenerator',
    'create_html_generator',
    'ReportData',
]

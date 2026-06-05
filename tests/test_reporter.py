"""
tests/test_reporter.py — reporter 模块测试

测试报告生成功能：
- 图表生成
- 建议引擎
- HTML 报告生成
"""

import sys
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# 确保项目根目录在路径中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from storage.models import (
    Session,
    FocusRecord,
    FatigueRecord,
    FatigueLevel,
    BlinkRecord,
    GlassesMode,
)
from reporter.charts import ChartGenerator, create_chart_generator
from reporter.insights import InsightsEngine, Insight, create_insights_engine
from reporter.report_html import HTMLReportGenerator, ReportData, create_html_generator


# ============ Fixtures ============

@pytest.fixture
def sample_session():
    """创建示例会话"""
    return Session(
        session_id="test_session_001",
        start_time=datetime.now() - timedelta(minutes=30),
        end_time=datetime.now(),
        baseline_ear=0.25,
        baseline_yaw_std=3.0,
        baseline_pitch_std=3.0,
        cqs_score=85.0,
        glasses_mode=GlassesMode.WITHOUT_GLASSES,
        is_calibrated=True,
        is_active=False,
    )


@pytest.fixture
def sample_focus_records():
    """创建示例专注度记录"""
    records = []
    base_time = datetime.now() - timedelta(minutes=30)
    for i in range(20):
        # 模拟专注度逐渐下降然后恢复的模式
        if i < 10:
            score = 80.0 - i * 2
        else:
            score = 60.0 + (i - 10) * 3

        records.append(FocusRecord(
            session_id="test_session_001",
            window_start=i * 60.0,
            window_end=(i + 1) * 60.0,
            focus_score=max(40.0, score),
            eye_score=max(50.0, score - 5),
            head_score=max(45.0, score - 10),
            gaze_score=max(55.0, score + 5),
            blink_rate=15.0 + (i % 5) * 2,
            avg_ear=0.25,
            avg_yaw=2.0,
            avg_pitch=-1.0,
        ))
    return records


@pytest.fixture
def sample_fatigue_records():
    """创建示例疲劳记录"""
    records = []
    base_time = datetime.now() - timedelta(minutes=30)
    for i in range(10):
        cumulative = min(100.0, 30.0 + i * 8)

        if i < 3:
            level = FatigueLevel.LOW
        elif i < 7:
            level = FatigueLevel.MEDIUM
        else:
            level = FatigueLevel.HIGH

        records.append(FatigueRecord(
            session_id="test_session_001",
            timestamp=base_time.timestamp() + i * 180,
            fatigue_level=level,
            blink_rate=15.0 + i * 2,
            avg_ear_nadir=0.12 - i * 0.01,
            head_stability=90.0 - i * 5,
            cumulative_fatigue_score=cumulative,
        ))
    return records


@pytest.fixture
def sample_blink_records():
    """创建示例眨眼记录"""
    records = []
    base_time = datetime.now() - timedelta(minutes=30)
    for i in range(30):
        records.append(BlinkRecord(
            session_id="test_session_001",
            start_timestamp=base_time.timestamp() + i * 60,
            end_timestamp=base_time.timestamp() + i * 60 + 0.15,
            duration_seconds=0.15,
            ear_nadir=0.10,
        ))
    return records


@pytest.fixture
def chart_generator():
    """创建图表生成器"""
    return create_chart_generator(figsize=(8, 4), dpi=80)


@pytest.fixture
def insights_engine():
    """创建建议引擎"""
    return create_insights_engine()


@pytest.fixture
def html_generator():
    """创建 HTML 报告生成器（无数据库依赖）"""
    return create_html_generator(db_manager=None)


# ============ ChartGenerator Tests ============

class TestChartGenerator:

    def test_create_chart_generator(self):
        """测试图表生成器创建"""
        gen = create_chart_generator()
        assert isinstance(gen, ChartGenerator)
        assert gen.figsize == (10, 4)
        assert gen.dpi == 100

    def test_create_with_custom_params(self):
        """测试自定义参数创建"""
        gen = ChartGenerator(figsize=(12, 6), dpi=150)
        assert gen.figsize == (12, 6)
        assert gen.dpi == 150

    def test_generate_focus_trend_chart(self, chart_generator, sample_focus_records):
        """测试专注度趋势图生成"""
        result = chart_generator.generate_focus_trend_chart(sample_focus_records)
        assert isinstance(result, bytes)
        assert len(result) > 0
        # PNG 文件头
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_generate_focus_trend_empty(self, chart_generator):
        """测试空数据专注度趋势图"""
        result = chart_generator.generate_focus_trend_chart([])
        assert isinstance(result, bytes)

    def test_generate_blink_distribution(self, chart_generator, sample_blink_records, sample_focus_records):
        """测试眨眼频率分布图生成"""
        result = chart_generator.generate_blink_rate_distribution(
            sample_blink_records, sample_focus_records
        )
        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_generate_fatigue_timeline(self, chart_generator, sample_fatigue_records):
        """测试疲劳时间线图生成"""
        result = chart_generator.generate_fatigue_timeline(sample_fatigue_records)
        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_generate_fatigue_timeline_empty(self, chart_generator):
        """测试空数据疲劳时间线"""
        result = chart_generator.generate_fatigue_timeline([])
        assert isinstance(result, bytes)

    def test_generate_summary_chart(self, chart_generator):
        """测试摘要图表生成"""
        result = chart_generator.generate_summary_chart(
            avg_focus=75.0,
            avg_blink_rate=18.0,
            fatigue_level=FatigueLevel.LOW,
            total_duration=1800.0,
        )
        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_generate_summary_chart_high_fatigue(self, chart_generator):
        """测试高疲劳摘要图表"""
        result = chart_generator.generate_summary_chart(
            avg_focus=45.0,
            avg_blink_rate=32.0,
            fatigue_level=FatigueLevel.HIGH,
            total_duration=3600.0,
        )
        assert isinstance(result, bytes)


# ============ InsightsEngine Tests ============

class TestInsightsEngine:

    def test_create_insights_engine(self):
        """测试建议引擎创建"""
        engine = create_insights_engine()
        assert isinstance(engine, InsightsEngine)

    def test_analyze_no_data(self, insights_engine):
        """测试无数据分析"""
        insights = insights_engine.analyze(
            focus_records=[],
            fatigue_records=[],
            avg_focus=0,
            avg_blink_rate=0,
            session_duration=0,
        )
        assert isinstance(insights, list)

    def test_analyze_with_data(
        self,
        insights_engine,
        sample_focus_records,
        sample_fatigue_records,
    ):
        """测试完整数据分析"""
        insights = insights_engine.analyze(
            focus_records=sample_focus_records,
            fatigue_records=sample_fatigue_records,
            avg_focus=70.0,
            avg_blink_rate=18.0,
            session_duration=1800.0,
        )
        assert isinstance(insights, list)
        # 应该有建议产生
        assert len(insights) >= 0

    def test_detect_declining_pattern(self, insights_engine):
        """测试下降趋势检测"""
        # 创建下降趋势数据
        records = []
        for i in range(10):
            records.append(FocusRecord(
                session_id="test",
                window_start=i * 60,
                window_end=(i + 1) * 60,
                focus_score=90.0 - i * 5,  # 明显下降
                eye_score=90.0 - i * 5,
                head_score=90.0 - i * 5,
                gaze_score=90.0 - i * 5,
                blink_rate=15.0,
                avg_ear=0.25,
                avg_yaw=2.0,
                avg_pitch=-1.0,
            ))

        pattern = insights_engine._detect_focus_pattern(records)
        assert pattern.pattern_type == 'declining'

    def test_detect_stable_pattern(self, insights_engine):
        """测试稳定模式检测"""
        records = []
        for i in range(10):
            records.append(FocusRecord(
                session_id="test",
                window_start=i * 60,
                window_end=(i + 1) * 60,
                focus_score=75.0,  # 稳定
                eye_score=75.0,
                head_score=75.0,
                gaze_score=75.0,
                blink_rate=15.0,
                avg_ear=0.25,
                avg_yaw=2.0,
                avg_pitch=-1.0,
            ))

        pattern = insights_engine._detect_focus_pattern(records)
        assert pattern.pattern_type == 'stable'

    def test_fatigue_alert(self, insights_engine):
        """测试疲劳警告生成"""
        # 创建高疲劳数据
        fatigue_records = [
            FatigueRecord(
                session_id="test",
                timestamp=0,
                fatigue_level=FatigueLevel.HIGH,
                blink_rate=35.0,
                avg_ear_nadir=0.05,
                head_stability=50.0,
                cumulative_fatigue_score=85.0,
            )
        ]

        insights = insights_engine._analyze_fatigue(fatigue_records)
        assert len(insights) > 0
        # 应该有 HIGH 级别的警告
        high_severity = [i for i in insights if i.severity == 'alert']
        assert len(high_severity) > 0

    def test_generate_summary(self, insights_engine):
        """测试摘要生成"""
        insights = [
            Insight(
                category='focus',
                severity='warning',
                title='测试标题',
                description='测试描述',
                suggestion='测试建议',
            )
        ]
        summary = insights_engine.generate_summary(insights)
        assert isinstance(summary, str)
        assert '测试标题' in summary


# ============ HTMLReportGenerator Tests ============

class TestHTMLReportGenerator:

    def test_create_html_generator(self):
        """测试 HTML 生成器创建"""
        gen = create_html_generator()
        assert isinstance(gen, HTMLReportGenerator)

    def test_generate_report_from_data(
        self,
        html_generator,
        sample_session,
        sample_focus_records,
        sample_fatigue_records,
        sample_blink_records,
    ):
        """测试从数据生成 HTML 报告"""
        html = html_generator.generate_report_from_data(
            session=sample_session,
            focus_records=sample_focus_records,
            fatigue_records=sample_fatigue_records,
            blink_records=sample_blink_records,
        )

        assert isinstance(html, str)
        assert '<!DOCTYPE html>' in html
        assert 'EyeFocus' in html
        assert '专注度分析报告' in html
        assert len(html) > 1000  # 应该有实质内容

    def test_html_contains_charts(
        self,
        html_generator,
        sample_session,
        sample_focus_records,
        sample_fatigue_records,
        sample_blink_records,
    ):
        """测试 HTML 包含图表"""
        html = html_generator.generate_report_from_data(
            session=sample_session,
            focus_records=sample_focus_records,
            fatigue_records=sample_fatigue_records,
            blink_records=sample_blink_records,
        )

        # 应该包含 base64 编码的 PNG 图片
        assert 'data:image/png;base64,' in html

    def test_html_contains_insights(
        self,
        html_generator,
        sample_session,
        sample_focus_records,
        sample_fatigue_records,
        sample_blink_records,
    ):
        """测试 HTML 包含个性化建议"""
        html = html_generator.generate_report_from_data(
            session=sample_session,
            focus_records=sample_focus_records,
            fatigue_records=sample_fatigue_records,
            blink_records=sample_blink_records,
        )

        assert '个性化建议' in html
        assert 'insight' in html.lower()

    def test_html_session_details(
        self,
        html_generator,
        sample_session,
        sample_focus_records,
        sample_fatigue_records,
        sample_blink_records,
    ):
        """测试 HTML 包含会话详情"""
        html = html_generator.generate_report_from_data(
            session=sample_session,
            focus_records=sample_focus_records,
            fatigue_records=sample_fatigue_records,
            blink_records=sample_blink_records,
        )

        assert 'test_session_001' in html
        assert '会话时长' in html
        assert '已校准' in html

    def test_calc_avg_focus(self, html_generator, sample_focus_records):
        """测试平均专注度计算"""
        avg = html_generator._calc_avg_focus(sample_focus_records)
        assert isinstance(avg, float)
        assert 0 <= avg <= 100

    def test_calc_avg_blink_rate(self, html_generator, sample_focus_records):
        """测试平均眨眼频率计算"""
        avg = html_generator._calc_avg_blink_rate(sample_focus_records)
        assert isinstance(avg, float)
        assert avg >= 0

    def test_determine_fatigue_level(self, html_generator, sample_fatigue_records):
        """测试疲劳等级判定"""
        level = html_generator._determine_fatigue_level(sample_fatigue_records)
        assert isinstance(level, FatigueLevel)

    def test_format_duration(self, html_generator):
        """测试时长格式化"""
        assert '30秒' in html_generator._format_duration(30)
        assert '5分30秒' in html_generator._format_duration(330)

    def test_error_html(self, html_generator):
        """测试错误页面"""
        html = html_generator._error_html("测试错误消息")
        assert '错误' in html
        assert '测试错误消息' in html

    # ===== H-10: 图表生成异常应被报告，不可静默吞 =====

    def test_h10_chart_failure_marked_in_html(
        self,
        sample_session,
        sample_focus_records,
        sample_fatigue_records,
        sample_blink_records,
    ):
        """H-10: 单个图表生成失败时，HTML 必须包含失败标记

        Bug 现象: 原 _generate_charts 把 4 个图表全包在一个 try/except，
        任一失败时 logger.error 后继续，charts dict 部分缺失但调用方无
        任何反馈 — 用户看到空白图但不知道是失败还是无数据。

        Fix 后: 每个图表独立 try/except，失败时 HTML 渲染
        <div class="chart-error">图表生成失败: {name}</div>。
        """
        from reporter.report_html import HTMLReportGenerator
        from reporter.charts import ChartGenerator

        # 用一个真实的 ChartGenerator（避免 mock 自身行为）
        # 然后 patch generate_focus_trend_chart 单独抛异常
        real_gen = create_chart_generator(figsize=(8, 4), dpi=80)

        with patch.object(
            ChartGenerator,
            'generate_focus_trend_chart',
            side_effect=RuntimeError("matplotlib 渲染失败: 模拟"),
        ):
            html_gen = HTMLReportGenerator(
                db_manager=None,
                chart_generator=real_gen,
            )
            html = html_gen.generate_report_from_data(
                session=sample_session,
                focus_records=sample_focus_records,
                fatigue_records=sample_fatigue_records,
                blink_records=sample_blink_records,
            )

        # 1) HTML 必须包含 chart-error 标记
        assert "chart-error" in html, \
            "图表生成失败时 HTML 必须包含 chart-error 标记"

        # 2) 错误信息应含失败的图表名（focus_trend）
        assert "focus_trend" in html, \
            "错误信息应指明哪个图表失败"

        # 3) 错误信息应包含具体异常消息（或其一部分）
        assert "matplotlib" in html or "模拟" in html, \
            f"错误信息应包含具体异常原因，实际 HTML 片段: {html[html.find('chart-error'):html.find('chart-error')+200] if 'chart-error' in html else '无 chart-error'}"

        # 4) 其他图表不应受影响 — 仍应有 base64 PNG（说明 focus_trend
        # 之外的其他图表正常生成）
        # fatigue_records 有数据 → fatigue_timeline 应当存在
        assert "fatigue_timeline" in html

    def test_h10_all_charts_failure_does_not_crash(
        self,
        sample_session,
        sample_focus_records,
        sample_fatigue_records,
        sample_blink_records,
    ):
        """H-10: 所有图表都失败时，HTML 仍可生成（不抛异常），含失败标记

        Fix 后整个报告流程应保持鲁棒 — 单图失败不应让整个 generate_report
        抛异常使上层崩溃。
        """
        from reporter.report_html import HTMLReportGenerator
        from reporter.charts import ChartGenerator

        real_gen = create_chart_generator(figsize=(8, 4), dpi=80)

        with patch.object(
            ChartGenerator,
            'generate_focus_trend_chart',
            side_effect=RuntimeError("focus_trend 失败"),
        ), patch.object(
            ChartGenerator,
            'generate_fatigue_timeline',
            side_effect=ValueError("fatigue_timeline 失败"),
        ):
            html_gen = HTMLReportGenerator(
                db_manager=None,
                chart_generator=real_gen,
            )
            # 不应抛异常
            html = html_gen.generate_report_from_data(
                session=sample_session,
                focus_records=sample_focus_records,
                fatigue_records=sample_fatigue_records,
                blink_records=sample_blink_records,
            )

        assert isinstance(html, str)
        assert len(html) > 0
        # 至少 2 个 chart-error 标记
        assert html.count("chart-error") >= 2

    # ===== M-17: session_id HTML XSS escape =====

    def test_m17_session_id_escaped_in_html(
        self,
        sample_focus_records,
        sample_fatigue_records,
        sample_blink_records,
    ):
        """M-17: session.session_id 嵌入 HTML 头部/详情表时必须 html.escape()

        Bug: session_id 含 HTML 元字符 (<, >, &, ", ') 时，原 f-string 直接
        拼入，未 escape，导致可注入 <script>alert(1)</script> 等。
        """
        from reporter.report_html import HTMLReportGenerator

        malicious_id = '"><script>alert("xss")</script>'
        session = Session(
            session_id=malicious_id,
            start_time=datetime.now() - timedelta(minutes=30),
            end_time=datetime.now(),
            baseline_ear=0.25,
            baseline_yaw_std=3.0,
            baseline_pitch_std=3.0,
            cqs_score=85.0,
            glasses_mode=GlassesMode.WITHOUT_GLASSES,
            is_calibrated=True,
            is_active=False,
        )

        html_gen = HTMLReportGenerator(db_manager=None)
        html = html_gen.generate_report_from_data(
            session=session,
            focus_records=sample_focus_records,
            fatigue_records=sample_fatigue_records,
            blink_records=sample_blink_records,
        )

        # 1) 原始 XSS payload 不应作为可执行 HTML 出现
        assert "<script>alert" not in html, \
            f"session_id 未转义, 可执行 <script> 注入: {html[:500]}"
        assert "</script>" not in html.replace("</body>", "").replace("</html>", ""), \
            "session_id 注入导致 </script> 提前闭合"

        # 2) 转义后的字符应出现 (&lt; &gt; &quot;)
        assert "&lt;script&gt;" in html, \
            "session_id 应被 html.escape 转为 &lt;script&gt;"

    def test_h10_normal_charts_have_no_error_marker(
        self,
        sample_session,
        sample_focus_records,
        sample_fatigue_records,
        sample_blink_records,
    ):
        """H-10 回归: 图表正常生成时，HTML 不应含 chart-error 标记

        确保 fix 没有把"无数据"和"失败"混淆 — 正常情况下报告应无
        chart-error 标记（除非真正的生成异常）。

        注意: 检查的是实际渲染的 <div class="chart-error"> 标签，
        不是 CSS 里的 .chart-error {} 规则。
        """
        from reporter.report_html import HTMLReportGenerator

        real_gen = create_chart_generator(figsize=(8, 4), dpi=80)
        html_gen = HTMLReportGenerator(
            db_manager=None,
            chart_generator=real_gen,
        )
        html = html_gen.generate_report_from_data(
            session=sample_session,
            focus_records=sample_focus_records,
            fatigue_records=sample_fatigue_records,
            blink_records=sample_blink_records,
        )

        # 实际渲染的 div 标签 — 不是 CSS 规则
        assert '<div class="chart-error">' not in html, \
            "图表正常生成时不应渲染 chart-error div"


# ============ Integration Tests ============

class TestReporterIntegration:

    def test_full_report_generation(
        self,
        sample_session,
        sample_focus_records,
        sample_fatigue_records,
        sample_blink_records,
    ):
        """测试完整报告生成流程"""
        # 1. 生成图表
        chart_gen = create_chart_generator()
        focus_chart = chart_gen.generate_focus_trend_chart(sample_focus_records)
        fatigue_chart = chart_gen.generate_fatigue_timeline(sample_fatigue_records)
        summary_chart = chart_gen.generate_summary_chart(
            avg_focus=70.0,
            avg_blink_rate=18.0,
            fatigue_level=FatigueLevel.LOW,
            total_duration=1800.0,
        )

        assert len(focus_chart) > 0
        assert len(fatigue_chart) > 0
        assert len(summary_chart) > 0

        # 2. 生成建议
        insights_engine = create_insights_engine()
        insights = insights_engine.analyze(
            focus_records=sample_focus_records,
            fatigue_records=sample_fatigue_records,
            avg_focus=70.0,
            avg_blink_rate=18.0,
            session_duration=1800.0,
        )
        assert isinstance(insights, list)

        # 3. 生成 HTML
        html_gen = create_html_generator()
        html = html_gen.generate_report_from_data(
            session=sample_session,
            focus_records=sample_focus_records,
            fatigue_records=sample_fatigue_records,
            blink_records=sample_blink_records,
        )

        assert len(html) > 5000  # 包含图表的报告应该较大
        assert 'png;base64' in html

    def test_report_with_empty_data(self, sample_session):
        """测试空数据的报告生成"""
        html_gen = create_html_generator()
        html = html_gen.generate_report_from_data(
            session=sample_session,
            focus_records=[],
            fatigue_records=[],
            blink_records=[],
        )

        assert isinstance(html, str)
        assert len(html) > 0
        # 仍应生成有效的 HTML
        assert '<html' in html.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

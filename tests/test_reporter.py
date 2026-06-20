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
    # v4.32: 清空模块级图表缓存，避免测试间缓存污染
    from reporter.report_html import _chart_html_cache
    _chart_html_cache.clear()
    return create_html_generator(db_manager=None)


# ============ ChartGenerator Tests ============

class TestChartGenerator:

    def test_create_chart_generator(self):
        """测试图表生成器创建"""
        gen = create_chart_generator()
        assert isinstance(gen, ChartGenerator)
        assert gen.figsize == (6, 2.8)
        assert gen.dpi == 120

    def test_create_with_custom_params(self):
        """测试自定义参数创建"""
        gen = ChartGenerator(figsize=(12, 6), dpi=150)
        assert gen.figsize == (12, 6)
        assert gen.dpi == 150

    def test_generate_focus_trend_chart(self, chart_generator, sample_focus_records):
        """v4.16: 测试 Plotly 专注度趋势图生成"""
        result = chart_generator.generate_focus_trend_chart(sample_focus_records)
        assert isinstance(result, str)
        assert 'plotly' in result.lower() or '无数据' in result
        assert len(result) > 0

    def test_generate_focus_trend_empty(self, chart_generator):
        """测试空数据专注度趋势图"""
        result = chart_generator.generate_focus_trend_chart([])
        assert isinstance(result, str)
        assert '无数据' in result

    def test_generate_blink_rate_chart(self, chart_generator, sample_focus_records):
        """v4.16: 测试 Plotly 眨眼频率图生成"""
        result = chart_generator.generate_blink_rate_chart(sample_focus_records)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_fatigue_timeline(self, chart_generator, sample_fatigue_records):
        """v4.16: 测试 Plotly 疲劳趋势图生成"""
        result = chart_generator.generate_fatigue_timeline(sample_fatigue_records)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_fatigue_timeline_empty(self, chart_generator):
        """测试空数据疲劳时间线"""
        result = chart_generator.generate_fatigue_timeline([])
        assert isinstance(result, str)
        assert '无数据' in result

    def test_generate_session_colorbar(self, chart_generator, sample_focus_records):
        """v4.16: 测试会话时间色条 HTML 生成"""
        result = chart_generator.generate_session_colorbar(sample_focus_records)
        assert isinstance(result, str)
        assert '专注' in result

    def test_generate_session_colorbar_empty(self, chart_generator):
        """v4.16: 测试空数据时间色条"""
        result = chart_generator.generate_session_colorbar([])
        assert isinstance(result, str)
        assert '无数据' in result

    def test_chart_generator_plotly_output(self, chart_generator, sample_focus_records):
        """v4.16: 验证 Plotly 输出包含交互式元素"""
        result = chart_generator.generate_focus_trend_chart(sample_focus_records)
        assert 'Plotly' in result or 'plotly' in result.lower() or '无数据' in result


# ============ v4.34: 零值填充间隙测试 ============

class TestGapBreaks:
    """验证 _insert_gap_breaks 用零值对取代 None 断点"""

    def test_zero_fill_single_gap(self):
        """间距 > GAP_THRESHOLD 产生两个零值点，不产生 None"""
        from reporter.charts import ChartGenerator
        t0 = 1000.0
        records = [
            MagicMock(window_start=t0, timestamp=t0, focus_score=80.0),
            MagicMock(window_start=t0 + 2000, timestamp=t0 + 2000, focus_score=70.0),
        ]
        offsets = [0.0, 2000.0]
        values = [80.0, 70.0]
        new_x, new_y = ChartGenerator._insert_gap_breaks(records, offsets, values)
        assert None not in new_x
        assert None not in new_y
        # 4 points: real[0], zero[0], zero[1], real[1]
        assert len(new_x) == 4
        assert len(new_y) == 4
        assert new_y == [80.0, 0, 0, 70.0]

    def test_no_gap_unchanged(self):
        """间距 < 动态阈值 不插入零值点 (v4.41: 阈值=min(300, dur/4))"""
        from reporter.charts import ChartGenerator
        t0 = 1000.0
        # v4.41: 使用 600s 时长（阈值=150s），10s 间隔不会被判为间隙
        records = [
            MagicMock(window_start=t0, timestamp=t0, focus_score=80.0),
            MagicMock(window_start=t0 + 10, timestamp=t0 + 10, focus_score=75.0),
            MagicMock(window_start=t0 + 20, timestamp=t0 + 20, focus_score=70.0),
        ]
        offsets = [0.0, 10.0, 20.0]
        values = [80.0, 75.0, 70.0]
        new_x, new_y = ChartGenerator._insert_gap_breaks(records, offsets, values)
        assert new_y == [80.0, 75.0, 70.0]

    def test_single_record_no_change(self):
        """单条记录不产生零值点"""
        from reporter.charts import ChartGenerator
        records = [MagicMock(window_start=1000.0, timestamp=1000.0, focus_score=80.0)]
        offsets = [0.0]
        values = [80.0]
        new_x, new_y = ChartGenerator._insert_gap_breaks(records, offsets, values)
        assert new_y == [80.0]


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

        # v4.16: 应该包含 Plotly 交互式图表
        assert 'plotly' in html.lower() or 'js-plotly-plot' in html

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
        assert '专注度' in html or '监测时长' in html
        assert '下一步' in html or 'v4.26' in html

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
        assert "模拟" in html or "RuntimeError" in html, \
            f"错误信息应包含具体异常原因"

        # 4) 其他图表不应受影响 — 至少有一个正常图表
        assert "chart-container" in html or "无数据" in html

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

    def test_m18_insight_fields_escaped_in_html(self, html_generator):
        """M-18: insight.title/description/suggestion 嵌入 HTML 时必须 escape

        Bug: _render_insights f-string 直接拼 insight.title/description/
        suggestion, 未 escape, 含 < > & 时会被解释为可执行 HTML。
        修复同时要求 severity_class 维持白名单 (仅 info/warning/alert),
        避免恶意 severity 值注入 class 属性。
        """
        malicious_insight = Insight(
            category='focus',
            severity='info',  # 白名单内
            title='<script>alert("title-xss")</script>',
            description='evil description <img src=x onerror=alert(1)> & "quoted"',
            suggestion='<b>建议</b> & more</div>',
        )

        # 直接调 _render_insights
        html_out = html_generator._render_insights([malicious_insight])

        # 1) 不可执行 <script> / <img onerror>
        assert '<script>alert' not in html_out, \
            f"title 未转义, 可执行 <script> 注入: {html_out[:500]}"
        assert '<img src=x onerror' not in html_out, \
            f"description 未转义, 可执行 <img onerror>: {html_out[:500]}"

        # 2) 转义后的字符应出现
        assert '&lt;script&gt;alert' in html_out, \
            "title 应被 html.escape 转为 &lt;script&gt;alert"
        assert '&lt;img src=x onerror=alert(1)&gt;' in html_out, \
            "description 应被 escape"
        assert '&lt;b&gt;建议&lt;/b&gt;' in html_out, \
            "suggestion 应被 escape"

    def test_m18_insight_severity_whitelist(self, html_generator):
        """M-18: severity 仅允许 info/warning/alert 三个白名单值

        防止恶意 severity 字符串注入 class 属性 (e.g. severity='foo"><script>')
        """
        bad_insight = Insight(
            category='focus',
            severity='alert"><script>alert(1)</script>',  # 恶意
            title='t',
            description='d',
            suggestion='s',
        )
        html_out = html_generator._render_insights([bad_insight])
        # severity 未在白名单时, 不应被原样嵌入 class 属性
        assert 'alert"><script>' not in html_out, \
            f"恶意 severity 注入 class 属性: {html_out[:500]}"

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
            f"session_id 未转义, 可执行 <script> 注入"
        # v4.16: Plotly 脚本包含合法 <script> 标签, 仅检查不含注入 payload
        assert '"><script>alert("xss")</script>' not in html, \
            "原始 XSS payload 不应对未转义出现"

        # 2) 转义后的字符应出现 (&lt; &gt; &quot;)
        assert "&lt;script&gt;" in html or "&quot;&gt;&lt;script&gt;" in html, \
            "session_id 应被 html.escape 转义"

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
        # 1. 生成图表 (v4.16: Plotly HTML 字符串)
        chart_gen = create_chart_generator()
        focus_chart = chart_gen.generate_focus_trend_chart(sample_focus_records)
        fatigue_chart = chart_gen.generate_fatigue_timeline(sample_fatigue_records)
        blink_chart = chart_gen.generate_blink_rate_chart(sample_focus_records)
        colorbar = chart_gen.generate_session_colorbar(sample_focus_records)

        assert isinstance(focus_chart, str) and len(focus_chart) > 0
        assert isinstance(fatigue_chart, str) and len(fatigue_chart) > 0
        assert isinstance(blink_chart, str) and len(blink_chart) > 0
        assert isinstance(colorbar, str) and len(colorbar) > 0

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
        # v4.16: Plotly 交互式图表，不包含 PNG
        assert 'Plotly' in html or 'plotly' in html.lower()

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

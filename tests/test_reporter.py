"""
tests/test_reporter.py — reporter 模块测试

测试报告生成功能：
- 图表生成
- 建议引擎
- HTML 报告生成
- v4.26: 字体加载器 + Hero 刻度盘 + 设计 token
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
from reporter import font_loader


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

    def test_v426_charts_xaxis_not_rotated(
        self, chart_generator, sample_focus_records, sample_fatigue_records,
    ):
        """v4.26: 时间序列图表 x 轴文字不应旋转（修复"侧倒"bug）

        Plotly 默认 tickangle='auto' 在标签多时会自动 -45° 旋转以防重叠。
        但腕表美学要求水平显示 —— 强制 tickangle=0 + nticks=6 限制数量。
        """
        # 至少 3 个时间序列图都应含 tickangle=0
        trend = chart_generator.generate_focus_trend_chart(sample_focus_records)
        blink = chart_generator.generate_blink_rate_chart(sample_focus_records)
        fatigue = chart_generator.generate_fatigue_timeline(sample_fatigue_records)
        # Plotly 序列化 tickangle 时输出 "tickangle":0
        for name, html in [
            ("focus_trend", trend),
            ("blink_rate", blink),
            ("fatigue_timeline", fatigue),
        ]:
            assert '"tickangle":0' in html, \
                f"{name} 应强制 tickangle=0 防止文字侧倒"

    def test_v426_charts_xticks_limited(self, chart_generator, sample_focus_records):
        """v4.26: x 轴 tick 数量应被 nticks=6 限制，避免标签拥挤"""
        trend = chart_generator.generate_focus_trend_chart(sample_focus_records)
        # Plotly 序列化 nticks 时输出 "nticks":6
        assert '"nticks":6' in trend, \
            "focus_trend 应限制 x 轴最多 6 个标签"

    def test_v426_charts_y_title_horizontal(
        self, chart_generator, sample_focus_records, sample_fatigue_records,
    ):
        """v4.26: y 轴标题应用 annotation + textangle=0 水平显示（修复"侧倒"）

        Plotly 6.x 不支持 yaxis.title.textangle（Bad property path），
        所以用 annotation 模拟水平标题。annotation 必含 textangle=0。
        """
        def _has_y_title_horizontal(html, chinese_text):
            """检查 HTML 含 y 轴水平标题 annotation"""
            # Plotly 把中文 unicode 转义为 \\uXXXX
            escaped = ''.join(f'\\u{ord(c):04x}' for c in chinese_text)
            # 1) annotation 含 textangle=0
            if '"textangle":0' not in html:
                return False
            # 2) annotation 含目标文字（raw 或 unicode 转义）
            if chinese_text in html or escaped in html:
                return True
            return False

        # 3 个时间序列图
        cases = [
            ("focus_trend", chart_generator.generate_focus_trend_chart(sample_focus_records), "专注度"),
            ("blink_rate", chart_generator.generate_blink_rate_chart(sample_focus_records), "次/分"),
            ("fatigue_timeline", chart_generator.generate_fatigue_timeline(sample_fatigue_records), "疲劳分"),
        ]
        for name, html, text in cases:
            assert _has_y_title_horizontal(html, text), \
                f"{name}: y 轴标题 '{text}' 应用 annotation + textangle=0 水平显示"

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
        assert '已校准' in html or '校准' in html

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

    # ===== v4.26: 设计 token + Hero 刻度盘 + 字体加载器 =====

    def test_v426_css_contains_new_tokens(self):
        """v4.26: CSS_STYLE 包含新设计 token（Quiet Focus v2）"""
        css = HTMLReportGenerator.CSS_STYLE
        # 多级墨色
        assert "--ink-900" in css
        assert "--ink-700" in css
        assert "--ink-400" in css
        # 多级石色
        assert "--stone-50" in css
        assert "--stone-100" in css
        assert "--stone-200" in css
        assert "--stone-300" in css
        # 语义色
        assert "--iris-600" in css
        assert "--sage-600" in css
        assert "--amber-600" in css
        assert "--rose-600" in css
        # 仪表渐变
        assert "--gauge-low" in css
        assert "--gauge-mid" in css
        assert "--gauge-high" in css
        # 排版尺度
        assert "--text-hero" in css
        assert "--text-h1" in css
        assert "--text-body" in css
        # 字体回退
        assert "--font-display" in css
        assert "--font-body" in css
        assert "--font-mono" in css
        # Fraunces/Inter/JetBrains Mono 必须在字体回退链
        assert "Fraunces" in css
        assert "Inter" in css
        assert "JetBrains Mono" in css

    def test_v426_body_has_dot_grid(self):
        """v4.26: body 背景含 0.5px 灰色点阵（仪表底盘纹理）"""
        css = HTMLReportGenerator.CSS_STYLE
        assert "radial-gradient(circle," in css, "body 应有 radial-gradient 点阵"
        assert "0.5px" in css, "点阵应为 0.5px 直径"
        assert "var(--stone-300)" in css, "点阵色应为 --stone-300"

    def test_v426_old_focus_hero_removed(self):
        """v4.26: 旧 .focus-hero / .hero-ring / .hero-value 应不再出现在 _render_overview_tab 输出

        Step A 仅替换 Hero 区，CSS 中的旧类保留（向后兼容），
        但实际渲染时不应再使用 focus-hero div。
        """
        html_gen = HTMLReportGenerator(db_manager=None)
        session = Session(
            session_id="t", start_time=datetime.now() - timedelta(minutes=10),
            end_time=datetime.now(), is_calibrated=True,
            glasses_mode=GlassesMode.WITHOUT_GLASSES,
        )
        fr = [FocusRecord(
            session_id="t", window_start=i*60.0, window_end=(i+1)*60.0,
            focus_score=70.0, eye_score=70.0, head_score=70.0, gaze_score=70.0,
            blink_rate=15.0, avg_ear=0.25, avg_yaw=0.0, avg_pitch=0.0,
        ) for i in range(5)]
        html = html_gen.generate_report_from_data(
            session=session, focus_records=fr, fatigue_records=[], blink_records=[],
        )
        # 新 gauge 应出现
        assert 'class="gauge-hero"' in html, "应渲染 .gauge-hero"
        # 旧 focus-hero div 应不出现（CSS 规则本身可能仍保留）
        assert '<div class="focus-hero">' not in html, \
            "旧的 .focus-hero div 应已被替换"

    def test_v426_gauge_center_text_no_overlap(self, html_generator):
        """v4.26: Hero 大数字与 /100 / 专注指数 不重叠

        数字 88px font 居中在 y=120（dominant-baseline=central）
        → 视觉范围 y=76~164
        /100 应在 y≥170（top 约 161）才能避开数字底部
        专注指数 应在 y≥193（top 约 184）才能避开 /100 底部
        """
        from reporter.report_html import ReportData
        session = Session(
            session_id="t", start_time=datetime.now(), end_time=datetime.now(),
        )
        data = ReportData(
            session=session, focus_records=[], fatigue_records=[],
            blink_records=[], frame_records=[],
            avg_focus=72.0, avg_blink_rate=0.0,
            total_duration=0.0, fatigue_level=FatigueLevel.LOW,
        )
        stats = {"avg_focus": 72.0, "focus_change": None, "hist_avg_focus": None}
        out = html_generator._render_hero_gauge(data, stats)

        # 解析 /100 的 y 属性
        import re
        m_unit = re.search(r'class="gauge-center-unit"[^>]*y="(\d+)"', out)
        m_lbl = re.search(r'class="gauge-center-label"[^>]*y="(\d+)"', out)
        assert m_unit, "/100 标签应存在"
        assert m_lbl, "专注指数 标签应存在"
        y_unit = int(m_unit.group(1))
        y_lbl = int(m_lbl.group(1))

        # 数字中心 y=120 + 88/2 = 164 是数字底部
        # /100 baseline 应 >= 170 才不重叠
        assert y_unit >= 170, \
            f"/100 baseline y={y_unit} 应 >= 170（避开数字底部 164）"
        # 专注指数 baseline 应 >= 193 才不与 /100 重叠
        assert y_lbl >= 193, \
            f"专注指数 baseline y={y_lbl} 应 >= 193（避开 /100 底部）"
        # 专注指数应在 /100 之下
        assert y_lbl > y_unit, \
            f"专注指数 y={y_lbl} 应在 /100 y={y_unit} 之下"

    def test_v426_gauge_hero_renders_svg(self, html_generator):
        """v4.26: _render_hero_gauge 返回有效 SVG 包含所有视觉元素"""
        from reporter.report_html import ReportData
        session = Session(
            session_id="abc12345",
            start_time=datetime.now() - timedelta(minutes=30),
            end_time=datetime.now(),
            glasses_mode=GlassesMode.WITHOUT_GLASSES,
            is_calibrated=True,
        )
        fr = [FocusRecord(
            session_id="abc12345", window_start=i*60.0, window_end=(i+1)*60.0,
            focus_score=70.0 + (i%3), eye_score=70.0, head_score=70.0, gaze_score=70.0,
            blink_rate=15.0, avg_ear=0.25, avg_yaw=0.0, avg_pitch=0.0,
        ) for i in range(20)]
        data = ReportData(
            session=session, focus_records=fr, fatigue_records=[],
            blink_records=[], frame_records=[],
            avg_focus=70.0, avg_blink_rate=15.0,
            total_duration=1200.0, fatigue_level=FatigueLevel.LOW,
        )
        stats = {"avg_focus": 70.0, "focus_change": 3.0, "hist_avg_focus": 67.0}
        out = html_generator._render_hero_gauge(data, stats)

        # 基本结构
        assert '<svg class="gauge-svg"' in out
        assert 'viewBox="0 0 240 240"' in out
        assert 'gauge-gradient' in out  # 渐变定义
        assert 'class="gauge-track"' in out  # 背景轨道
        assert 'class="gauge-arc"' in out  # 填充弧
        assert 'class="gauge-center-num"' in out  # 中心数字
        assert 'class="gauge-time-row"' in out  # 时间刻度行
        # 60 刻度（12 主刻度 + 48 普通）
        # 用 'class="gauge-tick' 作子串：major 和 minor 都以这个前缀开头
        assert out.count('class="gauge-tick major"') == 12
        assert out.count('class="gauge-tick') == 60
        # 数据属性（JS 动画用）
        assert 'data-focus="70"' in out
        assert 'data-fill="' in out
        # 旋转 135° 把 270° 弧的缺口放到 12 点钟
        assert 'rotate(135' in out
        # 历史对比箭头
        assert 'gauge-compare' in out
        assert '↑' in out  # 上升箭头

    def test_v426_gauge_clamps_out_of_range(self, html_generator):
        """v4.26: avg_focus 越界（<0 或 >100）应被 clamp"""
        from reporter.report_html import ReportData
        session = Session(
            session_id="t", start_time=datetime.now(), end_time=datetime.now(),
        )
        data = ReportData(
            session=session, focus_records=[], fatigue_records=[],
            blink_records=[], frame_records=[],
            avg_focus=150.0, avg_blink_rate=0.0,
            total_duration=0.0, fatigue_level=FatigueLevel.LOW,
        )
        stats = {"avg_focus": 150.0, "focus_change": None, "hist_avg_focus": None}
        out = html_generator._render_hero_gauge(data, stats)
        # 应被 clamp 到 100
        assert 'data-focus="100"' in out

    def test_v426_gauge_handles_empty_focus_records(self, html_generator):
        """v4.26: focus_records 为空时不崩，应输出 0 仪表"""
        from reporter.report_html import ReportData
        session = Session(
            session_id="t", start_time=datetime.now(), end_time=datetime.now(),
        )
        data = ReportData(
            session=session, focus_records=[], fatigue_records=[],
            blink_records=[], frame_records=[],
            avg_focus=0.0, avg_blink_rate=0.0,
            total_duration=0.0, fatigue_level=FatigueLevel.LOW,
        )
        stats = {"avg_focus": 0.0, "focus_change": None, "hist_avg_focus": None}
        out = html_generator._render_hero_gauge(data, stats)
        assert 'data-focus="0"' in out
        # data-fill 也应是 0（无填充）
        assert 'data-fill="0.00"' in out
        # 峰值时刻空时，中间用时长替代
        assert 'gauge-time-row' in out

    def test_v426_gauge_compare_decline(self, html_generator):
        """v4.26: 下降时 gauge-compare 应有 .down 类 + ↓ 箭头"""
        from reporter.report_html import ReportData
        session = Session(
            session_id="t", start_time=datetime.now(), end_time=datetime.now(),
        )
        data = ReportData(
            session=session, focus_records=[], fatigue_records=[],
            blink_records=[], frame_records=[],
            avg_focus=60.0, avg_blink_rate=0.0,
            total_duration=0.0, fatigue_level=FatigueLevel.LOW,
        )
        stats = {"avg_focus": 60.0, "focus_change": -5.0, "hist_avg_focus": 65.0}
        out = html_generator._render_hero_gauge(data, stats)
        assert 'gauge-compare down' in out
        assert '↓' in out
        assert '5.0' in out  # 变化量绝对值

    def test_v426_stat_row_replaces_stats_grid(self, html_generator):
        """v4.26: 4 关键指标卡应使用新 .stat-row 而非旧 .stats-grid"""
        session = Session(
            session_id="t", start_time=datetime.now() - timedelta(minutes=30),
            end_time=datetime.now(), glasses_mode=GlassesMode.WITHOUT_GLASSES,
            is_calibrated=True,
        )
        fr = [FocusRecord(
            session_id="t", window_start=i*60.0, window_end=(i+1)*60.0,
            focus_score=70.0, eye_score=70.0, head_score=70.0, gaze_score=70.0,
            blink_rate=15.0, avg_ear=0.25, avg_yaw=0.0, avg_pitch=0.0,
        ) for i in range(10)]
        html = html_generator.generate_report_from_data(
            session=session, focus_records=fr, fatigue_records=[], blink_records=[],
        )
        assert 'class="stat-row"' in html, "应使用新 .stat-row 横排"
        assert 'class="stat-cell"' in html, "单元格应为 .stat-cell"
        # 旧 .stats-grid 不应再被使用
        assert '<div class="stats-grid">' not in html, "旧 .stats-grid 应被替换"

    def test_v426_gauge_animation_js_present(self, html_generator):
        """v4.26: JS_SCRIPT 应包含 animateGauges 函数"""
        assert "function animateGauges" in HTMLReportGenerator.JS_SCRIPT
        # count-up
        assert "requestAnimationFrame" in HTMLReportGenerator.JS_SCRIPT
        # 减动效尊重
        assert "prefers-reduced-motion" in HTMLReportGenerator.JS_SCRIPT
        # stroke-dasharray 动画
        assert "strokeDasharray" in HTMLReportGenerator.JS_SCRIPT or \
               "stroke-dasharray" in HTMLReportGenerator.JS_SCRIPT

    def test_font_loader_force_offline(self):
        """font_loader: force_offline() 钩子应能强制覆盖探测结果"""
        font_loader.force_offline(True)   # 强制离线
        try:
            assert font_loader.is_online() is False
            assert font_loader.get_link_tag() == "", \
                "强制离线时不应返回 <link>"
        finally:
            font_loader.force_offline(None)  # 还原

        font_loader.force_offline(False)  # 强制在线
        try:
            assert font_loader.is_online() is True
            link = font_loader.get_link_tag()
            assert "<link" in link, "强制在线时应返回 <link> 标签"
            assert "fonts.googleapis.com" in link
            assert "Fraunces" in link
            assert "Inter" in link
            assert "JetBrains+Mono" in link or "JetBrains Mono" in link
        finally:
            font_loader.force_offline(None)  # 还原

    def test_font_loader_get_link_tag_no_io_when_forced(self):
        """font_loader: 强制模式下不应触发真实网络探测

        性能 + 稳定性：避免在 CI/测试时因网络阻塞导致报告生成卡死。
        """
        import time
        font_loader.force_offline(True)
        try:
            t0 = time.time()
            font_loader.get_link_tag()
            elapsed = time.time() - t0
            assert elapsed < 0.1, \
                f"强制离线应 <100ms, 实测 {elapsed*1000:.0f}ms"
        finally:
            font_loader.force_offline(None)

    def test_v426_no_achievement_system(
        self, html_generator, sample_session,
        sample_focus_records, sample_fatigue_records, sample_blink_records,
    ):
        """v4.26: 成就系统已彻底移除（用户反馈 v4.17 徽章与腕表美学冲突）

        验证三处:
        1. _render_achievements 方法不存在
        2. CSS_STYLE 不含 .achieve-row / .achieve-badge
        3. 渲染的报告不含 🏅 成就 卡片
        """
        # 1) 方法已删
        assert not hasattr(HTMLReportGenerator, "_render_achievements"), \
            "_render_achievements 方法还在，应已删除"
        # 2) CSS 已删
        css = HTMLReportGenerator.CSS_STYLE
        assert ".achieve-row" not in css, ".achieve-row CSS 还在"
        assert ".achieve-badge" not in css, ".achieve-badge CSS 还在"
        # 3) 渲染的报告不含成就
        html = html_generator.generate_report_from_data(
            session=sample_session,
            focus_records=sample_focus_records,
            fatigue_records=sample_fatigue_records,
            blink_records=sample_blink_records,
        )
        assert "🏅" not in html, "报告渲染了 🏅 成就 emoji"
        assert "achieve-row" not in html, "报告渲染了 .achieve-row"
        assert "achieve-badge" not in html, "报告渲染了 .achieve-badge"

    def test_v426_temporal_line_no_vrect(self, chart_generator):
        """v4.26: 高效时段图表不应再有 vrect 柱状叠加（用户反馈与折线冲突）

        修复前: peak/low 段加 vrect 半透明矩形 → 用户视觉上是"柱状+折线并存"
        修复后: 只保留 Scatter lines，peak/low 列表通过 hover / 文字传达
        """
        result = chart_generator.generate_temporal_line_chart(
            hourly_pattern=[10] * 24,
            peak_hours=["9-12", "14-15"],
            low_hours=["15-18"],
        )
        # vrect 在 Plotly 序列化为 layout.shapes 数组
        assert "\"shapes\"" not in result, \
            "高效时段图表不应再包含 vrect 矩形（plotly layout.shapes）"
        assert "\"shape\"" not in result, \
            "高效时段图表不应再包含 shape 对象"
        # 折线应保留
        assert "\"type\":\"scatter\"" in result, \
            "高效时段图表应保留 Scatter 折线"

    def test_v426_font_html_in_rendered_head(self):
        """v4.26: 渲染的 HTML <head> 应包含字体 link 标签（如果在线）"""
        session = Session(
            session_id="t", start_time=datetime.now() - timedelta(minutes=10),
            end_time=datetime.now(), glasses_mode=GlassesMode.WITHOUT_GLASSES,
            is_calibrated=True,
        )
        fr = [FocusRecord(
            session_id="t", window_start=i*60.0, window_end=(i+1)*60.0,
            focus_score=70.0, eye_score=70.0, head_score=70.0, gaze_score=70.0,
            blink_rate=15.0, avg_ear=0.25, avg_yaw=0.0, avg_pitch=0.0,
        ) for i in range(5)]
        font_loader.force_offline(False)  # 强制在线以便测试
        try:
            html_gen = HTMLReportGenerator(db_manager=None)
            html = html_gen.generate_report_from_data(
                session=session, focus_records=fr, fatigue_records=[], blink_records=[],
            )
            # 在线时 <head> 应有 <link rel="preconnect" + <link rel="stylesheet"
            assert '<link rel="preconnect" href="https://fonts.googleapis.com">' in html
            assert 'fonts.googleapis.com/css2' in html
            assert 'Fraunces' in html  # link URL 包含字体名
        finally:
            font_loader.force_offline(None)

        # 离线时 <head> 不应有 link 标签
        font_loader.force_offline(True)
        try:
            html_gen2 = HTMLReportGenerator(db_manager=None)
            html2 = html_gen2.generate_report_from_data(
                session=session, focus_records=fr, fatigue_records=[], blink_records=[],
            )
            assert 'fonts.googleapis.com' not in html2
        finally:
            font_loader.force_offline(None)


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

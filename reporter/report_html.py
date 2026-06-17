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
from reporter.font_loader import get_link_tag as _font_link_tag

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

    # CSS 样式 (v4.26: 腕表背透视图 · Quiet Focus v2)
    CSS_STYLE = """
        <style>
            /* ═══════════════════════════════════════
               Quiet Focus · 精密仪器美学 v4.26
               "腕表背透视图"
               Palette: Warm Ink · Stone · Iris · Sage
               Typography: Fraunces · Inter · JetBrains Mono
               ═══════════════════════════════════════ */

            /* 字体回退链 —— 在最前，离线时浏览器自然落到系统字体 */
            :root {
                --font-display: 'Fraunces', Georgia, 'Times New Roman', 'Source Han Serif SC', 'Noto Serif SC', 'SimSun', serif;
                --font-body:    'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Hiragino Sans GB', sans-serif;
                --font-mono:    'JetBrains Mono', 'Cascadia Mono', Consolas, 'SF Mono', 'Courier New', monospace;
            }

            /* 调色板（分层：墨 / 石 / 语义） */
            :root {
                /* 墨 · 文本 */
                --ink-900: #1A1816;
                --ink-700: #23201E;
                --ink-400: #5A5650;
                /* 石 · 背景 */
                --stone-50:  #F8F6F2;
                --stone-100: #F4F2EE;
                --stone-200: #E6E2DC;
                --stone-300: #D4D0CA;
                --card:      #FEFDFB;
                /* 语义色 */
                --iris-600:  #4A3A7A;
                --sage-600:  #4A7A5A;
                --amber-600: #B87333;
                --rose-600:  #A04A4A;
                --quiet:     #8B8680;
                /* 仪表渐变（rose → amber → sage，70+ 为佳） */
                --gauge-low:  var(--rose-600);
                --gauge-mid:  var(--amber-600);
                --gauge-high: var(--sage-600);
                /* 别名（兼容 v4.15- 旧 CSS） */
                --ink:        var(--ink-700);
                --stone:      var(--stone-100);
                --iris:       var(--iris-600);
                --sage:       var(--sage-600);
                --amber:      var(--amber-600);
                --rose:       var(--rose-600);
                --line:       var(--stone-200);
                --line-light: #F0EDE8;
            }

            /* 排版尺度 */
            :root {
                --text-hero:    7rem;
                --text-h1:      1.4rem;
                --text-h2:      1rem;
                --text-body:    0.875rem;
                --text-caption: 0.75rem;
                --text-micro:   0.6875rem;
            }

            * { margin: 0; padding: 0; box-sizing: border-box; }

            body {
                font-family: var(--font-body);
                font-size: var(--text-body);
                line-height: 1.55;
                color: var(--ink-700);
                background-color: var(--stone-100);
                background-image: radial-gradient(circle, var(--stone-300) 0.5px, transparent 0.5px);
                background-size: 28px 28px;
                background-position: 0 0;
                padding: 32px 20px;
                -webkit-font-smoothing: antialiased;
                -moz-osx-font-smoothing: grayscale;
            }
            .container { max-width: 880px; margin: 0 auto; }

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
                font-family: var(--font-display);
                font-size: var(--text-h1); font-weight: 500; color: var(--ink-900);
                letter-spacing: -0.5px; margin-bottom: 4px;
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
                font-family: var(--font-display);
                font-size: var(--text-h2); font-weight: 500; color: var(--ink-900);
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

            /* ═══════════════════════════════════════
               v4.26: 腕表背透视图 — 新增组件
               ═══════════════════════════════════════ */

            /* ── Hero 刻度盘（270° SVG 仪表） ── */
            .gauge-hero {
                text-align: center;
                padding: 56px 0 36px;
                position: relative;
            }
            .gauge-svg {
                width: 240px;
                height: 240px;
                display: block;
                margin: 0 auto;
            }
            .gauge-track {
                fill: none;
                stroke: var(--stone-200);
                stroke-width: 2;
            }
            .gauge-arc {
                fill: none;
                stroke: url(#gauge-gradient);
                stroke-width: 6;
                stroke-linecap: round;
                transition: stroke-dasharray 900ms cubic-bezier(0.16, 1, 0.3, 1);
            }
            .gauge-tick {
                stroke: var(--stone-300);
                stroke-width: 1;
                stroke-linecap: round;
            }
            .gauge-tick.major {
                stroke: var(--quiet);
                stroke-width: 1.5;
            }
            .gauge-center-num {
                font-family: var(--font-display);
                font-size: 88px;
                font-weight: 500;
                fill: var(--ink-900);
                letter-spacing: -3px;
                text-anchor: middle;
                dominant-baseline: central;
            }
            .gauge-center-label {
                font-family: var(--font-body);
                font-size: 11px;
                letter-spacing: 2.5px;
                fill: var(--quiet);
                text-anchor: middle;
                font-weight: 500;
                text-transform: uppercase;
            }
            .gauge-center-unit {
                font-family: var(--font-body);
                font-size: 11px;
                fill: var(--quiet);
                text-anchor: middle;
            }
            .gauge-time-row {
                display: flex;
                justify-content: space-between;
                width: 280px;
                margin: 10px auto 0;
                font-family: var(--font-mono);
                font-size: 10px;
                color: var(--quiet);
                letter-spacing: 1px;
            }
            .gauge-compare {
                margin-top: 12px;
                font-family: var(--font-body);
                font-size: 13px;
                font-weight: 500;
                color: var(--iris-600);
            }
            .gauge-compare.down { color: var(--rose-600); }

            /* ── 横排 stat row（替换 .stats-grid） ── */
            .stat-row {
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 1px;
                background: var(--stone-200);
                border: 1px solid var(--stone-200);
                margin-bottom: 32px;
            }
            .stat-row .stat-cell {
                background: var(--card);
                padding: 18px 20px;
                text-align: left;
            }
            .stat-row .stat-value {
                font-family: var(--font-mono);
                font-size: 1.5rem;
                font-weight: 500;
                color: var(--ink-900);
                line-height: 1.1;
                letter-spacing: -0.5px;
            }
            .stat-row .stat-label {
                font-size: 10px;
                color: var(--quiet);
                text-transform: uppercase;
                letter-spacing: 1.5px;
                margin-top: 8px;
                font-weight: 500;
            }
            .stat-row .stat-sub {
                font-size: 11px;
                color: var(--ink-400);
                margin-top: 4px;
            }

            /* ── 减少动效尊重 ── */
            @media (prefers-reduced-motion: reduce) {
                .gauge-arc { transition: none; }
                * { animation-duration: 0.001ms !important; }
            }
        </style>
    """

    # v4.26: 字体 link 标签（实例属性 self._font_html 在 __init__ 中探测并缓存）

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

        // v4.26: Hero 刻度盘 mount 动画
        // 1) 数字 0 → target (count-up, 900ms ease-out cubic)
        // 2) 弧形 stroke-dasharray 0 → target (CSS transition 900ms)
        // 尊重 prefers-reduced-motion: 直接跳到目标值
        function animateGauges() {
            var prefersReduce = window.matchMedia &&
                window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            document.querySelectorAll('.gauge-hero').forEach(function(hero) {
                var target = parseFloat(hero.dataset.focus) || 0;

                // 弧形填充
                var arc = hero.querySelector('.gauge-arc');
                if (arc) {
                    var fillLen = parseFloat(arc.dataset.fill) || 0;
                    var circ = parseFloat(arc.getAttribute('stroke-dasharray').split(' ')[1]) || 565.49;
                    if (prefersReduce) {
                        arc.style.strokeDasharray = fillLen + ' ' + (circ - fillLen);
                    } else {
                        requestAnimationFrame(function() {
                            arc.style.strokeDasharray = fillLen + ' ' + (circ - fillLen);
                        });
                    }
                }

                // 数字 count-up
                var num = hero.querySelector('.gauge-center-num');
                if (!num) return;
                if (prefersReduce) {
                    num.textContent = Math.round(target);
                    return;
                }
                var duration = 900;
                var startTime = performance.now();
                function step(now) {
                    var t = Math.min((now - startTime) / duration, 1);
                    var eased = 1 - Math.pow(1 - t, 3);
                    num.textContent = Math.round(target * eased);
                    if (t < 1) requestAnimationFrame(step);
                }
                requestAnimationFrame(step);
            });
        }

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', animateGauges);
        } else {
            animateGauges();
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

        v4.26: 实例化时探测 Google Fonts 可达性，缓存到 self._font_html
        （一次性，后续 _render_html 复用，不重复探测）

        Args:
            db_manager: 数据库管理器实例
            chart_generator: 图表生成器实例
            insights_engine: 建议引擎实例
        """
        self.db = db_manager
        self.chart_gen = chart_generator or create_chart_generator()
        # v4.10: 传递 db 给建议引擎（用于历史对比）
        self.insights_engine = insights_engine or create_insights_engine(db=db_manager)
        # v4.26: 探测 Google Fonts 可达性，结果缓存到 <head>
        self._font_html = _font_link_tag()

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
    {self._font_html}
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

    def _render_hero_gauge(self, data: ReportData, stats: dict) -> str:
        """v4.26: Hero 刻度盘 — 270° SVG 仪表，腕表背透视觉锚点

        设计意图：让 72 分不再是裸数字，而是一个真正的仪表盘——
        270° 真实刻度 + 渐变填充（rose→amber→sage 分段）
        + 60 刻度（含 12 主刻度）+ 时间刻度行 + 历史对比箭头。

        数字 mount 时由 JS count-up 0→target（900ms ease-out），
        弧形 stroke-dasharray 由 CSS transition 同步动画。
        """
        import math
        from datetime import timedelta as _td

        score = max(0, min(100, round(stats["avg_focus"])))

        # SVG 数学
        cx, cy, r = 120, 120, 90
        circ = 2 * math.pi * r          # ≈ 565.49
        full_270 = circ * 0.75          # ≈ 424.12 (270° 弧长)
        fill_len = full_270 * (score / 100.0)
        gap_270 = circ - full_270       # 90° 缺口

        # 60 刻度（每 4.5° 一格，12 主刻度 = 每 5 格）
        tick_lines = []
        for i in range(60):
            angle = i * (270.0 / 60)    # 0 → 265.5
            is_major = (i % 5 == 0)
            cls = "gauge-tick major" if is_major else "gauge-tick"
            # 短刻度 y=36→44；主刻度 y=32→44
            y1, y2 = (32, 44) if is_major else (36, 44)
            tick_lines.append(
                f'<line class="{cls}" x1="120" y1="{y1}" x2="120" y2="{y2}" '
                f'transform="rotate({angle:.1f} 120 120)" />'
            )
        ticks_svg = "\n                ".join(tick_lines)

        # 峰值时刻（focus_score 最高的窗口）
        peak_str = ""
        try:
            if data.focus_records and data.session.start_time:
                best = max(data.focus_records, key=lambda r: (r.focus_score or 0))
                if best.window_start is not None:
                    peak_dt = data.session.start_time + _td(seconds=best.window_start)
                    peak_str = f"★ {peak_dt.strftime('%H:%M')} 峰值"
        except Exception:
            pass

        # 时间刻度行：开始 / 峰值(或时长) / 结束
        sess = data.session
        start_str = sess.start_time.strftime('%H:%M') if sess.start_time else "--:--"
        if sess.end_time:
            end_str = sess.end_time.strftime('%H:%M')
        elif sess.start_time and data.total_duration:
            end_dt = sess.start_time + _td(seconds=data.total_duration)
            end_str = end_dt.strftime('%H:%M')
        else:
            end_str = "--:--"
        middle_str = peak_str if peak_str else f"{int(data.total_duration/60)} min"

        # 历史对比箭头
        compare_html = ""
        change = stats.get("focus_change")
        if change is not None and stats.get("hist_avg_focus") is not None:
            hist = stats["hist_avg_focus"]
            if change >= 0:
                compare_html = (
                    f'<div class="gauge-compare">'
                    f'↑ +{change:.0f}  vs  历史 {hist:.0f}'
                    f'</div>'
                )
            else:
                compare_html = (
                    f'<div class="gauge-compare down">'
                    f'↓ {change:.0f}  vs  历史 {hist:.0f}'
                    f'</div>'
                )

        return f'''
            <div class="gauge-hero" data-focus="{score}">
                <svg class="gauge-svg" viewBox="0 0 240 240" xmlns="http://www.w3.org/2000/svg"
                     role="img" aria-label="专注指数仪表盘 {score} / 100">
                    <defs>
                        <linearGradient id="gauge-gradient" x1="0%" y1="100%" x2="100%" y2="0%">
                            <stop offset="0%"   stop-color="#A04A4A" />
                            <stop offset="50%"  stop-color="#B87333" />
                            <stop offset="100%" stop-color="#4A7A5A" />
                        </linearGradient>
                    </defs>

                    <!-- 背景轨道（270° 静态，缺口朝上） -->
                    <circle class="gauge-track" cx="{cx}" cy="{cy}" r="{r}"
                            stroke-dasharray="{full_270:.2f} {gap_270:.2f}"
                            transform="rotate(135 {cx} {cy})" />

                    <!-- 填充弧（JS 动画 stroke-dasharray） -->
                    <circle class="gauge-arc" cx="{cx}" cy="{cy}" r="{r}"
                            stroke-dasharray="0 {circ:.2f}"
                            data-fill="{fill_len:.2f}"
                            transform="rotate(135 {cx} {cy})" />

                    <!-- 60 刻度（含 12 主刻度） -->
                    <g transform="rotate(135 {cx} {cy})">
                        {ticks_svg}
                    </g>

                    <!-- 中心数字（JS count-up 0→target） -->
                    <text class="gauge-center-num" x="{cx}" y="{cy}">0</text>
                    <text class="gauge-center-unit" x="{cx}" y="{cy + 58}">/ 100</text>
                    <text class="gauge-center-label" x="{cx}" y="{cy + 80}">专注指数</text>
                </svg>

                <div class="gauge-time-row">
                    <span>{start_str}</span>
                    <span>{middle_str}</span>
                    <span>{end_str}</span>
                </div>

                {compare_html}
            </div>
        '''

    def _render_overview_tab(self, data: ReportData, charts: dict) -> str:
        """v4.26: Hero 刻度盘 + 4 横排指标 + 周报 + 成就"""
        stats = self._compute_overview_stats(data)
        parts = []

        # ── v4.26: Hero 刻度盘（替换旧 .focus-hero）──
        parts.append(self._render_hero_gauge(data, stats))

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

        parts.append('<div class="stat-row">')
        for label, val, sub in cards:
            sub_html = f'<div class="stat-sub">{sub}</div>' if sub else ""
            parts.append(
                f'<div class="stat-cell">'
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

        # ── v4.25: 本周聚合（周报嵌入概览）──
        weekly_html = self._render_weekly_summary()
        if weekly_html:
            parts.append(weekly_html)

        return "\n".join(parts)

    # v4.26: 成就系统已移除（用户反馈：v4.17 引入的徽章与"腕表背透"美学冲突，删除）
    # 之前的方法 _render_achievements、调用点、.achieve-row / .achieve-badge CSS 一并删除

    # ════════════════════════════════════════════
    # v4.25: 周聚合（嵌入主报告概览 Tab）
    # ════════════════════════════════════════════
    def _compute_weekly_stats(self):
        """计算本周聚合统计数据"""
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

        total_minutes = 0.0
        total_score = 0.0
        score_count = 0
        session_list = []

        for sess in sessions:
            dur = sess.duration_seconds() or 0.0
            total_minutes += dur / 60.0
            records = self.db.get_focus_records(sess.session_id)
            avg = 0.0
            if records:
                valid = [r.focus_score for r in records if r.focus_score is not None]
                if valid:
                    avg = sum(valid) / len(valid)
                    total_score += avg
                    score_count += 1
            session_list.append({
                "id": sess.session_id[:8],
                "date": sess.start_time.strftime("%m-%d %H:%M"),
                "duration": dur / 60.0,
                "score": avg,
            })

        avg_score = total_score / max(1, score_count) if score_count > 0 else 0
        days_active = len(set(s.start_time.strftime("%Y-%m-%d") for s in sessions))

        return {
            "total_minutes": total_minutes,
            "avg_score": avg_score,
            "session_count": len(sessions),
            "days_active": days_active,
            "sessions": session_list,
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

        # 会话明细表
        rows = "".join(
            f'<tr><td>{s["date"]}</td><td>{s["duration"]:.0f}分</td>'
            f'<td>{s["score"]:.0f}分</td></tr>'
            for s in stats["sessions"][:10]
        )
        table = f"""
        <table class="detail-table" style="margin-top:8px;">
            <tr><th style="text-align:left;color:var(--quiet);font-weight:500;font-size:11px;">时间</th>
                <th style="text-align:left;color:var(--quiet);font-weight:500;font-size:11px;">时长</th>
                <th style="text-align:left;color:var(--quiet);font-weight:500;font-size:11px;">专注度</th></tr>
            {rows}
        </table>""" if stats["sessions"] else ""

        return f"""
        <div class="card" style="border-left:2px solid var(--iris);">
            <h2>📊 本周统计 <span style="font-size:11px;color:var(--quiet);font-weight:400;">{stats["range"]}</span></h2>
            {hero}
            {table}
        </div>"""

    def _render_analysis_tab(self, charts: dict) -> str:
        """v4.15: 数据分析 Tab（v4.24: 增加 AI 分析摘要）"""
        parts = []

        # ── AI 分析摘要（始终显示卡片，无数据时显示提示）──
        try:
            summary = self._generate_ai_summary()
            if not summary:
                summary = '<span style="color:#9E9A96;">数据不足，暂无法生成分析报告。</span>'
        except Exception as e:
            logger.warning("AI 分析摘要异常: %s", e)
            summary = '<span style="color:#B55C5C;">分析生成异常，请查看下方图表数据。</span>'
        parts.append(f'''
            <div class="card" style="background:linear-gradient(135deg,#F4F2EE,#FFFFFF);border-left:4px solid #5B4A8C;">
                <h2>🤖 专注度分析报告</h2>
                <div class="card-desc" style="font-size:15px;line-height:1.8;color:#23201E;padding:8px 0;">
                    {summary}
                </div>
            </div>''')

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

        return "\n".join(parts)

    def _generate_ai_summary(self) -> str:
        """生成 AI 分析摘要

        优先使用已配置的 LLM 后端（API/本地），不可用时回退到内置模板。
        """
        data = self._data if hasattr(self, '_data') and self._data else None
        if not data or not data.session:
            return ""

        # ── 尝试 LLM 后端 ──
        try:
            from config import get_yaml_value
            from concurrent.futures import ThreadPoolExecutor as _TPE, TimeoutError as _TO
            from analyzer.llm_client import create_llm_client

            backend = get_yaml_value("ai", "backend", default="template")
            if backend != "template":
                api_key = get_yaml_value("ai", "api_key", default="")
                base_url = get_yaml_value("ai", "base_url", default="")
                provider = get_yaml_value("ai", "provider", default="openai")

                kwargs = {"api_key": api_key}
                if backend == "openai":
                    kwargs["provider"] = provider
                    kwargs["base_url"] = base_url
                elif backend == "ollama":
                    kwargs["base_url"] = get_yaml_value("ai", "ollama_url",
                                                         default="http://127.0.0.1:11434")

                client = create_llm_client(backend, **kwargs)
                if client.available:
                    # 构造分析数据
                    fr = data.focus_records or []
                    dur = data.total_duration or 0.0
                    avg = data.avg_focus or 50.0

                    # 三段式专注趋势
                    third = max(1, len(fr) // 3)
                    seg_start = self._calc_avg_focus(fr[:third]) if len(fr) >= third else avg
                    seg_mid = self._calc_avg_focus(fr[third:2*third]) if len(fr) >= 2*third else avg
                    seg_end = self._calc_avg_focus(fr[-third:]) if len(fr) >= third else avg

                    # 分心统计（近似）
                    dist_count = len(getattr(data, 'distraction_records', None) or [])
                    head_pct = 50 if dist_count > 0 else 0  # 近似值
                    gaze_pct = 50 if dist_count > 0 else 0

                    # 疲劳等级（带空值保护）
                    fl = getattr(data, 'fatigue_level', None)
                    if fl is None:
                        fatigue_str = "LOW"
                    else:
                        fatigue_str = fl.name.upper() if hasattr(fl, 'name') else str(fl).upper()

                    llm_data = {
                        "duration": int(dur / 60),
                        "avg_focus": avg,
                        "baseline": 60,
                        "seg_start": seg_start,
                        "seg_mid": seg_mid,
                        "seg_end": seg_end,
                        "distractions": dist_count,
                        "head_pct": head_pct,
                        "gaze_pct": gaze_pct,
                        "fatigue": fatigue_str,
                        "pomo_count": 0,
                        "streak": 0,
                    }
                    # 超时保护：LLM 调用最多等 15 秒
                    with _TPE(max_workers=1) as _pool:
                        _fut = _pool.submit(client.analyze, llm_data)
                        result = _fut.result(timeout=15)
                    if result and result.strip():
                        logger.info("AI 分析: LLM 后端 (%s) 生成成功", client.name)
                        return result.strip()
                    logger.info("AI 分析: LLM 后端返回空结果，回退模板")

        except ImportError:
            pass  # 模块不存在 → 回退模板
        except _TO:
            logger.warning("AI 分析: LLM 调用超时 (15s)，回退模板")
        except Exception:
            logger.debug("AI 分析: LLM 异常，回退模板", exc_info=True)

        # ── 内置模板（零依赖，始终可用）──
        import html as _html
        session = data.session
        fr = data.focus_records or []
        fatigue = data.fatigue_records or []
        dist = getattr(data, 'distraction_records', None) or []

        avg = self._calc_avg_focus(fr)
        if avg == 0 and not fr:
            return ""

        parts = []
        # 整体评价
        if avg >= 80:
            parts.append(f"本次会话专注度 {avg:.0f} 分，表现优秀，保持了良好的工作状态。")
        elif avg >= 65:
            parts.append(f"本次会话专注度 {avg:.0f} 分，整体表现良好。")
        elif avg >= 50:
            parts.append(f"本次会话专注度 {avg:.0f} 分，适中水平，有一定提升空间。")
        else:
            parts.append(f"本次会话专注度 {avg:.0f} 分，偏低，建议调整工作节奏。")

        # 时间分段
        dur = session.duration_seconds() or 0
        if dur > 180 and fr:
            third = len(fr) // 3
            start_avg = self._calc_avg_focus(fr[:third]) if third > 0 else avg
            end_avg = self._calc_avg_focus(fr[-third:]) if third > 0 else avg
            if start_avg - end_avg > 10:
                parts.append(f"前段专注度 {start_avg:.0f} 分，后段降至 {end_avg:.0f} 分，"
                             f"下降 {start_avg - end_avg:.0f} 分，中途可能需要休息。")
            elif end_avg - start_avg > 10:
                parts.append(f"后段专注度 {end_avg:.0f} 分高于前段 {start_avg:.0f} 分，渐入佳境。")

        # 疲劳
        if fatigue:
            high_count = sum(1 for r in fatigue if r.fatigue_level.name == "HIGH")
            if high_count > len(fatigue) * 0.3:
                parts.append("疲劳信号较多，建议今晚保证充足睡眠。")
            elif high_count > 0:
                parts.append("有轻微疲劳迹象，注意适时放松眼部。")

        # 时长
        minutes = dur / 60
        if minutes > 90:
            parts.append(f"连续工作 {minutes:.0f} 分钟，建议使用番茄钟规律休息。")
        elif minutes > 0:
            parts.append(f"会话时长 {minutes:.0f} 分钟。")

        # 分心
        dist_count = len(dist)
        if dist_count > 10:
            parts.append(f"分心 {dist_count} 次偏多，可尝试排除环境干扰。")

        return _html.escape("".join(parts))

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
        """计算平均专注度（过滤 None 值）"""
        if not focus_records:
            return 0.0
        scores = [r.focus_score for r in focus_records if r.focus_score is not None]
        if not scores:
            return 0.0
        return sum(scores) / len(scores)

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

        # 聚合统计
        total_minutes = 0.0
        total_score = 0.0
        score_count = 0
        session_list = []

        for sess in sessions:
            dur = sess.duration_seconds() or 0.0
            total_minutes += dur / 60.0
            records = self.db.get_focus_records(sess.session_id)
            if records:
                valid = [r.focus_score for r in records if r.focus_score is not None]
                avg = sum(valid) / max(1, len(valid)) if valid else 0.0
                total_score += avg
                score_count += 1
                session_list.append({"date": sess.start_time.strftime("%m-%d"),
                                     "duration": dur / 60.0, "score": avg})
            else:
                session_list.append({"date": sess.start_time.strftime("%m-%d"),
                                     "duration": dur / 60.0, "score": 0})

        avg_score = total_score / max(1, score_count) if score_count > 0 else 0
        days_active = len(set(s.start_time.strftime("%Y-%m-%d") for s in sessions))

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
            f'<td>{s["score"]:.0f}分</td></tr>'
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
        <div class="hero-item"><div class="num">{len(sessions)}</div><div class="lbl">会话数</div></div>
        <div class="hero-item"><div class="num">{days_active}</div><div class="lbl">活跃天数</div></div>
    </div>

    <h2 style="font-size:16px;font-weight:400;border-bottom:1px solid var(--line);padding-bottom:8px;">📅 专注日历</h2>
    <div style="margin:12px 0;">{cal_html}</div>

    <h2 style="font-size:16px;font-weight:400;border-bottom:1px solid var(--line);padding-bottom:8px;">📋 会话明细</h2>
    <table><tr><th>日期</th><th>时长</th><th>平均专注度</th></tr>{rows}</table>

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

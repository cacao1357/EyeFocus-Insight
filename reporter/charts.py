"""
reporter/charts.py — Plotly 交互式图表 (v4.16)

v4.16: 从 matplotlib PNG 切换到 Plotly 交互式图表。
  - 鼠标悬停显示数据标签
  - 图例自动避让，不再重叠
  - 响应式宽度，统一 Quiet Focus 色板
"""
import logging
from typing import List, Optional, Tuple

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from storage.models import FocusRecord, FatigueRecord, FatigueLevel, BlinkRecord, FrameRecord

logger = logging.getLogger("eyefocus.reporter")

# ── Quiet Focus 色板 ──
C_SAGE  = "#5A8A6D"
C_IRIS  = "#5B4A8C"
C_AMBER = "#C9843A"
C_ROSE  = "#B55C5C"
C_INK   = "#23201E"
C_QUIET = "#8B8680"
C_LINE  = "#E6E2DC"
C_BG    = "#FEFDFB"

# Plotly 布局模板
_LAYOUT_BASE = dict(
    paper_bgcolor=C_BG,
    plot_bgcolor=C_BG,
    font=dict(family="Microsoft YaHei, SimHei, sans-serif", size=11, color=C_INK),
    margin=dict(l=40, r=20, t=30, b=40),
    hovermode="x unified",
    hoverlabel=dict(bgcolor="white", font_size=12, font_family="Microsoft YaHei, SimHei, sans-serif"),
    legend=dict(
        orientation="h", yanchor="top", y=1.12, xanchor="right", x=1,
        font=dict(size=10, color=C_QUIET), bgcolor="rgba(0,0,0,0)",
    ),
    xaxis=dict(
        showgrid=False, zeroline=False,
        tickfont=dict(size=10, color=C_QUIET),
        linecolor=C_LINE,
    ),
    yaxis=dict(
        showgrid=False, zeroline=False,
        tickfont=dict(size=10, color=C_QUIET),
        linecolor=C_LINE,
    ),
)

# 颜色映射
def _level_color(score):
    if score >= 70: return C_SAGE
    if score >= 40: return C_AMBER
    return C_ROSE


class ChartGenerator:
    """v4.16: Plotly 交互式图表生成器"""

    def __init__(self, figsize=(6, 2.8), dpi=120):
        self.figsize = figsize
        self.dpi = dpi

    def _to_html(self, fig, height=300) -> str:
        """将 Plotly figure 转为 HTML div 字符串"""
        fig.update_layout(height=height)
        return fig.to_html(full_html=False, include_plotlyjs=False,
                           config=dict(displayModeBar=False, responsive=True))

    def _time_labels(self, records):
        if not records:
            return []
        def _ts(r):
            v = getattr(r, 'window_start', None)
            return v if (v is not None and v != 0.0) else getattr(r, 'timestamp', 0.0)
        t0 = min(_ts(r) for r in records)
        return [f"{int((_ts(r)-t0)//60)}:{int((_ts(r)-t0)%60):02d}" for r in records]

    # ════════════════════════════════════════════
    # 1. 专注度趋势
    # ════════════════════════════════════════════
    def generate_focus_trend_chart(self, focus_records, title="专注度趋势"):
        if not focus_records:
            return self._empty_html("无数据")

        labels = self._time_labels(focus_records)
        scores = [r.focus_score for r in focus_records]
        colors = [_level_color(s) for s in scores]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=labels, y=scores, mode='lines',
            line=dict(width=2.5, color=C_IRIS),
            name='专注度',
            hovertemplate='%{y:.0f} 分<br>%{x}<extra></extra>',
        ))
        # 逐段着色标记点
        for i, (s, c) in enumerate(zip(scores, colors)):
            fig.add_trace(go.Scatter(
                x=[labels[i]], y=[s], mode='markers',
                marker=dict(size=6, color=c),
                showlegend=False,
                hoverinfo='skip',
            ))

        # 良好参考线
        fig.add_hline(y=70, line_dash="dash", line_color=C_LINE, line_width=1,
                      annotation_text="良好线 70", annotation_position="left",
                      annotation_font_size=10, annotation_font_color=C_SAGE)

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            yaxis=dict(**_LAYOUT_BASE["yaxis"], range=[0, 105], title="专注度"),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间"),
            showlegend=False,
        )
        return self._to_html(fig, height=240)

    # ════════════════════════════════════════════
    # 2. 眨眼频率
    # ════════════════════════════════════════════
    def generate_blink_rate_chart(self, focus_records, title="眨眼频率趋势"):
        if not focus_records:
            return self._empty_html("无数据")

        labels = self._time_labels(focus_records)
        rates = [r.blink_rate for r in focus_records]

        bc = max(5, len(rates) // 5)
        bs = [b for b in rates[:bc] if b > 0]
        bl = float(np.median(bs)) if bs else 15.0

        colors = [C_ROSE if r > bl*1.5 else C_AMBER if r > bl*1.2 else C_SAGE for r in rates]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=labels, y=rates,
            marker_color=colors,
            name='眨眼频率',
            hovertemplate='%{y:.1f} 次/分<br>%{x}<extra></extra>',
        ))
        fig.add_hline(y=bl, line_dash="dash", line_color=C_SAGE, line_width=1.5,
                      annotation_text=f"基线 {bl:.0f}", annotation_position="left",
                      annotation_font_size=10, annotation_font_color=C_SAGE)

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            yaxis=dict(**_LAYOUT_BASE["yaxis"], title="次/分"),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间"),
            showlegend=False,
        )
        return self._to_html(fig, height=200)

    # ════════════════════════════════════════════
    # 3. 疲劳趋势
    # ════════════════════════════════════════════
    def generate_fatigue_timeline(self, fatigue_records, title="疲劳趋势分析"):
        if not fatigue_records:
            return self._empty_html("无数据")

        labels = self._time_labels(fatigue_records)
        scores = [r.cumulative_fatigue_score for r in fatigue_records]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=labels, y=scores, mode='lines',
            line=dict(width=2, color=C_ROSE),
            fill='tozeroy', fillcolor=f'rgba(181,92,92,0.1)',
            name='疲劳分',
            hovertemplate='%{y:.0f} 分<br>%{x}<extra></extra>',
        ))
        fig.add_hline(y=60, line_dash="dash", line_color=C_LINE, line_width=1,
                      annotation_text="严重疲劳 60", annotation_position="left",
                      annotation_font_size=10, annotation_font_color=C_ROSE)

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            yaxis=dict(**_LAYOUT_BASE["yaxis"], title="疲劳分"),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间"),
            showlegend=False,
        )
        return self._to_html(fig, height=220)

    # ════════════════════════════════════════════
    # 4. 会话时间色条 — 纯 HTML/CSS (不需要 Plotly)
    # ════════════════════════════════════════════
    def generate_session_colorbar(self, focus_records, title="会话专注分布"):
        if not focus_records:
            return self._empty_html("无数据")

        n = len(focus_records)
        if n == 0:
            return self._empty_html("无数据")

        # 生成色条 HTML
        total = max(1, n)
        blocks = []
        for r in focus_records:
            s = r.focus_score
            c = C_SAGE if s >= 70 else C_AMBER if s >= 40 else C_ROSE
            blocks.append(f'<span style="background:{c};flex:1;height:100%;min-width:2px"></span>')

        # 图例
        legend = (
            f'<span style="display:flex;gap:12px;font-size:11px;color:{C_QUIET};margin-top:4px">'
            f'<span>■ <span style="color:{C_SAGE}">专注</span></span>'
            f'<span>■ <span style="color:{C_AMBER}">一般</span></span>'
            f'<span>■ <span style="color:{C_ROSE}">分心</span></span>'
            f'</span>'
        )
        bar = f'<div style="display:flex;height:12px;border-radius:2px;overflow:hidden;background:{C_BG};border:1px solid {C_LINE}">{"".join(blocks)}</div>'

        # 时间标签（开始/结束）
        labels = self._time_labels(focus_records)
        time_range = f'<div style="display:flex;justify-content:space-between;font-size:10px;color:{C_QUIET};margin-top:2px"><span>{labels[0] if labels else "0:00"}</span><span>{labels[-1] if labels else "--"}</span></div>'

        return f'<div style="padding:4px 0">{bar}{time_range}{legend}</div>'

    # ════════════════════════════════════════════
    # 5. 头部姿态
    # ════════════════════════════════════════════
    def generate_head_pose_scatter(self, frame_records, title="头部姿态变化"):
        if not frame_records:
            return self._empty_html("无头部姿态数据")

        times, devs = [], []
        t0 = None
        for r in frame_records:
            if abs(r.yaw) < 90 and abs(r.pitch) < 90:
                if t0 is None:
                    t0 = r.timestamp
                devs.append(np.sqrt(r.yaw**2 + r.pitch**2))
                times.append(max(0, r.timestamp - t0))
        if len(devs) < 3:
            return self._empty_html("头部姿态数据不足")

        step = max(1, len(times) // 200)
        times, devs = times[::step], devs[::step]
        time_labels = [f"{int(t//60)}:{int(t%60):02d}" for t in times]

        in_zone = sum(1 for d in devs if d <= 20)
        pct = in_zone / len(devs) * 100

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=time_labels, y=devs, mode='lines',
            line=dict(width=1.5, color=C_IRIS),
            name='偏移角',
            hovertemplate='%{y:.1f}°<br>%{x}<extra></extra>',
        ))
        fig.add_hline(y=20, line_dash="dash", line_color=C_SAGE, line_width=1,
                      annotation_text=f"舒适上限 20°", annotation_position="left",
                      annotation_font_size=10, annotation_font_color=C_SAGE)

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            yaxis=dict(**_LAYOUT_BASE["yaxis"], title="偏移°"),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间"),
            showlegend=False,
            annotations=(
                _LAYOUT_BASE.get("annotations", []) + [
                    dict(x=1, y=1, xref="paper", yref="paper", xanchor="right", yanchor="top",
                         text=f"舒适区占比 {pct:.0f}%", showarrow=False,
                         font=dict(size=11, color=C_SAGE), bgcolor="rgba(254,253,251,0.85)")
                ]
            ),
        )
        return self._to_html(fig, height=220)

    # ════════════════════════════════════════════
    # 6. Insights 图表
    # ════════════════════════════════════════════
    def generate_pattern_pie_chart(self, pattern_labels, cluster_sizes, title="工作模式分布"):
        return self._empty_html("请使用离线分析引擎查看")

    def generate_anomaly_bar_chart(self, top_factors, title="异常主要特征"):
        return self._empty_html("请使用离线分析引擎查看")

    def generate_temporal_line_chart(self, hourly_pattern, peak_hours, low_hours,
                                      title="日内专注度模式"):
        if not hourly_pattern or len(hourly_pattern) < 6:
            return self._empty_html("数据不足")
        vals = hourly_pattern[:24]
        while len(vals) < 24:
            vals.append(0.0)
        hours = [f"{h:02d}:00" for h in range(24)]
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=hours, y=vals, mode='lines',
            line=dict(width=2, color=C_IRIS),
            fill='tozeroy', fillcolor=f'rgba(91,74,140,0.08)',
            name='专注度',
            hovertemplate='%{y:.0f} 分<br>%{x}<extra></extra>',
        ))
        if peak_hours:
            for ph in peak_hours:
                parts = ph.split("-")
                if len(parts) == 2:
                    try:
                        sh, eh = int(parts[0]), int(parts[1])
                        fig.add_vrect(x0=f"{sh:02d}:00", x1=f"{eh:02d}:00",
                                      fillcolor=C_SAGE, opacity=0.08, line_width=0)
                    except ValueError:
                        pass
        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            yaxis=dict(**_LAYOUT_BASE["yaxis"], range=[0, 100], title="专注度"),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="小时"),
            showlegend=False,
        )
        return self._to_html(fig, height=220)

    def generate_attribution_bar_chart(self, findings, title="关联分析结果"):
        if not findings:
            return self._empty_html("无显著发现")
        factors = [f["factor"] for f in findings]
        effects = [abs(f["effect_size"]) for f in findings]
        colors = [C_SAGE if f["p_value"] < 0.01 else C_AMBER for f in findings]
        p_vals = [f"p={f['p_value']:.3f}" for f in findings]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=factors, x=effects, orientation='h',
            marker_color=colors,
            text=p_vals, textposition='outside', textfont=dict(size=10, color=C_QUIET),
            hovertemplate='效果量: %{x:.3f}<br>%{text}<extra></extra>',
        ))
        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="效果量"),
            showlegend=False,
            height=max(150, len(factors) * 30 + 80),
        )
        return self._to_html(fig, height=max(150, len(factors) * 30 + 80))

    def generate_distraction_heatmap(self, heatmap, labels, pattern_type="",
                                      title="分心时间轴"):
        if not heatmap:
            return self._empty_html("无分心数据")
        n = len(heatmap)
        colors = [C_SAGE if v < 0.2 else C_AMBER if v < 0.5 else C_ROSE for v in heatmap]

        fig = go.Figure()
        fig.add_trace(go.Heatmap(
            z=[heatmap], x=labels, y=[""],
            colorscale=[[0, C_SAGE], [0.25, C_SAGE], [0.25, C_AMBER], [0.6, C_AMBER], [0.6, C_ROSE], [1, C_ROSE]],
            showscale=False,
            hovertemplate='分心度: %{z:.2f}<br>%{x}<extra></extra>',
        ))
        title_text = f"{title} · {pattern_type}" if pattern_type else title
        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            title=dict(text=title_text, font_size=11, x=0),
            height=120, margin=dict(l=10, r=10, t=30, b=40),
            xaxis=dict(showgrid=False, tickfont_size=9, nticks=10),
            yaxis=dict(showgrid=False, showticklabels=False),
            showlegend=False,
        )
        return self._to_html(fig, height=100)

    def _empty_html(self, message):
        return f'<div style="text-align:center;color:#ccc;padding:32px;font-size:13px">{message}</div>'


def create_chart_generator(figsize=(6, 2.8), dpi=120):
    return ChartGenerator(figsize=figsize, dpi=dpi)

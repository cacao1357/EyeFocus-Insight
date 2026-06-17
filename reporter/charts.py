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
# v4.26 修复: x 轴 tickangle=0 + nticks=6，强制水平显示时间标签
# (Plotly 默认 -45° 自动旋转以防重叠，但 "侧倒" 不符合腕表仪表美学)
_LAYOUT_BASE = dict(
    paper_bgcolor=C_BG,
    plot_bgcolor=C_BG,
    font=dict(family="Microsoft YaHei, SimHei, sans-serif", size=11, color=C_INK),
    margin=dict(l=64, r=20, t=30, b=48),  # l=64 给 y 轴水平标题 annotation 留位
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
        tickangle=0,        # v4.26: 强制水平，不旋转
        nticks=6,           # v4.26: 限制 x 轴标签最多 6 个，避免拥挤
        automargin=True,    # v4.26: Plotly 自动调整 margin 防裁切
        title_standoff=12,  # v4.26: 标题与轴距离，避免压字
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


# v4.26: 水平 y 轴标题（修复"侧倒"）
# Plotly 6.x 不支持 yaxis.title.textangle（"Bad property path"），
# 用 annotation 模拟水平标题 —— paper 坐标系，x 轴外侧居中。
def _y_title_axis() -> dict:
    """yaxis 配置：关闭原生 title，释放空间给 annotation"""
    return dict(title=None, title_standoff=0)

def _y_title_annotation(text: str) -> dict:
    """y 轴水平标题 annotation（paper 坐标）"""
    return dict(
        xref="paper", yref="paper",
        x=-0.04, y=0.5, xanchor="right", yanchor="middle",
        text=text, showarrow=False, textangle=0,
        font=dict(size=10, color=C_QUIET),
    )


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

    # ── v4.25: 统一排序工具，确保 x 轴从左到右为时间正序 ──
    @staticmethod
    def _sorted_records(records):
        """按时间戳升序排列记录，确保图表不出现"时间倒流" """
        if not records:
            return records
        def _ts(r):
            return getattr(r, 'window_start', None) or getattr(r, 'timestamp', 0.0) or 0.0
        return sorted(records, key=_ts)

    def _time_labels(self, records):
        if not records:
            return []
        # v4.25: 先排序，确保时间从左到右递增
        sorted_r = self._sorted_records(records)
        def _ts(r):
            v = getattr(r, 'window_start', None)
            return v if (v is not None and v != 0.0) else getattr(r, 'timestamp', 0.0)
        t0 = min(_ts(r) for r in sorted_r)
        return [f"{int((_ts(r)-t0)//60)}:{int((_ts(r)-t0)%60):02d}" for r in sorted_r]

    # ════════════════════════════════════════════
    # 1. 专注度趋势
    # ════════════════════════════════════════════
    def generate_focus_trend_chart(self, focus_records, title="专注度趋势"):
        if not focus_records:
            return self._empty_html("无数据")

        # v4.25: 排序保时序
        fr = self._sorted_records(focus_records)
        labels = self._time_labels(focus_records)  # _time_labels 内部已排序
        scores = [r.focus_score for r in fr]
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
            yaxis=dict(**_LAYOUT_BASE["yaxis"], range=[0, 105], **_y_title_axis()),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间"),
            annotations=[_y_title_annotation("专注度")],
            showlegend=False,
        )
        return self._to_html(fig, height=240)

    # ════════════════════════════════════════════
    # 2. 眨眼频率
    # ════════════════════════════════════════════
    def generate_blink_rate_chart(self, focus_records, title="眨眼频率趋势"):
        if not focus_records:
            return self._empty_html("无数据")

        fr = self._sorted_records(focus_records)
        labels = self._time_labels(focus_records)  # 内部已排序
        rates = [r.blink_rate for r in fr]

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
            yaxis=dict(**_LAYOUT_BASE["yaxis"], **_y_title_axis()),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间"),
            annotations=[_y_title_annotation("次/分")],
            showlegend=False,
        )
        return self._to_html(fig, height=200)

    # ════════════════════════════════════════════
    # 3. 疲劳趋势
    # ════════════════════════════════════════════
    def generate_fatigue_timeline(self, fatigue_records, title="疲劳趋势分析"):
        if not fatigue_records:
            return self._empty_html("无数据")

        fr = self._sorted_records(fatigue_records)
        labels = self._time_labels(fatigue_records)  # 内部已排序
        scores = [r.cumulative_fatigue_score for r in fr]

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
            yaxis=dict(**_LAYOUT_BASE["yaxis"], **_y_title_axis()),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间"),
            annotations=[_y_title_annotation("疲劳分")],
            showlegend=False,
        )
        return self._to_html(fig, height=220)

    # ════════════════════════════════════════════
    # 4. 会话时间色条 — 纯 HTML/CSS (不需要 Plotly)
    # ════════════════════════════════════════════
    def generate_session_colorbar(self, focus_records, title="会话专注分布"):
        if not focus_records:
            return self._empty_html("无数据")

        fr = self._sorted_records(focus_records)
        n = len(fr)
        if n == 0:
            return self._empty_html("无数据")

        # 生成色条 HTML
        blocks = []
        for r in fr:
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

        # v4.25: 先排序
        sorted_frames = sorted(
            [r for r in frame_records if abs(getattr(r, 'yaw', 0)) < 90 and abs(getattr(r, 'pitch', 0)) < 90],
            key=lambda r: getattr(r, 'timestamp', 0.0) or 0.0,
        )
        if len(sorted_frames) < 3:
            return self._empty_html("头部姿态数据不足")

        times, devs = [], []
        t0 = sorted_frames[0].timestamp
        for r in sorted_frames:
            devs.append(np.sqrt(r.yaw**2 + r.pitch**2))
            times.append(max(0, r.timestamp - t0))

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
        # v4.25: annotation_position="right" 避免与数据点重叠
        fig.add_hline(y=20, line_dash="dash", line_color=C_SAGE, line_width=1,
                      annotation_text="舒适上限 20°", annotation_position="right",
                      annotation_font_size=10, annotation_font_color=C_SAGE)

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            yaxis=dict(**_LAYOUT_BASE["yaxis"], **_y_title_axis(),
                       range=[0, max(devs)*1.15]),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间"),
            showlegend=False,
            annotations=(
                _LAYOUT_BASE.get("annotations", []) + [
                    dict(x=1, y=0.98, xref="paper", yref="paper", xanchor="right", yanchor="top",
                         text=f"≤20° 舒适区占 {pct:.0f}%", showarrow=False,
                         font=dict(size=11, color=C_SAGE), bgcolor="rgba(254,253,251,0.85)"),
                    _y_title_annotation("偏移度 (°)"),
                ]
            ),
        )
        return self._to_html(fig, height=220)

    # ════════════════════════════════════════════
    # 6. Insights 图表 (v4.17: 修复空壳)
    # ════════════════════════════════════════════
    def generate_pattern_pie_chart(self, pattern_labels, cluster_sizes, title="工作模式分布"):
        """工作模式聚类饼图（Plotly 实现）"""
        if not cluster_sizes or not pattern_labels:
            return self._empty_html("无聚类数据")

        # 从 labels 提取显示名称（格式如 "高效专注(5次)"）
        labels = list(pattern_labels.values())
        values = list(cluster_sizes)

        if not labels or not values:
            return self._empty_html("无聚类数据")

        # 颜色映射
        colors = [C_IRIS, C_SAGE, C_AMBER, C_ROSE, C_QUIET][:len(labels)]

        fig = go.Figure()
        fig.add_trace(go.Pie(
            labels=labels,
            values=values,
            marker=dict(colors=colors),
            textinfo="label+percent",
            textposition="outside",
            textfont=dict(size=10, color=C_INK),
            hovertemplate="%{label}<br>%{value} 次会话 (%{percent})<extra></extra>",
            showlegend=False,
            hole=0.35,
        ))

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            title=dict(text=title, font_size=12, x=0),
            height=280,
            margin=dict(l=10, r=10, t=30, b=10),
        )
        return self._to_html(fig, height=280)

    def generate_anomaly_bar_chart(self, top_factors, title="异常主要特征"):
        """异常因子水平条形图（Plotly 实现）"""
        if not top_factors:
            return self._empty_html("无异常特征")

        # 水平柱状图：每个因子占一列，效果量递减
        n = len(top_factors)
        # 模拟效果量（从高到低），因为没有原始分数
        effects = [1.0 - i * 0.2 for i in range(n)]
        colors = [C_ROSE, C_AMBER, C_SAGE][:n]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=effects[::-1],
            y=top_factors[::-1],
            orientation='h',
            marker_color=colors[::-1],
            text=[f"{e*100:.0f}%" for e in effects[::-1]],
            textposition="outside",
            textfont=dict(size=10, color=C_QUIET),
            hovertemplate="%{y}<extra></extra>",
            showlegend=False,
        ))

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            title=dict(text=title, font_size=12, x=0),
            height=max(120, len(top_factors) * 35 + 40),
            margin=dict(l=10, r=40, t=30, b=10),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], showticklabels=False, range=[0, 1.3]),
            yaxis=dict(**_LAYOUT_BASE["yaxis"], title=None),
        )
        return self._to_html(fig, height=max(120, len(top_factors) * 35 + 40))

    def generate_temporal_line_chart(self, hourly_pattern, peak_hours, low_hours,
                                      title="日内专注度模式"):
        if not hourly_pattern or len(hourly_pattern) < 6:
            return self._empty_html("数据不足")
        vals = hourly_pattern[:24]
        while len(vals) < 24:
            vals.append(0.0)
        # v4.25: 每 4 小时一个刻度标签，避免拥挤
        tick_vals = [f"{h:02d}:00" for h in range(0, 24, 4)]
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
        if low_hours:
            for lh in low_hours:
                parts = lh.split("-")
                if len(parts) == 2:
                    try:
                        sh, eh = int(parts[0]), int(parts[1])
                        fig.add_vrect(x0=f"{sh:02d}:00", x1=f"{eh:02d}:00",
                                      fillcolor=C_ROSE, opacity=0.06, line_width=0)
                    except ValueError:
                        pass
        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            yaxis=dict(**_LAYOUT_BASE["yaxis"], range=[0, 100], **_y_title_axis()),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时段",
                       tickvals=tick_vals, ticktext=[f"{h:02d}:00" for h in range(0, 24, 4)]),
            annotations=[_y_title_annotation("平均专注度")],
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
            xaxis=dict(showgrid=False, tickfont_size=9, nticks=10, tickangle=0),
            yaxis=dict(showgrid=False, showticklabels=False),
            showlegend=False,
        )
        return self._to_html(fig, height=100)

    # ════════════════════════════════════════════════
    # 7. 日历热力图 (v4.17 GitHub 贡献图风格)
    # ════════════════════════════════════════════════
    def generate_calendar_heatmap(self, daily_stats: list, title="专注日历"):
        """GitHub 贡献图风格日历热力图

        Args:
            daily_stats: [{date: "2026-06-16", minutes: 45.0}, ...]

        Returns:
            HTML div string
        """
        if not daily_stats:
            return self._empty_html("无历史数据")

        # 构建日期→分钟映射
        dm = {s["date"]: s["minutes"] for s in daily_stats}
        dates = sorted(dm.keys())
        if not dates:
            return self._empty_html("无历史数据")

        from datetime import datetime, timedelta

        def _parse(d):
            return datetime.strptime(d, "%Y-%m-%d")

        first = _parse(dates[0])
        last = _parse(dates[-1])

        # 找到 first 所在周的周一
        start = first - timedelta(days=first.weekday())
        # 找到 last 所在周的周日
        end = last + timedelta(days=(6 - last.weekday()))

        total_days = (end - start).days + 1
        n_weeks = (total_days + 6) // 7

        # 行：周一→周日 (0-6)
        weekdays_cn = ["一", "二", "三", "四", "五", "六", "日"]

        # 构建 z 矩阵 [7 行 x n_weeks 列]
        z = [[0.0] * n_weeks for _ in range(7)]
        hover_texts = [[""] * n_weeks for _ in range(7)]
        date_labels = [""] * n_weeks
        tick_vals = []

        current = start
        last_month = -1
        for col in range(n_weeks):
            for row in range(7):
                if current > end:
                    break
                ds = current.strftime("%Y-%m-%d")
                minutes = dm.get(ds, 0.0)
                z[row][col] = minutes
                if minutes > 0:
                    hover_texts[row][col] = f"{ds}<br>{minutes:.0f} 分钟"
                else:
                    hover_texts[row][col] = ds
                if row == 0:  # 每周一标注月份
                    m = current.month
                    if m != last_month:
                        date_labels[col] = f"{current.year}-{m:02d}" if last_month == -1 else f"{m}月"
                        tick_vals.append(col)
                        last_month = m
                current += timedelta(days=1)

        # 颜色 scale：白→浅绿→深绿
        colorscale = [
            [0, "#F5F5F5"],
            [0.01, "#E8F5E9"],
            [0.25, "#A5D6A7"],
            [0.5, "#66BB6A"],
            [0.75, "#388E3C"],
            [1, "#1B5E20"],
        ]

        max_min = max(max(row) for row in z) if any(any(r) for r in z) else 1

        fig = go.Figure()
        fig.add_trace(go.Heatmap(
            z=z,
            x=list(range(n_weeks)),
            y=weekdays_cn,
            text=hover_texts,
            hovertemplate="%{text}<extra></extra>",
            colorscale=colorscale,
            zmin=0,
            zmax=max(1, max_min),
            showscale=True,
            colorbar=dict(
                title=dict(text="分钟/天", side="top"),  # 水平放顶部，不侧倒
                thickness=12,
                len=0.65,
                tickfont=dict(size=9, color=C_QUIET),
            ),
            xgap=3,
            ygap=3,
        ))

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            title=dict(text=title, font_size=12, x=0),
            height=160,
            margin=dict(l=10, r=40, t=28, b=10),
            xaxis=dict(
                showgrid=False, zeroline=False,
                tickvals=tick_vals if tick_vals else list(range(0, n_weeks, max(1, n_weeks//6))),
                ticktext=date_labels,
                tickfont=dict(size=9, color=C_QUIET),
                side="top",
                tickangle=0,  # v4.26: 月份标签水平显示，不旋转
            ),
            yaxis=dict(
                showgrid=False, zeroline=False,
                tickfont=dict(size=9, color=C_QUIET),
                autorange="reversed",
            ),
            showlegend=False,
        )
        return self._to_html(fig, height=180)

    def _empty_html(self, message):
        return f'<div style="text-align:center;color:#ccc;padding:32px;font-size:13px">{message}</div>'


def create_chart_generator(figsize=(6, 2.8), dpi=120):
    return ChartGenerator(figsize=figsize, dpi=dpi)

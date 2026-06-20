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
    dragmode=False,  # v4.41: 禁用拖动平移，保留滚轮缩放+悬停
    hovermode="x unified",
    hoverlabel=dict(bgcolor="white", font_size=12, font_family="Microsoft YaHei, SimHei, sans-serif"),
    legend=dict(
        orientation="h", yanchor="top", y=1.12, xanchor="right", x=1,
        font=dict(size=10, color=C_QUIET), bgcolor="rgba(0,0,0,0)",
    ),
    xaxis=dict(
        showgrid=False, zeroline=False,
        tickfont=dict(size=10, color=C_QUIET),
        linecolor=C_LINE, nticks=15, automargin=True,
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
        return [self._fmt_offset(_ts(r) - t0) for r in sorted_r]

    @staticmethod
    def _ts(r):
        """提取记录的时间戳（秒）"""
        v = getattr(r, 'window_start', None)
        return v if (v is not None and v != 0.0) else getattr(r, 'timestamp', 0.0)

    @staticmethod
    def _numeric_offsets(records):
        """返回从首条记录开始的秒偏移列表"""
        if not records:
            return []
        sorted_r = ChartGenerator._sorted_records(records)
        t0 = min(ChartGenerator._ts(r) for r in sorted_r)
        return [ChartGenerator._ts(r) - t0 for r in sorted_r]

    GAP_THRESHOLD = 300   # v4.34: 5 分钟 — 采集中断 >5min 视为间隙，填充零值

    @staticmethod
    def _dynamic_params(duration_seconds: float):
        """v4.41: 根据会话时长动态决定刻度数和采样点数。

        Returns (n_ticks, n_markers)
        """
        minutes = duration_seconds / 60.0
        if minutes < 10:
            return (5, 10)
        elif minutes < 30:
            return (12, 20)
        elif minutes <= 120:
            return (24, 30)
        else:
            return (24, 40)

    @classmethod
    def _effective_gap(cls, duration_seconds: float) -> float:
        """v4.41: 动态间隙阈值 — 最多 300s，但不超过时长的 1/4"""
        return min(cls.GAP_THRESHOLD, max(30.0, duration_seconds / 4.0))

    @classmethod
    def _insert_gap_breaks(cls, records, offsets, values, gap_threshold=None):
        """间隙处插入零值对，线条下降→贴零轴→恢复。

        v4.34: 用 (gap_start, 0) + (gap_end, 0) 替代 (None, None)。
        与 connectgaps=True 配合，线条在采集中断期间沿 y=0 走直线。
        v4.41: gap_threshold=None 时自动计算动态阈值。

        Returns (offsets_with_zeros, values_with_zeros)
        """
        if gap_threshold is None:
            n = len(records)
            if n >= 2:
                dur = cls._ts(records[-1]) - cls._ts(records[0])
                gap_threshold = cls._effective_gap(dur)
            else:
                gap_threshold = cls.GAP_THRESHOLD

        if len(records) < 2:
            return list(offsets), list(values)

        new_offsets, new_vals = [], []
        for i in range(len(records)):
            if i > 0:
                dt = cls._ts(records[i]) - cls._ts(records[i - 1])
                if dt > gap_threshold:
                    new_offsets.append(offsets[i - 1])
                    new_vals.append(0)
                    new_offsets.append(offsets[i])
                    new_vals.append(0)
            new_offsets.append(offsets[i])
            new_vals.append(values[i])
        return new_offsets, new_vals

    @staticmethod
    def _downsample_focus(focus_records, target=None):
        """间隙感知降采样 — 仅在有数据的时段内均匀分布标记点。

        v4.33:
        - 目标 30 个标记点（用户明确要求）
        - 扫描相邻记录间隔 > GAP_THRESHOLD → 标记为间隙，不在间隙内分桶
        - 有效时长 = 总时长 - 间隙时长。bucket_dt = 有效时长 / target
        - 每桶 1 个代表点（等级跨越优先，否则中位数）
        - 间隙边界记录始终保留
        v4.41: target=None 时根据时长自动计算；动态间隙阈值。
        """
        n = len(focus_records)
        if n == 0:
            return []

        t0 = ChartGenerator._ts(focus_records[0])
        tN = ChartGenerator._ts(focus_records[-1])
        total_dt = max(1.0, tN - t0)

        if target is None:
            _, target = ChartGenerator._dynamic_params(total_dt)

        effective_gap = ChartGenerator._effective_gap(total_dt)

        if n <= target:
            return list(range(n))

        kept = {0, n - 1}  # 首尾始终保留

        # ── 阶段 1: 检测间隙 ──
        gaps = []  # [(gap_start_idx, gap_end_idx), ...] — 间隙的记录索引
        for i in range(1, n):
            dt = ChartGenerator._ts(focus_records[i]) - ChartGenerator._ts(focus_records[i - 1])
            if dt > effective_gap:
                gaps.append((i - 1, i))
                kept.add(i - 1)  # 间隙前边界
                kept.add(i)      # 间隙后边界

        # ── 阶段 2: 计算有效时长 ──
        gap_dt = 0.0
        for ga, gb in gaps:
            gap_dt += ChartGenerator._ts(focus_records[gb]) - ChartGenerator._ts(focus_records[ga])
        effective_dt = max(1.0, total_dt - gap_dt)
        bucket_dt = effective_dt / target

        # ── 阶段 3: 仅在有效时段内分桶 ──
        def _level(s):
            if s >= 70: return 2
            if s >= 40: return 1
            return 0

        from statistics import median

        # 构建有效段 (start_ts, end_ts) 列表
        segments = []
        seg_start = t0
        for ga, gb in gaps:
            seg_end = ChartGenerator._ts(focus_records[ga])
            if seg_end - seg_start >= bucket_dt * 0.5:  # 段太短跳过
                segments.append((seg_start, seg_end))
            seg_start = ChartGenerator._ts(focus_records[gb])
        if tN - seg_start >= bucket_dt * 0.5:
            segments.append((seg_start, tN))

        # 在每个有效段内分桶
        for seg_start, seg_end in segments:
            bucket_start = seg_start
            bucket_items = []
            last_level = None

            for i, r in enumerate(focus_records):
                t = ChartGenerator._ts(r)
                if t < seg_start:
                    continue
                if t > seg_end:
                    break

                while t >= bucket_start + bucket_dt:
                    if bucket_items:
                        best = ChartGenerator._pick_bucket_rep(bucket_items, last_level)
                        kept.add(best[0])
                        last_level = None
                    bucket_items = []
                    bucket_start += bucket_dt

                bucket_items.append((i, r.focus_score))
                if last_level is None:
                    last_level = _level(r.focus_score)

            # 结算段内最后一个桶
            if bucket_items:
                best = ChartGenerator._pick_bucket_rep(bucket_items, last_level)
                kept.add(best[0])

        return sorted(kept)

    @staticmethod
    def _pick_bucket_rep(bucket_items, first_level):
        """从桶内选 1 个代表点: 有等级跨越则选跨越点，否则选中位数点"""
        from statistics import median

        def _level(s):
            if s >= 70: return 2
            if s >= 40: return 1
            return 0

        if first_level is not None:
            for idx, score in bucket_items:
                if _level(score) != first_level:
                    return (idx, score)

        scores = [x[1] for x in bucket_items]
        med = median(scores)
        return min(bucket_items, key=lambda x: abs(x[1] - med))

    def _regular_ticks(self, t_max_seconds: float, n_ticks: int = None):
        """生成 N 段均匀时间刻度

        v4.31: 固定段数（默认 24 段），确保横坐标简洁、间隔均匀。
        未采集到的时段在图表上自然留空（线条中断）。
        v4.41: n_ticks=None 时根据时长自动计算。
        """
        t = max(1, int(t_max_seconds))
        if n_ticks is None:
            n_ticks, _ = self._dynamic_params(t_max_seconds)
        step = max(1, t // n_ticks)
        tick_vals = list(range(0, t + step, step))
        if len(tick_vals) > n_ticks + 1:
            tick_vals = tick_vals[:n_ticks + 1]
        tick_texts = [self._fmt_offset(v) for v in tick_vals]
        return tick_vals, tick_texts

    @staticmethod
    def _fmt_offset(seconds: float) -> str:
        """将秒偏移格式化为 H:MM:SS（或 M:SS）"""
        s = int(seconds)
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    # ════════════════════════════════════════════
    # 1. 专注度趋势
    # ════════════════════════════════════════════
    def generate_focus_trend_chart(self, focus_records, title="专注度趋势"):
        if not focus_records:
            return self._empty_html("无数据")

        fr = self._sorted_records(focus_records)
        offsets = self._numeric_offsets(focus_records)
        scores = [r.focus_score for r in fr]
        colors = [_level_color(s) for s in scores]
        hover_labels = [self._fmt_offset(o) for o in offsets]

        fig = go.Figure()

        # 线条 — v4.33: 间隔处插入 NaN 断开
        line_x, line_y = self._insert_gap_breaks(fr, offsets, scores)
        line_text = [self._fmt_offset(x) if x is not None else "" for x in line_x]
        fig.add_trace(go.Scatter(
            x=line_x, y=line_y, mode='lines',
            line=dict(width=2.5, color=C_IRIS),
            text=line_text,
            name='专注度',
            hovertemplate='%{y:.0f} 分<br>%{text}<extra></extra>',
            connectgaps=True,   # v4.34: 零值填充替代断线
        ))

        # 标记点 — 单 trace + 间隙感知降采样 (v4.41: 动态target)
        sampled_idx = self._downsample_focus(fr)
        s_offsets = [offsets[i] for i in sampled_idx]
        s_scores = [scores[i] for i in sampled_idx]
        s_colors = [colors[i] for i in sampled_idx]
        fig.add_trace(go.Scatter(
            x=s_offsets, y=s_scores, mode='markers',
            marker=dict(size=6, color=s_colors),
            showlegend=False,
            hoverinfo='skip',
        ))

        # 良好参考线
        fig.add_hline(y=70, line_dash="dash", line_color=C_LINE, line_width=1,
                      annotation_text="良好线 70", annotation_position="left",
                      annotation_font_size=10, annotation_font_color=C_SAGE)

        # 规整时间刻度
        t_max = offsets[-1] if offsets else 0
        tick_vals, tick_texts = self._regular_ticks(t_max)

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            yaxis=dict(**_LAYOUT_BASE["yaxis"], range=[0, 105], title="专注度"),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间",
                       tickvals=tick_vals, ticktext=tick_texts),
            showlegend=False,
        )
        return self._to_html(fig, height=240)

    # ════════════════════════════════════════════
    # 2. 眨眼频率
    # ════════════════════════════════════════════
    def generate_blink_rate_chart(self, focus_records, title="眨眼频率趋势", baseline_blink_rate=None):
        if not focus_records:
            return self._empty_html("无数据")

        fr = self._sorted_records(focus_records)
        all_offsets = self._numeric_offsets(focus_records)
        rates = [r.blink_rate for r in fr]

        # 优先使用校准基线，否则自适应计算（取前 1/5 非零值中位数）
        if baseline_blink_rate is not None and baseline_blink_rate > 0:
            bl = baseline_blink_rate
        else:
            bc = max(5, len(rates) // 5)
            bs = [b for b in rates[:bc] if b > 0]
            bl = float(np.median(bs)) if bs else 15.0

        # v4.33: 间隙感知降采样 (v4.41: 动态target)
        sampled_idx = self._downsample_focus(fr)
        s_offsets = [all_offsets[i] for i in sampled_idx]
        s_rates = [rates[i] for i in sampled_idx]
        colors = [C_ROSE if r > bl*1.5 else C_AMBER if r > bl*1.2 else C_SAGE for r in s_rates]

        # 计算柱宽（基于有效间隔）
        if len(s_offsets) >= 2:
            bar_w = max((s_offsets[-1] - s_offsets[0]) / len(s_offsets) * 0.8, 10.0)
        else:
            bar_w = 60.0

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=s_offsets, y=s_rates,
            marker_color=colors,
            width=bar_w,
            name='眨眼频率',
            hovertemplate='%{y:.1f} 次/分<extra></extra>',
        ))
        fig.add_hline(y=bl, line_dash="dash", line_color=C_SAGE, line_width=1.5,
                      annotation_text=f"基线 {bl:.0f}", annotation_position="left",
                      annotation_font_size=10, annotation_font_color=C_SAGE)

        # 规整时间刻度
        t_max = all_offsets[-1] if all_offsets else 0
        tick_vals, tick_texts = self._regular_ticks(t_max)

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            yaxis=dict(**_LAYOUT_BASE["yaxis"], title="次/分"),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间",
                       tickvals=tick_vals, ticktext=tick_texts),
            bargap=0.3,
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
        offsets = self._numeric_offsets(fatigue_records)
        scores = [r.cumulative_fatigue_score for r in fr]
        hover_labels = [self._fmt_offset(o) for o in offsets]

        fig = go.Figure()
        # 间隔处插入 NaN 断开
        line_x, line_y = self._insert_gap_breaks(fr, offsets, scores)
        line_text = [self._fmt_offset(x) if x is not None else "" for x in line_x]
        fig.add_trace(go.Scatter(
            x=line_x, y=line_y, mode='lines',
            line=dict(width=2, color=C_ROSE),
            text=line_text,
            name='疲劳分',
            hovertemplate='%{y:.0f} 分<br>%{text}<extra></extra>',
            connectgaps=True,   # v4.34: 零值填充替代断线
        ))
        fig.add_hline(y=60, line_dash="dash", line_color=C_LINE, line_width=1,
                      annotation_text="严重疲劳 60", annotation_position="left",
                      annotation_font_size=10, annotation_font_color=C_ROSE)

        # 规整时间刻度
        t_max = offsets[-1] if offsets else 0
        tick_vals, tick_texts = self._regular_ticks(t_max)

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            yaxis=dict(**_LAYOUT_BASE["yaxis"], title="疲劳分"),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间",
                       tickvals=tick_vals, ticktext=tick_texts),
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

        # v4.43: 按时间比例生成色块 — 数据段着色，间隙段灰色
        first_ts = self._ts(fr[0])
        last_ts = max(self._ts(fr[-1]),
                      getattr(fr[-1], 'window_end', 0) or 0)
        total_span = max(1.0, last_ts - first_ts)

        gap_threshold = self._effective_gap(total_span)

        blocks = []
        for i, r in enumerate(fr):
            t_start = self._ts(r)
            t_end = getattr(r, 'window_end', 0) or t_start
            dur = max(1.0, t_end - t_start)

            # 间隙块（仅当间隙超过阈值）
            if i > 0:
                prev_end = getattr(fr[i - 1], 'window_end', 0) or self._ts(fr[i - 1])
                gap = t_start - prev_end
                if gap > gap_threshold:
                    gap_pct = gap / total_span * 100
                    blocks.append(
                        f'<span style="background:{C_LINE};width:{gap_pct:.2f}%;'
                        f'height:100%;min-width:2px;flex-shrink:0" '
                        f'title="无数据 {gap/60:.0f}分钟"></span>'
                    )

            # 数据块 — v4.43: 白色右边框标记人脸检测时段
            s = r.focus_score if r.focus_score is not None else 0
            c = C_SAGE if s >= 70 else C_AMBER if s >= 40 else C_ROSE
            pct = dur / total_span * 100
            blocks.append(
                f'<span style="background:{c};width:{pct:.2f}%;'
                f'height:100%;min-width:2px;flex-shrink:0;'
                f'border-right:2px solid white" '
                f'title="✓人脸 {s:.0f}分"></span>'
            )

        # 图例 (v4.43: +无数据 +白色边框=人脸)
        legend = (
            f'<span style="display:flex;gap:12px;font-size:11px;color:{C_QUIET};margin-top:4px">'
            f'<span>▐ <span style="color:{C_SAGE}">专注</span></span>'
            f'<span>▐ <span style="color:{C_AMBER}">一般</span></span>'
            f'<span>▐ <span style="color:{C_ROSE}">分心</span></span>'
            f'<span>▐ <span style="color:{C_LINE}">无数据</span></span>'
            f'<span style="font-size:10px">│白边=有人脸</span>'
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

        # v4.34: 间隙零值填充（与专注度/疲劳图表一致）
        line_x, line_y = self._insert_gap_breaks(sorted_frames, times, devs)

        # v4.42: 动态降采样密度（与其他图表一致）
        duration = line_x[-1] if line_x else 0
        _, n_markers = self._dynamic_params(duration)
        step = max(1, len(line_x) // n_markers)
        line_x, line_y = line_x[::step], line_y[::step]
        hover_labels = [self._fmt_offset(t) for t in line_x]

        in_zone = sum(1 for d in line_y if d <= 20 and d > 0)  # 排除零值
        n_real = sum(1 for d in line_y if d > 0)
        pct = in_zone / n_real * 100 if n_real > 0 else 0

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=line_x, y=line_y, mode='lines',
            line=dict(width=1.5, color=C_IRIS),
            text=hover_labels,
            name='偏移角',
            hovertemplate='%{y:.1f}°<br>%{text}<extra></extra>',
            connectgaps=True,   # v4.34: 零值填充替代断线
        ))
        # v4.25: annotation_position="right" 避免与数据点重叠
        fig.add_hline(y=20, line_dash="dash", line_color=C_SAGE, line_width=1,
                      annotation_text="舒适上限 20°", annotation_position="right",
                      annotation_font_size=10, annotation_font_color=C_SAGE)

        # 规整时间刻度
        t_max = line_x[-1] if line_x else 0
        tick_vals, tick_texts = self._regular_ticks(t_max)

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            yaxis=dict(**_LAYOUT_BASE["yaxis"], title="偏移度 (°)", range=[0, max(line_y)*1.15]),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间",
                       tickvals=tick_vals, ticktext=tick_texts),
            showlegend=False,
            annotations=(
                _LAYOUT_BASE.get("annotations", []) + [
                    dict(x=1, y=0.98, xref="paper", yref="paper", xanchor="right", yanchor="top",
                         text=f"≤20° 舒适区占 {pct:.0f}%", showarrow=False,
                         font=dict(size=11, color=C_SAGE), bgcolor="rgba(254,253,251,0.85)")
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
            yaxis=dict(**_LAYOUT_BASE["yaxis"], range=[0, 100], title="平均专注度"),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时段",
                       tickvals=tick_vals, ticktext=[f"{h:02d}:00" for h in range(0, 24, 4)]),
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
                title=dict(text="分钟/天", side="right"),
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
            ),
            yaxis=dict(
                showgrid=False, zeroline=False,
                tickfont=dict(size=9, color=C_QUIET),
                autorange="reversed",
            ),
            showlegend=False,
        )
        return self._to_html(fig, height=180)

    # ════════════════════════════════════════════════
    # 8. 24h/96 段墙钟时间图表 (v4.41)
    # ════════════════════════════════════════════════

    @staticmethod
    def _bucket_24h(records, start_of_day_ts: float, value_key: str = "focus_score",
                    time_key: str = "window_start", n_slots: int = 96,
                    value_fn=None):
        """v4.41: 将记录分入 24h 的 96 个槽（每槽 15 分钟）。
        v4.43: 新增 value_fn 可选参数，支持计算派生值（如 sqrt(yaw²+pitch²)）。

        Args:
            records: FocusRecord / FatigueRecord / FrameRecord 列表
            start_of_day_ts: 当天 00:00:00 的 Unix 时间戳
            value_key: 取值的属性名（value_fn 为 None 时使用）
            time_key: 取时间的属性名
            n_slots: 槽位数（默认 96 = 15分钟/槽）
            value_fn: 可选，callable(record) -> float；传入时忽略 value_key
        """
        slot_sec = 86400 / n_slots  # 900s = 15min
        slots = [[] for _ in range(n_slots)]

        for r in records:
            t = getattr(r, time_key, None)
            if t is None:
                t = getattr(r, 'timestamp', 0.0)
            if t is None or t <= 0:
                continue
            if value_fn is not None:
                v = value_fn(r)
            else:
                v = getattr(r, value_key, None)
            if v is None:
                continue
            idx = int((t - start_of_day_ts) / slot_sec)
            if 0 <= idx < n_slots:
                slots[idx].append(v)

        result = []
        for i, vals in enumerate(slots):
            t_sec = i * slot_sec
            h = int(t_sec // 3600)
            m = int((t_sec % 3600) // 60)
            if vals:
                result.append({
                    'slot_idx': i,
                    'wall_clock': f"{h}:{m:02d}",
                    'avg': sum(vals) / len(vals),
                    'min_val': min(vals),
                    'max_val': max(vals),
                    'count': len(vals),
                })
            else:
                # v4.42: 空槽也返回（avg=None），由 _fill_empty_slots 后处理
                result.append({
                    'slot_idx': i,
                    'wall_clock': f"{h}:{m:02d}",
                    'avg': None,
                    'min_val': None,
                    'max_val': None,
                    'count': 0,
                })
        return result

    @staticmethod
    def _wall_clock_ticks_24h(interval_hours: int = 1):
        """v4.41: 生成 24h 墙钟时间刻度 (tick positions in seconds, labels)"""
        tick_vals = []
        tick_texts = []
        for h in range(0, 24, interval_hours):
            tick_vals.append(h * 3600)
            tick_texts.append(f"{h}:00")
        return tick_vals, tick_texts

    @staticmethod
    def _fill_empty_slots(bucketed, max_gap_slots: int = 4):
        """v4.42: 空槽填充 — 连续空槽 > max_gap_slots(默认4=1h) 填0；
        连续空槽 ≤ max_gap_slots 用首尾数据点线性插值平滑过渡；
        首尾无边界的空槽保留 None（不参与连线）。

        Returns 新列表（不修改原列表）。
        """
        if not bucketed:
            return bucketed
        n = len(bucketed)
        filled = [dict(b) for b in bucketed]  # 浅拷贝，不修改原数据

        i = 0
        while i < n:
            if filled[i]['avg'] is None:
                gap_start = i
                while i < n and filled[i]['avg'] is None:
                    i += 1
                gap_end = i  # exclusive
                gap_len = gap_end - gap_start

                before = filled[gap_start - 1]['avg'] if gap_start > 0 else None
                after = filled[gap_end]['avg'] if gap_end < n else None

                if gap_len > max_gap_slots:
                    # 长间隙 → 填0贴地
                    for j in range(gap_start, gap_end):
                        filled[j]['avg'] = 0.0
                        filled[j]['min_val'] = 0.0
                        filled[j]['max_val'] = 0.0
                elif before is not None and after is not None:
                    # 短间隙 + 两端有值 → 线性插值平滑过渡
                    for j in range(gap_start, gap_end):
                        frac = (j - gap_start + 1) / (gap_len + 1)
                        v = before + (after - before) * frac
                        filled[j]['avg'] = v
                        filled[j]['min_val'] = v
                        filled[j]['max_val'] = v
                elif before is not None:
                    # 仅有前边界 → 延续前值
                    for j in range(gap_start, gap_end):
                        filled[j]['avg'] = before
                        filled[j]['min_val'] = before
                        filled[j]['max_val'] = before
                elif after is not None:
                    # 仅有后边界 → 反向填补
                    for j in range(gap_start, gap_end):
                        filled[j]['avg'] = after
                        filled[j]['min_val'] = after
                        filled[j]['max_val'] = after
                # else: 全空 → 保留 None
            else:
                i += 1
        return filled

    def generate_focus_trend_24h(self, bucketed, title="专注度趋势（全天）"):
        """v4.41: 24h 墙钟时间专注度趋势图。

        折线=真实avg_raw，标记=低于50分的slot放大凸显异常。
        v4.42: 调用 _fill_empty_slots 填零/插值；hover 用 wall_clock 替代 %{x}。
        """
        if not bucketed:
            return self._empty_html("无数据")

        # v4.42: 空槽填充（>1h填0，≤1h线性插值）
        bucketed = self._fill_empty_slots(bucketed)

        # 过滤剩余 None 值（首尾无边界的空槽）
        valid = [b for b in bucketed if b['avg'] is not None]
        if not valid:
            return self._empty_html("无数据")

        t_sec = [b['slot_idx'] * 900 for b in valid]
        wall_clocks = [b['wall_clock'] for b in valid]
        avgs = [b['avg'] for b in valid]
        counts = [b['count'] for b in valid]

        # 折线颜色基于avg
        colors = [_level_color(a) for a in avgs]
        # 异常点标记尺寸: <50 加大
        marker_sizes = [10 if a < 50 else 6 for a in avgs]
        marker_colors = [C_ROSE if a < 50 else c for a, c in zip(avgs, colors)]

        fig = go.Figure()

        # 折线 (v4.42: 不自动连缺口，text=墙钟时间)
        fig.add_trace(go.Scatter(
            x=t_sec, y=avgs, mode='lines',
            line=dict(width=2.5, color=C_IRIS),
            text=wall_clocks,
            name='专注度',
            hovertemplate='%{y:.0f} 分<br>%{text} (%{customdata}条记录)<extra></extra>',
            customdata=counts,
            connectgaps=False,
        ))

        # 标记点 — 异常点加大 (v4.42: text=墙钟时间)
        fig.add_trace(go.Scatter(
            x=t_sec, y=avgs, mode='markers',
            marker=dict(size=marker_sizes, color=marker_colors,
                       line=dict(width=1, color='white')),
            text=wall_clocks,
            showlegend=False,
            hovertemplate='%{y:.0f} 分<br>%{text}<extra></extra>',
        ))

        # 良好参考线
        fig.add_hline(y=70, line_dash="dash", line_color=C_LINE, line_width=1,
                      annotation_text="良好线 70", annotation_position="left",
                      annotation_font_size=10, annotation_font_color=C_SAGE)

        # 墙钟时间刻度
        tick_vals, tick_texts = self._wall_clock_ticks_24h(interval_hours=2)

        # 检查是否有异常槽（排除零值填充的槽）
        anomaly_count = sum(1 for a in avgs if 0 < a < 50)

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            yaxis=dict(**_LAYOUT_BASE["yaxis"], range=[0, 105], title="专注度"),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间",
                       tickvals=tick_vals, ticktext=tick_texts,
                       range=[-300, 86700]),  # 留一点边距
            showlegend=False,
        )
        if anomaly_count > 0:
            fig.add_annotation(
                x=1, y=0.02, xref="paper", yref="paper",
                xanchor="right", yanchor="bottom",
                text=f"⚠ {anomaly_count} 个低专注时段（标记加大）",
                showarrow=False, font=dict(size=9, color=C_ROSE),
                bgcolor="rgba(254,253,251,0.85)",
            )
        return self._to_html(fig, height=240)

    def generate_blink_rate_24h(self, bucketed, title="眨眼频率趋势（全天）",
                                baseline_blink_rate=None):
        """v4.41: 24h 墙钟时间眨眼频率图
        v4.42: 空槽填充 + hover 用 wall_clock。
        """
        if not bucketed:
            return self._empty_html("无数据")

        bucketed = self._fill_empty_slots(bucketed)
        valid = [b for b in bucketed if b['avg'] is not None]
        if not valid:
            return self._empty_html("无数据")

        t_sec = [b['slot_idx'] * 900 for b in valid]
        wall_clocks = [b['wall_clock'] for b in valid]
        avgs = [b['avg'] for b in valid]

        bl = baseline_blink_rate if baseline_blink_rate and baseline_blink_rate > 0 else 15.0
        colors = [C_ROSE if r > bl * 1.5 else C_AMBER if r > bl * 1.2 else C_SAGE for r in avgs]

        # 柱宽
        bar_w = 800  # ~13min 宽 — 接近 15min 槽宽

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=t_sec, y=avgs,
            marker_color=colors,
            width=bar_w,
            text=wall_clocks,
            name='眨眼频率',
            hovertemplate='%{y:.1f} 次/分<br>%{text}<extra></extra>',
        ))
        fig.add_hline(y=bl, line_dash="dash", line_color=C_SAGE, line_width=1.5,
                      annotation_text=f"基线 {bl:.0f}", annotation_position="left",
                      annotation_font_size=10, annotation_font_color=C_SAGE)

        tick_vals, tick_texts = self._wall_clock_ticks_24h(interval_hours=2)

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            yaxis=dict(**_LAYOUT_BASE["yaxis"], title="次/分"),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间",
                       tickvals=tick_vals, ticktext=tick_texts,
                       range=[-300, 86700]),
            bargap=0.1,
            showlegend=False,
        )
        return self._to_html(fig, height=200)

    def generate_fatigue_24h(self, bucketed, title="疲劳趋势（全天）"):
        """v4.41: 24h 墙钟时间疲劳趋势图
        v4.42: 空槽填充 + hover 用 wall_clock。
        """
        if not bucketed:
            return self._empty_html("无数据")

        bucketed = self._fill_empty_slots(bucketed)
        valid = [b for b in bucketed if b['avg'] is not None]
        if not valid:
            return self._empty_html("无数据")

        t_sec = [b['slot_idx'] * 900 for b in valid]
        wall_clocks = [b['wall_clock'] for b in valid]
        avgs = [b['avg'] for b in valid]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=t_sec, y=avgs, mode='lines',
            line=dict(width=2, color=C_ROSE),
            text=wall_clocks,
            name='疲劳分',
            hovertemplate='%{y:.0f} 分<br>%{text}<extra></extra>',
            connectgaps=False,
        ))
        fig.add_hline(y=60, line_dash="dash", line_color=C_LINE, line_width=1,
                      annotation_text="严重疲劳 60", annotation_position="left",
                      annotation_font_size=10, annotation_font_color=C_ROSE)

        tick_vals, tick_texts = self._wall_clock_ticks_24h(interval_hours=2)

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            yaxis=dict(**_LAYOUT_BASE["yaxis"], title="疲劳分"),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间",
                       tickvals=tick_vals, ticktext=tick_texts,
                       range=[-300, 86700]),
            showlegend=False,
        )
        return self._to_html(fig, height=220)

    def generate_head_pose_24h(self, bucketed, title="头部姿态变化（全天）"):
        """v4.43: 24h 墙钟时间头部姿态偏移趋势图。
        折线=平均偏移角度，空槽>1h贴零，≤1h线性插值。
        """
        if not bucketed:
            return self._empty_html("无头部姿态数据")

        bucketed = self._fill_empty_slots(bucketed)
        valid = [b for b in bucketed if b['avg'] is not None]
        if not valid:
            return self._empty_html("无头部姿态数据")

        t_sec = [b['slot_idx'] * 900 for b in valid]
        wall_clocks = [b['wall_clock'] for b in valid]
        avgs = [b['avg'] for b in valid]

        # 计算舒适区占比（排除零值填充）
        real_vals = [a for a in avgs if a > 0]
        in_zone = sum(1 for a in real_vals if a <= 20)
        pct = in_zone / len(real_vals) * 100 if real_vals else 0

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=t_sec, y=avgs, mode='lines',
            line=dict(width=1.5, color=C_IRIS),
            text=wall_clocks,
            name='偏移角',
            hovertemplate='%{y:.1f}°<br>%{text}<extra></extra>',
            connectgaps=False,
        ))
        fig.add_hline(y=20, line_dash="dash", line_color=C_SAGE, line_width=1,
                      annotation_text="舒适上限 20°", annotation_position="right",
                      annotation_font_size=10, annotation_font_color=C_SAGE)

        tick_vals, tick_texts = self._wall_clock_ticks_24h(interval_hours=2)

        fig.update_layout(**_LAYOUT_BASE)
        fig.update_layout(
            yaxis=dict(**_LAYOUT_BASE["yaxis"], title="偏移度 (°)"),
            xaxis=dict(**_LAYOUT_BASE["xaxis"], title="时间",
                       tickvals=tick_vals, ticktext=tick_texts,
                       range=[-300, 86700]),
            showlegend=False,
            annotations=[
                dict(x=1, y=0.98, xref="paper", yref="paper",
                     xanchor="right", yanchor="top",
                     text=f"≤20° 舒适区占 {pct:.0f}%", showarrow=False,
                     font=dict(size=11, color=C_SAGE),
                     bgcolor="rgba(254,253,251,0.85)"),
            ],
        )
        return self._to_html(fig, height=220)

    def _empty_html(self, message):
        return f'<div style="text-align:center;color:#ccc;padding:32px;font-size:13px">{message}</div>'


def create_chart_generator(figsize=(6, 2.8), dpi=120):
    return ChartGenerator(figsize=figsize, dpi=dpi)

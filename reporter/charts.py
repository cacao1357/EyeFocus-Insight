"""
reporter/charts.py — Matplotlib 图表生成模块

生成专注度趋势图、眨眼频率分布图、疲劳等级时间线图等。
依赖 Matplotlib 生成静态图表，图表以 PNG 格式嵌入 HTML 报告。
"""

import io
import logging
from typing import List, Optional, Tuple

import matplotlib
matplotlib.use('Agg')  # 无头模式，不使用交互式后端
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

from storage.models import FocusRecord, FatigueRecord, FatigueLevel, BlinkRecord

logger = logging.getLogger("eyefocus.reporter")

# 中文字体配置
_CHINESE_FONTS = [
    'Microsoft YaHei',
    'SimHei',
    'PingFang SC',
    'Hiragino Sans GB',
    'WenQuanYi Micro Hei',
]


def _get_chinese_font() -> str:
    """获取可用的中文字体"""
    available = {f.name for f in fm.fontManager.ttflist}

    for font in _CHINESE_FONTS:
        if font in available:
            return font

    # 尝试从系统字体路径查找
    for font in _CHINESE_FONTS:
        font_path = fm.findfont(fm.FontProperties(family=font))
        if font_path and 'fonts' in font_path.lower():
            return font

    logger.warning("未找到中文字体，图表中文可能显示异常")
    return 'sans-serif'


# 设置中文字体
plt.rcParams['font.sans-serif'] = [_get_chinese_font()]
plt.rcParams['axes.unicode_minus'] = False


class ChartGenerator:
    """图表生成器

    使用方法：
        generator = ChartGenerator()
        img_bytes = generator.generate_focus_trend_chart(focus_records)
    """

    def __init__(self, figsize: Tuple[int, int] = (10, 4), dpi: int = 100):
        """初始化图表生成器

        Args:
            figsize: 图表尺寸 (宽, 高) 英寸
            dpi: 图像分辨率
        """
        self.figsize = figsize
        self.dpi = dpi

    def _format_time_labels(self, timestamps: List[float]) -> List[str]:
        """格式化时间标签"""
        if not timestamps:
            return []
        # 假设 timestamps 是相对时间（秒），转换为 MM:SS 格式
        result = []
        for t in timestamps:
            minutes = int(t // 60)
            seconds = int(t % 60)
            result.append(f"{minutes:02d}:{seconds:02d}")
        return result

    def generate_focus_trend_chart(
        self,
        focus_records: List[FocusRecord],
        title: str = "专注度趋势",
    ) -> bytes:
        """生成专注度趋势图

        Args:
            focus_records: 专注度记录列表
            title: 图表标题

        Returns:
            PNG 格式图像字节数据
        """
        if not focus_records:
            return self._create_empty_chart("无数据")

        fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)

        # 提取数据
        windows = [(r.window_start + r.window_end) / 2 for r in focus_records]
        focus_scores = [r.focus_score for r in focus_records]
        eye_scores = [r.eye_score for r in focus_records]
        head_scores = [r.head_score for r in focus_records]

        # 绘制曲线
        time_labels = self._format_time_labels(windows)

        x = range(len(windows))
        ax.plot(x, focus_scores, 'b-', label='综合专注度', linewidth=2, alpha=0.8)
        ax.plot(x, eye_scores, 'g--', label='眼部专注', linewidth=1.5, alpha=0.7)
        ax.plot(x, head_scores, 'r--', label='头部姿态', linewidth=1.5, alpha=0.7)

        # 添加 60 分及格线
        ax.axhline(y=60, color='orange', linestyle=':', linewidth=1.5, label='专注及格线')

        # 配置
        ax.set_xlabel('时间')
        ax.set_ylabel('专注度分数')
        ax.set_title(title)
        ax.set_ylim(0, 100)
        ax.legend(loc='lower right', fontsize=8)
        ax.grid(True, alpha=0.3)

        # 设置时间标签（每 5 个点显示一个）
        tick_step = max(1, len(time_labels) // 6)
        ax.set_xticks(x[::tick_step])
        ax.set_xticklabels(time_labels[::tick_step], rotation=45, ha='right')

        plt.tight_layout()

        return self._fig_to_bytes(fig)

    def generate_blink_rate_distribution(
        self,
        blink_records: List[BlinkRecord],
        focus_records: List[FocusRecord],
        title: str = "眨眼频率分布",
    ) -> bytes:
        """生成眨眼频率分布图

        Args:
            blink_records: 眨眼事件列表
            focus_records: 专注度记录列表（用于计算频率）
            title: 图表标题

        Returns:
            PNG 格式图像字节数据
        """
        if not focus_records:
            return self._create_empty_chart("无数据")

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=self.figsize, dpi=self.dpi)

        # 左图：眨眼频率时间线
        blink_rates = [r.blink_rate for r in focus_records]
        windows = [(r.window_start + r.window_end) / 2 for r in focus_records]
        time_labels = self._format_time_labels(windows)

        x = range(len(windows))
        ax1.bar(x, blink_rates, color='steelblue', alpha=0.7)
        ax1.axhline(y=15, color='green', linestyle='--', label='正常范围 (15次/分)')
        ax1.axhline(y=20, color='orange', linestyle='--', label='轻度疲劳 (20次/分)')
        ax1.axhline(y=30, color='red', linestyle='--', label='明显疲劳 (30次/分)')
        ax1.set_xlabel('时间')
        ax1.set_ylabel('眨眼频率 (次/分钟)')
        ax1.set_title('眨眼频率时间线')
        ax1.legend(loc='upper right', fontsize=7)
        ax1.grid(True, alpha=0.3, axis='y')

        tick_step = max(1, len(time_labels) // 6)
        ax1.set_xticks(x[::tick_step])
        ax1.set_xticklabels(time_labels[::tick_step], rotation=45, ha='right')

        # 右图：眨眼频率分布直方图
        blink_durations = [e.duration_seconds * 1000 for e in blink_records]  # 转换为毫秒

        if blink_durations:
            ax2.hist(blink_durations, bins=20, color='steelblue', alpha=0.7, edgecolor='white')
            ax2.axvline(x=np.mean(blink_durations), color='red', linestyle='--',
                       label=f'平均: {np.mean(blink_durations):.0f}ms')
            ax2.set_xlabel('眨眼时长 (毫秒)')
            ax2.set_ylabel('频次')
            ax2.set_title('眨眼时长分布')
            ax2.legend(fontsize=8)
        else:
            ax2.text(0.5, 0.5, '无眨眼数据', ha='center', va='center', transform=ax2.transAxes)

        plt.suptitle(title, fontsize=12)
        plt.tight_layout()

        return self._fig_to_bytes(fig)

    def generate_fatigue_timeline(
        self,
        fatigue_records: List[FatigueRecord],
        title: str = "疲劳等级时间线",
    ) -> bytes:
        """生成疲劳等级时间线图

        Args:
            fatigue_records: 疲劳记录列表
            title: 图表标题

        Returns:
            PNG 格式图像字节数据
        """
        if not fatigue_records:
            return self._create_empty_chart("无数据")

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=self.figsize, dpi=self.dpi, sharex=True)

        # 提取数据
        timestamps = [r.timestamp for r in fatigue_records]
        cumulative_scores = [r.cumulative_fatigue_score for r in fatigue_records]

        # 眨眼频率
        blink_rates = [r.blink_rate for r in fatigue_records]

        # 时间标签
        time_labels = self._format_time_labels(timestamps)

        # 上图：累积疲劳分数
        ax1.fill_between(range(len(timestamps)), cumulative_scores, alpha=0.3, color='red')
        ax1.plot(range(len(timestamps)), cumulative_scores, 'r-', linewidth=2)
        ax1.set_ylabel('累积疲劳分数')
        ax1.set_title('累积疲劳趋势')
        ax1.grid(True, alpha=0.3)
        ax1.set_ylim(0, 100)

        # 下图：眨眼频率
        ax2.bar(range(len(timestamps)), blink_rates, color='steelblue', alpha=0.7)
        ax2.axhline(y=15, color='green', linestyle='--', label='正常')
        ax2.axhline(y=30, color='red', linestyle='--', label='疲劳')
        ax2.set_xlabel('时间')
        ax2.set_ylabel('眨眼频率 (次/分钟)')
        ax2.set_title('眨眼频率变化')
        ax2.legend(loc='upper right', fontsize=8)
        ax2.grid(True, alpha=0.3, axis='y')

        # 设置时间标签
        tick_step = max(1, len(time_labels) // 6)
        ax2.set_xticks(range(len(timestamps))[::tick_step])
        ax2.set_xticklabels(time_labels[::tick_step], rotation=45, ha='right')

        plt.suptitle(title, fontsize=12)
        plt.tight_layout()

        return self._fig_to_bytes(fig)

    def generate_summary_chart(
        self,
        avg_focus: float,
        avg_blink_rate: float,
        fatigue_level: FatigueLevel,
        total_duration: float,
        title: str = "会话摘要",
    ) -> bytes:
        """生成会话摘要图表

        Args:
            avg_focus: 平均专注度
            avg_blink_rate: 平均眨眼频率
            fatigue_level: 疲劳等级
            total_duration: 总时长（秒）
            title: 图表标题

        Returns:
            PNG 格式图像字节数据
        """
        fig, axes = plt.subplots(1, 3, figsize=self.figsize, dpi=self.dpi)

        # 专注度仪表盘
        self._draw_gauge(axes[0], avg_focus, 100, '专注度', ['red', 'orange', 'yellow', 'green'])

        # 眨眼频率
        self._draw_gauge(axes[1], avg_blink_rate, 40, '眨眼频率', ['green', 'yellow', 'orange', 'red'],
                        reverse=True)

        # 疲劳等级
        fatigue_colors = {
            FatigueLevel.LOW: 'green',
            FatigueLevel.MEDIUM: 'orange',
            FatigueLevel.HIGH: 'red',
        }
        fatigue_labels = {
            FatigueLevel.LOW: '低疲劳',
            FatigueLevel.MEDIUM: '中疲劳',
            FatigueLevel.HIGH: '高疲劳',
        }

        axes[2].bar([0], [1], color=fatigue_colors.get(fatigue_level, 'gray'))
        axes[2].set_xlim(-0.5, 0.5)
        axes[2].set_ylim(0, 1.5)
        axes[2].text(0, 0.5, fatigue_labels.get(fatigue_level, '未知'),
                    ha='center', va='center', fontsize=14, fontweight='bold')
        axes[2].text(0, 0.1, f"时长: {int(total_duration // 60)}分{int(total_duration % 60)}秒",
                    ha='center', va='center', fontsize=10)
        axes[2].set_title('疲劳等级')
        axes[2].axis('off')

        plt.suptitle(title, fontsize=12)
        plt.tight_layout()

        return self._fig_to_bytes(fig)

    def _draw_gauge(
        self,
        ax,
        value: float,
        max_value: float,
        label: str,
        colors: List[str],
        reverse: bool = False,
    ) -> None:
        """绘制简单仪表盘"""
        # 归一化值
        norm_value = min(1.0, max(0.0, value / max_value))

        # 背景条
        ax.barh([0], [1], color='lightgray', height=0.3)

        # 填充条
        color_idx = int(norm_value * (len(colors) - 1))
        if reverse:
            color_idx = len(colors) - 1 - color_idx
        ax.barh([0], [norm_value], color=colors[color_idx], height=0.3)

        ax.set_xlim(0, 1)
        ax.set_ylim(-0.3, 0.3)
        ax.text(0.5, -0.15, f"{value:.1f}", ha='center', va='center', fontsize=14, fontweight='bold')
        ax.text(0.5, 0.15, label, ha='center', va='center', fontsize=10)
        ax.axis('off')

    def _create_empty_chart(self, message: str) -> bytes:
        """创建空白占位图表"""
        fig, ax = plt.subplots(figsize=(self.figsize[0], 2), dpi=self.dpi)
        ax.text(0.5, 0.5, message, ha='center', va='center', fontsize=12, color='gray')
        ax.axis('off')
        plt.tight_layout()
        return self._fig_to_bytes(fig)

    def _fig_to_bytes(self, fig) -> bytes:
        """将 matplotlib 图表转换为 PNG 字节数据"""
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=self.dpi, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()


def create_chart_generator(figsize: Tuple[int, int] = (10, 4), dpi: int = 100) -> ChartGenerator:
    """工厂函数：创建图表生成器"""
    return ChartGenerator(figsize=figsize, dpi=dpi)

"""
reporter/insights.py — 个性化建议引擎

基于专注度/疲劳数据分析，生成个性化改善建议。
识别专注度下降模式，提供针对性建议。

建议分类：
- 专注度下降警告
- 疲劳预警
- 改善建议
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from storage.models import FocusRecord, FatigueRecord, FatigueLevel

logger = logging.getLogger("eyefocus.reporter")


@dataclass
class Insight:
    """建议数据模型"""
    category: str          # 类别: 'focus', 'fatigue', 'behavior', 'recommendation'
    severity: str          # 严重程度: 'info', 'warning', 'alert'
    title: str             # 标题
    description: str       # 详细描述
    suggestion: str        # 改善建议
    data_evidence: Optional[dict] = None  # 支持数据


@dataclass
class FocusPattern:
    """专注度模式"""
    pattern_type: str           # 'declining', 'unstable', 'stable', 'periodic'
    description: str
    evidence: dict


class InsightsEngine:
    """个性化建议引擎

    使用方法：
        engine = InsightsEngine()
        insights = engine.analyze(
            focus_records=focus_list,
            fatigue_records=fatigue_list,
            avg_focus=75.5,
            avg_blink_rate=18.0,
            session_duration=1800,
        )
    """

    # 专注度阈值
    FOCUS_GOOD = 70.0
    FOCUS_WARNING = 50.0
    FOCUS_POOR = 30.0

    # 眨眼频率阈值 (次/分钟)
    BLINK_NORMAL = 15.0
    BLINK_ELEVATED = 20.0
    BLINK_HIGH = 30.0

    # 头部稳定性阈值
    HEAD_STABILITY_LOW = 70.0

    def __init__(self):
        """初始化建议引擎"""
        self._focus_trends: List[float] = []
        self._blink_trends: List[float] = []

    def analyze(
        self,
        focus_records: List[FocusRecord],
        fatigue_records: List[FatigueRecord],
        avg_focus: float,
        avg_blink_rate: float,
        session_duration: float,
    ) -> List[Insight]:
        """分析数据并生成建议

        Args:
            focus_records: 专注度记录列表
            fatigue_records: 疲劳记录列表
            avg_focus: 平均专注度
            avg_blink_rate: 平均眨眼频率
            session_duration: 会话时长（秒）

        Returns:
            Insight 列表，按严重程度排序
        """
        insights: List[Insight] = []

        # 分析专注度模式
        if focus_records:
            pattern = self._detect_focus_pattern(focus_records)
            insights.extend(self._pattern_to_insights(pattern))

            # 专注度下降趋势分析
            focus_trend_insight = self._analyze_focus_trend(focus_records)
            if focus_trend_insight:
                insights.append(focus_trend_insight)

        # 疲劳分析
        if fatigue_records:
            insights.extend(self._analyze_fatigue(fatigue_records))

        # 眨眼频率分析
        blink_insights = self._analyze_blink_rate(avg_blink_rate)
        insights.extend(blink_insights)

        # 综合建议
        insights.extend(self._generate_recommendations(
            avg_focus=avg_focus,
            avg_blink_rate=avg_blink_rate,
            session_duration=session_duration,
            focus_records=focus_records,
        ))

        # 按严重程度排序
        severity_order = {'alert': 0, 'warning': 1, 'info': 2}
        insights.sort(key=lambda x: severity_order.get(x.severity, 2))

        return insights

    def _detect_focus_pattern(self, focus_records: List[FocusRecord]) -> FocusPattern:
        """检测专注度模式"""
        focus_scores = [r.focus_score for r in focus_records]

        if len(focus_scores) < 3:
            return FocusPattern('stable', '数据不足，无法判断模式', {})

        # 计算趋势（线性回归斜率）
        x = np.arange(len(focus_scores))
        slope = np.polyfit(x, focus_scores, 1)[0]

        # 计算标准差（稳定性）
        std = np.std(focus_scores)
        mean = np.mean(focus_scores)

        # 检测周期性波动（简单检测：相邻差值）
        diffs = np.abs(np.diff(focus_scores))
        periodic_score = np.mean(diffs) / (std + 1e-6)

        # 判断模式
        if slope < -2.0:
            pattern_type = 'declining'
            description = f'专注度呈下降趋势（斜率: {slope:.2f}）'
        elif std > 20:
            pattern_type = 'unstable'
            description = f'专注度波动较大（标准差: {std:.1f}）'
        elif periodic_score > 0.8:
            pattern_type = 'periodic'
            description = '专注度存在周期性波动'
        else:
            pattern_type = 'stable'
            description = '专注度基本稳定'

        return FocusPattern(
            pattern_type=pattern_type,
            description=description,
            evidence={
                'slope': slope,
                'std': std,
                'mean': mean,
                'min': np.min(focus_scores),
                'max': np.max(focus_scores),
            }
        )

    def _pattern_to_insights(self, pattern: FocusPattern) -> List[Insight]:
        """将专注度模式转换为建议"""
        insights = []

        if pattern.pattern_type == 'declining':
            insights.append(Insight(
                category='focus',
                severity='warning',
                title='专注度持续下降',
                description=pattern.description,
                suggestion='建议短暂休息（5-10分钟），起身活动有助于恢复专注力',
                data_evidence=pattern.evidence,
            ))
        elif pattern.pattern_type == 'unstable':
            insights.append(Insight(
                category='focus',
                severity='info',
                title='专注度波动较大',
                description=pattern.description,
                suggestion='波动可能受环境影响，尝试减少干扰源',
                data_evidence=pattern.evidence,
            ))

        return insights

    def _analyze_focus_trend(self, focus_records: List[FocusRecord]) -> Optional[Insight]:
        """分析专注度趋势，检测异常"""
        if len(focus_records) < 5:
            return None

        # 取最后 1/4 的记录
        cutoff_idx = len(focus_records) * 3 // 4
        recent_records = focus_records[cutoff_idx:]

        if not recent_records:
            return None

        recent_avg = np.mean([r.focus_score for r in recent_records])
        overall_avg = np.mean([r.focus_score for r in focus_records])

        # 如果最近专注度明显下降
        if recent_avg < overall_avg * 0.8 and recent_avg < self.FOCUS_WARNING:
            return Insight(
                category='focus',
                severity='alert',
                title='专注度急剧下降',
                description=f'最近专注度 ({recent_avg:.1f}) 明显低于整体 ({overall_avg:.1f})',
                suggestion='立即休息，避免疲劳累积',
                data_evidence={
                    'recent_avg': recent_avg,
                    'overall_avg': overall_avg,
                },
            )

        return None

    def _analyze_fatigue(self, fatigue_records: List[FatigueRecord]) -> List[Insight]:
        """分析疲劳数据"""
        insights = []

        if not fatigue_records:
            return insights

        cumulative_scores = [r.cumulative_fatigue_score for r in fatigue_records]
        recent_cumulative = cumulative_scores[-1] if cumulative_scores else 0

        # 累积疲劳分析
        if recent_cumulative > 70:
            insights.append(Insight(
                category='fatigue',
                severity='alert',
                title='疲劳累积严重',
                description=f'累积疲劳分数达到 {recent_cumulative:.1f}',
                suggestion='建议立即休息，疲劳会影响判断力和反应速度',
                data_evidence={'cumulative_fatigue': recent_cumulative},
            ))
        elif recent_cumulative > 50:
            insights.append(Insight(
                category='fatigue',
                severity='warning',
                title='疲劳开始累积',
                description=f'累积疲劳分数达到 {recent_cumulative:.1f}',
                suggestion='注意休息，每45-50分钟休息一次',
                data_evidence={'cumulative_fatigue': recent_cumulative},
            ))

        # 疲劳等级分析
        recent_level = fatigue_records[-1].fatigue_level
        if recent_level == FatigueLevel.HIGH:
            insights.append(Insight(
                category='fatigue',
                severity='alert',
                title='当前疲劳等级: 高',
                description='检测到明显的疲劳迹象',
                suggestion='强烈建议休息，必要时可进行短暂午睡',
                data_evidence={'fatigue_level': 'high'},
            ))
        elif recent_level == FatigueLevel.MEDIUM:
            insights.append(Insight(
                category='fatigue',
                severity='warning',
                title='当前疲劳等级: 中',
                description='疲劳程度适中',
                suggestion='保持警惕，适时休息',
                data_evidence={'fatigue_level': 'medium'},
            ))

        return insights

    def _analyze_blink_rate(self, avg_blink_rate: float) -> List[Insight]:
        """分析眨眼频率"""
        insights = []

        if avg_blink_rate > self.BLINK_HIGH:
            insights.append(Insight(
                category='fatigue',
                severity='warning',
                title='眨眼频率偏高',
                description=f'平均眨眼频率 {avg_blink_rate:.1f} 次/分钟',
                suggestion='眨眼频率过高可能是疲劳信号，注意适当休息',
                data_evidence={'avg_blink_rate': avg_blink_rate},
            ))
        elif avg_blink_rate > self.BLINK_ELEVATED:
            insights.append(Insight(
                category='behavior',
                severity='info',
                title='眨眼频率略高',
                description=f'平均眨眼频率 {avg_blink_rate:.1f} 次/分钟',
                suggestion='保持当前状态，注意用眼卫生',
                data_evidence={'avg_blink_rate': avg_blink_rate},
            ))

        return insights

    def _generate_recommendations(
        self,
        avg_focus: float,
        avg_blink_rate: float,
        session_duration: float,
        focus_records: List[FocusRecord],
    ) -> List[Insight]:
        """生成综合建议"""
        insights = []
        duration_minutes = session_duration / 60.0

        # 基于时长的建议
        if duration_minutes > 60:
            insights.append(Insight(
                category='recommendation',
                severity='info',
                title='连续工作时长较长',
                description=f'已连续工作 {int(duration_minutes)} 分钟',
                suggestion='建议每45-50分钟休息5-10分钟，保持高效',
                data_evidence={'duration_minutes': duration_minutes},
            ))

        # 基于综合专注度的建议
        if avg_focus >= self.FOCUS_GOOD:
            insights.append(Insight(
                category='recommendation',
                severity='info',
                title='专注状态良好',
                description=f'平均专注度 {avg_focus:.1f}，状态良好',
                suggestion='继续保持，注意适时休息',
                data_evidence={'avg_focus': avg_focus},
            ))
        elif avg_focus >= self.FOCUS_WARNING:
            insights.append(Insight(
                category='recommendation',
                severity='info',
                title='专注度一般',
                description=f'平均专注度 {avg_focus:.1f}',
                suggestion='尝试减少干扰，提高工作环境质量',
                data_evidence={'avg_focus': avg_focus},
            ))

        # 眼部健康建议
        if avg_blink_rate < self.BLINK_NORMAL * 0.8:
            insights.append(Insight(
                category='recommendation',
                severity='warning',
                title='眨眼频率偏低',
                description=f'眨眼频率 {avg_blink_rate:.1f} 次/分钟，可能存在干眼风险',
                suggestion='有意识地多眨眼，使用人工泪液润滑眼睛',
                data_evidence={'avg_blink_rate': avg_blink_rate},
            ))

        return insights

    def generate_summary(self, insights: List[Insight]) -> str:
        """生成建议摘要文本

        Args:
            insights: 建议列表

        Returns:
            格式化的摘要文本
        """
        if not insights:
            return "未检测到明显问题，继续保持当前状态。"

        lines = []
        for insight in insights[:5]:  # 最多显示 5 条
            icon = {
                'alert': '⚠',
                'warning': '⚡',
                'info': 'ℹ',
            }.get(insight.severity, '•')

            lines.append(f"{icon} {insight.title}")
            lines.append(f"   {insight.suggestion}")
            lines.append("")

        return "\n".join(lines)

    def analyze_with_attributions(
        self,
        focus_records: List[FocusRecord],
        fatigue_records: List[FatigueRecord],
        avg_focus: float,
        avg_blink_rate: float,
        session_duration: float,
        attribution_findings: Optional[list] = None,
    ) -> List[Insight]:
        """分析数据并生成建议，attribution findings 为主输入，规则引擎兜底。

        Args:
            focus_records: 专注度记录
            fatigue_records: 疲劳记录
            avg_focus: 平均专注度
            avg_blink_rate: 平均眨眼频率
            session_duration: 会话时长（秒）
            attribution_findings: 可选，insights pipeline 的关联分析结果

        Returns:
            Insight 列表
        """
        # 先用规则引擎生成基础建议
        insights = self.analyze(
            focus_records=focus_records,
            fatigue_records=fatigue_records,
            avg_focus=avg_focus,
            avg_blink_rate=avg_blink_rate,
            session_duration=session_duration,
        )

        # 如果有 attribution findings，转换成 Insight 并追加
        if attribution_findings:
            attr_insights = attribution_findings_to_insights(attribution_findings)
            # 去重：避免跟规则引擎的重复
            existing_titles = {i.title for i in insights}
            for ai in attr_insights:
                if ai.title not in existing_titles:
                    insights.append(ai)
                    existing_titles.add(ai.title)

        return insights


def attribution_findings_to_insights(attribution_findings: list) -> List[Insight]:
    """将 insights pipeline 的关联分析发现转换为 Insight 对象。

    Args:
        attribution_findings: pipeline result 的 attribution_findings 列表

    Returns:
        Insight 列表
    """
    insights = []
    for f in attribution_findings:
        factor = f.get("factor", "未知因子")
        direction = f.get("direction", "")
        summary = f.get("summary", "")
        effect_size = f.get("effect_size", 0)
        p_value = f.get("p_value", 1.0)

        # 根据 effect size 确定严重程度
        abs_effect = abs(effect_size)
        if abs_effect >= 0.8:
            severity = "alert"
        elif abs_effect >= 0.5:
            severity = "warning"
        else:
            severity = "info"

        # 生成建议文案
        suggestion = _factor_to_suggestion(factor, direction, effect_size)

        insights.append(Insight(
            category="recommendation",
            severity=severity,
            title=f"关联发现：{factor}",
            description=summary,
            suggestion=suggestion,
            data_evidence={
                "factor": factor,
                "effect_size": round(effect_size, 3),
                "p_value": round(p_value, 4),
                "direction": direction,
            },
        ))

    return insights


def _factor_to_suggestion(factor: str, direction: str, effect_size: float) -> str:
    """根据因子和方向生成可执行建议。"""
    suggestions = {
        "时段": {
            "正向": "你在特定时段表现更好，建议将重要工作安排在高效率时段",
            "负向": "当前时段可能不是你的最佳工作时间，尝试调整日程",
        },
        "会话时长": {
            "正向": "长时间工作仍保持专注，注意适当休息防止疲劳",
            "负向": "专注度随工作时间下降，建议采用番茄工作法（25分钟工作+5分钟休息）",
        },
        "眨眼频率比": {
            "正向": "眨眼频率正常，眼部状态良好",
            "负向": "眨眼频率异常，可能存在视疲劳，建议使用人工泪液并定期远眺",
        },
        "视线偏离比": {
            "正向": "视线集中度高，专注状态良好",
            "负向": "频繁视线偏离可能影响工作效率，建议减少环境干扰",
        },
        "PERCLOS": {
            "正向": "眼睑开合正常，无疲劳迹象",
            "负向": "眼睑闭合时间偏长，可能已处于疲劳状态，建议立即休息",
        },
        "头部运动": {
            "正向": "头部姿态稳定，坐姿良好",
            "负向": "头部晃动频繁，建议调整坐姿或检查 ergonomics",
        },
        "平均专注度": {
            "正向": "整体专注度水平良好",
            "负向": "专注度偏低，建议减少多任务并行，尝试单任务专注",
        },
        "专注度波动": {
            "正向": "专注度稳定，工作节奏良好",
            "负向": "专注度波动大，可能受频繁打断影响，建议使用免打扰时段",
        },
        "重度疲劳比": {
            "正向": "疲劳管理良好",
            "负向": "重度疲劳时间占比较高，建议增加休息频率",
        },
        "暗光比": {
            "正向": "工作环境光照良好",
            "负向": "暗光环境下工作增加眼疲劳风险，建议增加环境照明",
        },
    }

    key = "正向" if effect_size > 0 else "负向"
    factor_group = None
    for fname, advice in suggestions.items():
        if fname in factor:
            factor_group = advice
            break

    if factor_group:
        return factor_group.get(key, f"因子 {factor} 与专注度存在{direction}关联（效应量={effect_size:.2f}）")

    return f"检测到 {factor} 与专注度存在{direction}关联（效应量={effect_size:.2f}），建议关注该因素对工作效率的影响"


def create_insights_engine() -> InsightsEngine:
    """工厂函数：创建建议引擎"""
    return InsightsEngine()

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

    def __init__(self, db=None):
        """初始化建议引擎

        Args:
            db: 可选 DatabaseManager 实例，用于历史对比
        """
        self._db = db
        self._focus_trends: List[float] = []
        self._blink_trends: List[float] = []

    def analyze(
        self,
        focus_records: List[FocusRecord],
        fatigue_records: List[FatigueRecord],
        avg_focus: float,
        avg_blink_rate: float,
        session_duration: float,
        session_id: Optional[str] = None,
        session_start_time: Optional[float] = None,
    ) -> List[Insight]:
        """分析数据并生成建议

        Args:
            focus_records: 专注度记录列表
            fatigue_records: 疲劳记录列表
            avg_focus: 平均专注度
            avg_blink_rate: 平均眨眼频率
            session_duration: 会话时长（秒）
            session_id: 可选，会话 ID（用于历史对比）
            session_start_time: 可选，会话开始时间戳（用于时段分析）

        Returns:
            Insight 列表，按严重程度排序
        """
        insights: List[Insight] = []

        # 分析专注度模式
        if focus_records:
            pattern = self._detect_focus_pattern(focus_records, session_start_time)
            insights.extend(self._pattern_to_insights(pattern))

            # 专注度下降趋势分析
            focus_trend_insight = self._analyze_focus_trend(focus_records)
            if focus_trend_insight:
                insights.append(focus_trend_insight)

            # Tier 2: 薄弱环节分析
            weak_insights = self._find_weak_segments(focus_records)
            insights.extend(weak_insights)

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

        # Tier 3: 历史对比
        hist_insight = self._compare_with_history(
            avg_focus, avg_blink_rate, session_id, session_start_time)
        if hist_insight:
            insights.append(hist_insight)

        # 按严重程度排序
        severity_order = {'alert': 0, 'warning': 1, 'info': 2}
        insights.sort(key=lambda x: severity_order.get(x.severity, 2))

        return insights

    def _detect_focus_pattern(
        self, focus_records: List[FocusRecord],
        session_start_time: Optional[float] = None,
    ) -> FocusPattern:
        """检测专注度模式（v4.10: 加入时间信息和数据引用）"""
        focus_scores = [r.focus_score for r in focus_records]

        if len(focus_scores) < 3:
            return FocusPattern('stable', '数据不足，无法判断模式', {})

        # 计算趋势（线性回归斜率）
        x = np.arange(len(focus_scores))
        slope = np.polyfit(x, focus_scores, 1)[0]

        # 计算标准差（稳定性）
        std = np.std(focus_scores)
        mean = np.mean(focus_scores)
        fmin = np.min(focus_scores)
        fmax = np.max(focus_scores)

        # 检测周期性波动（简单检测：相邻差值）
        diffs = np.abs(np.diff(focus_scores))
        periodic_score = np.mean(diffs) / (std + 1e-6)

        # 判断模式 + 动态描述
        if slope < -2.0:
            pattern_type = 'declining'
            # 找出下降起始点
            first_half = np.mean(focus_scores[:len(focus_scores)//2])
            second_half = np.mean(focus_scores[len(focus_scores)//2:])
            if first_half - second_half > 10:
                pct = int((first_half - second_half) / first_half * 100)
                decline_min = len(focus_scores) // 4 if len(focus_scores) > 4 else 0
                description = f'专注度从约第{decline_min}个时间段起持续下降（{first_half:.0f}→{second_half:.0f}），降幅约{pct}%'
            else:
                description = f'专注度呈下降趋势（{fmax:.0f}→{fmin:.0f}），斜率: {slope:.2f}'
        elif std > 20:
            pattern_type = 'unstable'
            description = f'专注度波动较大（最高{fmax:.0f} / 最低{fmin:.0f}，标准差{std:.1f}）'
        elif periodic_score > 0.8:
            pattern_type = 'periodic'
            description = '专注度存在周期性波动，可能受固定间隔干扰影响'
        else:
            pattern_type = 'stable'
            description = f'专注度基本稳定（均值{mean:.1f}，波动范围{int(fmax-fmin)}分）'

        return FocusPattern(
            pattern_type=pattern_type,
            description=description,
            evidence={
                'slope': slope,
                'std': std,
                'mean': mean,
                'min': fmin,
                'max': fmax,
            }
        )

    def _pattern_to_insights(self, pattern: FocusPattern) -> List[Insight]:
        """将专注度模式转换为建议（v4.10: 动态描述）"""
        insights = []

        if pattern.pattern_type == 'declining':
            ev = pattern.evidence
            drop = int(ev.get('max', 0) - ev.get('min', 0))
            insights.append(Insight(
                category='focus',
                severity='warning',
                title='专注度持续下降',
                description=pattern.description,
                suggestion=f'建议短暂休息5-10分钟，起身活动有助于恢复专注力'
                          f'（专注度已下降约{drop}分）',
                data_evidence=pattern.evidence,
            ))
        elif pattern.pattern_type == 'unstable':
            ev = pattern.evidence
            insights.append(Insight(
                category='focus',
                severity='info',
                title='专注度波动较大',
                description=pattern.description,
                suggestion=f'波动范围{int(ev.get("max", 0)-ev.get("min", 0))}分，'
                          f'可能受环境影响，建议减少干扰源或切换任务',
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
        """分析疲劳数据（v4.10: 数值化描述）"""
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
                description=f'累积疲劳分数已达{recent_cumulative:.0f}（阈值70），超出{recent_cumulative-70:.0f}分',
                suggestion='建议立即休息10-15分钟，疲劳已明显影响判断力和反应速度',
                data_evidence={'cumulative_fatigue': recent_cumulative},
            ))
        elif recent_cumulative > 50:
            insights.append(Insight(
                category='fatigue',
                severity='warning',
                title='疲劳开始累积',
                description=f'累积疲劳分数{recent_cumulative:.0f}（警戒线50），距离严重疲劳还有{70-recent_cumulative:.0f}分',
                suggestion='注意休息，建议每45-50分钟休息5分钟',
                data_evidence={'cumulative_fatigue': recent_cumulative},
            ))

        # 疲劳等级分析
        recent_level = fatigue_records[-1].fatigue_level
        if recent_level == FatigueLevel.HIGH:
            high_count = sum(1 for r in fatigue_records if r.fatigue_level == FatigueLevel.HIGH)
            total = len(fatigue_records)
            insights.append(Insight(
                category='fatigue',
                severity='alert',
                title='当前疲劳等级: 高',
                description=f'检测到明显疲劳迹象，{high_count}/{total}个时段处于高疲劳状态',
                suggestion='强烈建议休息，必要时可进行短暂午睡（15-20分钟效果最佳）',
                data_evidence={'fatigue_level': 'high', 'high_count': high_count, 'total': total},
            ))
        elif recent_level == FatigueLevel.MEDIUM:
            insights.append(Insight(
                category='fatigue',
                severity='warning',
                title='当前疲劳等级: 中',
                description=f'疲劳程度适中（累积{recent_cumulative:.0f}分），需警惕继续恶化',
                suggestion='保持警惕，建议适时远眺或闭目休息1-2分钟',
                data_evidence={'fatigue_level': 'medium'},
            ))

        return insights

    def _analyze_blink_rate(self, avg_blink_rate: float) -> List[Insight]:
        """分析眨眼频率（v4.10: 百分比对比）"""
        insights = []

        if avg_blink_rate > self.BLINK_HIGH:
            over_pct = int((avg_blink_rate - self.BLINK_NORMAL) / self.BLINK_NORMAL * 100)
            insights.append(Insight(
                category='fatigue',
                severity='warning',
                title='眨眼频率偏高',
                description=f'平均眨眼频率{avg_blink_rate:.1f}次/分，高于正常范围({self.BLINK_NORMAL:.0f}次/分)约{over_pct}%',
                suggestion='眨眼频率过高可能是疲劳信号，建议闭目休息片刻或使用人工泪液',
                data_evidence={'avg_blink_rate': avg_blink_rate},
            ))
        elif avg_blink_rate > self.BLINK_ELEVATED:
            over_pct = int((avg_blink_rate - self.BLINK_NORMAL) / self.BLINK_NORMAL * 100)
            insights.append(Insight(
                category='behavior',
                severity='info',
                title='眨眼频率略高',
                description=f'平均眨眼频率{avg_blink_rate:.1f}次/分，略高于{self.BLINK_NORMAL:.0f}次/分（+{over_pct}%）',
                suggestion='注意用眼卫生，保持屏幕距离适中，定时远眺',
                data_evidence={'avg_blink_rate': avg_blink_rate},
            ))

        return insights

    # ── v4.10: Tier 2 薄弱环节分析 ──

    def _find_weak_segments(self, focus_records: List[FocusRecord]) -> List[Insight]:
        """分析专注度各维度（眼部/头部/视线）的薄弱环节"""
        insights = []
        if len(focus_records) < 3:
            return insights

        # 计算基准时间（第一个记录的 window_start）
        t0 = focus_records[0].window_start

        def _elapsed_label(ts: float) -> str:
            """将时间戳转为 MM:SS 格式"""
            elapsed = max(0, int(ts - t0))
            m, s = elapsed // 60, elapsed % 60
            return f"{m}:{s:02d}"

        # 找出眼部得分最低的时段
        min_eye_idx = min(range(len(focus_records)), key=lambda i: focus_records[i].eye_score)
        min_eye = focus_records[min_eye_idx]
        if min_eye.eye_score < 60:
            label = _elapsed_label(min_eye.window_start)
            insights.append(Insight(
                category='behavior',
                severity='info',
                title='眼部状态偏低时段',
                description=f'{label}时段眼部得分仅{min_eye.eye_score:.0f}分（低于60），'
                           f'可能存在视线偏离或短暂闭眼',
                suggestion='注意保持眼睛注视屏幕，如需查看其他内容请减少转头幅度',
                data_evidence={'segment_time': label, 'eye_score': min_eye.eye_score},
            ))

        # 找出头部得分最低的时段
        min_head_idx = min(range(len(focus_records)), key=lambda i: focus_records[i].head_score)
        min_head = focus_records[min_head_idx]
        if min_head.head_score < 60:
            label = _elapsed_label(min_head.window_start)
            insights.append(Insight(
                category='behavior',
                severity='info',
                title='头部姿态变化时段',
                description=f'{label}时段头部姿态得分{min_head.head_score:.0f}分（低于60），'
                           f'可能有较大幅度的头部转动',
                suggestion='调整坐姿保持头部稳定，如需转头尽量减小幅度',
                data_evidence={'segment_time': label, 'head_score': min_head.head_score},
            ))

        # 找出眨眼频率最高的时段
        blink_rates = [r.blink_rate for r in focus_records]
        if max(blink_rates) > 25:
            max_blink_idx = blink_rates.index(max(blink_rates))
            max_blink_r = focus_records[max_blink_idx]
            label = _elapsed_label(max_blink_r.window_start)
            insights.append(Insight(
                category='fatigue',
                severity='info',
                title='眨眼频率高峰时段',
                description=f'{label}时段眨眼频率达{max_blink_r.blink_rate:.1f}次/分，'
                           f'显著高于正常水平',
                suggestion='该时段可能有眼部疲劳或干涩，建议注意用眼休息',
                data_evidence={'segment_time': label, 'blink_rate': max_blink_r.blink_rate},
            ))

        return insights

    # ── v4.10: Tier 3 历史对比 ──

    def _compare_with_history(
        self,
        avg_focus: float,
        avg_blink_rate: float,
        session_id: Optional[str] = None,
        session_start_time: Optional[float] = None,
    ) -> Optional[Insight]:
        """与历史会话数据进行对比分析"""
        if not self._db or not session_id:
            return None

        try:
            with self._db._get_cursor() as cur:
                # 查询历史平均专注度（排除当前会话）
                cur.execute("""
                    SELECT AVG(focus_score) FROM focus_records
                    WHERE session_id != ? AND focus_score IS NOT NULL
                """, (session_id,))
                row = cur.fetchone()
                hist_avg = round(row[0], 1) if row and row[0] is not None else None
                if hist_avg is None:
                    return None

                diff = avg_focus - hist_avg
                direction = "高于" if diff > 0 else ("低于" if diff < 0 else "持平于")
                pct = int(abs(diff) / hist_avg * 100) if hist_avg > 0 else 0

                # 查询历史平均眨眼率
                cur.execute("""
                    SELECT AVG(blink_rate) FROM focus_records
                    WHERE session_id != ? AND blink_rate IS NOT NULL
                """, (session_id,))
                blink_row = cur.fetchone()
                hist_blink = round(blink_row[0], 1) if blink_row and blink_row[0] is not None else None

                # 按时间段对比（如果提供了开始时间）
                time_period = None
                if session_start_time:
                    from datetime import datetime as dt_mod
                    hour = dt_mod.fromtimestamp(session_start_time).hour
                    if hour < 12:
                        time_period = '上午'
                    elif hour < 14:
                        time_period = '中午'
                    elif hour < 18:
                        time_period = '下午'
                    else:
                        time_period = '晚上'

                    cur.execute("""
                        SELECT AVG(fr.focus_score)
                        FROM focus_records fr
                        JOIN sessions s ON fr.session_id = s.session_id
                        WHERE s.session_id != ?
                        AND CAST(strftime('%H', s.start_time) AS INTEGER) BETWEEN ? AND ?
                        AND fr.focus_score IS NOT NULL
                    """, (session_id, hour - 2, hour + 2))
                    period_row = cur.fetchone()
                    period_avg = round(period_row[0], 1) if period_row and period_row[0] is not None else None
                else:
                    period_avg = None

                # 组装描述
                desc_parts = [f'本次专注度({avg_focus:.1f}){direction}历史平均({hist_avg:.1f})，{"高" if diff > 0 else "低"}了{pct}%']
                if hist_blink is not None:
                    blink_diff = avg_blink_rate - hist_blink
                    blink_dir = "高于" if blink_diff > 0 else ("低于" if blink_diff < 0 else "持平")
                    desc_parts.append(f'眨眼频率({avg_blink_rate:.1f}){blink_dir}历史({hist_blink:.1f})')
                if period_avg is not None and time_period:
                    diff_period = avg_focus - period_avg
                    period_dir = "高于" if diff_period > 0 else ("低于" if diff_period < 0 else "持平于")
                    desc_parts.append(f'{time_period}时段专注度{period_dir}同时间段历史({period_avg:.1f})')

                # 建议文本
                if diff < -10:
                    suggestion = '本次专注度明显低于历史水平，建议检视是否存在干扰因素（睡眠不足、环境影响等）'
                elif diff > 10:
                    suggestion = '本次专注度显著高于历史水平，继续保持当前工作状态'
                else:
                    suggestion = '与历史表现基本一致，保持当前节奏即可'

                if time_period and period_avg and avg_focus > period_avg + 5:
                    suggestion = f'你在{time_period}时段表现较好，建议将重要工作安排在此时间段'

                return Insight(
                    category='recommendation',
                    severity='info',
                    title='与历史表现对比',
                    description='；'.join(desc_parts),
                    suggestion=suggestion,
                    data_evidence={
                        'hist_avg': hist_avg,
                        'diff': round(diff, 1),
                        'hist_blink': hist_blink,
                        'period_avg': period_avg,
                        'time_period': time_period,
                    },
                )

        except Exception as e:
            logger.warning("历史对比分析失败: %s", e)
            return None

    def _generate_recommendations(
        self,
        avg_focus: float,
        avg_blink_rate: float,
        session_duration: float,
        focus_records: List[FocusRecord],
    ) -> List[Insight]:
        """生成综合建议（v4.29: 新增时段/波动/多层级建议）"""
        insights = []
        duration_minutes = session_duration / 60.0

        # ── 1. 工作时长建议 ──
        if duration_minutes > 60:
            remain = duration_minutes - 45
            insights.append(Insight(
                category='recommendation',
                severity='info',
                title='连续工作时长较长',
                description=f'已连续工作{int(duration_minutes)}分钟，超过推荐高效周期',
                suggestion=f'建议每45-50分钟休息5-10分钟，超时{int(remain)}分钟，尽快休息',
                data_evidence={'duration_minutes': duration_minutes},
            ))

        # ── 2. 疲劳后恢复建议 ──
        if duration_minutes > 90 and avg_focus < self.FOCUS_GOOD:
            insights.append(Insight(
                category='recommendation',
                severity='warning',
                title='长时间工作后专注下降',
                description=f'连续工作{int(duration_minutes)}分钟且专注度{avg_focus:.0f}分，已达效率瓶颈',
                suggestion='建议10-15分钟彻底休息（起身走动+远眺+补水），之后效率明显回升',
                data_evidence={'duration_minutes': duration_minutes, 'avg_focus': avg_focus},
            ))

        # ── 3. 专注度分级建议 ──
        if avg_focus >= self.FOCUS_GOOD:
            insights.append(Insight(
                category='recommendation',
                severity='info',
                title='专注状态良好',
                description=f'平均专注度{avg_focus:.1f}，整体表现优秀',
                suggestion='继续保持当前节奏。①每50分钟微休息2分钟远眺；②重要任务优先安排在高效时段',
                data_evidence={'avg_focus': avg_focus},
            ))
        elif avg_focus >= self.FOCUS_WARNING:
            insights.append(Insight(
                category='recommendation',
                severity='info',
                title='专注度一般，有提升空间',
                description=f'平均专注度{avg_focus:.1f}（良好线{self.FOCUS_GOOD:.0f}），尚有提升空间',
                suggestion='提升方法：①减少多任务并行；②使用番茄工作法25+5；③清理桌面减少视觉干扰；④关闭非必要通知',
                data_evidence={'avg_focus': avg_focus},
            ))
        elif avg_focus > 0:
            insights.append(Insight(
                category='recommendation',
                severity='warning',
                title='专注度偏低，需系统改善',
                description=f'平均专注度{avg_focus:.0f}分，低于警戒线{self.FOCUS_WARNING:.0f}分',
                suggestion='改善路径：①排查睡眠质量（建议7-8小时）；②检查环境干扰（噪音/温度/照明）；'
                          f'③拆分任务为25分钟小单元；④每完成一个单元奖励短休',
                data_evidence={'avg_focus': avg_focus},
            ))

        # ── 4. 眼部健康建议 ──
        if avg_blink_rate < self.BLINK_NORMAL * 0.8:
            low_pct = int((self.BLINK_NORMAL - avg_blink_rate) / self.BLINK_NORMAL * 100)
            insights.append(Insight(
                category='recommendation',
                severity='warning',
                title='眨眼频率偏低，注意用眼健康',
                description=f'眨眼频率{avg_blink_rate:.1f}次/分，低于正常约{low_pct}%',
                suggestion='护眼建议：①有意识地多眨眼（每20秒眨眼1次）；②20-20-20法则：每20分钟看20英尺外20秒；'
                          f'③使用人工泪液润滑；④屏幕亮度与环境光协调；⑤保持50-70cm用眼距离',
                data_evidence={'avg_blink_rate': avg_blink_rate},
            ))

        # ── 5. v4.29: 专注高峰时段分析 ──
        if len(focus_records) >= 6:
            third = max(1, len(focus_records) // 3)
            segs = [
                ("前期", self._calc_seg_avg(focus_records[:third])),
                ("中期", self._calc_seg_avg(focus_records[third:2*third]) if len(focus_records) >= 2*third else None),
                ("后期", self._calc_seg_avg(focus_records[-third:])),
            ]
            valid = [(l, v) for l, v in segs if v is not None]
            if valid:
                best_label, best_val = max(valid, key=lambda x: x[1])
                worst_label, worst_val = min(valid, key=lambda x: x[1])
                if best_val - worst_val > 10:
                    insights.append(Insight(
                        category='recommendation',
                        severity='info',
                        title='专注高峰时段分析',
                        description=f'{best_label}专注度{best_val:.0f}分最高，{worst_label}{worst_val:.0f}分最低，差距{best_val-worst_val:.0f}分',
                        suggestion='建议将高难度创造性工作安排在专注高峰时段，低难度事务性工作安排在低谷时段。'
                                  f'若{worst_label}专注下降，可提前安排休息或切换简单任务',
                        data_evidence={'best_segment': best_label, 'best_score': best_val,
                                      'worst_segment': worst_label, 'worst_score': worst_val},
                    ))

        # ── 6. v4.29: 波动稳定性评估 ──
        if len(focus_records) >= 5:
            scores = [r.focus_score for r in focus_records if r.focus_score is not None]
            if scores:
                std = float(np.std(scores))
                if std > 18:
                    insights.append(Insight(
                        category='recommendation',
                        severity='info',
                        title='专注度波动较大，建议稳定节奏',
                        description=f'专注度标准差{std:.1f}分，波动较大（稳定阈值18分）',
                        suggestion='稳定策略：①固定每日工作时段培养生物钟；②任务前做2分钟正念呼吸平静心态；'
                                  f'③使用白噪音掩盖环境干扰；④每次只专注一个任务',
                        data_evidence={'std': std},
                    ))

        return insights

    # ── v4.29: 辅助方法 ──

    def _calc_seg_avg(self, records: List[FocusRecord]) -> float:
        """计算记录段的平均专注度"""
        scores = [r.focus_score for r in records if r.focus_score is not None]
        return float(np.mean(scores)) if scores else 0.0

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


def create_insights_engine(db=None) -> InsightsEngine:
    """工厂函数：创建建议引擎"""
    return InsightsEngine(db=db)

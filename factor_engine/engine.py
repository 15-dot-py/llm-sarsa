from dataclasses import dataclass, asdict
import hashlib
import json
import math
import numpy as np
from reward import RewardProfile, REWARD_KEYS

@dataclass(frozen=True)
class Factor:
    name: str
    category: str
    min_value: float
    max_value: float
    description: str
    enabled: bool = True
    normalization_method: str = 'minmax_clip'
    weight: float = 1.
    lag: int = 0
    controllable: bool = False
    source: str = 'CSV / observation'

    def normalize(self, value):
        if self.max_value <= self.min_value:
            raise ValueError('因子范围必须递增')
        if value is None or not math.isfinite(float(value)):
            return 0., False
        x = (float(value)-self.min_value)/(self.max_value-self.min_value)
        return float(np.clip(x, 0, 1)*self.weight) if self.enabled else 0., self.enabled

CORE = [
    Factor('roi','performance',-1,3,'营销 ROI（利润 / 营销投入）'),
    Factor('profit_margin','performance',-.5,.4,'营销贡献利润率，非会计净利率'),
    Factor('conversion_rate','performance',0,.12,'订单 / 点击'),
    Factor('ctr','performance',0,.1,'点击 / 曝光'),
    Factor('repeat_purchase_rate','performance',0,.8,'回流客户占比代理，非真实跨期复购率'),
    Factor('gmv_growth','performance',-.5,.5,'相邻观察窗口收入增长'),
    Factor('inventory_turnover','performance',0,.3,'观察期销量 / 期初库存'),
    Factor('cac','penalty',0,200,'广告费 / 新客，综合 CAC 代理'),
    Factor('return_rate','penalty',0,.2,'退货件数 / 销量'),
    Factor('promotion_cost_ratio','penalty',0,.4,'额外促销成本 / 收入'),
    Factor('inventory_pressure','penalty',0,1,'库存覆盖天数 / 60，截断至 1'),
    Factor('inventory_level','business',0,100000,'渠道分仓库存合计'),
    Factor('price_level','business',10,150,'平均成交价格',controllable=True),
    Factor('discount','business',0,.5,'标价折扣率；额外促销费不含此降价',controllable=True),
    Factor('advertising_budget','business',0,30000,'每日广告预算',controllable=True),
    Factor('new_customer_ratio','business',0,1,'新客 / 新客与回流客户总数'),
    Factor('douyin_share','channel',0,1,'抖音广告预算份额',controllable=True),
    Factor('xiaohongshu_share','channel',0,1,'小红书广告预算份额',controllable=True),
    Factor('private_share','channel',0,1,'私域预算份额',controllable=True),
    Factor('douyin_cac','channel',0,250,'抖音新客广告 CAC'),
    Factor('douyin_roi','channel',-1,3,'抖音营销 ROI'),
    Factor('seasonality','external',.5,1.5,'季节需求乘数',source='观察 / 仿真假设'),
    Factor('holiday_index','external',0,1,'活动窗口强度',source='用户明确描述 / 仿真日历'),
    Factor('competitor_intensity','external',0,1,'竞品压力信号',source='用户明确描述 / 仿真假设'),
    Factor('platform_traffic_change','external',-.5,.5,'平台流量环比变化',source='观察 / 仿真假设'),
    Factor('market_demand_index','external',.5,1.5,'需求指数',source='观察 / 仿真假设'),
    Factor('sunk_cost_score','bias',0,1,'低 ROI 仍增加预算的历史信号',source='Bias Engine'),
    Factor('loss_aversion_score','bias',0,1,'持续负利润且预算不收缩的历史信号',source='Bias Engine'),
    Factor('overconfidence_score','bias',0,1,'预测反复高于实际的偏差信号',source='Bias Engine'),
    Factor('recency_bias_score','bias',0,1,'短窗口波动伴随预算反复调整',source='Bias Engine'),
]
CANDIDATES = [
    Factor('customer_lifetime_value','candidate',0,5000,'需要客户级追踪',enabled=False),
    Factor('herding_score','candidate',0,1,'需要竞品跟随原因记录',enabled=False,source='Bias Engine'),
    Factor('anchoring_score','candidate',0,1,'需要历史锚定原因记录',enabled=False,source='Bias Engine'),
    Factor('refund_rate','candidate',0,.3,'与退货率不同，需要退款记录',enabled=False),
    Factor('stockout_risk','candidate',0,1,'补货提前期缺失时不能可靠计算',enabled=False),
    Factor('competitor_price','candidate',0,150,'需要可比竞品价格',enabled=False),
]

class FactorRegistry:
    def __init__(self, factors=None):
        self.factors = list(factors or CORE)
        if len({x.name for x in self.factors}) != len(self.factors):
            raise ValueError('因子名称不能重复')
    def register(self, factor: Factor):
        if any(x.name == factor.name for x in self.factors):
            raise ValueError('因子已注册')
        self.factors.append(factor)
    @property
    def signature(self):
        return hashlib.sha256(json.dumps([asdict(x) for x in self.factors],sort_keys=True).encode()).hexdigest()[:12]
    def list(self):
        return [asdict(x) for x in self.factors + CANDIDATES]

class FactorEngine:
    def __init__(self, registry=None):
        self.registry = registry or FactorRegistry()
    @property
    def state_dim(self):
        return 2*len(self.registry.factors) + len(REWARD_KEYS)
    def build(self, metrics: dict, profile: RewardProfile, semantic=None, bias=None):
        values, provenance = dict(metrics), {k: '经营数据 / 指标公式' for k in metrics}
        # Qualitative semantic evidence enters only unobserved EXTERNAL features.
        # Inventory/CAC claims are recorded but never replace observed business metrics.
        allowed = {'holiday_index','competitor_intensity','market_demand_index','platform_traffic_change','seasonality'}
        for k,v in (semantic or {}).items():
            if k in allowed and values.get(k) is None and v is not None:
                values[k], provenance[k] = v, '语义信号（未实测）'
        for k,v in (bias or {}).items():
            values[k], provenance[k] = v, 'Bias Engine 历史规则'
        numbers, present, details = [], [], []
        for f in self.registry.factors:
            raw = values.get(f.name)
            norm, available = f.normalize(raw)
            numbers.append(norm); present.append(float(available))
            details.append({**asdict(f),'raw': raw,'normalized': norm,'available': available,
                            'provenance': provenance.get(f.name,'缺失：数值 0 与缺失标记同时进入网络'),
                            'clipped': bool(available and (raw<f.min_value or raw>f.max_value))})
        state = np.asarray(numbers+present+list(profile.normalized_weights),dtype=np.float32)
        return {'vector': state.tolist(), 'factors': details,'signature': self.registry.signature,
                'state_dim': len(state), 'layout': '30 normalized factors + 30 presence masks + 12 objective weights',
                'coverage': float(np.mean(present))}

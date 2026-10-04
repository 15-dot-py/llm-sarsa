"""Public explanation of the implemented reward; ranges and weights use engine constants."""
from reward.engine import REWARD_KEYS, BOUNDS, PROFILES
from config.settings import PROFILE_LABELS

DETAILS = {
    'profit_margin': ('营销贡献利润率', '营销贡献利润 / 收入', '利润扣除商品成本、广告费、额外促销费和退货损失；未包含完整会计费用。'),
    'roi': ('营销 ROI', '营销贡献利润 /（广告费 + 额外促销费）', '不是收入 / 广告费；后者是 ROAS。'),
    'conversion_rate': ('转化率', '订单数 / 点击数', '没有点击时为缺失。'),
    'repeat_purchase_rate': ('回流客户占比', '回流客户数 /（新客数 + 回流客户数）', '缺少客户级追踪，是复购代理指标。'),
    'inventory_turnover': ('库存周转', '销量 /（剩余库存 + 销量）', '观察期库存消化比例，不是财报中的年度周转次数。'),
    'gmv_growth': ('收入增长', '本期收入 / max(上期收入, 1) − 1', 'CSV 按相邻观察日计算；首个观察日缺失。'),
    'new_customer_ratio': ('新客占比', '新客数 /（新客数 + 回流客户数）', '与回流客户占比互补，按经营目标取舍。'),
    'cac': ('广告获客成本', '广告费 / 新客数', '仅为广告 CAC 代理，不包含全部客户获取成本。'),
    'return_rate': ('退货率', '退货件数 / 销量', '退货与退款是不同口径。'),
    'promotion_cost_ratio': ('额外促销成本率', '额外促销费 / max(收入, 1)', '折扣已反映在成交收入中，不在这里重复扣除。'),
    'inventory_pressure': ('库存压力', 'clip(剩余库存 / max(销量, 1) / 60, 0, 1)', '以当前销量估计库存覆盖压力，60 为原型设定。'),
    'volatility': ('收入波动', 'CSV：最近至多 7 天收入的标准差 / max(均值, 1)', '单轮实际反馈和仿真使用绝对收入环比变化代理；不同来源口径不完全一致，不直接比较回报。'),
}

def reward_catalog():
    return {
        'version': 'reward-v1',
        'normalization': 'z = clip((x − lower) / (upper − lower), 0, 1)',
        'formula': 'R = Σ收益(w × z) − Σ惩罚(w × z)',
        'weight_rule': '12 项非负权重统一除以总和；缺失项贡献为 0，不重新分配其权重。',
        'boundary': '综合回报是无量纲偏好分数，不是预测利润。标准化范围和默认权重是原型设定，未用三只松鼠内部数据校准。',
        'factors': [
            {'name': name, 'label': DETAILS[name][0], 'formula': DETAILS[name][1],
             'note': DETAILS[name][2], 'sign': 1 if i < 7 else -1,
             'lower': BOUNDS[i][0], 'upper': BOUNDS[i][1]}
            for i, name in enumerate(REWARD_KEYS)
        ],
        'profiles': [
            {**profile.to_dict(), 'label': PROFILE_LABELS[name],
             'raw_weights': dict(zip(REWARD_KEYS, profile.weights))}
            for name, profile in PROFILES.items()
        ],
    }

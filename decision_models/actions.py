from dataclasses import dataclass, asdict
import copy
import numpy as np

CHANNELS = ['抖音','小红书','淘宝','搜索广告','私域']

@dataclass(frozen=True)
class Action:
    name: str
    label: str
    operation: str
    channel: str | None = None
    amount: float = 0.

ACTIONS = [
    Action('increase_douyin_budget','抖音预算增加 10%','budget','抖音',.1),
    Action('decrease_douyin_budget','抖音预算减少 10%','budget','抖音',-.1),
    Action('increase_xiaohongshu_budget','小红书预算增加 10%','budget','小红书',.1),
    Action('decrease_xiaohongshu_budget','小红书预算减少 10%','budget','小红书',-.1),
    Action('increase_search_ads','搜索广告增加 10%','budget','搜索广告',.1),
    Action('decrease_search_ads','搜索广告减少 10%','budget','搜索广告',-.1),
    Action('increase_coupon','额外优惠补贴增加 1 个百分点','coupon',amount=.01),
    Action('decrease_coupon','额外优惠补贴减少 1 个百分点','coupon',amount=-.01),
    Action('increase_discount','折扣增加 2 个百分点','discount',amount=.02),
    Action('decrease_discount','折扣减少 2 个百分点','discount',amount=-.02),
    Action('increase_price','标价提高 3%','price',amount=.03),
    Action('decrease_price','标价降低 3%','price',amount=-.03),
    Action('increase_retention_marketing','私域留存投入增加 10%','budget','私域',.1),
    Action('increase_new_customer_acquisition','淘宝新客投入增加 10%','budget','淘宝',.1),
    Action('increase_private_domain_marketing','向私域转移 5% 广告预算','transfer','私域',.05),
    Action('reduce_low_roi_channel','最低 ROI 渠道预算减少 15%','worst',amount=-.15),
    Action('clear_inventory_promotion','库存消化：额外增加 4% 折扣','discount',amount=.04),
    Action('keep_strategy','保持当前策略','keep'),
]

@dataclass
class ActionConstraints:
    max_daily_budget: float = 18000.
    min_gross_margin: float = .15
    min_price: float = 20.
    max_discount: float = .35
    clearance_min_inventory: float = 1000.
    stopped_channels: tuple = ()
    prohibited_promotions: bool = False

def apply_action(context: dict, index: int):
    c = copy.deepcopy(context); a = ACTIONS[index]
    budgets = c.setdefault('budgets', {k:0. for k in CHANNELS})
    if a.operation == 'budget':
        budgets[a.channel] = budgets.get(a.channel,0)*(1+a.amount)
    elif a.operation == 'transfer':
        take = sum(v for k,v in budgets.items() if k!='私域')*a.amount
        for k in list(budgets):
            if k!='私域': budgets[k] *= 1-a.amount
        budgets['私域'] = budgets.get('私域',0)+take
    elif a.operation == 'worst':
        active = [k for k,v in budgets.items() if v>0]
        if active:
            worst = min(active,key=lambda k:c.get('channel_roi',{}).get(k,0))
            budgets[worst] *= 1+a.amount
    elif a.operation == 'coupon': c['coupon'] = c.get('coupon',.01)+a.amount
    elif a.operation == 'discount': c['discount'] = c.get('discount',.08)+a.amount
    elif a.operation == 'price': c['price'] = c.get('price',55)*(1+a.amount)
    c['daily_budget'] = sum(budgets.values())
    return c

def action_mask(context: dict, constraints=None):
    rules = constraints or ActionConstraints()
    mask, reasons = np.ones(len(ACTIONS),dtype=bool), {}
    for i,a in enumerate(ACTIONS):
        c = apply_action(context,i); why = []
        if c['daily_budget']>rules.max_daily_budget+1e-6: why.append('超过每日广告预算上限')
        if a.amount>0 and a.channel in rules.stopped_channels: why.append('渠道已停用')
        if a.channel and a.operation == 'budget' and context.get('budgets',{}).get(a.channel,0)<=0:
            why.append('该渠道没有可调整预算')
        if a.name == 'reduce_low_roi_channel' and not any(v>0 for v in context.get('budgets',{}).values()):
            why.append('没有活跃广告渠道')
        if a.name == 'clear_inventory_promotion' and context.get('inventory',0)<rules.clearance_min_inventory:
            why.append('库存低于清仓阈值')
        price=c.get('price',55)*(1-c.get('discount',0)-c.get('coupon',0))
        if price<rules.min_price: why.append('低于成交价格底线')
        if (price-c.get('unit_cost',30))/max(price,1)<rules.min_gross_margin: why.append('低于毛利底线')
        if not 0<=c.get('discount',0)<=rules.max_discount: why.append('折扣超出允许范围')
        if not 0<=c.get('coupon',0)<=.15: why.append('补贴超出允许范围')
        if rules.prohibited_promotions and a.operation in {'coupon','discount'} and a.amount>0:
            why.append('当前阶段禁止新增促销')
        if why: mask[i]=False; reasons[a.name]=why
    return mask,reasons

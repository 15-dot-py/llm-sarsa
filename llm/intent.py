"""Conservative question intent and explicit business constraints, not action selection."""
import re
from dataclasses import replace
from decision_models.actions import CHANNELS

def marketing_question(question):
    return bool(re.search(r'营销|经营|销售|销量|获客|客户|老客|新客|复购|回流|留存|利润|毛利|库存|清仓|促销|优惠|折扣|定价|价格|投放|预算|渠道|电商|淘宝|抖音|小红书|私域|广告|竞品|竞争|需求|流量|订单|退货|坚果|零食|松鼠|ROI|CAC|ROAS|marketing|budget|conversion',question,re.I))

def infer_goal(question):
    # Expressed goals take priority over a mere mention of a business metric.
    choices=[('inventory_clearance',r'清库存|清仓|消化库存|去库存|库存消化'),
             ('acquisition_efficiency',r'控制.*获客成本|降低.*获客成本|获客效率|获客成本.*(高|上升|下降|降低)|CAC'),
             ('customer_retention',r'提高.*复购|提升.*复购|客户留存|老客留存|维护老客|复购率'),
             ('new_customer_acquisition',r'拓展新客|增加新客|拉新|新客拓展'),
             ('profit_maximization',r'提高.*利润|改善.*利润|提升.*利润|利润优先|减少亏损|扭亏|盈利'),
             ('growth_maximization',r'提高.*销售|提升.*销售|提高.*销量|提升.*销量|销售增长|销量增长|扩大销售')]
    for name,pattern in choices:
        if re.search(pattern,question,re.I): return name
    if re.search(r'库存.*(积压|多|高)|积压',question): return 'inventory_clearance'
    if re.search(r'老客|回流|复购|留存',question): return 'customer_retention'
    if re.search(r'利润|毛利|亏损',question): return 'profit_maximization'
    return 'balanced_growth'

def explicit_constraints(question,constraints):
    applied=[];stopped=set(constraints.stopped_channels)
    for channel in CHANNELS:
        pattern=rf'(?:禁止|不要|不再|不能|停止|暂停|停用|停投)(?:增加|加大)?{re.escape(channel)}(?:的)?(?:预算|投放|投入|广告)?|{re.escape(channel)}(?:预算|投放|投入)?(?:暂停|停止|停用|停投|不再增加|不要增加|不得增加)'
        matches=list(re.finditer(pattern,question))
        if any(not re.search(r'不要|无需|不用|禁止|不能',question[max(0,m.start()-4):m.start()]) for m in matches):
            stopped.add(channel);applied.append(f'不增加{channel}投入')
    found=re.search(r'(?:每日|日)?(?:广告)?预算(?:上限|不超过|最多|不得超过|不能超过|限制为)[：:\s]*(\d+(?:\.\d+)?)\s*(万)?\s*元?',question)
    budget=constraints.max_daily_budget
    if found:
        value=float(found[1])*(10000 if found[2] else 1)
        if value<=1e6:
            budget=min(budget,value);applied.append(f'每日广告预算不超过 {budget:g} 元')
    prohibited=constraints.prohibited_promotions or bool(re.search(r'禁止(?:新增)?促销|不要(?:新增|增加)?(?:促销|折扣|补贴)|不允许(?:新增|增加)?促销',question))
    if prohibited and not constraints.prohibited_promotions: applied.append('禁止新增促销')
    return replace(constraints,max_daily_budget=budget,stopped_channels=tuple(ch for ch in CHANNELS if ch in stopped),
                   prohibited_promotions=prohibited),applied

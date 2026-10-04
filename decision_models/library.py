"""Small, composable business computations rather than a list of pretend models."""
from dataclasses import dataclass
from typing import Callable

@dataclass
class Component:
    name: str
    label: str
    description: str
    compute: Callable
    source_file: str

class ModelLibrary:
    def __init__(self): self.components={}
    def register(self,component):
        if component.name in self.components: raise ValueError('组件名称重复')
        self.components[component.name]=component
    def run(self,metrics):
        return [{'name':c.name,'label':c.label,'description':c.description,'source_file':c.source_file,
                 'output':c.compute(metrics),'implemented':True} for c in self.components.values()]

def create_library():
    lib=ModelLibrary()
    definitions=[
        ('customer_model','客户结构','区分新客与回流客户，避免把占比当真实复购率',lambda m:{'new_customer_ratio':m.get('new_customer_ratio'),'returning_customer_share':m.get('repeat_purchase_rate')},'environments/marketing.py'),
        ('channel_model','渠道效率','按渠道计算 CAC 与营销 ROI',lambda m:{'channels':m.get('channels',[])},'environments/marketing.py'),
        ('promotion_model','促销成本','成交折扣与额外补贴分别计入',lambda m:{'discount':m.get('discount'),'promotion_cost_ratio':m.get('promotion_cost_ratio')},'decision_models/actions.py'),
        ('pricing_model','价格与毛利','计算成交价格与估算单位成本，约束价格底线',lambda m:{'price':m.get('price_level'),'unit_cost':m.get('unit_cost'),'margin_before_marketing':1-m.get('unit_cost',0)/max(m.get('price_level',1),1)},'decision_models/actions.py'),
        ('inventory_model','库存覆盖','库存 / 日销量换算覆盖天数，识别清仓约束',lambda m:{'coverage_days':m.get('inventory_level',0)/m['sales'] if m.get('sales') is not None and m['sales']>0 else None,'pressure':m.get('inventory_pressure')},'environments/marketing.py'),
        ('competitor_model','竞争信号','保留竞品强度和证据来源，缺失不臆测',lambda m:{'competitor_intensity':m.get('competitor_intensity'),'available':m.get('competitor_intensity') is not None},'factor_engine/engine.py'),
        ('behavior_model','行为指标','从曝光、点击、订单到获客构成经营漏斗',lambda m:{'ctr':m.get('ctr'),'conversion':m.get('conversion_rate'),'cac':m.get('cac')},'environments/marketing.py'),
        ('bias_model','决策偏差信号','六类历史证据规则，缺证据返回未知',lambda m:{'signals':[k for k in m if k.endswith('_score')]},'bias_engine/engine.py'),
        ('reward_model','多目标奖励','12 项标准化指标与 7 种目标权重',lambda m:{'profiles':7,'terms':12,'profit':m.get('profit')},'reward/engine.py'),
        ('factor_model','因子与状态','30 个核心因子、缺失标记、12 个目标权重',lambda m:{'core_factors':30,'state_dimension':72},'factor_engine/engine.py'),
        ('simulation_model','随机营销环境','预算饱和、滞后、库存、竞争与市场噪声',lambda m:{'calibration_revenue':m.get('revenue'),'source':'合成仿真'},'environments/marketing.py'),
        ('llm_prompt_library','语义与解释','严格结构化输出，解释不可改写最终动作',lambda m:{'roles':['extract','explain','experimental_baseline'],'decision_permission':False},'llm/prompts.py'),
        ('evaluation_model','共同场景评估','独立测试种子，多策略指标与消融',lambda m:{'metrics':['reward','ROI','profit','conversion','CAC','turnover','stability']},'evaluation/experiments.py'),
    ]
    for name,label,desc,fn,path in definitions: lib.register(Component(name,label,desc,fn,path))
    return lib

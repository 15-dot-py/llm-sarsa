import json
import os
import re
import threading
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict
from .prompts import EXTRACTION_PROMPT, EXPLANATION_PROMPT, BASELINE_PROMPT

Level=Literal['high','medium','low','unknown']
class Signals(BaseModel):
    model_config=ConfigDict(extra='forbid')
    summary: str
    inventory_pressure: Level
    douyin_cac: Level
    repeat_purchase: Level
    holiday_index: float | None
    competitor_intensity: float | None
    platform_traffic_change: float | None
    market_demand_index: float | None
    evidence: list[str]
    unknowns: list[str]

class Explanation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    selected_action: str
    summary: str
    reasons: list[str]
    watch_metrics: list[str]
    limitations: list[str]

class BaselineAction(BaseModel):
    model_config=ConfigDict(extra='forbid')
    selected_action: str
    reason: str

class LLMService:
    def __init__(self):
        self._lock=threading.Lock(); self._day=None; self._calls=0
    def _settings(self):
        provider=os.getenv('LLM_PROVIDER','auto').strip().lower()
        if provider=='auto': provider='deepseek' if os.getenv('DEEPSEEK_API_KEY') else 'openai'
        if provider=='deepseek':
            return {'provider':provider,'api_key':os.getenv('DEEPSEEK_API_KEY',''),
                    'model':os.getenv('DEEPSEEK_MODEL','deepseek-flash'),'base_url':'https://api.deepseek.com'}
        return {'provider':provider,'api_key':os.getenv('OPENAI_API_KEY','') if provider=='openai' else '',
                'model':os.getenv('OPENAI_MODEL','gpt-4.1-mini'),'base_url':None}
    @property
    def available(self):
        return bool(self._settings()['api_key']) and os.getenv('LLM_ENABLED','true').lower()=='true'
    def status(self):
        settings=self._settings()
        return {'available':self.available,'provider':settings['provider'],'model':settings['model'],
                'mode':('DeepSeek JSON + 本地结构校验' if settings['provider']=='deepseek' else 'OpenAI Structured Outputs') if self.available else '无密钥：规则解析与模板解释',
                'calls_today':self._calls,'daily_limit':int(os.getenv('LLM_DAILY_CALL_LIMIT','120'))}
    def _call(self,schema,prompt,payload):
        if not self.available: raise RuntimeError('LLM 未配置')
        with self._lock:
            today=date.today()
            if today!=self._day: self._calls=0; self._day=today
            if self._calls>=int(os.getenv('LLM_DAILY_CALL_LIMIT','120')): raise RuntimeError('LLM 当日调用额度已用完')
            self._calls+=1
        from openai import OpenAI
        settings=self._settings()
        client=OpenAI(api_key=settings['api_key'],base_url=settings['base_url'],timeout=float(os.getenv('OPENAI_TIMEOUT','20')),max_retries=0)
        if settings['provider']=='deepseek':
            examples={
                'Signals':{'summary':'仅提取问题中的信息','inventory_pressure':'unknown','douyin_cac':'unknown','repeat_purchase':'unknown','holiday_index':None,'competitor_intensity':None,'platform_traffic_change':None,'market_demand_index':None,'evidence':[],'unknowns':['未提供的信息']},
                'Explanation':{'selected_action':payload.get('action_name','keep_strategy'),'summary':'简要解释已选动作','reasons':[],'watch_metrics':[],'limitations':[]},
                'BaselineAction':{'selected_action':(payload.get('legal_actions') or ['keep_strategy'])[0],'reason':'基于提供的指标'},
            }
            instructions=prompt+'\n仅输出一个 JSON 对象。保留全部必需字段，遵守以下 JSON Schema，不输出 markdown：\n'+json.dumps(schema.model_json_schema(),ensure_ascii=False)+'\nJSON 格式示例：\n'+json.dumps(examples[schema.__name__],ensure_ascii=False)
            result=client.chat.completions.create(model=settings['model'],
                messages=[{'role':'system','content':instructions},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],
                response_format={'type':'json_object'},max_tokens=1600,extra_body={'thinking':{'type':'disabled'}})
            if not result.choices or result.choices[0].finish_reason!='stop': raise RuntimeError('DeepSeek 输出未完整结束')
            content=result.choices[0].message.content
            if not content: raise RuntimeError('DeepSeek 未返回 JSON 内容')
            return schema.model_validate_json(content,strict=True)
        result=client.responses.parse(model=settings['model'],
                 input=[{'role':'system','content':prompt},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],
                 text_format=schema,max_output_tokens=1600,store=False)
        if result.output_parsed is None: raise RuntimeError('LLM 未返回有效结构化输出')
        return result.output_parsed

    def extract(self,question,company_evidence=None):
        reason='API 密钥未配置'
        if self.available:
            try:
                s=self._call(Signals,EXTRACTION_PROMPT,{'question':question,'company_background':company_evidence or []})
                # External ranges are deterministic semantic mapping ranges, not measured data.
                d=s.model_dump()
                for key,lo,hi in [('holiday_index',0,1),('competitor_intensity',0,1),('platform_traffic_change',-.5,.5),('market_demand_index',.5,1.5)]:
                    if d[key] is not None and not lo<=d[key]<=hi: raise ValueError('语义信号越界')
                return {'source':'LLM','model':self._settings()['model'],'provider':self._settings()['provider'],'signals':d,'fallback_reason':None}
            except Exception as exc:
                reason=f'结构化调用失败（{type(exc).__name__}），未采用失败输出'
        high=bool(re.search('库存.*(高|很多|积压|严重)|积压',question))
        cac=bool(re.search('(抖音|获客).*(高|贵|上升|越来越)',question))
        repeat=bool(re.search('(复购|老客|回流).*(好|不错|稳定)',question))
        holiday=bool(re.search('节日|大促|双十一|春节|618|国庆',question))
        competitor=bool(re.search('竞争.*(强|激烈)|竞品.*(降价|压力)',question))
        traffic=-.2 if re.search('流量.*(下降|减少)',question) else None
        demand=1.2 if re.search('需求.*(增长|上涨)',question) else None
        signals={'summary':question[:180],'inventory_pressure':'high' if high else 'unknown',
                 'douyin_cac':'high' if cac else 'unknown','repeat_purchase':'high' if repeat else 'unknown',
                 'holiday_index':1. if holiday else None,'competitor_intensity':.8 if competitor else None,
                 'platform_traffic_change':traffic,'market_demand_index':demand,
                 'evidence':[question[:200]],'unknowns':['语义等级是规则匹配，未调用 LLM','未实测外部信号']}
        return {'source':'Rule parser','model':None,'signals':signals,'fallback_reason':reason}

    def explain(self,record):
        reason='API 密钥未配置'
        if self.available:
            try:
                payload={k:record[k] for k in ['action_name','action_label','q_selected','expected_reward','metrics','bias','mask_reasons']}
                payload['company_background']=record.get('company_evidence',[])
                x=self._call(Explanation,EXPLANATION_PROMPT,payload)
                if x.selected_action!=record['action_name']: raise ValueError('LLM 返回动作不匹配，拒绝采用')
                return {**x.model_dump(),'source':'LLM','fallback_reason':None,'model':self._settings()['model'],'provider':self._settings()['provider']}
            except Exception as exc: reason=f'解释调用失败（{type(exc).__name__}），使用可核查模板'
        m=record['metrics']; roi=m.get('roi'); cac=m.get('cac')
        return {'selected_action':record['action_name'],'source':'Template','model':None,'fallback_reason':reason,
                'summary':f"建议{record['action_label']}。执行后对照获客成本、利润与库存变化，再决定下一轮调整。",
                'reasons':[f"当前营销 ROI 为 {roi:.2f}。" if roi is not None else '营销 ROI 数据不足。',
                           f"获客广告 CAC 为 ¥{cac:.2f}。" if cac is not None else '新客不足，CAC 无法计算。',
                           f"当前分仓库存为 {m['inventory_level']:,.0f} 件；留意库存消化与预算消耗。" if m.get('inventory_level') is not None else '缺少分仓库存记录，需补充后评估。'],
                'watch_metrics':['营销贡献利润','获客成本与新客数','库存覆盖天数'],
                'limitations':['模板只复述模型和指标，不能证明该动作的因果收益','模型在合成环境预训练，实际执行前需业务审核']}

    def baseline_action(self,metrics,legal_names):
        x=self._call(BaselineAction,BASELINE_PROMPT,{'metrics':metrics,'legal_actions':legal_names})
        if x.selected_action not in legal_names: raise ValueError('LLM-only 返回非法动作')
        return x.selected_action

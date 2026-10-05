import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, PrivateAttr
from .prompts import EXTRACTION_PROMPT, EXPLANATION_PROMPT, BASELINE_PROMPT

Level=Literal['high','medium','low','unknown']
class LLMOutput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    _response_model: str | None = PrivateAttr(default=None)

class Signals(LLMOutput):
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

class Explanation(LLMOutput):
    selected_action: str
    summary: str
    reasons: list[str]
    watch_metrics: list[str]
    limitations: list[str]

class BaselineAction(LLMOutput):
    selected_action: str
    reason: str

class DailyCallLimitError(RuntimeError):
    pass

class LLMService:
    def __init__(self):
        self._lock=threading.Lock(); self._day=None; self._calls=0
        self._retry_after=0.;self._failure_reason=None
        self._last_success_at=None;self._last_used_model=None
    def _settings(self):
        provider=os.getenv('LLM_PROVIDER','auto').strip().lower()
        if provider=='auto':
            provider='openrouter' if os.getenv('OPENROUTER_API_KEY') else ('deepseek' if os.getenv('DEEPSEEK_API_KEY') else 'openai')
        if provider=='openrouter':
            model=os.getenv('OPENROUTER_MODEL','openrouter/free').strip()
            # Never silently send a paid request when a free model is unavailable.
            free_model=model=='openrouter/free' or (model.endswith(':free') and not model.startswith('openrouter/'))
            return {'provider':provider,'api_key':os.getenv('OPENROUTER_API_KEY',''),
                    'model':model,'base_url':'https://openrouter.ai/api/v1',
                    'configuration_error':None if free_model else '免费接口仅允许 openrouter/free 或具体模型的 :free 版本'}
        if provider=='deepseek':
            return {'provider':provider,'api_key':os.getenv('DEEPSEEK_API_KEY',''),
                    'model':os.getenv('DEEPSEEK_MODEL','deepseek-flash'),'base_url':'https://api.deepseek.com'}
        return {'provider':provider,'api_key':os.getenv('OPENAI_API_KEY','') if provider=='openai' else '',
                'model':os.getenv('OPENAI_MODEL','gpt-4.1-mini'),'base_url':None}
    def _daily_limit(self):
        free=self._settings()['provider']=='openrouter'
        value=max(1,int(os.getenv('LLM_DAILY_CALL_LIMIT','50' if free else '120')))
        return min(value,50) if free else value
    def _calls_today(self):
        return self._calls if self._day==datetime.now(timezone.utc).date() else 0
    def _unavailable_reason(self):
        settings=self._settings()
        if settings.get('configuration_error'):return settings['configuration_error']
        if self._calls_today()>=self._daily_limit():return 'LLM 当日调用上限已用完，当前使用规则解析和模板解释'
        if self._failure_reason and time.monotonic()<self._retry_after:return self._failure_reason
        if settings['provider']=='openrouter' and not settings['api_key']:return 'OpenRouter 免费接口待配置账号密钥，当前使用规则解析和模板解释'
        return 'LLM 未启用或 API 密钥未配置'
    @property
    def available(self):
        settings=self._settings()
        return (bool(settings['api_key']) and not settings.get('configuration_error')
                and os.getenv('LLM_ENABLED','true').lower()=='true' and time.monotonic()>=self._retry_after
                and self._calls_today()<self._daily_limit())
    def status(self):
        settings=self._settings()
        return {'available':self.available,'provider':settings['provider'],'model':settings['model'],
                'configured':bool(settings['api_key']),'last_error':self._failure_reason,
                'mode':({'openrouter':'OpenRouter 免费模型 + 本地结构校验','deepseek':'DeepSeek JSON + 本地结构校验'}.get(settings['provider'],'OpenAI Structured Outputs')
                        + ('（待实际调用验证）' if not self._last_success_at else '')) if self.available else self._unavailable_reason(),
                'last_success_at':self._last_success_at,'last_used_model':self._last_used_model,
                'free_only':settings['provider']=='openrouter',
                'calls_today':self._calls_today(),'daily_limit':self._daily_limit()}
    def _success(self,result,model):
        result._response_model=model
        self._last_success_at=datetime.now(timezone.utc).isoformat();self._last_used_model=model
        return result
    def _provenance(self,result):
        settings=self._settings()
        return {'model':result._response_model or settings['model'],'requested_model':settings['model'],'provider':settings['provider']}
    def _call(self,schema,prompt,payload):
        if not self.available: raise RuntimeError(self._unavailable_reason())
        with self._lock:
            today=datetime.now(timezone.utc).date()
            if today!=self._day: self._calls=0; self._day=today
            if self._calls>=self._daily_limit(): raise DailyCallLimitError('LLM 当日调用上限已用完')
            self._calls+=1
        from openai import OpenAI
        settings=self._settings()
        timeout=os.getenv('LLM_TIMEOUT',os.getenv('OPENAI_TIMEOUT','45' if settings['provider']=='openrouter' else '20'))
        client=OpenAI(api_key=settings['api_key'],base_url=settings['base_url'],timeout=float(timeout),max_retries=0)
        if settings['provider']=='openrouter':
            instructions=prompt+'\n仅输出符合以下 JSON Schema 的对象，不输出 Markdown：\n'+json.dumps(schema.model_json_schema(),ensure_ascii=False)
            result=client.chat.completions.create(model=settings['model'],
                messages=[{'role':'system','content':instructions},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],
                response_format={'type':'json_schema','json_schema':{'name':schema.__name__,'strict':True,'schema':schema.model_json_schema()}},
                # Optional reasoning can exhaust the budget before emitting the required JSON.
                max_tokens=2000,extra_body={'reasoning':{'enabled':False},
                    'provider':{'require_parameters':True,'max_price':{'prompt':0,'completion':0,'request':0}}})
            if not result.choices or result.choices[0].finish_reason!='stop':raise RuntimeError('免费模型输出未完整结束')
            content=result.choices[0].message.content
            if not content:raise RuntimeError('免费模型未返回 JSON 内容')
            return self._success(schema.model_validate_json(content,strict=True),getattr(result,'model',None) or settings['model'])
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
            return self._success(schema.model_validate_json(content,strict=True),getattr(result,'model',None) or settings['model'])
        result=client.responses.parse(model=settings['model'],
                 input=[{'role':'system','content':prompt},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],
                 text_format=schema,max_output_tokens=1600,store=False)
        if result.output_parsed is None: raise RuntimeError('LLM 未返回有效结构化输出')
        return self._success(result.output_parsed,getattr(result,'model',None) or settings['model'])

    def _failure(self,exc):
        # Publish only a known error category; never provider bodies, headers or keys.
        code=getattr(exc,'code',None)
        if isinstance(exc,DailyCallLimitError):
            message='LLM 当日调用上限已用完，当前使用规则解析和模板解释';delay=60
        elif code in {'credit_balance_exhausted','insufficient_quota'} or getattr(exc,'status_code',None)==402:
            message='LLM API 额度不足，本次使用规则解析和模板解释';delay=600
        elif code in {'organization_spend_limit_exceeded','project_spend_limit_exceeded','organization_usage_limit_reached'}:
            message='LLM API 触及账户使用限额，本次使用规则解析和模板解释';delay=600
        elif getattr(exc,'status_code',None)==401:
            message='LLM API 密钥验证失败，本次使用规则解析和模板解释';delay=600
        elif getattr(exc,'status_code',None)==429:
            message='LLM API 请求受限，本次使用规则解析和模板解释';delay=60
        elif getattr(exc,'status_code',None)==403:
            message='LLM 服务访问受限，本次使用规则解析和模板解释';delay=600
        else:
            message=f'LLM 调用或结构校验失败（{type(exc).__name__}），本次使用规则解析和模板解释';delay=30
        self._failure_reason=message;self._retry_after=time.monotonic()+delay
        return message

    def extract(self,question,company_evidence=None):
        reason=self._unavailable_reason()
        if self.available:
            try:
                s=self._call(Signals,EXTRACTION_PROMPT,{'question':question,'company_background':company_evidence or []})
                # External ranges are deterministic semantic mapping ranges, not measured data.
                d=s.model_dump()
                for key,lo,hi in [('holiday_index',0,1),('competitor_intensity',0,1),('platform_traffic_change',-.5,.5),('market_demand_index',.5,1.5)]:
                    if d[key] is not None and not lo<=d[key]<=hi: raise ValueError('语义信号越界')
                self._failure_reason=None
                return {'source':'LLM',**self._provenance(s),'signals':d,'fallback_reason':None}
            except Exception as exc:
                reason=self._failure(exc)
        clean=re.sub(r'不是大促|没有大促|非节日|没有节日|不在大促','',question)
        def direction(term,up,down):
            hits=[]
            for clause in re.split('[，。；,;!?！？]',clean):
                match=re.search(term+r'[^，。；,;!?！？]{0,14}',clause,re.I)
                if not match: continue
                part=match[0]
                if re.search(r'没有|并未|未曾|并不|不再',part): continue
                a=bool(re.search(up,part));b=bool(re.search(down,part))
                if a!=b:hits.append(1 if a else -1)
            return hits[0] if hits and len(set(hits))==1 else 0
        inventory=direction('库存','积压|严重|很多|较多|偏高|很高','不足|缺货|较低|不多')
        cac=direction('(?:抖音(?:获客成本|成本|CAC)|获客成本)','偏高|很高|贵|上升|上涨','下降|降低|便宜|较低')
        repeat=direction('(?:复购|老客回流|回流)','好|不错|稳定|增长|上升','差|下降|减少|低')
        holiday=bool(re.search('节日|大促|双十一|春节|618|国庆',clean))
        competitor=bool(re.search('竞争.{0,6}(强|激烈)|竞品.{0,6}(降价|压力)',clean))
        traffic=direction('流量','增长|上涨|上升|增加','下降|减少|下滑')
        demand=direction('需求','增长|上涨|上升|增加','下降|减少|下滑')
        level=lambda d:'high' if d==1 else 'low' if d==-1 else 'unknown'
        signals={'summary':question[:180],'inventory_pressure':level(inventory),
                 'douyin_cac':level(cac),'repeat_purchase':level(repeat),
                 'holiday_index':1. if holiday else None,'competitor_intensity':.8 if competitor else None,
                 'platform_traffic_change':.2*traffic if traffic else None,'market_demand_index':1+.2*demand if demand else None,
                 'evidence':[question[:200]],'unknowns':['语义等级是规则匹配，未调用 LLM','未实测外部信号']}
        return {'source':'Rule parser','model':None,'signals':signals,'fallback_reason':reason}

    def explain(self,record):
        reason=self._unavailable_reason()
        if self.available:
            try:
                payload={k:record[k] for k in ['action_name','action_label','q_selected','expected_reward','metrics','bias','mask_reasons']}
                payload.update(question=record.get('question'),input_audit=record.get('input_audit'),reward_profile=record.get('reward_profile'))
                payload['company_background']=record.get('company_evidence',[])
                x=self._call(Explanation,EXPLANATION_PROMPT,payload)
                if x.selected_action!=record['action_name']: raise ValueError('LLM 返回动作不匹配，拒绝采用')
                self._failure_reason=None
                return {**x.model_dump(),'source':'LLM','fallback_reason':None,**self._provenance(x)}
            except Exception as exc: reason=self._failure(exc)
        m=record['metrics']; roi=m.get('roi'); cac=m.get('cac')
        from config.settings import PROFILE_LABELS
        from decision_models import apply_action
        goal=PROFILE_LABELS.get(record.get('reward_profile'),'当前经营目标')
        question=record.get('question','')
        q_reason=[]
        legal=sorted((x for x in record.get('q_values',[]) if x['legal']),key=lambda x:x['q'],reverse=True)
        if len(legal)>1:q_reason.append(f"在 {len(legal)} 个合法动作中，该动作 Q 值最高；比第二名高 {legal[0]['q']-legal[1]['q']:.4f}。Q 是累计回报估计，不是利润。")
        if record.get('context') is not None:
            old=record['context'];new=apply_action(old,record['action'])
            changes=[f'{ch}预算 {old["budgets"].get(ch,0):,.0f} → {value:,.0f} 元' for ch,value in new['budgets'].items()
                     if abs(value-old['budgets'].get(ch,0))>1e-6]
            if new['discount']!=old['discount']:changes.append(f'折扣率 {old["discount"]:.0%} → {new["discount"]:.0%}')
            if new['coupon']!=old['coupon']:changes.append(f'额外补贴率 {old["coupon"]:.0%} → {new["coupon"]:.0%}')
            if new['price']!=old['price']:changes.append(f'标价 {old["price"]:.2f} → {new["price"]:.2f} 元')
            q_reason.insert(0,'执行影响：'+('；'.join(changes) if changes else '预算和价格保持当前水平')+'。')
        used=record.get('input_audit',{}).get('used_signals',[])
        if used:q_reason.append('本次识别：'+'、'.join(x['description'] for x in used)+'；均为用户描述的语义假设，未实测。')
        return {'selected_action':record['action_name'],'source':'Template','model':None,'fallback_reason':reason,
                'summary':f"针对“{question[:70]}”，按{goal}目标，模型选择{record['action_label']}。" if question else f"按{goal}目标，模型选择{record['action_label']}。",
                'reasons':q_reason+[f"当前营销 ROI 为 {roi:.2f}。" if roi is not None else '营销 ROI 数据不足。',
                           f"获客广告 CAC 为 ¥{cac:.2f}。" if cac is not None else '新客不足，CAC 无法计算。',
                           f"当前分仓库存为 {m['inventory_level']:,.0f} 件；留意库存消化与预算消耗。" if m.get('inventory_level') is not None else '缺少分仓库存记录，需补充后评估。'],
                'watch_metrics':['营销贡献利润','获客成本与新客数','库存覆盖天数'],
                'limitations':['模板只复述模型和指标，不能证明该动作的因果收益','模型在合成环境预训练，实际执行前需业务审核']}

    def baseline_action(self,metrics,legal_names):
        x=self._call(BaselineAction,BASELINE_PROMPT,{'metrics':metrics,'legal_actions':legal_names})
        if x.selected_action not in legal_names: raise ValueError('LLM-only 返回非法动作')
        return x.selected_action

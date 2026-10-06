from dataclasses import asdict
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
import secrets
import time
import threading
import uuid
import numpy as np
from database.store import Store,dumps
from factor_engine import FactorEngine
from factor_engine.engine import FactorRegistry,CORE
from factor_engine.selection import evaluate_factors
from sarsa import DeepSARSA,SARSAConfig
from sarsa.training import train
from reward import RewardProfile,PROFILES,REWARD_KEYS,RewardEngine
from environments import MarketingEnvironment,context_from_metrics
from decision_models import ACTIONS,action_mask,apply_action,ActionConstraints
from decision_models.actions import CHANNELS
from decision_models.library import create_library
from data import process_csv
from data.generate import generate_sample
from data.updates import prepare_update,stamp
from backend.schemas import FeedbackInput
from bias_engine import BiasEngine
from llm import LLMService
from llm.intent import marketing_question,infer_goal,explicit_constraints
from config.settings import ROOT,STORAGE,DATA_PATH,PROFILE_LABELS

def now(): return datetime.now(timezone.utc).isoformat()
def profile_from_record(record): return RewardProfile(record['reward_profile'],tuple(record['reward_weights']))

class BusinessError(Exception): pass

class Platform:
    def __init__(self,storage=None,base_path=None):
        self.storage=storage or STORAGE; self.storage.mkdir(parents=True,exist_ok=True)
        self.store=Store(self.storage/'platform.sqlite3'); self.factors=FactorEngine()
        self.company_profile=json.loads((ROOT/'data'/'company_profile.json').read_text(encoding='utf-8'))
        self.store.load_company_evidence(self.company_profile)
        self.reward=RewardEngine(); self.llm=LLMService(); self.bias=BiasEngine(); self.lock=threading.RLock()
        base=base_path or ROOT/'data'/'pretrained.pt'
        if base.exists(): self.base=DeepSARSA.load(base,self.factors.registry.signature)
        else: self.base=DeepSARSA(self.factors.state_dim,SARSAConfig(),self.factors.registry.signature)
        self.base_id=hashlib.sha256(self.base.to_bytes()).hexdigest()[:10]
        manifest=ROOT/'data'/'training_report.json'
        self.base_report=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else None
        self.jobs={}; self.training_gate=threading.Lock(); self.data_previews={}
        self.preview_limit=max(1,min(16,int(os.getenv('MAX_DATA_PREVIEWS','8'))))
        if not DATA_PATH.exists(): generate_sample(DATA_PATH)

    def _engine_for(self,agent):
        engine=self.factors if agent.state_dim==self.factors.state_dim else FactorEngine(FactorRegistry(CORE[:30]))
        if agent.signature!=engine.registry.signature or agent.state_dim!=engine.state_dim:
            raise ValueError('模型因子定义不兼容，不能生成决策')
        return engine

    def _agent(self,s):
        agent=DeepSARSA.from_bytes(s['model']);self._engine_for(agent);return agent

    def _session(self,sid):
        s=self.store.session(sid);agent=self._agent(s)
        if agent.state_dim!=self.factors.state_dim and not s['active_decision']:
            # Keep old data/history and archive the old checkpoint. An active cycle
            # stays on its original model until the confirmed SARSA transition ends.
            with self.lock,self.store.connect() as c:
                current=self.store.session(sid,c)
                if current['active_decision'] or self._agent(current).state_dim==self.factors.state_dim:return current
                c.execute('CREATE TABLE IF NOT EXISTS model_archive (session_id TEXT, archived TEXT, model BLOB, config TEXT)')
                c.execute('INSERT INTO model_archive VALUES (?,?,?,?)',(sid,now(),current['model'],dumps(current['config'])))
                config={**current['config'],'base_id':self.base_id,'training_status':'预训练 已升级渠道因子',
                        'model_migration':'原模型已归档，经营数据和历史记录保留'}
                c.execute('UPDATE sessions SET model=?,config=?,updated=? WHERE id=?',(self.base.to_bytes(),dumps(config),now(),sid))
                if self.base_report:self.store.set_metadata(f'training:{sid}',{**self.base_report,'model_id':self.base_id},c)
            s=self.store.session(sid)
        return s

    def new_session(self):
        dataset=process_csv(DATA_PATH.read_bytes(),'demo'); sid=secrets.token_urlsafe(32)
        for row in dataset['rows']:row['observation_source']='demo';row['cost_method']=dataset['current']['cost_method']
        for day in dataset['daily']:day['observation_source']='demo'
        stamp(dataset,'demo','初始合成演示数据')
        config={'base_id':self.base_id,'training_status':'预训练' if self.base.updates else '未训练初始化',
                'version':'platform-v1','constraints':asdict(ActionConstraints())}
        with self.store.connect() as c:
            c.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,NULL)',
                      (sid,now(),now(),dumps(dataset),dumps(dataset['current']),self.base.to_bytes(),dumps(config)))
            if self.base_report:
                self.store.set_metadata(f'training:{sid}',{**self.base_report,'model_id':self.base_id},c)
        return {'session_id':sid,'dataset':dataset['quality'],'training_status':config['training_status']}

    def dashboard(self,sid):
        s=self._session(sid); dataset=s['dataset']; metrics=s['metrics']; h=dataset['daily']
        bias=self.bias.analyze(h); bias_values={x['name']:x['score'] for x in bias}
        state=self._engine_for(self._agent(s)).build(metrics,PROFILES['balanced_growth'],bias=bias_values)
        records=self.store.history(sid,limit=None)
        confirmed=[r for r in records if r.get('execution')]
        feedback=[r for r in records if r.get('user_feedback')]
        latest=next((r for r in records if r['id']==dataset['quality'].get('latest_feedback_decision_id')),None)
        comparison=None
        if latest and latest.get('outcome_metrics'):
            before=latest['metrics']; after=latest['outcome_metrics']
            comparison={'source':latest['user_feedback']['provenance']['label'],
                        'before_profit':before.get('profit'),'after_profit':after.get('profit'),
                        'profit_change':after['profit']-before['profit'],
                        'before_roi':before.get('roi'),'after_roi':after.get('roi'),
                        'reward':latest['actual_reward']['total']}
        operations={'decisions':len(records),'confirmed':len(confirmed),
                    'accepted':sum(not r['execution']['override'] for r in confirmed),
                    'overrides':sum(bool(r['execution']['override']) for r in confirmed),
                    'actual_feedback':sum(r['user_feedback']['mode']=='actual' for r in feedback),
                    'simulation_feedback':sum(r['user_feedback']['mode']=='simulation' for r in feedback),
                    'last_confirmation':max((r['execution']['timestamp'] for r in confirmed),default=None)}
        return {'metrics':metrics,'series':[{k:x.get(k) for k in ['date','revenue','profit','roi','cac','inventory_level','advertising_budget','conversion_rate','repeat_purchase_rate']} for x in h],
                'quality':dataset['quality'],'state':state,'bias':bias,'llm':self.llm.status(),
                'operations':operations,'comparison':comparison,
                'training_status':s['config']['training_status'],'model_version':self.version(s),
                'active_decision':self.store.decision(sid,s['active_decision']) if s['active_decision'] else None,
                'profiles':[{'name':k,'label':PROFILE_LABELS[k],**v.to_dict()} for k,v in PROFILES.items()]}

    def version(self,s,agent=None):
        a=agent or self._agent(s)
        return f"{s['config']['base_id']}-u{a.updates}"

    def import_data(self,sid,blob,source='uploaded'):
        dataset=process_csv(blob,source)
        with self.lock,self.store.connect() as c:
            s=self.store.session(sid,c)
            if s['active_decision']: raise BusinessError('先完成当前决策周期，再更换数据')
            for row in dataset['rows']:row['observation_source']=source
            for day in dataset['daily']:day['observation_source']=source
            stamp(dataset,source,'整批替换数据',s['dataset'])
            c.execute('UPDATE sessions SET dataset=?,metrics=?,updated=? WHERE id=?',
                      (dumps(dataset),dumps(dataset['current']),now(),sid))
        return {'quality':dataset['quality'],'current':dataset['current']}

    def preview_data(self,sid,blob,source='uploaded',note='更新运营数据'):
        if source not in {'uploaded','manual','demo_upload'}:raise ValueError('数据来源不合法')
        if len(note)>200:raise ValueError('更新说明最多 200 字')
        incoming=process_csv(blob,source,min_rows=1)
        for row in incoming['rows']:row['cost_method']=incoming['current']['cost_method']
        with self.lock:
            s=self.store.session(sid)
            dataset,changes=prepare_update(s['dataset'],incoming,source,note)
            tick=time.monotonic()
            for token,plan in list(self.data_previews.items()):
                if tick-plan['created']>600:del self.data_previews[token]
            while len(self.data_previews)>=self.preview_limit:
                del self.data_previews[next(iter(self.data_previews))]
            token=secrets.token_urlsafe(32)
            active=self.store.decision(sid,s['active_decision']) if s['active_decision'] else None
            new_dates=[date for date in changes['incoming_dates'] if date>s['metrics']['date']]
            feedback_allowed=bool(active and active['status']=='executed' and len(new_dates)==1 and
                                  dataset['current']['date']==new_dates[0] and not changes['replaced_demo'])
            blocked=bool(active and active['parent_decision'] and active['status']=='draft')
            self.data_previews[token]={'sid':sid,'created':tick,'base_updated':s['updated'],
                                      'dataset':dataset,'changes':changes,'source':source,'note':note,
                                      'feedback_allowed':feedback_allowed}
            warnings=list(dataset['quality']['warnings'])
            if changes['replaced_demo']:warnings.append('首次导入真实观测将移出合成演示数据；旧决策的观测快照仍保留')
            if source=='demo_upload':warnings.append('本次更新标记为合成/测试数据，不作为企业实际业绩')
            return {'preview_token':token,'expires_in':600,'changes':changes,
                    'before':{'quality':s['dataset']['quality'],'metrics':s['metrics']},
                    'after':{'quality':dataset['quality'],'metrics':dataset['current']},
                    'warnings':warnings,'active_status':active['status'] if active else None,
                    'feedback_allowed':feedback_allowed,'blocked':blocked}

    def apply_data(self,sid,token,as_feedback=False,terminal=False):
        with self.lock:
            s=self.store.session(sid)
            if s['dataset']['quality'].get('last_applied_token')==token:
                return {**s['dataset']['quality']['last_apply_receipt'],'idempotent':True}
            plan=self.data_previews.get(token)
            if not plan or plan['sid']!=sid or time.monotonic()-plan['created']>600:
                raise BusinessError('预览已失效，请重新预览后保存')
            if plan['base_updated']!=s['updated']:raise BusinessError('预览后工作区已变化，请重新预览，避免覆盖新记录')
            active=self.store.decision(sid,s['active_decision']) if s['active_decision'] else None
            if active and active['status']=='draft' and active['parent_decision']:
                raise BusinessError('上一轮正在等待下一实际动作。请先确认执行或结束周期，再更新观测')
            if active and active['status']=='executed' and not as_feedback:
                raise BusinessError('当前动作已经执行。请选择将新增一天的观测作为本轮经营反馈；不能跳过执行结果')
            if as_feedback and not (active and plan['feedback_allowed']):
                raise BusinessError('经营反馈须对应已确认的动作，且只新增一个后续观察日；真实观测不能与初始合成数据组成训练转移')
            if terminal and not as_feedback:raise BusinessError('仅经营反馈可结束学习周期')
            dataset=json.loads(dumps(plan['dataset']))
            receipt={'revision':dataset['quality']['revision'],'observed_date':dataset['current']['date'],
                     'feedback_saved':as_feedback,'cancelled_draft':active['id'] if active and active['status']=='draft' else None,
                     'idempotent':False}
            dataset['quality'].update(last_applied_token=token,last_apply_receipt=receipt)
            if as_feedback:
                mode='simulation' if plan['source']=='demo_upload' else 'actual'
                provenance={'source':mode,'label':'上传的合成/测试结果，非企业实际业绩' if mode=='simulation' else '用户提供渠道级经营结果，未独立审计',
                            'method':'validated_channel_observations','incoming_dates':plan['changes']['incoming_dates']}
                self.feedback(sid,active['id'],FeedbackInput(mode=mode,terminal=terminal),
                              _observed=(dataset,dataset['current'],provenance,plan))
            else:
                stamp(dataset,plan['source'],plan['note'],s['dataset'],plan['changes'])
                with self.store.connect() as c:
                    if active:
                        active['status']='cancelled';active['cancellation_reason']='观测数据已更新，旧草稿保留供核对'
                        self.store.put_decision(sid,active,c)
                    c.execute('UPDATE sessions SET dataset=?,metrics=?,active_decision=NULL,updated=? WHERE id=?',
                              (dumps(dataset),dumps(dataset['current']),now(),sid))
            del self.data_previews[token]
            return receipt

    def _build_decision(self,s,question,profile,constraints,parent=None,agent=None):
        agent=agent or self._agent(s)
        company_evidence=self.store.retrieve_company_evidence(question)
        # A feedback cycle continues the original business question. Reuse its
        # audited signals instead of asking the LLM to reinterpret it each day.
        previous=self.store.decision(s['id'],parent) if parent else None
        semantic=json.loads(dumps(previous['semantic'])) if previous and previous['question']==question else self.llm.extract(question,company_evidence=company_evidence)
        history=s['dataset']['daily']; bias=self.bias.analyze(history)
        state=self._engine_for(agent).build(s['metrics'],profile,semantic['signals'],{x['name']:x['score'] for x in bias})
        used=[{'name':f['name'],'description':f['description'],'value':f['raw']} for f in state['factors']
              if f['provenance']=='语义信号（未实测）']
        input_audit={'used_signals':used,'business_claims':{k:semantic['signals'][k] for k in ['inventory_pressure','douyin_cac','repeat_purchase']
                         if semantic['signals'].get(k,'unknown')!='unknown'},
                     'data_source':s['dataset']['quality']['label'],
                     'note':'定性库存、获客与回流描述保留为证据，不覆盖运营数据库。相同经营状态、目标和约束可以得到同一动作。'}
        context=context_from_metrics(s['metrics']); mask,reasons=action_mask(context,constraints)
        if not mask.any(): raise BusinessError('当前数据下没有能同时满足预算与毛利限制的离散动作。请核对业务上限，或先人工调整现有预算与价格。')
        action=agent.select_action(state['vector'],mask,explore=False); q=agent.q_values(state['vector'])
        ranked=sorted((float(q[i]),i) for i in np.flatnonzero(mask))
        stability={'selection':'固定模型和状态下取合法动作的最高 Q 值，展示决策不使用 epsilon 随机探索',
                   'q_gap':ranked[-1][0]-ranked[-2][0] if len(ranked)>1 else None,
                   'alternative_action':ACTIONS[ranked[-2][1]].label if len(ranked)>1 else None,
                   'semantic_reused':bool(previous and previous['question']==question),
                   'previous_model_version':previous['model_version'] if previous else None,
                   'note':'Q 差距较小时排名容易因状态或在线更新变化；Q 差距不是置信度或利润差。'}
        importance=evaluate_factors(history,agent)
        record={'id':str(uuid.uuid4()),'timestamp':now(),'status':'draft','question':question,
                'data_context':{'revision':s['dataset']['quality'].get('revision',0),
                                'content_hash':s['dataset']['quality'].get('content_hash'),
                                'observed_date':s['metrics']['date'],'source':s['dataset']['quality']['label']},
                'model_version':self.version(s,agent),'state_vector':state['vector'],'factor_values':state['factors'],
                'factor_importance':importance,'factor_signature':state['signature'],'state_coverage':state['coverage'],
                'action':action,'action_name':ACTIONS[action].name,'action_label':ACTIONS[action].label,
                'q_values':[{'index':i,'name':a.name,'label':a.label,'q':float(q[i]),'legal':bool(mask[i]),
                             'reasons':reasons.get(a.name,[])} for i,a in enumerate(ACTIONS)],
                'q_selected':float(q[action]),'q_definition':'当前目标下折扣累计回报，非下一期利润',
                'expected_reward':MarketingEnvironment.forecast(s['metrics'],action,profile,constraints=constraints),
                'actual_reward':None,'reward_profile':profile.name,'reward_weights':list(map(float,profile.normalized_weights)),
                'user_feedback':None,'decision_source':'Deep SARSA','explanation_source':None,
                'semantic':semantic,'input_audit':input_audit,'company_evidence':company_evidence,'bias':bias,'mask_reasons':reasons,'constraints':asdict(constraints),
                'context':context,'metrics':s['metrics'],'parent_decision':parent,
                'training_data_source':'合成环境预训练' if agent.updates else '未训练，建议先在实验室训练',
                'stability_audit':stability,
                'execution':None,'transition':None}
        record['explanation']=self.llm.explain(record)
        record['explanation_source']=record['explanation']['source']
        return record

    def decide(self,sid,request):
        if not marketing_question(request.question): raise ValueError('请输入营销或经营问题，例如库存消化、渠道投入、获客或利润。无关内容不会生成营销动作。')
        goal=infer_goal(request.question) if request.reward_profile=='auto' else request.reward_profile
        if goal not in PROFILES: raise BusinessError('未知经营目标')
        profile=PROFILES[goal]
        if request.weights is not None:
            if set(request.weights)!=set(REWARD_KEYS): raise BusinessError('自定义权重必须完整包含 12 项指标')
            profile=RewardProfile(profile.name,tuple(request.weights[k] for k in REWARD_KEYS))
        if not set(request.constraints.stopped_channels).issubset(CHANNELS): raise BusinessError('停用渠道名称不合法')
        constraints=ActionConstraints(**request.constraints.model_dump())
        constraints,applied=explicit_constraints(request.question,constraints)
        with self.lock:
            s=self._session(sid)
            if s['active_decision']: raise BusinessError('当前决策周期尚未结束，请到历史或决策中心继续执行 / 反馈')
            record=self._build_decision(s,request.question,profile,constraints)
            record['input_audit'].update(goal_source='根据问题识别' if request.reward_profile=='auto' else '用户选择',
                                         explicit_constraints=applied)
            with self.store.connect() as c:
                self.store.put_decision(sid,record,c)
                c.execute('UPDATE sessions SET active_decision=?,updated=? WHERE id=?',(record['id'],now(),sid))
            return record

    def execute(self,sid,did,request):
        with self.lock,self.store.connect() as c:
            s=self.store.session(sid,c); record=self.store.decision(sid,did,c)
            if record['status']=='executed':
                if request.action_name and request.action_name!=record['execution']['action_name']: raise BusinessError('已执行动作不能被重复提交改写')
                return record
            if record['status']!='draft': raise BusinessError('只有草稿可确认执行')
            if s['active_decision']!=did: raise BusinessError('此决策已不是当前周期')
            chosen=request.action_name or record['action_name']
            indices={a.name:i for i,a in enumerate(ACTIONS)}
            if chosen not in indices: raise BusinessError('未知营销动作')
            action=indices[chosen]; mask,_=action_mask(record['context'],ActionConstraints(**record['constraints']))
            if not mask[action]: raise BusinessError('执行动作违反预算、价格或库存约束')
            override=action!=record['action']
            if override and not request.reason: raise BusinessError('人工调整必须填写理由')
            record['execution']={**request.model_dump(),'action':action,'action_name':chosen,'timestamp':now(),
                                 'override':override,'execution_source':'Human override' if override else 'Deep SARSA'}
            record['status']='executed'
            if record['parent_decision']:
                prev=self.store.decision(sid,record['parent_decision'],c)
                if prev['status']!='awaiting_next': raise BusinessError('上一转移已更新或状态无效')
                agent=self._agent(s)
                # Bootstrap with exactly the next action confirmed here, even when manually overridden.
                trace=agent.update(prev['state_vector'],prev['execution']['action'],prev['actual_reward']['total'],
                                   record['state_vector'],action,next_mask=mask)
                prev['status']='updated'; prev['transition']['next_action']=action
                prev['transition']['next_action_name']=chosen; prev['transition']['next_action_confirmed']=True
                prev['transition']['update']=trace; prev['transition']['model_version_after']=self.version(s,agent)
                c.execute('INSERT INTO transitions VALUES (?,?,?,?)',(str(uuid.uuid4()),sid,now(),dumps(prev['transition'])))
                self.store.put_decision(sid,prev,c)
                c.execute('UPDATE sessions SET model=? WHERE id=?',(agent.to_bytes(),sid))
                record['previous_update']=trace
            self.store.put_decision(sid,record,c)
            c.execute('UPDATE sessions SET updated=? WHERE id=?',(now(),sid))
            return record

    def _outcome(self,record,request):
        actual_action=record['execution']['action']; profile=profile_from_record(record)
        if request.mode=='simulation':
            # Common random innovations for the same observed day and metrics;
            # an unrelated UUID must not change the simulated market outcome.
            keys=['date','revenue','advertising_budget','promotion_cost','inventory_level',
                  'list_price','price_level','unit_cost','conversion_rate','repeat_purchase_rate','budgets']
            basis=json.dumps({k:record['metrics'].get(k) for k in keys},sort_keys=True,allow_nan=False)
            seed=int(hashlib.sha256(('state-seed-v1:'+basis).encode()).hexdigest()[:8],16)%100000
            env=MarketingEnvironment(seed=seed,profile=profile,calibration=record['metrics'],constraints=ActionConstraints(**record['constraints']))
            _,_,_,info=env.step(actual_action)
            return info['metrics'],{'source':'simulation','seed':seed,'seed_method':'observed-state-v1',
                                   'label':'合成环境执行结果，不是企业实际业绩',
                                   'boundary':'同一观察日与经营数据共用随机情景；环境仍含随机扰动，并非企业效果预测'}
        if request.outcome is None: raise BusinessError('实际反馈需要填写经营结果')
        o=request.outcome.model_dump(); prev=record['metrics']; context=apply_action(record['context'],actual_action)
        m={k:None for k in [f.name for f in self.factors.registry.factors]}
        ads=o['advertising_cost']; budgets=context['budgets']
        if ads is not None:
            prior=sum(budgets.values()); budgets={k:v*ads/max(prior,1) for k,v in budgets.items()}
        else: ads=None
        m.update({k:v for k,v in o.items() if k not in {'advertising_cost','promotion_cost'}})
        m.update(revenue=o['revenue'],profit_margin=o['profit']/max(o['revenue'],1),
                 gmv_growth=o['revenue']/max(prev['revenue'],1)-1,
                 price_level=context['price']*(1-context['discount']),list_price=context['price'],
                 unit_cost=context['unit_cost'],discount=context['discount'],budgets=budgets,
                 advertising_budget=ads,promotion_cost=o['promotion_cost'],
                 promotion_cost_ratio=o['promotion_cost']/max(o['revenue'],1) if o['promotion_cost'] is not None else None,
                 inventory_pressure=float(np.clip(o['inventory_level']/max(o['sales'],1)/60,0,1)) if o['sales'] is not None else None,
                 volatility=abs(o['revenue']/max(prev['revenue'],1)-1),channels=[],channel_roi={},
                 cost_method='用户反馈营销贡献利润，尚未审计')
        for key,k in [('douyin_share','抖音'),('xiaohongshu_share','小红书'),('private_share','私域'),('taobao_share','淘宝'),('search_share','搜索广告')]:
            m[key]=budgets.get(k,0)/max(sum(budgets.values()),1)
        return m,{'source':'actual','label':'用户填报实际结果；未填指标保持缺失，未审计',
                  'budget_source':'实际总投入按执行渠道比例分配' if ads is not None else '执行后预算计划，非实测投入'}

    def feedback(self,sid,did,request,_observed=None):
        with self.lock:
            s=self.store.session(sid); record=self.store.decision(sid,did)
            if record['user_feedback']:
                saved={**record['user_feedback']['request'],'observed_date':record['user_feedback']['request'].get('observed_date')}
                if saved!=request.model_dump(mode='json'): raise BusinessError('该反馈已保存，不能改写已学习的经营结果')
                return {'decision':record,'next_decision':self.store.decision(sid,record['next_decision']) if record.get('next_decision') else None,'idempotent':True}
            if record['status']!='executed' or s['active_decision']!=did: raise BusinessError('先确认该策略已执行，再提交结果')
            previous=json.loads(dumps(s['dataset']))
            if _observed:dataset,metrics,provenance,plan=_observed
            else:
                metrics,provenance=self._outcome(record,request);dataset=s['dataset']
                metrics['date']=request.observed_date.isoformat() if request.observed_date else (datetime.fromisoformat(s['metrics']['date'])+timedelta(days=1)).date().isoformat()
            if metrics['date']<=s['metrics']['date']:raise BusinessError('反馈观察日须晚于本轮决策使用的观察日')
            profile=profile_from_record(record)
            if record['execution'].get('forecast_revenue') is not None: metrics['forecast_revenue']=record['execution']['forecast_revenue']
            for k in ['reason','reason_category','supporting_experiment','anchor_value','current_evidence_conflict']: metrics[k]=record['execution'].get(k)
            reward=self.reward.calculate(metrics,profile)
            record['actual_reward']=reward; record['user_feedback']={'rating':request.rating,'mode':request.mode,
                       'provenance':provenance,'timestamp':now(),'request':request.model_dump(mode='json')}
            metrics['observation_source']=provenance['source']
            if not _observed:dataset['daily'].append(metrics)
            else:dataset['daily']=[metrics if day['date']==metrics['date'] else day for day in dataset['daily']]
            dataset['current']=metrics
            dataset['quality']['latest_result_source']=provenance['label']
            dataset['quality']['source']='demo' if provenance['source']=='simulation' else 'actual'
            dataset['quality']['label']=provenance['label']
            dataset['quality']['latest_feedback_decision_id']=did
            stamp(dataset,plan['source'] if _observed else provenance['source'],
                  plan['note'] if _observed else '已确认动作的经营反馈',previous,
                  plan['changes'] if _observed else None)
            record['outcome_metrics']=metrics
            s['metrics']=metrics; s['dataset']=dataset
            agent=self._agent(s)
            state=self._engine_for(agent).build(metrics,profile,bias={x['name']:x['score'] for x in self.bias.analyze(dataset['daily'])})
            transition={'state':record['state_vector'],'action':record['execution']['action'],
                        'reward':reward['total'],'next_state':state['vector'],'next_action':None,
                        'next_action_confirmed':False,'source':provenance['source'],'terminal':request.terminal}
            next_record=None
            if request.terminal:
                transition['update']=agent.update(record['state_vector'],record['execution']['action'],reward['total'],state['vector'],None,done=True)
                transition['model_version_after']=self.version(s,agent); record['status']='terminal'
            else:
                next_record=self._build_decision(s,record['question'],profile,ActionConstraints(**record['constraints']),parent=did,agent=agent)
                transition['next_state']=next_record['state_vector'] # Include the same semantic evidence as the actual next decision.
                record['next_decision']=next_record['id']; record['status']='awaiting_next'
            record['transition']=transition
            with self.store.connect() as c:
                self.store.put_decision(sid,record,c)
                if next_record: self.store.put_decision(sid,next_record,c)
                if request.terminal: c.execute('INSERT INTO transitions VALUES (?,?,?,?)',(str(uuid.uuid4()),sid,now(),dumps(transition)))
                c.execute('UPDATE sessions SET dataset=?,metrics=?,model=?,active_decision=?,updated=? WHERE id=?',
                          (dumps(dataset),dumps(metrics),agent.to_bytes(),next_record['id'] if next_record else None,now(),sid))
            return {'decision':record,'next_decision':next_record,'idempotent':False}

    def cancel(self,sid,did):
        with self.lock,self.store.connect() as c:
            s=self.store.session(sid,c); record=self.store.decision(sid,did,c)
            if record['status']!='draft' or record['parent_decision']: raise BusinessError('仅可取消尚未执行的首轮草稿；后续动作须执行或结束上一周期')
            record['status']='cancelled'; self.store.put_decision(sid,record,c)
            c.execute('UPDATE sessions SET active_decision=NULL,updated=? WHERE id=?',(now(),sid))
            return record

    def finish_cycle(self,sid,did):
        """End a pending episode without inventing an unexecuted A'."""
        with self.lock,self.store.connect() as c:
            s=self.store.session(sid,c); prev=self.store.decision(sid,did,c)
            if prev['status']=='terminal': return prev
            if prev['status']!='awaiting_next' or not prev.get('next_decision'): raise BusinessError('仅可结束等待下一实际动作的周期')
            child=self.store.decision(sid,prev['next_decision'],c)
            if child['status']!='draft' or s['active_decision']!=child['id']: raise BusinessError('下一动作已经执行，不能改为终止转移')
            agent=self._agent(s)
            tr=prev['transition']; tr['terminal']=True; tr['end_reason']='用户结束周期，下一建议未执行'
            tr['next_action']=None; tr['next_action_confirmed']=False
            tr['update']=agent.update(prev['state_vector'],prev['execution']['action'],prev['actual_reward']['total'],tr['next_state'],None,done=True)
            tr['model_version_after']=self.version(s,agent); prev['status']='terminal'
            child['status']='cancelled'; child['cancellation_reason']='上一经营周期结束，下一动作未执行'
            self.store.put_decision(sid,prev,c); self.store.put_decision(sid,child,c)
            c.execute('INSERT INTO transitions VALUES (?,?,?,?)',(str(uuid.uuid4()),sid,now(),dumps(tr)))
            c.execute('UPDATE sessions SET active_decision=NULL,model=?,updated=? WHERE id=?',(agent.to_bytes(),now(),sid))
            return prev

    def lab(self,sid):
        s=self._session(sid); agent=self._agent(s)
        manifest=ROOT/'data'/'training_report.json'; experiments=ROOT/'data'/'experiments.json'
        session_report=self.store.get_metadata(f'training:{sid}')
        return {'training':session_report or (self.base_report if s['config']['base_id']==self.base_id else None),
                'experiments':json.loads(experiments.read_text(encoding='utf-8')) if experiments.exists() else None,
                'importance':evaluate_factors(s['dataset']['daily'],agent),'updates':agent.updates,
                'model_version':self.version(s,agent),'network':str(agent.network),
                'epsilon':agent.epsilon,'config':asdict(agent.config),
                'current_state':self._engine_for(agent).build(s['metrics'],PROFILES['balanced_growth'],bias={x['name']:x['score'] for x in self.bias.analyze(s['dataset']['daily'])}),
                'recent_transitions':[x['transition'] for x in self.store.history(sid) if x.get('transition')][:10]}

    def start_training(self,sid,request):
        if request.minimum_epsilon>request.epsilon: raise BusinessError('minimum_epsilon 不能大于初始 epsilon')
        s=self.store.session(sid)
        if s['active_decision']: raise BusinessError('先结束决策周期再重新训练')
        if not self.training_gate.acquire(blocking=False): raise BusinessError('已有训练任务运行，请稍后再试')
        jid=str(uuid.uuid4()); job={'id':jid,'session_id':sid,'status':'running','progress':0,'curves':[]}
        self.jobs[jid]=job
        # Bounded background worker. Models remain per session; public deployment can require admin token.
        original=train
        def worker_with_progress():
            def cb(curve): job['progress']=curve['episode']; job['curves'].append(curve)
            try:
                cfg=SARSAConfig(**request.model_dump(),architecture='dueling-v2'); agent,report=original(cfg,progress=cb,calibration=s['metrics'])
                with self.lock,self.store.connect() as c:
                    current=self.store.session(sid,c)
                    if current['active_decision']: raise BusinessError('训练期间存在活动决策，训练结果未替换')
                    if current['dataset']!=s['dataset']: raise BusinessError('训练期间数据已变化，未替换模型；请以新数据重新训练')
                    conf=current['config']; conf['base_id']=hashlib.sha256(agent.to_bytes()).hexdigest()[:10]; conf['training_status']='本会话仿真训练'
                    report['calibration_source']=s['dataset']['quality']['label']
                    report['model_id']=conf['base_id']; report['created']=now()
                    self.store.set_metadata(f'training:{sid}',report,c)
                    c.execute('UPDATE sessions SET model=?,config=?,updated=? WHERE id=?',(agent.to_bytes(),dumps(conf),now(),sid))
                job.update(status='completed',report=report)
            except Exception as exc: job.update(status='failed',error=str(exc)[:300])
            finally: self.training_gate.release()
        threading.Thread(target=worker_with_progress,daemon=True,name='sarsa-training').start()
        return {k:v for k,v in job.items() if k!='session_id'}

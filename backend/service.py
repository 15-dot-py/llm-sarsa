from dataclasses import asdict
from datetime import datetime,timezone,timedelta
import hashlib
import json
import secrets
import threading
import uuid
import numpy as np
from database.store import Store,dumps
from factor_engine import FactorEngine
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
from bias_engine import BiasEngine
from llm import LLMService
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
        self.jobs={}; self.training_gate=threading.Lock()
        if not DATA_PATH.exists(): generate_sample(DATA_PATH)

    def new_session(self):
        dataset=process_csv(DATA_PATH.read_bytes(),'demo'); sid=secrets.token_urlsafe(32)
        config={'base_id':self.base_id,'training_status':'预训练' if self.base.updates else '未训练初始化',
                'version':'platform-v1','constraints':asdict(ActionConstraints())}
        with self.store.connect() as c:
            c.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,NULL)',
                      (sid,now(),now(),dumps(dataset),dumps(dataset['current']),self.base.to_bytes(),dumps(config)))
            if self.base_report:
                self.store.set_metadata(f'training:{sid}',{**self.base_report,'model_id':self.base_id},c)
        return {'session_id':sid,'dataset':dataset['quality'],'training_status':config['training_status']}

    def dashboard(self,sid):
        s=self.store.session(sid); dataset=s['dataset']; metrics=s['metrics']; h=dataset['daily']
        bias=self.bias.analyze(h); bias_values={x['name']:x['score'] for x in bias}
        state=self.factors.build(metrics,PROFILES['balanced_growth'],bias=bias_values)
        return {'metrics':metrics,'series':[{k:x.get(k) for k in ['date','revenue','profit','roi','cac','inventory_level','advertising_budget','conversion_rate','repeat_purchase_rate']} for x in h],
                'quality':dataset['quality'],'state':state,'bias':bias,'llm':self.llm.status(),
                'training_status':s['config']['training_status'],'model_version':self.version(s),
                'active_decision':self.store.decision(sid,s['active_decision']) if s['active_decision'] else None,
                'profiles':[{'name':k,'label':PROFILE_LABELS[k],**v.to_dict()} for k,v in PROFILES.items()]}

    def version(self,s,agent=None):
        a=agent or DeepSARSA.from_bytes(s['model'],self.factors.registry.signature)
        return f"{s['config']['base_id']}-u{a.updates}"

    def import_data(self,sid,blob,source='uploaded'):
        dataset=process_csv(blob,source)
        with self.lock,self.store.connect() as c:
            s=self.store.session(sid,c)
            if s['active_decision']: raise BusinessError('先完成当前决策周期，再更换数据')
            c.execute('UPDATE sessions SET dataset=?,metrics=?,updated=? WHERE id=?',
                      (dumps(dataset),dumps(dataset['current']),now(),sid))
        return {'quality':dataset['quality'],'current':dataset['current']}

    def _build_decision(self,s,question,profile,constraints,parent=None,agent=None):
        agent=agent or DeepSARSA.from_bytes(s['model'],self.factors.registry.signature)
        company_evidence=self.store.retrieve_company_evidence(question)
        semantic=self.llm.extract(question,company_evidence=company_evidence)
        history=s['dataset']['daily']; bias=self.bias.analyze(history)
        state=self.factors.build(s['metrics'],profile,semantic['signals'],{x['name']:x['score'] for x in bias})
        context=context_from_metrics(s['metrics']); mask,reasons=action_mask(context,constraints)
        if not mask.any(): raise BusinessError('当前数据下没有能同时满足预算与毛利限制的离散动作。请核对业务上限，或先人工调整现有预算与价格。')
        action=agent.select_action(state['vector'],mask,explore=False); q=agent.q_values(state['vector'])
        importance=evaluate_factors(history,agent)
        record={'id':str(uuid.uuid4()),'timestamp':now(),'status':'draft','question':question,
                'model_version':self.version(s,agent),'state_vector':state['vector'],'factor_values':state['factors'],
                'factor_importance':importance,'factor_signature':state['signature'],'state_coverage':state['coverage'],
                'action':action,'action_name':ACTIONS[action].name,'action_label':ACTIONS[action].label,
                'q_values':[{'index':i,'name':a.name,'label':a.label,'q':float(q[i]),'legal':bool(mask[i]),
                             'reasons':reasons.get(a.name,[])} for i,a in enumerate(ACTIONS)],
                'q_selected':float(q[action]),'q_definition':'当前目标下折扣累计回报，非下一期利润',
                'expected_reward':MarketingEnvironment.forecast(s['metrics'],action,profile,constraints=constraints),
                'actual_reward':None,'reward_profile':profile.name,'reward_weights':list(map(float,profile.normalized_weights)),
                'user_feedback':None,'decision_source':'Deep SARSA','explanation_source':None,
                'semantic':semantic,'company_evidence':company_evidence,'bias':bias,'mask_reasons':reasons,'constraints':asdict(constraints),
                'context':context,'metrics':s['metrics'],'parent_decision':parent,
                'training_data_source':'合成环境预训练' if agent.updates else '未训练，建议先在实验室训练',
                'execution':None,'transition':None}
        record['explanation']=self.llm.explain(record)
        record['explanation_source']=record['explanation']['source']
        return record

    def decide(self,sid,request):
        if request.reward_profile not in PROFILES: raise BusinessError('未知经营目标')
        profile=PROFILES[request.reward_profile]
        if request.weights is not None:
            if set(request.weights)!=set(REWARD_KEYS): raise BusinessError('自定义权重必须完整包含 12 项指标')
            profile=RewardProfile(profile.name,tuple(request.weights[k] for k in REWARD_KEYS))
        if not set(request.constraints.stopped_channels).issubset(CHANNELS): raise BusinessError('停用渠道名称不合法')
        constraints=ActionConstraints(**request.constraints.model_dump())
        with self.lock:
            s=self.store.session(sid)
            if s['active_decision']: raise BusinessError('当前决策周期尚未结束，请到历史或决策中心继续执行 / 反馈')
            record=self._build_decision(s,request.question,profile,constraints)
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
                agent=DeepSARSA.from_bytes(s['model'],self.factors.registry.signature)
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
            seed=int(hashlib.sha256(record['id'].encode()).hexdigest()[:8],16)%100000
            env=MarketingEnvironment(seed=seed,profile=profile,calibration=record['metrics'],constraints=ActionConstraints(**record['constraints']))
            _,_,_,info=env.step(actual_action)
            return info['metrics'],{'source':'simulation','seed':seed,'label':'合成环境执行结果，不是企业实际业绩'}
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
        for key,k in [('douyin_share','抖音'),('xiaohongshu_share','小红书'),('private_share','私域')]:
            m[key]=budgets.get(k,0)/max(sum(budgets.values()),1)
        return m,{'source':'actual','label':'用户填报实际结果；未填指标保持缺失，未审计',
                  'budget_source':'实际总投入按执行渠道比例分配' if ads is not None else '执行后预算计划，非实测投入'}

    def feedback(self,sid,did,request):
        with self.lock:
            s=self.store.session(sid); record=self.store.decision(sid,did)
            if record['user_feedback']:
                if record['user_feedback']['request']!=request.model_dump(): raise BusinessError('该反馈已保存，不能改写已学习的经营结果')
                return {'decision':record,'next_decision':self.store.decision(sid,record['next_decision']) if record.get('next_decision') else None,'idempotent':True}
            if record['status']!='executed' or s['active_decision']!=did: raise BusinessError('先确认该策略已执行，再提交结果')
            metrics,provenance=self._outcome(record,request); profile=profile_from_record(record)
            metrics['date']=(datetime.fromisoformat(s['dataset']['daily'][-1]['date'])+timedelta(days=1)).date().isoformat()
            if record['execution'].get('forecast_revenue') is not None: metrics['forecast_revenue']=record['execution']['forecast_revenue']
            for k in ['reason','reason_category','supporting_experiment','anchor_value','current_evidence_conflict']: metrics[k]=record['execution'].get(k)
            reward=self.reward.calculate(metrics,profile)
            record['actual_reward']=reward; record['user_feedback']={'rating':request.rating,'mode':request.mode,
                       'provenance':provenance,'timestamp':now(),'request':request.model_dump()}
            dataset=s['dataset']; dataset['daily'].append(metrics); dataset['current']=metrics
            dataset['quality']['latest_result_source']=provenance['label']
            s['metrics']=metrics; s['dataset']=dataset
            agent=DeepSARSA.from_bytes(s['model'],self.factors.registry.signature)
            state=self.factors.build(metrics,profile,bias={x['name']:x['score'] for x in self.bias.analyze(dataset['daily'])})
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
            agent=DeepSARSA.from_bytes(s['model'],self.factors.registry.signature)
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
        s=self.store.session(sid); agent=DeepSARSA.from_bytes(s['model'],self.factors.registry.signature)
        manifest=ROOT/'data'/'training_report.json'; experiments=ROOT/'data'/'experiments.json'
        session_report=self.store.get_metadata(f'training:{sid}')
        return {'training':session_report or (self.base_report if s['config']['base_id']==self.base_id else None),
                'experiments':json.loads(experiments.read_text(encoding='utf-8')) if experiments.exists() else None,
                'importance':evaluate_factors(s['dataset']['daily'],agent),'updates':agent.updates,
                'model_version':self.version(s,agent),'network':str(agent.network),
                'epsilon':agent.epsilon,'config':asdict(agent.config),
                'current_state':self.factors.build(s['metrics'],PROFILES['balanced_growth'],bias={x['name']:x['score'] for x in self.bias.analyze(s['dataset']['daily'])}),
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
                cfg=SARSAConfig(**request.model_dump()); agent,report=original(cfg,progress=cb,calibration=s['metrics'])
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

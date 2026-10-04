from dataclasses import asdict
import copy
import numpy as np
from sarsa import DeepSARSA, TabularSARSA, SARSAConfig
from environments import MarketingEnvironment
from factor_engine import FactorEngine
from reward import PROFILES

def train(config=None,kind='deep',semantic=True,progress=None,calibration=None,warm_start_batches=0):
    config=config or SARSAConfig(); engine=FactorEngine()
    agent=DeepSARSA(engine.state_dim,config,engine.registry.signature) if kind=='deep' else TabularSARSA(config)
    curves=[]; profiles=list(PROFILES.values()); rng=np.random.default_rng(config.seed+818)
    warm_report=None
    if kind=='deep' and warm_start_batches:
        warm_report=terminal_warm_start(agent,profiles,rng,warm_start_batches,calibration,semantic)
    for ep in range(config.episodes):
        if ep%len(profiles)==0: order=rng.permutation(len(profiles))
        profile=profiles[order[ep%len(profiles)]]
        env=MarketingEnvironment(seed=config.seed+ep,horizon=config.horizon,profile=profile,calibration=calibration,diverse=True)
        state=env.state(semantic); action=agent.select_action(state,env.mask()[0]); rewards=[]; losses=[]; actions=[]; qs=[]
        for step in range(config.horizon):
            _,r,done,_=env.step(action); next_state=env.state(semantic); next_mask=env.mask()[0]
            next_action=None if done else agent.select_action(next_state,next_mask)
            before=float(agent.q_values(state)[action])
            record=agent.update(state,action,r,next_state,next_action,done,next_mask)
            rewards.append(r); losses.append(record['loss']); actions.append(action); qs.append(before)
            state,action=next_state,next_action
            if done: break
        agent.decay()
        curve={'episode':ep+1,'average_reward':float(np.mean(rewards)),'loss':float(np.mean(losses)),
               'epsilon':agent.epsilon,'average_q':float(np.mean(qs)),'last_action':actions[-1],
               'reward_profile':profile.name,'actions':actions,'rewards':rewards}
        curves.append(curve)
        if progress: progress(curve)
    return agent,{'config':asdict(config),'curves':curves,'source':'随机合成环境预训练，非企业实际业绩',
                  'environment_version':'marketing-v3-diverse-channels',
                  'algorithm':agent.algorithm,'semantic_state':semantic,'training_seed_start':config.seed,
                  'normalization_signature':engine.registry.signature,'warm_start':warm_report}

def terminal_warm_start(agent,profiles,rng,batches,calibration=None,semantic=True):
    states=[];rewards=[];masks=[]
    for i in range(210):
        env=MarketingEnvironment(seed=200000+agent.config.seed*1000+i,horizon=1,profile=profiles[i%len(profiles)],
                                 calibration=calibration if i%3==0 else None,diverse=True)
        mask=env.mask()[0];outcomes={}
        for action in np.flatnonzero(mask):
            branch=copy.deepcopy(env);_,_,done,info=branch.step(int(action));assert done
            outcomes[int(action)]=info['metrics']
        # Include every built-in objective for exactly the same initial business state.
        for profile in profiles:
            env.profile=profile;row=np.zeros(len(mask),dtype=np.float32)
            for action,metrics in outcomes.items(): row[action]=env.reward_engine.calculate(metrics,profile)['total']
            states.append(env.state(semantic));rewards.append(row);masks.append(mask)
    states=np.asarray(states,dtype=np.float32);rewards=np.asarray(rewards,dtype=np.float32);masks=np.asarray(masks,dtype=bool)
    losses=[]
    for i in range(batches):
        indices=rng.choice(len(states),size=min(128,len(states)),replace=False)
        losses.append(agent.warm_start_terminal_batch(states[indices],rewards[indices],masks[indices]))
    return {'source':'合成环境单期终止 SARSA 冷启动，合法动作使用共同随机数；未调用 LLM',
            'business_states':210,'objective_states':len(states),'terminal_transitions':int(masks.sum()),
            'optimizer_steps':batches,'final_loss':float(np.mean(losses[-20:])),'seed_start':200000+agent.config.seed*1000}

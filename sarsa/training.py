from dataclasses import asdict
import numpy as np
from sarsa import DeepSARSA, TabularSARSA, SARSAConfig
from environments import MarketingEnvironment
from factor_engine import FactorEngine
from reward import PROFILES

def train(config=None,kind='deep',semantic=True,progress=None,calibration=None):
    config=config or SARSAConfig(); engine=FactorEngine()
    agent=DeepSARSA(engine.state_dim,config,engine.registry.signature) if kind=='deep' else TabularSARSA(config)
    curves=[]; profiles=list(PROFILES.values())
    for ep in range(config.episodes):
        profile=profiles[ep%len(profiles)]
        env=MarketingEnvironment(seed=config.seed+ep,horizon=config.horizon,profile=profile,calibration=calibration)
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
                  'environment_version':'marketing-v2-history-bias',
                  'algorithm':agent.algorithm,'semantic_state':semantic,'training_seed_start':config.seed,
                  'normalization_signature':engine.registry.signature}

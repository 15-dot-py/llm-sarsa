from dataclasses import dataclass, asdict
import io
import random
import numpy as np
import torch
from torch import nn
from decision_models import ACTIONS

torch.set_num_threads(1)

@dataclass
class SARSAConfig:
    learning_rate: float = .0007
    gamma: float = .92
    epsilon: float = .8
    epsilon_decay: float = .985
    minimum_epsilon: float = .08
    episodes: int = 180
    horizon: int = 28
    hidden_size: int = 96
    gradient_clip: float = 5.
    optimizer: str = 'Adam'
    seed: int = 42
    architecture: str = 'mlp-v1'

    def __post_init__(self):
        if not 0<=self.gamma<=1 or not 0<=self.minimum_epsilon<=self.epsilon<=1:
            raise ValueError('gamma / epsilon 配置无效')
        if not 0<self.epsilon_decay<=1 or self.learning_rate<=0 or self.hidden_size<1 or self.gradient_clip<=0:
            raise ValueError('学习参数必须处于允许范围')
        if self.optimizer not in {'Adam','SGD'}: raise ValueError('仅支持 Adam / SGD')
        if self.architecture not in {'mlp-v1','dueling-v2'}: raise ValueError('未知 Q 网络结构')

class QNetwork(nn.Module):
    def __init__(self, state_dim, action_count, hidden):
        super().__init__()
        self.layers=nn.Sequential(nn.Linear(state_dim,hidden),nn.Tanh(),nn.Linear(hidden,hidden),nn.Tanh(),nn.Linear(hidden,action_count))
    def forward(self,state): return self.layers(state)

class DuelingQNetwork(nn.Module):
    """Separate the common state value from small differences between actions."""
    def __init__(self,state_dim,action_count,hidden):
        super().__init__()
        self.features=nn.Sequential(nn.Linear(state_dim,hidden),nn.Tanh(),nn.Linear(hidden,hidden),nn.Tanh())
        self.value=nn.Linear(hidden,1); self.advantage=nn.Linear(hidden,action_count)
    def forward(self,state):
        # Give the twelve objective weights a comparable scale to normalized factors.
        x=torch.cat((state[...,:-12],state[...,-12:]*8),dim=-1)
        h=self.features(x); advantage=self.advantage(h)
        return self.value(h)+advantage-advantage.mean(dim=-1,keepdim=True)

class DeepSARSA:
    algorithm = 'Deep SARSA'
    def __init__(self,state_dim,config=None,signature=''):
        self.config = config or SARSAConfig()
        torch.manual_seed(self.config.seed)
        self.rng=np.random.default_rng(self.config.seed)
        self.state_dim, self.signature = state_dim, signature
        cls_net=DuelingQNetwork if self.config.architecture=='dueling-v2' else QNetwork
        self.network=cls_net(state_dim,len(ACTIONS),self.config.hidden_size)
        cls=torch.optim.Adam if self.config.optimizer=='Adam' else torch.optim.SGD
        self.optimizer=cls(self.network.parameters(),lr=self.config.learning_rate)
        self.epsilon, self.updates = self.config.epsilon, 0
        self.loss_fn=nn.SmoothL1Loss()

    def q_values(self,state):
        x=np.asarray(state,dtype=np.float32)
        if x.shape != (self.state_dim,) or not np.isfinite(x).all(): raise ValueError('状态维度或数值无效')
        with torch.no_grad(): return self.network(torch.from_numpy(x)).numpy().copy()

    def select_action(self,state,mask,explore=True):
        legal=np.flatnonzero(mask)
        if not len(legal): raise ValueError('没有合法动作')
        if explore and self.rng.random()<self.epsilon: return int(self.rng.choice(legal))
        q=self.q_values(state)
        return int(legal[np.argmax(q[legal])])

    def update(self,state,action,reward,next_state,next_action,done=False,next_mask=None):
        if not np.isfinite(reward): raise ValueError('奖励不是有限数')
        if not isinstance(action,(int,np.integer)) or not 0<=action<len(ACTIONS): raise ValueError('当前动作索引无效')
        if not done and next_action is None: raise ValueError('SARSA 必须有下一实际动作')
        if not done and (not isinstance(next_action,(int,np.integer)) or not 0<=next_action<len(ACTIONS)): raise ValueError('下一动作索引无效')
        if not done and next_mask is not None and not next_mask[next_action]: raise ValueError('下一实际动作违反约束')
        self.q_values(state)
        if not done: self.q_values(next_state)
        s=torch.as_tensor(state,dtype=torch.float32)
        predicted=self.network(s)[action]
        with torch.no_grad():
            bootstrap=0. if done else float(self.network(torch.as_tensor(next_state,dtype=torch.float32))[next_action])
            target=torch.tensor(float(reward)+self.config.gamma*bootstrap,dtype=torch.float32)
        loss=self.loss_fn(predicted,target)
        self.optimizer.zero_grad(); loss.backward()
        grad=float(nn.utils.clip_grad_norm_(self.network.parameters(),self.config.gradient_clip))
        self.optimizer.step(); self.updates+=1
        return {'loss':float(loss.detach()),'q_before':float(predicted.detach()),'target':float(target),
                'bootstrap_q':bootstrap,'next_action':next_action,'reward':float(reward),'terminal':done,
                'gradient_norm':grad,'updates':self.updates,'algorithm':'on-policy SARSA (no max Q)'}

    def decay(self): self.epsilon=max(self.config.minimum_epsilon,self.epsilon*self.config.epsilon_decay)

    def warm_start_terminal_batch(self,states,rewards,masks):
        """One-period, terminal SARSA targets measured for each legal action.

        Each row uses common random innovations across the candidate actions.
        There is no bootstrap, expert action label or fabricated LLM decision.
        """
        states=np.asarray(states,dtype=np.float32); rewards=np.asarray(rewards,dtype=np.float32)
        masks=np.asarray(masks,dtype=bool)
        if states.ndim!=2 or states.shape[1]!=self.state_dim or rewards.shape!=(len(states),len(ACTIONS)) or masks.shape!=rewards.shape:
            raise ValueError('冷启动批次维度无效')
        if not np.isfinite(states).all() or not np.isfinite(rewards).all() or not masks.any():
            raise ValueError('冷启动批次数值或合法动作无效')
        predicted=self.network(torch.from_numpy(states)); target=torch.from_numpy(rewards); valid=torch.from_numpy(masks)
        # Fit R, then emphasize the paired differences that a shared value can hide.
        count=valid.sum(dim=1,keepdim=True).clamp(min=1)
        p_mean=(predicted*valid).sum(dim=1,keepdim=True)/count
        t_mean=(target*valid).sum(dim=1,keepdim=True)/count
        loss=self.loss_fn(predicted[valid],target[valid])+5*self.loss_fn((predicted-p_mean)[valid],(target-t_mean)[valid])
        self.optimizer.zero_grad();loss.backward();nn.utils.clip_grad_norm_(self.network.parameters(),self.config.gradient_clip)
        self.optimizer.step();self.updates+=1
        return float(loss.detach())

    def to_bytes(self):
        buf=io.BytesIO()
        torch.save({'state_dim':self.state_dim,'config':asdict(self.config),'signature':self.signature,
                    'network':self.network.state_dict(),'optimizer':self.optimizer.state_dict(),
                    'epsilon':self.epsilon,'updates':self.updates,'rng':self.rng.bit_generator.state},buf)
        return buf.getvalue()

    @classmethod
    def from_bytes(cls,blob,expected_signature=None):
        # Only internally created checkpoints are accepted; no checkpoint upload endpoint.
        c=torch.load(io.BytesIO(blob),map_location='cpu',weights_only=True)
        if expected_signature and c['signature']!=expected_signature: raise ValueError('因子签名与模型不一致')
        a=cls(c['state_dim'],SARSAConfig(**c['config']),c['signature'])
        a.network.load_state_dict(c['network']); a.optimizer.load_state_dict(c['optimizer'])
        a.epsilon=c['epsilon']; a.updates=c['updates']; a.rng.bit_generator.state=c['rng']
        return a

    def save(self,path):
        from pathlib import Path
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        Path(path).write_bytes(self.to_bytes())
    @classmethod
    def load(cls,path,expected_signature=None):
        from pathlib import Path
        return cls.from_bytes(Path(path).read_bytes(),expected_signature)

class TabularSARSA:
    algorithm='Tabular SARSA'
    def __init__(self,config=None):
        self.config=config or SARSAConfig(); self.table={}
        self.epsilon=self.config.epsilon; self.rng=np.random.default_rng(self.config.seed)
    def key(self,state):
        # Intentional compact baseline; coarse discretization loses full factor information.
        idx=[0,1,4,7,10,16,19,22,23]
        return tuple(int(np.clip(state[i],0,.999)*3) for i in idx)+tuple(round(float(x),2) for x in state[-12:])
    def q_values(self,state): return self.table.setdefault(self.key(state),np.zeros(len(ACTIONS)))
    def select_action(self,state,mask,explore=True):
        legal=np.flatnonzero(mask)
        if not len(legal): raise ValueError('没有合法动作')
        if explore and self.rng.random()<self.epsilon: return int(self.rng.choice(legal))
        q=self.q_values(state); return int(legal[np.argmax(q[legal])])
    def update(self,state,action,reward,next_state,next_action,done=False,next_mask=None):
        if not done and next_action is None: raise ValueError('缺少下一动作')
        if not done and next_mask is not None and not next_mask[next_action]: raise ValueError('下一动作不合法')
        q=self.q_values(state); target=reward+(0 if done else self.config.gamma*self.q_values(next_state)[next_action])
        q[action]+=.15*(target-q[action]); return {'loss':float((target-q[action])**2),'target':float(target)}
    def decay(self): self.epsilon=max(self.config.minimum_epsilon,self.epsilon*self.config.epsilon_decay)

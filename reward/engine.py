"""Versioned, dimensionless objective preferences; not an accounting formula."""
from dataclasses import dataclass, asdict
import math
import numpy as np

REWARD_KEYS = ['profit_margin', 'roi', 'conversion_rate', 'repeat_purchase_rate',
               'inventory_turnover', 'gmv_growth', 'new_customer_ratio',
               'cac', 'return_rate', 'promotion_cost_ratio', 'inventory_pressure', 'volatility']
BOUNDS = [(-.5,.4), (-1,3), (0,.12), (0,.8), (0,.3), (-.5,.5), (0,1),
          (0,200), (0,.2), (0,.4), (0,1), (0,.8)]

@dataclass(frozen=True)
class RewardProfile:
    name: str
    weights: tuple[float, ...]
    version: str = 'reward-v1'

    def __post_init__(self):
        if len(self.weights) != len(REWARD_KEYS) or any(not math.isfinite(w) or w < 0 for w in self.weights):
            raise ValueError('奖励权重须为 12 个有限非负数')
        if sum(self.weights) <= 0:
            raise ValueError('奖励权重总和必须大于零')

    @property
    def normalized_weights(self):
        return np.asarray(self.weights, dtype=np.float32) / sum(self.weights)

    def to_dict(self):
        return {**asdict(self), 'weights': dict(zip(REWARD_KEYS, map(float, self.normalized_weights)))}

PROFILES = {
    'profit_maximization': RewardProfile('profit_maximization', (5,4,1,1,1,1,0,2,1,3,1,1)),
    'growth_maximization': RewardProfile('growth_maximization', (1,1,3,1,1,5,3,1,1,1,1,1)),
    'inventory_clearance': RewardProfile('inventory_clearance', (2,1,2,1,6,3,1,1,1,1,5,1)),
    'customer_retention': RewardProfile('customer_retention', (2,2,2,6,1,1,0,1,2,1,1,1)),
    'new_customer_acquisition': RewardProfile('new_customer_acquisition', (1,1,3,0,1,3,6,3,1,1,1,1)),
    'acquisition_efficiency': RewardProfile('acquisition_efficiency', (2,5,3,1,1,1,2,6,1,1,1,1)),
    'balanced_growth': RewardProfile('balanced_growth', (3,3,2,2,2,2,1,2,1,1,2,1)),
}

class RewardEngine:
    def calculate(self, metrics: dict, profile: RewardProfile):
        contributions, missing = [], []
        w = profile.normalized_weights
        for i, (name, (lo, hi)) in enumerate(zip(REWARD_KEYS, BOUNDS)):
            raw = metrics.get(name)
            available = raw is not None and math.isfinite(float(raw))
            normalized = float(np.clip((float(raw)-lo)/(hi-lo), 0, 1)) if available else 0.
            if not available:
                missing.append(name)
            sign = 1 if i < 7 else -1
            value = float(w[i] * normalized * sign)
            contributions.append({'name': name, 'raw': raw, 'normalized': normalized,
                                  'weight': float(w[i]), 'sign': sign, 'contribution': value, 'available': available})
        return {'total': round(sum(x['contribution'] for x in contributions), 8),
                'contributions': contributions, 'missing': missing,
                'profile': profile.name, 'version': profile.version,
                'coverage': float(sum(w[i] for i,x in enumerate(contributions) if x['available']))}

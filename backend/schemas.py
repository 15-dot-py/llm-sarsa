from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
from reward import REWARD_KEYS

class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)

class ConstraintsInput(StrictModel):
    max_daily_budget: float=Field(18000,ge=0,le=1000000)
    min_gross_margin: float=Field(.15,ge=0,le=.9)
    min_price: float=Field(20,ge=1,le=10000)
    max_discount: float=Field(.35,ge=0,le=.5)
    clearance_min_inventory: float=Field(1000,ge=0,le=10000000)
    stopped_channels: list[str]=[]
    prohibited_promotions: bool=False

class DecisionInput(StrictModel):
    question: str=Field(min_length=2,max_length=1600)
    reward_profile: str='balanced_growth'
    weights: dict[str,float] | None=None
    constraints: ConstraintsInput=ConstraintsInput()

class ExecuteInput(StrictModel):
    action_name: str | None=None
    reason: str | None=Field(None,max_length=300)
    reason_category: Literal['business_evidence','competitor_follow','historical_anchor'] | None=None
    supporting_experiment: bool=False
    forecast_revenue: float | None=Field(None,ge=0)
    anchor_value: float | None=Field(None,ge=0)
    current_evidence_conflict: bool=False

class OutcomeInput(StrictModel):
    revenue: float=Field(ge=0,le=1e10)
    roi: float=Field(ge=-10,le=1000)
    cac: float=Field(ge=0,le=1e7)
    inventory_level: float=Field(ge=0,le=1e9)
    profit: float=Field(ge=-1e10,le=1e10)
    conversion_rate: float=Field(ge=0,le=1)
    repeat_purchase_rate: float | None=Field(None,ge=0,le=1)
    inventory_turnover: float | None=Field(None,ge=0,le=1)
    new_customer_ratio: float | None=Field(None,ge=0,le=1)
    return_rate: float | None=Field(None,ge=0,le=1)
    promotion_cost: float | None=Field(None,ge=0)
    advertising_cost: float | None=Field(None,ge=0)
    sales: float | None=Field(None,ge=0)

class FeedbackInput(StrictModel):
    rating: Literal['effective','neutral','ineffective']='neutral'
    mode: Literal['actual','simulation']='actual'
    outcome: OutcomeInput | None=None
    terminal: bool=False

class TrainInput(StrictModel):
    episodes: int=Field(40,ge=10,le=300)
    horizon: int=Field(21,ge=7,le=40)
    seed: int=Field(42,ge=0,le=100000)
    learning_rate: float=Field(.0007,ge=.00001,le=.02)
    gamma: float=Field(.92,ge=0,le=.99)
    epsilon: float=Field(.8,ge=.05,le=1)
    epsilon_decay: float=Field(.985,ge=.8,le=1)
    minimum_epsilon: float=Field(.08,ge=0,le=1)
    optimizer: Literal['Adam','SGD']='Adam'

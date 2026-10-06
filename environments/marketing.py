"""Stochastic channel response with bounded controls, saturation, carryover and inventory."""
import copy
import numpy as np
from decision_models.actions import CHANNELS, ACTIONS, apply_action, action_mask, ActionConstraints
from reward import RewardEngine, PROFILES
from factor_engine import FactorEngine
from bias_engine import BiasEngine

def metrics_from_rows(rows, previous_revenue=None):
    sums={k:sum(float(r.get(k,0) or 0) for r in rows) for k in
          ['sales','revenue','advertising_cost','promotion_cost','impressions','clicks','orders','new_customers','returning_customers','inventory','returns','cogs','return_loss']}
    rev=sums['revenue']; sales=sums['sales']; ads=sums['advertising_cost']; promo=sums['promotion_cost']
    profit=rev-sums['cogs']-ads-promo-sums['return_loss']
    customers=sums['new_customers']+sums['returning_customers']
    inv=sums['inventory']; initial=inv+sales
    m={'revenue':rev,'sales':sales,'profit':profit,'advertising_budget':ads,'promotion_cost':promo,
       'cogs':sums['cogs'],'return_loss':sums['return_loss'],
       'ctr':sums['clicks']/sums['impressions'] if sums['impressions']>0 else None,
       'conversion_rate':sums['orders']/sums['clicks'] if sums['clicks']>0 else None,
       'cac':ads/sums['new_customers'] if sums['new_customers']>0 else None,
       'roi':profit/(ads+promo) if ads+promo>0 else None,
       'roas':rev/ads if ads>0 else None,'aov':rev/sums['orders'] if sums['orders']>0 else None,
       'profit_margin':profit/rev if rev>0 else None,'repeat_purchase_rate':sums['returning_customers']/customers if customers>0 else None,
       'new_customer_ratio':sums['new_customers']/customers if customers>0 else None,
       'return_rate':sums['returns']/sales if sales>0 else None,'inventory_level':inv,'inventory_turnover':sales/initial if initial>0 else None,
       'inventory_pressure':float(np.clip(inv/max(sales,1)/60,0,1)),
       'gmv_growth':rev/max(previous_revenue,1)-1 if previous_revenue is not None else None,
       'price_level':float(np.average([float(r['price']) for r in rows],weights=[max(float(r['sales']),1) for r in rows])),
       'discount':float(np.mean([float(r.get('discount',0)) for r in rows])),
       'promotion_cost_ratio':promo/max(rev,1),'volatility':0.,
       'budgets':{r['channel']:float(r['advertising_cost']) for r in rows},
       'channel_roi':{},'channels':[], 'cost_method':'explicit cogs / explicit return loss'}
    for r in rows:
        denom=float(r['advertising_cost'])+float(r.get('promotion_cost',0))
        p=float(r['revenue'])-float(r.get('cogs',0))-denom-float(r.get('return_loss',0))
        roi=p/denom if denom>0 else None
        cac=float(r['advertising_cost'])/float(r['new_customers']) if float(r['new_customers'])>0 else None
        m['channel_roi'][r['channel']]=roi if roi is not None else 0.
        m['channels'].append({'channel':r['channel'],'revenue':float(r['revenue']),'advertising_cost':float(r['advertising_cost']),
                              'profit':p,'roi':roi,'cac':cac,'inventory':float(r['inventory']),
                              'conversion_rate':float(r['orders'])/float(r['clicks']) if float(r['clicks'])>0 else None})
        prefix=dict(zip(CHANNELS,['douyin','xiaohongshu','taobao','search','private']))[r['channel']]
        m[f'{prefix}_roi']=roi; m[f'{prefix}_cac']=cac
        if r['channel']=='抖音': m['douyin_cac']=cac; m['douyin_roi']=roi
    for name,ch in [('douyin_share','抖音'),('xiaohongshu_share','小红书'),('private_share','私域'),('taobao_share','淘宝'),('search_share','搜索广告')]:
        m[name]=m['budgets'].get(ch,0)/max(ads,1)
    return m

def context_from_metrics(m):
    unit_cost=float(m.get('unit_cost') or m.get('price_level',55)*.58)
    return {'budgets':{k:float(m.get('budgets',{}).get(k,0)) for k in CHANNELS},
            'inventory':float(m.get('inventory_level') or 0), 'price':float(m.get('list_price') or m.get('price_level') or 55),
            'discount':float(m.get('discount') or 0),'coupon':float(m.get('promotion_cost_ratio') or 0),
            'unit_cost':unit_cost,'channel_roi':m.get('channel_roi',{})}

class MarketingEnvironment:
    def __init__(self,seed=42,horizon=28,profile=None,calibration=None,constraints=None,diverse=False):
        self.seed=seed; self.rng=np.random.default_rng(seed); self.horizon=horizon
        self.profile=profile or PROFILES['balanced_growth']; self.constraints=constraints or ActionConstraints()
        self.factor_engine=FactorEngine(); self.reward_engine=RewardEngine(); self.calibration=calibration
        self.diverse=diverse; self.observation_missing=set()
        self.reset()

    def reset(self):
        self.observation_missing=set()
        self.t=0; self.history=[]; self.demand=float(self.rng.uniform(.85,1.15)); self.competitor=float(self.rng.uniform(.1,.65))
        self.traffic=float(self.rng.uniform(-.15,.15)); self.loyalty=float(self.rng.uniform(.3,.55))
        self.efficiency=np.array([1.05,.75,1.1,1.2,.65])
        budgets=dict(zip(CHANNELS,[2400.,1200.,2000.,1000.,600.]))
        self.context={'budgets':budgets,'inventory':float(self.rng.uniform(18000,36000)),
                      'price':55.,'discount':.08,'coupon':.01,'unit_cost':29.,'channel_roi':{k:.5 for k in CHANNELS}}
        if self.diverse and not self.calibration:
            total=float(self.rng.uniform(1800,15000))
            self.context['budgets']=dict(zip(CHANNELS,(self.rng.dirichlet(np.ones(5)*2)*total).tolist()))
            self.context.update(inventory=float(self.rng.uniform(1500,95000)),price=float(self.rng.uniform(35,85)),
                                discount=float(self.rng.uniform(0,.22)),coupon=float(self.rng.uniform(0,.03)))
            self.context['unit_cost']=self.context['price']*float(self.rng.uniform(.32,.56))
            self.efficiency*=self.rng.uniform(.55,1.65,size=5)
            self.loyalty=float(self.rng.uniform(.18,.7)); self.demand=float(self.rng.uniform(.6,1.4))
        if self.calibration:
            self.context=context_from_metrics(self.calibration)
            # Preserve observed initial channel allocation, cap total at safety limit.
            total=sum(self.context['budgets'].values())
            if total>self.constraints.max_daily_budget:
                scale=self.constraints.max_daily_budget/total
                self.context['budgets']={k:v*scale for k,v in self.context['budgets'].items()}
        self.stock={k:self.context['inventory']/len(CHANNELS) for k in CHANNELS}
        self.carryover={k:float(v)*.25 for k,v in self.context['budgets'].items()}
        self.metrics=dict(self.calibration or {'roi':.5,'profit_margin':.13,'conversion_rate':.032,'ctr':.023,
                    'repeat_purchase_rate':self.loyalty,'gmv_growth':0.,'inventory_turnover':.04,'cac':55.,
                    'return_rate':.03,'promotion_cost_ratio':.01,'inventory_pressure':.7,
                    'inventory_level':self.context['inventory'],'price_level':55.,'discount':.08,
                    'advertising_budget':7200.,'new_customer_ratio':1-self.loyalty,'douyin_share':1/3,
                    'xiaohongshu_share':1/6,'private_share':1/12,'douyin_cac':65.,'douyin_roi':.2,
                    'revenue':40000.,'profit':5200.,'sales':800.,'volatility':0.})
        self._externals(); self._bias_metrics()
        if self.diverse:
            # Start from a measured synthetic day rather than invented fixed ROI/CAC.
            self.step(len(ACTIONS)-1)
            self.t=0; self.history=[]; self._externals(); self._bias_metrics()
            self.observation_missing={k for k in ['seasonality','holiday_index','competitor_intensity',
                'platform_traffic_change','market_demand_index'] if self.rng.random()<.5}
        return self.state()

    def _bias_metrics(self):
        for signal in BiasEngine().analyze(self.history):
            self.metrics[signal['name']]=signal['score']

    def _externals(self):
        self.metrics.update(seasonality=1+.15*np.sin((self.t+7)/28*2*np.pi),
                            holiday_index=float(12<=self.t%28<=17),competitor_intensity=self.competitor,
                            platform_traffic_change=self.traffic,market_demand_index=self.demand)

    def state(self,semantic=True):
        m=dict(self.metrics)
        for k in self.observation_missing: m[k]=None
        if not semantic:
            for k in ['seasonality','holiday_index','competitor_intensity','platform_traffic_change','market_demand_index']: m[k]=None
        return self.factor_engine.build(m,self.profile)['vector']

    def mask(self): return action_mask(self.context,self.constraints)

    def step(self,action):
        mask,reasons=self.mask()
        if not mask[action]: raise ValueError('动作违反约束：'+str(reasons))
        oldrev=self.metrics.get('revenue',40000.)
        self.context=apply_action(self.context,action)
        # Exogenous innovations are action-independent and always draw the same number of values.
        self.demand=float(np.clip(.8*self.demand+.2+self.rng.normal(0,.045),.5,1.5))
        self.competitor=float(np.clip(self.competitor+self.rng.normal(0,.03),0,1))
        self.traffic=float(np.clip(.7*self.traffic+self.rng.normal(0,.05),-.4,.4))
        self._externals()
        rows=[]; price=self.context['price']*(1-self.context['discount'])
        efficiency=self.efficiency; cpm=[18,24,15,20,10]
        for i,k in enumerate(CHANNELS):
            budget=self.context['budgets'].get(k,0); lag=self.carryover.get(k,0)
            self.carryover[k]=.6*lag+.4*budget
            exposure=(.8*budget+.2*lag)/cpm[i]*1000
            exposure*=float(np.exp(self.rng.normal(0,.055)))*(1+self.traffic)
            clicks=exposure*(.025 if k!='私域' else .04)*float(np.exp(self.rng.normal(0,.04)))
            saturation=1/(1+budget/5500)
            trend=1-(.2*self.t/max(self.horizon,1) if k=='抖音' else 0)
            cv=.035*efficiency[i]*saturation*self.demand*(1+.32*self.metrics['holiday_index'])
            cv*=self.metrics['seasonality']*(1-.25*self.competitor)*trend
            cv*=np.exp(-1.4*(price/50-1))*(1+2*self.context['coupon'])
            if k=='私域': cv*=1+self.loyalty
            orders=int(max(0,clicks*cv*float(np.exp(self.rng.normal(0,.07)))))
            replenishment=100+80*self.demand # deliberately limited replenishment, inventory consequences persist
            available=self.stock[k]+replenishment
            sales=min(orders,int(available)); self.stock[k]=max(0,available-sales)
            returning=int(sales*(self.loyalty if k=='私域' else .18))
            revenue=sales*price; promo=revenue*self.context['coupon']
            returns=int(sales*np.clip(.025+.12*self.context['discount']+self.rng.normal(0,.004),0,.2))
            rows.append({'date':str(self.t),'channel':k,'sales':sales,'orders':sales,'revenue':revenue,
                         'price':price,'discount':self.context['discount'],'advertising_cost':budget,
                         'impressions':int(exposure),'clicks':int(clicks),'new_customers':sales-returning,
                         'returning_customers':returning,'promotion_cost':promo,'inventory':self.stock[k],
                         'returns':returns,'cogs':sales*self.context['unit_cost'],'return_loss':returns*price*.7})
        self.metrics=metrics_from_rows(rows,oldrev); self._externals()
        self.metrics['list_price']=self.context['price']; self.metrics['unit_cost']=self.context['unit_cost']
        self.metrics['volatility']=abs(self.metrics['gmv_growth'])
        self.context['inventory']=self.metrics['inventory_level']; self.context['channel_roi']=self.metrics['channel_roi']
        self.loyalty=float(np.clip(self.loyalty+.008*(self.context['budgets'].get('私域',0)/600-1)-.003*self.competitor,.15,.8))
        self.t+=1
        self.metrics['date']=str(self.t)
        self.history.append(copy.deepcopy(self.metrics)); self._bias_metrics()
        reward=self.reward_engine.calculate(self.metrics,self.profile)
        return self.state(),reward['total'],self.t>=self.horizon,{'metrics':copy.deepcopy(self.metrics),'rows':rows,'reward':reward,'context':copy.deepcopy(self.context)}

    @classmethod
    def forecast(cls,metrics,action,profile,samples=24,constraints=None):
        rewards=[]
        for seed in range(900,900+samples):
            env=cls(seed=seed,profile=profile,calibration=metrics,constraints=constraints)
            if not env.mask()[0][action]: continue
            _,r,_,_=env.step(action); rewards.append(r)
        if not rewards: return {'mean':None,'low':None,'high':None,'source':'仿真情景不可用','n':0}
        return {'mean':float(np.mean(rewards)),'low':float(np.quantile(rewards,.1)),
                'high':float(np.quantile(rewards,.9)),'n':len(rewards),
                'source':'合成环境下一期奖励情景；10%–90% 分位区间，非实际效果预测'}

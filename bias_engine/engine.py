import numpy as np

LABELS={'sunk_cost_score':'沉没成本风险','herding_score':'从众风险','loss_aversion_score':'损失厌恶风险',
        'overconfidence_score':'过度自信风险','recency_bias_score':'近期偏差风险','anchoring_score':'锚定风险'}

class BiasEngine:
    def analyze(self,history):
        results=[]; n=len(history)
        for key,label in LABELS.items():
            score=None; evidence=[]
            if n>=3 and key=='sunk_cost_score':
                pairs=[(a,b) for a,b in zip(history[:-1],history[1:]) if a.get('roi') is not None and a['roi']<0 and a.get('advertising_budget') is not None and b.get('advertising_budget') is not None]
                if pairs:
                    bad=[(a,b) for a,b in pairs if b.get('advertising_budget',0)>a.get('advertising_budget',0)*1.03]
                    score=len(bad)/len(pairs); evidence=[{'date':b.get('date'),'prior_roi':a['roi'],'prior_budget':a.get('advertising_budget'),'budget':b.get('advertising_budget')} for a,b in bad][-6:]
                else: score=0.; evidence=[{'observations':n,'negative_roi_pairs':0}]
                # Evaluate per-channel persistence too: total ROI may hide a losing channel.
                channels={x['channel'] for m in history for x in m.get('channels',[])}
                for channel in channels:
                    observations=[]
                    for m in history:
                        row=next((x for x in m.get('channels',[]) if x['channel']==channel),None)
                        if row: observations.append({**row,'date':m.get('date')})
                    pairs=[(a,b) for a,b in zip(observations[:-1],observations[1:]) if a.get('roi') is not None and a['roi']<0]
                    if len(pairs)<2: continue
                    bad=[(a,b) for a,b in pairs if b['advertising_cost']>a['advertising_cost']*1.03]
                    channel_score=len(bad)/len(pairs)
                    if channel_score>score:
                        score=channel_score
                        evidence=[{'channel':channel,'date':b['date'],'prior_roi':a['roi'],'prior_budget':a['advertising_cost'],'budget':b['advertising_cost']} for a,b in bad][-6:]
            if n>=3 and key=='loss_aversion_score':
                pairs=[(a,b) for a,b in zip(history[:-1],history[1:]) if a.get('profit') is not None and a['profit']<0 and a.get('advertising_budget') is not None and b.get('advertising_budget') is not None]
                bad=[(a,b) for a,b in pairs if b.get('advertising_budget',0)>=a.get('advertising_budget',0)*.98]
                score=len(bad)/len(pairs) if pairs else 0.
                evidence=[{'date':b.get('date'),'prior_profit':a.get('profit'),'budget':b.get('advertising_budget')} for a,b in bad][-6:] or [{'observations':n,'negative_profit_pairs':len(pairs)}]
            if key=='overconfidence_score':
                usable=[x for x in history if x.get('forecast_revenue') is not None and x.get('revenue',0)>0]
                if len(usable)>=3:
                    gaps=[max(0,x['forecast_revenue']/x['revenue']-1) for x in usable]
                    score=float(np.clip(np.mean(gaps),0,1)); evidence=[{'date':x.get('date'),'forecast':x['forecast_revenue'],'actual':x['revenue']} for x in usable[-6:]]
            if n>=7 and key=='recency_bias_score':
                usable=[x for x in history[-14:] if x.get('advertising_budget') is not None and x.get('revenue') is not None]
                if len(usable)<7:
                    results.append({'name':key,'label':label,'score':None,'evidence':[],'status':'evidence_insufficient','interpretation':'预算记录不足'})
                    continue
                budgets=np.array([x['advertising_budget'] for x in usable]); rev=np.array([x['revenue'] for x in usable])
                shifts=np.diff(budgets)/np.maximum(budgets[:-1],1); noise=np.std(rev)/max(np.mean(rev),1)
                reversals=int(sum(shifts[1:]*shifts[:-1]<0))
                score=float(np.clip(reversals/max(len(shifts)-1,1)*min(noise/.2,1),0,1))
                evidence=[{'dates':[x.get('date') for x in usable],'budget_reversals':reversals,'revenue_cv':float(noise)}]
            if key=='herding_score':
                usable=[x for x in history if (x.get('reason_category') or x.get('reason'))=='competitor_follow']
                if usable:
                    score=sum(not x.get('supporting_experiment') for x in usable)/len(usable)
                    evidence=[{'date':x.get('date'),'reason':x.get('reason'),'has_experiment':bool(x.get('supporting_experiment'))} for x in usable]
            if key=='anchoring_score':
                usable=[x for x in history if (x.get('reason_category') or x.get('reason'))=='historical_anchor']
                if usable:
                    score=sum(bool(x.get('current_evidence_conflict')) for x in usable)/len(usable)
                    evidence=[{'date':x.get('date'),'anchor':x.get('anchor_value'),'conflict':bool(x.get('current_evidence_conflict'))} for x in usable]
            results.append({'name':key,'label':label,'score':score,'evidence':evidence,
                            'status':'evidence_insufficient' if score is None else 'computed',
                            'interpretation':'可核查的操作风险信号，不能据此诊断人员心理'})
        return results

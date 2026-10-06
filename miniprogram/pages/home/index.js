const api=require('../../utils/api');
const PROFILES=[{name:'auto',label:'根据问题识别目标'},{name:'profit_maximization',label:'利润优先'},{name:'growth_maximization',label:'销售增长'},{name:'inventory_clearance',label:'库存消化'},{name:'customer_retention',label:'客户留存'},{name:'new_customer_acquisition',label:'新客拓展'},{name:'acquisition_efficiency',label:'获客效率'},{name:'balanced_growth',label:'均衡经营'}];
const STATES={draft:'等待执行确认',executed:'等待经营结果',awaiting_next:'等待下一动作',updated:'已完成学习',terminal:'周期已结束',cancelled:'已取消'};
function num(v,d=2){return v==null||!Number.isFinite(v)?'—':Number(v).toFixed(d);}
function viewRecord(d){if(!d)return null;return {...d,statusLabel:STATES[d.status]||d.status,legalActions:d.q_values.filter(q=>q.legal),qRows:d.q_values.map(q=>({...q,qLabel:num(q.q,5)})),rewardLabel:d.actual_reward?num(d.actual_reward.total,5):'—'};}
Page({data:{loading:true,busy:false,error:'',panel:'work',user:null,dashboard:null,record:null,history:[],profiles:PROFILES,profileIndex:0,
  question:'坚果大促前，库存较多，竞品正在降价。如何在毛利底线内调整渠道投入和促销？',budget:'18000',floor:'20',margin:'0.15',noPromo:false,stopped:[],showConstraints:false,showQ:false,actionIndex:0,reason:'',terminal:false,feedback:{},sourceMode:'actual',tabs:[{id:'work',name:'工作台'},{id:'data',name:'数据库'},{id:'history',name:'记录'},{id:'model',name:'模型'}]},
  async onLoad(){try{const user=await api.ensureLogin();if(!user)return;this.setData({user});await this.refresh();}catch(e){this.setData({error:e.message});}finally{this.setData({loading:false});}},
  async onPullDownRefresh(){try{await this.refresh();}catch(e){this.setData({error:e.message});}finally{wx.stopPullDownRefresh();}},
  async refresh(){const [d,h]=await Promise.all([api.request('/dashboard'),api.request('/decisions')]);const active=d.active_decision;
    this.setData({dashboard:d,metrics:[{name:'营销 ROI',value:num(d.metrics.roi)},{name:'广告获客成本',value:'¥'+num(d.metrics.cac)},{name:'贡献利润',value:'¥'+num(d.metrics.profit,0)},{name:'库存',value:num(d.metrics.inventory_level,0)+' 件'}],
      channels:d.metrics.channels.map(ch=>({...ch,revenueText:num(ch.revenue,0),costText:num(ch.advertising_cost,0),roiText:num(ch.roi),cacText:num(ch.cac)})),history:h.map(viewRecord),activeId:active?active.id:''});
    if(active)this.setRecord(active);},
  setRecord(d){const r=viewRecord(d);this.setData({record:r,actionIndex:r?Math.max(0,r.legalActions.findIndex(q=>q.name===r.action_name)):0,reason:'',feedback:{},terminal:false});},
  async run(job){if(this.data.busy)return;this.setData({busy:true,error:''});try{await job();}catch(e){this.setData({error:e.message});if(e.status===401)wx.redirectTo({url:'/pages/login/index'});}finally{this.setData({busy:false});}},
  input(e){this.setData({[e.currentTarget.dataset.field]:e.detail.value});},
  feedbackInput(e){this.setData({['feedback.'+e.currentTarget.dataset.field]:e.detail.value});},
  profile(e){this.setData({profileIndex:Number(e.detail.value)});},
  action(e){this.setData({actionIndex:Number(e.detail.value)});},
  toggleConstraints(){this.setData({showConstraints:!this.data.showConstraints});},toggleQ(){this.setData({showQ:!this.data.showQ});},
  noPromo(e){this.setData({noPromo:e.detail.value});},terminal(e){this.setData({terminal:e.detail.value});},stopped(e){this.setData({stopped:e.detail.value});},
  panel(e){const id=e.currentTarget.dataset.id;this.setData({panel:id});if(id==='model')this.run(async()=>{const [r,l]=await Promise.all([api.request('/reward'),api.request('/lab')]);this.setData({reward:r,lab:l});});},
  generate(){this.run(async()=>{if(this.data.activeId)throw new Error('请先完成或取消当前决策');
    const {question,budget,floor,margin}=this.data;
    if(question.trim().length<2||![budget,floor,margin].every(x=>x.trim()!==''&&Number.isFinite(Number(x))))throw new Error('请完整填写经营问题和业务约束');
    const d=await api.request('/decisions',{question,reward_profile:PROFILES[this.data.profileIndex].name,constraints:{max_daily_budget:Number(budget),min_price:Number(floor),min_gross_margin:Number(margin),prohibited_promotions:this.data.noPromo,stopped_channels:this.data.stopped}},'POST');this.setRecord(d);await this.refresh();});},
  execute(){this.run(async()=>{const d=this.data.record;const q=d.legalActions[this.data.actionIndex];if(q.name!==d.action_name&&!this.data.reason.trim())throw new Error('请填写人工调整理由');
    const r=await api.request('/decisions/'+d.id+'/execute',{action_name:q.name,reason:this.data.reason||null},'POST');this.setRecord(r);await this.refresh();});},
  feedback(){this.run(async()=>{const d=this.data.record;const fields=['revenue','profit','roi','cac','inventory_level','conversion_rate'];const values=this.data.feedback;const outcome={};
    for(const key of fields){if(values[key]==null||String(values[key]).trim()===''||!Number.isFinite(Number(values[key])))throw new Error('请完整填写六项实际经营指标');outcome[key]=Number(values[key]);}
    const r=await api.request('/decisions/'+d.id+'/feedback',{mode:'actual',rating:'neutral',terminal:this.data.terminal,outcome},'POST');this.setRecord(r.next_decision||r.decision);await this.refresh();});},
  cancel(){this.run(async()=>{await api.request('/decisions/'+this.data.record.id+'/cancel',{},'POST');this.setRecord(null);await this.refresh();});},
  finish(){this.run(async()=>{const id=this.data.record.parent_decision;if(!id)throw new Error('没有待结束的上一轮周期');const d=await api.request('/decisions/'+id+'/finish',{},'POST');this.setRecord(d);await this.refresh();});},
  newDecision(){if(this.data.activeId){wx.showToast({title:'请先完成当前决策',icon:'none'});return;}this.setRecord(null);this.setData({panel:'work'});},
  openRecord(e){const d=this.data.history.find(x=>x.id===e.currentTarget.dataset.id);if(d){this.setRecord(d);this.setData({panel:'work'});}},
  upload(){if(this.data.busy)return;wx.chooseMessageFile({count:1,type:'file',extension:['csv'],success:r=>{const file=r.tempFiles[0];if(file)this.run(async()=>{await api.upload(file.path);this.setRecord(null);await this.refresh();wx.showToast({title:'CSV 已导入',icon:'success'});});},fail:()=>this.setData({error:'未选择 CSV 文件'})});},
  demo(){this.run(async()=>{await api.request('/data/demo',{},'POST');this.setRecord(null);await this.refresh();});},
  account(){wx.showActionSheet({itemList:['隐私说明','退出登录','注销账号'],success:r=>{if(r.tapIndex===0)wx.navigateTo({url:'/pages/privacy/index'});if(r.tapIndex===1)this.logout();if(r.tapIndex===2)wx.showModal({title:'注销账号',content:'将删除此账号的工作区、决策和登录凭证。此操作无法撤销。',confirmText:'确认注销',success:v=>{if(v.confirm)this.removeAccount();}});}});},
  logout(){this.run(async()=>{await api.request('/auth/logout',{},'POST');api.clear();wx.redirectTo({url:'/pages/login/index'});});},
  removeAccount(){this.run(async()=>{await api.request('/auth/account',undefined,'DELETE');api.clear();wx.redirectTo({url:'/pages/login/index'});});},
  onShareAppMessage(){return {title:'深谋远虑营销工作台',path:'/pages/home/index'};}
});

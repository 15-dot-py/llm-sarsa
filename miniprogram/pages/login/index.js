const api=require('../../utils/api');const config=require('../../config');
Page({data:{phone:'',code:'',phoneValid:false,codeValid:false,accepted:false,ready:false,busy:false,challenge:'',remaining:0,message:'正在检查登录服务…',error:''},
  async onLoad(){try{const status=await api.request('/auth/status',undefined,'GET',true);this.setData({ready:status.sms_ready,message:status.sms_ready?'':status.message});}catch(e){this.setData({message:'',error:e.message});}},
  onUnload(){if(this.timer)clearInterval(this.timer);},
  phoneInput(e){const phone=e.detail.value.replace(/\D/g,'');this.setData({phone,phoneValid:/^1[3-9]\d{9}$/.test(phone),code:'',codeValid:false,challenge:''});},
  codeInput(e){const code=e.detail.value.replace(/\D/g,'');this.setData({code,codeValid:/^\d{6}$/.test(code)});},
  consent(e){this.setData({accepted:e.detail.value.includes('accepted')});},privacy(){wx.navigateTo({url:'/pages/privacy/index'});},
  async send(){if(this.data.busy||this.data.remaining||!this.data.ready||!this.data.phoneValid||!this.data.accepted)return;
    this.setData({busy:true,error:'',message:''});const phone=this.data.phone;
    try{const result=await api.request('/auth/sms/request',{phone,privacy_accepted:true,privacy_version:config.privacyVersion},'POST',true);
      // A phone edit during the network request must not apply an old challenge.
      if(this.data.phone!==phone)return;
      this.setData({challenge:result.challenge_id,message:result.message,remaining:result.retry_after});this.deadline=Date.now()+result.retry_after*1000;
      if(this.timer)clearInterval(this.timer);this.timer=setInterval(()=>this.setData({remaining:Math.max(0,Math.ceil((this.deadline-Date.now())/1000))}),1000);
    }catch(e){this.setData({error:e.message});}finally{this.setData({busy:false});}},
  async login(){if(this.data.busy||!this.data.challenge||!this.data.codeValid||!this.data.accepted||!this.data.ready)return;
    this.setData({busy:true,error:''});try{const result=await api.request('/auth/sms/verify',{phone:this.data.phone,code:this.data.code,challenge_id:this.data.challenge,privacy_accepted:true,privacy_version:config.privacyVersion},'POST',true);api.save(result);wx.redirectTo({url:'/pages/home/index'});}
    catch(e){this.setData({error:e.message});}finally{this.setData({busy:false});}}
});

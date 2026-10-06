const config=require('../config');
const TOKEN='shenmou-auth-v1',SESSION='shenmou-session-v1';
function authHeaders(){const token=wx.getStorageSync(TOKEN),sid=wx.getStorageSync(SESSION);return {'Authorization':token?'Bearer '+token:'','X-Session-Id':sid||''};}
function request(path,data,method='GET',publicRequest=false){
  return new Promise((resolve,reject)=>wx.request({url:config.baseUrl+'/api'+path,method,data,timeout:120000,
    header:{'Content-Type':'application/json',...(publicRequest?{}:authHeaders())},
    success(response){if(response.statusCode>=200&&response.statusCode<300)resolve(response.data);else{if(response.statusCode===401&&!publicRequest)clear();const error=new Error(typeof response.data.detail==='string'?response.data.detail:'请求失败，请检查输入');error.status=response.statusCode;reject(error);}},
    fail(){reject(new Error('无法连接工作台，请检查网络和服务状态'));}}));
}
function save(value){wx.setStorageSync(TOKEN,value.access_token);wx.setStorageSync(SESSION,value.session_id);}
function clear(){wx.removeStorageSync(TOKEN);wx.removeStorageSync(SESSION);}
async function ensureLogin(){
  if(!wx.getStorageSync(TOKEN)){wx.redirectTo({url:'/pages/login/index'});return false;}
  try{const value=await request('/auth/me');wx.setStorageSync(SESSION,value.session_id);return value.user;}
  catch(error){if(error.status===401){clear();wx.redirectTo({url:'/pages/login/index'});return false;}throw error;}
}
function upload(path){return new Promise((resolve,reject)=>wx.uploadFile({url:config.baseUrl+'/api/data/upload',filePath:path,name:'file',header:authHeaders(),timeout:120000,
  success(r){try{const value=JSON.parse(r.data);if(r.statusCode>=200&&r.statusCode<300)resolve(value);else{if(r.statusCode===401)clear();const error=new Error(typeof value.detail==='string'?value.detail:'CSV 校验失败');error.status=r.statusCode;reject(error);}}catch(e){reject(new Error('上传返回异常'));}},fail(){reject(new Error('CSV 上传失败，请检查网络'));}}));}
module.exports={request,save,clear,ensureLogin,upload};

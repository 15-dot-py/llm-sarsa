# 微信小程序迁移方案

## 保留
现有 FastAPI、Factor Engine、Deep SARSA、Reward、Bias、LLM、SQLite 结构保持不变。

## 新增
- 原生微信小程序前端
- CloudBase 手机短信验证码登录
- CloudBase user_id -> 平台 session 映射
- 首页、智能决策、决策记录、我的四个移动端页面

## 后端接入点
在 backend.main 中引入：
from backend.miniapp_auth import cloudbase_user,authenticated_session

并增加：
@app.post('/api/auth/session')
async def new_authenticated_session(uid=Depends(cloudbase_user)):
    return {**authenticated_session(platform,uid),'user_id':uid}

这样不会改变网页现有的匿名 /api/session 流程。

## 下一阶段
- 在决策详情中加入“确认执行”和“结果反馈”
- 适配 CSV 上传（wx.chooseMessageFile）
- 增加企业资料、模型因子、Q 值与屏蔽原因页面
- 小程序码生成与比赛落地页
- 完成 CloudBase 真环境联调和微信审核

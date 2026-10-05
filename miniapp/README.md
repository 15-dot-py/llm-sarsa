# 深谋远虑微信小程序

本目录是现有“深谋远虑”营销决策平台的微信小程序前端。它不会重写 Deep SARSA、Factor Engine、Reward Engine 或 LLM 逻辑，而是继续调用现有 FastAPI 服务。

## 架构
- 微信小程序：移动端 UI、手机号短信验证码登录
- CloudBase Auth：短信 OTP 身份认证
- Render / FastAPI：现有营销决策 API
- PyTorch Deep SARSA：仍由后端决定营销动作
- SQLite：现有会话、决策、转移和模型状态

## 首次配置
1. 在微信公众平台注册小程序并取得 AppID。
2. 在 CloudBase 创建上海地域环境，开启手机号验证码登录，配置短信签名和模板。
3. 编辑 miniprogram/config.js：填 CloudBase 环境 ID；API 默认使用 https://shenmou-marketing.onrender.com
4. Render 新增环境变量 CLOUDBASE_TOKEN_INTROSPECT_URL。
5. 微信公众平台把 https://shenmou-marketing.onrender.com 加入 request 合法域名。
6. 在 miniapp/miniprogram 运行 npm install，再在微信开发者工具“构建 npm”。
7. 将 project.config.json 的 appid 换成真实 AppID。

## 原则
- 不在小程序中放 OpenAI、DeepSeek 或腾讯云 SecretKey。
- 网页端 POST /api/session 保留，避免影响现有站点。
- 小程序通过 POST /api/auth/session 把 CloudBase 用户映射到后端会话。
- 同一用户会复用同一平台 session，便于保留历史决策和 SARSA 在线更新。

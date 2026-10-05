# 免费 LLM 接口与验证边界

2026年10月5日，后端新增 OpenRouter 免费接口。SARSA 网络、动作空间、奖励和实际下一动作更新链路保持既有职责；免费 LLM 负责结构化理解和解释已确定的动作。

## 调用方式

- 服务地址为官方 `https://openrouter.ai/api/v1`。
- 默认模型为 `openrouter/free`；允许具体模型的 `:free` 版本，拒绝付费模型及 `openrouter/auto:free` 等歧义配置。
- 请求采用 Chat Completions 和严格 JSON Schema，本地 Pydantic 再校验。输入、输出及每请求价格上限均为零，没有付费回退配置。
- 完整决策通常需要两次调用：先提取业务信号，SARSA 选择动作后再解释。
- 每日调用数按 UTC 重置，当前免费接口上限为 50；服务商自身限额仍会独立生效。
- 语义与解释记录保存服务返回的实际模型名称，另存请求模型名。免费路由选择的具体模型可能变化。
- 无密钥、超时、限频、无效结构或动作不匹配时明确显示规则/模板来源。密钥只读取后端环境变量，既有 OpenAI 密钥不会被免费接口使用。

## 已完成的检查

50 项 Python 测试通过；前端 TypeScript 和生产构建通过。新增测试覆盖免费请求参数、付费路由拦截、来源记录、无效/截断响应拒绝、每日限额与 UTC 重置、缺失免费密钥时禁止使用旧 OpenAI 密钥、SARSA 动作一致性及预算约束。

这些是接口契约和系统测试，使用模拟 SDK 响应，不代表服务商的真实免费模型调用成功。测试自动隔离本机真实密钥，避免消耗用户账户额度。

本次发布时尚未取得 OpenRouter 账号密钥，实际免费 LLM 调用未运行。页面通过 `configured`、`last_success_at`、`last_used_model` 和记录来源区分待配置、待验证与真实成功，不能仅凭健康检查通过就声称 LLM 已接通。

## 官方资料

- [免费方案与请求上限](https://openrouter.ai/pricing)
- [免费模型路由](https://openrouter.ai/docs/guides/routing/routers/free-router)
- [结构化输出](https://openrouter.ai/docs/guides/features/structured-outputs)
- [提供商选择与 max_price](https://openrouter.ai/docs/guides/routing/provider-selection)
- [官方密钥页面](https://openrouter.ai/settings/keys)

# 营销工作台改版

用户要求：简洁、减少聊天式 AI 外观，保留数据库和嵌入的 SARSA。

实际查看了以下官方页面和开源项目：

- https://github.com/satnaing/shadcn-admin 与其运行演示 https://shadcn-admin.netlify.app/
- https://github.com/shadcn-ui/ui 与官方 Tasks 示例 https://ui.shadcn.com/examples/tasks
- https://github.com/twentyhq/twenty 的 CRM 数据视图介绍

参考其导航、表格和表单组织方式，未复制其代码、商标或示例数据，也未引入新组件依赖。使用灰白色、细边框、普通业务表单，去掉聊天式大输入框和大面积欢迎文案。首页直接显示当前观察日的渠道经营表和最近七个观察日的收入趋势；决策与执行反馈在同一个工作台完成，训练和对照实验保留在侧栏。

收益说明从新增的只读 /api/reward 接口读取，与 RewardEngine 共享范围、因子顺序和权重，避免文案与评分漂移。查看其他目标的权重不会修改已生成决策。

原有合成数据、仿真标识、真实下一动作确认、人工调整理由、模型凭证与来源披露均保留。此改版没有重训模型或改变动作、奖励和 SARSA 更新规则。

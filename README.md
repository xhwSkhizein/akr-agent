# Akr, agent know rules

> a agent framework that easy to use and config custom rules.

## Agent

• 配置驱动：通过 AgentConfig 灵活定义系统 prompt、规则、依赖工具、action target。

• 上下文管理：Context 负责中间结果的存取。

• 异步流式：LLMClient 以 async for 返回流式 token 或 chunk，满足实时性需求。

• 模块化：将配置、核心逻辑、工具、上下文、LLM 客户端解耦，便于扩展和单测。

• 单元测试：例子展示了如何用 Dummy LLM 验证规则执行流程，实际可补充更多用例。


# 提示语模板配置

```
├── prompts/
│   └── CoachLi/                    # Agent 名称
│       └── v1/                     # 版本号
│           ├── system_prompt.txt   # Agent 的基础系统提示 (可以是 Jinja2 模板)
│           ├── meta.json           # Agent 的元数据 (名称、描述、参数等)
│           └── rules/              # 规则定义
│               ├── 意图分析.json
│               ├── 回复力量训练相关.json
│               └── 避免回复康复训练相关.json
```

> 参考代码 

* [AgentConfig](../config/agent_config.py)
* [AgentConfigEngine](../config/agent_config_engine.py)

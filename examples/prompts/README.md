

# Prompt template configuration

```
├── prompts/
│   └── CoachLi/                     # Agent name
│       └── v1/                      # Version number
│           ├── system_prompt.yaml   # Agent's base system prompt (can be Jinja2 template)
│           ├── meta.yaml            # Agent metadata (name, description, parameters, etc.)
│           └── rules/               # Rule definition
│               ├── intent_analysis.yaml
│               ├── default_qa.yaml
│               └── about_rehabilitation.yaml
```

> Reference code 

* [AgentConfigEngine](../../akr_agent/agent_config_engine.py)

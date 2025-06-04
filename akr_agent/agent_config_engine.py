#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Prompt 配置引擎，负责加载和管理 Agent 的 prompt 配置
"""
import logging

logger = logging.getLogger(__name__)

import os
from typing import List, Dict, Any
import yaml
from jinja2 import Template

from .rule_config import AgentConfig, AgentMeta, RuleConfig


class AgentConfigEngine:
    """Agent 配置引擎，负责从 YAML 文件加载配置并构建 AgentConfig"""

    @staticmethod
    def _load_yaml(file_path: str) -> Dict[str, Any]:
        """加载 YAML 文件"""
        with open(file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    @staticmethod
    def _render_template(template_str: str, context: Dict[str, Any]) -> str:
        """渲染 Jinja2 模板"""
        template = Template(template_str)
        return template.render(**context)

    @staticmethod
    def _load_system_prompt(base_config_path: str, meta_data: Dict[str, Any]) -> str:
        """加载并渲染系统提示"""
        system_prompt_path = os.path.join(base_config_path, "system_prompt.yaml")
        if not os.path.exists(system_prompt_path):
            raise FileNotFoundError(
                f"System prompt file not found: {system_prompt_path}"
            )

        system_prompt_data = AgentConfigEngine._load_yaml(system_prompt_path)
        template_str = system_prompt_data.get("content", "")

        # 构建渲染上下文
        context = {
            "meta": meta_data.get("meta", {}),
            "agent": meta_data.get("agent", {}),
        }

        return AgentConfigEngine._render_template(template_str, context)

    @staticmethod
    def _load_rules(base_config_path: str) -> List[RuleConfig]:
        """加载所有规则配置"""
        rules_dir = os.path.join(base_config_path, "rules")
        if not os.path.isdir(rules_dir):
            raise NotADirectoryError(f"Rules directory not found: {rules_dir}")

        rules = []
        for rule_file in os.listdir(rules_dir):
            if not rule_file.endswith(".yaml"):
                continue

            rule_path = os.path.join(rules_dir, rule_file)
            rule_data = AgentConfigEngine._load_yaml(rule_path)

            # 确保规则数据包含必要的字段
            if not all(k in rule_data for k in ["name", "prompt"]):
                raise ValueError(f"Rule {rule_file} missing required fields")
            logger.debug(f"Loading rule from {rule_file}, \n{rule_data}\n")

            rules.append(RuleConfig(**rule_data))
        return rules

    @staticmethod
    def load(config_dir: str) -> AgentConfig:
        """
        加载并构建 AgentConfig

        Args:
            config_dir: prompt 配置文件的基础路径，例如 "prompts/CoachLi/v1"

        Returns:
            AgentConfig: 构建好的 Agent 配置对象

        Raises:
            FileNotFoundError: 当必要的配置文件不存在时
            ValueError: 当配置文件格式不正确时
        """
        if not config_dir or not os.path.exists(config_dir):
            raise ValueError(f"Invalid config directory: {config_dir}")

        # 1. 加载 meta 配置
        meta_path = os.path.join(config_dir, "meta.yaml")
        if not os.path.exists(meta_path):
            raise FileNotFoundError(f"Meta configuration file not found: {meta_path}")

        meta_data = AgentConfigEngine._load_yaml(meta_path)

        # 2. 构建 AgentMeta
        agent_meta = AgentMeta(**meta_data.get("meta", {}))

        # 3. 加载并渲染系统提示
        system_prompt = AgentConfigEngine._load_system_prompt(config_dir, meta_data)

        # 4. 加载规则
        rules = AgentConfigEngine._load_rules(config_dir)

        # 5. 构建并返回 AgentConfig
        return AgentConfig(
            name=meta_data.get("agent", {}).get("name", "Unnamed Agent"),
            meta=agent_meta,
            system_prompt=system_prompt,
            rules=rules,
        )

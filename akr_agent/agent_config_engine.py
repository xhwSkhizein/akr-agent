#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Prompt configuration engine, responsible for loading and managing Agent prompt configuration
"""
import logging

logger = logging.getLogger(__name__)

import os
from typing import List, Dict, Any
import yaml
from jinja2 import Template

from .rule_config import AgentConfig, AgentMeta, RuleConfig


class AgentConfigEngine:
    """Agent configuration engine, responsible for loading and building AgentConfig from YAML files"""

    @staticmethod
    def _load_yaml(file_path: str) -> Dict[str, Any]:
        """Load YAML file"""
        with open(file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    @staticmethod
    def _render_template(template_str: str, context: Dict[str, Any]) -> str:
        """Render Jinja2 template"""
        template = Template(template_str)
        return template.render(**context)

    @staticmethod
    def _load_system_prompt(base_config_path: str, meta_data: Dict[str, Any]) -> str:
        """Load and render system prompt"""
        system_prompt_path = os.path.join(base_config_path, "system_prompt.yaml")
        if not os.path.exists(system_prompt_path):
            raise FileNotFoundError(
                f"System prompt file not found: {system_prompt_path}"
            )

        system_prompt_data = AgentConfigEngine._load_yaml(system_prompt_path)
        template_str = system_prompt_data.get("content", "")

        # Render template
        context = {
            "meta": meta_data.get("meta", {}),
            "agent": meta_data.get("agent", {}),
        }

        return AgentConfigEngine._render_template(template_str, context)

    @staticmethod
    def _load_rules(base_config_path: str) -> List[RuleConfig]:
        """Load all rule configurations"""
        rules_dir = os.path.join(base_config_path, "rules")
        if not os.path.isdir(rules_dir):
            raise NotADirectoryError(f"Rules directory not found: {rules_dir}")

        rules = []
        for rule_file in os.listdir(rules_dir):
            if not rule_file.endswith(".yaml"):
                continue

            rule_path = os.path.join(rules_dir, rule_file)
            rule_data = AgentConfigEngine._load_yaml(rule_path)

            # Ensure rule data contains necessary fields
            if not all(k in rule_data for k in ["name", "prompt"]):
                raise ValueError(f"Rule {rule_file} missing required fields")
            logger.debug(f"Loading rule from {rule_file}, \n{rule_data}\n")

            rules.append(RuleConfig(**rule_data))
        return rules

    @staticmethod
    def load(config_dir: str) -> AgentConfig:
        """
        Load and build AgentConfig

        Args:
            config_dir: Base path of prompt configuration files, e.g. "prompts/CoachLi/v1"

        Returns:
            AgentConfig: Built AgentConfig object

        Raises:
            FileNotFoundError: When necessary configuration files are not found
            ValueError: When configuration file format is incorrect
        """
        if not config_dir or not os.path.exists(config_dir):
            raise ValueError(f"Invalid config directory: {config_dir}")

        # 1. Load meta configuration
        meta_path = os.path.join(config_dir, "meta.yaml")
        if not os.path.exists(meta_path):
            raise FileNotFoundError(f"Meta configuration file not found: {meta_path}")

        meta_data = AgentConfigEngine._load_yaml(meta_path)

        # 2. Build AgentMeta
        agent_meta = AgentMeta(**meta_data.get("meta", {}))

        # 3. Load and render system prompt
        system_prompt = AgentConfigEngine._load_system_prompt(config_dir, meta_data)

        # 4. Load rules
        rules = AgentConfigEngine._load_rules(config_dir)

        # 5. Build and return AgentConfig
        return AgentConfig(
            name=meta_data.get("agent", {}).get("name", "Unnamed Agent"),
            meta=agent_meta,
            system_prompt=system_prompt,
            rules=rules,
        )

from typing import Dict, Set, Optional

import uuid
import logging
from collections import defaultdict

from .observable_ctx import ObservableCtx
from .rule_config import RuleConfig


logger = logging.getLogger(__name__)

class RuleRegistry:
    """
    规则注册表，负责规则的注册、索引和查询
    """
    
    def __init__(self):
        self._rules: Dict[str, RuleConfig] = {}  # rule_id -> RuleConfig
        self._key_to_rules = defaultdict(set)  # ctx_key -> {rule_ids}
        self._rule_priorities: Dict[str, int] = {}  # rule_id -> priority
    
    def generate_rule_id(self, rule_name: str) -> str:
        """生成唯一的规则ID"""
        return f"{rule_name}_{str(uuid.uuid4())[:8]}"
    
    def register_rule(self, rule_config: RuleConfig) -> str:
        """注册新规则"""
        rule_id = self.generate_rule_id(rule_config.name)
        self._rules[rule_id] = rule_config
        
        # 设置优先级
        priority = getattr(rule_config, "priority", 0)
        self._rule_priorities[rule_id] = priority
        
        # 添加到索引
        for key in rule_config.depend_ctx_key:
            self._key_to_rules[key].add(rule_id)
        
        logger.debug(
            f"Registered rule: {rule_id} (Name: {rule_config.name}, "
            f"Depend_ctx_key: {rule_config.depend_ctx_key}, "
            f"Condition: {rule_config.match_condition}, Priority: {priority})"
        )
        
        return rule_id
    
    def unregister_rule(self, rule_id: str) -> None:
        """注销规则"""
        if rule_id not in self._rules:
            return
            
        rule_config = self._rules[rule_id]
        
        # 从索引中移除
        for key in rule_config.depend_ctx_key:
            if rule_id in self._key_to_rules[key]:
                self._key_to_rules[key].remove(rule_id)
        
        # 移除规则配置和优先级
        del self._rules[rule_id]
        if rule_id in self._rule_priorities:
            del self._rule_priorities[rule_id]
        
        logger.debug(f"Unregistered rule: {rule_id}")
    
    def get_rule(self, rule_id: str) -> Optional[RuleConfig]:
        """获取规则配置"""
        return self._rules.get(rule_id)
    
    def get_rules_for_key(self, key: str) -> Set[str]:
        """获取依赖指定键的所有规则ID"""
        return self._key_to_rules.get(key, set())
    
    def get_rule_priority(self, rule_id: str) -> int:
        """获取规则优先级"""
        return self._rule_priorities.get(rule_id, 0)
    
    def check_rule_condition(self, rule_id: str, ctx: ObservableCtx) -> bool:
        """检查规则条件是否满足"""
        rule_config = self.get_rule(rule_id)
        if not rule_config:
            return False
            
        condition = rule_config.match_condition
        if not condition:
            return True
            
        try:
            # 准备安全的执行环境
            eval_globals = {
                "__builtins__": {
                    "True": True,
                    "False": False,
                    "None": None,
                    "str": str,
                    "int": int,
                    "float": float,
                    "bool": bool,
                    "list": list,
                    "dict": dict,
                    "set": set,
                    "tuple": tuple,
                    "len": len,
                    "Exception": Exception,
                },
                "ctx": ctx,
            }
            result = eval(condition, eval_globals, {})
            logger.debug(
                f"Condition '{condition}' for rule {rule_id} evaluated to: {result}"
            )
            return bool(result)
        except Exception as e:
            logger.error(f"Error evaluating condition for rule {rule_id}: {e}")
            return False
"""
LLM调用日志记录器
用于记录LLM调用的输入输出到日志文件，支持ShareGPT格式
"""

import os
import json
import time
import uuid
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List, Union, Tuple

from loguru import logger


class LLMLogger:
    """
    LLM调用日志记录器
    记录每次LLM调用的输入输出到指定日志文件，支持ShareGPT格式
    """

    def __init__(
        self,
        log_dir: str = "logs/llm_calls",
        log_filename: Optional[str] = None,
        enable: bool = True,
    ):
        """
        初始化LLM日志记录器

        Args:
            log_dir: 日志文件目录
            log_filename: 日志文件名，默认为"llm_calls_{日期}.jsonl"
            enable: 是否启用日志记录
        """
        self.enable = enable
        logger.debug(f"初始化LLM日志记录器，启用状态: {enable}")
        
        if not enable:
            logger.debug("日志记录已禁用，跳过初始化日志文件")
            return

        # 创建日志目录
        self.log_dir = Path(log_dir)
        logger.debug(f"创建日志目录: {self.log_dir}")
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 设置日志文件名
        if log_filename is None:
            current_date = datetime.now().strftime("%Y%m%d")
            log_filename = f"llm_calls_{current_date}.jsonl"

        self.log_path = self.log_dir / log_filename
        logger.info(f"LLM调用日志将记录到: {self.log_path}")
        
        # 测试日志文件是否可写
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                pass
            logger.debug(f"日志文件可写: {self.log_path}")
        except Exception as e:
            logger.error(f"日志文件不可写: {self.log_path}, 错误: {e}")
        
        # 用于构建ShareGPT格式的对话历史
        self.conversations_cache = {}
        # 用于缓存工具定义
        self.tools_cache = {}
        # 用于缓存系统提示词
        self.system_prompts_cache = {}

    def log_request(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        params: Dict[str, Any],
        call_id: Optional[str] = None,
    ) -> str:
        """
        记录LLM请求

        Args:
            model: 模型名称
            messages: 消息列表
            params: 调用参数
            call_id: 调用ID，如果为None则自动生成

        Returns:
            调用ID
        """
        if not self.enable:
            logger.debug("日志记录已禁用，跳过记录请求")
            return call_id or f"llm_{uuid.uuid4().hex}"
            
        # 生成调用ID
        if call_id is None:
            call_id = f"llm_{uuid.uuid4().hex}"
        
        logger.debug(f"记录LLM请求，调用ID: {call_id}, 模型: {model}")
            
        # 提取工具定义
        tools = params.get("tools", [])
        if tools:
            self.tools_cache[call_id] = json.dumps(tools)
        
        # 初始化对话历史
        self.conversations_cache[call_id] = []
        
        # 处理消息历史，转换为ShareGPT格式
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            
            # 处理系统消息，存储到系统提示词缓存中
            if role == "system":
                if content and isinstance(content, str):
                    self.system_prompts_cache[call_id] = content
                continue
            
            # 转换角色名称
            from_role = "human" if role == "user" else "gpt" if role == "assistant" else role
            
            # 处理内容
            files = []
            if isinstance(content, list):  # 多模态内容
                text_parts = []
                for part in content:
                    if part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        # 处理图片URL
                        image_data = part.get("image_url", {})
                        files.append({
                            "type": "image",
                            "url": image_data.get("url", ""),
                            "detail": image_data.get("detail", "auto")
                        })
                    # 可以根据需要添加其他类型的处理
                value = " ".join(text_parts)
            else:
                value = content
            
            # 添加到对话历史
            message_entry = {
                "from": from_role,
                "value": value
            }
            
            # 如果有文件，添加到消息中
            if files:
                message_entry["files"] = files
                
            # 只有当有文本内容或文件时才添加消息
            if value or files:
                self.conversations_cache[call_id].append(message_entry)
            
            # 处理工具调用
            if "tool_calls" in msg:
                for tool_call in msg.get("tool_calls", []):
                    func = tool_call.get("function", {})
                    func_call = {
                        "name": func.get("name", ""),
                        "arguments": func.get("arguments", "{}")
                    }
                    self.conversations_cache[call_id].append({
                        "from": "function_call",
                        "value": json.dumps(func_call)
                    })
            
        return call_id

    def log_response(
        self,
        call_id: str,
        response_content: Union[str, Dict[str, Any]],
        token_usage: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        记录LLM响应

        Args:
            call_id: 调用ID
            response_content: 响应内容
            token_usage: Token使用情况
            duration_ms: 调用耗时(毫秒)
            error: 错误信息，如果有的话
        """
        if not self.enable:
            logger.debug("日志记录已禁用，跳过记录响应")
            return
            
        logger.debug(f"记录LLM响应，调用ID: {call_id}, 内容长度: {len(str(response_content))}, 错误: {error}")
        
        if call_id in self.conversations_cache:
            # 添加助手回复到对话历史
            if response_content and not error:
                content_str = response_content if isinstance(response_content, str) else json.dumps(response_content)
                if content_str.strip():  # 跳过空内容
                    self.conversations_cache[call_id].append({
                        "from": "gpt",
                        "value": content_str
                    })
            
            # 如果有错误，记录错误
            if error:
                self.conversations_cache[call_id].append({
                    "from": "gpt",
                    "value": f"Error: {error}"
                })
            
            # 检查是否需要写入日志（当对话完成时）
            # 这里我们假设当收到响应时，对话已经完成
            self._write_sharegpt_log(call_id, token_usage, duration_ms)

    def log_tool_call(
        self,
        call_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call_id: str,
    ) -> None:
        """
        记录工具调用

        Args:
            call_id: LLM调用ID
            tool_name: 工具名称
            tool_args: 工具参数
            tool_call_id: 工具调用ID
        """
        if not self.enable:
            return

        # 工具调用已经在log_request中处理，这里不需要额外处理
        pass

    def log_tool_result(
        self,
        call_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_result: str,
        error: Optional[str] = None,
    ) -> None:
        """
        记录工具调用结果

        Args:
            call_id: LLM调用ID
            tool_call_id: 工具调用ID
            tool_name: 工具名称
            tool_result: 工具调用结果
            error: 错误信息，如果有的话
        """
        if not self.enable:
            return

        if call_id in self.conversations_cache:
            # 添加工具调用结果到对话历史
            result_value = tool_result
            if error:
                result_value = f"Error: {error}\n{result_value}"
            
            # 尝试将结果解析为JSON
            try:
                # 检查结果是否已经是JSON格式
                json_obj = json.loads(result_value)
                result_value = json.dumps(json_obj)  # 确保是有效的JSON字符串
            except (json.JSONDecodeError, TypeError):
                # 如果不是JSON，尝试将结果包装为JSON
                try:
                    result_value = json.dumps({"result": result_value})
                except (TypeError, ValueError):
                    # 如果还是失败，保持原样
                    pass
            
            self.conversations_cache[call_id].append({
                "from": "observation",
                "value": result_value
            })


    
    def _write_sharegpt_log(self, call_id: str, token_usage: Optional[Dict[str, Any]] = None, duration_ms: Optional[float] = None) -> None:
        """
        将ShareGPT格式的对话写入日志文件

        Args:
            call_id: 调用ID
            token_usage: Token使用情况
            duration_ms: 调用耗时(毫秒)
        """
        if not self.enable:
            logger.debug("日志记录已禁用，跳过写入日志")
            return
            
        if call_id not in self.conversations_cache:
            logger.warning(f"找不到调用ID对应的对话缓存: {call_id}")
            return
            
        logger.debug(f"准备写入日志，调用ID: {call_id}，对话历史长度: {len(self.conversations_cache[call_id])}")
        
        # 获取对话历史
        conversations = self.conversations_cache[call_id]
        
        # 检查对话是否符合ShareGPT格式要求
        if not self._is_valid_sharegpt_conversation(conversations):
            logger.warning(f"对话不符合ShareGPT格式要求，跳过写入: {call_id}")
            logger.debug(f"不符合要求的对话内容: {conversations}")
            return
        
        # 构建日志
        log_entry = {
            "conversations": conversations,
        }
        
        # 添加系统提示词
        if call_id in self.system_prompts_cache:
            log_entry["system"] = self.system_prompts_cache[call_id]
        
        # 添加工具定义
        if call_id in self.tools_cache:
            log_entry["tools"] = self.tools_cache[call_id]
        
        # 添加元数据
        log_entry["metadata"] = {
            "call_id": call_id,
            "timestamp": datetime.now().isoformat(),
        }
        
        if token_usage:
            log_entry["metadata"]["token_usage"] = token_usage
        
        if duration_ms:
            log_entry["metadata"]["duration_ms"] = duration_ms
        
        # 写入日志文件
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            
            # 清理缓存
            del self.conversations_cache[call_id]
            if call_id in self.tools_cache:
                del self.tools_cache[call_id]
            if call_id in self.system_prompts_cache:
                del self.system_prompts_cache[call_id]
                
        except Exception as e:
            logger.error(f"写入ShareGPT格式日志失败: {e}")
    
    def _is_valid_sharegpt_conversation(self, conversations: List[Dict[str, str]]) -> bool:
        """
        检查对话是否符合ShareGPT格式要求
        
        Args:
            conversations: 对话历史
            
        Returns:
            是否符合ShareGPT格式要求
        """
        if not conversations:
            return False
        
        # 检查对话是否至少包含一个人类消息和一个助手消息
        has_human = False
        has_gpt = False
        
        for i, msg in enumerate(conversations):
            from_role = msg.get("from")
            
            # 检查奇偶位置的角色
            if i % 2 == 0:  # 偶数位置
                if from_role not in ["human", "observation"]:
                    logger.warning(f"ShareGPT格式要求偶数位置的角色必须是human或observation，但得到了{from_role}")
                    return False
                if from_role == "human":
                    has_human = True
            else:  # 奇数位置
                if from_role not in ["gpt", "function_call"]:
                    logger.warning(f"ShareGPT格式要求奇数位置的角色必须是gpt或function_call，但得到了{from_role}")
                    return False
                if from_role == "gpt":
                    has_gpt = True
        
        # 修正：ShareGPT格式中，human应该在奇数位置，gpt应该在偶数位置
        # 但由于索引从0开始，所以实际上human在偶数索引，gpt在奇数索引
        return has_human and has_gpt

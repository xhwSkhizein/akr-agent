from typing import get_origin, get_args
from inspect import Parameter
from typing import Dict, Any


def get_json_type_info(annotation) -> Dict[str, Any]:
    """
    将 Python 类型注解映射到 JSON schema 类型信息（支持泛型）
    返回示例：
    - 普通类型: {"type": "integer"}
    - 泛型 list: {"type": "array", "items": {"type": "string"}}
    """
    # 无类型注解时默认返回 string（可根据需求调整）
    if annotation is Parameter.empty:
        return {"type": "string"}

    # 处理泛型类型（如 list[str], dict[str, int]）
    origin = get_origin(annotation)
    args = get_args(annotation)

    # -------------------- 处理 list 泛型 --------------------
    if origin is list:
        if args:  # list[str] → {"type": "array", "items": {"type": "string"}}
            items_type = get_json_type_info(args[0])
            return {"type": "array", "items": items_type}
        else:  # list → {"type": "array"}（无元素类型信息）
            return {"type": "array"}

    # -------------------- 处理 dict 泛型 --------------------
    if origin is dict:
        if (
            len(args) >= 2
        ):  # dict[str, int] → {"type": "object", "properties": ...}（简化处理）
            return {
                "type": "object"
            }  # 实际可扩展为更细粒度的 properties，但 OpenAI 通常接受 object
        else:
            return {"type": "object"}

    # -------------------- 处理内置类型 --------------------
    type_mapping = {
        int: "integer",
        float: "number",
        bool: "boolean",
        str: "string",
        dict: "object",
        list: "array",
        tuple: "array",  # 简化处理为 array
    }
    for py_type, json_type in type_mapping.items():
        if annotation is py_type:
            return {"type": json_type}

    # -------------------- 处理自定义类 --------------------
    # 自定义类默认视为 object（可根据需求扩展，如检查是否为 Pydantic 模型）
    return {"type": "object"}

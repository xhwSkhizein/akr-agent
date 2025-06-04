from typing import get_origin, get_args
from inspect import Parameter
from typing import Dict, Any


def get_json_type_info(annotation) -> Dict[str, Any]:
    """
    Map Python type annotations to JSON schema type information (supports generics)
    Return examples:
    - Simple types: {"type": "integer"}
    - Generic list: {"type": "array", "items": {"type": "string"}}
    """
    # Default to string when no type annotation (can be adjusted based on needs)
    if annotation is Parameter.empty:
        return {"type": "string"}

    # Handle generic types (e.g., list[str], dict[str, int])
    origin = get_origin(annotation)
    args = get_args(annotation)

    # -------------------- Handle list generic --------------------
    if origin is list:
        if args:  # list[str] → {"type": "array", "items": {"type": "string"}}
            items_type = get_json_type_info(args[0])
            return {"type": "array", "items": items_type}
        else:  # list → {"type": "array"}（No element type information）
            return {"type": "array"}

    # -------------------- Handle dict generic --------------------
    if origin is dict:
        if (
            len(args) >= 2
        ):  # dict[str, int] → {"type": "object", "properties": ...}（Simplified processing）
            return {
                "type": "object"
            }
        else:
            return {"type": "object"}

    # -------------------- Handle built-in types --------------------
    type_mapping = {
        int: "integer",
        float: "number",
        bool: "boolean",
        str: "string",
        dict: "object",
        list: "array",
        tuple: "array",  # Simplified to array
    }
    for py_type, json_type in type_mapping.items():
        if annotation is py_type:
            return {"type": json_type}

    # -------------------- Handle custom classes --------------------
    # Custom classes are treated as object by default (can be extended based on needs, e.g., check if Pydantic model)
    return {"type": "object"}

"""
AKR-Agent - A flexible rule-based AI Agent framework
"""

try:
    from ._version import version as __version__
except ImportError:
    __version__ = "0.1.0.dev0"

from .agent import Agent
from .tools.base import Tool, ToolCenter

__all__ = ["Agent", "Tool", "ToolCenter"]

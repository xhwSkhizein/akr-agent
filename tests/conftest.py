import pytest
import asyncio
import logging

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 注意：我们不再定义自定义的 event_loop fixture
# pytest-asyncio 会自动提供一个 event_loop fixture

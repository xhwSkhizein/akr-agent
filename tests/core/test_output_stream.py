import pytest
import asyncio
from typing import AsyncGenerator, Dict, Any
from datetime import datetime

from core.output_stream import OutputStreamManager, StreamMetadata, OutputChunk
from core.chunk import ResponseChunk


async def mock_generator(items, delay=0.01):
    """创建一个模拟的异步生成器"""
    for item in items:
        await asyncio.sleep(delay)
        yield item


@pytest.fixture
def stream_metadata():
    """创建一个流元数据实例"""
    return StreamMetadata(
        rule_name="test_rule",
        rule_id="test_rule_id",
        task_id="test_task_id",
        rule_priority=10
    )


@pytest.mark.asyncio
async def test_register_stream():
    """测试注册输出流"""
    manager = OutputStreamManager()
    
    # 创建一个模拟的异步生成器
    items = ["chunk1", "chunk2", "chunk3"]
    generator = mock_generator(items)
    
    # 创建元数据
    metadata = StreamMetadata(
        rule_name="test_rule",
        rule_id="test_rule_id",
        task_id="test_task_id",
        rule_priority=10
    )
    
    # 注册流
    stream_id = await manager.register_stream(generator, metadata)
    
    # 验证流已注册
    assert stream_id in manager._streams
    assert manager._streams[stream_id]["generator"] is generator
    assert manager._streams[stream_id]["metadata"] == metadata


@pytest.mark.asyncio
async def test_unregister_stream():
    """测试注销输出流"""
    manager = OutputStreamManager()
    
    # 创建一个模拟的异步生成器
    items = ["chunk1", "chunk2", "chunk3"]
    generator = mock_generator(items)
    
    # 创建元数据
    metadata = StreamMetadata(
        rule_name="test_rule",
        rule_id="test_rule_id",
        task_id="test_task_id",
        rule_priority=10
    )
    
    # 注册流
    stream_id = await manager.register_stream(generator, metadata)
    
    # 注销流
    await manager.unregister_stream(stream_id)
    
    # 验证流已注销
    assert stream_id not in manager._streams


@pytest.mark.asyncio
async def test_get_output_stream_single():
    """测试从单个流获取输出"""
    manager = OutputStreamManager()
    
    # 创建一个模拟的异步生成器
    items = ["chunk1", "chunk2", "chunk3"]
    generator = mock_generator(items)
    
    # 创建元数据
    metadata = StreamMetadata(
        rule_name="test_rule",
        rule_id="test_rule_id",
        task_id="test_task_id",
        rule_priority=10
    )
    
    # 注册流
    await manager.register_stream(generator, metadata)
    
    # 收集输出
    results = []
    async for chunk in manager.get_output_stream():
        results.append(chunk.content)
    
    # 验证输出
    assert results == items


@pytest.mark.asyncio
async def test_get_output_stream_multiple():
    """测试从多个流获取输出"""
    manager = OutputStreamManager()
    
    # 创建两个模拟的异步生成器
    items1 = ["stream1-chunk1", "stream1-chunk2"]
    items2 = ["stream2-chunk1", "stream2-chunk2"]
    
    generator1 = mock_generator(items1, delay=0.01)
    generator2 = mock_generator(items2, delay=0.02)
    
    # 创建元数据
    metadata1 = StreamMetadata(
        rule_name="test_rule1",
        rule_id="test_rule_id1",
        task_id="test_task_id1",
        rule_priority=10
    )
    
    metadata2 = StreamMetadata(
        rule_name="test_rule2",
        rule_id="test_rule_id2",
        task_id="test_task_id2",
        rule_priority=5
    )
    
    # 注册流
    await manager.register_stream(generator1, metadata1)
    await manager.register_stream(generator2, metadata2)
    
    # 收集输出
    results = []
    async for chunk in manager.get_output_stream():
        results.append({
            "content": chunk.content,
            "rule_name": chunk.metadata.rule_name
        })
    
    # 验证所有输出都被收集
    assert len(results) == len(items1) + len(items2)
    
    # 验证两个流的输出都存在
    stream1_outputs = [r for r in results if r["rule_name"] == "test_rule1"]
    stream2_outputs = [r for r in results if r["rule_name"] == "test_rule2"]
    
    assert len(stream1_outputs) == len(items1)
    assert len(stream2_outputs) == len(items2)


@pytest.mark.asyncio
async def test_output_chunk_serialization():
    """测试OutputChunk的序列化"""
    # 创建元数据
    metadata = StreamMetadata(
        rule_name="test_rule",
        rule_id="test_rule_id",
        task_id="test_task_id",
        rule_priority=10
    )
    
    # 创建输出块
    chunk = OutputChunk(content="test content", metadata_ref=metadata)
    
    # 测试dict方法
    chunk_dict = chunk.dict()
    assert chunk_dict["content"] == "test content"
    assert chunk_dict["metadata"]["rule_name"] == "test_rule"
    assert chunk_dict["metadata"]["rule_id"] == "test_rule_id"
    assert chunk_dict["metadata"]["task_id"] == "test_task_id"
    assert chunk_dict["metadata"]["rule_priority"] == 10


@pytest.mark.asyncio
async def test_stream_metadata_serialization():
    """测试StreamMetadata的序列化"""
    # 创建元数据
    metadata = StreamMetadata(
        rule_name="test_rule",
        rule_id="test_rule_id",
        task_id="test_task_id",
        rule_priority=10
    )
    
    # 测试model_dump方法
    metadata_dict = metadata.model_dump()
    assert metadata_dict["rule_name"] == "test_rule"
    assert metadata_dict["rule_id"] == "test_rule_id"
    assert metadata_dict["task_id"] == "test_task_id"
    assert metadata_dict["rule_priority"] == 10
    assert "created_at" in metadata_dict

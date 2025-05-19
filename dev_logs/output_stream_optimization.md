# 输出流处理优化设计文档

## 背景

当前Agent框架在处理多任务并发输出时存在以下问题：

1. 所有RuleTask向同一个输出队列写入数据，没有明确的标识来区分不同任务的输出
2. 多个RuleTask并发执行时，输出会交错混合，没有清晰的分离
3. `get_output_stream`方法使用`wait_for`等待输出队列数据，导致不必要的等待和超时处理
4. 当前`get_output_stream`方法过于复杂，承担了太多责任

## 优化目标

1. 实现更高效、优雅的输出流管理机制
2. 避免不同任务输出的混合和交错
3. 简化输出流处理逻辑，提高代码可维护性
4. 优化`ResponseChunk`设计，减少冗余

## 设计方案

### 1. OutputStreamManager类设计

#### 1.1 核心思想

创建专门的`OutputStreamManager`类来管理多个异步生成器，支持按注册顺序或优先级合并输出流。

* 注意多线程环境下的线程安全
* 使用高效的数据结构和算法
* 保持代码的简洁性和可读性

#### 1.2 类结构

```python
class OutputStreamManager:
    """输出流管理器，负责管理和合并多个异步生成器的输出"""
    
    async def register_stream(self, generator, metadata):
        """注册一个新的输出流"""
        pass
    
    async def unregister_stream(self, stream_id):
        """注销一个输出流"""
        pass
    
    async def get_output_stream(self):
        """按注册顺序获取所有输出流"""
        # 使用异步迭代器模式，按注册顺序遍历所有流
        # 当所有流都耗尽时自动结束
        pass
```

#### 1.3 工作流程

1. 每个`RuleTask`在执行时向`OutputStreamManager`注册自己的异步生成器
2. `OutputStreamManager`为每个任务保存相关元数据和 Id
3. 当调用`get_output_stream`时，按注册顺序或优先级依次从各个生成器获取数据
4. 当某个生成器耗尽时，自动从活跃流列表中移除

### 2. RuleTask输出机制优化

#### 2.1 核心思想

每个`RuleTask`返回一个异步生成器，而不是向共享队列写入数据。

#### 2.2 实现方式

```python
class RuleTask:
    # 其他方法保持不变
    
    async def execute_tool(self, ctx, dispatcher) -> AsyncGenerator[str, None]:
        """执行工具调用，返回异步生成器"""
        # 直接使用yield返回结果
```

#### 2.3 优势

1. 避免了共享队列带来的竞争和混合问题
2. 每个任务的输出天然隔离
3. 更符合Python异步编程模型

### 3. Dispatcher优化

#### 3.1 核心变更

1. 移除共享的`_output_queue`
2. 添加`OutputStreamManager`实例
3. 重构`get_output_stream`方法

#### 3.2 新的实现

```python
class RuleDispatcher:
    def __init__(self, ...):
        # 其他初始化保持不变
        self._output_manager = OutputStreamManager()
        # 移除 self._output_queue
    
    async def _schedule_task(self, task):
        # 创建任务执行协程
        execution_coro = task.execute_tool(ctx=self._ctx, dispatcher=self)
        
        # 向输出管理器注册此流
        metadata = {
            "rule_name": task.rule_config.name,
            "rule_id": task.rule_id,
            "task_id": task.task_id,
            "rule_priority": task.rule_config.priority
        }
        stream_id = await self._output_manager.register_stream(execution_coro, metadata)
        
        # 创建任务包装器
        async def task_wrapper():
            try:
                # 执行任务，但不需要处理输出
                # 输出由OutputStreamManager处理
                await execution_coro.__anext__()  # 启动生成器
            finally:
                # 任务完成时，从输出管理器注销
                await self._output_manager.unregister_stream(stream_id)
        
        # 创建并跟踪异步任务
        # 其余逻辑保持不变
    
    async def get_output_stream(self):
        """提供最终输出的异步生成器"""
        # 直接委托给输出管理器
        async for chunk, metadata in self._output_manager.get_output_stream():
            yield chunk
```

### 4. ResponseChunk重新设计

#### 4.1 核心思想

将`ResponseChunk`重新设计为元数据容器，而不是为每个输出块都附加完整元数据。

#### 4.2 新的实现

```python
class StreamMetadata(BaseModel):
    """流元数据，描述一个输出流的属性"""
    rule_name: str
    rule_id: str
    task_id: str
    rule_priority: int = 0
    created_at: datetime = Field(default_factory=datetime.now)

class OutputChunk:
    """单个输出块，包含内容和对应的元数据引用"""
    def __init__(self, content: str, metadata_ref: StreamMetadata):
        self.content = content
        self.metadata = metadata_ref
    
    def dict(self):
        """返回可序列化的字典表示"""
        return {
            "content": self.content,
            "metadata": self.metadata.dict()
        }
```

## 实现步骤

1. 创建`OutputStreamManager`类
2. 修改`RuleTask.execute_tool`方法，使其直接返回异步生成器
3. 更新`RuleDispatcher`，移除共享队列，添加输出管理器
4. 重构`get_output_stream`方法，简化逻辑
5. 实现新的`StreamMetadata`和`OutputChunk`类
6. 更新相关测试用例

## 优势

1. **更清晰的责任分离**：输出流管理由专门的类负责
2. **避免输出混合**：每个任务的输出被独立处理
3. **更高效的异步处理**：直接使用异步生成器，避免队列操作开销
4. **更简洁的代码**：移除复杂的等待和超时处理逻辑
5. **更低的内存占用**：元数据共享，减少冗余

## 潜在挑战

1. **顺序保证**：需要确保按照预期顺序处理多个流的输出
2. **错误处理**：需要妥善处理单个流出错的情况，避免影响其他流
3. **资源管理**：确保流在不再需要时被正确关闭和清理
4. **兼容性**：确保新的设计与现有代码兼容

## 后续优化方向

1. 添加流量控制机制，防止某个任务产生过多输出
2. 实现更灵活的优先级策略，如动态调整优先级
3. 添加监控和统计功能，跟踪各个流的性能指标
4. 支持输出流过滤和转换，满足不同场景需求

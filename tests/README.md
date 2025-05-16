# 异步任务管理测试套件

本测试套件用于测试异步任务管理系统的各个组件，确保在进行优化和重构时不会破坏现有功能。

## 测试内容

测试套件包含以下测试文件：

1. **test_dispatcher.py** - 测试 `RuleDispatcher` 类的功能，包括：
   - 添加新规则
   - 处理上下文变化
   - 获取输出流
   - 关闭调度器
   - 任务执行成功和失败的情况

2. **test_rule_task.py** - 测试 `RuleTask` 类的功能，包括：
   - 任务初始化
   - 状态管理
   - 条件评估
   - 准备工具参数
   - 处理工具结果
   - 执行工具（成功、失败和重试情况）

3. **test_event_bus.py** - 测试 `EventBus` 类的功能，包括：
   - 订阅事件
   - 取消订阅
   - 发布事件
   - 处理回调错误

4. **test_observable_ctx.py** - 测试 `ObservableCtx` 类的功能，包括：
   - 设置和更新值
   - 追加到列表
   - 获取值
   - 转换为字典
   - 检查键是否存在

## 如何运行测试

使用以下命令运行所有测试：

```bash
pytest tests/
```

或者运行特定测试文件：

```bash
pytest tests/core/test_dispatcher.py
```

## 测试覆盖率

要生成测试覆盖率报告，请运行：

```bash
pytest --cov=core tests/
```

## 注意事项

1. 测试使用 `pytest` 和 `pytest-asyncio` 来测试异步代码
2. 使用 `unittest.mock` 来模拟依赖项
3. 测试会创建独立的事件循环，避免干扰主应用程序

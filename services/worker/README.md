# 任务状态骨架

`src/sw_worker/state.py` 定义 queued、running、waiting_user、succeeded、failed、cancelled 六态及合法转换，相关测试覆盖非法转换。

本阶段业务回放同步执行。尚未启动 Celery、Redis、Outbox、租约、检查点或可靠重试；状态机测试不证明异步任务可靠性。真实异步入口必须按[系统设计](../../docs/design/detailed-design.md)落实幂等、事务消息、执行租约和故障恢复后启用。

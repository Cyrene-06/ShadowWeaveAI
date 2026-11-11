# 后台任务服务

状态：目录骨架，尚无 Celery 应用、可消费队列或任务实现。

计划采用 Celery 与 Redis，执行素材分析、模型编排、代理生成、预览和导出等长任务。任务入口调度 `packages/ai` 和 `packages/media`，避免将算法和媒体命令复制到队列代码。

初始化后的建议布局：`app/tasks/` 放任务入口，`app/runtime/` 放执行上下文与检查点适配。队列名称、并发与重试配置待资源验证后确定。

任务需要幂等键、阶段状态、有限重试、超时、取消和错误分类；产物保存完成后才提交成功状态。详见 [架构中的任务约定](../../docs/architecture.md)。初始化时补齐启动方式、依赖、配置、故障恢复与重复投递验证。

任务租约与 Outbox 见 [数据库设计](../../docs/design/database-design.md)，图执行和恢复见 [Agent 设计](../../docs/design/agent-design.md)。

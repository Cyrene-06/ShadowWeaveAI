# 业务 API

状态：目录骨架，尚无 FastAPI 应用或已实现接口。

负责用户与项目权限、素材上传协调、任务受理与查询、创作意图和故事板、修改草案确认、版本管理及导出记录。耗时分析与渲染通过后台任务执行。

初始化后的建议布局：`app/api/` 放路由，`app/core/` 放设置和鉴权，`app/models/` 放持久化对象，`app/schemas/` 放请求响应，`app/services/` 放业务协调，`migrations/` 放数据库迁移。

外部 API 设计集中维护在 [接口文档](../../docs/api/README.md)，跨端对象见 [数据契约](../../packages/contracts/README.md)。引入持久化时明确事务、幂等和并发版本检查。

初始化时补齐 Python 环境、依赖与锁定、数据库迁移、开发启动、健康检查和测试命令。

接口和事务以 [系统详细设计](../../docs/design/detailed-design.md) 为准，表结构和迁移以 [数据库设计](../../docs/design/database-design.md) 为准。

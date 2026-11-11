# FastAPI 第一阶段服务

从仓库根目录安装依赖并迁移后运行：

```powershell
$env:ENABLE_PHASE_ONE_REPLAY='true'
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn sw_api.app:app --host 127.0.0.1 --port 8000
```

默认数据库为 SQLite `artifacts/phase-one.sqlite3`，PostgreSQL 通过 `DATABASE_URL` 切换。API 不自动建表，也不自动读取 `.env`。开发 JWT 密钥保存在被 Git 忽略的 `artifacts/jwt-secret.txt`；生产要求环境密钥，且禁止固定输入回放。

已实现健康检查、注册/登录、刷新轮换/退出、项目幂等创建/读取、owner/editor/viewer 授权，以及显式启用的第一阶段固定样例导入、回放、证据校验和真实媒体上传探针。错误格式、路径和请求字段见 [OpenAPI](../../docs/api/openapi.json)。

样例导入在单事务内完成，PostgreSQL 测试覆盖并发导入和失败回滚。样例素材记录明确标记 `fixture://human-annotation/`，不代表已上传原片。媒体探针上传文件处理后清理，不登记为真实 Asset，也不能完成补拍任务。

访问令牌 15 分钟；Web 刷新令牌由 HttpOnly Cookie 承载，cookie 刷新需可信 Origin；Flutter 令牌只在内存保存。开发限流为单进程内存实现。生产级用户管理、分布式限流、对象存储、可靠异步和版本提交尚未启用。

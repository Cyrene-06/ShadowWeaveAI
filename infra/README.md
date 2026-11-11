# 本地数据环境

第一阶段提供单个 PostgreSQL 17 开发容器；API、Web、Flutter 在宿主机运行。SQLite 可直接用于快速启动。Compose 不包含 Redis、S3 或可靠异步 Worker。

```powershell
docker compose -f infra/compose.yaml up -d --wait
$env:DATABASE_URL='postgresql+psycopg://shadowweave:phase_one_local_only@127.0.0.1:55432/shadowweave'
.venv/Scripts/python.exe -m alembic upgrade head
```

端口由 `SW_POSTGRES_PORT` 覆盖，口令由 `SW_POSTGRES_PASSWORD` 覆盖；均需同步连接 URL。默认口令是公开的本地测试值。停止服务用 `docker compose -f infra/compose.yaml stop`，该命令保留数据卷。

首次迁移建立 10 张基础表和 1 张开发样例表；不等同于完整 36 表设计落地。真实 PostgreSQL 的迁移、外键、并发与事务结果见[阶段报告](../docs/reports/phase-1-report.md)。

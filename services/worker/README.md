# Worker：状态与素材分析

`src/sw_worker/state.py` 保留通用 Job 六态。第一阶段固定样例仍是同步回放；第二阶段 `src/sw_worker/media_jobs.py` 是独立进程，从数据库领取视频分析任务，而非 Redis 或 Celery。

- `queued → probe → media → speech → publish → succeeded`，可中途 `failed`。粗粒度阶段不是完成百分比；通用 Job 将中间阶段映射为 `running`。
- 每次领取使用 15 分钟租约，阶段边界续期。进程崩溃后，可在租约过期时重新领取一次；累计两次仍中断则标 `WORKER_INTERRUPTED`。应用级失败立即终止，用户提交新代次重试，而不是无限自动重跑。失去令牌的旧 Worker 不得发布。
- 成功时一次数据库事务写入片段、观察和活动分析指针。失败可查原因，不覆盖上一成功版本；老版本的证据和预览可以按版本回溯。标签按片段分析版本保存，不自动迁移到新分析。

```powershell
.venv/Scripts/python.exe -m sw_worker.media_jobs        # 持续轮询
.venv/Scripts/python.exe -m sw_worker.media_jobs --once # 处理当前可领取的任务后退出
```

API/Worker 需共享数据库和本地 `ARTIFACT_DIR`，设置方式见[开发指南](../../docs/development.md#7-第二阶段素材证据链)。建议单机、单 Worker、可信素材；还没有生产容器资源隔离、心跳守护、队列监控或 S3 对象层。

原片在 `materials/original`，产物在 `materials/derived` 的任务/令牌目录；成功版本按需留存用于回溯。正常失败清理本次尝试的产物，崩溃可能留下未登记的文件。阶段二不提供在线自动回收。清理前应停 API/Worker、备份库和文件，按数据库 `stored_objects.storage_key`、`media_runs.result.preview_key`、`media_observations.frame_key` 核对引用；不能只按文件年龄、活动版本或租约过期判定。不要在演示库混入需要硬删除的私有素材。

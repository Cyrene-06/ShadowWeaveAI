# 接口与生成契约

当前可执行接口以 [OpenAPI](openapi.json) 为准，由 `scripts/export_contracts.py` 从实际 FastAPI 路由导出。项目级接口全部检查身份和成员关系；固定样例接口只在 `ENABLE_PHASE_ONE_REPLAY=true` 时注册，生产环境禁止该开关。

| 路径前缀 | 当前能力 |
| --- | --- |
| `/api/v1/health` | 检查服务和数据库基础表 |
| `/api/v1/auth/` | 注册、登录、轮换刷新、退出 |
| `/api/v1/projects` | 幂等创建、授权列表和读取 |
| `/api/v1/projects/{id}/phase-one` | 固定样例 seed、读取、replay、validate-evidence、media-probe |
| `/api/v1/projects/{id}/materials` | 受控视频上传、持久分析、检索、授权预览及证据导出 |

通用错误包含 `error.code/message/retryable/details` 和 `request_id`；响应带 `X-Request-ID`、`Cache-Control: no-store`。请求校验错误不回显密码或令牌。鉴权细节和本地启动见[API 说明](../../services/api/README.md)。

详细设计中的分块/对象存储上传、故事规划、编辑草案发布、工作流恢复等接口仍是后续目标；当前未通过路由暴露，不能由 OpenAPI 的存在推断已经实现全部设计。

## 第二阶段路由

以下相对于 `/api/v1/projects/{project_id}/materials`。读取需要项目访问权，上传、重新分析、打标签和证据导出需要写入权限。

| 方法与路径 | 参数与返回 |
| --- | --- |
| `POST /assets` | 查询 `name/source/rights_confirmed`，请求体为 `application/octet-stream`；返回 201、登记资产及最新状态。相同项目相同字节返回已有条目，`duplicate=true`，不重复排队或覆盖来源登记。 |
| `GET /assets` | 资产列表、当前活动分析及最新尝试；二者在新版本失败时可能不同。 |
| `GET /assets/{asset_id}/analyses` | 最近 50 代的阶段、尝试次数、错误、耗时和摘要。 |
| `POST /assets/{asset_id}/analyses` | 必须传 `Idempotency-Key`，成功 202；有分析进行中返回 409（同幂等键重放返回原结果）。 |
| `GET /search` | `q/asset_id/from_ms/to_ms/limit`，先过滤活动分析与源区间相交，再按转写、人工标签关键词排序；默认 20，最多 50。空查询可浏览；无命中返回空数组。 |
| `GET /segments/{segment_id}` | 读取指定已发布片段（含历史）；带原片哈希、分析版本及摘要、帧时间和上传者登记的来源。 |
| `POST /segments/{segment_id}/tags` | `{"label":"..."}`；仅向活动片段加入人工标签，不修改转写。 |
| `GET /segments/{segment_id}/frame` | 授权 JPEG 代表帧。 |
| `GET /analyses/{analysis_run_id}/preview` | 授权 MP4 代理，支持 `Range`（206）；不是原片下载或剪辑成片。 |
| `POST /evidence` | 提交明确复核过的 `bindings` 并返回共享 `EvidenceManifest`。拒绝越界、跨项目、错误版本和同资产跨版本混用；允许按同一成功历史版本复现。 |

目前限制为每项目 50 个视频，每段 20 个人工标签。`source` 是用户声明，不是服务验证的许可；不要提交带令牌/签名的 URL。搜索不自动判定语义或可用性；`semantic_support=unknown` 是候选默认。`queue_ms` 是首次领取减排队，`wall_ms` 含等待与处理；阶段处理耗时位于 `result.timing_ms`。Web 携带授权头下载受限代理至 Blob 后定位，尚未做流式预览客户端优化。

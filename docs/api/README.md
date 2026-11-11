# 接口与生成契约

第一阶段可执行接口以 [OpenAPI](openapi.json) 为准，由 `scripts/export_contracts.py` 从实际 FastAPI 路由导出。项目级接口全部检查身份和成员关系；固定样例接口只在 `ENABLE_PHASE_ONE_REPLAY=true` 时注册，生产环境禁止该开关。

| 路径前缀 | 当前能力 |
| --- | --- |
| `/api/v1/health` | 检查服务和数据库基础表 |
| `/api/v1/auth/` | 注册、登录、轮换刷新、退出 |
| `/api/v1/projects` | 幂等创建、授权列表和读取 |
| `/api/v1/projects/{id}/phase-one` | 固定样例 seed、读取、replay、validate-evidence、media-probe |

通用错误包含 `error.code/message/retryable/details` 和 `request_id`；响应带 `X-Request-ID`、`Cache-Control: no-store`。请求校验错误不回显密码或令牌。鉴权细节和本地启动见[API 说明](../../services/api/README.md)。

详细设计中的生产上传、故事规划、编辑草案发布、工作流恢复等接口仍是后续目标；当前未通过路由暴露，不能由 OpenAPI 的存在推断已经实现全部设计。

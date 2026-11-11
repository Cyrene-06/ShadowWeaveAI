# 影织 AI 系统详细设计文档

| 项目 | 内容 |
| --- | --- |
| 文档编号 | SWAI-SDD-R01 |
| 编制日期 | 2026-11-11 |
| 对应需求 | YINGZHI-AI-V1.1.0-20261110-FULL-R01 / SRS-R01 |
| 设计范围 | Flutter、Web、API、Worker、AI、媒体、存储与部署 |
| 文档状态 | 第一版实施设计草案；所有接口与流程尚待编码验证 |
| 配套文档 | [数据库设计](database-design.md)、[Agent 设计](agent-design.md) |

## 1. 目标、范围与设计原则

本设计将需求中的七大模块、七类 Agent、双端和五类场景映射为可分工实施的组件、数据对象和处理流程。首个可运行闭环与完整功能范围分开验收，不能以目录、模拟页面或固定响应证明智能能力已完成。

设计遵循：项目数据可追溯；耗时任务异步；模型只提出受约束的业务建议；确认动作由业务服务执行；已有版本不被失败任务覆盖；缓存与队列不能作为唯一事实来源。

内部首版以单套 PostgreSQL、对象存储、Redis 和少量 Worker 为部署起点。七类 Agent 是职责接口，不要求七个独立模型或微服务。模型型号、依赖版本和容量值须在原型验证后锁定。

## 2. 系统组成与代码布局

| 组件 | 建议实现模块 | 责任 |
| --- | --- | --- |
| `apps/web` | projects、assets、intent、director、storyboard、editor、review | Vue 页面、Pinia 状态、HTTP 与事件适配、预览和时间轴交互 |
| `apps/mobile` | capture、reshoots、uploads、projects | Flutter 采集、轻量摄影提示、补拍卡、离线待传与同步 |
| `services/api` | auth、projects、uploads、assets、stories、workflows、drafts、versions、exports | 身份、授权、校验、事务、任务受理、事件订阅 |
| `services/worker` | analysis、planning、render、maintenance | 消费任务、租约与心跳、恢复、结果持久化 |
| `packages/ai` | roles、graphs、providers、tools、evaluation | 七角色、状态图、模型适配、工具权限和评测 |
| `packages/media` | probe、analysis、timeline、render | 媒体解析、代理、确定性规则与渲染执行 |
| `packages/contracts` | schemas、examples、generated | 跨端输入输出、EDL、错误、事件和代码生成契约 |

上述为拟实现模块名。仓库当前只有目录职责文档；Python 命名空间与依赖锁文件在工程初始化时确定，不能直接将路径当作已可导入的包。

部署中拟将队列分为 `analysis`、`planning`、`render`、`maintenance`。模型编排和 CPU/GPU 媒体执行分别控制并发，防止长渲染占满普通接口资源。队列名是部署配置，不进入客户端契约。

## 3. 全局契约

### 3.1 标识、日期与序列化

- 业务主键采用服务端生成的随机 UUID，API 为 UUID 字符串，数据库为 `uuid`。文件哈希不承担访问控制或对象主键职责。
- 业务时间使用 UTC `timestamptz`，API 使用含 `Z` 的 ISO 8601；界面按用户时区显示。拍摄时间与入库时间分别存储；无拍摄元数据时留空，不用上传时间替代。
- 媒体和时间轴统一使用整数毫秒，区间为 `[in_ms, out_ms)`，时长为 `out_ms - in_ms`。禁止浮点秒参与业务比较。帧号仅在渲染适配层按有理帧率换算。
- `schema_version` 首版为 `1.0`；方案版本、Schema 版本和代码发布版本独立。
- JSON 字段使用 `snake_case`，所有时长携带 `_ms` 后缀；字节数以 `_bytes` 结尾。金额以数据库 `numeric` 和 API 十进制字符串表达。
- 分页使用稳定游标，如 `(created_at,id)`；默认 20 条、上限 100 条是初始接口设计值，可配置但不得静默改变排序。

### 3.2 权限和身份

首版设计采用邮箱与密码登录；密码仅存 Argon2id 哈希。访问令牌短期有效，刷新令牌使用随机不透明值、数据库存摘要，支持轮换和撤销。建议访问令牌 15 分钟、刷新会话 7 天，正式实现前验证客户端生命周期与密钥管理。

Web 访问令牌保存在内存，刷新令牌使用 HttpOnly、Secure、SameSite Cookie，刷新和退出验证 Origin 并采取 CSRF 防护。移动端刷新令牌使用系统安全存储。WebSocket 由鉴权接口签发一次性短期连接票据，禁止把长期令牌拼入 URL。接口开发时补充登录限流与令牌复用检测。

| 项目角色 | 可读 | 可写与执行 |
| --- | --- | --- |
| owner | 全项目 | 管理成员、归档/删除、编辑、确认、导出 |
| editor | 全项目 | 上传、编辑、任务、确认草案与导出；不能管理成员或删除项目 |
| viewer | 全项目 | 只读预览与进度；不得提交任务、确认或修改 |

每次通过项目资源操作都重新验证成员资格。owner 由 `projects.owner_id` 唯一表示，成员表只存 editor/viewer。资源签名 URL 短期有效，不能替代项目鉴权。跨项目访问返回 404，已授权用户权限不足返回 403。

### 3.3 错误、幂等与并发

错误结构：

```json
{
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "项目版本已变化，请重新生成修改草案",
    "details": {"expected_revision": 3, "actual_revision": 4},
    "retryable": false
  },
  "request_id": "req-example"
}
```

| HTTP | 业务错误 | 处理 |
| --- | --- | --- |
| 400 / 422 | INVALID_ARGUMENT / INVALID_TIMELINE | 展示字段或片段位置，修正后再提交 |
| 401 / 403 / 404 | UNAUTHENTICATED / FORBIDDEN / NOT_FOUND | 重新登录、权限提示或资源不存在 |
| 409 | VERSION_CONFLICT / IDEMPOTENCY_CONFLICT / RESOURCE_IN_USE | 更新基准或按提示处理依赖 |
| 410 | APPROVAL_EXPIRED / DRAFT_EXPIRED | 重新生成，不自动认可旧草案 |
| 413 / 415 | FILE_TOO_LARGE / UNSUPPORTED_MEDIA | 展示实际配置的文件限制 |
| 429 | RATE_LIMITED / BUDGET_EXCEEDED | 有限退避或等待用户调整预算 |
| 503 | DEPENDENCY_UNAVAILABLE | 保留已有状态，返回可重试信息 |

有副作用的 POST 接受 `Idempotency-Key`，按用户、项目（若适用）、操作和键去重。规范化请求哈希一致时返回同一业务资源，不一致返回 409。并发请求不重复产生任务；幂等记录与资源创建同事务提交。客户端在网络重试时复用键。

项目维护元数据 `revision` 和作品头 `head_revision`；前者保护名称、状态与成员变更，后者保护作品版本提交。草案记住 `base_version_id` 与 `base_revision`。确认时比较并交换项目头。单凭客户端最后读取的版本 ID 不足以识别“修改后又回退”的并发变化。

## 4. 客户端详细设计

### 4.1 Web 页面与状态

| 路由设计 | 页面状态与行为 | 主要数据 |
| --- | --- | --- |
| `/projects` | 列表、创建、归档、访问失败 | Project、当前版本、待办数 |
| `/projects/:id/assets` | 上传队列、分析状态、检索、原片定位、纠错 | Asset、Segment、AnalysisRun |
| `/projects/:id/intent` | 原文/语音、参数、约束冲突、确认意图 | Intent revision、未解决项 |
| `/projects/:id/director` | 阶段、角色、依赖、决策摘要、等待确认 | WorkflowRun、Job、AgentRun |
| `/projects/:id/storyboard` | 节点顺序、覆盖、候选证据、补拍与确认 | Storyboard、Node、Candidate |
| `/projects/:id/editor` | 素材左栏、预览中心、AI 右栏、下方轨道 | Version、EditDraft、EDL |
| `/projects/:id/review` | 问题定位、建议采纳、版本差异、恢复 | ReviewReport、Issue、Version |

Pinia 按项目、上传、任务、编辑会话拆分；服务端确认数据和本地未提交操作分别保存。页面切换不清除后台上传队列。版本变化后提示刷新或重新基线化，不把远端新状态覆盖到用户未保存的编辑内容。

时间轴拖动、字幕编辑与自然语言修改最终都转换成 EditDraft；本地预览是临时态，点击保存后通过同一校验与确认路径产生版本。播放器回传时间用于界面定位，不作为素材时间精度来源。

每个页面具备加载、空数据、失败、无权限和离线状态。进度有可测比例时才显示百分比，否则显示阶段。固定样例和预生成结果明确标注。

### 4.2 Flutter 采集与摄影提示

采集链路：权限检查 → Camera 会话 → 本地保存 → 文件摘要 → 上传队列。摄像头被占用、权限拒绝、低存储和应用进入后台时释放或暂停资源，并保留已经保存的文件。

本地轻量提示按受控采样频率计算亮度、模糊、主体位置与稳定性。初始建议采样上限 2 帧/秒、只保留最新待分析帧，属于待真机调优值；不把每一帧上传或写数据库。语义摄影建议可由云端异步返回，单独标记延迟和不确定性。NFR-PERF-001 的 500 ms 目标只统计本地分析。

本地上传记录至少含本地文件标识、project_id、capture_task_id、session_id、分片进度、重试原因和修改时间。恢复时先查询服务端会话与分片，避免仅凭本地进度重复完成。设备文件被删除时标记待重新选择。

补拍卡展示“拍什么、为什么、如何拍、建议时长、关联节点”。用户可以无法补拍并选择替代路径；拍摄上传只是提交证据，服务端重新分析后才判断节点是否覆盖。

## 5. API 目录与输入输出

统一前缀 `/api/v1`。下表是拟实施路由，尚不可调用。GET 默认 200；创建同步资源 201；长任务受理 202；删除或无响应动作 204。所有项目资源位于 `/projects/{project_id}` 作用域，服务端不得只凭子对象 ID 越过授权。

| 方法与路径（省略 `/api/v1`） | 输入要点 | 输出/行为 |
| --- | --- | --- |
| POST `/auth/register`、`/auth/login` | email、password | 用户/访问令牌，建立刷新会话 |
| POST `/auth/refresh`、`/auth/logout` | Cookie 或移动端刷新凭据 | 轮换/撤销会话 |
| GET/POST `/projects` | 游标；name、scenario | 项目列表/新项目 |
| GET/PATCH/DELETE `/projects/{p}` | if_revision；name、状态 | 项目详情/修改/软删除；DELETE 仅 owner |
| GET `/projects/{p}/members`；GET/PUT/DELETE `/projects/{p}/members/{user_id}` | role（写入时） | owner 管理成员；GET 单成员 |
| GET/POST `/projects/{p}/upload-sessions` | original_name、size_bytes、sha256、capture_task_id | 上传会话；配置的分片大小与过期时间 |
| POST `/projects/{p}/upload-sessions/{s}/parts/{part_no}/sign` | part_size_bytes | 当前分片的短期签名地址 |
| POST `/projects/{p}/upload-sessions/{s}/complete` | 有序 part_no、etag、校验信息 | 完成任务 ID，异步校验后生成 Asset |
| POST `/projects/{p}/upload-sessions/{s}/abort` | reason | 中止未完成会话并安排暂存清理 |
| GET `/projects/{p}/upload-sessions/{s}` | 无 | 分片列表、状态、asset_id 或错误 |
| GET/DELETE `/projects/{p}/assets/{a}` | 删除理由；可选替代引用 | 元数据/删除处理，受引用时返回影响 |
| GET `/projects/{p}/assets` | 游标、状态、类型 | 素材列表 |
| POST `/projects/{p}/assets/{a}/analysis-runs` | profile、config_revision | 分析 Job；不等待结果 |
| POST `/projects/{p}/search` | query、filters、embedding_space_id | 区间、来源、置信度与检索方式 |
| POST `/projects/{p}/segments/{s}/annotations` | supersedes_id、kind、payload | 新纠错记录，原模型结果保留 |
| POST `/projects/{p}/intents` | 原文、target_duration_ms、constraints | 意图草案，revision |
| POST `/projects/{p}/intents/{i}/confirm` | revision、明确参数 | 确认快照，之后不就地修改 |
| POST `/projects/{p}/workflows` | kind、intent_id、base_version_id、预算 | WorkflowRun 与根 Job |
| GET `/projects/{p}/jobs/{j}` | 可选 after_seq | 状态、阶段、错误、事件游标 |
| POST `/projects/{p}/jobs/{j}/cancel`、`/retry` | reason；失败策略 | 取消请求；失败作业的新 Job，关联 retry_of_id |
| GET `/projects/{p}/workflows/{w}` | 无 | 角色任务、产物和待确认事项 |
| POST `/projects/{p}/approvals/{a}/decide` | decision、payload_hash、base_revision | 单次确认结果；恢复工作流事件 |
| GET `/projects/{p}/storyboards/{b}` | 无 | 节点、候选和覆盖依据 |
| POST `/projects/{p}/storyboards`、`/{b}/confirm` | 来源/节点草案；revision | 新草案/确认快照 |
| POST `/projects/{p}/capture-guidance` | 受限帧引用、场景摘要、capture_task_id | 云端摄影建议 Job；端侧分析不走此接口 |
| GET/POST `/projects/{p}/capture-tasks` | 筛选；节点、要求 | 拍摄与补拍卡 |
| PATCH `/projects/{p}/capture-tasks/{t}` | if_revision、choice、reason | 用户领取/无法补拍/重新打开等明确操作 |
| POST `/projects/{p}/edit-drafts` | base_version_id、base_revision、target、operations | 手工草案，或异步 AI 草案 Job |
| GET `/projects/{p}/edit-drafts/{d}` | 无 | 候选 EDL、差异、影响与校验报告 |
| POST `/projects/{p}/edit-drafts/{d}/confirm` | payload_hash、base_revision、unlock_clip_ids | 不可变 Version 与新 head_revision |
| GET `/projects/{p}/versions`、`/{v}` | 游标/版本 | 历史/完整快照 |
| POST `/projects/{p}/versions/restore` | target_version_id、base_revision | 创建复制目标内容的新版本，保留历史链 |
| POST `/projects/{p}/versions/compare` | left_version_id、right_version_id | 镜头、字幕、声音及约束差异 |
| POST `/projects/{p}/versions/{v}/reviews` | 检查范围、profile | 审片 Job |
| GET `/projects/{p}/versions/{v}/reviews` | 游标 | 报告、问题位置与状态 |
| PATCH `/projects/{p}/review-issues/{i}` | disposition、reason | 采纳/忽略/已验证修复等用户处置 |
| POST `/projects/{p}/versions/{v}/exports` | purpose、preset、编码参数 | Export 与渲染 Job |
| GET `/projects/{p}/exports/{e}` | 无 | 阶段、结果对象、过期的下载地址可重签 |
| GET `/projects/{p}/events` | after_project_seq、limit | 持久化事件补拉或游标过期提示 |
| POST `/projects/{p}/events/ticket` | 客户端 last_project_seq | 一次性 WebSocket 票据 |
| WS `/projects/{p}/events` | ticket、last_project_seq | 事件通知，缺口时补拉查询 |

`GET /health/live` 与 `/health/ready` 计划用于部署探测；后者检查必要依赖可用性但不触发模型调用。批量删除、成员邀请邮件、外部视频编辑器格式等不在首版接口扩展中预先实现。

### 5.1 创建异步任务示例

```json
{
  "workflow_id": "00000000-0000-4000-8000-000000000010",
  "job_id": "00000000-0000-4000-8000-000000000011",
  "state": "queued",
  "status_url": "/api/v1/projects/00000000-0000-4000-8000-000000000001/jobs/00000000-0000-4000-8000-000000000011"
}
```

任务通知包含 `event_id`、`job_id`、`seq`、`type`、`state`、`stage`、`occurred_at` 与摘要；每个 Job 的 seq 单调递增，project 事件游标使用持久化的 project_seq，与单 Job 的 seq 分开。projects.event_seq 在项目行锁下递增，与 Outbox 同事务提交；重连按 project_seq 补拉，去重并查询最新状态。游标早于已保留窗口时返回 EVENT_CURSOR_EXPIRED，客户端进行全量状态重同步。

## 6. 素材上传、分析与检索

### 6.1 上传与存储

1. API 鉴权后建立上传会话。分片大小、总大小和类型限制由配置返回，不能只在客户端校验。
2. 客户端通过短期签名地址上传到项目隔离的暂存对象；存储对象键由服务端生成，不使用未经处理的原文件名。
3. 完成请求写入 `completing` 并派发合并/校验 Job，重复调用返回同一任务。
4. Worker 确认服务端对象大小与 SHA-256，探测真实格式及可解码性；不能把 multipart ETag 当作完整 SHA-256。
5. 校验成功后原子关联 StoredObject、Asset 和后续分析事件；会话进入 `completed`。失败进入 `failed`，保留原因，暂存对象按策略回收。
6. 仅在同一项目内按实际原片哈希去重；新提交的补拍关系仍需关联 capture_task_id，不因文件去重丢失业务记录。

分片记录与对象存储之间采用可重入校验与对账。对象已完成但 DB 未提交时，重试通过同一上传操作标识查找对象，不重新覆盖其他用户文件。

### 6.2 分析流水线

探测 → 代理/缩略图 → 切镜/关键帧 → 转写/OCR → 标签、事件与质量 → 向量索引 → 发布结果。阶段按依赖拆成 Job，能独立缓存与重试。无音轨时转写为 not_applicable 的阶段结果，不能误报整次分析失败。

AnalysisRun 固定媒体哈希、配置摘要、模型版本与产物；新分析生成新 run 和 segment，成功后再切换 `assets.active_analysis_id`。切换前旧索引继续有效；失败不能混入半成品。已有版本引用旧 segment 时继续可追溯。

照片作为静态素材保存，分析 segment 的 `in_ms/out_ms` 均为 NULL；显示时长由时间轴决定。视频/音频 segment 为正时长半开区间。用户纠错采用新 Annotation 覆盖语义，不删除原模型结果。

### 6.3 检索

服务端首先应用项目授权、未删除素材与 active_analysis_id 过滤，再进行关键词、条件和同一向量空间内的检索。返回 asset_id、segment_id、原片区间、摘要、证据与分数来源；缺少地点/人物确认时不得伪造过滤结果。

文本向量与图文对齐向量使用不同 `embedding_space_id`；维度相同也不能直接混搜。首版小样本优先精确检索，验证召回后再使用索引。候选不足时回退关键词或扩大受限检索，并在响应说明策略。

## 7. 意图、故事板与补拍

意图由原文/转写生成草案，用户确认主题、时长、画幅、情绪、必留、禁用及重点人物。冲突字段不进入默认推断，置为待确认。任何修改生成新 intent revision；任务始终绑定确认过的 intent_id。

故事板以 revision 管理：draft 可编辑，confirmed 不可改。节点包含目标、镜头要求、情绪、顺序、预算和候选证据；覆盖分为 `covered`、`insufficient`、`uncertain`、`missing`，用户略过使用独立 resolution 字段，避免把“略过”写成“已覆盖”。

用户确认时校验节点顺序、总时长预算、必留条件与未解决缺口。略过必需节点或改变主题需要新的明确确认。照片替代、环境音或结构调整均由用户选择。

补拍任务状态为 `open → in_progress → submitted → fulfilled`；`submitted` 代表收到已完成上传的素材，只有更新后的分析和覆盖验证能进入 fulfilled。`unable`、`cancelled` 表示无法执行或取消，不代表覆盖成功。新素材导致新故事板 revision，旧确认快照保持不变。

## 8. EDL 与时间轴规则

### 8.1 快照结构

EDL 是版本内容的规范化序列化，不是数据库之外另一份可独立修改的事实源。保存版本时在一个事务内写入关系轨道/片段和规范化摘要，按确定排序导出 EDL；读取时可校验摘要一致性。

```json
{
  "schema_version": "1.0",
  "duration_ms": 5000,
  "output": {"width": 1920, "height": 1080, "fps_num": 25, "fps_den": 1},
  "tracks": [{
    "track_key": "video-main", "kind": "video", "position": 0,
    "clips": [{
      "clip_key": "opening-01", "kind": "video",
      "asset_id": "00000000-0000-4000-8000-000000000101",
      "segment_id": "00000000-0000-4000-8000-000000000102",
      "src_in_ms": 1000, "src_out_ms": 6000,
      "dst_in_ms": 0, "dst_out_ms": 5000,
      "speed_num": 1, "speed_den": 1,
      "locked": false, "config": {}, "dependencies": []
    }]
  }]
}
```

示例只有视频轨；字幕、旁白、音乐、环境音在不同轨道。稳定的 track_key/clip_key 跨版本保留，数据库行 ID 每个版本重新创建。

### 8.2 媒体与轨道约束

- 轨道 kind：`video`、`subtitle`、`voiceover`、`music`、`ambience`。片段 kind：`video`、`image`、`audio`、`subtitle`；兼容矩阵在数据库文档定义。
- video/audio 必须引用 Asset，源范围在原片与已引用 Segment 内。image 引用图片 Asset，src 为 NULL。subtitle 文本存 config，asset/segment/src 为 NULL。
- 目标区间总在 `[0,duration_ms]` 内。普通视频/音频遵循 `src_duration * speed_den / speed_num = dst_duration`，首版只允许正向速率，误差按明确帧舍入容差验证。
- 同一视频轨片段默认不得重叠；显式转场允许相邻片段重叠，重叠长度必须与 config 指定长度相等，且不越过源片段可用范围。字幕按层处理，声音轨混音允许重叠。
- 字幕的相对位置、依赖音频和锚定片段变化需纳入依赖传播；删除一个片段不能留下悬空依赖。
- 输出参数只能来自允许的预设与白名单，路径、滤镜和执行命令不由模型直接指定。

### 8.3 锁定和变更影响

首版 `locked=true` 表示整片段锁定：源、入出点、目标区间、速率、config 和依赖均保持不变。锁定内容向后移动也算变更。排除数据库 ID 与版本 ID，按稳定键与规范化内容计算锁定摘要。

局部重规划从目标片段沿依赖边计算影响集合，并加入目标时间段重叠、后续顺延和节点预算约束。若触及锁定内容，返回冲突；用户明确提交 unlock_clip_ids 后才能形成解锁后的新版本。普通“确认修改”不能隐式解锁。ready 草案应事先列明 requested_unlock_clip_ids；确认提交的 unlock_clip_ids 必须与该受 payload_hash 保护的集合一致。新增解锁目标需生成新草案，不能在确认请求中临时扩大修改范围。

## 9. 修改、确认与版本事务

```mermaid
sequenceDiagram
    actor U as 用户
    participant API as API
    participant W as Worker/Agent
    participant DB as PostgreSQL
    U->>API: 提交修改(base_version, base_revision)
    API->>DB: 草案+Job+Outbox
    API-->>U: 202 + job_id
    W->>DB: 领取Job，读取不可变输入
    W->>W: 生成差异，规则校验，计算锁定摘要
    W->>DB: 保存ready草案+payload_hash
    U->>API: 确认草案(hash, revision)
    API->>DB: 锁项目头+复查权限、素材和约束
    API->>DB: 新版本+轨道片段+head_revision+1+Outbox
    API-->>U: 新版本ID
```

版本内容提交和导出发布分开。确认可以保存一个尚无预览文件的合法版本；预览/导出成功后另行增加 Export 记录，不改版本内容。任务失败只改变任务与产物状态，不清除当前版本或历史已成功导出。

确认时重新读取项目、草案和素材状态，防止生成后素材被删除或用户失去权限。`payload_hash` 必须匹配用户看见的草案。两用户确认不同草案时只允许匹配当前 revision 的事务成功，另一方返回 409。

恢复历史版本采用“复制目标内容形成新 Version，parent 指向恢复前当前版本，restored_from 指向目标版本”；head_revision 递增。若历史素材已被删除且不可用，恢复被阻止并列出缺失项，不自动声称可重新渲染。

## 10. 审片、预览和导出

审片分两路：规则检查确定性错误；模型检查叙事、重复和主观建议。问题记录 severity、category、location、evidence、confidence、suggestion 和 disposition。缺乏可靠检测条件时标记待复核，不把“未发现”作为合格证明。

输出分 `purpose=preview|final`，绑定精确 version_id、content_hash、preset_hash 和渲染配置。预览和正式导出可分辨率不同，但使用同一时间轴；界面清楚标记代理质量与真实成片。

导出步骤：鉴权 → 验证引用与规则 → 去重受理 → 规范化输入 → 分段/整段处理 → 封装 → 解码抽检、参数与时长检查 → 上传临时对象 → 对象 HEAD/校验 → 事务标记对象 available 与 Export succeeded。下载地址按需签发。

复用分段缓存按媒体哈希、源范围、变换、工具版本和参数计算，不只按素材 ID。局部重规划不承诺 MP4 只渲染局部；分别记录规划、片段处理和封装/编码时间。

## 11. 长任务与一致性

Job 状态统一为 `queued/running/waiting_user/succeeded/failed/cancelled`。waiting_user 释放 Worker 执行资源，通过持久化 approval 再恢复，不让进程长时间阻塞等待。

API 在同一事务写业务变化、Job 与 outbox_events；派发器至少一次发布，消费者按 Job/幂等键和执行租约去重。业务任务状态以 PostgreSQL 为准，Celery 结果后端只用于调度辅助。

Worker 以 `lease_token` 和 `lease_expires_at` 领取执行，心跳续租；完成写入必须匹配 lease_token。租约过期后回收器检查可恢复产物，重新排队或明确失败；旧 Worker 的迟到提交被拒绝。外部调用仍可能发生多次，不能宣称端到端 exactly-once。

取消通过 cancel_requested_at 请求，Worker 在阶段边界和受控子进程中检查。渲染终止后清理暂存，不删除已发布产物。用户重试失败 Job 创建新 Job 并关联 retry_of_id；基础设施重投递仍属于原 Job 的 attempt。

## 12. 安全、删除与隐私

上传按大小、格式、解码与资源限制检查，服务端生成路径，媒体子进程使用参数数组、限制时长和临时目录。模型输入中的素材文字和转写是数据，工具只接受结构化参数并再次鉴权。

用户可先查询删除影响。素材无版本引用时可标记删除并异步回收；被不可变版本引用时默认返回 RESOURCE_IN_USE。owner 如明确选择强制删除，保留元数据墓碑及引用，停止未来检索/渲染，将相关版本呈现为素材缺失；既有导出按明确的项目删除/保留政策处理，不静默丢失。

数据库和对象存储之间无跨系统事务。使用删除标记、延迟回收和对账，不在单次 API 中先删原片再提交 DB。项目删除先撤销访问并取消任务，再按引用与保留期清理；数据保留期是部署前待确认事项。

## 13. 可观测性与性能

日志统一包含 request_id、project_id、workflow_id、job_id、agent_run_id、version_id、step、attempt、duration_ms、error_code。决策保存可读摘要与来源，不要求保存模型隐藏推理。日志和错误响应不包含密钥、完整个人转写或签名 URL。

指标拆分上传、排队、分析、规划、waiting_user、渲染和下载。P95 需要样本量和硬件，不用单次演示替代统计。需求目标保持原值：本地摄影分析 500 ms、故事规划 180 s、局部规划 20 s、导出 180 s、可测音画偏移 100 ms；这些均未实测。

首轮负载采用 30 段、约 10 分钟输入、120 秒 1080p 输出，记录队列负载、格式、编码、模型位置与网络。优先识别等待和重复工作，再决定缓存、并发或索引调整。

## 14. 部署、配置与实现顺序

开发环境拟用 Compose 提供 PostgreSQL/pgvector、Redis 和 S3 兼容存储；API、Worker 可本机或容器运行。数据库迁移作为独立步骤先执行，再启动消费者。服务启动检查 schema 兼容性，失败时不得继续处理旧格式任务。

已有 `.env.example` 只是配置草案。实际初始化时增加鉴权密钥引用、允许源、上传上限、超时、队列并发、模型预算、对象保留和检查点配置，同时更新环境文档；密钥不写 model_profiles。

实施批次：身份与项目/迁移 → 上传与 AnalysisRun → Jobs/Outbox/租约 → 首个合法 EDL 与版本 → Web/移动端闭环 → 故事与七角色 → 审片、补拍、局部修改 → 故障与效果验证。每个批次补齐对应启动与检查命令。

## 15. 需求追踪与验收用例

| 范围 | 需求 | 主要设计 | 验收要点 |
| --- | --- | --- | --- |
| 双端与项目 | FR-SYS-001—008 | 3、4、5、11 节 | 双端同项目，角色隔离，断线重连 |
| 摄影 | FR-CAM-001—008 | 4.2、7 节 | 真机提示，权限拒绝，补拍回传 |
| 素材 | FR-MAT-001—010 | 6、12 节 | 校验去重、区间检索、再分析与删除影响 |
| 意图 | FR-IDEA-001—005 | 7 节 | 冲突可见，确认快照，任务绑定版本 |
| Agent | FR-AGT-001—008 | 7、11 节及 Agent 文档 | 七角色有实际输入输出，人工暂停与恢复 |
| 故事 | FR-STO-001—009 | 7 节 | 四类覆盖，补拍/替代/略过，新增素材更新 |
| 剪辑 | FR-EDT-001—011 | 8、9、10 节 | 非法范围拒绝、锁定、差异、声音依赖和导出 |
| 审片 | FR-REV-001—010 | 9、10 节 | 问题可定位，版本对比与历史恢复 |
| 非功能 | NFR-*（含 NFR-COMP-001—002） | 11—14 节 | 中断、重复、权限、备份和真实计时 |

具体需求编号沿用 [需求基线](../requirements.md)，不能新造编号代替原文。跨组件必测场景：

1. 重复完成上传、重复确认与重复导出，均只产生一个对应业务资源。
2. 新分析失败，旧分析仍可检索；成功切换后新搜索不混入旧索引。
3. 两客户端基于同一 revision 修改，后确认者收到 409，已有版本不损坏。
4. 修改开场长度触及锁定结尾，必须提示冲突且不能暗中顺延。
5. Worker 在对象上传后、事务提交前崩溃，恢复不重复发布；租约失效后拒绝旧结果。
6. waiting_user 时重启，用户一次确认只恢复一条工作流分支。
7. 删除在用素材有影响提示，强制删除后检索隐藏且恢复/渲染明确失败。
8. 同维度不同模型向量不混搜，图文能力与文本检索分别报告。

这些是拟验收用例，当前没有执行记录。

## 16. 设计决策与待验证项

| 决策 | 本版选择 | 变更门槛 |
| --- | --- | --- |
| 时间与标识 | UUID、UTC、整数毫秒、半开区间 | Schema 变更需迁移和多端同步 |
| 版本 | 不可变快照，恢复生成新版本 | 不允许运行中静默改历史 |
| 队列一致性 | Outbox、至少一次、租约与幂等 | 需中断与重复投递验证 |
| 授权 | owner/editor/viewer、项目域 | 共享模式扩展前补权限矩阵 |
| 检索 | 分向量空间，先精确后索引 | 实测召回、过滤和内存后决策 |
| 鉴权 | 短访问令牌+可撤销轮换刷新会话 | 依赖与跨端会话原型验证 |
| 仍待确定 | 依赖、模型、维度、文件限制、编码预设、设备与保留期 | 在首阶段技术验证记录结果与修订号 |

## 17. 技术依据

2026-11-11 设计核对范围为 PostgreSQL 约束、pgvector、Celery、FastAPI 安全示例及 LangGraph 持久化/中断的官方说明。具体版本不在本设计中推定为“最新”或已安装，实际实现锁定后需重新核验，链接列于 [数据库设计](database-design.md) 和 [Agent 设计](agent-design.md)。

FastAPI 身份验证参考：<https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/>。其中示例仅提供组件用法，本项目的项目域授权、刷新会话、CSRF 与撤销仍需单独实现和验证。

# 第一阶段数据准备与标注交接指南

| 项目 | 内容 |
| --- | --- |
| 文档编号 | SWAI-DATA-P1-R01 |
| 日期 | 2026-11-11 |
| 对应交付 | 第一阶段大纲 T09、T10；评测协议的数据清单、标注指南与运行记录模板 |
| 当前状态 | 模板、离线校验入口已实现；真实评测数据采集、人工标注及正式实验待执行 |
| 创新验证用途 | 将证据覆盖、补拍和局部重规划假设转成可追溯的人工参照与配对对照 |

本指南配合[评测协议](evaluation.md)使用，不修改其中的分组、分母和门槛。[空白模板与 Schema](../examples/evaluation/README.md)用于准备记录；填写为 `ready` 只表示具备结构与一致性条件，不能证明已经拍摄、获得授权、完成人工评审或实际执行实验。

## 1. 数据清单与采集步骤

1. 按五类场景登记候选任务：`campus`、`travel`、`family_friends`、`vlog`、`organization`。目标仍为每类 3 组、每组至少 20 段，共 15 组至少 300 段；目前没有完成这一采集目标。
2. 为任务创建稳定 `task_id` 和 `event_id`，通过 `intent_ref` 关联用户确认的原始故事要求。另存必需节点 R0、允许替代、可略过项、锁定集合、拍摄条件和用户确认记录；后续调整保留修订与理由。
3. 复制 `dataset_manifest.template.json`，逐素材填写原片 URI、实际 SHA-256、媒体类型、实测时长、来源类型、事件、近重复组及父素材 ID。`source_uri` 指向受控存储，不填写临时访问令牌。
4. 审核来源和使用范围：授权登记须能从 `permission_ref` 找到原件、权利范围、到期或撤回条件。开发、评测、公开展示分别登记；获准开发不自动代表可公开展示。未知授权保持 pending，不能加入 ready 任务。
5. 先分组再划分集合。每场景 1 组开发、2 组冻结测试；同一事件、相同字节、近重复组，以及原片和裁剪/转码的父子家族只能落在同一集合。近重复组由人工或工具发现后登记；校验器只检查已声明分组，不负责识别未登记的近重复。
6. 生成数据版本，在正式运行前冻结清单、意图、标注、阈值和条件配置，保存清单字节的 SHA-256。发现泄漏或撤回授权时新建版本并披露受影响任务，不能覆盖旧版本后继续复用旧成绩。

| 字段 | 填写约定 | 复核责任 |
| --- | --- | --- |
| `source_kind` | 实拍为 real_capture；工具生成探针为 generated_probe；纯规则元数据为 synthetic_metadata | 采集者保存原始来源，复核者检查 |
| `duration_ms` | 音视频用实际探测结果；图片/元数据可为 null | 数据维护者核对原片与探测工件 |
| `duplicate_group` | 每份素材都填写组；疑似同源内容先归组，不能按期待结果拆组 | 两人复核分组 |
| `parent_asset_id` | 裁剪或转码指向原片，原片无父项；父链完整且无环 | 数据维护者复核家族 |
| `rights` | 状态、授权引用和允许用途均填写；仓库只保存脱敏引用 | 实际授权审核人签署 |

任务引用的每个素材会检查用途、音视频时长和父链；未被任务使用的目录条目不代表已经获准进入实验。正式冻结时清理未使用项或在清单 notes 解释其用途。校验器不会下载 source_uri、计算原片字节 hash、鉴定授权真伪或检测设备、地点和时间隔离；这些检查须由采集和复核人员完成并保存记录。生成探针和纯元数据不能进入冻结测试任务。

## 2. 独立标注与裁决

两名真实标注者分别复制 `annotation.template.json`，设置 `annotation_stage=independent`，独立查看同一冻结任务与原始意图。使用不同的 annotator_id，先完成各自文件再交流；不展示系统方案、组别或另一人的答案。标注员训练使用开发集，不能借训练更改冻结任务答案。

对每个故事节点记录以下内容：

- `node_key` 与 `requirement_keys`：逐项列出冻结要求，避免将系统生成的新要求当成人工真值。
- `evidence`：指向该任务的素材；音视频用原片毫秒区间 `[in_ms, out_ms)`，满足 `0 ≤ in < out ≤ duration`。不得填写成片时间；图片不伪造时长。
- `semantic_support`：supported 表示片段能支持指定要求，unsupported 表示明确不支持，unknown 表示当前无法确认。填写 rationale 解释人物、动作、时间或语义依据；模型自评分不能代替人工判断。
- `quality_usable`：能否满足该要求的观看/听辨条件。遮挡、模糊、音频不可辨或连续时长不足的原因写入 rationale 与 gap_types；未知使用 null。
- `search_complete`：是否完成约定候选池及工具状态检查。搜索失败或未完成不能直接记为 missing。

| 覆盖标注 | 人工判断约定 | 必须保留的依据 |
| --- | --- | --- |
| covered | 每项要求都有可用支持，且满足该节点时长和质量条件 | 对应要求的素材区间、可用性和解释 |
| insufficient | 已有支持但覆盖、质量、时长等条件不足 | 可用/不可用部分与具体缺口 |
| uncertain | 检索未完成、来源/语义/质量无法确定等 | 未决问题、失败步骤和待复核项 |
| missing | 约定搜索已完成，仍无支持证据 | 候选池、排除理由和完成搜索的记录 |

离线校验会拒绝未完成搜索却标 missing、没有支持却标 insufficient、每项要求缺少可用证据却标 covered，以及跨任务或越界证据。它不计算真实语义、覆盖时长阈值或质量分数；完整判定仍依赖冻结准则和真实人工复核。gap_types 使用团队冻结的分类词表，至少区分语义、质量、时长、授权/条件与未知；当前字段结构不负责验证词表含义。

局部修改用 `edits` 逐请求登记 request_id、目标稳定 clip_key、**求解前**可接受的影响集合、锁定键及理由。所有标注者查看同一基准、依赖和冻结约束；记录多种合法替代及无法确定项，不能把执行后实际 diff 反填成唯一标准答案。依赖图、批准范围、完整 EDL 和解锁证明保存在关联工件中；离线标签字段不替代业务内核的校验。

第三人裁决时新建 `annotation_stage=adjudicated` 的文件，记录 adjudicator_id、两个独立文件的不同引用、分歧和裁决理由，保留两份原稿及修订链。两个不同引用的结构检查不能证明由两个不同人完成；成员身份和独立性由真实复核记录确认。

## 3. 运行记录与失败保留

每个任务、条件和重复轮次单独创建 `evaluation_run` 文件。A/B/C 与 D1/D1b/D2/D3 的定义沿用评测协议；模板的 condition 为空，不预填成功结果。第一阶段准备这些记录，不据此声称完成模型对照。

运行前冻结数据版本、input_manifest_hash、完整 40 位代码提交、模型/提示/图版本、随机种子及硬件、预算。无适用版本填写 `not_applicable` 并解释；需要随机性控制却无法设种子时保留 null 并说明限制。budget 与 hardware 为配置记录，当前校验器不执行预算或验证硬件真实性。

收到任务时记 UTC `received_at`；结束记 `finished_at`。分别保留用户操作、waiting_user、队列、模型、渲染和下载耗时；timings_seconds 使用有限非负数。结束不能早于开始；waiting_user 可以保留未结束边界，不作为已完成任务计时。

状态使用 succeeded、failed、timed_out、cancelled、waiting_user、budget_exceeded；失败、超时、取消和超预算必须填写 failure_code。未运行的记录保持 template / not_run。原始工件引用 raw_artifact_refs 应包含输入、日志、输出或失败详情，敏感内容留在受控存储。

未实际调用模型时 model_called=false，model_profile、usage、cost 均为 null，不能填估算 token 或费用冒充实测。实际调用时记录配置与提供商返回的用量、计价币种和依据；未返回用量保持缺测并解释，不能根据费用字符串推断已计费。校验器只要求声明调用时配置非空，不审核计价真实性。

保留失败、无解、用户拒绝、等待、超预算及每次重试，不覆盖为最后一次成功。汇总必须按协议固定分母，并报告自然/构造缺口、逐场景和未决项。第一阶段单元测试与固定样例不进入正式实验分母。

## 4. 生成、填写与校验

从仓库根目录、已安装项目开发环境的 Python 执行：

```powershell
python scripts/prepare_evaluation.py --check
python scripts/validate_evaluation.py examples/evaluation/dataset_manifest.template.json examples/evaluation/annotation.template.json examples/evaluation/evaluation_run.template.json
```

第二条只检查空白模板结构，输出 execution_or_human_review_proved=false。实际采集时复制到受控工作目录、填完后设置 record_stage=ready，再按依赖检查：

```powershell
python scripts/validate_evaluation.py artifacts/evaluation/dataset_manifest.json --ready
python scripts/validate_evaluation.py artifacts/evaluation/annotation-a.json artifacts/evaluation/annotation-b.json --manifest artifacts/evaluation/dataset_manifest.json --ready
python scripts/validate_evaluation.py artifacts/evaluation/run.json --manifest artifacts/evaluation/dataset_manifest.json --ready
```

这些路径是填写后的约定位置，仓库不提供虚构的 ready 样本。ready 注释与运行记录必须引用已验证的同版本 manifest 和任务。JSON Schema 检查字段形状；跨字段、跨文件与防泄漏检查必须运行 Python CLI。修改离线契约后运行 `python scripts/prepare_evaluation.py` 更新生成物；业务 21 个契约及双端 42 个共享用例仍独立维护。

## 5. 独立复现交接表

以下为空白签署表。当前未有其他成员的复现签名；本机运行或远端 CI 均不能代填。

| 交接项 | 待填写内容 |
| --- | --- |
| 实际复现者/复核者 | 待填写真实成员及日期 |
| 环境与目标版本 | 系统、设备、依赖、40 位提交、数据版本和 hash |
| 指南执行记录 | 安装、数据库迁移、API、Web、Flutter 命令及 exit code |
| 两组创新演示 | 输入/输出、失败反例、锁定/范围检查、submitted 与 fulfilled 区别 |
| 数据复核 | 来源/授权、分组隔离、两份独立标注及裁决引用 |
| 差异与阻塞 | 可复现/不可复现项、原始日志引用、负责人及复核日期 |
| 验收结论 | 根据实际结果填写通过、部分通过或存在阻塞；签署后方可更新报告 |

完整启动步骤见[开发指南](development.md)，任务与验收对应见[第一阶段大纲](phase-1-outline.md)，当前实际完成与未验证依赖见[阶段报告](reports/phase-1-report.md)。媒体、密钥、签字授权原件、个人信息与原始浏览器 trace 不提交公共仓库；仓库只纳入脱敏模板、规范和可审阅的小型摘要。

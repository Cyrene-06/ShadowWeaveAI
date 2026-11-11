# 共享数据契约

状态：契约设计目录，尚无正式 Schema、生成代码或可安装包。

这里维护 Web、Flutter、API、Worker、AI 与媒体层之间需要一致理解的数据结构。首批对象包括 Project、Intent、Asset、Segment、StoryNode、ReshootTask、Job、Timeline、Clip、ReviewIssue 和 Version。

## 已确定的基础约定

- UUID 标识、UTC 业务时间、整数毫秒、半开区间和 snake_case JSON 字段。
- Schema 版本 1.0；自定义 EDL、六态 Job、项目角色和不可变版本。
- ready 草案绑定基准修订与 payload_hash，确认时验证锁定、依赖和引用。

完整契约见 [系统详细设计](../../docs/design/detailed-design.md)，字段字典见 [数据库设计](../../docs/design/database-design.md)，角色信封见 [Agent 设计](../../docs/design/agent-design.md)。这些仍是设计，尚无可机器执行的 Schema。

## 首次实现时需要落实

- 稳定标识、字段命名、必填与可空语义。
- 源素材时间与目标时间轴的时基、区间边界和精度。
- 任务状态、错误结构、进度与重试约定。
- 用户确认、禁用、必留、锁定与并发版本规则。
- Schema 版本、兼容性和不同语言端的映射或生成方式。

建议以可机器校验的 Schema 为依据，API 请求响应通过 OpenAPI 维护。选择工具后记录生成命令，避免多端手工维护不一致的副本。

项目所称 EDL 为自定义剪辑决策 JSON；字段设计已有文档示例，尚未发布可执行 Schema，也不等同于外部编辑器交换标准。完整实体背景见 [需求分析第 7 节](../../docs/requirements.md)。

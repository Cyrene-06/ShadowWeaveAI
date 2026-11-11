# 共享数据契约

状态：契约设计目录，尚无正式 Schema、生成代码或可安装包。

这里维护 Web、Flutter、API、Worker、AI 与媒体层之间需要一致理解的数据结构。首批对象包括 Project、Intent、Asset、Segment、StoryNode、ReshootTask、Job、Timeline、Clip、ReviewIssue 和 Version。

## 首次实现前需要确定

- 稳定标识、字段命名、必填与可空语义。
- 源素材时间与目标时间轴的时基、区间边界和精度。
- 任务状态、错误结构、进度与重试约定。
- 用户确认、禁用、必留、锁定与并发版本规则。
- Schema 版本、兼容性和不同语言端的映射或生成方式。

建议以可机器校验的 Schema 为依据，API 请求响应通过 OpenAPI 维护。选择工具后记录生成命令，避免多端手工维护不一致的副本。

项目所称 EDL 为自定义剪辑决策 JSON；尚未发布字段规范，也不等同于外部编辑器交换标准。完整实体背景见 [需求分析第 7 节](../../docs/requirements.md)。

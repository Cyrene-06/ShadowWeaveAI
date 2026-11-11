# 第一阶段本机证据摘要

本机工件由 `python scripts/package_evidence.py` 从实际运行工件整理，`ci.json` 另由 GitHub Actions 只读 API 保存，运行顺序见[开发指南](../../development.md)。大纲描述实施安排，[阶段报告](../phase-1-report.md)解释结果和限制。

| 文件 | 作用 |
| --- | --- |
| [index.json](index.json) | 整理时间、实现提交、源码摘要、原始工件与本目录文件 SHA-256 |
| [replay.json](replay.json) | 原始固定输入、实际规则输出、18 项检查、代码/规则/数据版本 |
| [verification-summary.json](verification-summary.json) | 真实命令、退出码、耗时、JUnit 数量和浏览器结果摘要 |
| [media.json](media.json) | 原创真实媒体探测、解码/渲染结果、工具版本和二进制摘要 |
| [ci.json](ci.json) | GitHub Actions 只读 API 获取的实现提交、最终状态、core/flutter/android 三个 job 的结果及工件元数据（归档 digest 不是 APK 摘要） |
| [model-probe.json](model-probe.json) | 模型协议探针的实际配置/执行记录；not_configured 不代表已调用 |
| [environment.json](environment.json) | 工具版本、设备发现、真机阻塞与模型未配置记录 |

固定元数据与真实媒体是两条独立验证路径，均未调用模型。源码摘要是整理时状态；回放中的 commit/dirty 是回放运行时状态，二者分别保留。测试摘要不替代独立复现或正式阶段签署。

完整 stdout/stderr、JUnit、浏览器原始结果、媒体和截图保存在本机忽略目录 `artifacts/phase-one/`。这里不提交密钥、令牌、数据库、SDK、媒体或原始浏览器 trace。原始工件 hash 用于核对本机记录，单独持有 hash 不能恢复原始工件；其他成员需按开发指南重新运行并保存自己的真实结果。

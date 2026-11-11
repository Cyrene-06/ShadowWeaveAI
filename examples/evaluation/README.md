# 离线评测准备模板

本目录提供第一阶段的数据清单、独立标注、对照运行记录模板及 JSON Schema。均为未填写模板，不含真实采集、人工裁决或运行成绩。填写方法与证据限制见[数据准备与标注指南](../../docs/evaluation-data.md)，实验条件和指标以[评测协议](../../docs/evaluation.md)为准。

| 模板 | 配套 Schema | 用途 |
| --- | --- | --- |
| [dataset_manifest.template.json](dataset_manifest.template.json) | [dataset_manifest.schema.json](dataset_manifest.schema.json) | 来源、授权引用、事件/近重复/父链、开发与冻结划分 |
| [annotation.template.json](annotation.template.json) | [annotation.schema.json](annotation.schema.json) | 独立标注、四态覆盖、证据区间、修改影响与裁决 |
| [evaluation_run.template.json](evaluation_run.template.json) | [evaluation_run.schema.json](evaluation_run.schema.json) | A/B/C 与消融条件、版本、预算、实际耗时、失败与原始工件 |

从仓库根目录执行：

```powershell
python scripts/prepare_evaluation.py --check
python scripts/validate_evaluation.py examples/evaluation/dataset_manifest.template.json examples/evaluation/annotation.template.json examples/evaluation/evaluation_run.template.json
```

复制模板到受控工作目录后填写；完整记录设置 record_stage=ready，以 `--ready` 校验。注释和运行记录还需 `--manifest` 指向已填写、通过 ready 检查的清单。空白模板不能通过 ready 门，CLI 输出只证明结构和声明的一致性，不证明实际执行、授权真实性或人工独立性。

这些离线记录独立于 21 个业务契约，不进入双端业务对象导出。Schema 由 `packages/contracts/src/sw_contracts/evaluation.py` 生成；变更后重新生成，禁止手工修改生成文件。

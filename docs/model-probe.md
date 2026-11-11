# 第一阶段模型协议探针

本工具对应大纲 T10 的模型可达性、结构化返回和用量记录准备。当前没有提供商配置，尚未调用真实模型。本地 HTTP 测试只验证适配器；不验证真实服务可达性、真实 token、费用或模型效果。

## 1. 支持范围

入口为 `scripts/model_probe.py`。本阶段提供一个 Chat Completions 协议适配器，使用 JSON Schema 结构化返回；MODEL_PROVIDER 填 openai 或 openai_compatible。只支持这个接口的提供商仍可能不支持 strict JSON Schema、max_completion_tokens 或 store 参数，须以真实服务文档和实际失败记录为准；脚本不会自动降级或切换模型。

协议参考：[官方 Chat Completions 接口](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。适配器沿用现有可替换模型边界，不替代后续生产模型服务或七角色编排。

请求使用固定合成元数据：probe-evidence 尚未完成检索，应返回 `evidence_ref=probe-evidence`、`decision=uncertain`。实际响应经本地严格 Schema 再校验。它只检查协议和这一固定回答，不是四态覆盖准确率、故事质量或真实素材理解实验。

## 2. 配置与执行

凭据通过进程环境传入，不写入仓库。设置 MODEL_PROVIDER、MODEL_BASE_URL、MODEL_NAME、MODEL_API_KEY；不要把密钥复制到 issue、日志或公开报告。API 根地址通常包含 /v1，不包含 /chat/completions；拒绝 URL 用户名、密码、query、fragment。非回环地址要求 HTTPS，回环 HTTP 专供本地测试。

默认命令只记录配置就绪状态，不发送请求，统一检查与 CI 使用这一方式：

```powershell
python scripts/model_probe.py
```

配置未齐时输出 not_configured；齐全但未执行时输出 not_run。主动执行时运行：

```powershell
python scripts/model_probe.py --execute --timeout 30 --max-output-tokens 256
```

这会向所配置提供商发送一次可能产生费用的请求；不自动重试，也不跟随重定向。max-output-tokens 范围为 16—4096，默认 256；timeout 范围为大于 0、至多 60 秒，作用于网络操作，不能证明提供商在本地超时后已取消生成或停止计费。模型本身不支持请求参数或输出预算不足时保留失败，不修改成更容易通过的请求。

输出默认保存在 `artifacts/phase-one/model-probe.json`。默认检查未配置时退出码为 0，但记录明确为未验证；显式执行失败、超时或缺配置时退出码为 1。绿色 CI 只说明本地检查通过，不代表真实模型探针成功。

## 3. 用量与费用口径

记录只接收非负整数的 prompt_tokens、completion_tokens、total_tokens，并要求总数相等。缺失、不一致或类型错误时 usage=null，不填零冒充实测。即使响应被拒绝、截断或不满足 Schema，也尽量保留已经返回的用量，不能只保留成功调用。

实际账单费用 cost 始终为 null，脚本没有账单接口。若另有经过审核、与本次模型和计价档位匹配的平价输入/输出费率，可在受控目录准备 JSON 文件：

```json
{
  "input_per_million": "0",
  "output_per_million": "0",
  "currency": "USD",
  "reference": "TEMPLATE_ONLY: replace both zero placeholders with reviewed provider rates and source/date"
}
```

以上是文件格式示例，零是待替换占位，不是任何提供商的价格或免费承诺。随后执行：

```powershell
python scripts/model_probe.py --execute --pricing artifacts/private-pricing.json
```

cost_estimate 按提供商返回的 token × 操作者给定费率计算，并保留费率及来源。没有费率或有效用量则为 null。这个估算不处理缓存折扣、批量/区域/长上下文档位、工具费、税或其他计费规则，不作为实际账单；适用条件不满足时不要提供平价费率文件。回环测试不生成提供商费用估算。

## 4. 结果解释与证据边界

| 字段/状态 | 含义 |
| --- | --- |
| request_attempted=false | 尚未发送请求，不能证明服务不可达或可达 |
| model_called=true | 非回环目标返回可识别 completion 消息；不代表本地 Schema 校验成功 |
| model_called=null | 已尝试请求，但无法确认是否执行推理，例如网络超时或部分服务端失败 |
| endpoint_kind=loopback_test | 本地协议夹具；model_called 保持 false，用量标为 loopback_fixture |
| succeeded | completion 正常停止、未拒绝，且内容通过固定 ProbeReply 校验 |
| failed / timed_out | 保存失败类别和 HTTP 状态（若存在）；不输出提供商原始错误正文 |

记录包括请求/响应字节摘要、提示版本、代码提交、脚本 hash、时长及输出上限；模型名称仅来自操作者配置。不会保存 API 密钥、Authorization、完整 URL、原始响应正文或原始提示。脚本不上传媒体、不写业务状态，也不确认或发布剪辑版本。

测试通过回环 HTTP 服务覆盖请求、鉴权头、结构化内容、拒绝、截断、错误用量、HTTP 401/429/500、重定向和超大响应；超时用受控传输异常验证。测试模型名、token 和费率都是夹具，不能并入正式模型试验记录或评测分母。

获得真实配置后，应执行实际探针，复核提供商返回和用量，记录缺测，再按[评测协议](evaluation.md)准备效果实验。当前正式依赖仍为项目负责人的提供商账号、获准使用的模型和实际调用记录；脚本准备完成不关闭该待办。

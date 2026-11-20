# 自动化入口

从仓库根目录、已安装 Python 开发依赖的环境执行：

| 入口 | 用途 | 输出 |
| --- | --- | --- |
| `python scripts/build_fixtures.py` | 生成项目自编固定输入 | `examples/phase-1/campus.json` |
| `python scripts/export_contracts.py [--check]` | 生成/检查 Schema、共享用例、OpenAPI、Flutter 资源 | 对应受版本控制的 JSON |
| `python scripts/prepare_evaluation.py [--check]` | 生成/检查离线评测 Schema 与空白模板 | `examples/evaluation/` |
| `python scripts/validate_evaluation.py RECORD... [--manifest PATH] [--ready]` | 检查记录结构、来源引用和分组一致性 | stdout；不证明实际执行或人工评审 |
| `python -m sw_api.replay` | 实际执行两组样例规则 | `artifacts/phase-one/replay.json` |
| `python scripts/media_probe.py` | 原创媒体生成、真实解码与最小渲染 | `artifacts/phase-one/media/` |
| `python scripts/model_probe.py [--execute] [--pricing PATH]` | 默认记录模型配置；显式执行一次结构化协议探针 | `artifacts/phase-one/model-probe.json`，见[口径说明](../docs/model-probe.md) |
| `python scripts/environment_probe.py` | 工具、设备与模型配置可用性记录 | `artifacts/phase-one/environment.json` |
| `python scripts/package_evidence.py` | 整理白名单证据与原始工件摘要；缺失记录会失败 | `docs/reports/evidence/` |
| `python scripts/verify_phase_two.py --model PATH --output PATH [--download]` | 复跑真实实拍档案、检索对照、失败及 Worker 进程重启；开发锚点不计独立人工验收 | 新的脱敏运行记录，见[开发指南](../docs/development.md#7-第二阶段素材证据链) |
| `python scripts/phase_two_timing.py REPLAY --case PATH --output PATH` | 使用同一批哈希核对的代理生成互换分组、独立参与者页面和观察员表 | `artifacts/` 内计时包；浏览器记录不裁决正确性、不签署 G4 |
| `python scripts/phase_two_handoff.py MANIFEST... --output PATH [--search-complete]` | 合并同项目的 NASA 实拍素材 Web 复核清单，运行第一阶段覆盖规则；默认不视为检索已完成 | 本地覆盖回执，不签署 G4；见[独立验收表](../docs/reports/phase-2-acceptance.md#2-回看事实并交接) |
| `python scripts/verify.py [--flutter]` | 检查 Python/Web 并保存真实命令结果 | `artifacts/phase-one/verification.json` |

`environment_probe.py` 不输出凭据，也不发起计费模型调用。缺少设备/模型配置时写 blocked/not_configured，不伪造成功。可用 `FLUTTER_PATH` 指定 Flutter 可执行文件。Flutter 分析/测试/构建的具体命令见[开发指南](../docs/development.md)。

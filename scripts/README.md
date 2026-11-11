# 自动化入口

从仓库根目录、已安装 Python 开发依赖的环境执行：

| 入口 | 用途 | 输出 |
| --- | --- | --- |
| `python scripts/build_fixtures.py` | 生成项目自编固定输入 | `examples/phase-1/campus.json` |
| `python scripts/export_contracts.py [--check]` | 生成/检查 Schema、共享用例、OpenAPI、Flutter 资源 | 对应受版本控制的 JSON |
| `python -m sw_api.replay` | 实际执行两组样例规则 | `artifacts/phase-one/replay.json` |
| `python scripts/media_probe.py` | 原创媒体生成、真实解码与最小渲染 | `artifacts/phase-one/media/` |
| `python scripts/environment_probe.py` | 工具、设备与模型配置可用性记录 | `artifacts/phase-one/environment.json` |
| `python scripts/package_evidence.py` | 整理白名单证据与原始工件摘要；缺失记录会失败 | `docs/reports/evidence/` |
| `python scripts/verify.py [--flutter]` | 检查 Python/Web 并保存真实命令结果 | `artifacts/phase-one/verification.json` |

`environment_probe.py` 不输出凭据，也不发起计费模型调用。缺少设备/模型配置时写 blocked/not_configured，不伪造成功。可用 `FLUTTER_PATH` 指定 Flutter 可执行文件。Flutter 分析/测试/构建的具体命令见[开发指南](../docs/development.md)。

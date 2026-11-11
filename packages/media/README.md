# 时间轴约束与真实媒体探针

`src/sw_media/policy.py` 实现 EDL 规范化、稳定键/轨道比较、依赖 DAG 检查、影响传播、候选完整 diff、锁定/范围校验和草案摘要确认。批准范围在读取候选前建立；改字段、删除、换键、移轨和改依赖都会参与比较。

`confirm_contract` 只检查已审阅草案，不创建生产 Version。正式确认事务、并发头更新和完整重规划求解器继续按后续阶段实施。

`src/sw_media/tools.py` 调用真实 ffprobe/FFmpeg，使用参数数组、受限协议/格式、超时及受控错误。工具从 `FFMPEG_PATH / FFPROBE_PATH`、PATH 或本地缓存发现。开发探针允许最多 16 MiB 的文件；进程尚无生产资源隔离，应在受控本地环境使用。

```powershell
.venv/Scripts/python.exe scripts/media_probe.py
```

脚本生成原创色块/正弦测试片，真实解码并渲染约半秒预览，记录工具版本、探测结果及文件摘要；不包含第三方素材或模型结果。

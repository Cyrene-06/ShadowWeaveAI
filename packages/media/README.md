# 时间轴约束与真实媒体探针

`src/sw_media/policy.py` 实现 EDL 规范化、稳定键/轨道比较、依赖 DAG 检查、影响传播、候选完整 diff、锁定/范围校验和草案摘要确认。批准范围在读取候选前建立；改字段、删除、换键、移轨和改依赖都会参与比较。

`confirm_contract` 只检查已审阅草案，不创建生产 Version。正式确认事务、并发头更新和完整重规划求解器继续按后续阶段实施。

`src/sw_media/tools.py` 调用真实 ffprobe/FFmpeg，使用参数数组、受限协议/格式、超时及受控错误。工具从 `FFMPEG_PATH / FFPROBE_PATH`、PATH 或本地缓存发现。开发探针允许最多 16 MiB 的文件；进程尚无生产资源隔离，应在受控本地环境使用。

```powershell
.venv/Scripts/python.exe scripts/media_probe.py
```

脚本生成原创色块/正弦测试片，真实解码并渲染约半秒预览，记录工具版本、探测结果及文件摘要；不包含第三方素材或模型结果。

## 第二阶段真实素材分析

`src/sw_media/analysis.py` 处理单视频：最多 64 MiB、180 秒、最长边 3840 且最多 8,294,400 像素。受限协议和格式、FFmpeg 子进程超时；代理最长 75 秒、ASR 推理最长 180 秒，这些是单操作预算，不是整任务 SLA。

- 采样扫描场景变化，间隔过长时定长回退；输出 `scene / scene_and_fixed / fixed_or_single`。这不是经过精确性评测的镜头识别器。
- 片段是原片相对毫秒半开区间 `[in_ms,out_ms)`。代理不剪掉时间；代表帧和分辨率、亮度采样是提示，不自动判断成片质量。
- 有轨素材经 FFmpeg 转为带前导时间补偿的 16 kHz 单声道 PCM，再由 `local_speech.py` 读取本地模型产生词时间戳；以词中点唯一分配给片段。模型、依赖版本、快照文件摘要和音频时长可查；无音轨为 `not_applicable`。安装和复跑见[开发指南](../../docs/development.md#7-第二阶段素材证据链)。

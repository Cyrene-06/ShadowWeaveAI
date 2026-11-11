# 第一阶段验证

```powershell
.venv/Scripts/python.exe -m pytest -q
```

默认运行契约、覆盖、补拍门、依赖/锁定/范围/摘要、API 授权和幂等、回放、任务状态以及真实媒体测试。FFmpeg 和 ffprobe 必须可发现；缺失工具时真实媒体用例会失败，不能据此标为通过。

真实 PostgreSQL 测试需显式配置：

```powershell
$env:TEST_DATABASE_URL='postgresql+psycopg://shadowweave:phase_one_local_only@127.0.0.1:55432/shadowweave'
.venv/Scripts/python.exe -m pytest -q --junitxml=artifacts/phase-one/python-tests.xml
```

测试在随机命名 `sw_test_<uuid>` schema 内运行并清理该 schema，不删除 public 下的业务数据。验证升级/回退/元数据一致性、同项目外键、4 路并发幂等/导入以及失败事务回滚。未配置 TEST_DATABASE_URL 时这 4 项会明确跳过。

Web/Flutter 共用同一组 42 个有效和无效契约用例。浏览器测试真实连接双端和 API，复现方法见 [Web 说明](../apps/web/README.md)。实际结果和适用边界见[阶段报告](../docs/reports/phase-1-report.md)。

`test_evaluation_records.py` 检查离线准备记录的 ready 门、事件/字节/近重复/原片家族跨集合泄漏、授权声明、标注引用区间和覆盖一致性，以及失败、无模型调用和计时记录。测试夹具为单元测试声明，不属于实拍数据集或人工标注成绩。

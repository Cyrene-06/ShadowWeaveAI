# 共享契约

单一字段来源为 `src/sw_contracts/models.py`，使用 Pydantic 生成 JSON Schema。引用、权限、覆盖、依赖和锁定等业务规则由对应规则层执行，Schema 不代替业务校验。

```powershell
.venv/Scripts/python.exe scripts/export_contracts.py
.venv/Scripts/python.exe scripts/export_contracts.py --check
```

生成工件包括 `schema/catalog.json`、`examples/cases.json`、Flutter 的 `assets/contracts.json` 和 `docs/api/openapi.json`。当前包含 21 个公开契约对象及 42 个跨语言共用用例，覆盖有效对象、缺失必填、可空、UUID、类型、整数毫秒及语义约束。Web 使用 AJV 2020；Dart 解释生成 Schema 所需的受限子集，并补充相同的语义校验。

Python/TypeScript/Dart 都读取同一用例文件，比较解析后的规范化结果，而非只比较“没有抛错”。新增 Schema 关键字时同步 Dart 解释器及共享用例。字段变更须更新三份设计并重新导出；`--check` 用于发现生成工件过期。

契约 `schema_version=1.0` 是第一阶段固定输入格式，不代表完整产品发布版本。正式版本发布、异步恢复和模型质量另行验收。

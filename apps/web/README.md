# Web 项目工作台

Vue 3 + TypeScript + Pinia + Vite。具备真实账号/项目 API、五场景项目选择、固定输入规则回放、证据/补拍状态、编辑差异/拒绝依据和真实媒体上传探针。界面标明人工输入及未调用模型。

```powershell
cd apps/web
npm ci
npm run dev
```

默认端口 5173，Vite 将 `/api` 代理到 `127.0.0.1:8000`。生产静态部署需要反向代理配置；当前并未提供生产部署。

```powershell
npm test
npm run build
npm run test:e2e
```

前两项分别运行 42 个共享契约用例、类型检查和构建。E2E 需要 API、Web、Flutter Web（8080）已经运行，并先执行根目录 `scripts/media_probe.py`。默认使用已安装的 Edge；可用 `PLAYWRIGHT_CHANNEL=chromium` 配合 `npx playwright install chromium` 切换。结果、截图和失败 trace 进入根目录 `artifacts/phase-one/browser/`。Trace 可能包含测试账号的令牌，留在忽略目录。

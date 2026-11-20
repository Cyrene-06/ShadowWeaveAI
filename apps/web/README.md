# Web 项目工作台

Vue 3 + TypeScript + Pinia + Vite。具备真实账号/项目 API、五场景项目选择、固定输入规则回放、证据/补拍状态、编辑差异/拒绝依据和真实媒体上传探针。第二阶段另有独立素材工作区：授权上传、Worker 分析状态、按词检索、回看和人工复核导出。规则回放和本地转写的来源分别在界面标明。

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

前两项分别运行 49 个共享契约用例、类型检查和构建。第一阶段 E2E 需要启用规则回放的 API、Web 和 Flutter Web（8080），媒体工具配置见[开发指南](../../docs/development.md)。第二阶段真实语音用例还需本地 ASR Worker 和注册素材，通过 `PHASE_TWO_WEB_URL`、`PHASE_TWO_SPOKEN_VIDEO` 启用，缺任一变量时测试会跳过。详见[浏览器复跑](../../docs/development.md#独立-apiworker-复跑和浏览器复跑)。默认使用已安装的 Edge；可用 `PLAYWRIGHT_CHANNEL=chromium` 配合 `npx playwright install chromium` 切换。结果、截图和失败 trace 进入根目录 `artifacts/phase-one/browser/`。Trace 可能包含测试账号的令牌，留在忽略目录。

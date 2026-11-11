# 开发与复现指南

第一阶段已有可运行的双端/API 与规则内核。本文命令以仓库根目录的 Windows PowerShell 为例；跨系统请激活 Python 虚拟环境并使用对应可执行路径。实际验证版本和未验证项见[阶段报告](reports/phase-1-report.md)。API 不自动加载 `.env`，配置通过进程环境传入。

## 1. 安装工具和依赖

本次验证使用 Python 3.12.7、Node 24.14.0、Flutter 3.47.9 / Dart 3.13.7、PostgreSQL 17。Python 支持范围由 `pyproject.toml` 限定为 3.12，JS/Dart 依赖由各端锁文件固定。先安装对应工具，并让 ffprobe/FFmpeg 可发现。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.lock.txt
.venv/Scripts/python.exe -m pip install --no-deps -e .
npm ci --prefix apps/web
```

Windows 若没有 ffprobe，可用以下命令安装本地探针工具，缓存目录已忽略：

```powershell
npm install --prefix .cache/media @ffprobe-installer/ffprobe
```

FFmpeg 可由已安装的 `imageio-ffmpeg` 提供。也可将系统工具放入 PATH，或显式设置 `FFMPEG_PATH` / `FFPROBE_PATH` 为可执行文件路径；不要包含额外命令参数。Linux 可安装系统 ffmpeg 软件包，同时获得 ffprobe。

Flutter SDK 自行安装到英文路径；本次为 `.cache/flutter` 下的官方 stable SDK。新终端运行前确认 `flutter --version` 与 `apps/mobile/pubspec.lock` 匹配。

## 2. 数据迁移与 API

默认 SQLite 无须容器。先在仓库根目录执行迁移：

```powershell
$env:ENABLE_PHASE_ONE_REPLAY='true'
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn sw_api.app:app --host 127.0.0.1 --port 8000
```

保持 API 终端运行。健康入口 `/api/v1/health`；交互接口 `/docs`。开发 JWT 密钥和数据库进入 `artifacts/`，不提交。`ENABLE_PHASE_ONE_REPLAY` 默认关闭，启用后才出现固定样例路由；生产环境禁止启用。生产设置还要求独立 JWT_SECRET，但这并不构成完整生产部署方案。

需要 PostgreSQL 时，先按[基础设施说明](../infra/README.md)启动数据库，在迁移和 API 启动前设置同一个 `DATABASE_URL`。第一次使用新库只运行 upgrade；升级回退测试在独立测试 schema 内执行，不在业务库上演示删除表。

## 3. 启动 Web

新终端从仓库根目录执行：

```powershell
npm --prefix apps/web run dev
```

浏览器访问本机 5173 端口。创建账号，创建项目，点击“运行固定样例”；可查看四态覆盖、补拍验证和完整编辑 diff。固定样例数据是人工合成元数据，页面会标明未调用模型。

## 4. 构建和运行 Flutter Web

```powershell
cd apps/mobile
flutter pub get
flutter analyze
flutter test
flutter build web --release --dart-define=API_BASE_URL=http://127.0.0.1:8000/api/v1
python -m http.server 8080 --bind 127.0.0.1 --directory build/web
```

浏览器访问本机 8080 端口，用 Web 创建的同一账号登录并选择同一项目。默认 CORS 包含 5173/8080 的 localhost 和 127.0.0.1。Flutter Web 渲染器和中文字体首次加载可能访问其默认字体/CDN 资源；离线交付需另做资源自包含验证。

本次 Windows 中文路径引发 Flutter shader 编译和 LSP 编码错误，使用未占用盘符 `subst W: E:\软创\ShadowWeaveAI` 后，在 `W:\apps\mobile` 调用 `W:\.cache\flutter\bin\flutter.bat` 成功。盘符只作本机工具兼容处理，不写入工程配置；用户路径不同需自行替换。勿覆盖现有盘符映射。

Android 原生工程新增独立 CI debug APK 构建入口，实际结果见阶段报告；本机缺 Android SDK，真机仍需设备和可达的 API 地址。设备上的 127.0.0.1 是设备自身，不能直接使用本机回环地址。开发明文访问限 debug/profile，正式版本使用 HTTPS。当前没有真机采集通过证据。安装和 USB 反向端口步骤见[Android 探针指南](android-probe.md)。

## 5. 统一检查与浏览器联调

```powershell
# 可选；配置后额外执行真实 PostgreSQL 测试，否则这 4 项明确跳过。
$env:TEST_DATABASE_URL='postgresql+psycopg://shadowweave:phase_one_local_only@127.0.0.1:55432/shadowweave'
.venv/Scripts/python.exe scripts/verify.py
# Flutter 在 PATH 或 FLUTTER_PATH 可用时，同时检查 Flutter。
.venv/Scripts/python.exe scripts/verify.py --flutter
.venv/Scripts/python.exe scripts/environment_probe.py
```

本次映射环境使用 `$env:FLUTTER_PATH='W:\.cache\flutter\bin\flutter.bat'` 和 `$env:FLUTTER_WORKDIR='W:\apps\mobile'` 再运行 `--flutter`。检查脚本保存真实输出和退出码，不安装依赖或自动启动服务。

API、Web、Flutter Web 保持运行，媒体探针已生成后执行：

```powershell
npm --prefix apps/web run test:e2e
```

默认使用 Edge。无 Edge 时可在 `apps/web` 安装 Playwright Chromium 并设置 `PLAYWRIGHT_CHANNEL=chromium`。浏览器测试真实注册、创建项目、规则回放、视频上传，并在 Flutter Web 登录同一账号和读取同一项目。Flutter 使用无障碍语义定位，并通过真实键盘输入触发文本控制器。

CI 定义在 `.github/workflows/phase-one.yml`，覆盖核心检查、PostgreSQL 与 Flutter；实际通过记录见阶段报告。本机检查与远端 CI 以各自的执行记录和提交号为准。

## 6. 数据与变更约定

修改契约后运行 `scripts/export_contracts.py` 并提交生成文件；CI 用 `--check` 防止过期。数据库首迁移带冻结元数据快照，后续变更新增迁移，不通过导入当前 metadata 偷改旧迁移。

`artifacts/`、设备 SDK、媒体、凭据、数据库和浏览器 trace 均不提交。可审阅的小型证据摘要进入 `docs/reports/evidence/`，保留实际来源和局限。固定输入不能代替真实模型/素材评测。需求原件 `docs/requirements.md` 保持不变；设计范围仍保留七模块、七角色、双端和五场景。

## 评测数据准备与独立交接

按[数据准备与标注指南](evaluation-data.md)复制并填写[离线模板](../examples/evaluation/README.md)。`python scripts/prepare_evaluation.py --check` 已进入统一检查；实际数据、独立标注与运行记录使用 `scripts/validate_evaluation.py` 的 `--ready` 和 `--manifest` 校验。模板通过不表示完成采集或实验。复现者使用指南中的空白交接表记录真实结果；另一成员尚未独立签署时保持待复核。

## 模型协议探针

`scripts/model_probe.py` 默认仅记录配置状态，统一检查也只执行此模式。获得提供商配置后按[模型探针说明](model-probe.md)使用 `--execute` 显式请求一次并保存实际返回；不自动重试，不把回环测试当作模型效果。费用若有费率文件仅记录估算，实际账单字段保持缺测。

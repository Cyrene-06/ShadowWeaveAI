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

浏览器访问本机 5173 端口。创建账号，创建项目，点击“运行固定样例”；可查看四态覆盖、补拍验证和完整编辑 diff。固定样例数据是人工合成元数据，页面会标明未调用模型。工作台支持桌面侧栏与窄屏布局，覆盖卡片可展开逐需求证据，编辑检查可展开依赖传播路径。

只复核 Web 界面（不启动 Flutter）：保持 API 与 Web 服务运行，在仓库根目录生成媒体夹具，再从 Web 目录运行浏览器测试。浏览器默认使用 Microsoft Edge，可通过 `PLAYWRIGHT_CHANNEL` 指定其他已安装通道。

```powershell
.venv/Scripts/python.exe scripts/media_probe.py
Set-Location apps/web
npm run test:e2e -- workspace-ui.spec.ts --reporter=list --output=../../artifacts/phase-one/browser/web-ui/test-results
```

该检查覆盖桌面和窄屏的注册、创建项目、规则回放、证据展开及编辑风险阅读，桌面用例还会上传媒体夹具。预览截图保存在 `artifacts/phase-one/browser/web-ui/`，不纳入版本控制。

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

Android 原生工程的独立 CI debug APK 构建及工件上传已通过，实际结果见阶段报告；本机缺 Android SDK，真机仍需设备和可达的 API 地址。设备上的 127.0.0.1 是设备自身，不能直接使用本机回环地址。开发明文访问限 debug/profile，正式版本使用 HTTPS。当前没有真机采集通过证据。安装和 USB 反向端口步骤见[Android 探针指南](android-probe.md)。

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

## 7. 第二阶段素材证据链

第二阶段只在 Web 核对素材。API 负责登记、检索、授权和导出；后台 Worker 负责实际分析。两者必须使用相同 `DATABASE_URL`，并以同一绝对路径配置 `ARTIFACT_DIR`。示例以下使用仅监听回环地址的开发环境。

```powershell
# 已执行 §1 的基础安装。没有音轨的视频不需要模型，也可跳过本段。
.venv/Scripts/python.exe -m pip install -e ".[media-asr]"
$Model = (.venv/Scripts/python.exe -c "from huggingface_hub import snapshot_download; print(snapshot_download('Systran/faster-whisper-tiny.en', revision='0d3d19a32d3338f10357c0889762bd8d64bbdeba', cache_dir='.cache/huggingface/hub', allow_patterns=['model.bin','config.json','tokenizer.json','vocabulary.txt']))").Trim()
$env:SW_MEDIA_ASR_MODEL = (Resolve-Path $Model).Path
$env:SW_MEDIA_ASR_LANGUAGE = 'en' # 此开发样例是英语；其他语言需相应模型
```

模型下载需网络，下载完成后 Worker 只读本地快照，不向模型服务上传音视频。若无网络，可从已下载快照设置绝对路径。转写缺配置会得到 `TRANSCRIPTION_NOT_CONFIGURED`；修正配置并重启 Worker 后，在 Web 对该资产发起重新分析。

```powershell
# API 和 Worker 的两个终端都执行以下环境设置
$env:DATABASE_URL = 'sqlite:///artifacts/phase-two.sqlite3'
$env:ARTIFACT_DIR = Join-Path (Get-Location) 'artifacts/phase-two'

# API 终端；ENABLE_PHASE_ONE_REPLAY=true 仅用于开发回归
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn sw_api.app:app --host 127.0.0.1 --port 8000

# Worker 终端确保同时设置了上面的 SW_MEDIA_ASR_* 后执行
.venv/Scripts/python.exe -m sw_worker.media_jobs
```

第三个终端执行 `npm --prefix apps/web run dev`，打开本机 5173，注册并创建项目，在“素材证据工作区”上传视频、检索、回看和人工复核后导出。接口与错误见 [API 目录](api/README.md)，本地 Worker 的数据生命周期见[运行约定](../services/worker/README.md)。

### 独立 API/Worker 复跑和浏览器复跑

```powershell
.venv/Scripts/python.exe scripts/verify_phase_two.py --download --model $env:SW_MEDIA_ASR_MODEL --output artifacts/phase-two-repro/evidence.json
```

脚本使用一次性 SQLite 目录，走同一套 API、迁移和 Worker 逻辑，不依赖已启动的服务。`--download` 只补齐素材登记中缺失的 NASA 文件并对照 SHA-256；可以预放文件后省略。报告会绑定 Git 版本、工作树状态和实测工具。它测试提交“人工复核”表单的协议，不替代真人判断。

在真实 API、Worker、Web 均运行后，从仓库根目录设置浏览器用例输入：

```powershell
$env:PHASE_TWO_WEB_URL = 'http://127.0.0.1:5173'
$env:PHASE_TWO_SPOKEN_VIDEO = (Resolve-Path 'artifacts/phase-two-input/one-small-step.m4v').Path
Push-Location apps/web
npm run test:e2e -- material-workspace.spec.ts --reporter=list --output=../../artifacts/phase-two-browser/test-results
Pop-Location
```

少任一变量时用例会跳过，不计通过。交给独立成员时记录实际提交号、数据哈希、工具和模型快照、运行输出，以及[人工计时与签署表](reports/phase-2-acceptance.md)。

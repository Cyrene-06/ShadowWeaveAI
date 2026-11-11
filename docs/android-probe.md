# Android 原生构建与真机采集探针

本入口对应第一阶段 T08/T10。相机按钮和视频上传已实现；APK 编译、设备安装、相机采集和上传分别验收。Flutter Web、单元测试和 CI 编译不能证明真机相机成功。

## 1. 当前证据与构建入口

2026-11-11 本机 `flutter doctor -v` 未找到 Android SDK；在移动端工程目录执行 `flutter build apk --debug --no-pub`，以退出码 1 返回 `No Android SDK found`。设备探测未发现 Android/iOS 真机。原始构建记录保存在忽略目录 `artifacts/phase-one/`。

工作流 `.github/workflows/phase-one.yml` 新增独立 `android` 任务：使用 Flutter 3.47.9、Temurin JDK 17 和运行器的 Android SDK，执行依赖解析、debug APK 编译、SHA-256 记录及工件上传。实现提交 `30cfe4d` 的该任务已通过，实际步骤及工件元数据见[CI 记录](reports/evidence/ci.json)。构建成功时工件名为 `phase-one-android-debug`，保存 14 天，内含 APK 与校验文件；二进制不进入 Git。

该调试包的 API 地址为 `http://127.0.0.1:8000/api/v1`，用于下述 USB 反向端口连接。包使用调试签名，仅供本阶段验证；正式发布另行配置签名和 HTTPS。

具备 SDK 的环境可自行构建：

```powershell
cd apps/mobile
flutter pub get
flutter build apk --debug --dart-define=API_BASE_URL=http://127.0.0.1:8000/api/v1
Get-FileHash build/app/outputs/flutter-apk/app-debug.apk -Algorithm SHA256
```

本机中文目录的 Flutter 调用沿用[开发指南](development.md)中的 W: 映射；不要覆盖已有盘符。编译失败应记录命令、退出码和原始错误。

## 2. USB 连接与安装

先按开发指南启动 API 和 Web，显式开启第一阶段固定样例入口。API 监听本机 8000 端口。使用本人授权的 Android 设备，打开开发者选项和 USB 调试，解锁并确认该电脑的调试授权。

以下命令从仓库根目录执行：

```powershell
adb devices -l
# 把 DEVICE_SERIAL 替换为状态是 device 的真实序列号。
adb -s DEVICE_SERIAL reverse tcp:8000 tcp:8000
adb -s DEVICE_SERIAL install -r apps/mobile/build/app/outputs/flutter-apk/app-debug.apk
adb -s DEVICE_SERIAL shell am start -n ai.shadowweave.shadowweave_mobile/.MainActivity
```

从 CI 下载时将 APK 保存到自己的受控目录，并调整安装路径；先比对下载文件的 SHA-256。多设备场景始终指定序列号。unauthorized、offline 或没有设备时停止设备步骤，保留实际状态。USB 反向映射把设备 8000 端口连接到开发机 API；未建立映射时，设备的回环地址不能访问开发机。

## 3. 真机操作与检查

1. Web 注册测试账号并创建项目。在 Android 使用同一账号登录，核对相同项目；运行固定样例，检查页面注明人工固定输入和未调用模型。
2. 点击“拍摄 8 秒视频并上传探针”。拍摄有使用权限、不含敏感个人信息的短场景；返回 App 后检查上传结果。探针限制为 16 MiB，设备编码产生较大文件时缩短视频后重试。
3. 保存 API 返回的媒体探测摘要、文件大小和自行测量的请求耗时；核对结果中的 `capture_fulfilled=false`。当前探针检查媒体后删除临时上传文件，不创建持久化 Asset，不渲染或分析其故事语义；成功不应把真实上传伪装成固定样例的补拍验证完成。
4. 取消拍摄，确认可以返回并继续操作；设备或相机拒绝访问时记录实际提示。正常上传和失败分支分别记录。
5. 核对固定回放仍分别显示 submitted 与新人工证据验证后的 fulfilled。这是规则样例，不表示真机视频已经被模型理解。
6. Android 相机返回时若系统回收 App，记录恢复提示和重试结果；当前实现提示重新登录/选择项目后重选视频，不声称自动恢复未完成上传。

调试结束可执行 `adb -s DEVICE_SERIAL reverse --remove tcp:8000`。相机素材、账号令牌、设备序列号和原始日志保存在受控位置，公共报告保留脱敏引用和摘要。

## 4. 结果交接

每个子项分别记录 passed、failed、blocked 或 not_run，保留失败。至少填写：实际操作者/复核者、日期、40 位源码提交、APK SHA-256、Flutter/JDK/SDK 版本、设备型号与 Android 版本、网络方式、命令/退出码、采集与上传结果、取消/拒绝及恢复分支、媒体摘要引用和待修问题。

正式复现另填写[独立交接表](evaluation-data.md#5-独立复现交接表)。本文件提供操作入口，不代填真实设备或人工结果；当前阶段状态见[阶段报告](reports/phase-1-report.md)。

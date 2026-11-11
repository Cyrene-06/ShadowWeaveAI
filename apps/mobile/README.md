# Flutter 项目与补拍端

已生成 Android/Web 工程，包含真实 API 登录/项目读取、补拍卡状态、规则回放和视频选择上传探针。原生 Android/iOS 平台显示相机按钮，当前仅生成 Android 平台工程；iOS 需在后续具备 macOS 环境时初始化并验证。没有真机采集通过记录。

```powershell
cd apps/mobile
flutter pub get
flutter analyze
flutter test
flutter build web --release --dart-define=API_BASE_URL=http://127.0.0.1:8000/api/v1
python -m http.server 8080 --bind 127.0.0.1 --directory build/web
```

已验证 Flutter 3.47.9 / Dart 3.13.7，44 项测试（42 契约 + 2 界面/API 状态测试）通过，Flutter Web 通过真实双端联调。API 地址由编译参数指定；真机不能使用宿主机的 `127.0.0.1`，需使用其可达地址并核对开发 CORS/网络环境。Android 开发明文访问只在 debug/profile 配置中允许，正式构建使用 HTTPS。

Windows 本次环境的中文路径触发了 Flutter 工具的 shader/LSP 错误，使用空闲盘符 `subst W: E:\软创\ShadowWeaveAI` 映射后成功；在 `W:\apps\mobile` 调用 `W:\.cache\flutter\bin\flutter.bat`。其他环境优先选择英文路径，不要覆盖已占用盘符。

Web 与原生 Android 分别验证；实现提交 `30cfe4d` 的 CI debug APK 编译及工件上传已通过，相机能力仍待真机验证。设备、SDK 和模型未验证项见[阶段报告](../../docs/reports/phase-1-report.md)。

原生 Android 独立 CI debug APK 构建已通过，并上传 APK 和 SHA-256 工件；构建与真机状态分开记录。USB 连接、安装、相机采集与上传检查见[Android 探针指南](../../docs/android-probe.md)。

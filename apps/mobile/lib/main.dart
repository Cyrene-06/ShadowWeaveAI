import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';

import 'api.dart';
import 'contracts.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final catalog = ContractCatalog(
    jsonDecode(await rootBundle.loadString('assets/contracts.json')),
  );
  runApp(PhaseOneApp(api: ShadowApi(catalog: catalog)));
}

class PhaseOneApp extends StatelessWidget {
  final ShadowApi api;
  const PhaseOneApp({super.key, required this.api});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: '影织 AI · 第一阶段',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff256550)),
      useMaterial3: true,
    ),
    home: Workspace(api: api),
  );
}

class Workspace extends StatefulWidget {
  final ShadowApi api;
  const Workspace({super.key, required this.api});
  @override
  State<Workspace> createState() => _WorkspaceState();
}

class _WorkspaceState extends State<Workspace> {
  final email = TextEditingController(),
      password = TextEditingController(),
      projectName = TextEditingController(text: '校园活动');
  bool registration = false, busy = false;
  String error = '', selected = '', createKey = '';
  List<Map<String, dynamic>> projects = [];
  Map<String, dynamic>? run, probeResult;
  final picker = ImagePicker();
  static const labels = {
    'covered': '已有合格证据',
    'insufficient': '素材不足',
    'uncertain': '尚不确定',
    'missing': '缺少支持素材',
  };
  @override
  void initState() {
    super.initState();
    recoverCapture();
  }

  Future<void> recoverCapture() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
    try {
      final lost = await picker.retrieveLostData();
      if (!lost.isEmpty && mounted) {
        setState(() => error = '发现未完成的采集返回，请登录并选择项目后重新选择视频进行探针。');
      }
    } catch (e) {
      if (mounted) setState(() => error = '无法恢复采集返回：$e');
    }
  }

  @override
  void dispose() {
    email.dispose();
    password.dispose();
    projectName.dispose();
    super.dispose();
  }

  Future<void> action(Future<void> Function() work) async {
    if (busy) return;
    setState(() {
      busy = true;
      error = '';
    });
    try {
      await work();
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> login() async {
    await widget.api.authenticate(
      email.text.trim(),
      password.text,
      register: registration,
    );
    projects = await widget.api.projects();
  }

  Future<void> create() async {
    createKey = createKey.isEmpty
        ? 'mobile-ui-${DateTime.now().microsecondsSinceEpoch}'
        : createKey;
    final project = await widget.api.createProject(
      projectName.text,
      key: createKey,
    );
    createKey = '';
    projects = await widget.api.projects();
    selected = project['id'];
    run = null;
  }

  Future<void> capture(ImageSource source) async {
    final video = await picker.pickVideo(
      source: source,
      maxDuration: const Duration(seconds: 8),
    );
    if (video == null) return;
    if (await video.length() > 16 * 1024 * 1024) {
      throw ApiFailure('视频超过 16 MiB，请缩短后重试');
    }
    probeResult = await widget.api.probe(
      selected,
      await video.readAsBytes(),
      video.name,
    );
  }

  Widget panel(List<Widget> children) => Card(
    margin: const EdgeInsets.only(bottom: 16),
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: children,
      ),
    ),
  );
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('影织 AI · 第一阶段'),
      actions: [
        if (widget.api.token.isNotEmpty)
          TextButton(
            onPressed: busy
                ? null
                : () => action(() async {
                    await widget.api.logout();
                    projects = [];
                    selected = '';
                    run = null;
                    probeResult = null;
                  }),
            child: const Text('退出'),
          ),
      ],
    ),
    body: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760),
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            Text(
              '故事有据可依，修改有界可控。',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: 12),
            const Text('人工标注的合成元数据 · 同步规则回放 · 未调用模型'),
            const SizedBox(height: 20),
            if (busy) const LinearProgressIndicator(),
            if (error.isNotEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text(
                  error,
                  key: const Key('error'),
                  style: const TextStyle(color: Colors.red),
                ),
              ),
            if (widget.api.token.isEmpty)
              panel([
                Text(
                  registration ? '创建账号' : '登录项目',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 12),
                TextField(
                  key: const Key('email'),
                  controller: email,
                  keyboardType: TextInputType.emailAddress,
                  decoration: const InputDecoration(labelText: '邮箱'),
                ),
                TextField(
                  key: const Key('password'),
                  controller: password,
                  obscureText: true,
                  decoration: const InputDecoration(labelText: '密码（至少 12 位）'),
                ),
                const SizedBox(height: 18),
                FilledButton(
                  onPressed: busy ? null : () => action(login),
                  child: Text(registration ? '注册并进入' : '登录'),
                ),
                TextButton(
                  onPressed: busy
                      ? null
                      : () => setState(() => registration = !registration),
                  child: Text(registration ? '已有账号，登录' : '创建账号'),
                ),
              ])
            else ...[
              panel([
                Text('项目', style: Theme.of(context).textTheme.titleLarge),
                TextField(
                  controller: projectName,
                  decoration: const InputDecoration(labelText: '项目名称'),
                ),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: busy ? null : () => action(create),
                  child: const Text('创建校园项目'),
                ),
                TextButton(
                  onPressed: busy
                      ? null
                      : () => action(() async {
                          projects = await widget.api.projects();
                        }),
                  child: const Text('刷新项目'),
                ),
                if (projects.isEmpty) const Text('还没有项目，请先创建。'),
                for (final project in projects)
                  ListTile(
                    title: Text(project['name']),
                    subtitle: Text(
                      '${project['scenario']} · revision ${project['revision']}',
                    ),
                    selected: selected == project['id'],
                    trailing: selected == project['id']
                        ? const Icon(Icons.check_circle_outline)
                        : null,
                    onTap: busy
                        ? null
                        : () => setState(() {
                            selected = project['id'];
                            run = null;
                            probeResult = null;
                          }),
                  ),
              ]),
              if (selected.isNotEmpty)
                panel([
                  FilledButton(
                    onPressed: busy
                        ? null
                        : () => action(() async {
                            run = await widget.api.replay(selected);
                          }),
                    child: const Text('运行固定样例'),
                  ),
                  const SizedBox(height: 12),
                  const Text('补拍上传事件与完成验证分开；规则回放不会发布生产版本。'),
                ]),
              if (run != null) ...[
                panel([
                  Text('故事覆盖', style: Theme.of(context).textTheme.titleLarge),
                  for (final report in run!['coverage'] as List)
                    ListTile(
                      title: Text(
                        '${report['node_key']} · ${labels[report['coverage']]}',
                      ),
                      subtitle: Text(
                        '可用时长 ${report['usable_duration_ms']} ms\n${(report['reason_codes'] as List).join(' / ')}',
                      ),
                    ),
                ]),
                panel([
                  Text('补拍验证门', style: Theme.of(context).textTheme.titleLarge),
                  const SizedBox(height: 8),
                  Text(run!['capture']['initial']['instruction']),
                  Text('初始：${run!['capture']['initial']['state']}'),
                  Text('上传后：${run!['capture']['after_upload']['state']}'),
                  Text(
                    '新证据验证后：${run!['capture']['after_verification']['state']}',
                  ),
                ]),
                panel([
                  Text('局部修改检查', style: Theme.of(context).textTheme.titleLarge),
                  for (final entry
                      in (run!['edits'] as Map<String, dynamic>).entries)
                    ListTile(
                      title: Text(
                        '${entry.key} · ${entry.value['accepted'] ? '允许' : '拒绝'}',
                      ),
                      subtitle: Text(
                        '${entry.value['validation']?['hard_errors'] ?? entry.value['error_code'] ?? '通过'}',
                      ),
                    ),
                ]),
                panel([
                  Text('复核记录', style: Theme.of(context).textTheme.titleLarge),
                  Text('数据版本：${run!['dataset_version']}'),
                  Text('检查：${run!['passed'] ? '通过' : '存在失败'}'),
                  SelectableText('代码：${run!['code']['commit']}'),
                  SelectableText('输入摘要：${run!['input_hash']}'),
                ]),
              ],
              if (selected.isNotEmpty)
                panel([
                  Text(
                    '采集与媒体探针',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const Text('请选择有权使用的视频；探针上限 16 MiB，只检查媒体工具链。'),
                  const SizedBox(height: 12),
                  FilledButton.tonal(
                    onPressed: busy
                        ? null
                        : () => action(() => capture(ImageSource.gallery)),
                    child: const Text('选择视频并上传探针'),
                  ),
                  if (!kIsWeb &&
                      (defaultTargetPlatform == TargetPlatform.android ||
                          defaultTargetPlatform == TargetPlatform.iOS))
                    TextButton(
                      onPressed: busy
                          ? null
                          : () => action(() => capture(ImageSource.camera)),
                      child: const Text('拍摄 8 秒视频并上传探针'),
                    ),
                  if (probeResult != null)
                    SelectableText(
                      const JsonEncoder.withIndent('  ').convert(probeResult),
                    ),
                ]),
            ],
          ],
        ),
      ),
    ),
  );
}

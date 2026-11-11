import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'contracts.dart';

class ApiFailure implements Exception {
  final String message;
  ApiFailure(this.message);
  @override
  String toString() => message;
}

class ShadowApi {
  final String baseUrl;
  final http.Client client;
  final ContractCatalog catalog;
  String token = '', refreshToken = '', displayName = '';
  int _counter = 0;
  ShadowApi({
    required this.catalog,
    http.Client? client,
    this.baseUrl = const String.fromEnvironment(
      'API_BASE_URL',
      defaultValue: 'http://127.0.0.1:8000/api/v1',
    ),
  }) : client = client ?? http.Client();

  Future<dynamic> request(
    String path, {
    String method = 'GET',
    Object? body,
    Map<String, String>? extra,
  }) async {
    final headers = {
      'Content-Type': 'application/json',
      if (token.isNotEmpty) 'Authorization': 'Bearer $token',
      ...?extra,
    };
    try {
      final req = http.Request(method, Uri.parse('$baseUrl$path'))
        ..headers.addAll(headers);
      if (body != null) req.body = jsonEncode(body);
      final streamed = await client
          .send(req)
          .timeout(const Duration(seconds: 20));
      final response = await http.Response.fromStream(streamed)
          .timeout(const Duration(seconds: 20));
      final dynamic parsed = response.body.isEmpty
          ? null
          : jsonDecode(utf8.decode(response.bodyBytes));
      if (response.statusCode >= 400) {
        if (response.statusCode == 401) {
          token = '';
          refreshToken = '';
          displayName = '';
        }
        throw ApiFailure(
          '${parsed?['error']?['code'] ?? response.statusCode}：${parsed?['error']?['message'] ?? '请求失败'}',
        );
      }
      return parsed;
    } on TimeoutException {
      throw ApiFailure('请求超时，请检查 API 连接后重试');
    } on http.ClientException {
      throw ApiFailure('无法连接 API，请检查服务地址和网络');
    }
  }

  Future<void> authenticate(
    String email,
    String password, {
    bool register = false,
  }) async {
    final body = await request(
      '/auth/${register ? 'register' : 'login'}',
      method: 'POST',
      body: {
        'email': email,
        'password': password,
        'client_kind': 'mobile',
        if (register) 'display_name': email.split('@').first,
      },
    );
    token = body['access_token'];
    refreshToken = body['refresh_token'];
    displayName = body['user']['display_name'];
  }

  Future<void> logout() async {
    try {
      await request(
        '/auth/logout',
        method: 'POST',
        body: {'refresh_token': refreshToken},
      );
    } finally {
      token = '';
      refreshToken = '';
      displayName = '';
    }
  }

  Future<List<Map<String, dynamic>>> projects() async {
    final rows = await request('/projects') as List;
    return rows.map((row) => catalog.parse('Project', row)).toList();
  }

  Future<Map<String, dynamic>> createProject(String name, {String? key}) async {
    final requestKey =
        key ?? 'mobile-${DateTime.now().microsecondsSinceEpoch}-${_counter++}';
    return catalog.parse(
      'Project',
      await request(
        '/projects',
        method: 'POST',
        body: {'name': name, 'scenario': 'campus'},
        extra: {'Idempotency-Key': requestKey},
      ),
    );
  }

  Future<Map<String, dynamic>> replay(String project) async {
    final prefix = '/projects/$project/phase-one';
    await request('$prefix/seed', method: 'POST');
    return await request('$prefix/replay', method: 'POST')
        as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> probe(
    String project,
    Uint8List bytes,
    String name,
  ) async {
    if (bytes.length > 16 * 1024 * 1024) throw ApiFailure('探针视频不能超过 16 MiB');
    final req =
        http.MultipartRequest(
            'POST',
            Uri.parse('$baseUrl/projects/$project/phase-one/media-probe'),
          )
          ..headers['Authorization'] = 'Bearer $token'
          ..files.add(
            http.MultipartFile.fromBytes('upload', bytes, filename: name),
          );
    try {
      final response = await http.Response.fromStream(
        await client.send(req).timeout(const Duration(seconds: 30)),
      );
      final body =
          jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      if (response.statusCode >= 400) {
        throw ApiFailure(
          '${body['error']?['code']}：${body['error']?['message']}',
        );
      }
      return body;
    } on TimeoutException {
      throw ApiFailure('媒体探针超时，请重试');
    }
  }

  void close() => client.close();
}

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shadowweave_mobile/api.dart';
import 'package:shadowweave_mobile/contracts.dart';
import 'package:shadowweave_mobile/main.dart';

void main() {
  testWidgets('login displays API project and exposes replay action', (
    tester,
  ) async {
    final paths = <String>[];
    final api = ShadowApi(
      catalog: ContractCatalog(
        jsonDecode(File('assets/contracts.json').readAsStringSync()),
      ),
      client: MockClient((request) async {
        paths.add(request.url.path);
        if (request.url.path.endsWith('/auth/login')) {
          return http.Response(
            jsonEncode({
              'access_token': 'test-access',
              'refresh_token': 'test-refresh',
              'user': {'display_name': 'Tester'},
            }),
            200,
          );
        }
        expect(request.headers['Authorization'], 'Bearer test-access');
        return http.Response(
          jsonEncode([
            {
              'id': '00000000-0000-4000-8000-000000000001',
              'name': 'API Campus',
              'scenario': 'campus',
              'revision': 1,
              'head_revision': 0,
            },
          ]),
          200,
        );
      }),
    );
    await tester.pumpWidget(PhaseOneApp(api: api));
    await tester.enterText(find.byKey(const Key('email')), 'test@example.test');
    await tester.enterText(
      find.byKey(const Key('password')),
      'test-password-123',
    );
    await tester.tap(find.text('登录'));
    await tester.pumpAndSettle();
    expect(find.text('API Campus'), findsOneWidget);
    await tester.tap(find.text('API Campus'));
    await tester.pumpAndSettle();
    expect(find.text('运行固定样例'), findsOneWidget);
    expect(paths, ['/api/v1/auth/login', '/api/v1/projects']);
    api.close();
  });
  testWidgets('connection failure is visible and does not authenticate', (
    tester,
  ) async {
    final api = ShadowApi(
      catalog: ContractCatalog(
        jsonDecode(File('assets/contracts.json').readAsStringSync()),
      ),
      client: MockClient((_) async => throw http.ClientException('offline')),
    );
    await tester.pumpWidget(PhaseOneApp(api: api));
    await tester.tap(find.text('登录'));
    await tester.pumpAndSettle();
    expect(find.textContaining('无法连接 API'), findsOneWidget);
    expect(api.token, isEmpty);
    api.close();
  });
}

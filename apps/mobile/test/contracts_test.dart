import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:shadowweave_mobile/contracts.dart';

void main() {
  final catalog = ContractCatalog(
    jsonDecode(File('assets/contracts.json').readAsStringSync()),
  );
  final cases =
      jsonDecode(
            File('../../packages/contracts/examples/cases.json')
                .readAsStringSync(),
          )['cases']
          as List;
  for (final c in cases) {
    test(c['id'], () {
      if (c['valid']) {
        expect(catalog.parse(c['model'], c['input']), c['normalized']);
      } else {
        expect(
          () => catalog.parse(c['model'], c['input']),
          throwsFormatException,
        );
      }
    });
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/routing/app_router.dart';

class MeuFinanceiroApp extends ConsumerWidget {
  const MeuFinanceiroApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(appRouterProvider);

    return MaterialApp.router(
      title: 'MeuFinanceiro',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF365C4D)),
        useMaterial3: true,
      ),
      routerConfig: router,
    );
  }
}

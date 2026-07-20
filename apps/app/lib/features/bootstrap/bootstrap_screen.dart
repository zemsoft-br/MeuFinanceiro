import 'package:flutter/material.dart';

class BootstrapScreen extends StatelessWidget {
  const BootstrapScreen({super.key});

  static const titleKey = Key('bootstrap-title');

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Semantics(
                    header: true,
                    child: Text(
                      'MeuFinanceiro',
                      key: titleKey,
                      style: Theme.of(context).textTheme.headlineMedium,
                    ),
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'Base Flutter inicial. O shell funcional será portado em uma entrega posterior.',
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

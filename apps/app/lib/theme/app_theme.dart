import 'package:flutter/material.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

ThemeData buildAppTheme() {
  final colorScheme = ColorScheme.fromSeed(
    seedColor: AppTokens.forest900,
    brightness: Brightness.light,
    primary: AppTokens.forest900,
    secondary: AppTokens.amber700,
    surface: AppTokens.white,
    error: AppTokens.red700,
  );

  final baseTextTheme = Typography.material2021().black.apply(
    bodyColor: AppTokens.neutral950,
    displayColor: AppTokens.neutral950,
  );

  return ThemeData(
    useMaterial3: true,
    colorScheme: colorScheme,
    scaffoldBackgroundColor: AppTokens.neutral50,
    textTheme: baseTextTheme.copyWith(
      displaySmall: baseTextTheme.displaySmall?.copyWith(
        fontWeight: FontWeight.w700,
        height: 1.12,
      ),
      headlineLarge: baseTextTheme.headlineLarge?.copyWith(
        fontWeight: FontWeight.w700,
        height: 1.18,
      ),
      headlineMedium: baseTextTheme.headlineMedium?.copyWith(
        fontWeight: FontWeight.w700,
        height: 1.2,
      ),
      titleLarge: baseTextTheme.titleLarge?.copyWith(
        fontWeight: FontWeight.w700,
      ),
      titleMedium: baseTextTheme.titleMedium?.copyWith(
        fontWeight: FontWeight.w700,
      ),
      bodyLarge: baseTextTheme.bodyLarge?.copyWith(height: 1.5),
      bodyMedium: baseTextTheme.bodyMedium?.copyWith(height: 1.45),
      labelLarge: baseTextTheme.labelLarge?.copyWith(
        fontWeight: FontWeight.w700,
      ),
    ),
    focusColor: AppTokens.amber100,
    hoverColor: AppTokens.forest50,
    dividerColor: AppTokens.neutral200,
    cardTheme: const CardThemeData(
      elevation: 0,
      color: AppTokens.white,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(AppTokens.radiusMedium)),
        side: BorderSide(color: AppTokens.neutral200),
      ),
    ),
    inputDecorationTheme: const InputDecorationTheme(
      filled: true,
      fillColor: AppTokens.white,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(AppTokens.radiusSmall)),
        borderSide: BorderSide(color: AppTokens.neutral300),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(AppTokens.radiusSmall)),
        borderSide: BorderSide(color: AppTokens.neutral300),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(AppTokens.radiusSmall)),
        borderSide: BorderSide(color: AppTokens.forest700, width: 2),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(AppTokens.radiusSmall)),
        borderSide: BorderSide(color: AppTokens.red700),
      ),
      focusedErrorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(AppTokens.radiusSmall)),
        borderSide: BorderSide(color: AppTokens.red700, width: 2),
      ),
      contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(44, 44),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.all(
            Radius.circular(AppTokens.radiusSmall),
          ),
        ),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(44, 44),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
        side: const BorderSide(color: AppTokens.neutral300),
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.all(
            Radius.circular(AppTokens.radiusSmall),
          ),
        ),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        minimumSize: const Size(44, 44),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.all(
            Radius.circular(AppTokens.radiusSmall),
          ),
        ),
      ),
    ),
    navigationBarTheme: const NavigationBarThemeData(
      height: 72,
      backgroundColor: AppTokens.white,
      indicatorColor: AppTokens.forest100,
      labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
    ),
    tooltipTheme: const TooltipThemeData(
      waitDuration: Duration(milliseconds: 500),
    ),
    visualDensity: VisualDensity.standard,
  );
}

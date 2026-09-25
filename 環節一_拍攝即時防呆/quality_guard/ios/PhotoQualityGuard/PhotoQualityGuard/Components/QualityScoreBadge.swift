import SwiftUI

struct QualityScoreBadge: View {
    let score: Int
    var body: some View {
        Text("品質分數 \(score)")
            .font(.footnote.weight(.semibold))
            .foregroundStyle(AppTheme.Colors.textSecondary)
            .padding(.horizontal, AppTheme.Spacing.md)
            .padding(.vertical, AppTheme.Spacing.xs)
            .background(AppTheme.Colors.surface2, in: Capsule())
            .accessibilityLabel("品質分數 \(score) 分")
    }
}

/// 黃色 advisory pill（偏暗／偏模糊等，不擋關）
struct WarningPill: View {
    let text: String
    var body: some View {
        Label(text, systemImage: "exclamationmark.triangle.fill")
            .font(.caption.weight(.bold))
            .foregroundStyle(AppTheme.Colors.warning)
            .padding(.horizontal, AppTheme.Spacing.sm)
            .frame(minHeight: 24)
            .background(AppTheme.Colors.warningSoft, in: Capsule())
            .accessibilityLabel("注意：\(text)")
    }
}

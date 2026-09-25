import SwiftUI

enum AppButtonKind { case primary, secondary, ghost }

/// 統一的按鈕：48pt 高、圓角 10、三種樣式。
struct AppButton: View {
    let title: String
    var systemImage: String? = nil
    var kind: AppButtonKind = .primary
    var fullWidth: Bool = true
    let action: () -> Void

    @Environment(\.isEnabled) private var isEnabled

    var body: some View {
        Button(action: action) {
            HStack(spacing: AppTheme.Spacing.sm) {
                if let systemImage { Image(systemName: systemImage) }
                Text(title)
            }
            .font(.body.weight(.bold))
            .frame(maxWidth: fullWidth ? .infinity : nil, minHeight: AppTheme.touchTarget)
            .padding(.horizontal, AppTheme.Spacing.lg)
            .foregroundStyle(foreground)
            .background(background, in: RoundedRectangle(cornerRadius: AppTheme.Radius.sm, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: AppTheme.Radius.sm, style: .continuous)
                    .stroke(border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .contentShape(Rectangle())
    }

    private var foreground: Color {
        guard isEnabled else { return AppTheme.Colors.textTertiary }
        switch kind {
        case .primary: return .white
        case .secondary: return AppTheme.Colors.text
        case .ghost: return AppTheme.Colors.textSecondary
        }
    }

    private var background: Color {
        guard isEnabled else { return AppTheme.Colors.surface2 }
        switch kind {
        case .primary: return AppTheme.Colors.primary
        case .secondary: return AppTheme.Colors.surface
        case .ghost: return .clear
        }
    }

    private var border: Color {
        guard isEnabled else { return AppTheme.Colors.border }
        switch kind {
        case .primary: return .clear
        case .secondary: return AppTheme.Colors.border2
        case .ghost: return .clear
        }
    }
}

/// 保留規劃中的名稱，方便之後直接使用。
struct PrimaryButton: View {
    let title: String
    var systemImage: String? = nil
    let action: () -> Void
    var body: some View { AppButton(title: title, systemImage: systemImage, kind: .primary, action: action) }
}

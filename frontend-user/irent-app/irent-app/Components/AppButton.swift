import SwiftUI

enum AppButtonKind { case primary, secondary, ghost }

struct AppButton: View {
    let title: String
    var systemImage: String? = nil
    var kind: AppButtonKind = .primary
    var fullWidth = true
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
            .overlay {
                RoundedRectangle(cornerRadius: AppTheme.Radius.sm, style: .continuous)
                    .stroke(border, lineWidth: 1)
            }
        }
        .buttonStyle(.plain)
    }

    private var foreground: Color {
        guard isEnabled else { return AppTheme.Colors.textTertiary }
        return kind == .primary ? .white : (kind == .secondary ? AppTheme.Colors.text : AppTheme.Colors.textSecondary)
    }

    private var background: Color {
        guard isEnabled else { return AppTheme.Colors.surface2 }
        return kind == .primary ? AppTheme.Colors.primary : (kind == .secondary ? AppTheme.Colors.surface : .clear)
    }

    private var border: Color {
        guard isEnabled else { return AppTheme.Colors.border }
        return kind == .secondary ? AppTheme.Colors.border2 : .clear
    }
}

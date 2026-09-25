import SwiftUI

/// 三關卡片左側的狀態 icon。顏色 + 符號 + 無障礙文字三者一起給，不靠顏色單獨表達。
struct StatusIcon: View {
    let status: StageStatus
    var size: CGFloat = 32

    var body: some View {
        ZStack {
            Circle().fill(tint.opacity(0.14))
            Image(systemName: symbol)
                .font(.system(size: size * 0.5, weight: .bold))
                .foregroundStyle(tint)
        }
        .frame(width: size, height: size)
        .accessibilityLabel(label)
    }

    var tint: Color {
        switch status {
        case .passed: return AppTheme.Colors.success
        case .failed: return AppTheme.Colors.error
        case .skipped: return AppTheme.Colors.warning
        }
    }

    var symbol: String {
        switch status {
        case .passed: return "checkmark"
        case .failed: return "xmark"
        case .skipped: return "minus"
        }
    }

    var label: String {
        switch status {
        case .passed: return "通過"
        case .failed: return "未通過"
        case .skipped: return "未執行"
        }
    }
}

/// 狀態文字標籤（右側）
struct StatusTag: View {
    let status: StageStatus
    var body: some View {
        let icon = StatusIcon(status: status)
        Text(icon.label)
            .font(.footnote.weight(.bold))
            .foregroundStyle(icon.tint)
            .padding(.horizontal, AppTheme.Spacing.sm)
            .padding(.vertical, AppTheme.Spacing.xs)
            .background(icon.tint.opacity(0.14), in: RoundedRectangle(cornerRadius: AppTheme.Radius.xs, style: .continuous))
    }
}

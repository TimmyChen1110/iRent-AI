import SwiftUI

/// Shared visual tokens from the PhotoQualityGuard prototype.
enum AppTheme {
    enum Colors {
        static let primary = Color(hex: 0x3764CA)
        static let primaryDark = Color(hex: 0x2446A3)
        static let primarySoft = Color(hex: 0xE8EEFA)
        static let success = Color(hex: 0x1F9D55)
        static let successSoft = Color(hex: 0xE4F5EB)
        static let error = Color(hex: 0xD93B3B)
        static let errorSoft = Color(hex: 0xFBE9E9)
        static let background = Color(hex: 0xF7F9FC)
        static let surface = Color.white
        static let surface2 = Color(hex: 0xF1F4F9)
        static let text = Color(hex: 0x1A2138)
        static let textSecondary = Color(hex: 0x5B6478)
        static let textTertiary = Color(hex: 0x8C94A6)
        static let border = Color(hex: 0xE3E8F1)
        static let border2 = Color(hex: 0xCCD4E3)
        static let cameraBackground = Color(hex: 0x0F172A)
    }

    enum Spacing {
        static let xs: CGFloat = 4
        static let sm: CGFloat = 8
        static let md: CGFloat = 12
        static let lg: CGFloat = 16
        static let xl: CGFloat = 24
    }

    enum Radius {
        static let sm: CGFloat = 10
        static let md: CGFloat = 14
        static let lg: CGFloat = 20
    }

    static let touchTarget: CGFloat = 48
}

extension Color {
    init(hex: UInt32, opacity: Double = 1) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: opacity
        )
    }
}

private struct CardStyle: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(AppTheme.Spacing.lg)
            .background(AppTheme.Colors.surface, in: RoundedRectangle(cornerRadius: AppTheme.Radius.md, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: AppTheme.Radius.md, style: .continuous)
                    .stroke(AppTheme.Colors.border, lineWidth: 1)
            }
    }
}

extension View {
    func qualityCard() -> some View { modifier(CardStyle()) }
}

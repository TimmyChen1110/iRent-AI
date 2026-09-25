import SwiftUI

/// 蓋在照片區上的分析中遮罩
struct AnalysisLoadingView: View {
    var body: some View {
        ZStack {
            AppTheme.Colors.cameraBackground.opacity(0.68)
            VStack(spacing: AppTheme.Spacing.sm) {
                ProgressView()
                    .controlSize(.large)
                    .tint(.white)
                Text("正在檢查照片")
                    .font(.headline)
                    .foregroundStyle(.white)
                Text("正在確認清晰度、車牌與拍攝角度")
                    .font(.footnote)
                    .foregroundStyle(.white.opacity(0.75))
                    .multilineTextAlignment(.center)
            }
            .padding(AppTheme.Spacing.xl)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("正在檢查照片，正在確認清晰度、車牌與拍攝角度")
        .accessibilityIdentifier("analysis.loading")
    }
}

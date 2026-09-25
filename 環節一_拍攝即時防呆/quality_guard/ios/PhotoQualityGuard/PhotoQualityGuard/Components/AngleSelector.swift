import SwiftUI

/// 拍攝角度 chips。`nil` = 不指定。送給 API 的值是 `RequiredView.rawValue`，這裡只負責顯示與選取。
struct AngleSelector: View {
    let selection: RequiredView?
    let isDisabled: Bool
    let onSelect: (RequiredView?) -> Void

    private var options: [RequiredView?] { [nil] + RequiredView.allCases.map { Optional($0) } }

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: AppTheme.Spacing.sm) {
                ForEach(Array(options.enumerated()), id: \.offset) { _, option in
                    chip(for: option)
                }
            }
            .padding(.horizontal, AppTheme.Spacing.lg)
        }
        .disabled(isDisabled)
        .opacity(isDisabled ? 0.5 : 1)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("拍攝角度")
    }

    private func chip(for option: RequiredView?) -> some View {
        let isSelected = option == selection
        let title = option?.chipTitle ?? "不指定"
        return Button {
            onSelect(option)
        } label: {
            Text(title)
                .font(.body.weight(.semibold))
                .foregroundStyle(isSelected ? .white : AppTheme.Colors.textSecondary)
                .padding(.horizontal, AppTheme.Spacing.lg)
                .frame(minHeight: 44)
                .background(isSelected ? AppTheme.Colors.primary : AppTheme.Colors.surface, in: Capsule())
                .overlay(Capsule().stroke(isSelected ? AppTheme.Colors.primary : AppTheme.Colors.border2, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(option?.displayName ?? "不指定角度")
        .accessibilityAddTraits(isSelected ? [.isSelected] : [])
        .accessibilityIdentifier("angle.\(option?.rawValue ?? "none")")
    }
}

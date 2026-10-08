import SwiftUI

/// 導航列左上角的返回按鈕（`chevron.left`）。
/// 只用在 NavigationStack 的「根畫面」——租還車各階段依狀態替換根畫面，系統不會自動給返回鍵；
/// push 進來的頁面一律沿用系統原生返回鍵與邊緣滑動手勢，不要再加這顆。
struct AppBackButton: View {
    var label = "返回"
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(label, systemImage: "chevron.left")
                .labelStyle(.iconOnly)
                .font(.body.weight(.semibold))
                .frame(minWidth: 44, minHeight: 44)
                .contentShape(Rectangle())
        }
        .accessibilityLabel(label)
    }
}

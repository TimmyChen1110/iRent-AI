import SwiftUI

/// 拍攝項目圖示。外觀四角各用一張從該角落約 45° 看過去的車輛 SVG（`InspectionShot.iconAsset`，
/// 由 `tools/angle_icons/generate.py` 產生、template 模式渲染）；車內沿用原本的 SF Symbol。
/// 未拍攝＝灰色；完成＝accent 色＋右下角綠色勾。
struct InspectionAngleIcon: View {
    let shot: InspectionShot
    var isDone = false

    var body: some View {
        icon
            .foregroundStyle(isDone ? Color.accentColor : Color.secondary)
            .overlay(alignment: .bottomTrailing) {
                if isDone {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.caption)
                        .symbolRenderingMode(.palette)
                        .foregroundStyle(.white, .green)
                }
            }
            .accessibilityElement()
            .accessibilityLabel(isDone ? "\(shot.title)，已完成" : shot.title)
    }

    @ViewBuilder private var icon: some View {
        if let asset = shot.iconAsset {
            Image(asset).resizable().scaledToFit()
        } else {
            Image(systemName: shot.systemImage)
        }
    }
}

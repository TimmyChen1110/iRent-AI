import SwiftUI

/// 把 backend 的 `plate_bbox` 畫在照片上。
///
/// 沿用 Web 版 `renderAnnotatedPhoto()` 的座標語意：
/// - `bbox` 是「backend 實際處理的那張圖」的像素座標。若 `rotation`（backend 方向防護網套用的
///   **逆時針**角度，0/90/270）不是 0，bbox 是轉正後的座標系，畫面上的照片也要先轉同樣角度。
/// - 轉 90/270 時寬高互換；先用「轉正後的尺寸」做 aspectFit，再把原圖以同樣比例縮放、
///   置中、逆時針轉 `rotation` 度，bbox 直接乘比例加 letterbox 偏移。
struct PlateOverlayImage: View {
    let image: UIImage
    /// backend 收到的那張圖的像素尺寸（= PreparedPhoto.pixelSize）
    let pixelSize: CGSize
    let bbox: [Int]
    let rotation: Int

    var body: some View {
        let geometry = PlateBoxGeometry(pixelSize: pixelSize, rotation: rotation)
        GeometryReader { geo in
            let layout = geometry.layout(in: geo.size, bbox: bbox)
            ZStack(alignment: .topLeading) {
                Image(uiImage: image)
                    .resizable()
                    .frame(width: layout.imageFrameSize.width, height: layout.imageFrameSize.height)
                    .rotationEffect(.degrees(-Double(rotation)))
                    .position(layout.imageCenter)

                if let box = layout.boxRect {
                    RoundedRectangle(cornerRadius: 2)
                        .stroke(.black.opacity(0.55), lineWidth: 5)
                        .frame(width: box.width, height: box.height)
                        .offset(x: box.minX, y: box.minY)
                    RoundedRectangle(cornerRadius: 2)
                        .stroke(AppTheme.Colors.plateBox, lineWidth: 3)
                        .frame(width: box.width, height: box.height)
                        .offset(x: box.minX, y: box.minY)
                    Text("車牌")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(Color(hex: 0x06240F))
                        .padding(.horizontal, 5)
                        .frame(height: 18)
                        .background(AppTheme.Colors.plateBox)
                        .offset(x: box.minX, y: box.minY - 20 >= 0 ? box.minY - 20 : box.minY + 2)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height)
        }
        .aspectRatio(geometry.displayAspectRatio, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.sm, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: AppTheme.Radius.sm, style: .continuous).stroke(AppTheme.Colors.border, lineWidth: 1))
        .accessibilityLabel("標示車牌位置的照片")
        .accessibilityIdentifier("plate.overlay")
    }
}

/// 純計算，方便單元測試。
struct PlateBoxGeometry {
    let pixelSize: CGSize
    let rotation: Int

    struct Layout: Equatable {
        /// 原圖（未旋轉）縮放後的 frame 尺寸
        var imageFrameSize: CGSize
        /// 原圖 frame 的中心（旋轉以此為軸）
        var imageCenter: CGPoint
        /// 轉正後照片實際佔的區域（letterbox 之後）
        var fittedRect: CGRect
        var scale: CGFloat
        /// bbox 在容器座標系的位置
        var boxRect: CGRect?
    }

    var swapsAxes: Bool { rotation == 90 || rotation == 270 }

    /// 轉正後的像素尺寸
    var rotatedPixelSize: CGSize {
        swapsAxes ? CGSize(width: pixelSize.height, height: pixelSize.width) : pixelSize
    }

    var displayAspectRatio: CGFloat {
        let r = rotatedPixelSize
        return r.height > 0 ? r.width / r.height : 1
    }

    func layout(in container: CGSize, bbox: [Int]?) -> Layout {
        let rotated = rotatedPixelSize
        guard rotated.width > 0, rotated.height > 0, container.width > 0, container.height > 0 else {
            return Layout(imageFrameSize: .zero, imageCenter: .zero, fittedRect: .zero, scale: 1, boxRect: nil)
        }
        let scale = min(container.width / rotated.width, container.height / rotated.height)
        let fitted = CGSize(width: rotated.width * scale, height: rotated.height * scale)
        let origin = CGPoint(x: (container.width - fitted.width) / 2, y: (container.height - fitted.height) / 2)
        let fittedRect = CGRect(origin: origin, size: fitted)
        let imageFrameSize = CGSize(width: pixelSize.width * scale, height: pixelSize.height * scale)
        let center = CGPoint(x: fittedRect.midX, y: fittedRect.midY)

        var boxRect: CGRect?
        if let bbox, bbox.count == 4 {
            let x1 = CGFloat(bbox[0]) * scale, y1 = CGFloat(bbox[1]) * scale
            let x2 = CGFloat(bbox[2]) * scale, y2 = CGFloat(bbox[3]) * scale
            boxRect = CGRect(x: origin.x + x1, y: origin.y + y1, width: max(0, x2 - x1), height: max(0, y2 - y1))
        }
        return Layout(imageFrameSize: imageFrameSize, imageCenter: center, fittedRect: fittedRect, scale: scale, boxRect: boxRect)
    }
}

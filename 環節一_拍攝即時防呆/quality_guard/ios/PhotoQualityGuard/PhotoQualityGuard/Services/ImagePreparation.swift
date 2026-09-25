import UIKit

/// 準備好要送 backend 的照片。
///
/// `image` 的像素已經是正立的（orientation == .up），`pixelSize` 就是 backend 收到的圖片尺寸，
/// 所以 backend 回傳的 `plate_bbox` 可以直接用 `pixelSize` 對回這張圖。
struct PreparedPhoto: Sendable, Identifiable {
    let id = UUID()
    let image: UIImage
    let jpegData: Data
    let base64: String
    let pixelSize: CGSize
}

enum ImagePreparationError: Error {
    case cannotEncode
}

enum ImagePreparation {
    /// 把 UIImage 轉成 backend 要的 JPEG + 純 base64。
    ///
    /// - **不縮圖**：輸出像素尺寸 = 原圖的（套用 orientation 後的）像素尺寸。
    /// - **把 EXIF orientation 烙進像素**：iPhone 拍的照片 `imageOrientation` 常是 `.right`，
    ///   像素其實是橫躺的。這裡用 renderer 重新畫一次，輸出的 JPEG 像素就是正立的，
    ///   backend 不需要依賴 EXIF，bbox 座標也直接對應我們手上這張圖。
    /// - 相簿的 HEIC 也在這一步轉成 JPEG（backend 的 cv2.imdecode 不吃 HEIC）。
    static func prepare(_ source: UIImage, jpegQuality: CGFloat = 0.95) throws -> PreparedPhoto {
        let upright = normalizedUpright(source)
        guard let data = upright.jpegData(compressionQuality: jpegQuality) else {
            throw ImagePreparationError.cannotEncode
        }
        let pixelSize = CGSize(width: upright.size.width * upright.scale, height: upright.size.height * upright.scale)
        return PreparedPhoto(image: upright, jpegData: data, base64: data.base64EncodedString(), pixelSize: pixelSize)
    }

    /// 回傳 orientation == .up、scale == 1、像素尺寸不變的 UIImage。
    static func normalizedUpright(_ image: UIImage) -> UIImage {
        if image.imageOrientation == .up, image.scale == 1 { return image }
        // image.size 已經是「套用 orientation 後」的 point 尺寸；乘 scale 得到像素尺寸。
        let pixelSize = CGSize(width: image.size.width * image.scale, height: image.size.height * image.scale)
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        format.opaque = true
        let renderer = UIGraphicsImageRenderer(size: pixelSize, format: format)
        return renderer.image { _ in
            image.draw(in: CGRect(origin: .zero, size: pixelSize))
        }
    }
}

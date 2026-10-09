import CryptoKit
import Foundation
import UIKit

enum PhotoStoreError: LocalizedError {
    case imageEncodingFailed

    var errorDescription: String? { "無法處理這張照片，請重新拍攝。" }
}

struct PhotoStore {
    private let directory: URL

    init(fileManager: FileManager = .default) {
        directory = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("InspectionPhotos", isDirectory: true)
        try? fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    /// 保存／上傳的長邊上限。後端送 AI 前一律縮到 1280 寬（run_eval_gemini.prep_image），
    /// 原尺寸（iPhone 4032×3024）只會讓每張上傳變大數倍、拖慢還車；裝置端車牌／角度檢查在縮圖前就已完成。
    static let maxLongEdge: CGFloat = 1920

    func save(_ image: UIImage, stage: InspectionStage, shot: InspectionShot) throws -> (fileName: String, data: Data, hash: String) {
        guard let data = Self.downscaled(image).jpegData(compressionQuality: 0.9) else {
            throw PhotoStoreError.imageEncodingFailed
        }
        let hash = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        let fileName = "\(stage.rawValue)-\(shot.rawValue)-\(UUID().uuidString).jpg"
        try data.write(to: directory.appendingPathComponent(fileName), options: .atomic)
        return (fileName, data, hash)
    }

    /// 長邊超過上限才縮小；重繪時套用 EXIF 方向（輸出為正向像素）。
    static func downscaled(_ image: UIImage, maxLongEdge: CGFloat = maxLongEdge) -> UIImage {
        let pixelWidth = image.size.width * image.scale
        let pixelHeight = image.size.height * image.scale
        let longEdge = max(pixelWidth, pixelHeight)
        guard longEdge > maxLongEdge else { return image }
        let ratio = maxLongEdge / longEdge
        let target = CGSize(width: (pixelWidth * ratio).rounded(), height: (pixelHeight * ratio).rounded())
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        format.opaque = true
        return UIGraphicsImageRenderer(size: target, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: target))
        }
    }

    func image(named fileName: String) -> UIImage? {
        UIImage(contentsOfFile: directory.appendingPathComponent(fileName).path)
    }

    func data(named fileName: String) throws -> Data {
        try Data(contentsOf: directory.appendingPathComponent(fileName))
    }

    /// 重新拍攝某一階段時只清掉那些檔案。
    func remove(_ fileNames: [String]) {
        for name in fileNames { try? FileManager.default.removeItem(at: directory.appendingPathComponent(name)) }
    }

    /// 重新開始 Demo 時清掉本機照片檔。
    func removeAll() {
        guard let files = try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil) else { return }
        for file in files { try? FileManager.default.removeItem(at: file) }
    }
}

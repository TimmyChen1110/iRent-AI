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

    func save(_ image: UIImage, stage: InspectionStage, shot: InspectionShot) throws -> (fileName: String, data: Data, hash: String) {
        guard let data = image.jpegData(compressionQuality: 0.9) else {
            throw PhotoStoreError.imageEncodingFailed
        }
        let hash = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        let fileName = "\(stage.rawValue)-\(shot.rawValue)-\(UUID().uuidString).jpg"
        try data.write(to: directory.appendingPathComponent(fileName), options: .atomic)
        return (fileName, data, hash)
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

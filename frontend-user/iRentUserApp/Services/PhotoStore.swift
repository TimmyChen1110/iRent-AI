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

    func save(_ image: UIImage, stage: InspectionStage, view: VehicleView) throws -> (fileName: String, data: Data, hash: String) {
        guard let data = image.jpegData(compressionQuality: 0.9) else {
            throw PhotoStoreError.imageEncodingFailed
        }
        let hash = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        let fileName = "(stage.rawValue)-(view.rawValue)-(UUID().uuidString).jpg"
        try data.write(to: directory.appendingPathComponent(fileName), options: .atomic)
        return (fileName, data, hash)
    }

    func image(named fileName: String) -> UIImage? {
        UIImage(contentsOfFile: directory.appendingPathComponent(fileName).path)
    }

    func data(named fileName: String) throws -> Data {
        try Data(contentsOf: directory.appendingPathComponent(fileName))
    }
}

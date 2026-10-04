import CoreImage
import CoreML
import Foundation
import ImageIO
@preconcurrency import Vision

#if canImport(UIKit)
import UIKit
typealias RecognitionImage = UIImage
#elseif canImport(AppKit)
import AppKit
typealias RecognitionImage = NSImage
#endif

enum VehicleView: String, Codable, CaseIterable, Identifiable {
    case leftFront = "左前"
    case rightFront = "右前"
    case leftRear = "左後"
    case rightRear = "右後"

    var id: String { rawValue }
    var instruction: String { "請拍攝車輛\(rawValue)角，並讓車牌清楚入鏡。" }
}

struct LocalInspectionResult: Codable, Equatable {
    let passed: Bool
    let plateText: String?
    let plateConfidence: Double?
    let detectedView: VehicleView?
    let viewConfidence: Double?
    let errors: [String]
    let modelVersions: [String: String]
}

enum RecognitionError: LocalizedError {
    case modelMissing(String)
    case noPlate
    case unreadablePlate
    case wrongPlate(expected: String, actual: String)
    case wrongView(expected: VehicleView, actual: String)
    case lowResolution
    case unsupportedOutput

    var errorDescription: String? {
        switch self {
        case .modelMissing(let name): "離線模型 \(name) 尚未安裝。"
        case .noPlate: "沒有偵測到車牌，請讓車牌完整清楚入鏡。"
        case .unreadablePlate: "車牌文字無法辨識，請靠近並重新拍攝。"
        case .wrongPlate(let expected, let actual): "辨識到 \(actual)，與租約車牌 \(expected) 不符。"
        case .wrongView(let expected, let actual): "目前照片判定為 \(actual)，請改拍 \(expected.rawValue)角。"
        case .lowResolution: "照片解析度不足，請重新拍攝。"
        case .unsupportedOutput: "離線模型輸出格式不符合預期，請重新匯出模型。"
        }
    }
}

struct OnDeviceRecognitionService {
    private let plateDetector: CoreMLModel
    private let plateOCR: CoreMLModel
    private let viewClassifier: CoreMLModel

    // The app uses its compiled bundle resources. An explicit directory also
    // allows the same app pipeline to be validated with exported packages.
    init(modelDirectory: URL? = nil, computeUnits: MLComputeUnits = .all) {
        plateDetector = CoreMLModel(name: "PlateDetector", directory: modelDirectory, computeUnits: computeUnits)
        plateOCR = CoreMLModel(name: "PlateOCR", version: "2.0", directory: modelDirectory, computeUnits: computeUnits)
        viewClassifier = CoreMLModel(name: "ViewClassifier", directory: modelDirectory, computeUnits: computeUnits)
    }

    func evaluate(
        image: RecognitionImage,
        expectedPlate: String,
        expectedView: VehicleView
    ) async -> LocalInspectionResult {
        var plateText: String?
        var plateConfidence: Double?
        var detectedView: VehicleView?
        var viewConfidence: Double?
        do {
#if canImport(UIKit)
            guard let sourceImage = image.cgImage else {
                throw RecognitionError.lowResolution
            }
            // cgImage contains sensor pixels; UIImage keeps their display
            // orientation separately. Normalize once so detection, cropping,
            // OCR and view classification all use the same coordinate space.
            let cgImage = try Self.uprightCGImage(
                sourceImage,
                orientation: Self.exifOrientation(image.imageOrientation)
            )
#elseif canImport(AppKit)
            guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
                throw RecognitionError.lowResolution
            }
#endif
            guard cgImage.width >= 640, cgImage.height >= 480 else {
                throw RecognitionError.lowResolution
            }

            let detector = try plateDetector.load()
            let detection = try await detectPlate(in: cgImage, model: detector)
            let crop = try crop(cgImage, rect: detection.boundingBox)
            let plate = try recognizePlate(in: crop)
            plateText = plate.text
            plateConfidence = plate.confidence
            let normalizedExpected = normalize(expectedPlate)

            guard normalize(plate.text) == normalizedExpected else {
                throw RecognitionError.wrongPlate(expected: expectedPlate, actual: plate.text)
            }

            let view = try recognizeView(in: cgImage)
            detectedView = VehicleView(rawValue: view.label)
            viewConfidence = view.confidence
            guard view.label == expectedView.rawValue else {
                throw RecognitionError.wrongView(expected: expectedView, actual: view.label)
            }

            return LocalInspectionResult(
                passed: true,
                plateText: plate.text,
                plateConfidence: plate.confidence,
                detectedView: expectedView,
                viewConfidence: view.confidence,
                errors: [],
                modelVersions: modelVersions
            )
        } catch {
            return LocalInspectionResult(
                passed: false,
                plateText: plateText,
                plateConfidence: plateConfidence,
                detectedView: detectedView,
                viewConfidence: viewConfidence,
                errors: [error.localizedDescription],
                modelVersions: modelVersions
            )
        }
    }

    private var modelVersions: [String: String] {
        [
            "plate_detector": plateDetector.version,
            "plate_ocr": plateOCR.version,
            "view_classifier": viewClassifier.version
        ]
    }

    static func uprightCGImage(
        _ image: CGImage,
        orientation: CGImagePropertyOrientation
    ) throws -> CGImage {
        guard orientation != .up else { return image }
        let oriented = CIImage(cgImage: image).oriented(orientation)
        guard let result = CIContext().createCGImage(oriented, from: oriented.extent) else {
            throw RecognitionError.lowResolution
        }
        return result
    }

#if canImport(UIKit)
    private static func exifOrientation(_ orientation: UIImage.Orientation) -> CGImagePropertyOrientation {
        // UIKit and EXIF use different raw values, so map each case explicitly.
        switch orientation {
        case .up: .up
        case .upMirrored: .upMirrored
        case .down: .down
        case .downMirrored: .downMirrored
        case .left: .left
        case .leftMirrored: .leftMirrored
        case .right: .right
        case .rightMirrored: .rightMirrored
        @unknown default: .up
        }
    }
#endif

    private func detectPlate(in image: CGImage, model: MLModel) async throws -> VNRecognizedObjectObservation {
        let visionModel = try VNCoreMLModel(for: model)
        return try await withCheckedThrowingContinuation { continuation in
            let request = VNCoreMLRequest(model: visionModel) { request, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                guard let observations = request.results as? [VNRecognizedObjectObservation] else {
                    continuation.resume(throwing: RecognitionError.unsupportedOutput)
                    return
                }
                guard let observation = observations.max(by: { $0.confidence < $1.confidence }),
                      observation.confidence >= 0.25 else {
                    continuation.resume(throwing: RecognitionError.noPlate)
                    return
                }
                continuation.resume(returning: observation)
            }
            request.imageCropAndScaleOption = .scaleFill
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    try VNImageRequestHandler(cgImage: image).perform([request])
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    private func crop(_ image: CGImage, rect: CGRect) throws -> CGImage {
        let width = CGFloat(image.width)
        let height = CGFloat(image.height)
        let padded = rect.insetBy(dx: -rect.width * 0.08, dy: -rect.height * 0.08)
        let crop = CGRect(
            x: padded.minX * width,
            y: (1 - padded.maxY) * height,
            width: padded.width * width,
            height: padded.height * height
        ).integral.intersection(CGRect(x: 0, y: 0, width: width, height: height))
        guard let result = image.cropping(to: crop), !crop.isEmpty else {
            throw RecognitionError.noPlate
        }
        return result
    }

    private func recognizePlate(in image: CGImage) throws -> (text: String, confidence: Double) {
        let model = try plateOCR.load()
        guard let input = model.modelDescription.inputDescriptionsByName.values.first(where: { $0.type == .image }),
              let constraint = input.imageConstraint else {
            throw RecognitionError.unsupportedOutput
        }
        let buffer = try pixelBuffer(from: image, size: CGSize(width: constraint.pixelsWide, height: constraint.pixelsHigh))
        let provider = try MLDictionaryFeatureProvider(dictionary: [input.name: buffer])
        let output = try model.prediction(from: provider)
        guard let array = output.featureNames.compactMap({ output.featureValue(for: $0)?.multiArrayValue })
            .first(where: { $0.shape.map(\.intValue) == [1, 10, 37] }) else {
            throw RecognitionError.unsupportedOutput
        }
        return try decodePlate(array)
    }

    private func decodePlate(_ output: MLMultiArray) throws -> (text: String, confidence: Double) {
        let alphabet = Array("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_")
        let slots = 10
        let classes = alphabet.count
        guard output.shape.map(\.intValue) == [1, slots, classes] else { throw RecognitionError.unsupportedOutput }

        var result = ""
        var confidences: [Double] = []
        for slot in 0..<slots {
            let values = (0..<classes).map { output[[0, NSNumber(value: slot), NSNumber(value: $0)]].doubleValue }
            guard values.allSatisfy(\.isFinite),
                  values.allSatisfy({ $0 >= -0.001 && $0 <= 1.001 }),
                  abs(values.reduce(0, +) - 1) < 0.02 else {
                throw RecognitionError.unsupportedOutput
            }
            let best = values.enumerated().max(by: { $0.element < $1.element })!
            // CCT already returns probabilities; applying softmax again would
            // turn near-certain characters into misleadingly low confidence.
            let character = alphabet[best.offset]
            if character != "_" {
                result.append(character)
                confidences.append(best.element)
            }
        }
        guard !result.isEmpty, !confidences.isEmpty else { throw RecognitionError.unreadablePlate }
        return (formatPlate(result), confidences.reduce(0, +) / Double(confidences.count))
    }

    private func recognizeView(in image: CGImage) throws -> (label: String, confidence: Double) {
        let model = try viewClassifier.load()
        let buffer = try letterboxedPixelBuffer(from: image, size: 224)
        guard let inputName = model.modelDescription.inputDescriptionsByName.keys.first else {
            throw RecognitionError.unsupportedOutput
        }
        let provider = try MLDictionaryFeatureProvider(dictionary: [inputName: buffer])
        let output = try model.prediction(from: provider)
        guard let logits = output.featureNames.compactMap({ output.featureValue(for: $0)?.multiArrayValue })
            .max(by: { $0.count < $1.count }), logits.count == VehicleView.allCases.count else {
            throw RecognitionError.unsupportedOutput
        }
        let values = (0..<logits.count).map { logits[$0].doubleValue }
        guard let best = values.enumerated().max(by: { $0.element < $1.element }) else {
            throw RecognitionError.unsupportedOutput
        }
        let maxValue = values.max() ?? 0
        let denominator = values.reduce(0) { $0 + exp($1 - maxValue) }
        let confidence = exp(best.element - maxValue) / denominator
        guard confidence >= 0.6 else { throw RecognitionError.unsupportedOutput }
        return (VehicleView.allCases[best.offset].rawValue, confidence)
    }

    private func pixelBuffer(from image: CGImage, size: CGSize) throws -> CVPixelBuffer {
        var buffer: CVPixelBuffer?
        CVPixelBufferCreate(
            kCFAllocatorDefault, Int(size.width), Int(size.height),
            kCVPixelFormatType_32ARGB, nil, &buffer
        )
        guard let buffer else { throw RecognitionError.unsupportedOutput }
        CVPixelBufferLockBaseAddress(buffer, [])
        defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
        guard let context = CGContext(
            data: CVPixelBufferGetBaseAddress(buffer),
            width: Int(size.width), height: Int(size.height),
            bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue
        ) else { throw RecognitionError.unsupportedOutput }
        context.interpolationQuality = .medium
        context.draw(image, in: CGRect(origin: .zero, size: size))
        return buffer
    }

    private func letterboxedPixelBuffer(from image: CGImage, size: Int) throws -> CVPixelBuffer {
        var buffer: CVPixelBuffer?
        CVPixelBufferCreate(kCFAllocatorDefault, size, size, kCVPixelFormatType_32ARGB, nil, &buffer)
        guard let buffer else { throw RecognitionError.unsupportedOutput }
        CVPixelBufferLockBaseAddress(buffer, [])
        defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
        guard let context = CGContext(
            data: CVPixelBufferGetBaseAddress(buffer), width: size, height: size,
            bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue
        ) else { throw RecognitionError.unsupportedOutput }
        context.setFillColor(red: 114.0 / 255.0, green: 114.0 / 255.0, blue: 114.0 / 255.0, alpha: 1)
        context.fill(CGRect(x: 0, y: 0, width: size, height: size))
        let scale = min(CGFloat(size) / CGFloat(image.width), CGFloat(size) / CGFloat(image.height))
        let drawSize = CGSize(width: CGFloat(image.width) * scale, height: CGFloat(image.height) * scale)
        let origin = CGPoint(x: (CGFloat(size) - drawSize.width) / 2, y: (CGFloat(size) - drawSize.height) / 2)
        context.interpolationQuality = .medium
        context.draw(image, in: CGRect(origin: origin, size: drawSize))
        return buffer
    }

    private func normalize(_ plate: String) -> String {
        plate.uppercased().filter { $0.isLetter || $0.isNumber }
    }

    private func formatPlate(_ plate: String) -> String {
        if plate.range(of: "^[A-Z]{3}[0-9]{4}$", options: .regularExpression) != nil {
            return "\(plate.prefix(3))-\(plate.suffix(4))"
        }
        if plate.range(of: "^[0-9]{4}[A-Z]{2}$", options: .regularExpression) != nil {
            return "\(plate.prefix(4))-\(plate.suffix(2))"
        }
        return plate
    }
}

private struct CoreMLModel {
    let name: String
    var version = "1.0"
    var directory: URL?
    var computeUnits: MLComputeUnits = .all

    func load() throws -> MLModel {
        let url: URL
        if let directory {
            let compiled = directory.appendingPathComponent("\(name).mlmodelc")
            let package = directory.appendingPathComponent("\(name).mlpackage")
            if FileManager.default.fileExists(atPath: compiled.path) {
                url = compiled
            } else if FileManager.default.fileExists(atPath: package.path) {
                url = try MLModel.compileModel(at: package)
            } else { throw RecognitionError.modelMissing(name) }
        } else {
            guard let bundled = Bundle.main.url(forResource: name, withExtension: "mlmodelc") else {
                throw RecognitionError.modelMissing(name)
            }
            url = bundled
        }
        let configuration = MLModelConfiguration()
        configuration.computeUnits = computeUnits
        return try MLModel(contentsOf: url, configuration: configuration)
    }
}

import CoreImage
import CoreML
import Foundation
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

struct ValidationCheck: Codable, Equatable, Identifiable {
    let label: String
    let passed: Bool
    var id: String { label }
}

struct LocalInspectionResult: Codable, Equatable {
    let passed: Bool
    let plateText: String?
    let plateConfidence: Double?
    let detectedView: VehicleView?
    let viewConfidence: Double?
    let errors: [String]
    let modelVersions: [String: String]
    /// 拍攝端逐項檢核（畫面清晰／角度／車牌／完整性），UI 用 ✓ ✗ 呈現。舊版存檔沒有這些欄位。
    var checks: [ValidationCheck]? = nil
    var failureTitle: String? = nil
    var failureHint: String? = nil

    static func failure(title: String, reason: String, hint: String?, checks: [ValidationCheck], modelVersions: [String: String]) -> LocalInspectionResult {
        LocalInspectionResult(
            passed: false, plateText: nil, plateConfidence: nil, detectedView: nil, viewConfidence: nil,
            errors: [reason], modelVersions: modelVersions, checks: checks, failureTitle: title, failureHint: hint
        )
    }
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

    /// 給 UI 的標題／提示（為什麼要重拍、怎麼拍）。
    var failureTitle: String {
        switch self {
        case .noPlate, .unreadablePlate, .wrongPlate: "車牌需要重新拍攝"
        case .wrongView: "拍攝角度不正確"
        case .lowResolution: "照片需要重拍"
        case .modelMissing, .unsupportedOutput: "離線模型無法使用"
        }
    }

    var failureHint: String? {
        switch self {
        case .noPlate, .unreadablePlate: "請靠近一點，讓車牌清楚入鏡後重新拍攝。"
        case .wrongPlate: "請確認拍攝的是本次租約的車輛。"
        case .wrongView(let expected, _): "請移動至車輛\(expected.rawValue)方重新拍攝。"
        case .lowResolution: "請保持手機穩定並重新拍攝。"
        case .modelMissing, .unsupportedOutput: nil
        }
    }

    /// 逐項檢核：哪一項沒過。
    func checks(expectedPlate: String) -> [ValidationCheck] {
        let plateOK: Bool
        switch self { case .noPlate, .unreadablePlate, .wrongPlate: plateOK = false; default: plateOK = true }
        let viewOK: Bool
        switch self { case .wrongView: viewOK = false; default: viewOK = true }
        let clearOK: Bool
        switch self { case .lowResolution: clearOK = false; default: clearOK = true }
        return [
            ValidationCheck(label: "畫面清晰", passed: clearOK),
            ValidationCheck(label: "拍攝角度正確", passed: viewOK),
            ValidationCheck(label: "車牌 \(expectedPlate)", passed: plateOK),
            ValidationCheck(label: "車輛完整可辨識", passed: plateOK && viewOK),
        ]
    }
}

struct OnDeviceRecognitionService {
    private let plateDetector = CoreMLModel(name: "PlateDetector")
    private let plateOCR = CoreMLModel(name: "PlateOCR")
    private let viewClassifier = CoreMLModel(name: "ViewClassifier")

    func evaluate(
        image: RecognitionImage,
        expectedPlate: String,
        expectedView: VehicleView
    ) async -> LocalInspectionResult {
        do {
#if canImport(UIKit)
            guard let cgImage = image.cgImage else {
                throw RecognitionError.lowResolution
            }
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
            let normalizedExpected = normalize(expectedPlate)

            guard normalize(plate.text) == normalizedExpected else {
                throw RecognitionError.wrongPlate(expected: expectedPlate, actual: plate.text)
            }

            let view = try recognizeView(in: cgImage)
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
                modelVersions: modelVersions,
                checks: [
                    ValidationCheck(label: "畫面清晰", passed: true),
                    ValidationCheck(label: "拍攝角度正確", passed: true),
                    ValidationCheck(label: "車牌 \(plate.text)", passed: true),
                    ValidationCheck(label: "車輛完整可辨識", passed: true),
                ]
            )
        } catch let error as RecognitionError {
            return LocalInspectionResult.failure(
                title: error.failureTitle,
                reason: error.localizedDescription,
                hint: error.failureHint,
                checks: error.checks(expectedPlate: expectedPlate),
                modelVersions: modelVersions
            )
        } catch {
            return LocalInspectionResult.failure(
                title: "照片檢查失敗",
                reason: error.localizedDescription,
                hint: "請重新拍攝。",
                checks: [],
                modelVersions: modelVersions
            )
        }
    }

    /// 車內照：不跑車牌／視角模型，只做解析度與亮度的品質防呆（沿用既有門檻，不另造一套引擎）。
    func evaluateInterior(image: RecognitionImage) -> LocalInspectionResult {
#if canImport(UIKit)
        let cgImage = image.cgImage
#else
        let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil)
#endif
        let versions = modelVersions.merging(["interior_guard": "resolution+brightness/1.0"]) { $1 }
        guard let cgImage, cgImage.width >= 640, cgImage.height >= 480 else {
            return .failure(
                title: "照片需要重拍", reason: RecognitionError.lowResolution.localizedDescription,
                hint: "請保持手機穩定並重新拍攝。",
                checks: [ValidationCheck(label: "畫面清晰", passed: false), ValidationCheck(label: "光線充足", passed: true)],
                modelVersions: versions
            )
        }
        let brightness = meanLuminance(of: cgImage)
        guard brightness > 0.08 else {
            return .failure(
                title: "照片太暗", reason: "車內光線不足，無法辨識座艙狀況",
                hint: "請開啟車內燈或車門後重新拍攝。",
                checks: [ValidationCheck(label: "畫面清晰", passed: true), ValidationCheck(label: "光線充足", passed: false)],
                modelVersions: versions
            )
        }
        return LocalInspectionResult(
            passed: true, plateText: nil, plateConfidence: nil, detectedView: nil, viewConfidence: nil,
            errors: [], modelVersions: versions,
            checks: [ValidationCheck(label: "畫面清晰", passed: true), ValidationCheck(label: "光線充足", passed: true),
                     ValidationCheck(label: "座艙完整可辨識", passed: true)]
        )
    }

    private func meanLuminance(of image: CGImage) -> Double {
        let size = 32
        guard let buffer = try? pixelBuffer(from: image, size: CGSize(width: size, height: size)) else { return 1 }
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { return 1 }
        let bytesPerRow = CVPixelBufferGetBytesPerRow(buffer)
        var total = 0.0
        for y in 0..<size {
            let row = base.advanced(by: y * bytesPerRow).assumingMemoryBound(to: UInt8.self)
            for x in 0..<size {
                let r = Double(row[x * 4 + 1]), g = Double(row[x * 4 + 2]), b = Double(row[x * 4 + 3])
                total += (0.299 * r + 0.587 * g + 0.114 * b) / 255
            }
        }
        return total / Double(size * size)
    }

    private var modelVersions: [String: String] {
        [
            "plate_detector": plateDetector.version,
            "plate_ocr": plateOCR.version,
            "view_classifier": viewClassifier.version
        ]
    }

    private func detectPlate(in image: CGImage, model: MLModel) async throws -> VNRecognizedObjectObservation {
        let visionModel = try VNCoreMLModel(for: model)
        return try await withCheckedThrowingContinuation { continuation in
            let request = VNCoreMLRequest(model: visionModel) { request, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                guard let observation = (request.results as? [VNRecognizedObjectObservation])?
                    .max(by: { $0.confidence < $1.confidence }),
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
        let paddingX = rect.width * 0.08
        let paddingY = rect.height * 0.08
        let crop = CGRect(
            x: max(0, rect.minX - paddingX) * width,
            y: max(0, 1 - rect.maxY - paddingY) * height,
            width: min(1, rect.width + paddingX * 2) * width,
            height: min(1, rect.height + paddingY * 2) * height
        ).integral.intersection(CGRect(x: 0, y: 0, width: width, height: height))
        guard let result = image.cropping(to: crop), !crop.isEmpty else {
            throw RecognitionError.noPlate
        }
        return result
    }

    private func recognizePlate(in image: CGImage) throws -> (text: String, confidence: Double) {
        let model = try plateOCR.load()
        let buffer = try pixelBuffer(from: image, size: CGSize(width: 128, height: 64))
        guard let inputName = model.modelDescription.inputDescriptionsByName.keys.first else {
            throw RecognitionError.unsupportedOutput
        }
        let provider = try MLDictionaryFeatureProvider(dictionary: [inputName: buffer])
        let output = try model.prediction(from: provider)
        guard let array = output.featureNames.compactMap({ output.featureValue(for: $0)?.multiArrayValue })
            .max(by: { $0.count < $1.count }) else {
            throw RecognitionError.unsupportedOutput
        }
        return try decodePlate(array)
    }

    private func decodePlate(_ output: MLMultiArray) throws -> (text: String, confidence: Double) {
        let alphabet = Array("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_")
        let slots = 10
        let classes = alphabet.count
        guard output.count == slots * classes else { throw RecognitionError.unsupportedOutput }

        var result = ""
        var confidences: [Double] = []
        for slot in 0..<slots {
            let values = (0..<classes).map { output[slot * classes + $0].doubleValue }
            let best = values.enumerated().max(by: { $0.element < $1.element })!
            let maxValue = values.max()!
            let sum = values.reduce(0) { $0 + exp($1 - maxValue) }
            let confidence = exp(best.element - maxValue) / sum
            let character = alphabet[best.offset]
            if character != "_" {
                result.append(character)
                confidences.append(confidence)
            }
        }
        guard result.count == 7, !confidences.isEmpty else { throw RecognitionError.unreadablePlate }
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
        let characters = Array(plate)
        return "\(String(characters.prefix(3)))-\(String(characters.suffix(4)))"
    }
}

private struct CoreMLModel {
    let name: String
    let version = "1.0"

    func load() throws -> MLModel {
        guard let url = Bundle.main.url(forResource: name, withExtension: "mlmodelc") else {
            throw RecognitionError.modelMissing(name)
        }
        let configuration = MLModelConfiguration()
        configuration.computeUnits = .all
        return try MLModel(contentsOf: url, configuration: configuration)
    }
}

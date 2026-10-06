// Run on macOS with Xcode Command Line Tools:
// swift validate_coreml_detector.swift PlateDetector.mlpackage photo.jpg
import CoreImage
import CoreML
import Foundation
import ImageIO
import Vision

enum ValidationError: Error, CustomStringConvertible {
    case invalidImage
    case unsupportedOutput
    case noPlate
    case invalidArguments(String)
    case invalidOCR(String)

    var description: String {
        switch self {
        case .invalidImage: "Cannot decode the input photo."
        case .unsupportedOutput: "Expected Vision object detections. Export with nms=True."
        case .noPlate: "No plate above confidence 0.25."
        case .invalidArguments(let message): message
        case .invalidOCR(let message): "OCR: \(message)"
        }
    }
}

func option(_ name: String) throws -> String? {
    guard let index = CommandLine.arguments.firstIndex(of: name) else { return nil }
    guard index + 1 < CommandLine.arguments.count,
          !CommandLine.arguments[index + 1].hasPrefix("--") else {
        throw ValidationError.invalidArguments("Missing value after \(name).")
    }
    return CommandLine.arguments[index + 1]
}

func plateCrop(_ image: CGImage, box: CGRect) throws -> CGImage {
    // Vision uses a normalized bottom-left origin; CGImage cropping uses top-left.
    let padded = box.insetBy(dx: -box.width * 0.08, dy: -box.height * 0.08)
    let rect = CGRect(
        x: padded.minX * CGFloat(image.width),
        y: (1 - padded.maxY) * CGFloat(image.height),
        width: padded.width * CGFloat(image.width),
        height: padded.height * CGFloat(image.height)
    ).integral.intersection(CGRect(x: 0, y: 0, width: image.width, height: image.height))
    guard !rect.isEmpty, let crop = image.cropping(to: rect) else {
        throw ValidationError.invalidImage
    }
    return crop
}

func recognizePlate(_ crop: CGImage, modelURL: URL, configuration: MLModelConfiguration) throws {
    let compiled = modelURL.pathExtension == "mlmodelc" ? modelURL : try MLModel.compileModel(at: modelURL)
    let model = try MLModel(contentsOf: compiled, configuration: configuration)
    guard let input = model.modelDescription.inputDescriptionsByName.values.first(where: { $0.type == .image }),
          let constraint = input.imageConstraint else {
        throw ValidationError.invalidOCR("Expected an image input.")
    }
    var buffer: CVPixelBuffer?
    let status = CVPixelBufferCreate(kCFAllocatorDefault, constraint.pixelsWide, constraint.pixelsHigh,
                                    kCVPixelFormatType_32ARGB, nil, &buffer)
    guard status == kCVReturnSuccess, let buffer else {
        throw ValidationError.invalidOCR("Cannot create pixel buffer.")
    }
    CVPixelBufferLockBaseAddress(buffer, [])
    guard let context = CGContext(data: CVPixelBufferGetBaseAddress(buffer),
                                  width: constraint.pixelsWide, height: constraint.pixelsHigh,
                                  bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
                                  space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue) else {
        CVPixelBufferUnlockBaseAddress(buffer, [])
        throw ValidationError.invalidOCR("Cannot resize plate.")
    }
    context.interpolationQuality = .medium
    context.draw(crop, in: CGRect(x: 0, y: 0, width: constraint.pixelsWide, height: constraint.pixelsHigh))
    CVPixelBufferUnlockBaseAddress(buffer, [])
    let output = try model.prediction(from: MLDictionaryFeatureProvider(dictionary: [input.name: buffer]))
    let alphabet = Array("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_")
    // The supplied CCT model returns plate probabilities [1,10,37] and a
    // separate region output. Select by shape, not arbitrary feature ordering.
    guard let probabilities = output.featureNames.compactMap({ output.featureValue(for: $0)?.multiArrayValue })
        .first(where: { $0.shape.map(\.intValue) == [1, 10, alphabet.count] }) else {
        throw ValidationError.invalidOCR("Expected plate output shape [1,10,37].")
    }
    var text = ""
    var confidences: [Double] = []
    for slot in 0..<10 {
        let values = (0..<alphabet.count).map { probabilities[[0, NSNumber(value: slot), NSNumber(value: $0)]].doubleValue }
        guard values.allSatisfy(\.isFinite),
              values.allSatisfy({ $0 >= -0.001 && $0 <= 1.001 }),
              abs(values.reduce(0, +) - 1) < 0.02 else {
            throw ValidationError.invalidOCR("Expected normalized character probabilities.")
        }
        let best = values.enumerated().max { $0.element < $1.element }!
        let character = alphabet[best.offset]
        if character != "_" {
            text.append(character)
            confidences.append(best.element)
        }
    }
    guard !text.isEmpty else { throw ValidationError.invalidOCR("No characters recognized.") }
    let formatted: String
    if text.range(of: "^[A-Z]{3}[0-9]{4}$", options: .regularExpression) != nil {
        formatted = "\(text.prefix(3))-\(text.suffix(4))"
    } else if text.range(of: "^[0-9]{4}[A-Z]{2}$", options: .regularExpression) != nil {
        formatted = "\(text.prefix(4))-\(text.suffix(2))"
    } else { formatted = text }
    print("OCR plate: \(formatted)")
    print("OCR mean character confidence: \(confidences.reduce(0, +) / Double(confidences.count))")
    print("OCR character confidences: \(confidences)")
    if let expected = try option("--expect-plate") {
        let normalized = expected.uppercased().filter { $0.isLetter || $0.isNumber }
        guard text == normalized else {
            throw ValidationError.invalidOCR("Expected \(expected), got \(formatted).")
        }
        print("Expected plate: PASS")
    }
}

func validate() throws {
    guard CommandLine.arguments.count >= 3 else {
        print("Usage: swift validate_coreml_detector.swift MODEL.mlpackage PHOTO [--ocr OCR.mlpackage] [--save-crop plate.png] [--expect-plate TEXT] [--ignore-orientation] [--cpu-only]")
        exit(1)
    }
    let modelURL = URL(fileURLWithPath: CommandLine.arguments[1])
    let photoURL = URL(fileURLWithPath: CommandLine.arguments[2])
    guard let source = CGImageSourceCreateWithURL(photoURL as CFURL, nil),
          let rawImage = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        throw ValidationError.invalidImage
    }
    let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any]
    let exif = (properties?[kCGImagePropertyOrientation] as? NSNumber)?.uint32Value ?? 1
    guard let orientation = CGImagePropertyOrientation(rawValue: exif) else {
        throw ValidationError.invalidImage
    }
    let ignoreOrientation = CommandLine.arguments.contains("--ignore-orientation")
    let image: CGImage
    if ignoreOrientation || orientation == .up {
        image = rawImage
    } else {
        let oriented = CIImage(cgImage: rawImage).oriented(orientation)
        guard let rendered = CIContext().createCGImage(oriented, from: oriented.extent) else {
            throw ValidationError.invalidImage
        }
        image = rendered
    }
    print("EXIF orientation: \(exif); apply orientation: \(!ignoreOrientation)")
    print("Stored pixels: \(rawImage.width)x\(rawImage.height); model photo: \(image.width)x\(image.height)")

    let compiled = modelURL.pathExtension == "mlmodelc" ? modelURL : try MLModel.compileModel(at: modelURL)
    let configuration = MLModelConfiguration()
    configuration.computeUnits = CommandLine.arguments.contains("--cpu-only") ? .cpuOnly : .all
    let model = try MLModel(contentsOf: compiled, configuration: configuration)
    let request = VNCoreMLRequest(model: try VNCoreMLModel(for: model))
    // Match the app; normalization happens before detection and cropping.
    request.imageCropAndScaleOption = .scaleFill
    try VNImageRequestHandler(cgImage: image, orientation: .up).perform([request])
    guard let objects = request.results as? [VNRecognizedObjectObservation] else {
        throw ValidationError.unsupportedOutput
    }
    let detections = objects.filter { $0.confidence >= 0.25 }
        .sorted { $0.confidence > $1.confidence }
    print("Detections above 0.25: \(detections.count)")
    for object in detections {
        print("label=\(object.labels.first?.identifier ?? "unknown") confidence=\(object.confidence) box=\(object.boundingBox)")
    }
    guard !detections.isEmpty else { throw ValidationError.noPlate }
    let ocrPath = try option("--ocr")
    let cropPath = try option("--save-crop")
    if try option("--expect-plate") != nil && ocrPath == nil {
        throw ValidationError.invalidArguments("--expect-plate requires --ocr.")
    }
    if ocrPath != nil || cropPath != nil {
        let crop = try plateCrop(image, box: detections[0].boundingBox)
        print("Plate crop: \(crop.width)x\(crop.height) (highest-confidence detection)")
        if let cropPath {
            let url = URL(fileURLWithPath: cropPath)
            guard let destination = CGImageDestinationCreateWithURL(url as CFURL, "public.png" as CFString, 1, nil) else {
                throw ValidationError.invalidImage
            }
            CGImageDestinationAddImage(destination, crop, nil)
            guard CGImageDestinationFinalize(destination) else { throw ValidationError.invalidImage }
            print("Saved plate crop: \(url.path)")
        }
        if let ocrPath {
            try recognizePlate(crop, modelURL: URL(fileURLWithPath: ocrPath), configuration: configuration)
        }
    }
}

do {
    try validate()
} catch {
    fputs("Validation failed: \(error)\n", stderr)
    exit(2)
}

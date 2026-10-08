import Foundation
import UIKit

/// 拍攝端驗證入口：正常模式走真實 Core ML（`OnDeviceRecognitionService`），
/// Demo 模式走 `DemoCaptureScenario` 的固定劇本。兩條路徑回傳同一種 `LocalInspectionResult`，
/// 後端以 `validation_mode` 分辨。Demo 不會取代真實模型，只是可切換的另一條路。
struct CaptureValidator {
    let demoMode: Bool

    func validate(image: UIImage, rental: Rental, stage: InspectionStage, shot: InspectionShot, attempt: Int,
                  options: CaptureOptions = CaptureOptions()) async -> LocalInspectionResult {
        if demoMode {
            return DemoCaptureScenario.result(rental: rental, stage: stage, shot: shot, attempt: attempt)
        }
        let recognizer = OnDeviceRecognitionService()
        if let view = shot.exteriorView {
            return await recognizer.evaluate(image: image, expectedPlate: rental.plateNumber, expectedView: view, options: options)
        }
        return recognizer.evaluateInterior(image: image)
    }
}

/// 比賽 Demo 劇本（deterministic）：
///   取車 左前 第一次 → 畫面模糊（重拍通過）；還車 右後 第一次 → 角度／距離不對（重拍通過）；其餘一律通過。
/// 集中在這裡，不把 `if plate == ABC-1234` 散落各處。
enum DemoCaptureScenario {
    static let mode = "demo"

    static func result(rental: Rental, stage: InspectionStage, shot: InspectionShot, attempt: Int) -> LocalInspectionResult {
        let versions = ["mode": mode, "scenario": "competition-2026.10"]
        if attempt <= 1 {
            switch (stage, shot) {
            case (.pickup, .leftFront):
                return .failure(
                    title: "照片需要重拍",
                    reason: "畫面過於模糊",
                    hint: "請保持手機穩定並重新拍攝。",
                    checks: [.init(label: "畫面清晰", passed: false), .init(label: "拍攝角度正確", passed: true),
                             .init(label: "車牌 \(rental.plateNumber)", passed: true), .init(label: "車輛完整可辨識", passed: true)],
                    modelVersions: versions
                )
            case (.return, .rightRear):
                return .failure(
                    title: "拍攝角度不正確",
                    reason: "距離太近，車身右後角未完整入鏡",
                    hint: "請移動至車輛右後方約 2–3 公尺處重新拍攝。",
                    checks: [.init(label: "畫面清晰", passed: true), .init(label: "拍攝角度正確", passed: false),
                             .init(label: "車牌 \(rental.plateNumber)", passed: true), .init(label: "車輛完整可辨識", passed: false)],
                    modelVersions: versions
                )
            default:
                break
            }
        }
        if shot.isInterior {
            return LocalInspectionResult(
                passed: true, plateText: nil, plateConfidence: nil, detectedView: nil, viewConfidence: nil,
                errors: [], modelVersions: versions,
                checks: [.init(label: "畫面清晰", passed: true), .init(label: "光線充足", passed: true),
                         .init(label: "座艙完整可辨識", passed: true)],
                failureTitle: nil, failureHint: nil
            )
        }
        return LocalInspectionResult(
            passed: true, plateText: rental.plateNumber, plateConfidence: 0.97,
            detectedView: shot.exteriorView, viewConfidence: 0.93,
            errors: [], modelVersions: versions,
            checks: [.init(label: "畫面清晰", passed: true), .init(label: "拍攝角度正確", passed: true),
                     .init(label: "車牌 \(rental.plateNumber)", passed: true), .init(label: "車輛完整可辨識", passed: true)],
            failureTitle: nil, failureHint: nil
        )
    }
}

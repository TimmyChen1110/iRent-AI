import Foundation

/// 對應 backend `schemas.BrightnessDebug`
struct BrightnessDebug: Codable, Sendable {
    let mean: Double
    let std: Double
    let darkRatio: Double
    let brightRatio: Double
}

/// 對應 backend `schemas.ViewProbability`
struct ViewProbability: Codable, Identifiable, Sendable {
    let label: String       // iRent 命名，例如「左前」
    let probability: Double
    var id: String { label }
}

/// 對應 backend `schemas.DebugInfo`
struct DebugInfo: Codable, Sendable {
    var stagesRun: [String] = []
    var blurScore: Double? = nil
    var brightness: BrightnessDebug? = nil
    var stage1Advisories: [String] = []
    /// 方向防護網套用的逆時針角度（0 / 90 / 270）。不是 0 時 plateBbox 是「轉正後」的座標。
    var orientationRotation: Int = 0
    /// [x1, y1, x2, y2]，像素座標
    var plateBbox: [Int]? = nil
    var plateAreaRatio: Double? = nil
    var plateDetectConfidence: Double? = nil
    var viewModelLabel: String? = nil
    var viewProbabilities: [ViewProbability]? = nil
    var exteriorInteriorGuess: String? = nil
    var exteriorInteriorConfidence: Double? = nil
    let elapsedMs: Double

    /// backend 的 list/int 欄位有 default，正常一定會送；這裡對缺鍵也寬容，避免 schema 微調時整包解不開。
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        stagesRun = try c.decodeIfPresent([String].self, forKey: .stagesRun) ?? []
        blurScore = try c.decodeIfPresent(Double.self, forKey: .blurScore)
        brightness = try c.decodeIfPresent(BrightnessDebug.self, forKey: .brightness)
        stage1Advisories = try c.decodeIfPresent([String].self, forKey: .stage1Advisories) ?? []
        orientationRotation = try c.decodeIfPresent(Int.self, forKey: .orientationRotation) ?? 0
        plateBbox = try c.decodeIfPresent([Int].self, forKey: .plateBbox)
        plateAreaRatio = try c.decodeIfPresent(Double.self, forKey: .plateAreaRatio)
        plateDetectConfidence = try c.decodeIfPresent(Double.self, forKey: .plateDetectConfidence)
        viewModelLabel = try c.decodeIfPresent(String.self, forKey: .viewModelLabel)
        viewProbabilities = try c.decodeIfPresent([ViewProbability].self, forKey: .viewProbabilities)
        exteriorInteriorGuess = try c.decodeIfPresent(String.self, forKey: .exteriorInteriorGuess)
        exteriorInteriorConfidence = try c.decodeIfPresent(Double.self, forKey: .exteriorInteriorConfidence)
        elapsedMs = try c.decodeIfPresent(Double.self, forKey: .elapsedMs) ?? 0
    }
}

/// 對應 backend `schemas.PhotoQualityCheckResponse`
struct PhotoQualityResponse: Codable, Sendable {
    let passed: Bool
    let qualityScore: Double
    var requiredView: RequiredView? = nil
    var plateText: String? = nil
    var plateConfidence: Double? = nil
    var detectedView: String? = nil
    var viewConfidence: Double? = nil
    var stages: [StageResult] = []
    let errors: [QualityErrorItem]
    let debug: DebugInfo

    // MARK: - 便利存取

    var firstFailedStage: StageResult? { stages.first { $0.status == .failed } }
    var skippedStages: [StageResult] { stages.filter { $0.status == .skipped } }
    /// 0–100 的顯示用分數
    var qualityScore100: Int { Int((qualityScore * 100).rounded()) }

    /// 每個錯誤碼補一句「為什麼」，跟 backend ERROR_MESSAGES（講要做什麼）互補。與 Web 版 ERROR_HINTS 相同。
    static func hint(for code: String) -> String? {
        switch code {
        case "IMAGE_INVALID": return "檔案不是有效的圖片，或整張畫面沒有內容（全黑／全白）。"
        case "LOW_RESOLUTION": return "解析度太低，放大後看不清楚車牌與車損細節。"
        case "IMAGE_BLURRY": return "畫面細節不足，通常是手震或對焦沒完成就按下快門。"
        case "TOO_DARK": return "整體曝光不足，車身與車牌的細節會被暗部吃掉。"
        case "TOO_BRIGHT": return "畫面過曝，白色車身與車牌反光會糊成一片。"
        case "PLATE_NOT_FOUND": return "畫面裡找不到完整車牌——常見原因是車牌被裁到畫面邊緣外。"
        case "TOO_FAR": return "車牌在畫面中佔比太小，放大後會看不清楚號碼。"
        case "TOO_CLOSE": return "拍得太近，車輛與車牌沒有完整入鏡。"
        case "PLATE_TEXT_UNREADABLE": return "車牌位置找得到，但字元辨識信心太低，通常是太糊或角度太斜。"
        case "PLATE_INCOMPLETE": return "讀出來的字數不足，代表車牌的頭或尾被畫面邊緣裁掉了。"
        case "WRONG_VIEW": return "系統判斷的角度跟指定角度不同，可能站錯位置了。"
        case "UNCERTAIN_VIEW": return "畫面資訊不足以判斷是車輛的哪一角，通常是拍太近或只拍到局部。"
        default: return nil
        }
    }

    /// 第 1 關 advisory 的顯示短語（backend 原句 → pill 文案）
    static func advisoryLabel(_ raw: String) -> String {
        switch raw {
        case "照片偏暗": return "光線稍暗"
        case "照片偏亮": return "光線偏亮"
        case "畫面偏模糊": return "畫面稍模糊"
        default: return raw
        }
    }
}

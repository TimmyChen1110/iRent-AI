import Foundation

/// 對應 backend `schemas.QualityErrorResponse`
struct QualityErrorItem: Codable, Hashable, Sendable {
    let code: String
    let message: String
}

enum StageStatus: String, Codable, Sendable {
    case passed, failed, skipped
}

/// 對應 backend `schemas.StageResult`。backend 保證永遠回三筆、順序固定：
/// readability → plate → view。
struct StageResult: Codable, Identifiable, Sendable {
    let id: String          // readability | plate | view
    let name: String        // backend 顯示名稱（技術細節裡用）
    let status: StageStatus
    var errors: [QualityErrorItem] = []
    var summary: String? = nil

    /// App 端的使用者語言名稱
    var displayName: String {
        switch id {
        case "readability": return "基本可讀性"
        case "plate": return "車牌辨識"
        case "view": return "拍攝角度"
        default: return name
        }
    }
}

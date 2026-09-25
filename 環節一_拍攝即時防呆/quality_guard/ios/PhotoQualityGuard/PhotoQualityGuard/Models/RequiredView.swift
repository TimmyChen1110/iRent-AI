import Foundation

/// 對應 backend `app/view_taxonomy.py` 的 `RequiredView`。
/// **rawValue 就是送給 API 的字串，必須與 backend 完全一致，不可改。**
enum RequiredView: String, Codable, CaseIterable, Identifiable, Sendable {
    case leftFront = "左前"
    case rightFront = "右前"
    case leftRear = "左後"
    case rightRear = "右後"
    case frontInterior = "前車內"
    case rearInterior = "後車內"

    var id: String { rawValue }

    /// chip 上的短名稱（跟 API 值相同）
    var chipTitle: String { rawValue }

    /// 畫面上的完整說法（只影響顯示）
    var displayName: String {
        switch self {
        case .leftFront: return "左前方"
        case .rightFront: return "右前方"
        case .leftRear: return "左後方"
        case .rightRear: return "右後方"
        case .frontInterior: return "前座車內"
        case .rearInterior: return "後座車內"
        }
    }

    /// backend 對車內視角只跑第 1 關（Stage 2–4 略過）
    var isExterior: Bool {
        switch self {
        case .leftFront, .rightFront, .leftRear, .rightRear: return true
        case .frontInterior, .rearInterior: return false
        }
    }

    /// 把 backend 回傳的角度字串（例如 detected_view / view_probabilities.label）轉成顯示名稱。
    static func displayName(forAPIValue value: String) -> String {
        RequiredView(rawValue: value)?.displayName ?? value
    }
}

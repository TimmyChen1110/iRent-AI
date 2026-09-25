import Foundation

/// 對應 backend `schemas.PhotoQualityCheckRequest`。
/// 編碼時用 `.convertToSnakeCase`；`nil` 欄位不會出現在 JSON 裡，
/// 所以「不指定角度」＝ `requiredView == nil` ＝ payload 沒有 `required_view`（跟 Web 版一致）。
struct PhotoQualityRequest: Encodable, Sendable {
    var rentalId: String? = nil
    var carId: String? = nil
    var requiredView: RequiredView? = nil
    /// 純 base64（不含 `data:image/...;base64,` 前綴）。backend 兩種都收，Web 版送的是純 base64。
    var imageBase64: String
}

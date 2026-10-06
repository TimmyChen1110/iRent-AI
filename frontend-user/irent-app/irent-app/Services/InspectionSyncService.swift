import Foundation

enum SyncError: LocalizedError {
    case invalidBaseURL
    case server(String)
    /// 後端明確拒絕（4xx）：重試也不會成功，例如取車已結束、租約未登記。
    case rejected(String)

    var errorDescription: String? {
        switch self {
        case .invalidBaseURL: "API 位址無效，請輸入例如 http://192.168.1.10:8000（Mac 的區網 IP，不是 localhost）。"
        case .server(let message), .rejected(let message): message
        }
    }
}

/// 與後端 `/v1/mobile-inspections` 溝通：上傳照片（既有端點，擴充 metadata）、查租約狀態、重新開始 Demo。
struct InspectionSyncService {
    /// 設定頁輸入的位址常見錯誤（少 http://、尾端斜線、空白）在這裡統一修正；`192.168.1.10:8000` 這種沒有 scheme 的輸入
    /// 會被 `URL(string:)` 當成 scheme 而失敗。回 nil 表示無法解析。
    static func normalizedBaseURL(_ raw: String) -> URL? {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        if !text.lowercased().hasPrefix("http://") && !text.lowercased().hasPrefix("https://") {
            text = "http://" + text
        }
        while text.hasSuffix("/") { text.removeLast() }
        guard let url = URL(string: text), let host = url.host(), !host.isEmpty else { return nil }
        return url
    }

    /// 連線檢查：打既有 `GET /api/health`（不需登入）。回伺服器狀態字串，失敗丟錯。
    func checkConnection(baseURL: String) async throws -> String {
        guard let url = Self.normalizedBaseURL(baseURL)?.appending(path: "api/health") else {
            throw SyncError.invalidBaseURL
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 6
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            throw SyncError.server("伺服器回應異常（HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0)）")
        }
        let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        return (object?["status"] as? String) ?? "ok"
    }

    func upload(
        photo: CapturedPhoto,
        rental: Rental,
        imageData: Data,
        baseURL: String
    ) async throws {
        guard let url = Self.normalizedBaseURL(baseURL)?.appending(path: "v1/mobile-inspections/photos") else {
            throw SyncError.invalidBaseURL
        }

        let boundary = "Boundary-\(UUID().uuidString)"
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 30

        var body = Data()
        // 既有欄位（後端 schema 不變）
        append("rental_id", rental.id, to: &body, boundary: boundary)
        append("car_id", rental.vehicleID, to: &body, boundary: boundary)
        append("expected_plate", rental.plateNumber, to: &body, boundary: boundary)
        append("stage", photo.stage.rawValue, to: &body, boundary: boundary)
        append("view", photo.shot.rawValue, to: &body, boundary: boundary)
        append("recognized_plate", photo.result.plateText ?? rental.plateNumber, to: &body, boundary: boundary)
        append("image_sha256", photo.sha256, to: &body, boundary: boundary)
        append("captured_at", ISO8601DateFormatter().string(from: photo.capturedAt), to: &body, boundary: boundary)
        let resultData = try JSONEncoder().encode(photo.result)
        append("local_result_json", String(decoding: resultData, as: UTF8.self), to: &body, boundary: boundary)
        // 本輪新增（選填、向後相容）：讓後端知道這張照片屬於哪筆租約／車輛／檢查／角度，重試不重複建檔
        append("photo_id", photo.id.uuidString, to: &body, boundary: boundary)
        append("vehicle_id", rental.vehicleID, to: &body, boundary: boundary)
        append("inspection_type", photo.stage.inspectionType, to: &body, boundary: boundary)
        append("photo_category", photo.shot.photoCategory, to: &body, boundary: boundary)
        append("angle", photo.shot.angleCode, to: &body, boundary: boundary)
        append("validation_mode", photo.result.modelVersions["mode"] == DemoCaptureScenario.mode ? "demo" : "coreml", to: &body, boundary: boundary)
        appendFile(imageData, name: "photo", filename: photo.fileName, to: &body, boundary: boundary)
        body.append(Data("--\(boundary)--\r\n".utf8))
        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw SyncError.server("無法上傳照片。") }
        guard 200..<300 ~= http.statusCode else {
            let message = Self.detail(from: data) ?? "無法上傳照片。"
            if 400..<500 ~= http.statusCode { throw SyncError.rejected(message) }
            throw SyncError.server(message)
        }
    }

    func status(rental: Rental, baseURL: String) async throws -> RentalRemoteStatus {
        guard let url = Self.normalizedBaseURL(baseURL)?.appending(path: "v1/mobile-inspections/rentals/\(rental.id)") else {
            throw SyncError.invalidBaseURL
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 10
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            throw SyncError.server(Self.detail(from: data) ?? "無法取得租約狀態。")
        }
        return try JSONDecoder().decode(RentalRemoteStatus.self, from: data)
    }

    /// 示範租約重新開始：清掉後端這筆租約的檢查紀錄與衍生案件，讓流程可以重演。
    func restart(rental: Rental, baseURL: String) async throws {
        guard let url = Self.normalizedBaseURL(baseURL)?.appending(path: "v1/mobile-inspections/rentals/\(rental.id)/restart") else {
            throw SyncError.invalidBaseURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 10
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            throw SyncError.server(Self.detail(from: data) ?? "無法重新開始 Demo。")
        }
    }

    private static func detail(from data: Data) -> String? {
        if let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let detail = object["detail"] as? String {
            return detail
        }
        let text = String(decoding: data, as: UTF8.self)
        return text.isEmpty ? nil : text
    }

    private func append(_ name: String, _ value: String, to body: inout Data, boundary: String) {
        body.append(Data("--\(boundary)\r\n".utf8))
        body.append(Data("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n".utf8))
        body.append(Data("\(value)\r\n".utf8))
    }

    private func appendFile(_ data: Data, name: String, filename: String, to body: inout Data, boundary: String) {
        body.append(Data("--\(boundary)\r\n".utf8))
        body.append(Data("Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\n".utf8))
        body.append(Data("Content-Type: image/jpeg\r\n\r\n".utf8))
        body.append(data)
        body.append(Data("\r\n".utf8))
    }
}

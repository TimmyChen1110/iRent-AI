import Foundation

/// 與後端 `/v1/rental-sessions` 溝通：模擬車輛、租車 Session 狀態轉換、AI 檢測結果。
/// 狀態轉換一律由後端驗證；這裡只是把回應解成 `RentalSession` / `InspectionResult`。
struct RentalSessionService {
    struct LocationBody: Encodable {
        let lat: Double
        let lng: Double
        let source: String
    }
    private struct CreateBody: Encodable { let vehicleId: String; let userLocation: LocationBody? }
    private struct InitiateBody: Encodable { let userLocation: LocationBody? }
    private struct ReturnInfoBody: Encodable { let endOdometerKm: Int; let returnLocation: LocationBody? }
    private struct RetryBody: Encodable { let mode: String }
    private struct EmptyBody: Encodable {}
    private struct VehiclesResponse: Decodable { let vehicles: [SimVehicle] }
    private struct ActiveResponse: Decodable { let session: RentalSession? }

    func vehicles(baseURL: String) async throws -> [SimVehicle] {
        try await get("v1/rental-sessions/vehicles", baseURL: baseURL, as: VehiclesResponse.self).vehicles
    }

    func active(baseURL: String) async throws -> RentalSession? {
        try await get("v1/rental-sessions/active", baseURL: baseURL, as: ActiveResponse.self).session
    }

    func get(id: String, baseURL: String) async throws -> RentalSession {
        try await get("v1/rental-sessions/\(id)", baseURL: baseURL, as: RentalSession.self)
    }

    func create(vehicleID: String, location: LocationBody?, baseURL: String) async throws -> RentalSession {
        try await post("v1/rental-sessions", body: CreateBody(vehicleId: vehicleID, userLocation: location), baseURL: baseURL, as: RentalSession.self)
    }

    func pickupComplete(id: String, baseURL: String) async throws -> RentalSession {
        try await post("v1/rental-sessions/\(id)/pickup/complete", body: EmptyBody(), baseURL: baseURL, as: RentalSession.self)
    }

    func initiateReturn(id: String, location: LocationBody?, baseURL: String) async throws -> RentalSession {
        try await post("v1/rental-sessions/\(id)/return/initiate", body: InitiateBody(userLocation: location), baseURL: baseURL, as: RentalSession.self)
    }

    func returnInfo(id: String, endOdometerKm: Int, location: LocationBody?, baseURL: String) async throws -> RentalSession {
        try await post("v1/rental-sessions/\(id)/return/info", body: ReturnInfoBody(endOdometerKm: endOdometerKm, returnLocation: location), baseURL: baseURL, as: RentalSession.self)
    }

    func inspection(id: String, baseURL: String) async throws -> InspectionResult {
        try await get("v1/rental-sessions/\(id)/inspection", baseURL: baseURL, as: InspectionResult.self)
    }

    /// mode: reanalyze（同一批照片重新檢測）| retake（清掉還車照重新拍攝）
    func retry(id: String, mode: String, baseURL: String) async throws -> RentalSession {
        try await post("v1/rental-sessions/\(id)/inspection/retry", body: RetryBody(mode: mode), baseURL: baseURL, as: RentalSession.self)
    }

    func confirmReturn(id: String, baseURL: String) async throws -> RentalSession {
        try await post("v1/rental-sessions/\(id)/confirm-return", body: EmptyBody(), baseURL: baseURL, as: RentalSession.self)
    }

    func cancel(id: String, baseURL: String) async throws -> RentalSession {
        try await post("v1/rental-sessions/\(id)/cancel", body: EmptyBody(), baseURL: baseURL, as: RentalSession.self)
    }

    /// 車況紀錄（已確認屬於本車的借車前／還車後照片）。
    func vehicleRecords(id: String, baseURL: String) async throws -> VehicleRecords {
        try await get("v1/rental-sessions/vehicles/\(id)/records", baseURL: baseURL, as: VehicleRecords.self)
    }

    // MARK: - HTTP

    private func url(_ path: String, baseURL: String) throws -> URL {
        guard let url = InspectionSyncService.normalizedBaseURL(baseURL)?.appending(path: path) else {
            throw SyncError.invalidBaseURL
        }
        return url
    }

    private func get<T: Decodable>(_ path: String, baseURL: String, as type: T.Type) async throws -> T {
        var request = URLRequest(url: try url(path, baseURL: baseURL))
        request.timeoutInterval = 12
        return try await send(request, as: type)
    }

    private func post<T: Decodable, B: Encodable>(_ path: String, body: B, baseURL: String, as type: T.Type) async throws -> T {
        var request = URLRequest(url: try url(path, baseURL: baseURL))
        request.httpMethod = "POST"
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try APICoding.encoder.encode(body)
        return try await send(request, as: type)
    }

    private func send<T: Decodable>(_ request: URLRequest, as type: T.Type) async throws -> T {
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw SyncError.server("無法連線到伺服器。") }
        guard 200..<300 ~= http.statusCode else {
            let message = InspectionSyncService.detail(from: data) ?? "伺服器錯誤（HTTP \(http.statusCode)）"
            if 400..<500 ~= http.statusCode { throw SyncError.rejected(message) }
            throw SyncError.server(message)
        }
        return try APICoding.decoder.decode(type, from: data)
    }
}

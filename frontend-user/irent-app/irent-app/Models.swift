import CoreLocation
import Foundation
import Observation

/// App 端畫面階段。後端 `RentalSession.state` 才是主要依據（`RentalStore.phase(for:)` 做對應）；
/// 本機只補足後端沒有的子步驟（例如取車照拍完但還沒按「開始租借」）。
enum RentalPhase: String, Codable, CaseIterable {
    /// 尚未租借：定位 → 地圖找車 → 車輛資訊 → 開始租車（建立 Session）→ 前往車輛。
    case findCar
    /// Session PICKUP_INSPECTION：取車拍攝（建立這次租借的車況基準）。
    case readyForPickup
    case pickupComplete
    /// Session RENTED：租用中（計時）。
    case activeRental
    /// Session RETURN_INITIATED：還車資訊確認（結束里程、使用時間）。
    case returnInfo
    /// Session PHOTO_INSPECTION：還車拍攝。
    case readyForReturn
    /// Session PHOTO_INSPECTION（分析中）/ INSPECTION_COMPLETED / INSPECTION_FAILED：AI 檢測結果。
    case inspectionResult
    /// Session RETURNED：還車完成。
    case completed

    var title: String {
        switch self {
        case .findCar: "尋找附近車輛"
        case .readyForPickup: "取車檢查"
        case .pickupComplete: "取車檢查完成"
        case .activeRental: "租用中"
        case .returnInfo: "還車資訊確認"
        case .readyForReturn: "還車拍攝"
        case .inspectionResult: "AI 影像檢測"
        case .completed: "還車完成"
        }
    }
}

/// 取車 = 建立這次租借的車況 Baseline；還車 = Return Inspection（後端比對 Pickup vs Return）。
enum InspectionStage: String, Codable, CaseIterable {
    case pickup
    case `return`

    var title: String { self == .pickup ? "取車拍攝" : "還車拍攝" }
    /// 後端 `inspection_type`
    var inspectionType: String { self == .pickup ? "PICKUP" : "RETURN" }
}

/// 一次檢查要拍的槽位：四個外觀角度（沿用 ViewClassifier 的 `VehicleView` 命名）＋ 一張車內照。
enum InspectionShot: String, Codable, CaseIterable, Identifiable {
    case leftFront = "左前"
    case rightFront = "右前"
    case leftRear = "左後"
    case rightRear = "右後"
    case interior = "車內"

    var id: String { rawValue }
    static let exterior: [InspectionShot] = [.leftFront, .rightFront, .leftRear, .rightRear]

    var isInterior: Bool { self == .interior }
    var exteriorView: VehicleView? { VehicleView(rawValue: rawValue) }
    /// 後端 `angle`（FRONT_LEFT … INTERIOR）
    var angleCode: String {
        switch self {
        case .leftFront: "FRONT_LEFT"
        case .rightFront: "FRONT_RIGHT"
        case .leftRear: "REAR_LEFT"
        case .rightRear: "REAR_RIGHT"
        case .interior: "INTERIOR"
        }
    }
    var photoCategory: String { isInterior ? "interior" : "exterior" }
    var title: String { isInterior ? "車內" : "\(rawValue)角" }
    var instruction: String {
        isInterior
            ? "請站在車門外拍攝整個座艙（前後座、杯架、地墊），光線充足、避免只拍到方向盤。"
            : "請站在車輛\(rawValue)方約 2–3 公尺處，讓車牌與整個車身角落清楚入鏡。"
    }
    var systemImage: String { isInterior ? "car.rear.and.collision.road.lane" : "car.side" }
}

struct Rental: Codable, Identifiable, Equatable {
    let id: String
    let vehicleID: String
    let plateNumber: String
    let carName: String
    /// 示範租約：後端走 deterministic demo fixture；App 可用「重新開始 Demo」重演。
    let isDemo: Bool

    /// 比賽示範租約（ABC-1234）：後端固定產生「右後車門刮痕 92% + 車內髒汙 88%」。
    static let demo = Rental(
        id: "RNT-20261005-1842",
        vehicleID: "VH-ABC-1234",
        plateNumber: "ABC-1234",
        carName: "Toyota Yaris",
        isDemo: true
    )

    /// 真實 Core ML 驗證用（資料集內真車，車牌可被 OCR 辨識），後端走真實 AI pipeline。
    static let coreMLTest = Rental(
        id: "demo-rental-001",
        vehicleID: "demo-car-001",
        plateNumber: "RCG-2235",
        carName: "Toyota Yaris",
        isDemo: true
    )

    static let available: [Rental] = [.demo, .coreMLTest]

    /// 由後端 Session 建立這次租借用的租約（照片上傳沿用 `rental_id`）。
    init(session: RentalSession) {
        id = session.rentalId
        vehicleID = session.vehicle.vehicleId
        plateNumber = session.vehicle.plate
        carName = session.vehicle.model ?? "車輛"
        isDemo = true
    }

    init(id: String, vehicleID: String, plateNumber: String, carName: String, isDemo: Bool) {
        self.id = id
        self.vehicleID = vehicleID
        self.plateNumber = plateNumber
        self.carName = carName
        self.isDemo = isDemo
    }
}

struct CapturedPhoto: Codable, Identifiable {
    let id: UUID
    let stage: InspectionStage
    let shot: InspectionShot
    let fileName: String
    let capturedAt: Date
    let sha256: String
    let result: LocalInspectionResult
    var uploadedAt: Date?
    /// 後端拒絕（例如取車已結束）時的原因；nil 表示仍會重試。
    var uploadError: String?
}

/// 後端 `GET /v1/mobile-inspections/rentals/{id}` 的精簡狀態（App 不會拿到任何車損／髒汙判定）。
struct RentalRemoteStatus: Codable {
    struct Completeness: Codable {
        struct Count: Codable {
            let received: Int
            let required: Int
        }
        let received: [String]
        let missing: [String]
        let complete: Bool
        let exterior: Count
        let interior: Count
    }
    let rental_id: String
    let status: String
    let pickup: Completeness
    let `return`: Completeness
    let analysis: String   // pending | analyzing | complete | failed
}

// MARK: - 模擬租還車（後端 /v1/rental-sessions）

/// 後端 JSON 走 snake_case；本 App 的 Session／車輛模型統一用這組 coder。
enum APICoding {
    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()
    static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()
}

struct GeoPoint: Codable, Equatable {
    let lat: Double?
    let lng: Double?
    var name: String? = nil
    var source: String? = nil      // gps | manual
    var simulated: Bool? = nil

    var coordinate: CLLocationCoordinate2D? {
        guard let lat, let lng else { return nil }
        return CLLocationCoordinate2D(latitude: lat, longitude: lng)
    }
}

/// 車輛（後端 `/v1/rental-sessions/vehicles` 的一般視圖：只有產品資訊與服務說明）。
struct SimVehicle: Codable, Identifiable, Equatable {
    struct Pricing: Codable, Equatable {
        let hourlyTwd: Double?
        let perKmTwd: Double?
        let estimatedKmFeeTwd: Double?
        let estimatedTotalTwd: Double?
        let billingNote: String?
    }
    let vehicleId: String
    let plate: String
    let model: String
    let color: String?
    let seats: Int?
    let vehicleType: String?
    let parkingSpot: String?
    let imageUrl: String?
    let location: GeoPoint
    let status: String              // AVAILABLE | RENTED | RETURNED
    let odometerKm: Int
    let fuelPercent: Int?
    let pricing: Pricing?
    /// 置頂推薦：不受定位距離與搜尋半徑限制
    let featured: Bool
    let serviceNotice: String?
    let activeSessionId: String?

    var id: String { vehicleId }
    var coordinate: CLLocationCoordinate2D { location.coordinate ?? CLLocationCoordinate2D(latitude: 0, longitude: 0) }
    var isAvailable: Bool { status == "AVAILABLE" }
    var statusLabel: String {
        switch status {
        case "AVAILABLE": "可租借"
        case "RENTED": "租用中"
        case "RETURNED": "已還車"
        default: status
        }
    }

    func distance(from origin: CLLocationCoordinate2D) -> CLLocationDistance {
        CLLocation(latitude: coordinate.latitude, longitude: coordinate.longitude)
            .distance(from: CLLocation(latitude: origin.latitude, longitude: origin.longitude))
    }
    func distanceLabel(from origin: CLLocationCoordinate2D) -> String {
        let meters = distance(from: origin)
        if meters >= 1000 { return String(format: "約 %.1f km", meters / 1000) }
        return "約 \(max(10, Int((meters / 10).rounded()) * 10)) m"
    }
    func walkingLabel(from origin: CLLocationCoordinate2D) -> String {
        "步行約 \(max(1, Int((distance(from: origin) / 80).rounded(.up)))) 分鐘"
    }
}

/// 租車 Session（後端 `rental_sessions`）。狀態轉換由後端驗證。
struct RentalSession: Codable, Equatable, Identifiable {
    struct Vehicle: Codable, Equatable {
        let vehicleId: String
        let plate: String
        let model: String?
        let imageUrl: String?
        let imageNote: String?
        let location: GeoPoint?
        let status: String?
        let aiSource: String?
        var category: String? = nil
        var featured: Bool? = nil
        var pricing: SimVehicle.Pricing? = nil
    }
    struct FeeEstimate: Codable, Equatable {
        let hourlyTwd: Double?
        let perKmTwd: Double?
        let billableHours: Int?
        let timeFeeTwd: Double?
        let distanceKm: Int?
        let kmFeeTwd: Double?
        let totalTwd: Double?
        let billingNote: String?
    }
    struct Completeness: Codable, Equatable {
        let received: [String]
        let missing: [String]
        let complete: Bool
    }

    let sessionId: String
    let state: String
    var serviceNotice: String? = nil
    var feeEstimate: FeeEstimate? = nil
    let vehicle: Vehicle
    let rentalId: String
    let rentalStatus: String?
    let aiSource: String?
    let aiSourceLabel: String?
    let startedAt: String
    let startLocation: GeoPoint?
    let startOdometerKm: Int
    let returnInitiatedAt: String?
    let returnInfoConfirmedAt: String?
    let returnLocation: GeoPoint?
    let endOdometerKm: Int?
    let distanceKm: Int?
    let usedSeconds: Int?
    let returnedAt: String?
    /// 後端已收到的照片（每個角度最新一張）：url 可供圖；preloaded = 預載 Demo 照片（非當下拍攝）
    struct RemotePhoto: Codable, Equatable, Identifiable {
        let angle: String
        let angleCode: String?
        let url: String?
        let validationMode: String?
        let source: String?
        let preloaded: Bool?
        let interiorStandin: Bool?
        var id: String { angle }
    }
    var photos: [String: [RemotePhoto]]? = nil          // "PICKUP" | "RETURN"
    var captureMode: [String: String?]? = nil           // live | preloaded | mixed
    let pickup: Completeness?
    let `return`: Completeness?
    let analysis: String?          // pending | analyzing | complete | failed
    let inspectionAttempts: Int?
    let lastError: String?
    let reviewRequired: Bool?

    var id: String { sessionId }
    var startedDate: Date? { Self.parse(startedAt) }
    func remotePhotos(_ stage: InspectionStage) -> [RemotePhoto] { photos?[stage.inspectionType] ?? [] }
    func remotePhoto(_ stage: InspectionStage, _ shot: InspectionShot) -> RemotePhoto? { remotePhotos(stage).first { $0.angle == shot.rawValue } }
    func isPreloaded(_ stage: InspectionStage) -> Bool { (captureMode?[stage.inspectionType] ?? nil) == "preloaded" }
    /// 照片來源說明（給使用者看的中性文案；系統登錄 ≠ 當下拍攝）
    func captureModeLabel(_ stage: InspectionStage) -> String? {
        switch captureMode?[stage.inspectionType] ?? nil {
        case "preloaded": "照片來源：車況紀錄（系統登錄，非本次拍攝）"
        case "live": "照片來源：本次拍攝"
        case "mixed": "照片來源：本次拍攝與車況紀錄"
        default: nil
        }
    }
    var returnedDate: Date? { returnedAt.flatMap(Self.parse) }
    var isFixture: Bool { aiSource == "demo_fixture" }

    /// 後端時間為本地時間的 ISO 8601（無時區）。
    nonisolated static func parse(_ text: String) -> Date? {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        for fmt in ["yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"] {
            f.dateFormat = fmt
            if let d = f.date(from: text) { return d }
        }
        return ISO8601DateFormatter().date(from: text)
    }
}

/// `GET /v1/rental-sessions/{id}/inspection`：逐角度比對、車內整潔、車牌比對、AI 來源。
struct InspectionResult: Codable, Equatable {
    struct Comparison: Codable, Equatable, Identifiable {
        struct Finding: Codable, Equatable {
            let label: String?
            let type: String?
            let severity: String?
            let confidence: Double?
            let status: String?
            let reasoning: String?
        }
        let angle: String
        let angleCode: String
        let result: String?
        let resultLabel: String
        let summary: String?
        let findings: [Finding]
        let returnPhotoUrl: String?
        let caseId: String?
        var id: String { angle }
    }
    struct Interior: Codable, Equatable {
        struct Finding: Codable, Equatable {
            let label: String?
            let severity: String?
            let confidence: Double?
            let description: String?
        }
        let result: String?
        let resultLabel: String?
        let cleanliness: String?
        let confidence: Double?
        let score: Int?
        let findings: [Finding]?
        let summary: String?
    }
    struct Incident: Codable, Equatable, Identifiable {
        let caseId: String
        let kind: String
        let angle: String
        let label: String?
        let severity: String?
        let confidence: Double?
        let aiLevel: String?
        let summary: String?
        var id: String { caseId }
    }
    struct PlateCheck: Codable, Equatable {
        struct Photo: Codable, Equatable, Identifiable {
            let angle: String
            let plateText: String?
            let confidence: Double?
            let source: String
            let status: String
            var id: String { angle }
        }
        let status: String          // MATCH | MANUAL | MISMATCH | UNKNOWN | PENDING
        let label: String
        let expectedPlate: String
        let photos: [Photo]
        let requiresManualReview: Bool
    }

    let sessionId: String
    let state: String
    let analysis: String
    let aiSource: String?
    let aiSourceLabel: String
    let analysisError: String?
    let overall: String?            // PASSED | ISSUES | FAILED | ANALYZING | PENDING
    let overallLabel: String
    let comparisons: [Comparison]
    let interior: Interior?
    let incidents: [Incident]
    let plateCheck: PlateCheck
    let reviewRequired: Bool
    let note: String?

    var isFixture: Bool { aiSource == "demo_fixture" }
    var isFinished: Bool { analysis == "complete" || analysis == "failed" }
}

@MainActor
@Observable
final class RentalStore {
    private(set) var rental: Rental
    var phase: RentalPhase = .findCar
    var photos: [CapturedPhoto] = []
    var remoteStatus: RentalRemoteStatus?
    var isSyncing = false
    /// 每個槽位的拍攝次數（Demo 劇本用：第一次固定失敗 → 重拍通過）。
    var attempts: [String: Int] = [:]

    /// 目前的租車 Session（後端為準）。nil = 尚未租借。
    private(set) var session: RentalSession?
    /// 地圖上的模擬車輛（後端 /v1/rental-sessions/vehicles）。
    var vehicles: [SimVehicle] = []
    var vehiclesError: String?
    /// 最近一次與後端同步 Session 失敗的訊息（離線時顯示，不擋本機操作）。
    var sessionSyncError: String?

    var apiBaseURL: String {
        didSet { UserDefaults.standard.set(apiBaseURL, forKey: "apiBaseURL") }
    }
    /// 開發者選項（拍攝驗證固定劇本等）只在以 `-developerMode YES` 啟動參數或 UserDefaults `developerMode` 開啟時顯示；
    /// 伺服器端的開發功能（重設、登錄照片、pipeline 細節）不在 App 內，改由 /api/ops/devtools（需管理者登入）。
    let developerMode: Bool = UserDefaults.standard.bool(forKey: "developerMode") || CommandLine.arguments.contains("-developerMode")
    /// Demo 模式：拍攝驗證改走固定劇本（不跑 Core ML）；關閉時一律真實 Core ML。
    var demoMode: Bool {
        didSet { UserDefaults.standard.set(demoMode, forKey: "demoMode") }
    }

    init() {
        // 預設留空：127.0.0.1 在真機上是 iPhone 自己，重裝後會靜默連錯；空值讓設定頁直接顯示紅字提示要填 Mac 的區網 IP
        apiBaseURL = UserDefaults.standard.string(forKey: "apiBaseURL") ?? ""
        demoMode = UserDefaults.standard.object(forKey: "demoMode") as? Bool ?? false
        rental = .demo
        load()
    }

    // MARK: - 查詢

    func photo(for stage: InspectionStage, shot: InspectionShot) -> CapturedPhoto? {
        photos.last { $0.stage == stage && $0.shot == shot }
    }

    func completedShots(for stage: InspectionStage) -> Int {
        InspectionShot.allCases.filter { photo(for: stage, shot: $0) != nil }.count
    }

    func completedExterior(for stage: InspectionStage) -> Int {
        InspectionShot.exterior.filter { photo(for: stage, shot: $0) != nil }.count
    }

    /// 本機拍齊 5 張，或後端已用預載照片收齊（模式 B）。
    func isComplete(_ stage: InspectionStage) -> Bool {
        completedShots(for: stage) == InspectionShot.allCases.count || isRemoteComplete(stage)
    }

    /// 外觀／車內張數：本機拍攝或後端已收到（預載）取大者。
    func exteriorCount(_ stage: InspectionStage) -> Int {
        max(completedExterior(for: stage), session?.remotePhotos(stage).filter { $0.angle != InspectionShot.interior.rawValue }.count ?? 0)
    }
    func interiorCount(_ stage: InspectionStage) -> Int {
        (photo(for: stage, shot: .interior) != nil || session?.remotePhoto(stage, .interior) != nil) ? 1 : 0
    }

    func isRemoteComplete(_ stage: InspectionStage) -> Bool {
        guard let session else { return false }
        return (stage == .pickup ? session.pickup?.complete : session.return?.complete) ?? false
    }

    /// 後端已收齊照片（例如由內部工具登錄）時，本機可直接進入下一步。
    func acceptRemotePhotos(stage: InspectionStage) {
        guard isRemoteComplete(stage) else { return }
        phase = stage == .pickup ? .pickupComplete : .inspectionResult
        save()
    }

    func uploadedCount(for stage: InspectionStage) -> Int {
        photos.filter { $0.stage == stage && $0.uploadedAt != nil }.count
    }

    func pendingUploads(for stage: InspectionStage) -> Int {
        photos.filter { $0.stage == stage && $0.uploadedAt == nil }.count
    }

    func nextShot(for stage: InspectionStage) -> InspectionShot? {
        if isRemoteComplete(stage) { return nil }
        return InspectionShot.allCases.first { photo(for: stage, shot: $0) == nil }
    }

    func attemptCount(stage: InspectionStage, shot: InspectionShot) -> Int {
        attempts["\(stage.rawValue)/\(shot.rawValue)"] ?? 0
    }

    func recordAttempt(stage: InspectionStage, shot: InspectionShot) -> Int {
        let key = "\(stage.rawValue)/\(shot.rawValue)"
        attempts[key, default: 0] += 1
        return attempts[key]!
    }

    // MARK: - 變更

    func replace(_ photo: CapturedPhoto) {
        photos.removeAll { $0.stage == photo.stage && $0.shot == photo.shot }
        photos.append(photo)
        save()
    }

    func markUploaded(id: UUID) {
        guard let index = photos.firstIndex(where: { $0.id == id }) else { return }
        photos[index].uploadedAt = Date()
        photos[index].uploadError = nil
        save()
    }

    func markRejected(id: UUID, reason: String) {
        guard let index = photos.firstIndex(where: { $0.id == id }) else { return }
        photos[index].uploadError = reason
        save()
    }

    /// 重新拍攝某一階段：清掉該階段本機照片與拍攝次數（檔案一併刪除）。
    func clearPhotos(stage: InspectionStage) {
        let files = photos.filter { $0.stage == stage }.map(\.fileName)
        photos.removeAll { $0.stage == stage }
        for shot in InspectionShot.allCases { attempts["\(stage.rawValue)/\(shot.rawValue)"] = nil }
        PhotoStore().remove(files)
        save()
    }

    /// 本機確認拍攝清單：取車 → 取車完成頁；還車 → AI 檢測結果頁（等待後端分析）。
    func confirm(stage: InspectionStage) {
        guard isComplete(stage) else { return }
        phase = stage == .pickup ? .pickupComplete : .inspectionResult
        save()
    }

    /// 「我已抵達車輛」：進入取車檢查（Session 已在 PICKUP_INSPECTION）。
    func arriveAtVehicle() {
        guard phase == .findCar, session != nil else { return }
        phase = .readyForPickup
        save()
    }

    /// 還車完成畫面「完成」：這次租借結束，回到 Find a Car（照片檔由呼叫端用 PhotoStore 清）。
    func finishRental() {
        guard phase == .completed else { return }
        resetLocal()
    }

    /// 每次 resetLocal 遞增：讓 Find a Car 畫面重建（清掉已選車輛／Find My Car 的畫面狀態），下一輪 Demo 從頭開始。
    private(set) var resetGeneration = 0

    /// 清掉本機照片與狀態（照片檔由 PhotoStore 另外清）。
    func resetLocal() {
        resetGeneration += 1
        photos = []
        phase = .findCar
        attempts = [:]
        remoteStatus = nil
        session = nil
        sessionSyncError = nil
        UserDefaults.standard.removeObject(forKey: "sessionID")
        save()
    }

    // MARK: - Session（後端為主要依據）

    /// 套用後端回來的 Session：更新租約與畫面階段。`keepLocalSubphase` 時尊重本機子步驟（例如取車照已拍完、等待按「開始租借」）。
    func apply(_ newSession: RentalSession) {
        let changedRental = session?.rentalId != newSession.rentalId
        session = newSession
        sessionSyncError = nil
        UserDefaults.standard.set(newSession.sessionId, forKey: "sessionID")
        if changedRental {
            rental = Rental(session: newSession)
            photos = []
            attempts = [:]
            remoteStatus = nil
        }
        phase = Self.phase(for: newSession, current: phase, localPhotos: photos)
        save()
    }

    /// 後端狀態 → App 畫面階段。
    static func phase(for s: RentalSession, current: RentalPhase, localPhotos: [CapturedPhoto]) -> RentalPhase {
        switch s.state {
        case "PICKUP_INSPECTION":
            if current == .findCar {
                // 推薦車輛不需要走到車旁：直接取車檢查；其他車輛停在 Find My Car
                return (s.vehicle.featured ?? (s.vehicle.category == "demo")) ? .readyForPickup : .findCar
            }
            return current == .pickupComplete ? .pickupComplete : .readyForPickup
        case "RENTED":
            return .activeRental
        case "RETURN_INITIATED":
            return .returnInfo
        case "PHOTO_INSPECTION":
            // 還車照齊、本機已按「完成還車拍攝」→ 停在結果頁等分析；否則（含重新拍攝）回到拍攝清單
            let remoteComplete = s.return?.complete ?? false
            if current == .inspectionResult && remoteComplete { return .inspectionResult }
            return .readyForReturn
        case "INSPECTION_COMPLETED", "INSPECTION_FAILED":
            return .inspectionResult
        case "RETURNED":
            return .completed
        default:
            return .findCar
        }
    }

    /// 開啟 App：有保存的 Session 就向後端取最新狀態；沒有就看後端是否有進行中的 Session（換手機／重裝）。
    func restoreSession() async {
        let service = RentalSessionService()
        let savedID = UserDefaults.standard.string(forKey: "sessionID") ?? session?.sessionId
        do {
            if let savedID {
                let s = try await service.get(id: savedID, baseURL: apiBaseURL)
                if s.state == "CANCELLED" || s.state == "ARCHIVED" || (s.state == "RETURNED" && phase != .completed) {
                    resetLocal()
                } else {
                    apply(s)
                }
            } else if let s = try await service.active(baseURL: apiBaseURL) {
                apply(s)
            }
        } catch SyncError.rejected(let reason) {
            // 404：後端已沒有這筆 Session（例如 Demo 重置）→ 本機回到找車
            sessionSyncError = reason
            if savedID != nil { resetLocal() }
        } catch {
            sessionSyncError = "無法連線到伺服器，顯示本機最後狀態（\(error.localizedDescription)）"
        }
    }

    /// 置頂推薦車輛：不受定位限制，定位頁與地圖頁固定顯示。
    var featuredVehicles: [SimVehicle] { vehicles.filter(\.featured) }

    /// 推薦車輛「開始使用」：建立 Session 後直接進入取車檢查（不需要走到車旁）。
    func startFeaturedVehicle(_ vehicle: SimVehicle, location: RentalSessionService.LocationBody?) async throws {
        let session = try await RentalSessionService().create(vehicleID: vehicle.vehicleId, location: location, baseURL: apiBaseURL)
        apply(session)
        phase = .readyForPickup
        save()
        await loadVehicles()
    }

    func loadVehicles() async {
        do {
            vehicles = try await RentalSessionService().vehicles(baseURL: apiBaseURL)
            vehiclesError = nil
        } catch {
            vehiclesError = error.localizedDescription
        }
    }

    // MARK: - 持久化

    private func save() {
        let state = PersistedRentalState(rentalID: rental.id, phase: phase, photos: photos, rental: rental, session: session)
        guard let data = try? JSONEncoder().encode(state) else { return }
        UserDefaults.standard.set(data, forKey: "rentalState")
    }

    private func load() {
        guard
            let data = UserDefaults.standard.data(forKey: "rentalState"),
            let state = try? JSONDecoder().decode(PersistedRentalState.self, from: data)
        else { return }
        if let r = state.rental { rental = r }
        session = state.session
        phase = state.phase
        photos = state.photos
        // 沒有 Session 就不可能在租借流程中（舊版資料或 Demo 重置後）
        if session == nil, phase != .findCar {
            phase = .findCar
            photos = []
        }
    }
}

private struct PersistedRentalState: Codable {
    let rentalID: String
    let phase: RentalPhase
    let photos: [CapturedPhoto]
    var rental: Rental? = nil
    var session: RentalSession? = nil
}


/// `GET /v1/rental-sessions/vehicles/{id}/records`：車況紀錄（已確認屬於本車的借車前／還車後照片）。
struct VehicleRecords: Codable, Equatable {
    struct Photo: Codable, Equatable, Identifiable {
        let angle: String?
        let angleCode: String?
        let url: String?
        let stage: String
        var id: String { "\(stage)-\(angle ?? "")" }
    }
    let hasRecords: Bool
    let before: [Photo]
    let after: [Photo]
    let angles: [String]?
    let complete: Bool?
    let recordNote: String?
}

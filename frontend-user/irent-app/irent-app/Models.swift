import Foundation
import Observation

enum RentalPhase: String, Codable, CaseIterable {
    case readyForPickup
    case pickupComplete
    case activeRental
    case readyForReturn
    case completed

    var title: String {
        switch self {
        case .readyForPickup: "取車檢查"
        case .pickupComplete: "取車檢查完成"
        case .activeRental: "租用中"
        case .readyForReturn: "還車檢查"
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

@MainActor
@Observable
final class RentalStore {
    private(set) var rental: Rental
    var phase: RentalPhase = .readyForPickup
    var photos: [CapturedPhoto] = []
    var remoteStatus: RentalRemoteStatus?
    var isSyncing = false
    /// 每個槽位的拍攝次數（Demo 劇本用：第一次固定失敗 → 重拍通過）。
    var attempts: [String: Int] = [:]

    var apiBaseURL: String {
        didSet { UserDefaults.standard.set(apiBaseURL, forKey: "apiBaseURL") }
    }
    /// Demo 模式：拍攝驗證改走固定劇本（不跑 Core ML）；關閉時一律真實 Core ML。
    var demoMode: Bool {
        didSet { UserDefaults.standard.set(demoMode, forKey: "demoMode") }
    }

    init() {
        apiBaseURL = UserDefaults.standard.string(forKey: "apiBaseURL") ?? "http://127.0.0.1:8000"
        demoMode = UserDefaults.standard.object(forKey: "demoMode") as? Bool ?? true
        let rentalID = UserDefaults.standard.string(forKey: "rentalID") ?? Rental.demo.id
        rental = Rental.available.first { $0.id == rentalID } ?? .demo
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

    func isComplete(_ stage: InspectionStage) -> Bool {
        completedShots(for: stage) == InspectionShot.allCases.count
    }

    func uploadedCount(for stage: InspectionStage) -> Int {
        photos.filter { $0.stage == stage && $0.uploadedAt != nil }.count
    }

    func pendingUploads(for stage: InspectionStage) -> Int {
        photos.filter { $0.stage == stage && $0.uploadedAt == nil }.count
    }

    func nextShot(for stage: InspectionStage) -> InspectionShot? {
        InspectionShot.allCases.first { photo(for: stage, shot: $0) == nil }
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

    func confirm(stage: InspectionStage) {
        guard isComplete(stage) else { return }
        phase = stage == .pickup ? .pickupComplete : .completed
        save()
    }

    func startRental() {
        phase = .activeRental
        save()
    }

    func beginReturn() {
        phase = .readyForReturn
        save()
    }

    func selectRental(_ newRental: Rental) {
        guard newRental != rental else { return }
        rental = newRental
        UserDefaults.standard.set(newRental.id, forKey: "rentalID")
        resetLocal()
    }

    /// 清掉本機照片與狀態（照片檔由 PhotoStore 另外清）。
    func resetLocal() {
        photos = []
        phase = .readyForPickup
        attempts = [:]
        remoteStatus = nil
        save()
    }

    // MARK: - 持久化

    private func save() {
        let state = PersistedRentalState(rentalID: rental.id, phase: phase, photos: photos)
        guard let data = try? JSONEncoder().encode(state) else { return }
        UserDefaults.standard.set(data, forKey: "rentalState")
    }

    private func load() {
        guard
            let data = UserDefaults.standard.data(forKey: "rentalState"),
            let state = try? JSONDecoder().decode(PersistedRentalState.self, from: data),
            state.rentalID == rental.id
        else { return }
        phase = state.phase
        photos = state.photos
    }
}

private struct PersistedRentalState: Codable {
    let rentalID: String
    let phase: RentalPhase
    let photos: [CapturedPhoto]
}

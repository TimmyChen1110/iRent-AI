import Foundation
import Observation

enum RentalPhase: String, Codable, CaseIterable {
    case readyForPickup
    case activeRental
    case readyForReturn
    case completed

    var title: String {
        switch self {
        case .readyForPickup: "開始取車"
        case .activeRental: "租用中"
        case .readyForReturn: "開始還車"
        case .completed: "租還完成"
        }
    }
}

enum InspectionStage: String, Codable, CaseIterable {
    case pickup
    case `return`

    var title: String { self == .pickup ? "取車拍攝" : "還車拍攝" }
}

enum VehicleView: String, Codable, CaseIterable, Identifiable {
    case leftFront = "左前"
    case rightFront = "右前"
    case leftRear = "左後"
    case rightRear = "右後"

    var id: String { rawValue }
    var instruction: String { "請拍攝車輛(rawValue)角，並讓車牌清楚入鏡。" }
}

struct DemoRental: Codable {
    let id: String
    let carID: String
    let plateNumber: String
    let carName: String

    static let current = DemoRental(
        id: "demo-rental-001",
        carID: "demo-car-001",
        plateNumber: "RCG-2235",
        carName: "Toyota Yaris"
    )
}

struct LocalInspectionResult: Codable, Equatable {
    let passed: Bool
    let plateText: String?
    let plateConfidence: Double?
    let detectedView: VehicleView?
    let viewConfidence: Double?
    let errors: [String]
    let modelVersions: [String: String]
}

struct CapturedPhoto: Codable, Identifiable {
    let id: UUID
    let stage: InspectionStage
    let view: VehicleView
    let fileName: String
    let capturedAt: Date
    let sha256: String
    let result: LocalInspectionResult
    var uploadedAt: Date?
}

@MainActor
@Observable
final class RentalStore {
    let rental = DemoRental.current
    var phase: RentalPhase = .readyForPickup
    var photos: [CapturedPhoto] = []
    var apiBaseURL: String {
        didSet { UserDefaults.standard.set(apiBaseURL, forKey: "apiBaseURL") }
    }

    init() {
        apiBaseURL = UserDefaults.standard.string(forKey: "apiBaseURL") ?? "http://127.0.0.1:8000"
        load()
    }

    func photo(for stage: InspectionStage, view: VehicleView) -> CapturedPhoto? {
        photos.last { $0.stage == stage && $0.view == view }
    }

    func completedViews(for stage: InspectionStage) -> Int {
        VehicleView.allCases.filter { photo(for: stage, view: $0) != nil }.count
    }

    func replace(_ photo: CapturedPhoto) {
        photos.removeAll { $0.stage == photo.stage && $0.view == photo.view }
        photos.append(photo)
        save()
    }

    func markUploaded(id: UUID) {
        guard let index = photos.firstIndex(where: { $0.id == id }) else { return }
        let photo = photos[index]
        photos[index] = CapturedPhoto(
            id: photo.id,
            stage: photo.stage,
            view: photo.view,
            fileName: photo.fileName,
            capturedAt: photo.capturedAt,
            sha256: photo.sha256,
            result: photo.result,
            uploadedAt: Date()
        )
        save()
    }

    func confirm(stage: InspectionStage) {
        guard completedViews(for: stage) == VehicleView.allCases.count else { return }
        phase = stage == .pickup ? .activeRental : .completed
        save()
    }

    func beginReturn() {
        phase = .readyForReturn
        save()
    }

    private func save() {
        let state = PersistedRentalState(phase: phase, photos: photos)
        guard let data = try? JSONEncoder().encode(state) else { return }
        UserDefaults.standard.set(data, forKey: "rentalState")
    }

    private func load() {
        guard
            let data = UserDefaults.standard.data(forKey: "rentalState"),
            let state = try? JSONDecoder().decode(PersistedRentalState.self, from: data)
        else { return }
        phase = state.phase
        photos = state.photos
    }
}

private struct PersistedRentalState: Codable {
    let phase: RentalPhase
    let photos: [CapturedPhoto]
}

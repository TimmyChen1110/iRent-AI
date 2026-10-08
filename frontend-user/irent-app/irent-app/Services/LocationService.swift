import CoreLocation
import Foundation
import Observation

enum LocationSource: String {
    case gps
    case manual
}

/// Phase 1 定位：向使用者說明用途並請求「使用 App 期間」權限；取得 GPS 座標或讓使用者手動選位置。
/// 定位資訊只保存在記憶體（這次操作），不寫入磁碟。
@MainActor
@Observable
final class LocationService: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var timeoutTask: Task<Void, Never>?

    private(set) var authorization: CLAuthorizationStatus = .notDetermined
    private(set) var coordinate: CLLocationCoordinate2D?
    private(set) var source: LocationSource = .gps
    private(set) var locationName: String?
    private(set) var accuracyMeters: Double?
    var errorMessage: String?
    private(set) var isRequesting = false

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
        authorization = manager.authorizationStatus
    }

    var isResolved: Bool { coordinate != nil }
    var isDenied: Bool { authorization == .denied || authorization == .restricted }
    var isAuthorized: Bool { authorization == .authorizedWhenInUse || authorization == .authorizedAlways }

    /// 給後端的位置（含來源）。
    var body: RentalSessionService.LocationBody? {
        guard let coordinate else { return nil }
        return .init(lat: coordinate.latitude, lng: coordinate.longitude, source: source.rawValue)
    }

    /// 「允許定位」：未決定 → 跳系統授權；已授權 → 直接定位；已拒絕 → 提示改用設定或手動選位置。
    func request() {
        errorMessage = nil
        switch manager.authorizationStatus {
        case .notDetermined:
            isRequesting = true
            manager.requestWhenInUseAuthorization()
        case .denied, .restricted:
            isRequesting = false
            errorMessage = "定位權限已關閉。你可以到「設定 › iRent App › 位置」開啟，或改用手動選擇位置。"
        default:
            startLocating()
        }
    }

    func setManual(_ coordinate: CLLocationCoordinate2D, name: String) {
        timeoutTask?.cancel()
        self.coordinate = coordinate
        source = .manual
        locationName = name
        accuracyMeters = nil
        errorMessage = nil
        isRequesting = false
    }

    func clear() {
        timeoutTask?.cancel()
        coordinate = nil
        locationName = nil
        accuracyMeters = nil
        source = .gps
        isRequesting = false
    }

    private func startLocating() {
        isRequesting = true
        manager.requestLocation()
        timeoutTask?.cancel()
        timeoutTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(15))
            guard let self, !Task.isCancelled, self.isRequesting else { return }
            self.isRequesting = false
            self.errorMessage = "定位逾時（15 秒內沒有取得位置）。請重試，或手動選擇位置。"
        }
    }

    // MARK: - CLLocationManagerDelegate（回呼可能在背景執行緒，統一切回 MainActor）

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in
            self.authorization = status
            switch status {
            case .authorizedWhenInUse, .authorizedAlways:
                if self.isRequesting { self.startLocating() }
            case .denied, .restricted:
                self.isRequesting = false
                self.errorMessage = "你拒絕了定位權限。可以改用手動選擇位置，或到「設定」重新開啟。"
            default:
                break
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let last = locations.last else { return }
        let coordinate = last.coordinate
        let accuracy = last.horizontalAccuracy
        Task { @MainActor in
            self.timeoutTask?.cancel()
            self.isRequesting = false
            self.coordinate = coordinate
            self.source = .gps
            self.accuracyMeters = accuracy
            self.locationName = "目前位置（GPS）"
            self.errorMessage = nil
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        let message = error.localizedDescription
        Task { @MainActor in
            self.timeoutTask?.cancel()
            self.isRequesting = false
            self.errorMessage = "定位失敗：\(message)。請重試，或手動選擇位置。"
        }
    }
}

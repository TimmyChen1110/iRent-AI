import CoreLocation
import Foundation

/// 附近車輛（Find a Car 用）。沒有獨立的 Vehicle backend：能取車的車輛直接連到既有 `Rental`，
/// 選車後 `RentalStore.selectRental` 仍然使用同一筆租約（ABC-1234 → RNT-20261005-1842）。
struct NearbyVehicle: Identifiable, Equatable {
    enum Status: String {
        case available = "AVAILABLE"
        case unavailable = "UNAVAILABLE"

        var label: String { self == .available ? "可租借" : "租用中" }
    }

    let id: String            // 與 Rental.vehicleID 對齊（VH-<plate>）
    let plateNumber: String
    let model: String
    /// 停放位置（例如「台北市信義區 · 信義站 A3」）
    let locationName: String
    let coordinate: CLLocationCoordinate2D
    let fuelPercent: Int
    let status: Status
    /// 這台車對應的既有租約；nil 代表只是地圖上的示範車，無法進入取車。
    let rental: Rental?

    var isAvailable: Bool { status == .available }
    var canPickup: Bool { isAvailable && rental != nil }

    static func == (lhs: NearbyVehicle, rhs: NearbyVehicle) -> Bool { lhs.id == rhs.id }

    /// 與使用者位置的直線距離（公尺）。
    func distance(from origin: CLLocationCoordinate2D) -> CLLocationDistance {
        CLLocation(latitude: coordinate.latitude, longitude: coordinate.longitude)
            .distance(from: CLLocation(latitude: origin.latitude, longitude: origin.longitude))
    }

    /// 「約 320 m」：四捨五入到 10 m。
    func distanceLabel(from origin: CLLocationCoordinate2D) -> String {
        let meters = distance(from: origin)
        if meters >= 1000 { return String(format: "約 %.1f km", meters / 1000) }
        return "約 \(Int((meters / 10).rounded()) * 10) m"
    }

    /// 「步行約 4 分鐘」：以 80 m/min 估算，無條件進位。
    func walkingLabel(from origin: CLLocationCoordinate2D) -> String {
        "步行約 \(max(1, Int((distance(from: origin) / 80).rounded(.up)))) 分鐘"
    }
}

/// Find a Car 的固定示範資料：地點、使用者位置、附近車輛。
/// 這不是真 GPS、也不是車隊 API；比賽 Demo 不要求定位權限，所有數值皆為本機 deterministic fixture。
enum DemoFleet {
    /// 示範使用者位置（Demo Location）：台北信義區，距 ABC-1234 約 320 m。**不是**真實定位。
    static let demoUserLocation = CLLocationCoordinate2D(latitude: 25.0368, longitude: 121.5680)

    /// App 開啟時的鏡頭中心（信義區概覽），不顯示整個台灣。
    static let overviewCenter = CLLocationCoordinate2D(latitude: 25.0372, longitude: 121.5670)

    /// 主角車輛：Toyota Yaris ABC-1234，連到比賽示範租約。
    static let hero = NearbyVehicle(
        id: Rental.demo.vehicleID,
        plateNumber: Rental.demo.plateNumber,
        model: Rental.demo.carName,
        locationName: "台北市信義區 · 信義站 A3",
        coordinate: CLLocationCoordinate2D(latitude: 25.0346, longitude: 121.5660),
        fuelPercent: 72,
        status: .available,
        rental: .demo
    )

    /// 地圖上的附近車輛（5–8 台）。除 ABC-1234 / RCG-2235 外僅為增加真實感，無法進入取車。
    static let vehicles: [NearbyVehicle] = [
        hero,
        NearbyVehicle(
            id: "VH-DEF-5678", plateNumber: "DEF-5678", model: "Toyota Corolla Cross",
            locationName: "台北市信義區 · 市政府站 2 號出口",
            coordinate: CLLocationCoordinate2D(latitude: 25.0410, longitude: 121.5650),
            fuelPercent: 58, status: .available, rental: nil
        ),
        NearbyVehicle(
            id: "VH-GHI-9012", plateNumber: "GHI-9012", model: "Honda Fit",
            locationName: "台北市信義區 · 松壽路停車場",
            coordinate: CLLocationCoordinate2D(latitude: 25.0362, longitude: 121.5632),
            fuelPercent: 83, status: .available, rental: nil
        ),
        NearbyVehicle(
            id: "VH-JKL-3456", plateNumber: "JKL-3456", model: "Toyota Yaris",
            locationName: "台北市信義區 · 象山站 1 號出口",
            coordinate: CLLocationCoordinate2D(latitude: 25.0338, longitude: 121.5684),
            fuelPercent: 35, status: .unavailable, rental: nil
        ),
        NearbyVehicle(
            id: "VH-MNO-7890", plateNumber: "MNO-7890", model: "Toyota Corolla Cross",
            locationName: "台北市信義區 · 松仁路 B2",
            coordinate: CLLocationCoordinate2D(latitude: 25.0382, longitude: 121.5708),
            fuelPercent: 91, status: .available, rental: nil
        ),
        NearbyVehicle(
            id: Rental.coreMLTest.vehicleID, plateNumber: Rental.coreMLTest.plateNumber, model: Rental.coreMLTest.carName,
            locationName: "台北市信義區 · 松高路 C1",
            coordinate: CLLocationCoordinate2D(latitude: 25.0395, longitude: 121.5690),
            fuelPercent: 66, status: .available, rental: .coreMLTest
        ),
    ]

    /// 目前租約對應的車輛（設定頁換租約後，Find a Car 預設聚焦這台）。
    static func vehicle(for rental: Rental) -> NearbyVehicle? {
        vehicles.first { $0.rental?.id == rental.id }
    }

    /// Find My Car 的步行示意路線：固定折線，不是真實導航（不打 Directions API）。
    static func walkingPath(to vehicle: NearbyVehicle) -> [CLLocationCoordinate2D] {
        let from = demoUserLocation
        let to = vehicle.coordinate
        // 先沿街區走一段、再轉向車輛：兩個中繼點讓線條像人行路徑而非直線。
        let mid1 = CLLocationCoordinate2D(latitude: from.latitude, longitude: from.longitude + (to.longitude - from.longitude) * 0.55)
        let mid2 = CLLocationCoordinate2D(latitude: to.latitude + (from.latitude - to.latitude) * 0.25, longitude: mid1.longitude)
        return [from, mid1, mid2, to]
    }
}

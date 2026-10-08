import CoreLocation
import Foundation

/// Find a Car 的本機輔助資料。車輛清單已改由後端 `/v1/rental-sessions/vehicles`（模擬車輛）提供；
/// 這裡只剩：定位不可用時的後備中心點（**不是**真實定位，UI 會標示），以及示意步行路線。
enum DemoFleet {
    /// 後備位置：臺灣大學正門一帶。只在使用者尚未取得定位、也沒手動選位置時用來擺地圖鏡頭。
    static let fallbackUserLocation = CLLocationCoordinate2D(latitude: 25.01694, longitude: 121.53440)

    /// Find My Car 的步行示意路線：固定折線，不是真實導航（不打 Directions API）。
    static func walkingPath(from: CLLocationCoordinate2D, to: CLLocationCoordinate2D) -> [CLLocationCoordinate2D] {
        // 先沿街區走一段、再轉向車輛：兩個中繼點讓線條像人行路徑而非直線。
        let mid1 = CLLocationCoordinate2D(latitude: from.latitude, longitude: from.longitude + (to.longitude - from.longitude) * 0.55)
        let mid2 = CLLocationCoordinate2D(latitude: to.latitude + (from.latitude - to.latitude) * 0.25, longitude: mid1.longitude)
        return [from, mid1, mid2, to]
    }
}

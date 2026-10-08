import CoreLocation
import SwiftUI

/// 置頂推薦車輛：後端 `featured=true` 的車輛，不受定位距離與搜尋半徑限制，定位頁與地圖頁都顯示；點擊進入一般車輛資訊頁。
struct FeaturedVehiclesView: View {
    @Environment(RentalStore.self) private var store
    @Environment(LocationService.self) private var location
    @State private var selected: SimVehicle?

    var compact = false

    var body: some View {
        Group {
            if store.featuredVehicles.isEmpty {
                Button {
                    Task { await store.loadVehicles() }
                } label: {
                    HStack(spacing: 12) {
                        Image(systemName: store.vehiclesError == nil ? "car.2.fill" : "wifi.exclamationmark")
                            .font(.title3)
                            .foregroundStyle(store.vehiclesError == nil ? Color.accentColor : .orange)
                            .frame(width: 40, height: 40)
                            .background(Color.accentColor.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(store.vehiclesError == nil ? "正在載入推薦車輛…" : "目前無法載入車輛").font(.headline)
                            Text(store.vehiclesError == nil ? "請稍候" : "請確認網路連線後點此重試").font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                    }
                    .padding(compact ? 10 : 14)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            } else {
                VStack(spacing: compact ? 6 : 8) {
                    HStack(spacing: 6) {
                        Image(systemName: "star.fill").foregroundStyle(Color.accentColor)
                        Text("推薦車輛 · 可立即使用").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                        Spacer()
                    }
                    ForEach(store.featuredVehicles) { vehicle in
                        Button { selected = vehicle } label: { vehicleRow(vehicle) }
                            .buttonStyle(.plain)
                    }
                }
                .padding(compact ? 10 : 12)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            }
        }
        .task { if store.vehicles.isEmpty { await store.loadVehicles() } }
        .sheet(item: $selected) { vehicle in
            VehicleDetailView(vehicle: vehicle, userLocation: location.coordinate, imageURL: Self.imageURL(vehicle, baseURL: store.apiBaseURL))
        }
    }

    /// 車輛卡片：照片、車牌、車型、狀態。
    private func vehicleRow(_ vehicle: SimVehicle) -> some View {
        HStack(spacing: 10) {
            VehicleThumbnail(url: Self.imageURL(vehicle, baseURL: store.apiBaseURL), size: compact ? 40 : 52)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(vehicle.plate).font(.subheadline.weight(.bold)).monospaced()
                    Text(vehicle.statusLabel).font(.caption2.weight(.semibold))
                        .padding(.horizontal, 5).padding(.vertical, 1)
                        .background((vehicle.isAvailable ? Color.green : Color.gray).opacity(0.15), in: Capsule())
                        .foregroundStyle(vehicle.isAvailable ? .green : .secondary)
                }
                Text([vehicle.model, vehicle.color, vehicle.seats.map { "\($0) 人座" }].compactMap { $0 }.joined(separator: " · "))
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            if let price = vehicle.pricing?.hourlyTwd {
                Text("NT$\(VehicleDetailView.money(price))/時").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            }
            Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(.tertiary)
        }
        .contentShape(Rectangle())
    }

    static func imageURL(_ vehicle: SimVehicle, baseURL: String) -> URL? {
        guard let path = vehicle.imageUrl, let base = InspectionSyncService.normalizedBaseURL(baseURL) else { return nil }
        return URL(string: path, relativeTo: base)?.absoluteURL
    }
}

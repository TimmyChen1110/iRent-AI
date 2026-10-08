import CoreLocation
import SwiftUI

/// 首頁固定入口「Demo 測試車輛 — RFY-1753」：不論定位成功／失敗／在哪個城市都顯示；點擊開車輛詳細頁，可直接「開始使用」。
/// 車輛資料單一來源：後端 `/v1/rental-sessions/vehicles`（category=demo）。
struct DemoVehicleEntry: View {
    @Environment(RentalStore.self) private var store
    @Environment(LocationService.self) private var location
    @State private var selected: SimVehicle?
    @State private var loadError: String?

    var compact = false

    var body: some View {
        Group {
            if store.demoVehicles.isEmpty {
                Button {
                    Task { await store.loadVehicles(); loadError = store.vehiclesError }
                } label: {
                    row(icon: "wifi.exclamationmark", title: "Demo 測試車輛", subtitle: loadError ?? store.vehiclesError ?? "正在載入…（需連上後端）", tint: .orange)
                }
                .buttonStyle(.plain)
            } else {
                VStack(spacing: compact ? 6 : 8) {
                    HStack(spacing: 6) {
                        Image(systemName: "flag.checkered").foregroundStyle(.orange)
                        Text("Demo 測試車輛（\(store.demoVehicles.count) 台）· 不受定位距離限制").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                        Spacer()
                    }
                    ForEach(store.demoVehicles) { vehicle in
                        Button { selected = vehicle } label: {
                            vehicleRow(vehicle)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(compact ? 10 : 12)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(Color.orange.opacity(0.35), lineWidth: 1))
            }
        }
        .task { if store.vehicles.isEmpty { await store.loadVehicles() } }
        .sheet(item: $selected) { vehicle in
            VehicleDetailView(vehicle: vehicle, userLocation: location.coordinate, imageURL: Self.imageURL(vehicle, baseURL: store.apiBaseURL))
        }
    }

    /// 車輛卡片：照片、車牌、車型、狀態、Demo 標籤。
    private func vehicleRow(_ vehicle: SimVehicle) -> some View {
        HStack(spacing: 10) {
            VehicleThumbnail(url: Self.imageURL(vehicle, baseURL: store.apiBaseURL), size: compact ? 40 : 52)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(vehicle.plate).font(.subheadline.weight(.bold)).monospaced()
                    Text("DEMO").font(.caption2.weight(.bold))
                        .padding(.horizontal, 5).padding(.vertical, 1)
                        .background(Color.orange.opacity(0.18), in: Capsule()).foregroundStyle(.orange)
                    if vehicle.hasRegistryPhotos {
                        Text("有借／還照片").font(.caption2.weight(.semibold))
                            .padding(.horizontal, 5).padding(.vertical, 1)
                            .background(Color.green.opacity(0.15), in: Capsule()).foregroundStyle(.green)
                    }
                }
                Text("\(vehicle.model) · \(vehicle.statusLabel)").font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(.tertiary)
        }
        .contentShape(Rectangle())
    }

    private func row(icon: String, title: String, subtitle: String, tint: Color) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(tint)
                .frame(width: 40, height: 40)
                .background(tint.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(title).font(.headline).lineLimit(1)
                    Text("DEMO").font(.caption2.weight(.bold))
                        .padding(.horizontal, 5).padding(.vertical, 2)
                        .background(Color.orange.opacity(0.18), in: Capsule())
                        .foregroundStyle(.orange)
                }
                Text(subtitle).font(.caption).foregroundStyle(.secondary).lineLimit(compact ? 1 : 2)
            }
            Spacer()
            Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(.tertiary)
        }
        .padding(compact ? 10 : 14)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(Color.orange.opacity(0.35), lineWidth: 1))
        .contentShape(Rectangle())
    }

    static func imageURL(_ vehicle: SimVehicle, baseURL: String) -> URL? {
        guard let path = vehicle.imageUrl, let base = InspectionSyncService.normalizedBaseURL(baseURL) else { return nil }
        return URL(string: path, relativeTo: base)?.absoluteURL
    }
}

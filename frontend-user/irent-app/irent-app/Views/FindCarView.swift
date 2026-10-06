import CoreLocation
import MapKit
import SwiftUI

/// 尚未租借時的首頁：3D 台北信義區地圖為主體，底部是車輛資訊。
/// 狀態機只有三步（FIND_CAR → VEHICLE_SELECTED → FIND_MY_CAR），「我已抵達車輛」才交給既有取車檢查（`RentalStore.arriveAtVehicle`）。
/// 使用者位置為 Demo Location（`DemoFleet.demoUserLocation`），不要求定位權限；地圖圖資載不到也不影響進入取車。
struct FindCarView: View {
    @Environment(RentalStore.self) private var store

    private enum Mode { case findCar, findMyCar }
    @State private var mode: Mode = .findCar
    @State private var selected: NearbyVehicle?
    @State private var camera: MapCameraPosition = .camera(FleetCamera.overview)

    private var userLocation: CLLocationCoordinate2D { DemoFleet.demoUserLocation }

    var body: some View {
        ZStack(alignment: .bottom) {
            VehicleMapView(
                camera: $camera,
                vehicles: mode == .findMyCar ? (selected.map { [$0] } ?? []) : DemoFleet.vehicles,
                selected: selected,
                userLocation: userLocation,
                path: mode == .findMyCar ? selected.map { DemoFleet.walkingPath(to: $0) } : nil,
                onSelect: select
            )
            .ignoresSafeArea(edges: .bottom)

            Group {
                switch mode {
                case .findCar:
                    if let selected {
                        VehicleBottomSheet(vehicle: selected, userLocation: userLocation, onClose: { deselect() }, onGo: { goToVehicle(selected) })
                    } else {
                        NearbyHintCard(count: DemoFleet.vehicles.filter(\.isAvailable).count)
                    }
                case .findMyCar:
                    if let selected {
                        FindMyCarPanel(vehicle: selected, userLocation: userLocation, onBack: { backToFindCar() }, onArrived: { arrived() })
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 12)
        }
        .animation(.snappy(duration: 0.3), value: selected)
        .animation(.snappy(duration: 0.3), value: mode == .findMyCar)
    }

    // MARK: - 狀態轉換

    private func select(_ vehicle: NearbyVehicle) {
        guard mode == .findCar else { return }
        selected = vehicle
        withAnimation(.easeInOut(duration: 0.8)) {
            camera = .camera(FleetCamera.focus(on: vehicle.coordinate))
        }
    }

    private func deselect() {
        selected = nil
        withAnimation(.easeInOut(duration: 0.8)) { camera = .camera(FleetCamera.overview) }
    }

    /// 「前往取車」：切到 Find My Car。這裡就把租約切到這台車（既有 `selectRental`），後續取車／上傳沿用同一筆租約。
    private func goToVehicle(_ vehicle: NearbyVehicle) {
        guard let rental = vehicle.rental else { return }
        store.selectRental(rental)
        mode = .findMyCar
        withAnimation(.easeInOut(duration: 0.9)) {
            camera = .camera(FleetCamera.route(from: userLocation, to: vehicle.coordinate))
        }
    }

    private func backToFindCar() {
        mode = .findCar
        if let selected {
            withAnimation(.easeInOut(duration: 0.8)) { camera = .camera(FleetCamera.focus(on: selected.coordinate)) }
        }
    }

    /// 「我已抵達車輛」（Demo shortcut）：進入既有取車檢查。
    private func arrived() {
        store.arriveAtVehicle()
    }
}

// MARK: - 鏡頭

/// MapKit 3D 鏡頭預設：有 pitch 讓建築物立體，但不壓到看不見車輛 marker。
enum FleetCamera {
    /// 開啟 App：信義區概覽。
    static let overview = MapCamera(centerCoordinate: DemoFleet.overviewCenter, distance: 3300, heading: 20, pitch: 50)

    /// 選到車：鏡頭飛到車輛。中心稍微往南移，讓 marker 不被底部卡片遮住。
    static func focus(on coordinate: CLLocationCoordinate2D) -> MapCamera {
        let center = CLLocationCoordinate2D(latitude: coordinate.latitude - 0.0009, longitude: coordinate.longitude)
        return MapCamera(centerCoordinate: center, distance: 900, heading: 20, pitch: 60)
    }

    /// Find My Car：同時看到使用者與車輛，heading 朝向車輛。
    static func route(from origin: CLLocationCoordinate2D, to destination: CLLocationCoordinate2D) -> MapCamera {
        // 鏡頭朝向車輛（車在畫面上方、你在下方）。中心取兩者中點再略偏使用者，pitch 放緩、距離拉遠，
        // 讓藍點落在底部卡片之上、車輛落在上半部。
        let mid = CLLocationCoordinate2D(
            latitude: origin.latitude + (destination.latitude - origin.latitude) * 0.15,
            longitude: origin.longitude + (destination.longitude - origin.longitude) * 0.15
        )
        let meters = CLLocation(latitude: origin.latitude, longitude: origin.longitude)
            .distance(from: CLLocation(latitude: destination.latitude, longitude: destination.longitude))
        return MapCamera(centerCoordinate: mid, distance: max(1200, meters * 4.0), heading: bearing(from: origin, to: destination), pitch: 40)
    }

    private static func bearing(from a: CLLocationCoordinate2D, to b: CLLocationCoordinate2D) -> Double {
        let lat1 = a.latitude * .pi / 180, lat2 = b.latitude * .pi / 180
        let dLon = (b.longitude - a.longitude) * .pi / 180
        let y = sin(dLon) * cos(lat2)
        let x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dLon)
        return (atan2(y, x) * 180 / .pi + 360).truncatingRemainder(dividingBy: 360)
    }
}

// MARK: - 地圖

/// 原生 MapKit（SwiftUI `Map`）：3D 建築、車輛 annotation、Demo 使用者位置、示意步行路線。
private struct VehicleMapView: View {
    @Binding var camera: MapCameraPosition
    let vehicles: [NearbyVehicle]
    let selected: NearbyVehicle?
    let userLocation: CLLocationCoordinate2D
    let path: [CLLocationCoordinate2D]?
    let onSelect: (NearbyVehicle) -> Void

    var body: some View {
        Map(position: $camera, interactionModes: [.pan, .zoom, .rotate]) {
            if let path {
                MapPolyline(coordinates: path)
                    .stroke(Color.accentColor, style: StrokeStyle(lineWidth: 5, lineCap: .round, lineJoin: .round, dash: [1, 9]))
            }

            Annotation("", coordinate: userLocation, anchor: .center) {
                DemoLocationDot()
            }
            .annotationTitles(.hidden)

            ForEach(vehicles) { vehicle in
                Annotation("", coordinate: vehicle.coordinate, anchor: .bottom) {
                    VehicleMarker(vehicle: vehicle, isSelected: vehicle == selected) { onSelect(vehicle) }
                }
                .annotationTitles(.hidden)
            }
        }
        .mapStyle(.standard(elevation: .realistic, pointsOfInterest: .excludingAll))
        .mapControlVisibility(.hidden)
    }
}

/// Demo Location：外觀仿原生藍點，但**不是**真實 GPS（見 `DemoFleet.demoUserLocation`）。
private struct DemoLocationDot: View {
    var body: some View {
        ZStack {
            Circle().fill(Color.blue.opacity(0.18)).frame(width: 44, height: 44)
            Circle().fill(.white).frame(width: 22, height: 22).shadow(radius: 2)
            Circle().fill(Color.blue).frame(width: 16, height: 16)
        }
        .accessibilityLabel("目前位置（示範）")
    }
}

/// 車輛 marker：圓形車輛圖示；選中時放大並加上車牌標籤。
private struct VehicleMarker: View {
    let vehicle: NearbyVehicle
    let isSelected: Bool
    let onTap: () -> Void

    private var tint: Color { vehicle.isAvailable ? Color.accentColor : Color.gray }

    var body: some View {
        Button(action: onTap) {
            VStack(spacing: 2) {
                if isSelected {
                    Text(vehicle.plateNumber)
                        .font(.caption.weight(.bold))
                        .monospaced()
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(.regularMaterial, in: Capsule())
                }
                ZStack {
                    if isSelected {
                        Circle().stroke(tint.opacity(0.35), lineWidth: 6).frame(width: 46, height: 46)
                    }
                    Circle().fill(tint).frame(width: isSelected ? 40 : 32, height: isSelected ? 40 : 32)
                        .shadow(color: .black.opacity(0.25), radius: 3, y: 2)
                    Image(systemName: "car.fill")
                        .font(.system(size: isSelected ? 18 : 14, weight: .semibold))
                        .foregroundStyle(.white)
                }
                Triangle().fill(tint).frame(width: 10, height: 6).offset(y: -1)
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(vehicle.model) \(vehicle.plateNumber)，\(vehicle.status.label)")
    }

    private struct Triangle: Shape {
        func path(in rect: CGRect) -> Path {
            Path { p in
                p.move(to: CGPoint(x: rect.minX, y: rect.minY))
                p.addLine(to: CGPoint(x: rect.maxX, y: rect.minY))
                p.addLine(to: CGPoint(x: rect.midX, y: rect.maxY))
                p.closeSubpath()
            }
        }
    }
}

// MARK: - 底部卡片

private struct SheetCard<Content: View>: View {
    @ViewBuilder let content: Content
    var body: some View {
        content
            .padding(16)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            .shadow(color: .black.opacity(0.12), radius: 12, y: 4)
    }
}

/// 尚未選車：提示點選地圖上的車輛。
private struct NearbyHintCard: View {
    let count: Int
    var body: some View {
        SheetCard {
            HStack(spacing: 12) {
                Image(systemName: "mappin.and.ellipse")
                    .font(.title2)
                    .foregroundStyle(Color.accentColor)
                VStack(alignment: .leading, spacing: 2) {
                    Text("附近有 \(count) 台可租借車輛").font(.headline)
                    Text("點選地圖上的車輛查看資訊").font(.subheadline).foregroundStyle(.secondary)
                }
                Spacer()
            }
        }
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }
}

/// 選車後的車輛資訊：車款、車牌、位置、距離、步行時間、油量、狀態；主要按鈕「前往取車」。
private struct VehicleBottomSheet: View {
    let vehicle: NearbyVehicle
    let userLocation: CLLocationCoordinate2D
    let onClose: () -> Void
    let onGo: () -> Void

    var body: some View {
        SheetCard {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: "car.side.fill")
                        .font(.system(size: 30))
                        .foregroundStyle(Color.accentColor)
                        .frame(width: 56, height: 56)
                        .background(Color.accentColor.opacity(0.12), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    VStack(alignment: .leading, spacing: 3) {
                        Text(vehicle.model).font(.title3.weight(.semibold))
                        Text(vehicle.plateNumber).font(.subheadline.monospaced()).foregroundStyle(.secondary)
                        Text(vehicle.locationName).font(.footnote).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button(action: onClose) {
                        Image(systemName: "xmark.circle.fill")
                            .font(.title2)
                            .foregroundStyle(.tertiary)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("關閉")
                }

                // 兩列各兩個，390pt 寬度不截字
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 8) {
                        InfoChip(icon: "figure.walk", text: vehicle.distanceLabel(from: userLocation))
                        InfoChip(icon: "clock", text: vehicle.walkingLabel(from: userLocation))
                    }
                    HStack(spacing: 8) {
                        InfoChip(icon: "fuelpump.fill", text: "油量 \(vehicle.fuelPercent)%")
                        InfoChip(icon: vehicle.isAvailable ? "checkmark.circle.fill" : "minus.circle.fill",
                                 text: vehicle.status.label,
                                 tint: vehicle.isAvailable ? .green : .secondary)
                    }
                }

                Button(action: onGo) {
                    Text("前往取車")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(!vehicle.canPickup)

                if !vehicle.canPickup {
                    Text(vehicle.isAvailable ? "此車輛為地圖示範資料，請選擇 ABC-1234 進行取車。" : "此車輛目前租用中。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }
}

private struct InfoChip: View {
    let icon: String
    let text: String
    var tint: Color = .primary

    var body: some View {
        Label(text, systemImage: icon)
            .font(.caption.weight(.medium))
            .foregroundStyle(tint)
            .lineLimit(1)
            .minimumScaleFactor(0.8)
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(Color.primary.opacity(0.06), in: Capsule())
    }
}

/// Find My Car：顯示你 → 車輛的距離與步行時間；「我已抵達車輛」為比賽 Demo 捷徑，進入既有取車檢查。
private struct FindMyCarPanel: View {
    let vehicle: NearbyVehicle
    let userLocation: CLLocationCoordinate2D
    let onBack: () -> Void
    let onArrived: () -> Void

    var body: some View {
        SheetCard {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 12) {
                    Button(action: onBack) {
                        Image(systemName: "chevron.left")
                            .font(.headline)
                            .frame(width: 36, height: 36)
                            .background(Color.primary.opacity(0.06), in: Circle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("返回")
                    VStack(alignment: .leading, spacing: 2) {
                        Text("前往 \(vehicle.plateNumber)").font(.headline)
                        Text("\(vehicle.model) · \(vehicle.locationName)").font(.footnote).foregroundStyle(.secondary)
                    }
                    Spacer()
                }

                HStack(spacing: 16) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(vehicle.distanceLabel(from: userLocation)).font(.title2.weight(.semibold))
                        Text("直線距離").font(.caption).foregroundStyle(.secondary)
                    }
                    Divider().frame(height: 32)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(vehicle.walkingLabel(from: userLocation)).font(.title2.weight(.semibold))
                        Text("示意路線，非即時導航").font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                }

                Button(action: onArrived) {
                    Label("我已抵達車輛", systemImage: "checkmark.circle.fill")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)

                Text("抵達後會先進行取車前車況確認，建立這次租借的車況基準。")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }
}

#Preview("Find a Car") {
    NavigationStack { FindCarView() }
        .environment(RentalStore())
}

import CoreLocation
import MapKit
import SwiftUI

/// 尚未租借時的首頁：地圖為主體（使用者位置 + 後端模擬車輛），底部是車輛卡片。
/// FIND_CAR（選車 → 車輛資訊 → 開始租車＝建立 Session）→ FIND_MY_CAR（前往車輛 → 我已抵達 → 取車檢查）。
/// 使用者位置來自 `LocationService`（GPS 或手動選擇）；車輛位置是後端模擬資料（固定座標）。
struct FindCarView: View {
    @Environment(RentalStore.self) private var store
    @Environment(LocationService.self) private var location

    private enum Mode { case findCar, findMyCar }
    @State private var mode: Mode = .findCar
    @State private var selected: SimVehicle?
    @State private var camera: MapCameraPosition = .automatic
    @State private var isWorking = false
    @State private var actionError: String?
    @State private var showDetail = false
    @State private var didPlaceCamera = false

    private var userLocation: CLLocationCoordinate2D { location.coordinate ?? DemoFleet.fallbackUserLocation }

    var body: some View {
        ZStack(alignment: .bottom) {
            VehicleMapView(
                camera: $camera,
                vehicles: mode == .findMyCar ? (selected.map { [$0] } ?? []) : store.vehicles,
                selected: selected,
                userLocation: userLocation,
                userSource: location.isResolved ? location.source : nil,
                path: mode == .findMyCar ? selected.map { DemoFleet.walkingPath(from: userLocation, to: $0.coordinate) } : nil,
                onSelect: select
            )
            .ignoresSafeArea(edges: .bottom)

            Group {
                switch mode {
                case .findCar:
                    if let selected {
                        VehicleBottomSheet(
                            vehicle: selected, userLocation: userLocation, imageURL: imageURL(selected),
                            isWorking: isWorking, error: actionError,
                            onClose: { deselect() }, onDetail: { showDetail = true }, onStart: { startRental(selected) }
                        )
                    } else {
                        NearbyHintCard(
                            count: store.vehicles.filter(\.isAvailable).count,
                            loading: store.vehicles.isEmpty && store.vehiclesError == nil,
                            error: store.vehiclesError, locationLabel: locationLabel,
                            onReload: { Task { await store.loadVehicles() } }
                        )
                    }
                case .findMyCar:
                    if let selected {
                        FindMyCarPanel(vehicle: selected, userLocation: userLocation, isWorking: isWorking, error: actionError,
                                       onCancel: { cancelRental() }, onArrived: { store.arriveAtVehicle() })
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 12)
        }
        .animation(.snappy(duration: 0.3), value: selected)
        .animation(.snappy(duration: 0.3), value: mode == .findMyCar)
        .sheet(isPresented: $showDetail) {
            if let selected {
                VehicleDetailView(vehicle: selected, userLocation: userLocation, imageURL: imageURL(selected))
            }
        }
        // 置頂推薦車輛（不受定位距離限制），在地圖上方永遠可見
        .safeAreaInset(edge: .top) {
            if mode == .findCar {
                FeaturedVehiclesView(compact: true)
                    .padding(.horizontal, 16)
                    .padding(.top, 6)
            }
        }
        .task(id: store.resetGeneration) {
            await store.loadVehicles()
            restoreFromSession()
            if !didPlaceCamera {
                didPlaceCamera = true
                camera = .camera(FleetCamera.overview(center: userLocation))
            }
        }
        .onChange(of: location.coordinate?.latitude) { _, _ in
            // 定位更新（例如手動改位置）→ 鏡頭跟著移
            guard mode == .findCar, selected == nil else { return }
            withAnimation(.easeInOut(duration: 0.8)) { camera = .camera(FleetCamera.overview(center: userLocation)) }
        }
    }

    private var locationLabel: String {
        guard location.isResolved else { return "尚未取得定位（鏡頭先停在後備位置）" }
        return location.source == .manual ? "位置：\(location.locationName ?? "手動選擇")" : "位置：GPS 目前位置"
    }

    private func imageURL(_ vehicle: SimVehicle) -> URL? {
        guard let path = vehicle.imageUrl, let base = InspectionSyncService.normalizedBaseURL(store.apiBaseURL) else { return nil }
        return URL(string: path, relativeTo: base)?.absoluteURL
    }

    /// App 重開：Session 已建立但還沒按「我已抵達」→ 直接回到 Find My Car。
    private func restoreFromSession() {
        guard let session = store.session, session.state == "PICKUP_INSPECTION", mode == .findCar else { return }
        let vehicle = store.vehicles.first { $0.vehicleId == session.vehicle.vehicleId }
            ?? SimVehicle(vehicleId: session.vehicle.vehicleId, plate: session.vehicle.plate, model: session.vehicle.model ?? "車輛",
                          color: nil, seats: nil, vehicleType: nil, parkingSpot: nil, imageUrl: session.vehicle.imageUrl,
                          location: session.vehicle.location ?? GeoPoint(lat: nil, lng: nil), status: "RENTED",
                          odometerKm: session.startOdometerKm, fuelPercent: nil, pricing: session.vehicle.pricing,
                          featured: session.vehicle.featured ?? false, serviceNotice: session.serviceNotice, activeSessionId: session.sessionId)
        selected = vehicle
        mode = .findMyCar
        didPlaceCamera = true
        camera = .camera(FleetCamera.route(from: userLocation, to: vehicle.coordinate))
    }

    // MARK: - 狀態轉換

    private func select(_ vehicle: SimVehicle) {
        guard mode == .findCar else { return }
        selected = vehicle
        actionError = nil
        withAnimation(.easeInOut(duration: 0.8)) {
            camera = .camera(FleetCamera.focus(on: vehicle.coordinate))
        }
    }

    private func deselect() {
        selected = nil
        actionError = nil
        withAnimation(.easeInOut(duration: 0.8)) { camera = .camera(FleetCamera.overview(center: userLocation)) }
    }

    /// 「開始租車」：向後端建立 Session（車輛 → RENTED、Session → PICKUP_INSPECTION），成功後切到 Find My Car。
    private func startRental(_ vehicle: SimVehicle) {
        guard !isWorking else { return }
        isWorking = true
        actionError = nil
        Task {
            defer { isWorking = false }
            do {
                if vehicle.featured {
                    // 推薦車輛：不需要走到車旁，直接進取車檢查
                    try await store.startFeaturedVehicle(vehicle, location: location.body)
                    return
                }
                let session = try await RentalSessionService().create(vehicleID: vehicle.vehicleId, location: location.body, baseURL: store.apiBaseURL)
                store.apply(session)
                mode = .findMyCar
                withAnimation(.easeInOut(duration: 0.9)) {
                    camera = .camera(FleetCamera.route(from: userLocation, to: vehicle.coordinate))
                }
                await store.loadVehicles()
            } catch {
                actionError = error.localizedDescription
            }
        }
    }

    /// Find My Car「取消租車」：還沒開始取車檢查，後端允許取消（車輛回到 AVAILABLE）。
    private func cancelRental() {
        guard !isWorking else { return }
        isWorking = true
        actionError = nil
        Task {
            defer { isWorking = false }
            do {
                if let id = store.session?.sessionId {
                    _ = try await RentalSessionService().cancel(id: id, baseURL: store.apiBaseURL)
                }
                store.resetLocal()
            } catch {
                actionError = error.localizedDescription
            }
        }
    }
}

// MARK: - 鏡頭

/// MapKit 3D 鏡頭預設：有 pitch 讓建築物立體，但不壓到看不見車輛 marker。
enum FleetCamera {
    /// 開啟 App：以使用者位置為中心的概覽。
    static func overview(center: CLLocationCoordinate2D) -> MapCamera {
        MapCamera(centerCoordinate: center, distance: 2600, heading: 20, pitch: 50)
    }

    /// 選到車：鏡頭飛到車輛。中心稍微往南移，讓 marker 不被底部卡片遮住。
    static func focus(on coordinate: CLLocationCoordinate2D) -> MapCamera {
        let center = CLLocationCoordinate2D(latitude: coordinate.latitude - 0.0009, longitude: coordinate.longitude)
        return MapCamera(centerCoordinate: center, distance: 900, heading: 20, pitch: 60)
    }

    /// Find My Car：同時看到使用者與車輛，heading 朝向車輛。
    static func route(from origin: CLLocationCoordinate2D, to destination: CLLocationCoordinate2D) -> MapCamera {
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

/// 原生 MapKit（SwiftUI `Map`）：3D 建築、車輛 annotation、使用者位置、示意步行路線。
private struct VehicleMapView: View {
    @Binding var camera: MapCameraPosition
    let vehicles: [SimVehicle]
    let selected: SimVehicle?
    let userLocation: CLLocationCoordinate2D
    /// nil = 尚未定位（顯示後備位置，灰色）；gps / manual 顯示藍點。
    let userSource: LocationSource?
    let path: [CLLocationCoordinate2D]?
    let onSelect: (SimVehicle) -> Void

    var body: some View {
        Map(position: $camera, interactionModes: [.pan, .zoom, .rotate]) {
            if let path {
                MapPolyline(coordinates: path)
                    .stroke(Color.accentColor, style: StrokeStyle(lineWidth: 5, lineCap: .round, lineJoin: .round, dash: [1, 9]))
            }

            Annotation("", coordinate: userLocation, anchor: .center) {
                UserLocationDot(source: userSource)
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

/// 使用者位置：GPS 或手動選擇為藍點；尚未定位時為灰點（後備位置，不是真實定位）。
private struct UserLocationDot: View {
    let source: LocationSource?

    private var tint: Color { source == nil ? .gray : .blue }

    var body: some View {
        ZStack {
            Circle().fill(tint.opacity(0.18)).frame(width: 44, height: 44)
            Circle().fill(.white).frame(width: 22, height: 22).shadow(radius: 2)
            Circle().fill(tint).frame(width: 16, height: 16)
            if source == .manual {
                Image(systemName: "hand.point.up.left.fill").font(.system(size: 9)).foregroundStyle(.white)
            }
        }
        .accessibilityLabel(source == nil ? "後備位置（尚未定位）" : source == .manual ? "手動選擇的位置" : "目前位置")
    }
}

/// 車輛 marker：圓形車輛圖示；選中時放大並加上車牌標籤。
private struct VehicleMarker: View {
    let vehicle: SimVehicle
    let isSelected: Bool
    let onTap: () -> Void

    private var tint: Color { vehicle.isAvailable ? Color.accentColor : Color.gray }

    var body: some View {
        Button(action: onTap) {
            VStack(spacing: 2) {
                if isSelected || vehicle.featured {
                    Text(vehicle.plate)
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
        .accessibilityLabel("\(vehicle.model) \(vehicle.plate)，\(vehicle.statusLabel)")
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

struct SheetCard<Content: View>: View {
    @ViewBuilder let content: Content
    var body: some View {
        content
            .padding(16)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            .shadow(color: .black.opacity(0.12), radius: 12, y: 4)
    }
}

/// 尚未選車：提示點選地圖上的車輛；顯示定位來源與載入／錯誤狀態。
private struct NearbyHintCard: View {
    let count: Int
    let loading: Bool
    let error: String?
    let locationLabel: String
    let onReload: () -> Void

    var body: some View {
        SheetCard {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 12) {
                    Image(systemName: error == nil ? "mappin.and.ellipse" : "wifi.exclamationmark")
                        .font(.title2)
                        .foregroundStyle(error == nil ? Color.accentColor : .orange)
                    VStack(alignment: .leading, spacing: 2) {
                        if let error {
                            Text("無法取得車輛資料").font(.headline)
                            Text(error).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                        } else if loading {
                            Text("正在載入附近車輛…").font(.headline)
                        } else {
                            Text("附近有 \(count) 台可租借車輛").font(.headline)
                            Text("點選地圖上的車輛查看資訊").font(.subheadline).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    if error != nil {
                        Button("重試", action: onReload).buttonStyle(.bordered).controlSize(.small)
                    }
                }
                HStack(spacing: 6) {
                    Image(systemName: "location").font(.caption2)
                    Text(locationLabel).font(.caption)
                    Spacer()
                }
                .foregroundStyle(.secondary)
            }
        }
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }
}

/// 選車後的車輛資訊：車款、車牌、位置、距離、步行時間、油量、里程、狀態；主要按鈕「開始租車」。
private struct VehicleBottomSheet: View {
    let vehicle: SimVehicle
    let userLocation: CLLocationCoordinate2D
    let imageURL: URL?
    let isWorking: Bool
    let error: String?
    let onClose: () -> Void
    let onDetail: () -> Void
    let onStart: () -> Void

    var body: some View {
        SheetCard {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .top, spacing: 12) {
                    VehicleThumbnail(url: imageURL, size: 56)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(vehicle.model).font(.title3.weight(.semibold))
                        Text(vehicle.plate).font(.subheadline.monospaced()).foregroundStyle(.secondary)
                        Text(vehicle.location.name ?? "停放位置").font(.footnote).foregroundStyle(.secondary).lineLimit(2)
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

                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 8) {
                        InfoChip(icon: "figure.walk", text: vehicle.distanceLabel(from: userLocation))
                        InfoChip(icon: "clock", text: vehicle.walkingLabel(from: userLocation))
                        InfoChip(icon: "gauge.with.needle", text: "\(vehicle.odometerKm) km")
                    }
                    HStack(spacing: 8) {
                        if let fuel = vehicle.fuelPercent { InfoChip(icon: "fuelpump.fill", text: "油量 \(fuel)%") }
                        InfoChip(icon: vehicle.isAvailable ? "checkmark.circle.fill" : "minus.circle.fill",
                                 text: vehicle.statusLabel,
                                 tint: vehicle.isAvailable ? .green : .secondary)
                        if let price = vehicle.pricing?.hourlyTwd { InfoChip(icon: "dollarsign.circle", text: "NT$\(VehicleDetailView.money(price))/時") }
                    }
                }

                if let error {
                    Text(error).font(.footnote).foregroundStyle(.red)
                }

                HStack(spacing: 10) {
                    Button(action: onDetail) {
                        Label("詳細資訊", systemImage: "doc.text.magnifyingglass")
                            .font(.subheadline.weight(.semibold))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 6)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)

                    Button(action: onStart) {
                        HStack {
                            if isWorking { ProgressView().tint(.white) }
                            Text("開始租車").font(.headline)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(!vehicle.isAvailable || isWorking)
                }

                if !vehicle.isAvailable {
                    Text("此車輛目前\(vehicle.statusLabel)，暫時無法租借。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                if vehicle.featured {
                    Text("推薦車輛可直接開始使用；地圖上的位置為停放位置。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }
}

struct VehicleThumbnail: View {
    let url: URL?
    let size: CGFloat

    var body: some View {
        Group {
            if let url {
                AsyncImage(url: url) { phase in
                    if let image = phase.image {
                        image.resizable().scaledToFill()
                    } else {
                        placeholder
                    }
                }
            } else {
                placeholder
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private var placeholder: some View {
        Image(systemName: "car.side.fill")
            .font(.system(size: size * 0.5))
            .foregroundStyle(Color.accentColor)
            .frame(width: size, height: size)
            .background(Color.accentColor.opacity(0.12))
    }
}

struct InfoChip: View {
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

/// Find My Car：你 → 車輛的距離與步行時間；「我已抵達車輛」進入取車檢查；「取消租車」釋放車輛。
private struct FindMyCarPanel: View {
    let vehicle: SimVehicle
    let userLocation: CLLocationCoordinate2D
    let isWorking: Bool
    let error: String?
    let onCancel: () -> Void
    let onArrived: () -> Void

    var body: some View {
        SheetCard {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 12) {
                    Image(systemName: "car.fill")
                        .font(.headline)
                        .frame(width: 36, height: 36)
                        .background(Color.accentColor.opacity(0.12), in: Circle())
                    VStack(alignment: .leading, spacing: 2) {
                        Text("前往 \(vehicle.plate)").font(.headline)
                        Text("\(vehicle.model) · \(vehicle.location.name ?? "停放位置")").font(.footnote).foregroundStyle(.secondary).lineLimit(2)
                    }
                    Spacer()
                    Text("已預約").font(.caption2.weight(.semibold))
                        .padding(.horizontal, 6).padding(.vertical, 3)
                        .background(Color.green.opacity(0.15), in: Capsule())
                        .foregroundStyle(.green)
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

                if let error {
                    Text(error).font(.footnote).foregroundStyle(.red)
                }

                Button(action: onArrived) {
                    Label("我已抵達車輛，開始取車檢查", systemImage: "checkmark.circle.fill")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(isWorking)

                Button(role: .destructive, action: onCancel) {
                    Text(isWorking ? "處理中…" : "取消租車")
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(isWorking)

                Text("抵達後會先拍攝四個角度與車內照，建立這次租借的車況基準；完成後才正式開始租用。")
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
        .environment(LocationService())
}

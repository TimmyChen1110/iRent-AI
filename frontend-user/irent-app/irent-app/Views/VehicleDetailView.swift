import CoreLocation
import SwiftUI

/// 車輛資訊頁：車牌、車型圖、車款、乘坐人數、狀態、停車格、租金與里程費、費用試算、車況紀錄、「開始使用」。
struct VehicleDetailView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(RentalStore.self) private var store
    @Environment(LocationService.self) private var location
    let vehicle: SimVehicle
    let userLocation: CLLocationCoordinate2D?
    let imageURL: URL?

    @State private var isWorking = false
    @State private var error: String?
    @State private var records: VehicleRecords?
    @State private var recordsChecked = false

    private var hasActiveSessionHere: Bool { store.session?.vehicle.vehicleId == vehicle.vehicleId && store.phase != .findCar }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 10) {
                        Group {
                            if let imageURL {
                                AsyncImage(url: imageURL) { phase in
                                    if let image = phase.image {
                                        image.resizable().scaledToFill()
                                    } else if phase.error != nil {
                                        placeholder("無法載入圖片")
                                    } else {
                                        ProgressView().frame(maxWidth: .infinity)
                                    }
                                }
                            } else {
                                placeholder("尚未連線，無法載入圖片")
                            }
                        }
                        .frame(height: 200)
                        .frame(maxWidth: .infinity)
                        .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.md, style: .continuous))
                        HStack(spacing: 8) {
                            Text(vehicle.plate).font(.title2.weight(.bold)).monospaced()
                            Spacer()
                            Text(vehicle.statusLabel).font(.subheadline.weight(.semibold))
                                .foregroundStyle(vehicle.isAvailable ? .green : .secondary)
                        }
                        Text(vehicle.model).font(.headline)
                    }
                    .listRowInsets(EdgeInsets(top: 12, leading: 16, bottom: 12, trailing: 16))
                }
                Section("車輛") {
                    LabeledContent("車款", value: vehicle.model)
                    if let type = vehicle.vehicleType { LabeledContent("車輛類型", value: type) }
                    if let seats = vehicle.seats { LabeledContent("乘坐人數", value: "\(seats) 人") }
                    if let color = vehicle.color { LabeledContent("車輛顏色", value: color) }
                    LabeledContent("狀態") { Text(vehicle.statusLabel).foregroundStyle(vehicle.isAvailable ? .green : .secondary) }
                    LabeledContent("目前里程", value: "\(vehicle.odometerKm) km")
                    if let fuel = vehicle.fuelPercent { LabeledContent("油量", value: "\(fuel)%") }
                }
                Section("位置") {
                    if let spot = vehicle.parkingSpot { LabeledContent("停車格 / 路段", value: spot) }
                    LabeledContent("停放位置", value: vehicle.location.name ?? "—")
                    if let userLocation {
                        LabeledContent("與你的距離", value: vehicle.distanceLabel(from: userLocation))
                        LabeledContent("步行時間", value: vehicle.walkingLabel(from: userLocation))
                    } else {
                        LabeledContent("與你的距離", value: "尚未定位")
                    }
                }
                if let pricing = vehicle.pricing {
                    Section("租金與里程費") {
                        if let v = pricing.hourlyTwd { LabeledContent("租金", value: "NT$\(Self.money(v)) / 小時") }
                        if let v = pricing.perKmTwd { LabeledContent("里程費", value: "NT$\(Self.money(v)) / 公里") }
                        if let v = pricing.estimatedKmFeeTwd { LabeledContent("預估里程費", value: "NT$\(Self.money(v))") }
                        if let v = pricing.estimatedTotalTwd {
                            LabeledContent("預估總金額") { Text("NT$\(Self.money(v))").font(.headline) }
                        }
                        if let note = pricing.billingNote { Text(note).font(.footnote).foregroundStyle(.secondary) }
                    }
                }
                Section("車況紀錄") {
                    if let records, records.hasRecords {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("借車前").font(.subheadline.weight(.semibold))
                            photoStrip(records.before)
                            if !records.after.isEmpty {
                                Text("最近一次還車").font(.subheadline.weight(.semibold))
                                photoStrip(records.after)
                            }
                        }
                        if let note = records.recordNote { Text(note).font(.footnote).foregroundStyle(.secondary) }
                    } else if recordsChecked {
                        Text("尚無車況紀錄。取車時拍攝的照片會成為本次租借的車況基準。").font(.footnote).foregroundStyle(.secondary)
                    } else {
                        ProgressView()
                    }
                }
                Section {
                    if hasActiveSessionHere {
                        Label("你目前正在使用這台車（\(store.phase.title)）。關閉此頁即可繼續。", systemImage: "car.fill")
                            .font(.footnote).foregroundStyle(.secondary)
                    } else if store.session != nil {
                        Label("你已有進行中的租借，請先完成還車再租借其他車輛。", systemImage: "exclamationmark.triangle")
                            .font(.footnote).foregroundStyle(.orange)
                    } else {
                        AppButton(title: isWorking ? "處理中…" : "開始使用", systemImage: "play.circle.fill") { start() }
                            .disabled(!vehicle.isAvailable || isWorking)
                            .listRowInsets(EdgeInsets())
                            .listRowBackground(Color.clear)
                        if !vehicle.isAvailable {
                            Text("此車輛目前\(vehicle.statusLabel)，暫時無法租借。").font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                    if let error { Text(error).font(.footnote).foregroundStyle(.red) }
                }
                if let notice = vehicle.serviceNotice {
                    Section("服務說明") {
                        Label(notice, systemImage: "info.circle").font(.footnote).foregroundStyle(.secondary)
                    }
                }
            }
            .task {
                guard !recordsChecked else { return }
                records = try? await RentalSessionService().vehicleRecords(id: vehicle.vehicleId, baseURL: store.apiBaseURL)
                recordsChecked = true
            }
            .navigationTitle("\(vehicle.model) · \(vehicle.plate)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("關閉") { dismiss() } } }
        }
    }

    private func start() {
        isWorking = true
        error = nil
        Task {
            defer { isWorking = false }
            do {
                try await store.startFeaturedVehicle(vehicle, location: location.body)
                dismiss()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    private func photoStrip(_ photos: [VehicleRecords.Photo]) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(photos) { photo in
                    VStack(spacing: 3) {
                        RemoteThumb(path: photo.url, width: 120, height: 90)
                        Text(photo.angle.map { "\($0)角" } ?? "—").font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    static func money(_ v: Double) -> String {
        v == v.rounded() ? String(Int(v)) : String(format: "%.1f", v)
    }

    private func placeholder(_ text: String) -> some View {
        VStack(spacing: 6) {
            Image(systemName: "car.side.fill").font(.system(size: 40)).foregroundStyle(Color.accentColor)
            Text(text).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.accentColor.opacity(0.08))
    }
}

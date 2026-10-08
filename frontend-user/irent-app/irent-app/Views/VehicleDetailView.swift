import CoreLocation
import SwiftUI

/// 車輛詳細資訊頁（模擬車輛／Demo 測試車輛）：圖片、車牌、車款、乘坐人數、狀態、停車格、租金與里程費、預估費用、「開始使用」。
/// Demo 測試車輛另有「重設 Demo」（確認後封存 Session、車輛回可租借）。
struct VehicleDetailView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(RentalStore.self) private var store
    @Environment(LocationService.self) private var location
    let vehicle: SimVehicle
    let userLocation: CLLocationCoordinate2D?
    let imageURL: URL?

    @State private var isWorking = false
    @State private var error: String?
    @State private var showResetConfirm = false
    @State private var resetMessage: String?
    @State private var photoSet: DemoPhotoSet?
    @State private var photoSetChecked = false

    private var details: SimVehicle.Details? { vehicle.details }
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
                                placeholder("尚未設定 API 位址，無法載入圖片")
                            }
                        }
                        .frame(height: 200)
                        .frame(maxWidth: .infinity)
                        .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.md, style: .continuous))
                        HStack(spacing: 8) {
                            Text(vehicle.plate).font(.title2.weight(.bold)).monospaced()
                            if vehicle.isDemo {
                                Text("Demo Vehicle").font(.caption.weight(.bold))
                                    .padding(.horizontal, 8).padding(.vertical, 3)
                                    .background(Color.orange.opacity(0.18), in: Capsule()).foregroundStyle(.orange)
                            }
                            Spacer()
                            Text(vehicle.statusLabel).font(.subheadline.weight(.semibold))
                                .foregroundStyle(vehicle.isAvailable ? .green : .secondary)
                        }
                        Text(vehicle.model).font(.headline)
                        if let note = vehicle.imageNote {
                            Text(note).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    .listRowInsets(EdgeInsets(top: 12, leading: 16, bottom: 12, trailing: 16))
                }
                Section("車輛") {
                    LabeledContent("車款", value: vehicle.model)
                    if let type = details?.vehicleType { LabeledContent("車輛類型", value: type) }
                    if let seats = details?.seats { LabeledContent("乘坐人數", value: "\(seats) 人") }
                    if let color = details?.color { LabeledContent("車輛顏色", value: color) }
                    LabeledContent("狀態") { Text(vehicle.statusLabel).foregroundStyle(vehicle.isAvailable ? .green : .secondary) }
                    LabeledContent("目前里程", value: "\(vehicle.odometerKm) km")
                    if let fuel = vehicle.fuelPercent { LabeledContent("油量", value: "\(fuel)%") }
                }
                Section("位置") {
                    if let spot = details?.parkingSpot { LabeledContent("停車格 / 路段", value: spot) }
                    LabeledContent("停放位置", value: vehicle.location.name ?? "—")
                    if let userLocation {
                        LabeledContent("與你的距離", value: vehicle.distanceLabel(from: userLocation))
                    } else {
                        LabeledContent("與你的距離", value: "尚未定位")
                    }
                    if vehicle.isDemo {
                        Text(details?.pinnedNote ?? "不受 GPS 距離限制；地圖上的位置為固定示範位置，不代表車輛真的在你附近。")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
                if let pricing = details?.pricing {
                    Section("租金與里程費（示範數值）") {
                        if let v = pricing.hourlyTwd { LabeledContent("租金", value: "NT$\(Self.money(v)) / 小時") }
                        if let v = pricing.perKmTwd { LabeledContent("里程費", value: "NT$\(Self.money(v)) / 公里") }
                        if let v = pricing.estimatedKmFeeTwd { LabeledContent("預估里程費", value: "NT$\(Self.money(v))") }
                        if let v = pricing.estimatedTotalTwd {
                            LabeledContent("預估總金額") { Text("NT$\(Self.money(v))").font(.headline) }
                        }
                        Text(pricing.note ?? "示範數值，不會產生任何費用。").font(.footnote).foregroundStyle(.secondary)
                    }
                }
                if vehicle.isDemo {
                    Section("借車前／還車後照片（專案資料集）") {
                        if let photoSet {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("借車前（Before）· \(photoSet.before.count) 張").font(.subheadline.weight(.semibold))
                                photoStrip(photoSet.before)
                                Text("還車後（After）· \(photoSet.after.count) 張").font(.subheadline.weight(.semibold))
                                photoStrip(photoSet.after)
                            }
                            ForEach(photoSet.pairs) { pair in
                                LabeledContent(pair.angle) {
                                    VStack(alignment: .trailing, spacing: 1) {
                                        Text(pair.pairVerification == "VERIFIED" ? "配對已驗證（OCR 雙向一致）" : "Unverified Pair（待人工確認）")
                                            .foregroundStyle(pair.pairVerification == "VERIFIED" ? .green : .orange)
                                        if let r = pair.humanRelabel { Text("人工重標：\(r)").font(.caption2).foregroundStyle(.secondary) }
                                    }
                                    .font(.caption)
                                }
                            }
                            if let standin = photoSet.interiorStandin {
                                Text(standin.note).font(.footnote).foregroundStyle(.secondary)
                            }
                            Text("來源：比賽資料集（非公開），既有借／還紀錄；車牌由 Core ML OCR 驗證。可在取車／還車拍攝頁選「模式 B：預載 Demo 照片」。")
                                .font(.footnote).foregroundStyle(.secondary)
                        } else if photoSetChecked {
                            Text("此車輛沒有登記的借車前／還車後照片，只能即時拍攝（模式 A）。").font(.footnote).foregroundStyle(.secondary)
                        } else {
                            ProgressView()
                        }
                    }
                }
                Section("還車 AI 檢測") {
                    LabeledContent("判定來源") {
                        Text(vehicle.aiSourceLabel ?? vehicle.aiSource)
                            .multilineTextAlignment(.trailing)
                            .foregroundStyle(vehicle.isFixture ? .orange : .primary)
                    }
                    if vehicle.isFixture {
                        Text("此車輛為比賽示範固定劇本：還車後的車損／髒汙結果是預先寫定的示範資料，不是模型即時判定。")
                            .font(.footnote).foregroundStyle(.secondary)
                    } else {
                        Text("還車照片會送到後端 Gemini 模型級聯（Flash 快篩 → Pro 複核），與取車照逐角度比對。需要後端設定 GEMINI_API_KEY。")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
                Section {
                    if hasActiveSessionHere {
                        Label("你目前正在使用這台車（\(store.phase.title)）。關閉此頁即可繼續。", systemImage: "car.fill")
                            .font(.footnote).foregroundStyle(.secondary)
                    } else if store.session != nil {
                        Label("你已有進行中的租車 Session，請先完成或重設後再租借其他車輛。", systemImage: "exclamationmark.triangle")
                            .font(.footnote).foregroundStyle(.orange)
                    } else {
                        AppButton(title: isWorking ? "處理中…" : "開始使用", systemImage: "play.circle.fill") { start() }
                            .disabled(!vehicle.isAvailable || isWorking)
                            .listRowInsets(EdgeInsets())
                            .listRowBackground(Color.clear)
                        if !vehicle.isAvailable {
                            Text("此車輛目前\(vehicle.statusLabel)。\(vehicle.isDemo ? "若上一位展示者沒有還車，可用下方「重設 Demo」。" : "")")
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                    if let error { Text(error).font(.footnote).foregroundStyle(.red) }
                }
                if vehicle.isDemo {
                    Section("Demo 重設") {
                        Button(role: .destructive) { showResetConfirm = true } label: {
                            Label(isWorking ? "處理中…" : "重設 Demo（\(vehicle.plate) 回到可租借）", systemImage: "arrow.counterclockwise")
                        }
                        .disabled(isWorking)
                        if let resetMessage { Text(resetMessage).font(.footnote).foregroundStyle(.secondary) }
                        Text("封存這台車進行中的 Demo Session、車輛狀態改回 Available；不影響其他車輛與正式資料。")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
                Section {
                    Label(vehicle.dataNote ?? "模擬車輛資料，非真實 iRent 車隊。", systemImage: "info.circle")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .task {
                guard vehicle.isDemo, !photoSetChecked else { return }
                photoSet = try? await RentalSessionService().vehiclePhotos(id: vehicle.vehicleId, baseURL: store.apiBaseURL)
                photoSetChecked = true
            }
            .navigationTitle(vehicle.isDemo ? "Demo 測試車輛" : "\(vehicle.model) · \(vehicle.plate)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("關閉") { dismiss() } } }
            .confirmationDialog("確定要重設 Demo 車輛 \(vehicle.plate)？", isPresented: $showResetConfirm, titleVisibility: .visible) {
                Button("重設 Demo", role: .destructive) { reset() }
                Button("取消", role: .cancel) {}
            } message: {
                Text("進行中的 Demo Session 會被封存，車輛回到可租借狀態。")
            }
        }
    }

    private func start() {
        isWorking = true
        error = nil
        Task {
            defer { isWorking = false }
            do {
                try await store.startDemoVehicle(vehicle, location: location.body)
                dismiss()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    private func reset() {
        isWorking = true
        error = nil
        Task {
            defer { isWorking = false }
            do {
                try await store.resetDemoVehicle(vehicle)
                resetMessage = "已重設：\(vehicle.plate) 回到可租借。"
                dismiss()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    private func photoStrip(_ photos: [DemoPhotoSet.Photo]) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(photos) { photo in
                    VStack(spacing: 3) {
                        RemoteThumb(path: photo.url, width: 120, height: 90)
                        Text("\(photo.angle ?? "—") · \(photo.plateRecognition?.ocrText ?? "OCR 未讀到")")
                            .font(.caption2).foregroundStyle(.secondary).lineLimit(1)
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

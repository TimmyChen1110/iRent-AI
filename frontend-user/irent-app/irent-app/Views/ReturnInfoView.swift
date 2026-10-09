import SwiftUI

/// Phase 3 還車資訊確認：車牌、租車開始／還車時間、總使用時間（系統算）、起始／結束里程（使用者輸入）、
/// 總行駛里程（系統算）、還車位置。結束里程由後端再驗證一次（不可小於起始里程）。
struct ReturnInfoView: View {
    @Environment(RentalStore.self) private var store
    @Environment(LocationService.self) private var location

    @State private var endOdometerText = ""
    @State private var isSubmitting = false
    @State private var error: String?

    private var session: RentalSession? { store.session }
    private var endOdometer: Int? { Int(endOdometerText.trimmingCharacters(in: .whitespaces)) }
    private var localValidation: String? {
        guard let session else { return nil }
        guard !endOdometerText.isEmpty else { return nil }
        guard let endOdometer else { return "請輸入整數里程（km）" }
        if endOdometer < session.startOdometerKm { return "結束里程不可小於起始里程 \(session.startOdometerKm) km" }
        return nil
    }
    private var canSubmit: Bool { endOdometer != nil && localValidation == nil && !isSubmitting }

    var body: some View {
        if let session {
            Form {
                Section("車輛") {
                    LabeledContent("車牌", value: session.vehicle.plate)
                    LabeledContent("車型", value: session.vehicle.model ?? "—")
                }
                Section("時間") {
                    LabeledContent("租車開始時間", value: Self.format(session.startedDate))
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        LabeledContent("還車時間", value: Self.format(context.date))
                        LabeledContent("總使用時間", value: Self.duration(from: session.startedDate, to: context.date))
                    }
                    Text("使用時間＝還車時間 − 租車開始時間；最終以後端確認時間為準。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("里程") {
                    LabeledContent("起始里程", value: "\(session.startOdometerKm) km")
                    HStack {
                        Text("結束里程")
                        Spacer()
                        TextField("例如 \(session.startOdometerKm + 12)", text: $endOdometerText)
                            .keyboardType(.numberPad)
                            .multilineTextAlignment(.trailing)
                            .frame(maxWidth: 160)
                        Text("km").foregroundStyle(.secondary)
                    }
                    LabeledContent("總行駛里程") {
                        if let endOdometer, localValidation == nil {
                            Text("\(endOdometer - session.startOdometerKm) km")
                        } else {
                            Text("—").foregroundStyle(.secondary)
                        }
                    }
                    if let localValidation {
                        Text(localValidation).font(.footnote).foregroundStyle(.red)
                    }
                    Button {
                        endOdometerText = "\(session.startOdometerKm + 12)"
                    } label: {
                        Label("使用系統估算值（起始 + 12 km）", systemImage: "wand.and.stars")
                    }
                    Text("請依儀表板里程輸入；若無法確認可使用系統估算值。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                if let pricing = session.vehicle.pricing, pricing.hourlyTwd != nil || pricing.perKmTwd != nil {
                    Section("費用明細") {
                        TimelineView(.periodic(from: .now, by: 1)) { context in
                            let seconds = Int(context.date.timeIntervalSince(session.startedDate ?? context.date))
                            let hours = max(1, Int((Double(max(seconds, 0)) / 3600).rounded(.up)))
                            let km = (endOdometer != nil && localValidation == nil) ? (endOdometer! - session.startOdometerKm) : nil
                            let timeFee = (pricing.hourlyTwd ?? 0) * Double(hours)
                            let kmFee = km.map { (pricing.perKmTwd ?? 0) * Double($0) }
                            LabeledContent("時間費", value: "NT$\(VehicleDetailView.money(timeFee))（\(hours) 小時 × NT$\(VehicleDetailView.money(pricing.hourlyTwd ?? 0))）")
                            LabeledContent("里程費") {
                                if let kmFee, let km { Text("NT$\(VehicleDetailView.money(kmFee))（\(km) km × NT$\(VehicleDetailView.money(pricing.perKmTwd ?? 0))）") }
                                else { Text("輸入結束里程後計算").foregroundStyle(.secondary) }
                            }
                            LabeledContent("合計") { Text("NT$\(VehicleDetailView.money(timeFee + (kmFee ?? 0)))").font(.headline) }
                        }
                        Text(pricing.billingNote ?? "費用為試算，不會扣款").font(.footnote).foregroundStyle(.secondary)
                    }
                }
                Section("還車位置") {
                    if let coordinate = location.coordinate {
                        LabeledContent("來源", value: location.source == .manual ? "手動選擇" : "目前位置")
                        LabeledContent("位置", value: location.locationName ?? "—")
                        LabeledContent("座標", value: String(format: "%.5f, %.5f", coordinate.latitude, coordinate.longitude))
                    } else if let start = session.returnLocation?.coordinate ?? session.startLocation?.coordinate {
                        LabeledContent("位置", value: String(format: "%.5f, %.5f（沿用租車位置）", start.latitude, start.longitude))
                    } else {
                        Text("尚未取得定位；還車位置將留空。").font(.footnote).foregroundStyle(.secondary)
                    }
                }
                Section {
                    AppButton(title: isSubmitting ? "送出中…" : "確認還車資訊，開始拍照", systemImage: "camera.fill") { submit() }
                        .disabled(!canSubmit)
                        .listRowInsets(EdgeInsets())
                        .listRowBackground(Color.clear)
                    if let error {
                        Text(error).font(.footnote).foregroundStyle(.red)
                    }
                    Text("確認後進入還車拍攝：四個外觀角度與一張車內照，每張都會在手機上先檢查車牌、角度與品質。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                CancelReturnSection(disabled: isSubmitting)
            }
            .onAppear {
                if endOdometerText.isEmpty, let end = session.endOdometerKm { endOdometerText = "\(end)" }
            }
            .task {
                // 舊版返回鍵可能讓本機停在這頁、後端卻已完成檢測：開頁時就同步，直接前往對應畫面
                if !store.canEditReturnInfo { _ = await store.leaveReturnInfoIfPassed() }
            }
        } else {
            ContentUnavailableView("沒有進行中的租車", systemImage: "car", description: Text("請回到地圖重新開始。"))
        }
    }

    private func submit() {
        guard let session, let endOdometer else { return }
        isSubmitting = true
        error = nil
        Task {
            defer { isSubmitting = false }
            do {
                let updated = try await RentalSessionService().returnInfo(id: session.sessionId, endOdometerKm: endOdometer,
                                                                        location: location.body, baseURL: store.apiBaseURL)
                store.apply(updated)
            } catch {
                if await store.leaveReturnInfoIfPassed() { return }
                self.error = error.localizedDescription
            }
        }
    }

    static func format(_ date: Date?) -> String {
        guard let date else { return "—" }
        return date.formatted(date: .numeric, time: .shortened)
    }

    static func duration(from start: Date?, to end: Date) -> String {
        guard let start else { return "—" }
        return durationLabel(seconds: Int(end.timeIntervalSince(start)))
    }

    static func durationLabel(seconds: Int) -> String {
        let s = max(0, seconds)
        let h = s / 3600, m = (s % 3600) / 60, sec = s % 60
        if h > 0 { return String(format: "%d 小時 %02d 分 %02d 秒", h, m, sec) }
        return String(format: "%d 分 %02d 秒", m, sec)
    }
}

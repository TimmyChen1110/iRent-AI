import PhotosUI
import SwiftUI

struct ContentView: View {
    @Environment(RentalStore.self) private var store
    @Environment(LocationService.self) private var location
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            Group {
                switch store.phase {
                case .findCar:
                    if location.isResolved {
                        FindCarView().id(store.resetGeneration)
                    } else {
                        LocationPermissionView()
                    }
                case .readyForPickup:
                    InspectionChecklistView(stage: .pickup)
                case .pickupComplete:
                    PickupCompleteView()
                case .activeRental:
                    ActiveRentalView()
                case .returnInfo:
                    ReturnInfoView()
                case .readyForReturn:
                    InspectionChecklistView(stage: .`return`)
                case .inspectionResult:
                    InspectionResultView()
                case .completed:
                    ReturnCompleteView()
                }
            }
            .navigationTitle(store.phase == .findCar && !location.isResolved ? "定位" : store.phase.title)
            .navigationBarTitleDisplayMode(store.phase == .findCar ? .inline : .automatic)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("設定", systemImage: "gear") { showSettings = true }
                }
            }
            .sheet(isPresented: $showSettings) {
                SettingsView()
            }
            .task {
                // 重新開啟 App：以後端 Session 狀態為準恢復畫面，再補傳離線照片
                await store.restoreSession()
                await PendingUploadSync().run(for: store)
            }
        }
    }
}

// MARK: - 取車／還車導引拍攝清單

private struct InspectionChecklistView: View {
    @Environment(RentalStore.self) private var store
    let stage: InspectionStage
    @State private var isPreloading = false
    @State private var preloadError: String?
    @State private var photoSet: DemoPhotoSet?

    private var canPreload: Bool { photoSet != nil && !(store.session?.isPreloaded(stage) ?? false) && store.completedShots(for: stage) == 0 }

    var body: some View {
        List {
            if let label = store.session?.captureModeLabel(stage) {
                Section {
                    Label(label, systemImage: (store.session?.isPreloaded(stage) ?? false) ? "photo.on.rectangle.angled" : "camera.viewfinder")
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle((store.session?.isPreloaded(stage) ?? false) ? .orange : .secondary)
                }
            } else if photoSet != nil {
                Section("選擇操作方式") {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("模式 A：即時拍攝 — 用手機相機依序拍攝（下方清單）", systemImage: "camera.viewfinder")
                        Label("模式 B：預載 Demo 照片 — 使用專案內已驗證的\(stage == .pickup ? "借車前" : "還車後")照片，不需要實體車輛", systemImage: "photo.on.rectangle.angled")
                    }
                    .font(.footnote)
                    Button {
                        preload()
                    } label: {
                        HStack {
                            Label(stage == .pickup ? "使用預載借車前照片（模式 B）" : "使用預載還車後照片（模式 B）", systemImage: "square.and.arrow.down.on.square")
                                .fontWeight(.semibold)
                            if isPreloading { Spacer(); ProgressView() }
                        }
                    }
                    .disabled(!canPreload || isPreloading)
                    if let preloadError { Text(preloadError).font(.footnote).foregroundStyle(.red) }
                    Text("預載照片會明確標示為「資料集照片」，不會呈現為當下拍攝；AI 檢測與即時拍攝走同一條 pipeline。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            Section {
                VStack(alignment: .leading, spacing: 6) {
                    Text("\(store.rental.carName) · \(store.rental.plateNumber)")
                        .font(.headline)
                    Text(stage == .pickup
                         ? "取車檢查會建立這次租借的車況基準。請依序拍攝四個外觀角度與一張車內照。"
                         : "還車檢查會與取車時的車況基準比對。請依序拍攝四個外觀角度與一張車內照。")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("每張照片都會在手機上即時檢查車牌、角度與品質；不合格會請你重拍。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    if let session = store.session {
                        Text("Session \(session.sessionId) · \(session.state)")
                            .font(.caption2.monospaced())
                            .foregroundStyle(.tertiary)
                    }
                }
                .padding(.vertical, 4)
                SyncStatusRow(stage: stage)
            }

            Section {
                ForEach(InspectionShot.exterior) { shot in
                    ShotRow(stage: stage, shot: shot)
                }
            } header: {
                HStack {
                    Text("外觀")
                    Spacer()
                    Text("\(store.exteriorCount(stage)) / \(InspectionShot.exterior.count)")
                        .monospacedDigit()
                }
            }

            Section {
                ShotRow(stage: stage, shot: .interior)
            } header: {
                HStack {
                    Text("車內")
                    Spacer()
                    Text("\(store.interiorCount(stage)) / 1")
                        .monospacedDigit()
                }
            }

            if store.isComplete(stage) {
                Section {
                    NavigationLink {
                        InspectionSummaryView(stage: stage)
                    } label: {
                        Label(stage == .pickup ? "檢視並完成取車檢查" : "檢視並完成還車拍攝", systemImage: "checkmark.seal")
                            .fontWeight(.semibold)
                    }
                }
            } else if let next = store.nextShot(for: stage) {
                Section {
                    NavigationLink {
                        CaptureView(stage: stage, shot: next)
                    } label: {
                        Label("拍攝下一張：\(next.title)", systemImage: "camera.fill")
                            .fontWeight(.semibold)
                    }
                }
            }
        }
        .task { await loadPhotoSet() }
    }

    private func loadPhotoSet() async {
        guard let session = store.session, session.vehicle.category == "demo", photoSet == nil else { return }
        photoSet = try? await RentalSessionService().vehiclePhotos(id: session.vehicle.vehicleId, baseURL: store.apiBaseURL)
    }

    private func preload() {
        isPreloading = true
        preloadError = nil
        Task {
            defer { isPreloading = false }
            do { try await store.preloadDemoPhotos(stage: stage) } catch { preloadError = error.localizedDescription }
        }
    }
}

private struct ShotRow: View {
    @Environment(RentalStore.self) private var store
    let stage: InspectionStage
    let shot: InspectionShot

    var body: some View {
        let photo = store.photo(for: stage, shot: shot)
        let remote = store.session?.remotePhoto(stage, shot)
        NavigationLink {
            CaptureView(stage: stage, shot: shot)
        } label: {
            HStack(spacing: 12) {
                if let photo, let image = PhotoStore().image(named: photo.fileName) {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFill()
                        .frame(width: 56, height: 42)
                        .clipShape(.rect(cornerRadius: 6))
                } else if photo == nil, let remote, let url = remoteURL(remote.url) {
                    AsyncImage(url: url) { phase in
                        if let image = phase.image { image.resizable().scaledToFill() } else { Color.secondary.opacity(0.15) }
                    }
                    .frame(width: 56, height: 42)
                    .clipShape(.rect(cornerRadius: 6))
                } else {
                    Image(systemName: shot.systemImage)
                        .frame(width: 56, height: 42)
                        .foregroundStyle(.secondary)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(shot.title)
                    if let photo {
                        Text(uploadLabel(photo))
                            .font(.caption)
                            .foregroundStyle(photo.uploadError == nil ? Color.secondary : Color.red)
                    } else if let remote, remote.preloaded == true {
                        Text(remote.interiorStandin == true ? "預載 · 車內佔位照（其他車輛，非本車）" : "預載 Demo 照片（資料集，非當下拍攝）")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
                Spacer()
                if photo != nil || remote != nil {
                    Label("已通過", systemImage: "checkmark.circle.fill")
                        .labelStyle(.iconOnly)
                        .foregroundStyle(.green)
                } else {
                    Text("待拍攝").foregroundStyle(.secondary)
                }
            }
        }
    }

    private func uploadLabel(_ photo: CapturedPhoto) -> String {
        if let error = photo.uploadError { return "上傳被拒：\(error)" }
        return photo.uploadedAt == nil ? "已拍攝 · 待上傳" : "已拍攝 · 已同步"
    }

    private func remoteURL(_ path: String?) -> URL? {
        guard let path, let base = InspectionSyncService.normalizedBaseURL(store.apiBaseURL) else { return nil }
        return URL(string: path, relativeTo: base)?.absoluteURL
    }
}

/// 拍攝完成 ≠ 伺服器已收到：這一列獨立顯示同步狀態。
private struct SyncStatusRow: View {
    @Environment(RentalStore.self) private var store
    let stage: InspectionStage

    var body: some View {
        let total = store.completedShots(for: stage)
        let uploaded = store.uploadedCount(for: stage)
        let pending = store.pendingUploads(for: stage)
        HStack {
            if store.isSyncing {
                ProgressView().controlSize(.small)
                Text("同步中…")
            } else if total == 0, store.isRemoteComplete(stage) {
                Image(systemName: "photo.on.rectangle.angled").foregroundStyle(.orange)
                Text("後端已收到 5 張預載 Demo 照片")
            } else if total == 0 {
                Image(systemName: "icloud").foregroundStyle(.secondary)
                Text("尚未拍攝")
            } else if pending == 0 {
                Image(systemName: "checkmark.icloud.fill").foregroundStyle(.green)
                Text("已同步 \(uploaded) / \(total)")
            } else {
                Image(systemName: "icloud.slash").foregroundStyle(.orange)
                Text("待上傳 \(pending) 張（已拍攝照片保存在手機，連線後自動重送）")
            }
            Spacer()
            if pending > 0 && !store.isSyncing {
                Button("重試") { Task { await PendingUploadSync().run(for: store) } }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
            }
        }
        .font(.footnote)
    }
}

// MARK: - 確認頁

private struct InspectionSummaryView: View {
    @Environment(RentalStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let stage: InspectionStage

    var body: some View {
        List {
            Section(stage == .pickup ? "取車照片" : "還車照片") {
                if let session = store.session, session.isPreloaded(stage) {
                    Label("預載 Demo 照片（資料集，非當下拍攝）", systemImage: "photo.on.rectangle.angled").font(.footnote).foregroundStyle(.orange)
                    ForEach(session.remotePhotos(stage)) { remote in
                        HStack {
                            RemoteThumb(path: remote.url, width: 96, height: 72)
                            VStack(alignment: .leading) {
                                Text(remote.angle)
                                Text(remote.interiorStandin == true ? "車內佔位照（非本車）" : "資料集照片").font(.caption).foregroundStyle(.orange)
                            }
                        }
                    }
                }
                ForEach(InspectionShot.allCases) { shot in
                    if let photo = store.photo(for: stage, shot: shot) {
                        HStack {
                            Image(uiImage: PhotoStore().image(named: photo.fileName) ?? UIImage())
                                .resizable()
                                .scaledToFill()
                                .frame(width: 96, height: 72)
                                .clipShape(.rect(cornerRadius: 8))
                            VStack(alignment: .leading) {
                                Text(shot.title)
                                Text(shot.isInterior ? "車內照" : (photo.result.plateText ?? store.rental.plateNumber))
                                    .foregroundStyle(.secondary)
                                Text(photo.uploadedAt == nil ? "待上傳" : "已同步")
                                    .font(.caption)
                                    .foregroundStyle(photo.uploadedAt == nil ? .orange : .green)
                            }
                        }
                    }
                }
            }

            Section {
                Button(stage == .pickup ? "完成取車檢查" : "完成還車拍攝，開始 AI 檢測") {
                    store.confirm(stage: stage)
                    // 這頁是從清單 push 進來的；phase 改變只會換掉 NavigationStack 的根畫面，
                    // 不會自動 pop，若不 dismiss 使用者會停在這頁看起來「沒反應」（真機實測）。
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
                Text(stage == .pickup
                     ? "完成後這些照片會成為還車時的車況比對依據。"
                     : "後端收齊 5 張照片後會與取車基準逐角度比對，結果會顯示在下一頁。")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle("確認\(stage.title)")
        .task { await PendingUploadSync().run(for: store) }
    }
}

// MARK: - 取車檢查完成（Pickup Baseline Established）→ 後端驗證照片齊全後才 RENTED

private struct PickupCompleteView: View {
    @Environment(RentalStore.self) private var store
    @State private var isStarting = false
    @State private var error: String?

    var body: some View {
        List {
            Section {
                CompletionHeader(
                    icon: "checkmark.seal.fill",
                    tint: .green,
                    title: "取車檢查完成",
                    subtitle: "\(store.rental.carName)\n\(store.rental.plateNumber)"
                )
            }
            Section {
                LabeledContent("外觀照片", value: "\(store.exteriorCount(.pickup)) / 4")
                LabeledContent("車內照片", value: "\(store.interiorCount(.pickup)) / 1")
                LabeledContent("車況基準", value: baselineLabel)
                if let label = store.session?.captureModeLabel(.pickup) {
                    LabeledContent("照片來源", value: label)
                }
                SyncStatusRow(stage: .pickup)
            }
            Section {
                Text("這些照片將作為還車時的車況比對依據。按「開始租借」後由後端確認 5 張照片都已收到，才正式進入租用中。")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Button {
                    startRental()
                } label: {
                    HStack {
                        Text("開始租借")
                        if isStarting { Spacer(); ProgressView() }
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isStarting || store.pendingUploads(for: .pickup) > 0)
                if let error {
                    Text(error).font(.footnote).foregroundStyle(.red)
                }
            }
        }
        .task { await PendingUploadSync().run(for: store) }
    }

    private var baselineLabel: String {
        if let remote = store.remoteStatus, remote.pickup.complete { return "已建立" }
        return store.pendingUploads(for: .pickup) == 0 ? "已建立" : "同步後建立"
    }

    private func startRental() {
        guard let session = store.session else { error = "找不到租車 Session，請回到地圖重新開始。"; return }
        isStarting = true
        error = nil
        Task {
            defer { isStarting = false }
            await PendingUploadSync().run(for: store)
            do {
                let updated = try await RentalSessionService().pickupComplete(id: session.sessionId, baseURL: store.apiBaseURL)
                store.apply(updated)
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}

// MARK: - 租用中

private struct ActiveRentalView: View {
    @Environment(RentalStore.self) private var store
    @Environment(LocationService.self) private var location
    @State private var isInitiating = false
    @State private var error: String?

    var body: some View {
        List {
            Section {
                VStack(spacing: 12) {
                    HStack(spacing: 14) {
                        Image(systemName: "car.fill")
                            .font(.system(size: 30))
                            .foregroundStyle(Color.accentColor)
                            .frame(width: 60, height: 60)
                            .background(Color.accentColor.opacity(0.12), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                        VStack(alignment: .leading, spacing: 3) {
                            Text(store.rental.carName).font(.title3.weight(.semibold))
                            Text(store.rental.plateNumber).font(.subheadline.monospaced()).foregroundStyle(.secondary)
                            Label("租用中 · RENTED", systemImage: "circle.fill")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.green)
                        }
                        Spacer()
                    }
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        VStack(spacing: 2) {
                            Text(ReturnInfoView.duration(from: store.session?.startedDate, to: context.date))
                                .font(.system(size: 34, weight: .bold, design: .rounded))
                                .monospacedDigit()
                            Text("已使用時間").font(.caption).foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity)
                    }
                }
                .padding(.vertical, 6)
            }
            Section("租車資訊") {
                LabeledContent("租車開始時間", value: ReturnInfoView.format(store.session?.startedDate))
                LabeledContent("起始里程", value: store.session.map { "\($0.startOdometerKm) km" } ?? "—")
                LabeledContent("起始位置") {
                    if let start = store.session?.startLocation?.coordinate {
                        Text(String(format: "%.5f, %.5f", start.latitude, start.longitude)).monospacedDigit()
                    } else {
                        Text("未記錄").foregroundStyle(.secondary)
                    }
                }
                LabeledContent("Session", value: store.session?.sessionId ?? "—")
                LabeledContent("車況基準", value: "已建立（取車照 5 張）")
            }
            if let session = store.session, !session.remotePhotos(.pickup).isEmpty {
                Section("借車前車況（取車照）") {
                    if let label = session.captureModeLabel(.pickup) {
                        Text(label).font(.footnote).foregroundStyle(session.isPreloaded(.pickup) ? .orange : .secondary)
                    }
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 10) {
                            ForEach(session.remotePhotos(.pickup)) { remote in
                                VStack(spacing: 4) {
                                    RemoteThumb(path: remote.url, width: 140, height: 105)
                                    Text(remote.interiorStandin == true ? "車內（佔位，非本車）" : remote.angle).font(.caption2).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    Text("還車時 AI 會以這些照片為基準逐角度比對。").font(.footnote).foregroundStyle(.secondary)
                }
            }
            Section {
                Text("模擬租車：此為 Demo 流程，不涉及真實車門、計費或合約。")
                    .font(.footnote).foregroundStyle(.secondary)
                if let error { Text(error).font(.footnote).foregroundStyle(.red) }
                AppButton(title: isInitiating ? "處理中…" : "我要還車", systemImage: "arrow.uturn.backward.circle.fill") { beginReturn() }
                    .disabled(isInitiating)
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
            }
        }
        .task {
            // 回到此頁時刷新一次後端狀態（例如另一端已改變）
            if let id = store.session?.sessionId, let s = try? await RentalSessionService().get(id: id, baseURL: store.apiBaseURL) {
                store.apply(s)
            }
        }
    }

    private func beginReturn() {
        guard let session = store.session else { return }
        isInitiating = true
        error = nil
        Task {
            defer { isInitiating = false }
            do {
                let updated = try await RentalSessionService().initiateReturn(id: session.sessionId, location: location.body, baseURL: store.apiBaseURL)
                store.apply(updated)
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}

// MARK: - 還車完成（RETURNED）

private struct ReturnCompleteView: View {
    @Environment(RentalStore.self) private var store
    @State private var result: InspectionResult?

    var body: some View {
        List {
            Section {
                CompletionHeader(
                    icon: "checkmark.circle.fill",
                    tint: .accentColor,
                    title: "還車完成",
                    subtitle: "\(store.rental.carName)\n\(store.rental.plateNumber)"
                )
            }
            if let session = store.session {
                Section("這次租借") {
                    LabeledContent("租車開始", value: ReturnInfoView.format(session.startedDate))
                    LabeledContent("還車時間", value: ReturnInfoView.format(session.returnedDate))
                    LabeledContent("總使用時間", value: session.usedSeconds.map { ReturnInfoView.durationLabel(seconds: $0) } ?? "—")
                    LabeledContent("里程", value: "\(session.startOdometerKm) → \(session.endOdometerKm.map(String.init) ?? "—") km")
                    LabeledContent("總行駛里程", value: session.distanceKm.map { "\($0) km" } ?? "—")
                }
                Section("AI 影像檢測") {
                    LabeledContent("結果", value: result?.overallLabel ?? "已完成")
                    LabeledContent("車牌比對", value: result?.plateCheck.label ?? "—")
                    LabeledContent("判定來源") {
                        Text(result?.aiSourceLabel ?? session.aiSourceLabel ?? "—")
                            .multilineTextAlignment(.trailing)
                            .foregroundStyle((result?.isFixture ?? session.isFixture) ? .orange : .primary)
                    }
                    if session.reviewRequired == true {
                        Label("此次還車已轉營運人員人工複核（有 AI 檢出的異常或車牌需確認）。", systemImage: "person.badge.clock")
                            .font(.footnote).foregroundStyle(.orange)
                    } else {
                        Label("未檢出異常，無需人工複核。", systemImage: "checkmark.shield")
                            .font(.footnote).foregroundStyle(.green)
                    }
                }
            }
            Section {
                Text("車輛狀態已更新為「可租借」。感謝使用 iRent 模擬租車 Demo。")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Button("完成") {
                    PhotoStore().removeAll()
                    store.finishRental()
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .task {
            if let id = store.session?.sessionId {
                result = try? await RentalSessionService().inspection(id: id, baseURL: store.apiBaseURL)
            }
        }
    }
}

/// 後端供圖的縮圖（/photos/...），用設定頁的 API Base URL 解析。
struct RemoteThumb: View {
    @Environment(RentalStore.self) private var store
    let path: String?
    let width: CGFloat
    let height: CGFloat

    var body: some View {
        Group {
            if let path, let base = InspectionSyncService.normalizedBaseURL(store.apiBaseURL), let url = URL(string: path, relativeTo: base)?.absoluteURL {
                AsyncImage(url: url) { phase in
                    if let image = phase.image { image.resizable().scaledToFill() } else { Color.secondary.opacity(0.15) }
                }
            } else {
                Color.secondary.opacity(0.15)
            }
        }
        .frame(width: width, height: height)
        .clipShape(.rect(cornerRadius: 8))
    }
}

private struct CompletionHeader: View {
    let icon: String
    let tint: Color
    let title: String
    let subtitle: String

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 48))
                .foregroundStyle(tint)
            Text(title).font(.title2.bold())
            Text(subtitle)
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 12)
    }
}

// MARK: - 設定

private struct SettingsView: View {
    @Environment(RentalStore.self) private var store
    @Environment(LocationService.self) private var location
    @Environment(\.dismiss) private var dismiss
    @State private var restarting = false
    @State private var restartMessage: String?
    @State private var connectionMessage: String?
    @State private var testingConnection = false

    var body: some View {
        @Bindable var store = store
        NavigationStack {
            Form {
                Section("同步服務") {
                    TextField("API Base URL", text: $store.apiBaseURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    if let url = InspectionSyncService.normalizedBaseURL(store.apiBaseURL) {
                        Text("實際連線位址：\(url.absoluteString)")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    } else {
                        Text("位址無法解析。請輸入 Mac 的區網 IP，例如 http://192.168.1.10:8000（localhost 代表 iPhone 自己）。")
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }
                    Button {
                        Task { await testConnection() }
                    } label: {
                        HStack {
                            Text("測試連線")
                            if testingConnection { Spacer(); ProgressView() }
                        }
                    }
                    .disabled(testingConnection)
                    if let connectionMessage {
                        Text(connectionMessage).font(.footnote).foregroundStyle(.secondary)
                    }
                }
                Section {
                    Toggle("Demo 模式（固定驗證劇本）", isOn: $store.demoMode)
                    Text(store.demoMode
                         ? "拍攝驗證走固定劇本：取車左前第一次失敗、還車右後第一次失敗，其餘通過；不執行 Core ML。"
                         : "拍攝驗證使用裝置端 Core ML（PlateDetector / PlateOCR / ViewClassifier）。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                } header: {
                    Text("拍攝驗證")
                }
                Section("定位") {
                    if let coordinate = location.coordinate {
                        LabeledContent("來源", value: location.source == .manual ? "手動選擇" : "GPS")
                        LabeledContent("位置", value: location.locationName ?? "—")
                        LabeledContent("座標", value: String(format: "%.5f, %.5f", coordinate.latitude, coordinate.longitude))
                        Button("重新選擇位置") { location.clear(); dismiss() }
                    } else {
                        Text("尚未取得定位。").foregroundStyle(.secondary)
                    }
                    Text("定位資訊只保存在這次操作，不會永久儲存。").font(.footnote).foregroundStyle(.secondary)
                }
                Section("目前租車 Session") {
                    if let session = store.session {
                        LabeledContent("Session", value: session.sessionId)
                        LabeledContent("狀態", value: session.state)
                        LabeledContent("租約", value: session.rentalId)
                        LabeledContent("車輛", value: "\(session.vehicle.plate) · \(session.vehicle.model ?? "")")
                        LabeledContent("AI 來源", value: session.aiSourceLabel ?? session.aiSource ?? "—")
                    } else {
                        Text("尚未租車。地圖上的 RCG-2235（真實 pipeline）與 ABC-1234（示範固定劇本）皆為模擬車輛。")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                    if let message = store.sessionSyncError {
                        Text(message).font(.footnote).foregroundStyle(.orange)
                    }
                }
                Section("Demo 測試車輛") {
                    DemoVehicleEntry(compact: true)
                        .listRowInsets(EdgeInsets())
                        .listRowBackground(Color.clear)
                    Text("點進去可「開始使用」或「重設 Demo」（重設前會再確認）。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Demo") {
                    Button {
                        Task { await restart() }
                    } label: {
                        HStack {
                            Text("重新開始 Demo（清除本機與後端 Session）")
                            if restarting { Spacer(); ProgressView() }
                        }
                    }
                    .disabled(restarting)
                    if let restartMessage {
                        Text(restartMessage).font(.footnote).foregroundStyle(.secondary)
                    }
                    Text("後端需以 DEMO_MODE=true 啟動；會結束所有模擬租車 Session、車輛回到可租借。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("設定")
        }
    }

    private func testConnection() async {
        testingConnection = true
        defer { testingConnection = false }
        do {
            let status = try await InspectionSyncService().checkConnection(baseURL: store.apiBaseURL)
            connectionMessage = "✓ 已連上伺服器（status: \(status)）"
        } catch {
            connectionMessage = "✗ 連不到伺服器：\(error.localizedDescription)"
        }
    }

    private func restart() async {
        restarting = true
        defer { restarting = false }
        do {
            try await RentalSessionService().reset(baseURL: store.apiBaseURL)
            restartMessage = "後端 Session 已重置。"
        } catch {
            restartMessage = "後端無法重置（\(error.localizedDescription)），只清除本機紀錄。"
        }
        PhotoStore().removeAll()
        store.resetLocal()
        dismiss()
    }
}


#Preview("取車檢查") {
    ContentView()
        .environment(RentalStore())
        .environment(LocationService())
}

import PhotosUI
import SwiftUI

struct ContentView: View {
    @Environment(RentalStore.self) private var store
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            Group {
                switch store.phase {
                case .readyForPickup:
                    InspectionChecklistView(stage: .pickup)
                case .pickupComplete:
                    PickupCompleteView()
                case .activeRental:
                    ActiveRentalView()
                case .readyForReturn:
                    InspectionChecklistView(stage: .`return`)
                case .completed:
                    ReturnCompleteView()
                }
            }
            .navigationTitle(store.phase.title)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("設定", systemImage: "gear") { showSettings = true }
                }
            }
            .sheet(isPresented: $showSettings) {
                SettingsView()
            }
            .task {
                await PendingUploadSync().run(for: store)
            }
        }
    }
}

// MARK: - 取車／還車導引拍攝清單

private struct InspectionChecklistView: View {
    @Environment(RentalStore.self) private var store
    let stage: InspectionStage
    @State private var didPrepareDemo = false

    var body: some View {
        List {
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
                    Text("\(store.completedExterior(for: stage)) / \(InspectionShot.exterior.count)")
                        .monospacedDigit()
                }
            }

            Section {
                ShotRow(stage: stage, shot: .interior)
            } header: {
                HStack {
                    Text("車內")
                    Spacer()
                    Text("\(store.photo(for: stage, shot: .interior) == nil ? 0 : 1) / 1")
                        .monospacedDigit()
                }
            }

            if store.isComplete(stage) {
                Section {
                    NavigationLink {
                        InspectionSummaryView(stage: stage)
                    } label: {
                        Label(stage == .pickup ? "檢視並完成取車檢查" : "檢視並完成還車檢查", systemImage: "checkmark.seal")
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
        .task {
            // 示範租約：本機還沒有任何取車照片時，先請後端清掉上一輪的紀錄，讓流程可以重演（best effort）。
            guard stage == .pickup, store.rental.isDemo, store.photos.isEmpty, !didPrepareDemo else { return }
            didPrepareDemo = true
            try? await InspectionSyncService().restart(rental: store.rental, baseURL: store.apiBaseURL)
        }
    }
}

private struct ShotRow: View {
    @Environment(RentalStore.self) private var store
    let stage: InspectionStage
    let shot: InspectionShot

    var body: some View {
        let photo = store.photo(for: stage, shot: shot)
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
                    }
                }
                Spacer()
                if photo != nil {
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
    let stage: InspectionStage

    var body: some View {
        List {
            Section(stage == .pickup ? "取車照片" : "還車照片") {
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
                Button(stage == .pickup ? "完成取車檢查" : "完成還車") {
                    store.confirm(stage: stage)
                }
                .buttonStyle(.borderedProminent)
                Text(stage == .pickup
                     ? "完成後這些照片會成為還車時的車況比對依據。"
                     : "車況分析由系統在背景進行，不需要等待。")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle("確認\(stage.title)")
        .task { await PendingUploadSync().run(for: store) }
    }
}

// MARK: - 取車檢查完成（Pickup Baseline Established）

private struct PickupCompleteView: View {
    @Environment(RentalStore.self) private var store

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
                LabeledContent("外觀照片", value: "\(store.completedExterior(for: .pickup)) / 4")
                LabeledContent("車內照片", value: "\(store.photo(for: .pickup, shot: .interior) == nil ? 0 : 1) / 1")
                LabeledContent("車況基準", value: baselineLabel)
                SyncStatusRow(stage: .pickup)
            }
            Section {
                Text("這些照片將作為還車時的車況比對依據。")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Button("開始租借") { store.startRental() }
                    .buttonStyle(.borderedProminent)
            }
        }
        .task { await PendingUploadSync().run(for: store) }
    }

    private var baselineLabel: String {
        if let remote = store.remoteStatus, remote.pickup.complete { return "已建立" }
        return store.pendingUploads(for: .pickup) == 0 ? "已建立" : "同步後建立"
    }
}

// MARK: - 租用中

private struct ActiveRentalView: View {
    @Environment(RentalStore.self) private var store

    var body: some View {
        ContentUnavailableView(
            "租用中",
            systemImage: "car.fill",
            description: Text("\(store.rental.carName) · \(store.rental.plateNumber)\n取車車況基準已建立。還車前請再次拍攝四個角度與車內照。")
        )
        .overlay(alignment: .bottom) {
            Button("開始還車") { store.beginReturn() }
                .buttonStyle(.borderedProminent)
                .padding()
        }
    }
}

// MARK: - 還車完成（不歸責；分析在背景進行）

private struct ReturnCompleteView: View {
    @Environment(RentalStore.self) private var store

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
            Section {
                LabeledContent("外觀照片", value: "\(store.completedExterior(for: .return)) / 4")
                LabeledContent("車內照片", value: "\(store.photo(for: .return, shot: .interior) == nil ? 0 : 1) / 1")
                LabeledContent("車況檢查") {
                    HStack(spacing: 6) {
                        if analysisLabel == "分析中" { ProgressView().controlSize(.small) }
                        Text(analysisLabel)
                    }
                }
                SyncStatusRow(stage: .return)
            }
            Section {
                Text("車況資料已提交。系統將比對您取車與還車時的車況紀錄。")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .task {
            await PendingUploadSync().run(for: store)
            // 只輪詢「分析狀態」，不取判定內容：App 不負責判定車損。
            while !Task.isCancelled, store.remoteStatus?.analysis != "complete", store.remoteStatus?.analysis != "failed" {
                try? await Task.sleep(for: .seconds(4))
                await PendingUploadSync().refreshStatus(for: store)
            }
        }
    }

    private var analysisLabel: String {
        if store.pendingUploads(for: .return) > 0 { return "等待照片上傳" }
        switch store.remoteStatus?.analysis {
        case "complete": return "已完成"
        case "failed": return "待人工複核"
        default: return "分析中"
        }
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
    @Environment(\.dismiss) private var dismiss
    @State private var restarting = false
    @State private var restartMessage: String?

    var body: some View {
        @Bindable var store = store
        NavigationStack {
            Form {
                Section("同步服務") {
                    TextField("API Base URL", text: $store.apiBaseURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
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
                Section("租約") {
                    Picker("目前租約", selection: Binding(
                        get: { store.rental.id },
                        set: { id in if let r = Rental.available.first(where: { $0.id == id }) { store.selectRental(r); PhotoStore().removeAll() } }
                    )) {
                        ForEach(Rental.available) { rental in
                            Text("\(rental.plateNumber) · \(rental.id)").tag(rental.id)
                        }
                    }
                    Text("ABC-1234 為比賽示範租約（後端固定產生車損與清潔案件）；RCG-2235 為真實 Core ML 驗證用。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                Section("Demo") {
                    Button {
                        Task { await restart() }
                    } label: {
                        HStack {
                            Text("重新開始 Demo（清除本機與後端紀錄）")
                            if restarting { Spacer(); ProgressView() }
                        }
                    }
                    .disabled(restarting)
                    if let restartMessage {
                        Text(restartMessage).font(.footnote).foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("設定")
        }
    }

    private func restart() async {
        restarting = true
        defer { restarting = false }
        do {
            try await InspectionSyncService().restart(rental: store.rental, baseURL: store.apiBaseURL)
            restartMessage = "後端紀錄已清除。"
        } catch {
            restartMessage = "後端無法連線（\(error.localizedDescription)），只清除本機紀錄。"
        }
        PhotoStore().removeAll()
        store.resetLocal()
        dismiss()
    }
}


#Preview("取車檢查") {
    ContentView()
        .environment(RentalStore())
}

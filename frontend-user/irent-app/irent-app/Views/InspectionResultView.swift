import SwiftUI

/// Phase 4/5：AI 影像檢測結果。資料來自後端 `GET /v1/rental-sessions/{id}/inspection`（既有 pipeline 的比對結果）。
/// 分析中每 2 秒輪詢（顯示已完成項目數）；失敗可「重新檢測」或「重新拍攝」；完成後需使用者按「確認還車」才會 RETURNED。
struct InspectionResultView: View {
    @Environment(RentalStore.self) private var store

    @State private var result: InspectionResult?
    @State private var fetchError: String?
    @State private var isActing = false
    @State private var actionError: String?
    @State private var selectedPart: CarPart?
    @State private var selectedMarker: MarkerRef?

    struct MarkerRef: Identifiable {
        let id: String
        let comparison: InspectionResult.Comparison
        let finding: InspectionResult.Comparison.Finding
    }

    /// 只把「有車身區域」的外觀發現放上 3D；沒有可確認位置的不畫。
    private func markerLookup(_ result: InspectionResult) -> [String: MarkerRef] {
        var out: [String: MarkerRef] = [:]
        for c in result.comparisons {
            for (i, f) in c.findings.enumerated() where f.region.map({ BodyRegion.labels[$0] != nil }) ?? false {
                guard f.status == "NEW_DAMAGE" || f.status == "EXISTING_DAMAGE" else { continue }
                let id = "\(c.angle)#\(i)"
                out[id] = MarkerRef(id: id, comparison: c, finding: f)
            }
        }
        return out
    }

    private func resultConfig(_ result: InspectionResult) -> Vehicle3DConfig {
        let vehicle = store.session?.vehicle
        let markers = markerLookup(result).values.sorted { $0.id < $1.id }.map { ref in
            Vehicle3DConfig.Marker(id: ref.id, region: ref.finding.region ?? "",
                                   severity: ref.finding.status == "EXISTING_DAMAGE" ? "existing" : (ref.finding.severity ?? "medium"),
                                   kind: ref.finding.status == "EXISTING_DAMAGE" ? "existing" : "new")
        }
        // 有新增車損時，鏡頭先轉到第一處新損所在部位
        let firstNew = markers.first { $0.kind == "new" }.flatMap { CarPart.of(region: $0.region)?.rawValue }
        return Vehicle3DConfig(style: vehicle?.bodyStyle ?? "sedan", plate: store.rental.plateNumber, paint: vehicle?.paintHex,
                               autoRotate: selectedPart == nil && markers.isEmpty, focus: firstNew, focusToken: firstNew.map { "damage-\($0)" },
                               markers: markers)
    }

    private var pendingUploads: Int { store.pendingUploads(for: .return) }

    var body: some View {
        List {
            Section {
                header
            }

            if pendingUploads > 0 {
                Section {
                    SyncStatusRowCompat()
                    Text("還有照片尚未上傳，收齊四個外觀角度後才會開始分析。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }

            if let result {
                Section("車況總覽") {
                    Vehicle3DCard(config: resultConfig(result), fallbackURL: nil, height: 230, selectedPart: selectedPart) { event in
                        switch event {
                        case .pick(let part, _): selectedPart = part
                        case .marker(let id): selectedMarker = markerLookup(result)[id]
                        }
                    }
                    .listRowInsets(EdgeInsets(top: 12, leading: 16, bottom: 12, trailing: 16))
                    let markers = markerLookup(result)
                    if result.analysis != "complete" {
                        Text("檢測完成後，偵測到的車損會標示在車身上。").font(.footnote).foregroundStyle(.secondary)
                    } else if markers.isEmpty {
                        Label("車身上沒有需要標示的車損。", systemImage: "checkmark.shield").font(.footnote).foregroundStyle(.green)
                    } else {
                        Text("紅色為本次新增車損、灰色為取車時已存在；點標記查看前後照片。").font(.footnote).foregroundStyle(.secondary)
                    }
                }
                if let selectedPart {
                    Section("部位 · \(selectedPart.title)") {
                        let rows = result.comparisons.filter { selectedPart.angles.contains($0.angle) }
                        if rows.isEmpty {
                            Text("車頂不在四角拍攝範圍內。").font(.footnote).foregroundStyle(.secondary)
                        }
                        ForEach(rows) { comparison in
                            ComparisonRow(comparison: comparison, thumbnail: thumbnail(for: comparison.angle), remotePath: comparison.returnPhotoUrl)
                        }
                    }
                }

                Section("車牌比對") {
                    Label(result.plateCheck.label, systemImage: plateIcon(result.plateCheck.status))
                        .foregroundStyle(plateTint(result.plateCheck.status))
                    ForEach(result.plateCheck.photos) { photo in
                        LabeledContent(photo.angle + "角") {
                            VStack(alignment: .trailing, spacing: 2) {
                                Text(photo.plateText ?? "未辨識").monospaced()
                                Text(sourceLabel(photo.source)).font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                    }
                }

                Section("外觀比對（取車 vs 還車）") {
                    if result.comparisons.isEmpty {
                        Text(result.analysis == "analyzing" ? "分析中…" : "尚無比對結果").foregroundStyle(.secondary)
                    }
                    if let label = store.session?.captureModeLabel(.return) {
                        Text(label).font(.footnote).foregroundStyle(.secondary)
                    }
                    ForEach(result.comparisons) { comparison in
                        ComparisonRow(comparison: comparison, thumbnail: thumbnail(for: comparison.angle), remotePath: comparison.returnPhotoUrl)
                    }
                }

                Section("車內整潔") {
                    if let interior = result.interior {
                        HStack(spacing: 12) {
                            if let image = thumbnail(for: "車內") {
                                Image(uiImage: image).resizable().scaledToFill().frame(width: 64, height: 48).clipShape(.rect(cornerRadius: 6))
                            }
                            VStack(alignment: .leading, spacing: 3) {
                                HStack(spacing: 6) {
                                    Image(systemName: interior.result == "CLEANING_REQUIRED" ? "exclamationmark.triangle.fill" : interior.result == "CLEAN" ? "checkmark.circle.fill" : "questionmark.circle")
                                        .foregroundStyle(interior.result == "CLEANING_REQUIRED" ? .orange : interior.result == "CLEAN" ? .green : .secondary)
                                    Text(interior.resultLabel ?? interior.result ?? "—").font(.subheadline.weight(.semibold))
                                }
                                HStack(spacing: 8) {
                                    if let level = interior.cleanliness { Text("等級：\(level)") }
                                    if let score = interior.score { Text("整潔分數 \(score)/100") }
                                    if let c = interior.confidence { Text("信心 \(Int(c * 100))%") }
                                }
                                .font(.caption).foregroundStyle(.secondary)
                                if let findings = interior.findings, !findings.isEmpty {
                                    Text(findings.compactMap(\.label).joined(separator: "、")).font(.caption)
                                }
                            }
                        }
                    } else {
                        if result.analysis == "complete" || result.analysis == "failed" {
                            Text("未拍攝車內照（選填），本次未判定車內整潔度。").font(.footnote).foregroundStyle(.secondary)
                        } else {
                            Text(result.analysis == "analyzing" ? "分析中…" : "尚無結果").foregroundStyle(.secondary)
                        }
                    }
                }

                if !result.incidents.isEmpty {
                    Section("已轉人工複核的異常") {
                        ForEach(result.incidents) { incident in
                            VStack(alignment: .leading, spacing: 2) {
                                HStack {
                                    Text(incident.kind == "cleaning" ? "車內髒汙" : incident.kind == "integrity" ? "照片重複" : "新增車損")
                                        .font(.subheadline.weight(.semibold))
                                    if let level = incident.aiLevel {
                                        Text(level).font(.caption2.weight(.bold)).padding(.horizontal, 6).padding(.vertical, 2)
                                            .background((level == "P1" ? Color.red : Color.orange).opacity(0.15), in: Capsule())
                                    }
                                    Spacer()
                                    Text(incident.angle).font(.caption).foregroundStyle(.secondary)
                                }
                                if let summary = incident.summary { Text(summary).font(.caption).foregroundStyle(.secondary) }
                            }
                        }
                        Text("AI 判定為決策輔助；是否歸責與收費由營運人員在管理者端複核後決定，App 不會直接向你收費。")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }

                if result.analysis == "failed" {
                    Section("檢測失敗") {
                        if result.analysisError?.contains("TimeoutError") == true {
                            Text("這次檢測等待太久已自動停止（照片都已保存），可直接重新檢測。").font(.footnote).foregroundStyle(.red)
                        }
                        Text("車況檢測暫時無法完成，請重新檢測或重新拍攝；若持續發生，客服會協助人工檢視。").font(.footnote).foregroundStyle(.red)
                        Button { retry(mode: "reanalyze") } label: { Label("重新檢測（同一批照片）", systemImage: "arrow.clockwise") }
                            .disabled(isActing)
                        Button { retry(mode: "retake") } label: { Label("重新拍攝還車照片", systemImage: "camera.fill") }
                            .disabled(isActing)
                    }
                }

                if result.analysis == "complete" {
                    Section {
                        AppButton(title: isActing ? "處理中…" : "確認還車", systemImage: "checkmark.seal.fill") { confirmReturn() }
                            .disabled(isActing || pendingUploads > 0)
                            .listRowInsets(EdgeInsets())
                            .listRowBackground(Color.clear)
                        Text("檢測完成不代表還車完成：請確認上方結果後按「確認還車」，車輛才會回到可租借狀態。")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
            } else if let fetchError {
                Section {
                    Label(fetchError, systemImage: "wifi.exclamationmark").font(.footnote).foregroundStyle(.orange)
                    Button("重試") { Task { await refresh() } }
                }
            }

            if let actionError {
                Section { Text(actionError).font(.footnote).foregroundStyle(.red) }
            }

            CancelReturnSection(disabled: isActing)
        }
        .task {
            await PendingUploadSync().run(for: store)
            // 完成拍攝時若離線沒送到，這裡補送（冪等；已開始分析不會重跑）
            if store.session?.state == "PHOTO_INSPECTION" { await store.finishCapture(stage: .return) }
            await poll()
        }
        .refreshable { await refresh() }
        #if DEBUG
        // 開發驗證用（僅 Debug build）：-openFirstMarker 啟動後自動開第一個車損標記的詳情
        .onChange(of: result) { _, r in
            guard CommandLine.arguments.contains("-openFirstMarker"), selectedMarker == nil, let r else { return }
            selectedMarker = markerLookup(r).values.sorted { $0.id > $1.id }.first { $0.finding.status == "NEW_DAMAGE" }
        }
        #endif
        .sheet(item: $selectedMarker) { ref in
            DamageDetailSheet(comparison: ref.comparison, finding: ref.finding)
        }
    }

    // MARK: - 區塊

    @ViewBuilder
    private var header: some View {
        let analysis = result?.analysis ?? store.session?.analysis ?? "pending"
        VStack(spacing: 10) {
            Group {
                switch analysis {
                case "complete":
                    Image(systemName: (result?.overall == "PASSED") ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                        .foregroundStyle((result?.overall == "PASSED") ? .green : .orange)
                case "failed":
                    Image(systemName: "xmark.octagon.fill").foregroundStyle(.red)
                default:
                    ProgressView().controlSize(.large)
                }
            }
            .font(.system(size: 44))
            Text(result?.overallLabel ?? (pendingUploads > 0 ? "等待照片上傳" : "AI 分析中"))
                .font(.title3.bold()).multilineTextAlignment(.center)
            Text("\(store.rental.carName) · \(store.rental.plateNumber)").foregroundStyle(.secondary)
            if analysis == "analyzing" || analysis == "pending" {
                if let progress = result?.analysisProgress ?? store.session?.analysisProgress, let total = progress.total, total > 0 {
                    ProgressView(value: Double(min(progress.done, total)), total: Double(total))
                        .frame(maxWidth: 220)
                        .accessibilityIdentifier("analysis-progress-bar")
                    Text("已完成 \(min(progress.done, total)) / \(total) 項比對" + (progress.elapsedS.map { " · 已等待 \($0) 秒" } ?? ""))
                        .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                        .accessibilityIdentifier("analysis-progress-text")
                }
                Text(pendingUploads > 0
                     ? "照片上傳完成後會自動開始分析。"
                     : "系統正同時比對四個角度與車內照片，通常 10–40 秒完成。請留在此頁，不需要重新送出。")
                    .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 8)
    }

    private func thumbnail(for angle: String) -> UIImage? {
        guard let shot = InspectionShot(rawValue: angle), let photo = store.photo(for: .return, shot: shot) else { return nil }
        return PhotoStore().image(named: photo.fileName)
    }

    private func plateIcon(_ status: String) -> String {
        switch status {
        case "MATCH": "checkmark.circle.fill"
        case "PENDING": "clock"
        default: "exclamationmark.triangle.fill"
        }
    }

    private func plateTint(_ status: String) -> Color {
        switch status {
        case "MATCH": .green
        case "PENDING": .secondary
        default: .orange
        }
    }

    private func sourceLabel(_ source: String) -> String {
        switch source {
        case "manual": "手動輸入"
        case "user_confirmed_mismatch": "與租約不符，使用者確認"
        case "preloaded": "車況紀錄照片"
        default: "本次拍攝"
        }
    }

    // MARK: - 動作

    private func refresh() async {
        guard let session = store.session else { return }
        // 請求發出後若使用者取消了還車，回來的舊狀態／舊結果一律丟掉（否則會把畫面推回分析中或檢測完成）
        let generation = store.returnFlowGeneration
        do {
            let updated = try await RentalSessionService().get(id: session.sessionId, baseURL: store.apiBaseURL)
            guard store.applyIfCurrent(updated, generation: generation) else { return }
            let fresh = try await RentalSessionService().inspection(id: session.sessionId, baseURL: store.apiBaseURL)
            guard generation == store.returnFlowGeneration else { return }
            result = fresh
            fetchError = nil
        } catch {
            fetchError = "無法取得檢測結果：\(error.localizedDescription)"
        }
    }

    private func poll() async {
        while !Task.isCancelled {
            await refresh()
            if let result, result.isFinished { break }
            if store.phase != .inspectionResult { break }
            try? await Task.sleep(for: .seconds(2))
            if pendingUploads > 0 { await PendingUploadSync().run(for: store) }
        }
    }

    private func retry(mode: String) {
        guard let session = store.session, !isActing else { return }
        isActing = true
        actionError = nil
        let generation = store.returnFlowGeneration
        Task {
            defer { isActing = false }
            do {
                let updated = try await RentalSessionService().retry(id: session.sessionId, mode: mode, baseURL: store.apiBaseURL)
                guard generation == store.returnFlowGeneration else { return }
                if mode == "retake" {
                    store.clearPhotos(stage: .return)
                }
                result = nil
                store.apply(updated)
                if store.phase == .inspectionResult { await poll() }
            } catch {
                actionError = error.localizedDescription
            }
        }
    }

    private func confirmReturn() {
        guard let session = store.session, !isActing else { return }
        isActing = true
        actionError = nil
        Task {
            defer { isActing = false }
            do {
                let updated = try await RentalSessionService().confirmReturn(id: session.sessionId, baseURL: store.apiBaseURL)
                store.apply(updated)
            } catch {
                actionError = error.localizedDescription
            }
        }
    }
}

private struct ComparisonRow: View {
    let comparison: InspectionResult.Comparison
    let thumbnail: UIImage?
    var remotePath: String? = nil

    private var tint: Color {
        switch comparison.result {
        case "NO_NEW_DAMAGE": .green
        case "EXISTING_DAMAGE": .blue
        case "NEW_DAMAGE": .red
        case nil: .secondary
        default: .orange
        }
    }
    private var icon: String {
        switch comparison.result {
        case "NO_NEW_DAMAGE": "checkmark.circle.fill"
        case "EXISTING_DAMAGE": "info.circle.fill"
        case "NEW_DAMAGE": "exclamationmark.triangle.fill"
        case nil: "clock"
        default: "questionmark.circle.fill"
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            if let thumbnail {
                Image(uiImage: thumbnail).resizable().scaledToFill().frame(width: 64, height: 48).clipShape(.rect(cornerRadius: 6))
            } else if remotePath != nil {
                RemoteThumb(path: remotePath, width: 64, height: 48)
            } else {
                if let shot = InspectionShot(rawValue: comparison.angle) {
                    InspectionAngleIcon(shot: shot).padding(2).frame(width: 64, height: 48)
                } else {
                    Image(systemName: "car.side").frame(width: 64, height: 48).foregroundStyle(.secondary)
                }
            }
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Image(systemName: icon).foregroundStyle(tint)
                    Text("\(comparison.angle)角").font(.subheadline.weight(.semibold))
                    Spacer()
                    Text(comparison.resultLabel).font(.caption).foregroundStyle(tint)
                }
                if let summary = comparison.summary {
                    Text(summary).font(.caption).foregroundStyle(.secondary)
                }
                ForEach(Array(comparison.findings.enumerated()), id: \.offset) { _, finding in
                    HStack(spacing: 4) {
                        Text("•")
                        Text([finding.label, finding.type, finding.severity.map { "嚴重度 \($0)" },
                              finding.confidence.map { "信心 \(Int($0 * 100))%" }].compactMap { $0 }.joined(separator: " · "))
                    }
                    .font(.caption2).foregroundStyle(finding.status == "NEW_DAMAGE" ? .red : .secondary)
                }
            }
        }
    }
}

/// 與 ContentView 的 SyncStatusRow 同一邏輯（那個是 private），這裡只顯示待上傳數與重試。
private struct SyncStatusRowCompat: View {
    @Environment(RentalStore.self) private var store

    var body: some View {
        let pending = store.pendingUploads(for: .return)
        HStack {
            if store.isSyncing {
                ProgressView().controlSize(.small)
                Text("同步中…")
            } else {
                Image(systemName: "icloud.slash").foregroundStyle(.orange)
                Text("待上傳 \(pending) 張")
            }
            Spacer()
            if pending > 0 && !store.isSyncing {
                Button("重試") { Task { await PendingUploadSync().run(for: store) } }
                    .buttonStyle(.bordered).controlSize(.small)
            }
        }
        .font(.footnote)
    }
}

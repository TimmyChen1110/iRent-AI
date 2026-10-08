import AVFoundation
import PhotosUI
import SwiftUI

/// 單一槽位的導引拍攝：拍照／選相簿 → 裝置端驗證（Core ML 或 Demo 劇本）→ 通過才存檔並上傳。
struct CaptureView: View {
    @Environment(RentalStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let stage: InspectionStage
    let shot: InspectionShot

    @State private var selectedItem: PhotosPickerItem?
    @State private var previewImage: UIImage?
    @State private var showCamera = false
    @State private var isChecking = false
    @State private var result: LocalInspectionResult?
    @State private var syncMessage: String?
    @State private var manualPlate = ""
    @State private var showManualEntry = false
    @State private var isUploading = false
    @State private var confirmLeave = false

    /// 檢查或上傳進行中：改用自訂返回鍵先確認（平常保留系統返回鍵與邊緣滑動手勢）
    private var isBusy: Bool { isChecking || isUploading }

    private let photoStore = PhotoStore()
    private let syncService = InspectionSyncService()

    private var progressText: String {
        if shot.isInterior { return "車內照（選填）" }
        let index = (InspectionShot.exterior.firstIndex(of: shot) ?? 0) + 1
        return "外觀 \(index) / \(InspectionShot.exterior.count)"
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 20) {
                VStack(spacing: 6) {
                    Text(progressText)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Text(shot.title)
                        .font(.title2.bold())
                    Text(shot.instruction)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                .padding(.top, 8)

                if let previewImage {
                    Image(uiImage: previewImage)
                        .resizable()
                        .scaledToFit()
                        .clipShape(.rect(cornerRadius: 16))
                } else {
                    CaptureGuide3D(stage: stage, current: shot, height: 220)
                }

                if isChecking {
                    ProgressView(store.demoMode ? "正在檢查照片…" : "正在離線辨識…")
                }

                if let result {
                    ValidationCard(result: result, expectedPlate: store.rental.plateNumber)
                    if !result.passed, !store.demoMode, !shot.isInterior {
                        plateFallback(for: result)
                    }
                }

                if let syncMessage {
                    Text(syncMessage)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }

                if result?.passed == true {
                    Button {
                        dismiss()
                    } label: {
                        Label(store.nextShot(for: stage) == nil ? "回到清單" : "下一個角度", systemImage: "arrow.right")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                } else {
                    HStack {
                        Button(result == nil ? "拍照" : "重新拍攝", systemImage: "camera") { openCamera() }
                        PhotosPicker(selection: $selectedItem, matching: .images) {
                            Label("從相簿選擇", systemImage: "photo.on.rectangle")
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isChecking)
                }
            }
            .padding()
        }
        .navigationTitle(stage.title)
        .navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden(isBusy)
        .toolbar {
            if isBusy {
                ToolbarItem(placement: .topBarLeading) {
                    AppBackButton { confirmLeave = true }
                }
            }
        }
        .confirmationDialog(isChecking ? "照片還在檢查中" : "照片正在上傳", isPresented: $confirmLeave, titleVisibility: .visible) {
            Button("返回清單") { dismiss() }
            Button("留在此頁", role: .cancel) {}
        } message: {
            Text("返回後會在背景繼續完成，已通過檢查的照片不會遺失。")
        }
        .sheet(isPresented: $showCamera) {
            CameraPicker { process($0) }
        }
        .onChange(of: selectedItem) { _, newItem in
            Task {
                guard let data = try? await newItem?.loadTransferable(type: Data.self),
                      let image = UIImage(data: data) else { return }
                selectedItem = nil
                process(image)
            }
        }
    }

    /// 相機不可用（模擬器）或權限被拒時不開 picker：UIImagePickerController 在這兩種情況會直接閃退／黑畫面。
    private func openCamera() {
        guard UIImagePickerController.isSourceTypeAvailable(.camera) else {
            syncMessage = "此裝置沒有可用相機（模擬器請用「從相簿選擇」）。"
            return
        }
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .denied, .restricted:
            syncMessage = "相機權限已關閉。請至「設定 › iRent App › 相機」允許後再進行車況拍攝。"
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { granted in
                Task { @MainActor in
                    if granted { showCamera = true } else { syncMessage = "未授權相機，無法拍攝車況照片。" }
                }
            }
        default:
            showCamera = true
        }
    }

    /// 車牌關卡的補救：OCR 讀不到 → 手動輸入車牌（須與租約一致）；OCR 讀到別台 → 使用者確認同一台車（標記待人工複核）。
    @ViewBuilder
    private func plateFallback(for result: LocalInspectionResult) -> some View {
        if result.failureKind == "plate" {
            VStack(alignment: .leading, spacing: 8) {
                if showManualEntry {
                    Text("車牌無法自動辨識。請輸入車牌（須與租借車輛 \(store.rental.plateNumber) 一致）；手動輸入會標記為需人工確認。")
                        .font(.footnote).foregroundStyle(.secondary)
                    HStack {
                        TextField("例如 \(store.rental.plateNumber)", text: $manualPlate)
                            .textInputAutocapitalization(.characters)
                            .autocorrectionDisabled()
                            .textFieldStyle(.roundedBorder)
                        Button("重新檢查") {
                            guard let image = previewImage else { return }
                            process(image, options: CaptureOptions(manualPlate: manualPlate))
                        }
                        .buttonStyle(.bordered)
                        .disabled(manualPlate.trimmingCharacters(in: .whitespaces).count < 6 || isChecking)
                    }
                } else {
                    Button("車牌辨識失敗？手動輸入車牌", systemImage: "keyboard") { showManualEntry = true }
                        .font(.footnote)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        } else if result.failureKind == "plateMismatch", let detected = result.detectedPlateText {
            VStack(alignment: .leading, spacing: 8) {
                Text("辨識到 \(detected)，與租借車輛 \(store.rental.plateNumber) 不符。若你確定拍的是同一台車（例如 OCR 讀錯一個字），可以送出並交由人工確認；系統不會直接判定通過。")
                    .font(.footnote).foregroundStyle(.secondary)
                Button("我確認是同一台車，送人工確認", systemImage: "person.fill.questionmark") {
                    guard let image = previewImage else { return }
                    process(image, options: CaptureOptions(acceptPlateMismatch: true))
                }
                .font(.footnote)
                .disabled(isChecking)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func process(_ image: UIImage, options: CaptureOptions = CaptureOptions()) {
        previewImage = image
        isChecking = true
        result = nil
        syncMessage = nil
        if options.manualPlate == nil { showManualEntry = false }

        Task {
            let attempt = store.recordAttempt(stage: stage, shot: shot)
            let validator = CaptureValidator(demoMode: store.demoMode)
            let outcome = await validator.validate(image: image, rental: store.rental, stage: stage, shot: shot, attempt: attempt, options: options)
            isChecking = false
            result = outcome
            guard outcome.passed else { return }

            do {
                let saved = try photoStore.save(image, stage: stage, shot: shot)
                let photo = CapturedPhoto(
                    id: UUID(),
                    stage: stage,
                    shot: shot,
                    fileName: saved.fileName,
                    capturedAt: Date(),
                    sha256: saved.hash,
                    result: outcome,
                    uploadedAt: nil
                )
                store.replace(photo)
                syncMessage = "照片已保存在手機，正在上傳…"
                isUploading = true
                defer { isUploading = false }

                do {
                    try await syncService.upload(
                        photo: photo,
                        rental: store.rental,
                        imageData: saved.data,
                        baseURL: store.apiBaseURL
                    )
                    store.markUploaded(id: photo.id)
                    syncMessage = "已同步到伺服器。"
                } catch SyncError.rejected(let reason) {
                    store.markRejected(id: photo.id, reason: reason)
                    syncMessage = "伺服器拒絕這張照片：\(reason)"
                } catch {
                    syncMessage = "目前無法連線，照片已保存，稍後會自動重送（待上傳）。"
                }
            } catch {
                // 本機存檔失敗：不能假裝拍攝成功，狀態不前進
                result = .failure(title: "照片無法保存", reason: error.localizedDescription, hint: "請確認手機儲存空間後重新拍攝。",
                                  checks: [], modelVersions: outcome.modelVersions)
                syncMessage = nil
            }
        }
    }
}

/// 驗證結果卡：通過 → 「✓ 照片符合要求」＋逐項勾選；失敗 → 標題、原因、怎麼重拍。
private struct ValidationCard: View {
    let result: LocalInspectionResult
    let expectedPlate: String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: result.passed ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .foregroundStyle(result.passed ? .green : .red)
                Text(result.passed ? "照片符合要求" : (result.failureTitle ?? "照片需要重拍"))
                    .font(.headline)
            }
            if !result.passed, let reason = result.errors.first {
                Text(reason).font(.subheadline)
                if let hint = result.failureHint {
                    Text(hint).font(.subheadline).foregroundStyle(.secondary)
                }
            }
            if let checks = result.checks, !checks.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(checks) { check in
                        Label(check.label, systemImage: check.passed ? "checkmark" : "xmark")
                            .font(.footnote)
                            .foregroundStyle(check.passed ? .green : .red)
                    }
                }
                .padding(.top, 2)
            }
            if result.passed, let plate = result.plateText {
                Text(result.plateConfidence.map { "車牌 \(plate) · 信心 \(Int($0 * 100))%" } ?? "車牌 \(plate) · \(result.plateSource == "manual" ? "手動輸入" : "待人工確認")")
                    .font(.caption)
                    .foregroundStyle(result.plateSource == nil ? Color.secondary : Color.orange)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill((result.passed ? Color.green : Color.red).opacity(0.08))
        )
    }
}

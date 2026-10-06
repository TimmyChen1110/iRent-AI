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

    private let photoStore = PhotoStore()
    private let syncService = InspectionSyncService()

    private var progressText: String {
        if shot.isInterior { return "車內照 1 / 1" }
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
                    ContentUnavailableView(shot.isInterior ? "拍攝車內" : "拍攝\(shot.rawValue)角",
                                           systemImage: shot.systemImage,
                                           description: Text("車牌與車身需完整入鏡"))
                        .frame(height: 220)
                }

                if isChecking {
                    ProgressView(store.demoMode ? "正在檢查照片…" : "正在離線辨識…")
                }

                if let result {
                    ValidationCard(result: result, expectedPlate: store.rental.plateNumber)
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
                        Button(result == nil ? "拍照" : "重新拍攝", systemImage: "camera") { showCamera = true }
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

    private func process(_ image: UIImage) {
        previewImage = image
        isChecking = true
        result = nil
        syncMessage = nil

        Task {
            let attempt = store.recordAttempt(stage: stage, shot: shot)
            let validator = CaptureValidator(demoMode: store.demoMode)
            let outcome = await validator.validate(image: image, rental: store.rental, stage: stage, shot: shot, attempt: attempt)
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
                syncMessage = error.localizedDescription
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
            if result.passed, let plate = result.plateText, let confidence = result.plateConfidence {
                Text("車牌 \(plate) · 信心 \(Int(confidence * 100))%")
                    .font(.caption)
                    .foregroundStyle(.secondary)
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

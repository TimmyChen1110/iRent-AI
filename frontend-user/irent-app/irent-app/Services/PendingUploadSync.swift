import Foundation

/// 離線補傳：每次開啟 App（或畫面要求）把尚未上傳的照片依拍攝順序重送。
/// 冪等性由後端負責（photo_id / sha256 相同不重複建檔），這裡只管「沒傳成功就再試」。
@MainActor
struct PendingUploadSync {
    private let photoStore = PhotoStore()
    private let syncService = InspectionSyncService()

    func run(for store: RentalStore) async {
        guard !store.isSyncing else { return }
        store.isSyncing = true
        defer { store.isSyncing = false }
        let pending = store.photos
            .filter { $0.uploadedAt == nil && $0.uploadError == nil }
            .sorted { $0.capturedAt < $1.capturedAt }
        for photo in pending {
            guard let data = try? photoStore.data(named: photo.fileName) else { continue }
            do {
                try await syncService.upload(
                    photo: photo,
                    rental: store.rental,
                    imageData: data,
                    baseURL: store.apiBaseURL
                )
                store.markUploaded(id: photo.id)
            } catch SyncError.rejected(let reason) {
                store.markRejected(id: photo.id, reason: reason)   // 4xx：不再重試，UI 顯示原因
            } catch {
                continue   // 沒網路／伺服器暫時無法連線：下次再試
            }
        }
        await refreshStatus(for: store)
    }

    func refreshStatus(for store: RentalStore) async {
        if let status = try? await syncService.status(rental: store.rental, baseURL: store.apiBaseURL) {
            store.remoteStatus = status
        }
    }
}

import Foundation

@MainActor
struct PendingUploadSync {
    private let photoStore = PhotoStore()
    private let syncService = InspectionSyncService()

    func run(for store: RentalStore) async {
        for photo in store.photos where photo.uploadedAt == nil {
            guard let data = try? photoStore.data(named: photo.fileName) else { continue }
            do {
                try await syncService.upload(
                    photo: photo,
                    rental: store.rental,
                    imageData: data,
                    baseURL: store.apiBaseURL
                )
                store.markUploaded(id: photo.id)
            } catch {
                continue
            }
        }
    }
}

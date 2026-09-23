import PhotosUI
import SwiftUI

struct CaptureView: View {
    @Environment(RentalStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let stage: InspectionStage
    let view: VehicleView

    @State private var selectedItem: PhotosPickerItem?
    @State private var previewImage: UIImage?
    @State private var showCamera = false
    @State private var isChecking = false
    @State private var message: String?
    @State private var passed = false

    private let recognizer = OnDeviceRecognitionService()
    private let photoStore = PhotoStore()
    private let syncService = InspectionSyncService()

    var body: some View {
        ScrollView {
            VStack(spacing: 20) {
                ContentUnavailableView(
                    view.rawValue,
                    systemImage: "car.side",
                    description: Text(view.instruction)
                )

                if let previewImage {
                    Image(uiImage: previewImage)
                        .resizable()
                        .scaledToFit()
                        .clipShape(.rect(cornerRadius: 16))
                }

                if let message {
                    Label(message, systemImage: passed ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                        .foregroundStyle(passed ? .green : .red)
                        .multilineTextAlignment(.center)
                }

                if !passed {
                    HStack {
                        Button("拍照", systemImage: "camera") { showCamera = true }
                        PhotosPicker(selection: $selectedItem, matching: .images) {
                            Label("從相簿選擇", systemImage: "photo.on.rectangle")
                        }
                    }
                    .buttonStyle(.borderedProminent)
                }

                if isChecking {
                    ProgressView("正在離線辨識…")
                }
            }
            .padding()
        }
        .navigationTitle(stage.title)
        .sheet(isPresented: $showCamera) {
            CameraPicker { process($0) }
        }
        .onChange(of: selectedItem) { _, newItem in
            Task {
                guard let data = try? await newItem?.loadTransferable(type: Data.self),
                      let image = UIImage(data: data) else { return }
                process(image)
            }
        }
    }

    private func process(_ image: UIImage) {
        previewImage = image
        isChecking = true
        passed = false
        message = nil

        Task {
            let result = await recognizer.evaluate(
                image: image,
                expectedPlate: store.rental.plateNumber,
                expectedView: view
            )
            isChecking = false
            guard result.passed else {
                message = result.errors.first ?? "照片未通過檢查。"
                return
            }

            do {
                let saved = try photoStore.save(image, stage: stage, view: view)
                let photo = CapturedPhoto(
                    id: UUID(),
                    stage: stage,
                    view: view,
                    fileName: saved.fileName,
                    capturedAt: Date(),
                    sha256: saved.hash,
                    result: result,
                    uploadedAt: nil
                )
                store.replace(photo)
                passed = true
                message = "離線檢查通過，正在同步到伺服器。"

                do {
                    try await syncService.upload(
                        photo: photo,
                        rental: store.rental,
                        imageData: saved.data,
                        baseURL: store.apiBaseURL
                    )
                    store.markUploaded(id: photo.id)
                    message = "離線檢查與伺服器同步完成。"
                } catch {
                    message = "離線檢查通過；目前無法同步，將在下次開啟 App 時重送。"
                }
            } catch {
                message = error.localizedDescription
            }
        }
    }
}

import PhotosUI
import SwiftUI

struct CaptureView: View {
    @Environment(RentalStore.self) private var store
    let stage: InspectionStage
    let view: VehicleView

    @State private var selectedItem: PhotosPickerItem?
    @State private var previewImage: UIImage?
    @State private var showCamera = false
    @State private var isChecking = false
    @State private var message: String?
    @State private var passed = false
    @State private var recognitionResult: LocalInspectionResult?

    private let recognizer = OnDeviceRecognitionService()
    private let photoStore = PhotoStore()
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: AppTheme.Spacing.lg) {
                header
                contextCard
                photoPreview
                actions
                resultCard
            }
            .padding(AppTheme.Spacing.lg)
        }
        .background(AppTheme.Colors.background.ignoresSafeArea())
        .navigationTitle("車況拍攝")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented: $showCamera) {
            CameraPicker { process($0) }
                .ignoresSafeArea()
        }
        .onChange(of: selectedItem) { _, newItem in
            Task {
                guard let data = try? await newItem?.loadTransferable(type: Data.self),
                      let image = UIImage(data: data) else { return }
                process(image)
            }
        }
    }

    private var header: some View {
        HStack(spacing: AppTheme.Spacing.md) {
            ZStack {
                RoundedRectangle(cornerRadius: AppTheme.Radius.sm, style: .continuous)
                    .fill(AppTheme.Colors.primary)
                Image(systemName: "car.fill").foregroundStyle(.white)
            }
            .frame(width: 36, height: 36)
            VStack(alignment: .leading, spacing: 2) {
                Text(stage.title)
                    .font(.title2.weight(.heavy))
                    .foregroundStyle(AppTheme.Colors.text)
                Text("請依指定角度拍攝，車牌需清楚入鏡")
                    .font(.footnote)
                    .foregroundStyle(AppTheme.Colors.textSecondary)
            }
        }
    }

    private var contextCard: some View {
        HStack(spacing: AppTheme.Spacing.md) {
            Image(systemName: "viewfinder")
                .font(.title3)
                .foregroundStyle(AppTheme.Colors.primary)
            VStack(alignment: .leading, spacing: AppTheme.Spacing.xs) {
                Text("指定拍攝角度")
                    .font(.footnote.weight(.bold))
                    .foregroundStyle(AppTheme.Colors.textSecondary)
                Text(view.rawValue)
                    .font(.title3.weight(.bold))
                    .foregroundStyle(AppTheme.Colors.text)
            }
            Spacer()
            Text(stage == .pickup ? "取車" : "還車")
                .font(.caption.weight(.bold))
                .foregroundStyle(AppTheme.Colors.primaryDark)
                .padding(.horizontal, AppTheme.Spacing.md)
                .padding(.vertical, AppTheme.Spacing.sm)
                .background(AppTheme.Colors.primarySoft, in: Capsule())
        }
        .qualityCard()
    }

    @ViewBuilder
    private var photoPreview: some View {
        ZStack {
            RoundedRectangle(cornerRadius: AppTheme.Radius.lg, style: .continuous)
                .fill(AppTheme.Colors.cameraBackground)
            if let previewImage {
                Image(uiImage: previewImage)
                    .resizable()
                    .scaledToFit()
                    .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.lg, style: .continuous))
            } else {
                VStack(spacing: AppTheme.Spacing.sm) {
                    Image(systemName: "camera.viewfinder")
                        .font(.system(size: 42))
                    Text("拍攝車況照片")
                        .font(.headline)
                    Text(view.instruction)
                        .font(.footnote)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.white.opacity(0.72))
                }
                .foregroundStyle(.white)
                .padding(AppTheme.Spacing.xl)
            }
            if isChecking {
                Rectangle()
                    .fill(.black.opacity(0.55))
                ProgressView("正在以本機模型辨識…")
                    .tint(.white)
                    .foregroundStyle(.white)
                    .padding()
                    .background(.black.opacity(0.35), in: Capsule())
            }
        }
        .frame(minHeight: 290)
        .accessibilityLabel("車況照片預覽")
    }

    private var actions: some View {
        VStack(spacing: AppTheme.Spacing.sm) {
            AppButton(title: previewImage == nil ? "開啟相機拍攝" : "重新拍攝", systemImage: "camera.fill") {
                showCamera = true
            }
            HStack(spacing: AppTheme.Spacing.sm) {
                PhotosPicker(selection: $selectedItem, matching: .images) {
                    Label("從相簿選擇", systemImage: "photo.on.rectangle")
                        .font(.body.weight(.bold))
                        .frame(maxWidth: .infinity, minHeight: AppTheme.touchTarget)
                }
                .foregroundStyle(AppTheme.Colors.text)
                .background(AppTheme.Colors.surface, in: RoundedRectangle(cornerRadius: AppTheme.Radius.sm, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: AppTheme.Radius.sm, style: .continuous)
                        .stroke(AppTheme.Colors.border2, lineWidth: 1)
                }
                Button("清除") {
                    previewImage = nil
                    recognitionResult = nil
                    message = nil
                    passed = false
                }
                .font(.body.weight(.bold))
                .foregroundStyle(AppTheme.Colors.textSecondary)
                .frame(minHeight: AppTheme.touchTarget)
                .disabled(previewImage == nil || isChecking)
            }
        }
        .disabled(isChecking)
    }

    @ViewBuilder
    private var resultCard: some View {
        if let message {
            HStack(alignment: .top, spacing: AppTheme.Spacing.md) {
                Image(systemName: passed ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .font(.title2)
                    .foregroundStyle(passed ? AppTheme.Colors.success : AppTheme.Colors.error)
                VStack(alignment: .leading, spacing: AppTheme.Spacing.xs) {
                    Text(passed ? "離線辨識通過" : "請重新拍攝")
                        .font(.headline)
                        .foregroundStyle(AppTheme.Colors.text)
                    if let plate = recognitionResult?.plateText {
                        Text("辨識車牌：\(plate)")
                            .font(.headline)
                        if let confidence = recognitionResult?.plateConfidence {
                            Text("OCR 信心：\(confidence.formatted(.percent.precision(.fractionLength(1))))")
                                .font(.footnote)
                                .foregroundStyle(AppTheme.Colors.textSecondary)
                        }
                    }
                    Text(message)
                        .font(.footnote)
                        .foregroundStyle(AppTheme.Colors.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .padding(AppTheme.Spacing.lg)
            .background(passed ? AppTheme.Colors.successSoft : AppTheme.Colors.errorSoft,
                        in: RoundedRectangle(cornerRadius: AppTheme.Radius.md, style: .continuous))
        }
    }

    private func process(_ image: UIImage) {
        previewImage = image
        isChecking = true
        passed = false
        message = nil
        recognitionResult = nil

        Task {
            let result = await recognizer.evaluate(
                image: image,
                expectedPlate: store.rental.plateNumber,
                expectedView: view
            )
            isChecking = false
            recognitionResult = result
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
                message = "車牌與拍攝角度均由本機模型驗證，照片已儲存。"
            } catch {
                message = error.localizedDescription
            }
        }
    }
}

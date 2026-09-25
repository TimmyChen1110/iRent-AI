import SwiftUI
import PhotosUI

/// 首頁：Header → 角度 chips → 相機／照片區 → 按鈕 → 結果。
struct PhotoCaptureView: View {
    @State private var model = PhotoQualityViewModel()
    @State private var showCamera = false
    @State private var showCameraUnavailable = false
    @State private var photoItem: PhotosPickerItem?
    @State private var photoLoadFailed = false

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: AppTheme.Spacing.lg) {
                    header
                        .padding(.horizontal, AppTheme.Spacing.lg)

                    angleSection
                        .id("angle")

                    VStack(spacing: AppTheme.Spacing.md) {
                        PhotoPreviewView(
                            photo: model.currentPhoto?.image,
                            requiredView: model.requiredView,
                            isAnalyzing: model.isBusy
                        )
                        actions
                        statusLine
                    }
                    .padding(.horizontal, AppTheme.Spacing.lg)

                    resultSection
                        .padding(.horizontal, AppTheme.Spacing.lg)
                        .id("result")
                }
                .padding(.vertical, AppTheme.Spacing.lg)
            }
            .background(AppTheme.Colors.background.ignoresSafeArea())
            .onChange(of: model.state.isAnalyzing) { _, analyzing in
                if !analyzing, model.currentPhoto != nil {
                    withAnimation { proxy.scrollTo("result", anchor: .top) }
                }
            }
            .fullScreenCover(isPresented: $showCamera) {
                CameraPicker { image in model.didPick(image: image) }
                    .ignoresSafeArea()
            }
            .photosPicker(isPresented: $photoPickerPresented, selection: $photoItem, matching: .images, photoLibrary: .shared())
            .onChange(of: photoItem) { _, item in
                guard let item else { return }
                photoItem = nil
                loadPickedPhoto(item)
            }
            .alert("無法使用相機", isPresented: $showCameraUnavailable) {
                Button("好", role: .cancel) {}
            } message: {
                Text("目前裝置無法使用相機，請從相簿選擇照片。")
            }
            .alert("無法讀取照片", isPresented: $photoLoadFailed) {
                Button("好", role: .cancel) {}
            } message: {
                Text("這張照片無法讀取，請換一張再試。")
            }
            .alert("提示", isPresented: userMessageBinding) {
                Button("好", role: .cancel) { model.userMessage = nil }
            } message: {
                Text(model.userMessage ?? "")
            }
            .onChange(of: changeAngleTrigger) { _, _ in
                withAnimation { proxy.scrollTo("angle", anchor: .top) }
            }
        }
    }

    // MARK: - Sections

    private var header: some View {
        HStack(spacing: AppTheme.Spacing.md) {
            ZStack {
                RoundedRectangle(cornerRadius: AppTheme.Radius.sm, style: .continuous).fill(AppTheme.Colors.primary)
                Image(systemName: "car.fill").foregroundStyle(.white)
            }
            .frame(width: 36, height: 36)
            .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text("車況拍攝")
                    .font(.title2.weight(.heavy))
                    .foregroundStyle(AppTheme.Colors.text)
                    .accessibilityAddTraits(.isHeader)
                    .accessibilityIdentifier("header.title")
                Text("請依照指定角度拍攝車輛照片")
                    .font(.footnote)
                    .foregroundStyle(AppTheme.Colors.textSecondary)
            }
        }
    }

    private var angleSection: some View {
        VStack(alignment: .leading, spacing: AppTheme.Spacing.sm) {
            HStack(alignment: .firstTextBaseline) {
                Text("拍攝角度")
                    .font(.footnote.weight(.bold))
                    .foregroundStyle(AppTheme.Colors.textSecondary)
                Spacer()
                Text("不指定時只回報角度，不檢查是否拍錯")
                    .font(.caption2)
                    .foregroundStyle(AppTheme.Colors.textTertiary)
            }
            .padding(.horizontal, AppTheme.Spacing.lg)
            AngleSelector(selection: model.requiredView, isDisabled: model.isBusy) { view in
                model.select(view: view)
            }
        }
    }

    @State private var photoPickerPresented = false

    private var actions: some View {
        VStack(spacing: AppTheme.Spacing.sm) {
            AppButton(title: "開啟相機拍攝", systemImage: "camera.fill", kind: .primary) {
                if CameraPicker.isAvailable { showCamera = true } else { showCameraUnavailable = true }
            }
            .accessibilityIdentifier("action.camera")
            HStack(spacing: AppTheme.Spacing.sm) {
                AppButton(title: "從相簿選擇", kind: .secondary) { photoPickerPresented = true }
                    .accessibilityIdentifier("action.library")
                AppButton(title: "清除", kind: .ghost) { model.reset() }
                    .disabled(model.currentPhoto == nil)
                    .accessibilityIdentifier("action.reset")
            }
        }
        .disabled(model.isBusy)
    }

    private var statusLine: some View {
        Text(statusText)
            .font(.footnote)
            .foregroundStyle(AppTheme.Colors.textSecondary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityIdentifier("status.line")
    }

    private var statusText: String {
        switch model.state {
        case .idle: return "尚未選擇照片"
        case .analyzing: return "正在檢查照片…"
        case .result(_, let r): return r.passed ? "檢查完成：合格" : "檢查完成：請依提示重新拍攝"
        case .failed: return "檢查失敗"
        }
    }

    @State private var changeAngleTrigger = 0

    @ViewBuilder
    private var resultSection: some View {
        switch model.state {
        case .result(let photo, let response):
            ResultView(
                photo: photo,
                response: response,
                requiredView: model.requiredView,
                endpoint: model.apiEndpoint,
                onRetake: openCameraOrLibrary,
                onChangeAngle: { changeAngleTrigger += 1 }
            )
        case .failed(_, let failure):
            AnalysisFailureView(failure: failure, onRetry: { model.retry() }, onRetake: openCameraOrLibrary)
        case .idle, .analyzing:
            EmptyView()
        }
    }

    // MARK: - Helpers

    private func openCameraOrLibrary() {
        if CameraPicker.isAvailable { showCamera = true } else { photoPickerPresented = true }
    }

    private var userMessageBinding: Binding<Bool> {
        Binding(get: { model.userMessage != nil }, set: { if !$0 { model.userMessage = nil } })
    }

    private func loadPickedPhoto(_ item: PhotosPickerItem) {
        Task {
            // 讀原始檔（可能是 HEIC）→ UIImage；ImagePreparation 會再轉成正立 JPEG，不縮圖。
            if let data = try? await item.loadTransferable(type: Data.self), let image = UIImage(data: data) {
                model.didPick(image: image)
            } else {
                photoLoadFailed = true
            }
        }
    }
}

#Preview {
    PhotoCaptureView()
}

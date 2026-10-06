import PhotosUI
import SwiftUI

struct ContentView: View {
    @Environment(RentalStore.self) private var store

    var body: some View {
        NavigationStack {
            Group {
                switch store.phase {
                case .readyForPickup:
                    InspectionChecklistView(stage: .pickup)
                case .activeRental:
                    ActiveRentalView()
                case .readyForReturn:
                    InspectionChecklistView(stage: .`return`)
                case .completed:
                    CompletionView()
                }
            }
            .toolbar(.hidden, for: .navigationBar)
        }
    }
}

private struct InspectionChecklistView: View {
    @Environment(RentalStore.self) private var store
    let stage: InspectionStage

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: AppTheme.Spacing.lg) {
                header
                rentalCard
                captureChecklist

                if store.completedViews(for: stage) == VehicleView.allCases.count {
                    NavigationLink {
                        InspectionSummaryView(stage: stage)
                    } label: {
                        Label(stage == .pickup ? "檢視並確認取車" : "檢視並確認還車", systemImage: "checkmark.circle.fill")
                            .font(.body.weight(.bold))
                            .frame(maxWidth: .infinity, minHeight: AppTheme.touchTarget)
                    }
                    .foregroundStyle(.white)
                    .background(AppTheme.Colors.primary, in: RoundedRectangle(cornerRadius: AppTheme.Radius.sm, style: .continuous))
                }
            }
            .padding(AppTheme.Spacing.lg)
        }
        .background(AppTheme.Colors.background.ignoresSafeArea())
    }

    private var header: some View {
        HStack(spacing: AppTheme.Spacing.md) {
            ZStack {
                RoundedRectangle(cornerRadius: AppTheme.Radius.sm, style: .continuous)
                    .fill(AppTheme.Colors.primary)
                Image(systemName: "car.fill").foregroundStyle(.white)
            }
            .frame(width: 44, height: 44)
            VStack(alignment: .leading, spacing: 2) {
                Text(stage == .pickup ? "開始取車" : "開始還車")
                    .font(.title2.weight(.heavy))
                    .foregroundStyle(AppTheme.Colors.text)
                Text("依序完成四個指定角度的車況拍攝")
                    .font(.footnote)
                    .foregroundStyle(AppTheme.Colors.textSecondary)
            }
        }
    }

    private var rentalCard: some View {
        HStack(spacing: AppTheme.Spacing.md) {
            Image(systemName: "car.side.fill")
                .font(.title2)
                .foregroundStyle(AppTheme.Colors.primary)
                .frame(width: 42, height: 42)
                .background(AppTheme.Colors.primarySoft, in: RoundedRectangle(cornerRadius: AppTheme.Radius.sm, style: .continuous))
            VStack(alignment: .leading, spacing: AppTheme.Spacing.xs) {
                Text(store.rental.carName)
                    .font(.headline)
                    .foregroundStyle(AppTheme.Colors.text)
                Text(store.rental.plateNumber)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(AppTheme.Colors.textSecondary)
            }
            Spacer()
        }
        .qualityCard()
    }

    private var captureChecklist: some View {
        VStack(alignment: .leading, spacing: AppTheme.Spacing.sm) {
            HStack {
                Text("拍攝角度")
                    .font(.footnote.weight(.bold))
                    .foregroundStyle(AppTheme.Colors.textSecondary)
                Spacer()
                Text("\(store.completedViews(for: stage))/\(VehicleView.allCases.count) 已完成")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(AppTheme.Colors.primary)
            }
            ForEach(VehicleView.allCases) { view in
                let isComplete = store.photo(for: stage, view: view) != nil
                NavigationLink {
                    CaptureView(stage: stage, view: view)
                } label: {
                    HStack(spacing: AppTheme.Spacing.md) {
                        Image(systemName: isComplete ? "checkmark.circle.fill" : "camera.fill")
                            .font(.title3)
                            .foregroundStyle(isComplete ? AppTheme.Colors.success : AppTheme.Colors.primary)
                            .frame(width: 34)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(view.rawValue)
                                .font(.body.weight(.bold))
                            Text(isComplete ? "離線辨識已通過" : view.instruction)
                                .font(.caption)
                                .foregroundStyle(AppTheme.Colors.textSecondary)
                                .lineLimit(1)
                        }
                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(.footnote.weight(.bold))
                            .foregroundStyle(AppTheme.Colors.textTertiary)
                    }
                    .padding(AppTheme.Spacing.md)
                    .background(AppTheme.Colors.surface, in: RoundedRectangle(cornerRadius: AppTheme.Radius.md, style: .continuous))
                    .overlay {
                        RoundedRectangle(cornerRadius: AppTheme.Radius.md, style: .continuous)
                            .stroke(isComplete ? AppTheme.Colors.success.opacity(0.35) : AppTheme.Colors.border, lineWidth: 1)
                    }
                }
            }
        }
    }
}

private struct ActiveRentalView: View {
    @Environment(RentalStore.self) private var store

    var body: some View {
        ContentUnavailableView(
            "租用中",
            systemImage: "car.fill",
            description: Text("取車記錄已保存在本機。還車前請再次拍攝四個角度。")
        )
        .overlay(alignment: .bottom) {
            Button("開始還車拍攝") { store.beginReturn() }
                .buttonStyle(.borderedProminent)
                .padding()
        }
    }
}

private struct CompletionView: View {
    @Environment(RentalStore.self) private var store

    var body: some View {
        List {
            Section("租約") {
                LabeledContent("車輛", value: store.rental.carName)
                LabeledContent("車牌", value: store.rental.plateNumber)
            }
            ForEach(InspectionStage.allCases, id: \.self) { stage in
                Section(stage.title) {
                    ForEach(VehicleView.allCases) { view in
                        if let photo = store.photo(for: stage, view: view) {
                            LabeledContent(view.rawValue, value: photo.capturedAt.formatted(date: .abbreviated, time: .shortened))
                        }
                    }
                }
            }
        }
    }
}

private struct InspectionSummaryView: View {
    @Environment(RentalStore.self) private var store
    let stage: InspectionStage

    var body: some View {
        List {
            ForEach(VehicleView.allCases) { view in
                if let photo = store.photo(for: stage, view: view) {
                    HStack {
                        Image(uiImage: PhotoStore().image(named: photo.fileName) ?? UIImage())
                            .resizable()
                            .scaledToFill()
                            .frame(width: 96, height: 72)
                            .clipShape(.rect(cornerRadius: 8))
                        VStack(alignment: .leading) {
                            Text(view.rawValue)
                            Text(photo.result.plateText ?? store.rental.plateNumber)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }

            Section {
                Button(stage == .pickup ? "確認取車" : "確認還車") {
                    store.confirm(stage: stage)
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .navigationTitle("確認\(stage.title)")
    }
}

#Preview("取車檢查") {
    ContentView()
        .environment(RentalStore())
}

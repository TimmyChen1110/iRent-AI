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
                case .activeRental:
                    ActiveRentalView()
                case .readyForReturn:
                    InspectionChecklistView(stage: .`return`)
                case .completed:
                    CompletionView()
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

private struct InspectionChecklistView: View {
    @Environment(RentalStore.self) private var store
    let stage: InspectionStage

    var body: some View {
        List {
            Section {
                Text("\(store.rental.carName) · \(store.rental.plateNumber)")
                    .font(.headline)
                Text("請依序完成四個角度。每張照片均會在本機離線核對車牌、拍攝角度與品質。")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            Section(stage.title) {
                ForEach(VehicleView.allCases) { view in
                    NavigationLink {
                        CaptureView(stage: stage, view: view)
                    } label: {
                        HStack {
                            Label(view.rawValue, systemImage: store.photo(for: stage, view: view) == nil ? "camera" : "checkmark.circle.fill")
                            Spacer()
                            if store.photo(for: stage, view: view) != nil {
                                Text("已通過").foregroundStyle(.green)
                            } else {
                                Text("待拍攝").foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }

            if store.completedViews(for: stage) == VehicleView.allCases.count {
                Section {
                    NavigationLink("檢視並確認 (stage.title)") {
                        InspectionSummaryView(stage: stage)
                    }
                    .fontWeight(.semibold)
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
        .navigationTitle("確認(stage.title)")
    }
}

private struct SettingsView: View {
    @Environment(RentalStore.self) private var store

    var body: some View {
        @Bindable var store = store
        NavigationStack {
            Form {
                Section("同步服務") {
                    TextField("API Base URL", text: $store.apiBaseURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                }
            }
            .navigationTitle("設定")
        }
    }
}

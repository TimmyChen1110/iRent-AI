import CoreLocation
import MapKit
import SwiftUI
import UIKit

/// Phase 1：App 啟動後的定位授權畫面。說明用途 → 請求權限 → 取得 GPS；拒絕／失敗／逾時可手動選擇位置。
struct LocationPermissionView: View {
    @Environment(LocationService.self) private var location
    @State private var showManualPicker = false

    var body: some View {
        VStack(spacing: AppTheme.Spacing.xl) {
            Spacer()
            Image(systemName: "location.circle.fill")
                .font(.system(size: 76))
                .foregroundStyle(AppTheme.Colors.primary)
            VStack(spacing: AppTheme.Spacing.sm) {
                Text("允許 iRent 取得你的位置")
                    .font(.title2.bold())
                    .multilineTextAlignment(.center)
                Text("我們會用你的目前位置在地圖上顯示附近可租借的車輛，並記錄租車與還車位置。定位資訊只保存在這次操作中，不會永久儲存。")
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.Colors.textSecondary)
                    .multilineTextAlignment(.center)
            }
            .padding(.horizontal, AppTheme.Spacing.lg)

            if location.isRequesting {
                ProgressView("正在取得位置…")
            }
            if let message = location.errorMessage {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.footnote)
                    .foregroundStyle(AppTheme.Colors.error)
                    .padding(AppTheme.Spacing.md)
                    .background(AppTheme.Colors.errorSoft, in: RoundedRectangle(cornerRadius: AppTheme.Radius.sm, style: .continuous))
                    .padding(.horizontal, AppTheme.Spacing.lg)
            }
            Spacer()

            // 不論定位成功／失敗，都能從這裡進入 Demo 測試車輛
            DemoVehicleEntry()
                .padding(.horizontal, AppTheme.Spacing.lg)

            VStack(spacing: AppTheme.Spacing.md) {
                if location.isDenied {
                    AppButton(title: "前往設定開啟定位", systemImage: "gear") {
                        if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                    }
                    Text("開啟後回到 App 會自動重新定位。")
                        .font(.caption)
                        .foregroundStyle(AppTheme.Colors.textTertiary)
                } else {
                    AppButton(title: location.errorMessage == nil ? "允許定位" : "重新定位", systemImage: "location.fill") {
                        location.request()
                    }
                    .disabled(location.isRequesting)
                }
                AppButton(title: "手動選擇位置", systemImage: "mappin.and.ellipse", kind: .secondary) {
                    showManualPicker = true
                }
            }
            .padding(.horizontal, AppTheme.Spacing.lg)
            .padding(.bottom, AppTheme.Spacing.lg)
        }
        .background(AppTheme.Colors.background)
        .sheet(isPresented: $showManualPicker) {
            ManualLocationPicker { coordinate, name in
                location.setManual(coordinate, name: name)
            }
        }
        .onAppear {
            // 之前已授權（例如重開 App）：不必再按一次，直接定位
            if location.isAuthorized, !location.isResolved, !location.isRequesting { location.request() }
        }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)) { _ in
            // 從「設定」回來：權限若已開啟就自動定位
            if location.isAuthorized, !location.isResolved, !location.isRequesting { location.request() }
        }
    }
}

/// 手動選擇位置：拖曳地圖把中心釘在你的位置，或直接選一個預設地點。
struct ManualLocationPicker: View {
    @Environment(\.dismiss) private var dismiss
    let onPick: (CLLocationCoordinate2D, String) -> Void

    private struct Preset: Identifiable {
        let id = UUID()
        let name: String
        let coordinate: CLLocationCoordinate2D
    }
    private let presets: [Preset] = [
        Preset(name: "臺灣大學 第二學生活動中心（二活）", coordinate: CLLocationCoordinate2D(latitude: 25.01800, longitude: 121.53360)),
        Preset(name: "臺灣大學 正門（羅斯福路）", coordinate: CLLocationCoordinate2D(latitude: 25.01694, longitude: 121.53440)),
        Preset(name: "台北市信義區 市政府站", coordinate: CLLocationCoordinate2D(latitude: 25.04100, longitude: 121.56500)),
    ]

    @State private var camera: MapCameraPosition = .camera(MapCamera(centerCoordinate: CLLocationCoordinate2D(latitude: 25.01800, longitude: 121.53360), distance: 1600))
    @State private var center = CLLocationCoordinate2D(latitude: 25.01800, longitude: 121.53360)
    @State private var pickedName: String?

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ZStack {
                    Map(position: $camera, interactionModes: [.pan, .zoom])
                        .mapStyle(.standard(pointsOfInterest: .excludingAll))
                        .onMapCameraChange(frequency: .continuous) { context in
                            center = context.camera.centerCoordinate
                            pickedName = nil
                        }
                    Image(systemName: "mappin")
                        .font(.system(size: 40))
                        .foregroundStyle(AppTheme.Colors.error)
                        .offset(y: -18)
                        .allowsHitTesting(false)
                }
                List {
                    Section("快速選擇") {
                        ForEach(presets) { preset in
                            Button {
                                pickedName = preset.name
                                center = preset.coordinate
                                withAnimation { camera = .camera(MapCamera(centerCoordinate: preset.coordinate, distance: 1200)) }
                            } label: {
                                Label(preset.name, systemImage: "mappin.circle")
                            }
                        }
                    }
                    Section {
                        Text(String(format: "地圖中心：%.5f, %.5f", center.latitude, center.longitude))
                            .font(.footnote.monospacedDigit())
                            .foregroundStyle(.secondary)
                        Button {
                            onPick(center, pickedName ?? "手動選擇的位置")
                            dismiss()
                        } label: {
                            Label("使用此位置", systemImage: "checkmark.circle.fill").fontWeight(.semibold)
                        }
                    }
                }
                .frame(maxHeight: 280)
            }
            .navigationTitle("手動選擇位置")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
            }
        }
    }
}

#Preview("定位授權") {
    LocationPermissionView().environment(LocationService()).environment(RentalStore())
}

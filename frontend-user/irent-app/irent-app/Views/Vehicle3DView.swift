import SwiftUI
import WebKit

// MARK: - 車身部位與區域

/// 3D 車身的五個部位（點選車身時回傳）；對應的拍攝角度用來找借車前／還車照片。
enum CarPart: String, CaseIterable, Identifiable {
    case front, left, right, rear, roof

    var id: String { rawValue }
    var title: String {
        switch self {
        case .front: "車頭"
        case .left: "左側"
        case .right: "右側"
        case .rear: "車尾"
        case .roof: "車頂"
        }
    }
    /// 這個部位在照片中會出現的拍攝角度（四角照片各涵蓋兩個面）
    var angles: [String] {
        switch self {
        case .front: ["左前", "右前"]
        case .rear: ["左後", "右後"]
        case .left: ["左前", "左後"]
        case .right: ["右前", "右後"]
        case .roof: []
        }
    }
    var regions: [String] {
        switch self {
        case .front: ["front-bumper", "hood", "windshield"]
        case .rear: ["rear-bumper"]
        case .roof: ["roof"]
        case .left: ["left-front-door", "left-rear-door", "left-front-fender", "left-rear-quarter"]
        case .right: ["right-front-door", "right-rear-door", "right-front-fender", "right-rear-quarter"]
        }
    }

    static func of(region: String) -> CarPart? { allCases.first { $0.regions.contains(region) } }
}

/// 車身區域 id → 中文（與後端 body_regions.REGION_LABELS 同一組）
enum BodyRegion {
    static let labels: [String: String] = [
        "front-bumper": "前保桿", "rear-bumper": "後保桿", "hood": "引擎蓋", "roof": "車頂", "windshield": "擋風玻璃",
        "left-front-door": "左前車門", "right-front-door": "右前車門", "left-rear-door": "左後車門", "right-rear-door": "右後車門",
        "left-front-fender": "左前葉子板", "right-front-fender": "右前葉子板",
        "left-rear-quarter": "左後側板", "right-rear-quarter": "右後側板",
    ]
    static func label(_ id: String?) -> String { id.flatMap { labels[$0] } ?? "車身" }
}

// MARK: - 設定（Swift → JS）

struct Vehicle3DConfig: Encodable, Equatable {
    struct Marker: Encodable, Equatable {
        let id: String
        let region: String
        var severity: String? = nil
        var kind: String? = nil          // new | existing
    }
    struct Guide: Encodable, Equatable {
        var current: String?
        var done: [String]
    }
    var style: String = "sedan"
    var plate: String = ""
    var paint: String? = nil
    var autoRotate = false
    var selectable = true
    var focusOnPick = true
    var focus: String? = nil
    var focusToken: String? = nil
    var markers: [Marker] = []
    var guide: Guide? = nil
    var clearPick = false
}

enum Vehicle3DEvent {
    case pick(part: CarPart, region: String?)
    case marker(id: String)
}

// MARK: - 本機資源（irent3d://app/…）

/// 以自訂 scheme 提供隨 App 打包的 3D 檢視器檔案（HTML／ES modules／GLB），不連外網；
/// 自訂 scheme 讓 ES module 與 fetch 有一致的來源，避免 file:// 的模組限制。
final class Vehicle3DSchemeHandler: NSObject, WKURLSchemeHandler {
    static let scheme = "irent3d"
    static let shared = Vehicle3DSchemeHandler()
    private var cache: [String: Data] = [:]

    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        guard let url = urlSchemeTask.request.url else { return }
        let name = url.lastPathComponent
        let base = (name as NSString).deletingPathExtension
        let ext = (name as NSString).pathExtension
        let data: Data? = cache[name] ?? {
            guard let file = Bundle.main.url(forResource: base, withExtension: ext)
                    ?? Bundle.main.url(forResource: base, withExtension: ext, subdirectory: "Vehicle3D"),
                  let d = try? Data(contentsOf: file) else { return nil }
            cache[name] = d
            return d
        }()
        guard let data else {
            urlSchemeTask.didFailWithError(URLError(.fileDoesNotExist))
            return
        }
        let mime = switch ext.lowercased() {
        case "html": "text/html; charset=utf-8"
        case "js": "text/javascript; charset=utf-8"
        case "glb": "model/gltf-binary"
        default: "application/octet-stream"
        }
        let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1",
                                       headerFields: ["Content-Type": mime, "Content-Length": "\(data.count)",
                                                      "Access-Control-Allow-Origin": "*"])!
        urlSchemeTask.didReceive(response)
        urlSchemeTask.didReceive(data)
        urlSchemeTask.didFinish()
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {}
}

/// WKUserContentController 會強持有 handler：用弱參照避免 web view 與 coordinator 互相持有。
private final class WeakMessageHandler: NSObject, WKScriptMessageHandler {
    weak var target: WKScriptMessageHandler?
    init(_ target: WKScriptMessageHandler) { self.target = target }
    func userContentController(_ c: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.userContentController(c, didReceive: message)
    }
}

// MARK: - Web view

struct Vehicle3DWebView: UIViewRepresentable {
    enum Status { case loading, ready, failed }

    var config: Vehicle3DConfig
    var onEvent: (Vehicle3DEvent) -> Void = { _ in }
    var onStatus: (Status) -> Void = { _ in }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let cfg = WKWebViewConfiguration()
        cfg.setURLSchemeHandler(Vehicle3DSchemeHandler.shared, forURLScheme: Vehicle3DSchemeHandler.scheme)
        cfg.userContentController.add(WeakMessageHandler(context.coordinator), name: "irent3d")
        let webView = WKWebView(frame: .zero, configuration: cfg)
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.backgroundColor = .clear
        webView.scrollView.isScrollEnabled = false
        webView.scrollView.bounces = false
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        context.coordinator.webView = webView
        webView.load(URLRequest(url: URL(string: "\(Vehicle3DSchemeHandler.scheme)://app/vehicle3d.html")!))
        context.coordinator.startTimeout()
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        context.coordinator.parent = self
        context.coordinator.push()
    }

    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "irent3d")
        coordinator.timeout?.cancel()
    }

    final class Coordinator: NSObject, WKScriptMessageHandler {
        var parent: Vehicle3DWebView
        weak var webView: WKWebView?
        private var booted = false
        private var ready = false
        private var failed = false
        private var lastSent: Vehicle3DConfig?
        var timeout: Task<Void, Never>?

        init(_ parent: Vehicle3DWebView) { self.parent = parent }

        func startTimeout() {
            timeout = Task { [weak self] in
                try? await Task.sleep(for: .seconds(25))
                guard let self, !Task.isCancelled, !self.ready else { return }
                self.fail()
            }
        }

        private func fail() {
            guard !failed else { return }
            failed = true
            timeout?.cancel()
            parent.onStatus(.failed)
        }

        func push() {
            guard booted, !failed, let webView, parent.config != lastSent,
                  let data = try? JSONEncoder().encode(parent.config),
                  let json = String(data: data, encoding: .utf8) else { return }
            lastSent = parent.config
            webView.evaluateJavaScript("window.iRent3D && window.iRent3D.apply(\(json)); void 0;")
        }

        func userContentController(_ c: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
            switch type {
            case "boot":
                booted = true
                push()
            case "ready":
                ready = true
                timeout?.cancel()
                parent.onStatus(.ready)
            case "error":
                fail()
            case "pick":
                if let raw = body["part"] as? String, let part = CarPart(rawValue: raw) {
                    parent.onEvent(.pick(part: part, region: body["region"] as? String))
                }
            case "marker":
                if let id = body["id"] as? String { parent.onEvent(.marker(id: id)) }
            default:
                break
            }
        }
    }
}

// MARK: - 卡片（含載入中、回退照片、部位快捷鍵）

/// 互動式 3D 車輛卡片：拖曳旋轉、雙指縮放、點選車身部位。WebGL 不可用或載入失敗時顯示 2D 車輛照片。
struct Vehicle3DCard: View {
    var config: Vehicle3DConfig
    var fallbackURL: URL?
    var height: CGFloat = 240
    var showPartBar = true
    var hint: String? = "拖曳旋轉 · 雙指縮放 · 點選車身查看車況"
    var selectedPart: CarPart? = nil
    var onEvent: (Vehicle3DEvent) -> Void = { _ in }

    @State private var status: Vehicle3DWebView.Status = .loading
    @State private var chipFocus: String?
    @State private var chipToken = 0

    private var effectiveConfig: Vehicle3DConfig {
        var c = config
        if let chipFocus {
            c.focus = chipFocus
            c.focusToken = "chip-\(chipToken)"
        }
        return c
    }

    var body: some View {
        VStack(spacing: 8) {
            ZStack {
                RoundedRectangle(cornerRadius: AppTheme.Radius.md, style: .continuous)
                    .fill(LinearGradient(colors: [Color(.secondarySystemBackground), Color(.tertiarySystemBackground)], startPoint: .top, endPoint: .bottom))
                if status == .failed {
                    fallback
                } else {
                    Vehicle3DWebView(config: effectiveConfig, onEvent: handle, onStatus: { status = $0 })
                        .opacity(status == .ready ? 1 : 0)
                    if status == .loading {
                        ProgressView().controlSize(.regular)
                    }
                }
                if status == .ready, let hint {
                    VStack {
                        Spacer()
                        Text(hint)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 8).padding(.vertical, 4)
                            .background(.ultraThinMaterial, in: Capsule())
                            .padding(.bottom, 8)
                    }
                    .allowsHitTesting(false)
                }
            }
            .frame(height: height)
            .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.md, style: .continuous))

            if showPartBar, status == .ready {
                HStack(spacing: 6) {
                    ForEach(CarPart.allCases) { part in
                        Button {
                            chipFocus = part.rawValue
                            chipToken += 1
                            onEvent(.pick(part: part, region: nil))
                        } label: {
                            Text(part.title)
                                .font(.caption.weight(.semibold))
                                .frame(maxWidth: .infinity, minHeight: 30)
                                .foregroundStyle(selectedPart == part ? Color.white : AppTheme.Colors.text)
                                .background(selectedPart == part ? AppTheme.Colors.primary : AppTheme.Colors.surface2,
                                            in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    private func handle(_ event: Vehicle3DEvent) {
        if case .pick = event { chipFocus = nil }
        onEvent(event)
    }

    @ViewBuilder
    private var fallback: some View {
        if let fallbackURL {
            AsyncImage(url: fallbackURL) { phase in
                if let image = phase.image {
                    image.resizable().scaledToFill()
                } else {
                    Image(systemName: "car.side.fill").font(.system(size: 44)).foregroundStyle(Color.accentColor)
                }
            }
            .frame(height: height)
            .clipped()
        } else {
            Image(systemName: "car.side.fill").font(.system(size: 44)).foregroundStyle(Color.accentColor)
        }
    }
}


// MARK: - 部位車況（3D 點選後顯示）

/// 點選 3D 車身部位後的車況：該部位的借車前照片與已登錄車損。
struct PartConditionSection: View {
    let part: CarPart
    /// (角度, 照片 url)
    let beforePhotos: [(String, String?)]
    var damage: [VehicleRecords.DamageRecord] = []
    var title: String = "借車前照片"
    var emptyText: String? = nil

    private var photos: [(String, String?)] { beforePhotos.filter { part.angles.contains($0.0) } }

    var body: some View {
        Section("部位車況 · \(part.title)") {
            if part == .roof {
                Text("車頂不在四角拍攝範圍內；若有異常請於還車時另行回報。").font(.footnote).foregroundStyle(.secondary)
            } else if photos.isEmpty {
                Text(emptyText ?? "此部位尚無照片。").font(.footnote).foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    Text(title).font(.subheadline.weight(.semibold))
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(Array(photos.enumerated()), id: \.offset) { _, item in
                                VStack(spacing: 3) {
                                    RemoteThumb(path: item.1, width: 150, height: 112)
                                    Text("\(item.0)角").font(.caption2).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }
            }
            if damage.isEmpty {
                Label("此部位目前沒有車損紀錄", systemImage: "checkmark.shield").font(.footnote).foregroundStyle(.green)
            } else {
                ForEach(damage) { d in
                    HStack(alignment: .top, spacing: 10) {
                        RemoteThumb(path: d.photoUrl, width: 72, height: 54)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("\(BodyRegion.label(d.region)) · \(d.type ?? "車損")").font(.subheadline.weight(.semibold))
                            if let label = d.label { Text(label).font(.caption).foregroundStyle(.secondary) }
                            if let at = d.recordedAt { Text("登錄於 \(at.prefix(10))").font(.caption2).foregroundStyle(.tertiary) }
                        }
                    }
                }
            }
        }
    }
}


// MARK: - 車損詳情（AI 檢測結果頁點標記）

/// 3D 標記對應的車損：類型、位置、AI 判定、借還車前後照片（AI 框只畫在還車照片上）。
struct DamageDetailSheet: View {
    @Environment(\.dismiss) private var dismiss
    let comparison: InspectionResult.Comparison
    let finding: InspectionResult.Comparison.Finding

    var body: some View {
        NavigationStack {
            List {
                Section {
                    LabeledContent("位置", value: "\(BodyRegion.label(finding.region))（\(comparison.angle)角照片）")
                    LabeledContent("車損類型", value: finding.type ?? (finding.status == "EXISTING_DAMAGE" ? "既有痕跡" : "車損"))
                    if let sev = finding.severity { LabeledContent("嚴重度", value: ["low": "輕微", "medium": "中等", "high": "嚴重"][sev] ?? sev) }
                    if let c = finding.confidence { LabeledContent("AI 信心", value: "\(Int(c * 100))%") }
                    LabeledContent("AI 判定") {
                        Text(finding.status == "EXISTING_DAMAGE" ? "取車時已存在（不列入本次）" : "本次新增車損")
                            .foregroundStyle(finding.status == "EXISTING_DAMAGE" ? Color.secondary : Color.red)
                    }
                    if let r = finding.reasoning, !r.isEmpty { Text(r).font(.footnote).foregroundStyle(.secondary) }
                }
                Section("借還車前後比較") {
                    HStack(alignment: .top, spacing: 8) {
                        photo(title: "借車前", path: comparison.pickupPhotoUrl, boxes: [])
                        photo(title: "還車後", path: comparison.returnPhotoUrl,
                              boxes: finding.status == "EXISTING_DAMAGE" ? [] : (comparison.boxes ?? []))
                    }
                    Text("紅框為 AI 在還車照片上標出的位置；3D 標記依車身部位放置，僅示意所在區域。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section {
                    Text("AI 判定為輔助資訊；是否歸責由營運人員人工複核後決定。").font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle(BodyRegion.label(finding.region))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("關閉") { dismiss() } } }
        }
    }

    private func photo(title: String, path: String?, boxes: [InspectionResult.Comparison.Box]) -> some View {
        VStack(spacing: 4) {
            BoxedRemoteImage(path: path, boxes: boxes)
            Text(title).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }
}

/// 後端照片 + AI 框（box_2d 0–1000 正規化，[ymin, xmin, ymax, xmax]），框與顯示中的照片同尺寸對齊。
struct BoxedRemoteImage: View {
    @Environment(RentalStore.self) private var store
    let path: String?
    var boxes: [InspectionResult.Comparison.Box] = []

    var body: some View {
        Group {
            if let path, let base = InspectionSyncService.normalizedBaseURL(store.apiBaseURL), let url = URL(string: path, relativeTo: base)?.absoluteURL {
                AsyncImage(url: url) { phase in
                    if let image = phase.image {
                        image.resizable().scaledToFit()
                            .overlay {
                                GeometryReader { geo in
                                    ForEach(Array(boxes.enumerated()), id: \.offset) { _, box in
                                        if let b = box.box2d, b.count == 4 {
                                            Rectangle()
                                                .stroke(Color.red, lineWidth: 2)
                                                .frame(width: geo.size.width * (b[3] - b[1]) / 1000, height: geo.size.height * (b[2] - b[0]) / 1000)
                                                .position(x: geo.size.width * (b[1] + b[3]) / 2000, y: geo.size.height * (b[0] + b[2]) / 2000)
                                        }
                                    }
                                }
                            }
                    } else {
                        Color.secondary.opacity(0.12).frame(height: 120)
                    }
                }
            } else {
                Color.secondary.opacity(0.12).frame(height: 120)
            }
        }
        .clipShape(.rect(cornerRadius: 8))
    }
}

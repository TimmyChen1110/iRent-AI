import CryptoKit
import XCTest

/// iRent App UI 測試：真實後端（測試用資料庫）＋真實 App 畫面操作。
///
/// 執行前需要：
///   - 後端以 DEMO_MODE=true 跑在 IRENT_API（預設 http://127.0.0.1:8011；用測試資料庫，setUp 會清空所有模擬 Session）
///   - 測試照片資料夾（`<stage>-<角度>.jpg`）：IRENT_PHOTOS_OK＝與 Demo 車同車牌的真實照片、IRENT_PHOTOS_WRONG＝別台車
///   - IRENT_DATASET＝資料集「沒有進行索賠」資料夾（用 API 準備還車情境）
/// 以 xcodebuild 傳入時加 TEST_RUNNER_ 前綴（TEST_RUNNER_IRENT_API=…）。
/// 車牌辨識一律是 App 內真實 Core ML：測試照片只是取代模擬器沒有的相機。
@MainActor
final class IRentUITests: XCTestCase {
    private var api: Backend!
    private var env: [String: String] { ProcessInfo.processInfo.environment }
    private let demoPlate = "RDL-7827"

    override func setUp() async throws {
        continueAfterFailure = false
        api = Backend(base: URL(string: env["IRENT_API"] ?? "http://127.0.0.1:8011")!)
        try await api.login()
        _ = try await api.call("POST", "/api/ops/devtools/reset-all")
        for v in try await api.devVehicles() where v["admin_created"] as? Bool == true {
            _ = try await api.call("DELETE", "/api/ops/devtools/demo-vehicles/\(v["vehicle_id"] as! String)")
        }
    }

    /// 收尾：清掉測試建立的 Session 與 Demo 車，不把租用中的車輛留在測試資料庫裡
    override func tearDown() async throws {
        if let api {
            _ = try? await api.call("POST", "/api/ops/devtools/reset-all")
            for v in (try? await api.devVehicles()) ?? [] where v["admin_created"] as? Bool == true {
                _ = try? await api.call("DELETE", "/api/ops/devtools/demo-vehicles/\(v["vehicle_id"] as! String)")
            }
        }
        try await super.tearDown()
    }

    // MARK: - 測試

    /// 後台建立 Demo 車 → App 地圖／推薦清單出現 → 真實 OCR 取車 → 還車 → AI 檢測（進度條）→ 確認還車 → 車輛重新上架。
    func testAdminDemoVehicleFullRentalWithRealPlateOCR() async throws {
        let created = try await api.call("POST", "/api/ops/devtools/demo-vehicles",
                                         ["plate": demoPlate, "lat": 25.0179, "lng": 121.5372, "model": "UI 測試車"])
        XCTAssertEqual(created.status, 201)
        let app = launchApp(photos: try XCTUnwrap(env["IRENT_PHOTOS_OK"]))

        startRental(app, plate: demoPlate)
        for shot in ["左前", "右前", "左後", "右後"] {
            try captureWithTestPhoto(app, shot: shot, expectPass: true)
        }
        tap(app.buttons.containing(label: "檢視並完成取車檢查").firstMatch, app)
        tap(app.buttons.containing(label: "完成取車檢查").firstMatch, app)
        tap(app.buttons.containing(label: "開始租借").firstMatch, app)
        XCTAssertTrue(app.navigationBars["租用中"].waitForExistence(timeout: 20), "取車完成後應進入租用中")

        // 取車照片：後端收到的是 Core ML 的真實辨識結果（不是 Demo 劇本、不是拿資料庫車牌冒充）
        let pipeline = try await api.pipelineOfLatestSession(vehicleID: "demo-admin-rdl7827")
        let pickups = (pipeline["inspection_detail"] as? [String: Any])?["comparisons"] as? [[String: Any]] ?? []
        let validations = pickups.compactMap { ($0["pickup_photo"] as? [String: Any]) }.filter { $0["category"] as? String == "exterior" }
        XCTAssertEqual(validations.count, 4)
        for v in validations {
            XCTAssertEqual(v["validation_mode"] as? String, "coreml")
            let val = v["validation"] as? [String: Any]
            XCTAssertEqual((val?["plate_text"] as? String)?.replacingOccurrences(of: "-", with: ""), "RDL7827")
            XCTAssertNotEqual((val?["model_versions"] as? [String: Any])?["mode"] as? String, "demo")
        }

        // 還車
        tap(app.buttons["begin-return"], app)
        tap(app.buttons.containing(label: "使用系統估算值").firstMatch, app)
        tap(app.buttons.containing(label: "確認還車資訊").firstMatch, app)
        for shot in ["左前", "右前", "左後", "右後"] {
            try captureWithTestPhoto(app, shot: shot, expectPass: true, stage: "return")
        }
        tap(app.buttons.containing(label: "檢視並完成還車拍攝").firstMatch, app)
        tap(app.buttons.containing(label: "完成還車拍攝").firstMatch, app)
        XCTAssertTrue(app.staticTexts["analysis-progress-text"].waitForExistence(timeout: 30), "分析中應顯示進度")
        attach(app, "還車 AI 分析進度")
        // 進度文字消失＝分析結束（完成或失敗）；「確認還車」在清單底部，延遲渲染，要捲動才會出現
        let progress = app.staticTexts["analysis-progress-text"]
        let gone = expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: progress)
        await fulfillment(of: [gone], timeout: 240)
        attach(app, "AI 檢測完成")
        let confirm = app.buttons.matching(NSPredicate(format: "label CONTAINS '確認還車' AND NOT (label CONTAINS '資訊')")).firstMatch
        scrollTo(confirm, app)
        XCTAssertTrue(confirm.exists, "AI 檢測完成後應出現確認還車")
        confirm.tap()
        XCTAssertTrue(app.staticTexts["還車完成"].waitForExistence(timeout: 20))

        let vehicle = try await api.appVehicle(plate: demoPlate)
        XCTAssertEqual(vehicle?["status"] as? String, "AVAILABLE")
        let row = try await api.fleetRow(car: demoPlate)
        XCTAssertEqual(row?["rentable"] as? Bool, true)
    }

    /// 拍到別台車的車牌：真實 OCR 讀出不同車牌 → 顯示不符提示、不能進下一步、後端沒有收到照片。
    func testWrongPlateIsRejectedByRealOCR() async throws {
        _ = try await api.call("POST", "/api/ops/devtools/demo-vehicles", ["plate": demoPlate, "lat": 25.0179, "lng": 121.5372])
        let app = launchApp(photos: try XCTUnwrap(env["IRENT_PHOTOS_WRONG"]))
        startRental(app, plate: demoPlate)
        try captureWithTestPhoto(app, shot: "左前", expectPass: false)
        XCTAssertTrue(app.staticTexts.containing(label: "不符").firstMatch.exists, "應顯示車牌不符")
        attach(app, "車牌不符")
        let session = try await api.activeSession()
        XCTAssertEqual(((session?["pickup"] as? [String: Any])?["received"] as? [Any])?.count, 0)
    }

    /// AI 分析進行中：結果頁顯示進度 → 取消還車 → 回到租用中，後端維持 RENTED、舊結果不寫回。
    func testCancelReturnWhileAnalyzingShowsProgressAndReturnsToRental() async throws {
        let dataset = try XCTUnwrap(env["IRENT_DATASET"])
        let s = try await api.prepareAnalyzingReturn(vehicleID: "demo-rdg-9853", car: "RDG9853", dataset: dataset)
        let app = launchApp(photos: nil)
        tap(app.buttons.containing(label: "檢視並完成還車拍攝").firstMatch, app)
        tap(app.buttons.containing(label: "完成還車拍攝").firstMatch, app)
        XCTAssertTrue(app.staticTexts["analysis-progress-text"].waitForExistence(timeout: 20), "分析中應顯示進度文字")
        XCTAssertTrue(app.progressIndicators["analysis-progress-bar"].exists, "分析中應顯示進度條")
        attach(app, "分析進度")

        let cancel = app.buttons["cancel-return"]
        scrollTo(cancel, app)
        XCTAssertTrue(cancel.isEnabled)
        cancel.tap()
        let confirmButtons = app.buttons.matching(NSPredicate(format: "label == %@", "取消還車，繼續租用"))
        XCTAssertTrue(confirmButtons.element(boundBy: 0).waitForExistence(timeout: 5))
        confirmButtons.element(boundBy: confirmButtons.count - 1).tap()      // 確認對話框中的按鈕
        XCTAssertTrue(app.navigationBars["租用中"].waitForExistence(timeout: 15), "取消後應回到租用中")
        attach(app, "取消還車後")

        var state = try await api.session(s)
        XCTAssertEqual(state["state"] as? String, "RENTED")
        try await Task.sleep(for: .seconds(35))                              // 背景分析跑完
        state = try await api.session(s)
        XCTAssertEqual(state["state"] as? String, "RENTED", "過期的 AI 結果不得把狀態推回檢測完成")
        XCTAssertTrue(app.navigationBars["租用中"].exists)
    }

    /// 案件已被營運人員裁決：取消按鈕停用並顯示原因（後端不會刪除裁決或任務）。
    func testCancelReturnDisabledAfterOpsDecision() async throws {
        let s = try await api.prepareFixtureInspected()
        let detail = try await api.session(s)
        let rental = try XCTUnwrap(detail["rental_id"] as? String)
        let decided = try await api.call("POST", "/api/decision", ["case_id": "RI-\(rental)-右後", "decision": "confirm"])
        XCTAssertEqual(decided.status, 200)
        let app = launchApp(photos: nil)
        let cancel = app.buttons["cancel-return"]
        _ = app.staticTexts.containing(label: "AI 檢出").firstMatch.waitForExistence(timeout: 20)   // 結果頁載入
        scrollTo(cancel, app)
        XCTAssertTrue(cancel.exists, "結果頁應有取消還車按鈕")
        XCTAssertFalse(cancel.isEnabled, "已裁決時取消按鈕應停用")
        XCTAssertTrue(app.staticTexts.containing(label: "營運人員").firstMatch.exists)
        attach(app, "已裁決不可取消")
    }

    // MARK: - App 操作

    private func launchApp(photos: String?) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-developerMode", "YES", "-apiBaseURLOverride", api.base.absoluteString, "-demoMode", "NO"]
        if let photos { app.launchEnvironment["IRENT_UITEST_PHOTO_DIR"] = photos }
        app.launch()
        return app
    }

    /// 推薦車輛（Demo 車置頂）→ 車輛資訊 → 開始使用 → 取車檢查。
    private func startRental(_ app: XCUIApplication, plate: String) {
        // 推薦清單那一列（含價格）；地圖標註的無障礙標籤也含車牌，要區分開
        let row = app.buttons.matching(NSPredicate(format: "label CONTAINS %@ AND label CONTAINS 'NT$'", plate)).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 30), "後台建立的車輛應出現在 App")
        attach(app, "App 出現 Demo 車輛")
        let start = app.buttons.containing(label: "開始使用").firstMatch
        for _ in 0..<3 where !start.exists {          // 地圖鏡頭動畫期間的點擊偶爾會被吞掉：沒彈出就再點一次
            row.tap()
            _ = start.waitForExistence(timeout: 5)
        }
        tap(start, app)
    }

    private func captureWithTestPhoto(_ app: XCUIApplication, shot: String, expectPass: Bool, stage: String = "pickup") throws {
        tap(app.buttons.containing(label: "拍攝下一張：\(shot)").firstMatch, app)
        tap(app.buttons["uitest-photo"], app)
        let next = app.buttons.matching(NSPredicate(format: "label CONTAINS '下一個角度' OR label CONTAINS '回到清單'")).firstMatch
        let failed = app.staticTexts.containing(label: "車牌需要重新拍攝").firstMatch
        let deadline = Date().addingTimeInterval(60)
        while Date() < deadline, !next.exists, !failed.exists, !app.staticTexts.containing(label: "重拍").firstMatch.exists {
            _ = next.waitForExistence(timeout: 1)
        }
        if expectPass {
            if !next.exists { attach(app, "\(stage) \(shot) 未通過") }
            XCTAssertTrue(next.exists, "\(stage) \(shot)：真實 OCR 應辨識出租約車牌並通過")
            // 等上傳完成（已同步）再離開，避免清單畫面暫時顯示待上傳
            _ = app.staticTexts.containing(label: "已同步到伺服器").firstMatch.waitForExistence(timeout: 20)
            next.tap()
        } else {
            XCTAssertFalse(next.exists, "車牌不符不應通過")
        }
    }

    private func tap(_ element: XCUIElement, _ app: XCUIApplication, timeout: TimeInterval = 20) {
        if !element.waitForExistence(timeout: timeout) { scrollTo(element, app) }
        scrollTo(element, app)
        XCTAssertTrue(element.exists, "找不到元素：\(element)")
        element.tap()
    }

    private func scrollTo(_ element: XCUIElement, _ app: XCUIApplication) {
        var n = 0
        while n < 10, !(element.exists && element.isHittable) {
            app.swipeUp()
            n += 1
        }
    }

    private func attach(_ app: XCUIApplication, _ name: String) {
        let a = XCTAttachment(screenshot: app.screenshot())
        a.name = name
        a.lifetime = .keepAlways
        add(a)
    }
}

private extension XCUIElementQuery {
    func containing(label: String) -> XCUIElementQuery { matching(NSPredicate(format: "label CONTAINS %@", label)) }
}

// MARK: - 測試後端（管理者 API 準備情境、驗證結果）

private struct Backend {
    let base: URL
    let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.httpCookieAcceptPolicy = .always
        c.httpShouldSetCookies = true
        return URLSession(configuration: c)
    }()

    @discardableResult
    func call(_ method: String, _ path: String, _ body: [String: Any]? = nil) async throws -> (status: Int, json: Any?) {
        var req = URLRequest(url: base.appending(path: path))
        req.httpMethod = method
        req.timeoutInterval = 30
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, resp) = try await session.data(for: req)
        return ((resp as? HTTPURLResponse)?.statusCode ?? 0, try? JSONSerialization.jsonObject(with: data))
    }

    func login() async throws {
        let r = try await call("POST", "/api/auth/login", ["username": "admin", "password": "admin-demo"])
        guard r.status == 200 else { throw NSError(domain: "login", code: r.status) }
    }

    func devVehicles() async throws -> [[String: Any]] {
        ((try await call("GET", "/api/ops/devtools/vehicles").json as? [String: Any])?["vehicles"] as? [[String: Any]]) ?? []
    }

    func appVehicle(plate: String) async throws -> [String: Any]? {
        let list = (try await call("GET", "/v1/rental-sessions/vehicles").json as? [String: Any])?["vehicles"] as? [[String: Any]]
        return list?.first { $0["plate"] as? String == plate }
    }

    func fleetRow(car: String) async throws -> [String: Any]? {
        ((try await call("GET", "/api/ops/fleet").json as? [String: Any])?["fleet"] as? [[String: Any]])?.first { $0["car"] as? String == car }
    }

    func activeSession() async throws -> [String: Any]? {
        (try await call("GET", "/v1/rental-sessions/active").json as? [String: Any])?["session"] as? [String: Any]
    }

    func session(_ id: String) async throws -> [String: Any] {
        (try await call("GET", "/v1/rental-sessions/\(id)").json as? [String: Any]) ?? [:]
    }

    func pipelineOfLatestSession(vehicleID: String) async throws -> [String: Any] {
        let sessions = ((try await call("GET", "/api/ops/devtools/sessions").json as? [String: Any])?["sessions"] as? [[String: Any]]) ?? []
        let sid = sessions.first { ($0["vehicle"] as? [String: Any])?["vehicle_id"] as? String == vehicleID }?["session_id"] as? String ?? ""
        return (try await call("GET", "/api/ops/devtools/sessions/\(sid)/pipeline").json as? [String: Any]) ?? [:]
    }

    /// 用 API 把一台車推進到「四角還車照已上傳、尚未按完成」：還車照故意用錯位角度（四角都需 Pro 複核，分析較久）。
    func prepareAnalyzingReturn(vehicleID: String, car: String, dataset: String) async throws -> String {
        var s = try await start(vehicleID)
        let angles = ["左前", "右前", "左後", "右後"]
        for a in angles { try await upload(s, stage: "pickup", view: a, file: "\(dataset)/\(car)\(a) 借.jpg", mode: "coreml") }
        s = try await advanceToPhotoInspection(s)
        let rot = Dictionary(uniqueKeysWithValues: zip(angles, angles.dropFirst() + angles.prefix(1)))
        for a in angles { try await upload(s, stage: "return", view: a, file: "\(dataset)/\(car)\(rot[a]!) 還.jpg", mode: "coreml") }
        // 不送 photos/return/finish：車內照未略過 → 分析還沒開始；由 App 按「完成還車拍攝」時才開始（與真實流程相同）
        return s["session_id"] as! String
    }

    /// 固定劇本車（SIM-ABC-1234）走到檢測完成（固定劇本結果：右後新損＋車內髒汙，非真實 AI）。
    func prepareFixtureInspected() async throws -> String {
        var s = try await start("SIM-ABC-1234")
        let views = ["左前", "右前", "左後", "右後", "車內"]
        for (i, v) in views.enumerated() { try await upload(s, stage: "pickup", view: v, seed: 10 + i, mode: "demo") }
        s = try await advanceToPhotoInspection(s)
        for (i, v) in views.enumerated() { try await upload(s, stage: "return", view: v, seed: 30 + i, mode: "demo") }
        return s["session_id"] as! String
    }

    private func start(_ vehicleID: String) async throws -> [String: Any] {
        let r = try await call("POST", "/v1/rental-sessions", ["vehicle_id": vehicleID])
        guard r.status == 201, let s = r.json as? [String: Any] else { throw NSError(domain: "start", code: r.status) }
        return s
    }

    private func advanceToPhotoInspection(_ s: [String: Any]) async throws -> [String: Any] {
        let sid = s["session_id"] as! String
        try await call("POST", "/v1/rental-sessions/\(sid)/photos/pickup/finish")
        try await call("POST", "/v1/rental-sessions/\(sid)/pickup/complete")
        try await call("POST", "/v1/rental-sessions/\(sid)/return/initiate", [:])
        let start = s["start_odometer_km"] as? Int ?? 0
        let r = try await call("POST", "/v1/rental-sessions/\(sid)/return/info", ["end_odometer_km": start + 12])
        return (r.json as? [String: Any]) ?? s
    }

    private func upload(_ s: [String: Any], stage: String, view: String, file: String? = nil, seed: Int = 0, mode: String) async throws {
        let data: Data
        if let file { data = try Data(contentsOf: URL(fileURLWithPath: file)) } else { data = Self.syntheticJPEG(seed: seed) }
        let vehicle = s["vehicle"] as! [String: Any]
        let plate = vehicle["plate"] as! String
        let codes = ["左前": "FRONT_LEFT", "右前": "FRONT_RIGHT", "左後": "REAR_LEFT", "右後": "REAR_RIGHT", "車內": "INTERIOR"]
        let local: [String: Any] = ["passed": true, "plateText": view == "車內" ? NSNull() : plate, "errors": [],
                                    "modelVersions": ["mode": mode == "demo" ? "demo" : "uitest-fixture"]]
        let fields: [String: String] = [
            "rental_id": s["rental_id"] as! String, "car_id": vehicle["vehicle_id"] as! String, "expected_plate": plate,
            "stage": stage, "view": view, "recognized_plate": plate,
            "image_sha256": SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(),
            "captured_at": ISO8601DateFormatter().string(from: Date()),
            "local_result_json": String(decoding: try JSONSerialization.data(withJSONObject: local), as: UTF8.self),
            "photo_id": UUID().uuidString, "angle": codes[view]!, "photo_category": view == "車內" ? "interior" : "exterior",
            "validation_mode": mode,
        ]
        let boundary = "B-\(UUID().uuidString)"
        var body = Data()
        for (k, v) in fields { body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(k)\"\r\n\r\n\(v)\r\n".utf8)) }
        body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"p.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".utf8))
        body.append(data)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        var req = URLRequest(url: base.appending(path: "/v1/mobile-inspections/photos"))
        req.httpMethod = "POST"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
        let (_, resp) = try await session.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard code == 201 else { throw NSError(domain: "upload \(stage) \(view)", code: code) }
    }

    /// 固定劇本車用的佔位照（固定劇本不送 AI）：每個 seed 產生不同內容的小 JPEG。
    static func syntheticJPEG(seed: Int) -> Data {
        let size = CGSize(width: 64, height: 48)
        let renderer = UIGraphicsImageRenderer(size: size)
        let image = renderer.image { ctx in
            UIColor(red: CGFloat(seed % 255) / 255, green: 0.4, blue: 0.3, alpha: 1).setFill()
            ctx.fill(CGRect(origin: .zero, size: size))
        }
        return image.jpegData(compressionQuality: 0.9)!
    }
}

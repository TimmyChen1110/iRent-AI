import XCTest

/// UI 煙霧測試。相簿流程需要先把樣本照片加進 Simulator：
///   xcrun simctl addmedia booted "<照片路徑>"
/// 後端要跑在 PQG_API_BASE_URL 指到的位置（預設 http://127.0.0.1:8000）。
final class PhotoQualityGuardUITests: XCTestCase {

    private var app: XCUIApplication?

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    /// 失敗時把畫面與無障礙樹存下來（PQG_SHOT_DIR 有設才存），方便排查。
    override func tearDownWithError() throws {
        if let run = testRun, run.totalFailureCount > 0, let app,
           let dir = ProcessInfo.processInfo.environment["PQG_SHOT_DIR"] {
            let base = URL(fileURLWithPath: dir).appending(path: "fail-\(name.replacingOccurrences(of: "[^A-Za-z0-9]", with: "_", options: .regularExpression))")
            try? app.screenshot().pngRepresentation.write(to: base.appendingPathExtension("png"))
            try? app.debugDescription.write(to: base.appendingPathExtension("txt"), atomically: true, encoding: .utf8)
        }
        app = nil
    }

    private func launch(apiBaseURL: String? = nil) -> XCUIApplication {
        let app = XCUIApplication()
        if let apiBaseURL { app.launchEnvironment["PQG_API_BASE_URL"] = apiBaseURL }
        app.launch()
        self.app = app
        return app
    }

    func testHomeScreenShowsCoreElements() {
        let app = launch()
        XCTAssertTrue(app.staticTexts["header.title"].waitForExistence(timeout: 5))
        snap(app, "01-home")
        XCTAssertTrue(app.buttons["angle.none"].exists)
        XCTAssertTrue(app.buttons["angle.左前"].exists)
        XCTAssertTrue(app.buttons["action.camera"].exists)
        XCTAssertTrue(app.buttons["action.library"].exists)
        XCTAssertEqual(app.staticTexts["status.line"].label, "尚未選擇照片")
        XCTAssertTrue(app.staticTexts["photo.anglePill"].label.contains("未指定"))
    }

    func testAngleChipUpdatesPill() {
        let app = launch()
        app.buttons["angle.左前"].tap()
        XCTAssertTrue(app.staticTexts["photo.anglePill"].label.contains("左前方"))
        app.buttons["angle.none"].tap()
        XCTAssertTrue(app.staticTexts["photo.anglePill"].label.contains("未指定"))
    }

    /// 按「開啟相機拍攝」不可 crash：沒有相機的 Simulator 要出現友善提示；
    /// 有模擬相機的 Simulator（Xcode 27+）會開系統相機，取消後要回到首頁。
    func testCameraButtonNeverCrashes() {
        let app = launch()
        app.buttons["action.camera"].tap()
        let alert = app.alerts.firstMatch
        let cameraOpened = app.buttons.matching(NSPredicate(format: "label == 'Zoom' OR label == 'Cancel' OR label == '取消'")).firstMatch
        let appeared = alert.waitForExistence(timeout: 5) || cameraOpened.waitForExistence(timeout: 5)
        XCTAssertTrue(appeared, "既沒有提示也沒有相機畫面")
        snap(app, "07-camera")
        if alert.exists {
            XCTAssertTrue(alert.staticTexts["目前裝置無法使用相機，請從相簿選擇照片。"].exists)
            alert.buttons["好"].tap()
        } else {
            let cancel = app.buttons.matching(NSPredicate(format: "label == 'Cancel' OR label == '取消'")).firstMatch
            if cancel.waitForExistence(timeout: 3) { cancel.tap() }
        }
        XCTAssertTrue(app.staticTexts["header.title"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["status.line"].label, "尚未選擇照片")
    }

    /// 完整流程：相簿選圖 → 自動送 API → PASS → 換角度自動重跑 → FAIL → 清除。
    func testLibraryPhotoRunsThroughPassFailAndReset() throws {
        let app = launch(apiBaseURL: ProcessInfo.processInfo.environment["PQG_API_BASE_URL"])
        try pickFirstLibraryPhoto(app)

        // loading 先出現（可能很快）→ 然後結果
        let title = app.staticTexts["result.title"]
        XCTAssertTrue(title.waitForExistence(timeout: 90), "分析結果沒有出現（後端有跑嗎？）")
        XCTAssertEqual(title.label, "照片檢查通過")
        snap(app, "02-pass-top")
        app.swipeUp(); app.swipeUp(); snap(app, "03-pass-stages")
        XCTAssertTrue(app.staticTexts["plate.number"].exists)
        XCTAssertTrue(app.otherElements["plate.overlay"].exists || app.images["plate.overlay"].exists)
        XCTAssertTrue(app.staticTexts["view.detected"].exists)

        // 換成錯的角度 → 自動重跑 → FAIL
        app.buttons["angle.右前"].firstMatch.tap()
        let fail = app.otherElements["result.fail"]
        XCTAssertTrue(fail.waitForExistence(timeout: 90))
        XCTAssertEqual(app.staticTexts["result.title"].label, "需要重新拍攝")
        snap(app, "04-fail-top")
        app.swipeUp(); app.swipeUp(); app.swipeUp(); snap(app, "05-fail-stages")
        XCTAssertTrue(app.staticTexts["result.message"].label.contains("拍攝角度不符"))
        XCTAssertTrue(app.buttons["result.retake"].exists)
        XCTAssertTrue(app.buttons["result.changeAngle"].exists)

        // 清除
        app.buttons["action.reset"].firstMatch.tap()
        XCTAssertEqual(app.staticTexts["status.line"].label, "尚未選擇照片")
        XCTAssertFalse(app.staticTexts["result.title"].exists)
    }

    /// API 打不到 → 使用者文案 + 開發者資訊。
    func testAPIErrorShowsFriendlyCard() throws {
        let app = launch(apiBaseURL: "http://127.0.0.1:8999")
        try pickFirstLibraryPhoto(app)
        let title = app.staticTexts["result.title"]
        XCTAssertTrue(title.waitForExistence(timeout: 60))
        XCTAssertEqual(title.label, "目前無法完成照片檢查")
        snap(app, "06-apierror")
        XCTAssertTrue(app.buttons["result.retry"].exists)
        XCTAssertTrue(app.buttons["result.retake"].exists)
    }

    // MARK: - Helpers

    /// 把目前畫面存成 PNG（PQG_SHOT_DIR 有設才存），方便人工核對 UI。
    private func snap(_ app: XCUIApplication, _ name: String) {
        guard let dir = ProcessInfo.processInfo.environment["PQG_SHOT_DIR"] else { return }
        let png = app.screenshot().pngRepresentation
        try? png.write(to: URL(fileURLWithPath: dir).appending(path: "\(name).png"))
    }

    /// 開 PhotosPicker 並點第一張照片。PhotosPicker 是系統的 remote view，XCUITest 能看到它的 image 元素。
    private func pickFirstLibraryPhoto(_ app: XCUIApplication) throws {
        app.buttons["action.library"].tap()
        let picker = app.otherElements.matching(NSPredicate(format: "identifier CONTAINS[c] 'PhotosPicker' OR label CONTAINS[c] 'Photos'")).firstMatch
        _ = picker.waitForExistence(timeout: 5)
        let firstPhoto = app.images.matching(NSPredicate(format: "label CONTAINS[c] 'Photo' OR label CONTAINS[c] '照片'")).firstMatch
        guard firstPhoto.waitForExistence(timeout: 10) else {
            throw XCTSkip("PhotosPicker 裡找不到照片元素。請先 xcrun simctl addmedia booted <照片>。")
        }
        firstPhoto.tap()
    }
}

import XCTest
@testable import PhotoQualityGuard

final class ModelsAndAPITests: XCTestCase {

    // MARK: - Response decoding（真實 backend 回應）

    func testDecodesRealPassResponse() throws {
        let r = try PhotoQualityAPI.decoder.decode(PhotoQualityResponse.self, from: Data(Fixtures.passJSON.utf8))
        XCTAssertTrue(r.passed)
        XCTAssertEqual(r.plateText, "RCG-2235")
        XCTAssertEqual(r.detectedView, "左後")
        XCTAssertNil(r.requiredView)
        XCTAssertEqual(r.stages.map(\.id), ["readability", "plate", "view"])
        XCTAssertEqual(r.stages.map(\.status), [.passed, .passed, .passed])
        XCTAssertEqual(r.debug.plateBbox?.count, 4)
        XCTAssertEqual(r.debug.orientationRotation, 0)
        XCTAssertEqual(r.debug.viewProbabilities?.count, 4)
        XCTAssertEqual(Set(r.debug.viewProbabilities!.map(\.label)), ["左前", "右前", "左後", "右後"])
        XCTAssertGreaterThan(r.debug.elapsedMs, 0)
        XCTAssertTrue((0...100).contains(r.qualityScore100))
    }

    func testDecodesRealWrongViewResponse() throws {
        let r = try PhotoQualityAPI.decoder.decode(PhotoQualityResponse.self, from: Data(Fixtures.wrongViewJSON.utf8))
        XCTAssertFalse(r.passed)
        XCTAssertEqual(r.requiredView, .rightFront)
        XCTAssertEqual(r.firstFailedStage?.id, "view")
        XCTAssertEqual(r.firstFailedStage?.errors.first?.code, "WRONG_VIEW")
        XCTAssertTrue(r.firstFailedStage!.errors.first!.message.contains("拍攝角度不符"))
        // 第 3 關失敗時仍要有判定角度可顯示
        XCTAssertEqual(r.detectedView, "左後")
    }

    func testDecodesSkippedStagesAndImageInvalid() throws {
        // backend main.py 對解不開的圖回的固定結構
        let json = """
        {"passed": false, "quality_score": 0.0, "required_view": "前車內",
         "stages": [
           {"id":"readability","name":"基本可讀性","status":"failed","errors":[{"code":"IMAGE_INVALID","message":"無法讀取照片，請重新拍攝"}],"summary":"檔案無法解碼成圖片"},
           {"id":"plate","name":"車牌偵測","status":"skipped","errors":[],"summary":"前一關沒過，尚未執行"},
           {"id":"view","name":"四角辨識","status":"skipped","errors":[],"summary":"前一關沒過，尚未執行"}],
         "errors":[{"code":"IMAGE_INVALID","message":"無法讀取照片，請重新拍攝"}],
         "debug":{"stages_run":["stage0_readability"],"elapsed_ms":0.3}}
        """
        let r = try PhotoQualityAPI.decoder.decode(PhotoQualityResponse.self, from: Data(json.utf8))
        XCTAssertEqual(r.requiredView, .frontInterior)
        XCTAssertEqual(r.skippedStages.count, 2)
        XCTAssertEqual(r.debug.stage1Advisories, [])
        XCTAssertNil(r.debug.plateBbox)
    }

    // MARK: - Request encoding

    private func encodedJSON(_ request: PhotoQualityRequest) throws -> [String: Any] {
        let data = try PhotoQualityAPI.encoder.encode(request)
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func testRequestOmitsRequiredViewWhenNotSpecified() throws {
        let json = try encodedJSON(PhotoQualityRequest(imageBase64: "QUJD"))
        XCTAssertEqual(Set(json.keys), ["image_base64"], "不指定角度時 payload 只能有 image_base64（跟 Web 版一致）")
        XCTAssertEqual(json["image_base64"] as? String, "QUJD")
    }

    func testRequestSendsExactBackendChineseValue() throws {
        for view in RequiredView.allCases {
            let json = try encodedJSON(PhotoQualityRequest(requiredView: view, imageBase64: "QUJD"))
            XCTAssertEqual(json["required_view"] as? String, view.rawValue)
        }
        XCTAssertEqual(RequiredView.allCases.map(\.rawValue), ["左前", "右前", "左後", "右後", "前車內", "後車內"])
    }

    func testBase64HasNoDataURLPrefix() throws {
        let image = TestImages.solid(width: 480, height: 270)
        let prepared = try ImagePreparation.prepare(image)
        XCTAssertFalse(prepared.base64.hasPrefix("data:"))
        XCTAssertNotNil(Data(base64Encoded: prepared.base64))
    }

    // MARK: - Image preparation（不縮圖、轉正）

    func testPreparationKeepsPixelSizeAndUprightsOrientation() throws {
        // 像素是 400x200 橫的，但 orientation = .right 代表「顯示時要順時針轉 90°」→ 正立後是 200x400
        let landscapeCG = TestImages.solid(width: 400, height: 200).cgImage!
        let rotated = UIImage(cgImage: landscapeCG, scale: 1, orientation: .right)
        XCTAssertEqual(rotated.size, CGSize(width: 200, height: 400))

        let prepared = try ImagePreparation.prepare(rotated)
        XCTAssertEqual(prepared.pixelSize, CGSize(width: 200, height: 400), "不可縮圖，只能轉正")
        XCTAssertEqual(prepared.image.imageOrientation, .up)

        // 解回來的 JPEG 像素本身就是直的（backend 不需要 EXIF）
        let decoded = try XCTUnwrap(UIImage(data: prepared.jpegData))
        XCTAssertEqual(decoded.cgImage?.width, 200)
        XCTAssertEqual(decoded.cgImage?.height, 400)
    }

    func testPreparationDoesNotResizeLargePhoto() throws {
        let big = TestImages.solid(width: 3024, height: 4032)
        let prepared = try ImagePreparation.prepare(big)
        XCTAssertEqual(prepared.pixelSize, CGSize(width: 3024, height: 4032))
    }

    // MARK: - BBox geometry（沿用 Web renderAnnotatedPhoto 語意）

    func testBBoxGeometryWithoutRotation() {
        let g = PlateBoxGeometry(pixelSize: CGSize(width: 1000, height: 2000), rotation: 0)
        // 容器 500x1000 → scale 0.5，無 letterbox
        let layout = g.layout(in: CGSize(width: 500, height: 1000), bbox: [100, 200, 300, 400])
        XCTAssertEqual(layout.scale, 0.5)
        XCTAssertEqual(layout.fittedRect, CGRect(x: 0, y: 0, width: 500, height: 1000))
        XCTAssertEqual(layout.boxRect, CGRect(x: 50, y: 100, width: 100, height: 100))
        // 容器 500x2000 → 上下 letterbox 各 500
        let padded = g.layout(in: CGSize(width: 500, height: 2000), bbox: [100, 200, 300, 400])
        XCTAssertEqual(padded.fittedRect.origin, CGPoint(x: 0, y: 500))
        XCTAssertEqual(padded.boxRect, CGRect(x: 50, y: 600, width: 100, height: 100))
    }

    func testBBoxGeometryWithRotation90SwapsAxes() {
        // 原圖 2000 寬 1000 高（橫躺），backend 逆時針轉 90° 後變 1000x2000，bbox 是轉正後座標
        let g = PlateBoxGeometry(pixelSize: CGSize(width: 2000, height: 1000), rotation: 90)
        XCTAssertEqual(g.rotatedPixelSize, CGSize(width: 1000, height: 2000))
        let layout = g.layout(in: CGSize(width: 500, height: 1000), bbox: [100, 200, 300, 400])
        XCTAssertEqual(layout.scale, 0.5)
        // 原圖 frame 仍是未旋轉尺寸 × scale，旋轉以 fitted 中心為軸
        XCTAssertEqual(layout.imageFrameSize, CGSize(width: 1000, height: 500))
        XCTAssertEqual(layout.imageCenter, CGPoint(x: 250, y: 500))
        XCTAssertEqual(layout.boxRect, CGRect(x: 50, y: 100, width: 100, height: 100))
    }

    // MARK: - Live API（後端有跑才測，否則 skip）

    private static let sampleURL: URL? = {
        // ios/PhotoQualityGuard/PhotoQualityGuardTests/ → 往上找到 repo 根
        var url = URL(fileURLWithPath: #filePath)
        for _ in 0..<6 { url.deleteLastPathComponent() }
        let candidate = url.appending(path: "iRent - 運用 AI 打造 iRent 智能車況管家：優化租還車體驗與營運效率/沒有進行索賠/RCG2235左後 借.jpg")
        return FileManager.default.fileExists(atPath: candidate.path) ? candidate : nil
    }()

    private func liveAPIOrSkip() async throws -> PhotoQualityAPI {
        let api = PhotoQualityAPI(baseURL: AppConfig.apiBaseURL)
        var req = URLRequest(url: api.baseURL.appending(path: "healthz"), timeoutInterval: 3)
        req.httpMethod = "GET"
        do {
            let (_, resp) = try await URLSession.shared.data(for: req)
            guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw XCTSkip("backend 未回 200") }
        } catch let e as XCTSkip { throw e } catch {
            throw XCTSkip("backend 未啟動於 \(api.baseURL)：\(error.localizedDescription)")
        }
        return api
    }

    func testLiveBackendRoundTripPassAndWrongView() async throws {
        let api = try await liveAPIOrSkip()
        guard let sampleURL = Self.sampleURL, let image = UIImage(contentsOfFile: sampleURL.path) else {
            throw XCTSkip("找不到樣本照片")
        }
        let prepared = try ImagePreparation.prepare(image)

        let pass = try await api.check(PhotoQualityRequest(imageBase64: prepared.base64))
        XCTAssertTrue(pass.passed)
        XCTAssertEqual(pass.plateText, "RCG-2235")
        XCTAssertEqual(pass.detectedView, "左後")
        XCTAssertNil(pass.requiredView)
        // bbox 必須落在我們送出去的那張圖的範圍內
        let bbox = try XCTUnwrap(pass.debug.plateBbox)
        XCTAssertLessThanOrEqual(CGFloat(bbox[2]), prepared.pixelSize.width)
        XCTAssertLessThanOrEqual(CGFloat(bbox[3]), prepared.pixelSize.height)

        let fail = try await api.check(PhotoQualityRequest(requiredView: .rightFront, imageBase64: prepared.base64))
        XCTAssertFalse(fail.passed)
        XCTAssertEqual(fail.requiredView, .rightFront)
        XCTAssertEqual(fail.firstFailedStage?.errors.first?.code, "WRONG_VIEW")
    }

    /// 橫躺照片：把樣本逆時針轉 90° 再送，backend 方向防護網應回 orientation_rotation ≠ 0，
    /// 且 bbox 落在「轉正後」的座標系裡（寬高互換）。這是 PlateOverlayImage 旋轉語意的依據。
    func testLiveBackendOrientationRotationSemantics() async throws {
        let api = try await liveAPIOrSkip()
        guard let sampleURL = Self.sampleURL, let image = UIImage(contentsOfFile: sampleURL.path) else {
            throw XCTSkip("找不到樣本照片")
        }
        let upright = ImagePreparation.normalizedUpright(image)
        // 像素真的轉 90°（不是只改 orientation 旗標），模擬 EXIF 被清掉的橫躺照片
        let sideways = ImagePreparation.normalizedUpright(UIImage(cgImage: upright.cgImage!, scale: 1, orientation: .left))
        let prepared = try ImagePreparation.prepare(sideways)
        XCTAssertEqual(prepared.pixelSize, CGSize(width: upright.size.height, height: upright.size.width))

        let r = try await api.check(PhotoQualityRequest(imageBase64: prepared.base64))
        XCTAssertNotEqual(r.debug.orientationRotation, 0, "方向防護網應該有轉正")
        let g = PlateBoxGeometry(pixelSize: prepared.pixelSize, rotation: r.debug.orientationRotation)
        let bbox = try XCTUnwrap(r.debug.plateBbox)
        XCTAssertLessThanOrEqual(CGFloat(bbox[2]), g.rotatedPixelSize.width)
        XCTAssertLessThanOrEqual(CGFloat(bbox[3]), g.rotatedPixelSize.height)
        XCTAssertEqual(r.plateText, "RCG-2235")
    }

    func testLiveRequestCancellationThrowsCancellationError() async throws {
        let api = try await liveAPIOrSkip()
        let prepared = try ImagePreparation.prepare(TestImages.solid(width: 1280, height: 720))
        let task = Task { try await api.check(PhotoQualityRequest(imageBase64: prepared.base64)) }
        task.cancel()
        do {
            _ = try await task.value
            XCTFail("取消的請求不應回傳結果")
        } catch is CancellationError {
            // expected
        }
    }
}

enum TestImages {
    static func solid(width: Int, height: Int, color: UIColor = .gray) -> UIImage {
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        return UIGraphicsImageRenderer(size: CGSize(width: width, height: height), format: format).image { ctx in
            color.setFill()
            ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
            // 放一點紋理，避免被 backend 當成全白/全黑
            UIColor.black.setFill()
            ctx.fill(CGRect(x: width / 4, y: height / 4, width: width / 2, height: height / 2))
        }
    }
}

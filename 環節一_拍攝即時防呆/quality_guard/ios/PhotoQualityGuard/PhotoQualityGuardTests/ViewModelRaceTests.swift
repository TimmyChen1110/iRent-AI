import XCTest
@testable import PhotoQualityGuard

/// 用假的 URLProtocol 驗證 ViewModel 的取消／世代邏輯：舊請求不可覆蓋新請求。
final class MockURLProtocol: URLProtocol {
    nonisolated(unsafe) static var handler: (@Sendable (URLRequest) async throws -> (Int, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    private var loadTask: Task<Void, Never>?

    override func startLoading() {
        guard let handler = Self.handler else { return }
        let request = self.request
        // URLProtocol 不會把 httpBody 給我們，只有 httpBodyStream；讀出來給 handler。
        var bodyData = Data()
        if let stream = request.httpBodyStream {
            stream.open()
            let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 65536)
            defer { buffer.deallocate(); stream.close() }
            while stream.hasBytesAvailable {
                let n = stream.read(buffer, maxLength: 65536)
                if n <= 0 { break }
                bodyData.append(buffer, count: n)
            }
        }
        var withBody = request
        withBody.httpBody = bodyData
        loadTask = Task { [weak self] in
            guard let self else { return }
            do {
                let (status, data) = try await handler(withBody)
                let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
                client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
                client?.urlProtocol(self, didLoad: data)
                client?.urlProtocolDidFinishLoading(self)
            } catch {
                client?.urlProtocol(self, didFailWithError: error)
            }
        }
    }

    override func stopLoading() { loadTask?.cancel() }
}

@MainActor
final class ViewModelRaceTests: XCTestCase {

    private func makeModel() -> PhotoQualityViewModel {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let api = PhotoQualityAPI(baseURL: URL(string: "http://mock.local")!, session: URLSession(configuration: config))
        return PhotoQualityViewModel(api: api)
    }

    private func fixture(plate: String) -> Data {
        Data(Fixtures.passJSON.replacingOccurrences(of: "RCG-2235", with: plate).utf8)
    }

    private func waitUntil(_ timeout: TimeInterval = 5, _ condition: @escaping @MainActor () -> Bool) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if condition() { return true }
            try? await Task.sleep(for: .milliseconds(20))
        }
        return condition()
    }

    private func expectEventually(_ condition: @escaping @MainActor () -> Bool, file: StaticString = #filePath, line: UInt = #line) async {
        let ok = await waitUntil(5, condition)
        XCTAssertTrue(ok, "條件在時限內沒有成立", file: file, line: line)
    }

    func testLaterPhotoWinsOverSlowerEarlierRequest() async throws {
        // 小圖（A）的 request 慢回、大圖（B）的 request 快回。使用者先選 A 再選 B → 最後畫面必須是 B。
        MockURLProtocol.handler = { [fixtureA = fixture(plate: "AAA-1111"), fixtureB = fixture(plate: "BBB-2222")] request in
            let isSmall = (request.httpBody?.count ?? 0) < 20_000
            if isSmall {
                try await Task.sleep(for: .milliseconds(800))
                return (200, fixtureA)
            }
            try await Task.sleep(for: .milliseconds(50))
            return (200, fixtureB)
        }
        let model = makeModel()
        model.didPick(image: TestImages.solid(width: 480, height: 270))   // A：小
        await expectEventually({ model.isBusy })
        model.didPick(image: TestImages.solid(width: 1600, height: 1200)) // B：大

        await expectEventually({ if case .result = model.state { return true }; return false })
        guard case .result(_, let r) = model.state else { return XCTFail("應該有結果") }
        XCTAssertEqual(r.plateText, "BBB-2222")

        // 再等超過 A 的延遲，確認 A 沒有回頭覆蓋
        try await Task.sleep(for: .milliseconds(1200))
        guard case .result(_, let still) = model.state else { return XCTFail("狀態不應改變") }
        XCTAssertEqual(still.plateText, "BBB-2222")
    }

    func testResetCancelsInFlightAndStaysIdle() async throws {
        MockURLProtocol.handler = { [fixtureA = fixture(plate: "AAA-1111")] _ in
            try await Task.sleep(for: .milliseconds(600))
            return (200, fixtureA)
        }
        let model = makeModel()
        model.didPick(image: TestImages.solid(width: 480, height: 270))
        await expectEventually({ model.isBusy })
        model.reset()
        if case .idle = model.state {} else { XCTFail("reset 後應為 idle") }
        try await Task.sleep(for: .milliseconds(900))
        if case .idle = model.state {} else { XCTFail("被取消的請求不可把狀態改回結果") }
    }

    func testChangingAngleReanalyzesSamePhotoWithNewRequiredView() async throws {
        nonisolated(unsafe) var seenViews: [String?] = []
        MockURLProtocol.handler = { [fixtureA = fixture(plate: "AAA-1111")] request in
            let body = try JSONSerialization.jsonObject(with: request.httpBody ?? Data()) as? [String: Any]
            seenViews.append(body?["required_view"] as? String)
            return (200, fixtureA)
        }
        let model = makeModel()
        model.didPick(image: TestImages.solid(width: 480, height: 270))
        await expectEventually({ if case .result = model.state { return true }; return false })
        model.select(view: .leftFront)
        await expectEventually({ seenViews.count == 2 })
        await expectEventually({ if case .result = model.state { return true }; return false })
        XCTAssertEqual(seenViews, [nil, "左前"])
    }

    func testTransportFailureBecomesFailedState() async throws {
        MockURLProtocol.handler = { _ in throw URLError(.cannotConnectToHost) }
        let model = makeModel()
        model.didPick(image: TestImages.solid(width: 480, height: 270))
        await expectEventually({ if case .failed = model.state { return true }; return false })
        guard case .failed(_, let failure) = model.state else { return XCTFail() }
        XCTAssertTrue(failure.developerDescription.contains("URLError"))
        XCTAssertNil(failure.httpStatus)
    }
}

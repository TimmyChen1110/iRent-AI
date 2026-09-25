import Foundation

/// API 失敗的分類。使用者只看到通用文案；細節放「開發者資訊」。
enum PhotoQualityAPIError: Error, Sendable {
    case transport(URLError)
    case httpStatus(Int, body: String)
    case decoding(String)
    case other(String)

    /// 給「開發者資訊」用
    var developerDescription: String {
        switch self {
        case .transport(let e): return "URLError \(e.code.rawValue): \(e.localizedDescription)"
        case .httpStatus(let code, let body): return "HTTP \(code)\n\(body.prefix(600))"
        case .decoding(let d): return "Decoding failed: \(d)"
        case .other(let d): return d
        }
    }

    var httpStatus: Int? {
        if case .httpStatus(let code, _) = self { return code }
        return nil
    }
}

/// `POST /api/photo-quality/check` 的 client。純 URLSession + async/await。
struct PhotoQualityAPI: Sendable {
    let baseURL: URL
    let session: URLSession

    init(baseURL: URL = AppConfig.apiBaseURL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    var checkEndpoint: URL { baseURL.appending(path: "api/photo-quality/check") }

    static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    func check(_ request: PhotoQualityRequest) async throws -> PhotoQualityResponse {
        var urlRequest = URLRequest(url: checkEndpoint, timeoutInterval: AppConfig.requestTimeout)
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.setValue("application/json", forHTTPHeaderField: "Accept")
        urlRequest.httpBody = try Self.encoder.encode(request)

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await session.data(for: urlRequest)
        } catch let error as URLError where error.code == .cancelled {
            throw CancellationError()
        } catch let error as URLError {
            throw PhotoQualityAPIError.transport(error)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            throw PhotoQualityAPIError.other(error.localizedDescription)
        }

        try Task.checkCancellation()

        guard let http = response as? HTTPURLResponse else {
            throw PhotoQualityAPIError.other("Non-HTTP response")
        }
        guard (200..<300).contains(http.statusCode) else {
            throw PhotoQualityAPIError.httpStatus(http.statusCode, body: String(decoding: data, as: UTF8.self))
        }
        do {
            return try Self.decoder.decode(PhotoQualityResponse.self, from: data)
        } catch {
            throw PhotoQualityAPIError.decoding(String(describing: error))
        }
    }
}

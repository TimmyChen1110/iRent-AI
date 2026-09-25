import Foundation

/// API 位置集中在這裡，不要散落在 View 裡。
///
/// - iOS Simulator：`127.0.0.1` 就是這台 Mac，預設值直接可用。
/// - 實體 iPhone：`127.0.0.1` 是 iPhone 自己。把 `developmentBaseURL` 改成 Mac 的區網 IP，
///   例如 `http://192.168.1.23:8000`，並用 `--host 0.0.0.0` 啟動 FastAPI。
/// - 也可以不改程式：在 Xcode Scheme → Run → Arguments → Environment Variables
///   加 `PQG_API_BASE_URL=http://192.168.1.23:8000`。
enum AppConfig {
    /// 開發環境預設（Simulator 用）
    static let developmentBaseURL = URL(string: "http://127.0.0.1:8000")!

    static var apiBaseURL: URL {
        if let raw = ProcessInfo.processInfo.environment["PQG_API_BASE_URL"],
           let url = URL(string: raw.trimmingCharacters(in: .whitespacesAndNewlines)) {
            return url
        }
        return developmentBaseURL
    }

    /// 單張檢查的逾時。backend 中位數 113 ms，但實體機上傳整張原圖要留餘裕。
    static let requestTimeout: TimeInterval = 60
}

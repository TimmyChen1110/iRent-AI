import SwiftUI
import Observation

/// 一次檢查失敗的原因（給 UI 顯示）
struct AnalysisFailure: Sendable {
    let developerDescription: String
    let httpStatus: Int?
    let endpoint: URL
}

/// 畫面狀態機。照片永遠跟著狀態走，不會出現「analyzing 但沒有照片」這種不可能的組合。
enum AnalysisState {
    case idle
    case analyzing(PreparedPhoto)
    case result(PreparedPhoto, PhotoQualityResponse)
    case failed(PreparedPhoto, AnalysisFailure)

    var photo: PreparedPhoto? {
        switch self {
        case .idle: return nil
        case .analyzing(let p), .result(let p, _), .failed(let p, _): return p
        }
    }

    var isAnalyzing: Bool {
        if case .analyzing = self { return true }
        return false
    }
}

@MainActor
@Observable
final class PhotoQualityViewModel {
    private(set) var state: AnalysisState = .idle
    /// 目前指定角度；nil = 不指定（payload 不送 required_view）
    private(set) var requiredView: RequiredView? = nil
    /// 取得照片或準備照片時的錯誤（例如相機不可用、檔案不是圖片）
    var userMessage: String? = nil

    private let api: PhotoQualityAPI
    private var analysisTask: Task<Void, Never>?
    /// 每次「選照片」或「送檢」都遞增；只有最新一代可以更新 UI。
    private var generation = 0

    init(api: PhotoQualityAPI = PhotoQualityAPI()) {
        self.api = api
    }

    var apiEndpoint: URL { api.checkEndpoint }
    var isBusy: Bool { state.isAnalyzing }
    var currentPhoto: PreparedPhoto? { state.photo }

    // MARK: - Intents

    /// 使用者選了一張照片（相機或相簿）。先顯示照片，再自動送檢。
    func didPick(image: UIImage) {
        cancelInFlight()
        generation += 1
        let myGeneration = generation

        analysisTask = Task { [weak self] in
            guard let self else { return }
            let prepared: PreparedPhoto
            do {
                // 重新編碼在背景做，避免大圖卡住主執行緒
                prepared = try await Task.detached(priority: .userInitiated) {
                    try ImagePreparation.prepare(image)
                }.value
            } catch {
                guard myGeneration == self.generation else { return }
                self.userMessage = "這張照片無法讀取，請換一張再試。"
                return
            }
            guard myGeneration == self.generation, !Task.isCancelled else { return }
            await self.runAnalysis(of: prepared, generation: myGeneration)
        }
    }

    /// 換指定角度：同一張照片自動重跑（跟 Web 版一致）
    func select(view: RequiredView?) {
        guard !isBusy else { return }
        guard view != requiredView else { return }
        requiredView = view
        if let photo = currentPhoto { analyze(photo) }
    }

    /// API 失敗後的「重新檢查」
    func retry() {
        guard !isBusy, let photo = currentPhoto else { return }
        analyze(photo)
    }

    func reset() {
        cancelInFlight()
        generation += 1
        state = .idle
        userMessage = nil
    }

    // MARK: - 內部

    private func analyze(_ photo: PreparedPhoto) {
        cancelInFlight()
        generation += 1
        let myGeneration = generation
        analysisTask = Task { [weak self] in
            await self?.runAnalysis(of: photo, generation: myGeneration)
        }
    }

    private func cancelInFlight() {
        analysisTask?.cancel()
        analysisTask = nil
    }

    private func runAnalysis(of photo: PreparedPhoto, generation myGeneration: Int) async {
        state = .analyzing(photo)
        let request = PhotoQualityRequest(requiredView: requiredView, imageBase64: photo.base64)
        do {
            let response = try await api.check(request)
            guard myGeneration == generation, !Task.isCancelled else { return }
            state = .result(photo, response)
        } catch is CancellationError {
            // 被更新的請求取代，或使用者按了清除：什麼都不做
        } catch let error as PhotoQualityAPIError {
            guard myGeneration == generation, !Task.isCancelled else { return }
            state = .failed(photo, AnalysisFailure(
                developerDescription: error.developerDescription,
                httpStatus: error.httpStatus,
                endpoint: api.checkEndpoint))
        } catch {
            guard myGeneration == generation, !Task.isCancelled else { return }
            state = .failed(photo, AnalysisFailure(
                developerDescription: String(describing: error),
                httpStatus: nil,
                endpoint: api.checkEndpoint))
        }
    }
}

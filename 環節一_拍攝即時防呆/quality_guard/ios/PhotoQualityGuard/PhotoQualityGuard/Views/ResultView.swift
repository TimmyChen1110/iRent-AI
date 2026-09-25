import SwiftUI

/// 分析成功後的整塊結果：大型 Result Card → 三關卡片 → 技術細節。
struct ResultView: View {
    let photo: PreparedPhoto
    let response: PhotoQualityResponse
    let requiredView: RequiredView?
    let endpoint: URL
    let onRetake: () -> Void
    let onChangeAngle: () -> Void

    var body: some View {
        VStack(spacing: AppTheme.Spacing.md) {
            resultCard
            ForEach(Array(response.stages.enumerated()), id: \.element.id) { index, stage in
                StageResultCard(index: index, stage: stage, response: response, photo: photo)
            }
            TechnicalDetailsView(response: response, endpoint: endpoint)
        }
    }

    // MARK: - Result Card

    private var resultCard: some View {
        let passed = response.passed
        let tint = passed ? AppTheme.Colors.success : AppTheme.Colors.error
        return VStack(spacing: AppTheme.Spacing.md) {
            ZStack {
                Circle().fill(tint.opacity(0.14))
                Image(systemName: passed ? "checkmark" : "exclamationmark")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundStyle(tint)
            }
            .frame(width: 56, height: 56)
            .accessibilityHidden(true)

            Text(passed ? "照片檢查通過" : "需要重新拍攝")
                .font(.title2.weight(.heavy))
                .foregroundStyle(AppTheme.Colors.text)
                .accessibilityIdentifier("result.title")

            Text(passed ? passMessage : failMessage)
                .font(.body)
                .foregroundStyle(AppTheme.Colors.textSecondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("result.message")

            QualityScoreBadge(score: response.qualityScore100)

            VStack(spacing: AppTheme.Spacing.sm) {
                AppButton(title: passed ? "再拍一張" : "重新拍攝", systemImage: "camera.fill", kind: .primary, action: onRetake)
                    .accessibilityIdentifier("result.retake")
                if requiredView != nil {
                    AppButton(title: "更換拍攝角度", kind: .secondary, action: onChangeAngle)
                        .accessibilityIdentifier("result.changeAngle")
                }
            }
            .padding(.top, AppTheme.Spacing.xs)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, AppTheme.Spacing.xl)
        .padding(.horizontal, AppTheme.Spacing.lg)
        .background(AppTheme.Colors.surface, in: RoundedRectangle(cornerRadius: AppTheme.Radius.md, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: AppTheme.Radius.md, style: .continuous).stroke(AppTheme.Colors.border, lineWidth: 1))
        .overlay(alignment: .top) {
            // 頂邊語意色條
            Rectangle().fill(tint).frame(height: 4)
                .clipShape(UnevenRoundedRectangle(topLeadingRadius: AppTheme.Radius.md, topTrailingRadius: AppTheme.Radius.md))
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(passed ? "result.pass" : "result.fail")
    }

    /// PASS 副標：依情境。車內視角只跑第 1 關，不能說「三關全過」。
    private var passMessage: String {
        if !response.skippedStages.isEmpty {
            return "車內照片可讀性通過（車內視角不檢查車牌與拍攝角度）"
        }
        if response.requiredView != nil { return "照片清晰，拍攝角度符合要求" }
        if let detected = response.detectedView {
            return "照片清晰，判定角度為「\(RequiredView.displayName(forAPIValue: detected))」"
        }
        return "照片清晰，可以使用"
    }

    /// FAIL 副標：第一個失敗關卡的第一句（backend 文案本身就是可執行的動作）。
    private var failMessage: String {
        response.firstFailedStage?.errors.first?.message
            ?? response.errors.first?.message
            ?? "請重新拍攝"
    }
}

/// API 不可達／失敗時的卡片
struct AnalysisFailureView: View {
    let failure: AnalysisFailure
    let onRetry: () -> Void
    let onRetake: () -> Void

    var body: some View {
        VStack(spacing: AppTheme.Spacing.md) {
            VStack(spacing: AppTheme.Spacing.md) {
                ZStack {
                    Circle().fill(AppTheme.Colors.warning.opacity(0.14))
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 26, weight: .bold))
                        .foregroundStyle(AppTheme.Colors.warning)
                }
                .frame(width: 56, height: 56)
                .accessibilityHidden(true)

                Text("目前無法完成照片檢查")
                    .font(.title2.weight(.heavy))
                    .foregroundStyle(AppTheme.Colors.text)
                    .accessibilityIdentifier("result.title")
                Text("請確認網路連線後再試一次")
                    .font(.body)
                    .foregroundStyle(AppTheme.Colors.textSecondary)

                VStack(spacing: AppTheme.Spacing.sm) {
                    AppButton(title: "重新檢查", kind: .primary, action: onRetry)
                        .accessibilityIdentifier("result.retry")
                    AppButton(title: "重新拍攝", systemImage: "camera.fill", kind: .secondary, action: onRetake)
                        .accessibilityIdentifier("result.retake")
                }
                .padding(.top, AppTheme.Spacing.xs)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, AppTheme.Spacing.xl)
            .padding(.horizontal, AppTheme.Spacing.lg)
            .background(AppTheme.Colors.surface, in: RoundedRectangle(cornerRadius: AppTheme.Radius.md, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: AppTheme.Radius.md, style: .continuous).stroke(AppTheme.Colors.border, lineWidth: 1))
            .overlay(alignment: .top) {
                Rectangle().fill(AppTheme.Colors.warning).frame(height: 4)
                    .clipShape(UnevenRoundedRectangle(topLeadingRadius: AppTheme.Radius.md, topTrailingRadius: AppTheme.Radius.md))
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("result.error")

            DisclosureGroup("開發者資訊") {
                VStack(alignment: .leading, spacing: AppTheme.Spacing.xs) {
                    detailRow("API", failure.endpoint.absoluteString)
                    if let status = failure.httpStatus { detailRow("HTTP status", "\(status)") }
                    detailRow("錯誤", failure.developerDescription)
                    Text("請確認 FastAPI 有啟動：uvicorn app.main:app --host 0.0.0.0 --port 8000。實體 iPhone 請把 AppConfig 的網址改成 Mac 的區網 IP。")
                        .font(.caption)
                        .foregroundStyle(AppTheme.Colors.textTertiary)
                        .padding(.top, AppTheme.Spacing.xs)
                }
                .padding(.top, AppTheme.Spacing.sm)
            }
            .font(.footnote.weight(.semibold))
            .foregroundStyle(AppTheme.Colors.textSecondary)
            .card()
            .accessibilityIdentifier("developer.details")
        }
    }

    private func detailRow(_ key: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(key).font(.caption).foregroundStyle(AppTheme.Colors.textTertiary)
            Text(value).font(.caption.monospaced()).foregroundStyle(AppTheme.Colors.text)
                .textSelection(.enabled)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// 技術細節（預設收合）。主流程不會出現這些字。
struct TechnicalDetailsView: View {
    let response: PhotoQualityResponse
    let endpoint: URL

    var body: some View {
        DisclosureGroup("技術細節") {
            VStack(spacing: 0) {
                ForEach(rows, id: \.0) { key, value in
                    HStack(alignment: .top, spacing: AppTheme.Spacing.sm) {
                        Text(key)
                            .font(.footnote)
                            .foregroundStyle(AppTheme.Colors.textSecondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        Text(value)
                            .font(.footnote.monospaced())
                            .foregroundStyle(AppTheme.Colors.text)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .textSelection(.enabled)
                    }
                    .padding(.vertical, AppTheme.Spacing.sm)
                    Divider()
                }
            }
            .padding(.top, AppTheme.Spacing.sm)
        }
        .font(.footnote.weight(.semibold))
        .foregroundStyle(AppTheme.Colors.textSecondary)
        .card()
        .accessibilityIdentifier("technical.details")
    }

    private var rows: [(String, String)] {
        let d = response.debug
        var rows: [(String, String?)] = [
            ("實際跑到的內部階段", d.stagesRun.joined(separator: " → ")),
        ]
        for s in response.stages { rows.append(("\(s.displayName) 原始結論", s.summary)) }
        rows += [
            ("模糊分數（越高越銳利）", d.blurScore.map { String(format: "%.1f", $0) }),
            ("平均亮度 0-1", d.brightness.map { String(format: "%.3f", $0.mean) }),
            ("車牌偵測信心", d.plateDetectConfidence.map { String(format: "%.1f%%", $0 * 100) }),
            ("車牌 OCR 信心", response.plateConfidence.map { String(format: "%.1f%%", $0 * 100) }),
            ("車牌面積佔畫面比例", d.plateAreaRatio.map { String(format: "%.5f", $0) }),
            ("車牌 bbox", d.plateBbox.map { "[\($0.map(String.init).joined(separator: ", "))]" }),
            ("方向防護網旋轉角度", d.orientationRotation != 0 ? "逆時針 \(d.orientationRotation)°" : nil),
            ("模型原始角度標籤", d.viewModelLabel),
            ("判定角度（API 值）", response.detectedView),
            ("角度 top-1 機率", response.viewConfidence.map { String(format: "%.1f%%", $0 * 100) }),
            ("角度機率分布", d.viewProbabilities.map { $0.map { "\($0.label) \(String(format: "%.1f%%", $0.probability * 100))" }.joined(separator: "、") }),
            ("車外/車內猜測（僅供參考）", d.exteriorInteriorGuess),
            ("品質分數（0-1）", String(format: "%.3f", response.qualityScore)),
            ("後端處理耗時", String(format: "%.1f ms", d.elapsedMs)),
            ("API", endpoint.absoluteString),
        ]
        return rows.compactMap { key, value in
            guard let value, !value.isEmpty else { return nil }
            return (key, value)
        }
    }
}

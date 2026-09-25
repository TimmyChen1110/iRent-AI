import SwiftUI

/// 三關 Status Card：左 icon、中 名稱＋一句話、右 狀態；下方依關卡放錯誤、車牌、標框圖、角度。
struct StageResultCard: View {
    let index: Int
    let stage: StageResult
    let response: PhotoQualityResponse
    let photo: PreparedPhoto

    var body: some View {
        VStack(alignment: .leading, spacing: AppTheme.Spacing.md) {
            HStack(alignment: .top, spacing: AppTheme.Spacing.md) {
                StatusIcon(status: stage.status)
                VStack(alignment: .leading, spacing: AppTheme.Spacing.xs) {
                    HStack(spacing: AppTheme.Spacing.sm) {
                        Text("\(index + 1)")
                            .font(.caption.weight(.bold))
                            .foregroundStyle(AppTheme.Colors.textTertiary)
                            .accessibilityHidden(true)
                        Text(stage.displayName)
                            .font(.headline)
                            .foregroundStyle(AppTheme.Colors.text)
                    }
                    Text(summaryLine)
                        .font(.footnote)
                        .foregroundStyle(AppTheme.Colors.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: AppTheme.Spacing.sm)
                StatusTag(status: stage.status)
            }

            if stage.status != .skipped {
                extras
            }
        }
        .card()
        .overlay(alignment: .leading) {
            RoundedRectangle(cornerRadius: AppTheme.Radius.md, style: .continuous)
                .fill(StatusIcon(status: stage.status).tint)
                .frame(width: 4)
                .padding(.vertical, AppTheme.Spacing.sm)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("stage.\(stage.id)")
    }

    // MARK: - 一句話

    private var summaryLine: String {
        let advisories = response.debug.stage1Advisories
        switch stage.status {
        case .skipped:
            return stage.summary ?? "前一關沒過，尚未執行"
        default: break
        }
        switch stage.id {
        case "readability":
            if stage.status == .failed { return "照片無法判讀" }
            return advisories.isEmpty ? "清晰度與亮度正常" : "可以判讀，但光線或清晰度略差"
        case "plate":
            if response.plateText != nil {
                return stage.status == .passed ? "已辨識到車牌" : "有讀到車牌，但不完整或不夠清楚"
            }
            if response.debug.plateBbox != nil { return "有找到車牌位置，但讀不出號碼" }
            return "畫面中沒有找到車牌"
        case "view":
            if let detected = response.detectedView {
                return stage.status == .passed ? "拍攝角度符合" : "判定為「\(RequiredView.displayName(forAPIValue: detected))」"
            }
            return "無法判斷拍攝角度"
        default:
            return stage.summary ?? ""
        }
    }

    // MARK: - 各關附加內容

    @ViewBuilder
    private var extras: some View {
        VStack(alignment: .leading, spacing: AppTheme.Spacing.md) {
            if !stage.errors.isEmpty {
                errorList
            }
            switch stage.id {
            case "readability":
                if !response.debug.stage1Advisories.isEmpty {
                    HStack(spacing: AppTheme.Spacing.xs) {
                        ForEach(response.debug.stage1Advisories, id: \.self) { raw in
                            WarningPill(text: PhotoQualityResponse.advisoryLabel(raw))
                        }
                    }
                }
            case "plate":
                if let plate = response.plateText {
                    plateHero(plate)
                }
                if let bbox = response.debug.plateBbox {
                    PlateOverlayImage(image: photo.image, pixelSize: photo.pixelSize,
                                      bbox: bbox, rotation: response.debug.orientationRotation)
                        .frame(maxHeight: 360)
                }
            case "view":
                viewHero
            default:
                EmptyView()
            }
        }
        .padding(.leading, 32 + AppTheme.Spacing.md) // 對齊 icon 右側
    }

    private var errorList: some View {
        VStack(alignment: .leading, spacing: AppTheme.Spacing.sm) {
            ForEach(stage.errors, id: \.self) { error in
                VStack(alignment: .leading, spacing: AppTheme.Spacing.xs) {
                    Text(error.message)
                        .font(.body.weight(.bold))
                        .foregroundStyle(AppTheme.Colors.error)
                    if let hint = PhotoQualityResponse.hint(for: error.code) {
                        Text(hint)
                            .font(.footnote)
                            .foregroundStyle(AppTheme.Colors.textSecondary)
                    }
                }
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(AppTheme.Spacing.md)
                .background(AppTheme.Colors.errorSoft, in: RoundedRectangle(cornerRadius: AppTheme.Radius.sm, style: .continuous))
            }
        }
    }

    private func plateHero(_ plate: String) -> some View {
        VStack(alignment: .leading, spacing: AppTheme.Spacing.xs) {
            Text("辨識到車牌")
                .font(.caption.weight(.bold))
                .foregroundStyle(AppTheme.Colors.textTertiary)
            Text(plate)
                .font(.system(size: 28, weight: .bold, design: .monospaced))
                .tracking(2)
                .foregroundStyle(AppTheme.Colors.text)
                .padding(.horizontal, AppTheme.Spacing.md)
                .padding(.vertical, AppTheme.Spacing.xs)
                .overlay(RoundedRectangle(cornerRadius: AppTheme.Radius.xs).stroke(AppTheme.Colors.text, lineWidth: 2))
                .accessibilityIdentifier("plate.number")
            if let conf = response.plateConfidence {
                Text("辨識信心 \(Int((conf * 100).rounded()))%")
                    .font(.footnote)
                    .foregroundStyle(AppTheme.Colors.textSecondary)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("辨識到車牌 \(plate)")
    }

    @ViewBuilder
    private var viewHero: some View {
        if let detected = response.detectedView {
            VStack(alignment: .leading, spacing: AppTheme.Spacing.xs) {
                Text("判定角度")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(AppTheme.Colors.textTertiary)
                HStack(alignment: .firstTextBaseline, spacing: AppTheme.Spacing.sm) {
                    Text(RequiredView.displayName(forAPIValue: detected))
                        .font(.system(size: 28, weight: .heavy))
                        .foregroundStyle(AppTheme.Colors.text)
                        .accessibilityIdentifier("view.detected")
                    if let conf = response.viewConfidence {
                        Text("\(Int((conf * 100).rounded()))%")
                            .font(.body.weight(.semibold))
                            .foregroundStyle(AppTheme.Colors.textSecondary)
                    }
                }
            }
        }
        if let probabilities = response.debug.viewProbabilities, !probabilities.isEmpty {
            ProbabilityBars(probabilities: probabilities)
        }
    }
}

/// 四角機率條：top-1 用 Primary，其餘中性。
struct ProbabilityBars: View {
    let probabilities: [ViewProbability]

    private var topLabel: String? { probabilities.max(by: { $0.probability < $1.probability })?.label }

    var body: some View {
        VStack(spacing: AppTheme.Spacing.xs) {
            ForEach(probabilities) { p in
                let isTop = p.label == topLabel
                HStack(spacing: AppTheme.Spacing.sm) {
                    Text(RequiredView.displayName(forAPIValue: p.label))
                        .font(.footnote.weight(isTop ? .bold : .regular))
                        .foregroundStyle(isTop ? AppTheme.Colors.text : AppTheme.Colors.textTertiary)
                        .frame(width: 56, alignment: .leading)
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            Capsule().fill(AppTheme.Colors.surface2)
                            Capsule()
                                .fill(isTop ? AppTheme.Colors.primary : AppTheme.Colors.border2)
                                .frame(width: max(0, geo.size.width * CGFloat(p.probability)))
                        }
                    }
                    .frame(height: 8)
                    Text("\(Int((p.probability * 100).rounded()))%")
                        .font(.caption.monospacedDigit().weight(isTop ? .bold : .regular))
                        .foregroundStyle(isTop ? AppTheme.Colors.text : AppTheme.Colors.textTertiary)
                        .frame(width: 40, alignment: .trailing)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("\(RequiredView.displayName(forAPIValue: p.label)) \(Int((p.probability * 100).rounded()))%")
            }
        }
        .accessibilityIdentifier("view.probabilities")
    }
}

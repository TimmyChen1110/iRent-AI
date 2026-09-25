import SwiftUI

/// 畫面的視覺核心：深色相機／照片區。
/// 空狀態顯示 camera icon 與四角取景框；有照片時 aspectFit 顯示；分析中蓋上 loading overlay。
struct PhotoPreviewView: View {
    let photo: UIImage?
    let requiredView: RequiredView?
    let isAnalyzing: Bool

    var body: some View {
        ZStack {
            AppTheme.Colors.cameraBackground

            if let photo {
                Image(uiImage: photo)
                    .resizable()
                    .scaledToFit()
                    .accessibilityLabel("你選擇的車況照片")
            } else {
                emptyState
            }

            cornerGuides
                .padding(AppTheme.Spacing.xl)
                .opacity(photo == nil ? 1 : 0.6)
                .allowsHitTesting(false)

            VStack {
                HStack {
                    anglePill
                    Spacer()
                }
                Spacer()
            }
            .padding(AppTheme.Spacing.md)

            if isAnalyzing {
                AnalysisLoadingView()
            }
        }
        .aspectRatio(3 / 4, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.lg, style: .continuous))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("photo.preview")
    }

    private var emptyState: some View {
        VStack(spacing: AppTheme.Spacing.md) {
            ZStack {
                Circle().fill(.white.opacity(0.1))
                Image(systemName: "camera.fill")
                    .font(.system(size: 30, weight: .regular))
                    .foregroundStyle(.white)
            }
            .frame(width: 64, height: 64)
            Text("拍攝車況照片")
                .font(.headline)
                .foregroundStyle(.white)
            Text("請讓車牌與整台車完整入鏡")
                .font(.footnote)
                .foregroundStyle(.white.opacity(0.72))
        }
        .accessibilityElement(children: .combine)
    }

    private var anglePill: some View {
        Text(requiredView.map { "目前拍攝：\($0.displayName)" } ?? "未指定拍攝角度")
            .font(.footnote.weight(.semibold))
            .foregroundStyle(.white)
            .padding(.horizontal, AppTheme.Spacing.md)
            .padding(.vertical, AppTheme.Spacing.xs)
            .background(requiredView == nil ? Color.black.opacity(0.45) : AppTheme.Colors.primary, in: Capsule())
            .accessibilityIdentifier("photo.anglePill")
    }

    private var cornerGuides: some View {
        GeometryReader { geo in
            let len: CGFloat = 28
            let w = geo.size.width, h = geo.size.height
            Path { p in
                // 左上
                p.move(to: CGPoint(x: 0, y: len)); p.addLine(to: .zero); p.addLine(to: CGPoint(x: len, y: 0))
                // 右上
                p.move(to: CGPoint(x: w - len, y: 0)); p.addLine(to: CGPoint(x: w, y: 0)); p.addLine(to: CGPoint(x: w, y: len))
                // 左下
                p.move(to: CGPoint(x: 0, y: h - len)); p.addLine(to: CGPoint(x: 0, y: h)); p.addLine(to: CGPoint(x: len, y: h))
                // 右下
                p.move(to: CGPoint(x: w - len, y: h)); p.addLine(to: CGPoint(x: w, y: h)); p.addLine(to: CGPoint(x: w, y: h - len))
            }
            .stroke(.white.opacity(0.42), style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
        }
        .accessibilityHidden(true)
    }
}

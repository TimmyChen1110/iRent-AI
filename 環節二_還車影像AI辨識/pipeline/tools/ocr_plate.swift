import Foundation
import Vision
import AppKit
// 輸出 文字\t正規化框(x,y,w,h)  —— Vision 座標原點在左下
for path in CommandLine.arguments.dropFirst() {
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate; req.usesLanguageCorrection = false
    try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
    for obs in (req.results ?? []) {
        if let c = obs.topCandidates(1).first {
            let b = obs.boundingBox
            print("\(path)\t\(c.string)\t\(b.origin.x)\t\(b.origin.y)\t\(b.size.width)\t\(b.size.height)")
        }
    }
}

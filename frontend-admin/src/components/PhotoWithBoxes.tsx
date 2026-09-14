import type { Box } from '../lib/types'

/** 照片 + AI 標註框。box_2d 為 [y0, x0, y1, x1]，0–1000 正規化座標（與監理台同一格式）。 */
export function PhotoWithBoxes({ src, label, boxes = [], hot }: { src: string | null | undefined; label: string; boxes?: Box[]; hot?: number | null }) {
  if (!src) return <div className="photo" style={{ minHeight: 140, display: 'grid', placeItems: 'center' }}><span className="faint small">無照片</span></div>
  return (
    <div className="photo">
      <img src={src} alt={label} loading="lazy" />
      <span className="lbl">{label}</span>
      {boxes.map((b, i) => {
        const [y0, x0, y1, x1] = b.box_2d
        return <div key={i} className="box" style={{
          left: `${x0 / 10}%`, top: `${y0 / 10}%`, width: `${(x1 - x0) / 10}%`, height: `${(y1 - y0) / 10}%`,
          opacity: hot == null || hot === i ? 1 : .35, transition: 'opacity .15s',
        }}><i>{i + 1}</i></div>
      })}
    </div>
  )
}

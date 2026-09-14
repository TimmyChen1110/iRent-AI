import { useState } from 'react'

/** 單一序列長條圖（SVG）。依 dataviz 規範：<=24px 粗、資料端 4px 圓角、基線方角、
 *  hairline 格線、hover 提示、單色系（品牌藍），強調值用深藍；文字一律用文字色。 */
export interface BarDatum { label: string; value: number; hint?: string; emphasis?: boolean }

export function Columns({ data, height = 180, valueFmt = (v: number) => v.toLocaleString(), yTicks = 4 }:
  { data: BarDatum[]; height?: number; valueFmt?: (v: number) => string; yTicks?: number }) {
  const [hot, setHot] = useState<number | null>(null)
  const W = 720, padL = 44, padR = 8, padT = 12, padB = 26
  const innerW = W - padL - padR, innerH = height - padT - padB
  const max = Math.max(1, ...data.map(d => d.value))
  const step = niceStep(max, yTicks)
  const top = Math.ceil(max / step) * step
  const slot = innerW / data.length
  const bw = Math.min(24, slot * 0.7)
  const y = (v: number) => padT + innerH - (v / top) * innerH
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step)
  return (
    <div style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${W} ${height}`} width="100%" role="img" style={{ display: 'block', overflow: 'visible' }} onMouseLeave={() => setHot(null)}>
        {ticks.map(t => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth={1} />
            <text x={padL - 6} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--ink-3)" fontFamily="var(--mono)">{t.toLocaleString()}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = padL + slot * i + (slot - bw) / 2
          const h = Math.max(0, y(0) - y(d.value))
          const r = Math.min(4, h)
          const fill = d.emphasis ? 'var(--brand-deep)' : 'var(--brand)'
          return (
            <g key={i} onMouseEnter={() => setHot(i)}>
              <rect x={padL + slot * i} y={padT} width={slot} height={innerH} fill="transparent" />
              {h > 0 && <path d={`M${x},${y(0)} v${-(h - r)} a${r},${r} 0 0 1 ${r},${-r} h${bw - 2 * r} a${r},${r} 0 0 1 ${r},${r} v${h - r} z`} fill={fill} opacity={hot == null || hot === i ? 1 : .45} />}
              {(data.length <= 12 || i % Math.ceil(data.length / 12) === 0) && (
                <text x={padL + slot * i + slot / 2} y={height - 8} textAnchor="middle" fontSize={11} fill="var(--ink-2)" fontFamily="var(--mono)">{d.label}</text>
              )}
            </g>
          )
        })}
        {hot != null && (
          <g>
            <rect x={padL + slot * hot} y={padT} width={slot} height={innerH} fill="var(--brand)" opacity={.06} />
            <text x={padL + slot * hot + slot / 2} y={y(data[hot].value) - 6} textAnchor="middle" fontSize={12} fontWeight={700} fill="var(--ink)" fontFamily="var(--mono)">{valueFmt(data[hot].value)}</text>
          </g>
        )}
      </svg>
      {hot != null && data[hot].hint && <div className="small muted" style={{ marginTop: 4 }}>{data[hot].label}：{data[hot].hint}</div>}
    </div>
  )
}

/** 水平長條（排行用）。每列：標籤、長條、值在條尾。 */
export function HBars({ data, colorOf, valueFmt = (v: number) => v.toLocaleString() }:
  { data: Array<{ label: string; value: number; parts?: Array<{ key: string; value: number }>; hint?: string }>; colorOf?: (key: string) => string; valueFmt?: (v: number) => string }) {
  const max = Math.max(1, ...data.map(d => d.value))
  return (
    <div style={{ display: 'grid', gap: 6 }}>
      {data.map((d, i) => (
        <div key={i} className="row" style={{ gap: 10 }} title={d.hint}>
          <span className="plate small" style={{ width: 90, flex: 'none' }}>{d.label}</span>
          <div style={{ flex: 1, height: 16, display: 'flex', gap: 2 }}>
            {(d.parts || [{ key: 'v', value: d.value }]).filter(p => p.value > 0).map((p, j, arr) => (
              <div key={p.key} style={{ width: `${(p.value / max) * 100}%`, background: colorOf ? colorOf(p.key) : 'var(--brand)', borderRadius: j === arr.length - 1 ? '0 4px 4px 0' : 0, minWidth: 2 }} />
            ))}
          </div>
          <span className="mono small" style={{ width: 36, textAlign: 'right', color: 'var(--ink-2)' }}>{valueFmt(d.value)}</span>
        </div>
      ))}
    </div>
  )
}

function niceStep(max: number, ticks: number) {
  const raw = max / ticks
  const pow = Math.pow(10, Math.floor(Math.log10(raw)))
  const m = raw / pow
  const nice = m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10
  return nice * pow
}

import { useEffect, useRef, useState } from "react"
import { BrainCircuit, Flame, Layers } from "lucide-react"

import { endpoint } from "@/lib/api"
import { useLocale } from "./i18n"

interface ExpertMap { rows: number; cols: number; map: string; hits: string; seq: number }
interface AtlasEntry { affinity: Record<string, number>; entropy: number; top: string; label: string }

const TIER_KEYS = ["tier.disk", "tier.ram", "tier.vram"] as const
const TIER_RGB: [number, number, number][] = [[58, 71, 80], [90, 155, 216], [78, 214, 165]]

// (#P2) base-colour LUT: tier(0..3) x heat(0..63) -> rgb, so the frame loop
// does typed-array writes instead of 19k `rgb()` string allocs + fillStyle/fillRect
const BASE_LUT: Uint8Array = (() => {
  const lut = new Uint8Array(4 * 64 * 3)
  for (let t = 0; t < 4; t++) {
    const [R, G, B] = TIER_RGB[t] ?? TIER_RGB[0]
    for (let h = 0; h < 64; h++) {
      const lum = 0.35 + 0.65 * Math.min(h / 24, 1)
      const o = (t * 64 + h) * 3
      lut[o] = R * lum
      lut[o + 1] = G * lum
      lut[o + 2] = B * lum
    }
  }
  return lut
})()

function depthRoleKey(row: number, rows: number, isMtp: boolean): string {
  if (isMtp) return "brain.mtp"
  const f = row / Math.max(rows - 1, 1)
  if (f < 0.2) return "brain.early"
  if (f < 0.45) return "brain.lowerMiddle"
  if (f < 0.7) return "brain.upperMiddle"
  if (f < 0.9) return "brain.late"
  return "brain.final"
}

export function Brain({ baseUrl, apiKey, connected }: { baseUrl: string; apiKey: string; connected: boolean }) {
  const { t } = useLocale()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [wrapSize, setWrapSize] = useState({ w: 1200, h: 700 })
  const [data, setData] = useState<ExpertMap | null>(null)
  const [probeErr, setProbeErr] = useState(false)   // (#U3) surface /experts failures instead of an endless spinner
  const [atlas, setAtlas] = useState<Record<string, AtlasEntry> | null>(null)
  const [tip, setTip] = useState<{ x: number; y: number; row: number; col: number; tier: number; heat: number } | null>(null)
  const [totals, setTotals] = useState<[number, number, number]>([0, 0, 0])
  const pulseRef = useRef<Float32Array | null>(null)   // per-expert pulse intensity 0..1
  const mapRef = useRef<Uint8Array | null>(null)       // (#P1) decoded tier/heat bytes, once per seq
  const lastSeq = useRef(0)
  const rafRef = useRef(0)

  // (#P1) decode a hex-byte string once into a Uint8Array (no per-frame substr/parseInt)
  function decodeHexBytes(hex: string, n: number): Uint8Array {
    const out = new Uint8Array(n)
    for (let i = 0; i < n; i++) {
      out[i] = parseInt(hex.substr(i * 2, 2), 16) || 0
    }
    return out
  }

  // load the expert atlas if published (measured topic affinity, #175)
  useEffect(() => {
    // The atlas lives next to the engine's /experts endpoint, not on the page
    // origin: when the UI is hosted elsewhere (dev server, static hosting) a
    // root-relative fetch pointed at the wrong server and the atlas never
    // loaded. Same base + auth as the live expert map above.
    const base = baseUrl.replace(/\/v1\/?$/, "")
    fetch(endpoint(base, "/experts.json"), { headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {} })
      .then(r => r.ok ? r.json() : null).then(d => {
        if (d?.experts) setAtlas(d.experts)
      }).catch(() => {})
  }, [baseUrl, apiKey])

  // track container size for responsive cell sizing
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      setWrapSize({ w: el.clientWidth - 24, h: el.clientHeight - 24 })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // poll /experts
  useEffect(() => {
    if (!connected) return
    let disposed = false
    const base = baseUrl.replace(/\/v1\/?$/, "")
    const poll = async () => {
      try {
        // (#P8) ?since= : 304 si seq inchangé -> on saute tout (ni JSON, ni decode, ni render)
        const url = endpoint(base, "/experts") + (lastSeq.current > 0 ? `?since=${lastSeq.current}` : "")
        const res = await fetch(url, { headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {} })
        if (res.status === 304) { setProbeErr(false); return }
        if (!res.ok) throw new Error(`/experts ${res.status}`)
        const next = (await res.json()) as ExpertMap
        if (disposed || !next.rows) return
        // (#P1) same seq + already decoded => nothing changed, skip re-render/redraw
        if (lastSeq.current !== 0 && next.seq === lastSeq.current) { setProbeErr(false); return }
        lastSeq.current = next.seq
        const n = next.rows * next.cols
        const decoded = decodeHexBytes(next.map || "", n)
        mapRef.current = decoded
        const t: [number, number, number] = [0, 0, 0]
        for (let i = 0; i < n; i++) t[decoded[i] >> 6]++
        setTotals(t)
        setData(next)
        setProbeErr(false)
        if (next.hits) {
          if (!pulseRef.current || pulseRef.current.length !== n) pulseRef.current = new Float32Array(n)
          const p = pulseRef.current
          const hb = decodeHexBytes(next.hits, (n >> 3) + 1)
          for (let i = 0; i < n; i++) {
            if (hb[i >> 3] & (1 << (i & 7))) p[i] = 1
          }
        }
      } catch { if (!disposed) setProbeErr(true) /* surface repeated failures; keep the last frame */ }
    }
    void poll()
    const t = window.setInterval(() => void poll(), 1500)
    return () => { disposed = true; window.clearInterval(t) }
  }, [baseUrl, apiKey, connected])

  // render loop: base layer via putImageData + white pulse overlay while alive
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !data) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    const { rows, cols } = data
    const m = mapRef.current   // (#P1) pre-decoded bytes
    if (!m) return
    const cell = Math.max(2, Math.floor(Math.min(wrapSize.w / cols, wrapSize.h / rows)))
    const gap = cell >= 4 ? 1 : 0
    canvas.width = cols * (cell + gap)
    canvas.height = rows * (cell + gap)
    const W = canvas.width

    // (#P2) bake the static grid once into an ImageData (typed-array block fills)
    const img = ctx.createImageData(canvas.width, canvas.height)
    const px = img.data
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const byte = m[r * cols + c]
        const o = ((byte >> 6) * 64 + (byte & 63)) * 3
        const R = BASE_LUT[o], G = BASE_LUT[o + 1], B = BASE_LUT[o + 2]
        const x0 = c * (cell + gap), y0 = r * (cell + gap)
        for (let y = 0; y < cell; y++) {
          let p = ((y0 + y) * W + x0) * 4
          for (let x = 0; x < cell; x++) {
            px[p] = R; px[p + 1] = G; px[p + 2] = B; px[p + 3] = 255
            p += 4
          }
        }
      }
    }

    const draw = () => {
      ctx.putImageData(img, 0, 0)
      const p = pulseRef.current
      let alive = false
      if (p) {
        // (#P2) only routed experts get a (cheap) overlay rect; the rest is the blit
        ctx.fillStyle = "#ffffff"
        for (let i = 0; i < p.length; i++) {
          const v = p[i]
          if (v > 0.01) {
            const r = (i / cols) | 0, c = i % cols
            ctx.globalAlpha = Math.min(v, 1) * 0.85
            ctx.fillRect(c * (cell + gap), r * (cell + gap), cell, cell)
            p[i] = v * 0.94
            alive = true
          } else {
            p[i] = 0
          }
        }
        ctx.globalAlpha = 1
      }
      if (alive) rafRef.current = requestAnimationFrame(draw)
    }
    draw()
    const keepalive = window.setInterval(() => { if (!rafRef.current) draw(); rafRef.current = 0 }, 400)
    return () => { cancelAnimationFrame(rafRef.current); window.clearInterval(keepalive); if (tipRaf.current) cancelAnimationFrame(tipRaf.current) }
  }, [data, wrapSize])

  const tipRaf = useRef(0)
  const onMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!data) return
    // (#P3b) rAF-throttle: 1 setState max par frame au lieu d'1 par pixel
    if (tipRaf.current) return
    const rect = e.currentTarget.getBoundingClientRect()
    const clientX = e.clientX, clientY = e.clientY
    const target = e.currentTarget
    tipRaf.current = requestAnimationFrame(() => {
      tipRaf.current = 0
      const scaleX = target.width / rect.width
      const scaleY = target.height / rect.height
      const cell = Math.max(2, Math.floor(Math.min(wrapSize.w / data.cols, wrapSize.h / data.rows)))
      const gap = cell >= 4 ? 1 : 0
      const col = Math.floor(((clientX - rect.left) * scaleX) / (cell + gap))
      const row = Math.floor(((clientY - rect.top) * scaleY) / (cell + gap))
      if (row < 0 || row >= data.rows || col < 0 || col >= data.cols) { setTip(null); return }
      const m = mapRef.current
      if (!m) return
      const byte = m[row * data.cols + col]
      setTip((prev) => {
        if (prev && prev.row === row && prev.col === col) return prev   // même case: pas de re-render
        return { x: clientX, y: clientY, row, col, tier: byte >> 6, heat: byte & 63 }
      })
    })
  }

  // (#P1) totals computed once at decode time, no per-render scan

  return (
    <div className="brain-page">
      <div className="brain-head">
        <div className="section-title"><BrainCircuit className="size-4" /> {t("brain.title")} — {data ? t("brain.layers", { rows: data.rows, cols: data.cols }) : t("brain.waiting")}</div>
        <div className="brain-legend">
          <span><i style={{ background: "#4ed6a5" }} /> {t("tier.vram")} {totals[2].toLocaleString()}</span>
          <span><i style={{ background: "#5a9bd8" }} /> {t("tier.ram")} {totals[1].toLocaleString()}</span>
          <span><i style={{ background: "#3a4750" }} /> {t("tier.disk")} {totals[0].toLocaleString()}</span>
          <span><Flame className="size-3" /> {t("brain.brightnessHint")}</span>
          <span className="brain-pulse-hint">{t("brain.flashHint")}</span>
        </div>
      </div>
      <div className="brain-canvas-wrap" ref={wrapRef}>
        <canvas ref={canvasRef} onMouseMove={onMove} onMouseLeave={() => setTip(null)} />
        {!connected && <p className="runtime-unavailable">{t("brain.connectHint")}</p>}
      </div>
      {tip && data && (() => {
        const isMtp = tip.row === data.rows - 1
        const realLayer = isMtp ? 78 : tip.row + 3
        const entry = atlas?.[`${realLayer}:${tip.col}`]
        return (
        <div className="brain-tip" style={{ left: Math.min(tip.x + 14, window.innerWidth - 260), top: Math.min(tip.y + 14, window.innerHeight - 170) }}>
          <div className="brain-tip-title"><Layers className="size-3" /> Layer {realLayer}{isMtp ? " (MTP)" : ""} · Expert {tip.col}</div>
          <div>Tier: <strong style={{ color: ["#8b9aa3", "#5a9bd8", "#4ed6a5"][tip.tier] }}>{t(TIER_KEYS[tip.tier])}</strong></div>
          <div>Heat: <strong>{tip.heat === 0 ? t("brain.neverRouted") : t("brain.selections", { heat: tip.heat })}</strong></div>
          {entry ? <>
            <div className={entry.label.startsWith("specialist") ? "brain-tip-spec" : undefined}>
              {entry.label.startsWith("specialist") ? t("brain.specialist", { top: entry.top }) : t("brain.generalist")}
              <small> (entropy {entry.entropy})</small>
            </div>
            <div className="brain-tip-aff">{Object.entries(entry.affinity).sort((a, b) => b[1] - a[1]).slice(0, 3)
              .map(([c, p]) => `${c} ${Math.round(p * 100)}%`).join(" · ")}</div>
          </> : <div className="brain-tip-role">{t(depthRoleKey(tip.row, data.rows, isMtp))}</div>}
        </div>
        )
      })()}
    </div>
  )
}

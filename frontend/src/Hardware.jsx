import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { animate, stagger } from 'animejs'
import Esp32Board3D from './Esp32Board3D'
import Logo from './Logo'
import './Hardware.css'

const PARTS = [
  {
    id: 'module',
    label: 'esp32-wroom',
    title: 'ESP32-WROOM-32',
    body: 'Shielded SoC — dual-core Xtensa, Wi-Fi, BLE, deep sleep. Samples soil, buffers offline, syncs when the farm network returns.',
    meta: 'MCU · 2.4 GHz RF',
  },
  {
    id: 'antenna',
    label: 'antenna',
    title: 'PCB antenna',
    body: 'On-module trace antenna past the metal can. How the node reaches Wi-Fi after waking from deep sleep.',
    meta: 'RF · 2.4 GHz',
  },
  {
    id: 'gpio-l',
    label: 'gpio left',
    title: 'Left pin header',
    body: '3V3, GND, ADC. Capacitive moisture and EC probes land here on the field harness.',
    meta: 'ADC · 3V3 · GND',
  },
  {
    id: 'gpio-r',
    label: 'gpio right',
    title: 'Right pin header',
    body: 'Digital / 1-Wire / UART. DS18B20 temperature hangs off one data line with a pull-up.',
    meta: '1-Wire · TX / RX',
  },
  {
    id: 'regulator',
    label: '3v3 ldo',
    title: '3.3V regulator',
    body: 'Steps 5V down to the module rail. Clean power keeps soil ADC readings stable in the field.',
    meta: 'AMS1117 · 3V3',
  },
  {
    id: 'usb',
    label: 'usb-uart',
    title: 'USB ↔ UART',
    body: 'Flash firmware, serial logs, 5V in on install day. Later shares the rail with solar charge.',
    meta: 'CP2102 · 5V in',
  },
  {
    id: 'buttons',
    label: 'boot / en',
    title: 'BOOT & EN',
    body: 'EN resets the chip. BOOT holds GPIO0 for download mode when flashing soil-node firmware.',
    meta: 'Reset · Flash',
  },
  {
    id: 'power',
    label: 'field power',
    title: '18650 + solar',
    body: 'Off-board TP4056 + 1–2 W panel. Wake → sample → POST → deep sleep. Weeks offline on a fence post.',
    meta: 'BOM +$8–15',
  },
]

const LABELS = {
  module: [84, 28],
  antenna: [84, 12],
  'gpio-l': [8, 34],
  'gpio-r': [92, 50],
  regulator: [8, 56],
  usb: [84, 68],
  buttons: [10, 74],
  power: [48, 4],
}

const TIPS = {
  module: [46, 38],
  antenna: [48, 24],
  'gpio-l': [30, 42],
  'gpio-r': [58, 48],
  regulator: [44, 52],
  usb: [46, 60],
  buttons: [36, 66],
  power: [46, 18],
}

export default function Hardware() {
  const [active, setActive] = useState(0)
  const rootRef = useRef(null)
  const activeRef = useRef(0)
  const progressRef = useRef(0)

  useEffect(() => {
    const root = rootRef.current
    if (!root) return undefined

    const scroller = root.querySelector('.hw-scroll')
    const needle = root.querySelector('.hw-scrub__needle')
    const bar = root.querySelector('.hw-scrub__bar')
    let raf = 0
    let smooth = 0
    let target = 0
    let cur = 0

    try {
      animate(root.querySelectorAll('.hw-intro > *'), {
        opacity: [0, 1],
        y: [14, 0],
        ease: 'outExpo',
        duration: 700,
        delay: stagger(55),
      })
      animate(root.querySelectorAll('.hw-side, .hw-board'), {
        opacity: [0, 1],
        ease: 'outExpo',
        duration: 900,
        delay: stagger(80),
      })
    } catch (e) {
      console.error(e)
    }

    const applyVisual = (p) => {
      progressRef.current = p
      const idx = Math.min(PARTS.length - 1, Math.floor(p * PARTS.length * 0.999))
      if (idx !== cur) {
        cur = idx
        activeRef.current = idx
        setActive(idx)
      }
      if (needle && bar) {
        needle.style.transform = `translateX(${p * Math.max(0, bar.clientWidth - 2)}px)`
      }
    }

    const tick = () => {
      smooth += (target - smooth) * 0.22
      if (Math.abs(target - smooth) < 0.0008) smooth = target
      applyVisual(smooth)
      raf = smooth !== target ? requestAnimationFrame(tick) : 0
    }

    const onScrollNative = () => {
      const rect = scroller.getBoundingClientRect()
      const total = Math.max(1, scroller.offsetHeight - window.innerHeight)
      target = Math.min(1, Math.max(0, -rect.top / total))
      if (!raf) raf = requestAnimationFrame(tick)
    }

    window.addEventListener('scroll', onScrollNative, { passive: true })
    onScrollNative()

    return () => {
      window.removeEventListener('scroll', onScrollNative)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [])

  const part = PARTS[active]

  return (
    <div className="hw" ref={rootRef}>
      <header className="hw-topbar">
        <Link to="/" className="hw-brand">
          <Logo className="hw-brand__logo" />
          <span>Sylva</span>
        </Link>
        <nav className="hw-nav">
          <Link to="/">Plan</Link>
          <span>Hardware</span>
        </nav>
      </header>

      <div className="hw-scroll">
        <div className="hw-sticky">
          <div className="hw-intro">
            <h1>The complete soil-node toolbox</h1>
            <p>Scroll to walk the ESP32 DevKit — every block called out like an engineering schematic.</p>
          </div>

          <div className="hw-stage">
            <svg className="hw-leaders" viewBox="0 0 100 100" preserveAspectRatio="none">
              {PARTS.map((p) => {
                const [lx, ly] = LABELS[p.id]
                const [tx, ty] = TIPS[p.id]
                return (
                  <line
                    key={p.id}
                    className={`hw-leader ${part.id === p.id ? 'is-on' : ''}`}
                    x1={tx}
                    y1={ty}
                    x2={lx}
                    y2={ly}
                    vectorEffect="non-scaling-stroke"
                  />
                )
              })}
            </svg>

            {PARTS.map((p) => {
              const [lx, ly] = LABELS[p.id]
              return (
                <button
                  key={p.id}
                  type="button"
                  className={`hw-label ${part.id === p.id ? 'is-on' : ''}`}
                  style={{ left: `${lx}%`, top: `${ly}%` }}
                  onClick={() => {
                    const scroller = rootRef.current?.querySelector('.hw-scroll')
                    if (!scroller) return
                    const idx = PARTS.findIndex((x) => x.id === p.id)
                    const y =
                      scroller.offsetTop +
                      ((idx + 0.4) / PARTS.length) * (scroller.offsetHeight - window.innerHeight)
                    window.scrollTo({ top: y, behavior: 'smooth' })
                  }}
                >
                  {p.label}
                </button>
              )
            })}

            <div className="hw-board">
              <Esp32Board3D activeId={part.id} progressRef={progressRef} />
            </div>

            <aside className="hw-side" aria-live="polite">
              <div className="hw-side__inner" key={part.id}>
                <span className="hw-side__meta">{part.meta}</span>
                <h2>{part.title}</h2>
                <p>{part.body}</p>
                <div className="hw-side__index">
                  <b>{String(active + 1).padStart(2, '0')}</b>
                  <i>/</i>
                  <span>{String(PARTS.length).padStart(2, '0')}</span>
                </div>
              </div>
            </aside>

            <div className="hw-scrub" aria-hidden="true">
              <div className="hw-scrub__bar">
                {PARTS.map((p) => (
                  <i key={p.id} className={`hw-scrub__tick ${part.id === p.id ? 'is-on' : ''}`} />
                ))}
                <b className="hw-scrub__needle" />
              </div>
              <span className="hw-scrub__cap">{part.label}</span>
            </div>
          </div>
        </div>
      </div>

      <footer className="hw-foot">
        <div className="hw-foot__col">
          <p>Sense → buffer → sync → sleep · ~$35–60 BOM</p>
          <p className="hw-foot__cite">
            Built on the same cheap-node pattern as López et al. (Sensors 2024), Froiz-Míguez et al. (Sensors 2021), and I-Canopy (2025).{' '}
            <a
              href="https://github.com/ashm-023/sylva/blob/main/docs/sylva-soil-node-preprint.md"
              target="_blank"
              rel="noreferrer"
            >
              Research note →
            </a>
          </p>
        </div>
        <Link to="/">Back to farm plans</Link>
      </footer>
    </div>
  )
}

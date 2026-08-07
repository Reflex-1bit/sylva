import { useMemo, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { ContactShadows } from '@react-three/drei'
import * as THREE from 'three'

const ACCENT = '#c45c4a'

function Mat({ hot, color, roughness = 0.55, metalness = 0.1 }) {
  return (
    <meshStandardMaterial
      color={hot ? ACCENT : color}
      roughness={roughness}
      metalness={metalness}
      emissive={hot ? ACCENT : '#000000'}
      emissiveIntensity={hot ? 0.38 : 0}
    />
  )
}

/** Smooth rise — exponential ease, no spring bounce. */
function PopPart({ id, activeId, position, children, lift = 0.28 }) {
  const ref = useRef()
  const y = useRef(0)

  useFrame((_, dt) => {
    if (!ref.current) return
    const target = activeId === id ? lift : 0
    const t = 1 - Math.exp(-8 * Math.min(dt, 0.05))
    y.current += (target - y.current) * t
    const [bx, by, bz] = position
    const s = 1 + (activeId === id ? 0.04 : 0) * (y.current / Math.max(lift, 0.001))
    ref.current.position.set(bx, by + y.current, bz)
    ref.current.scale.setScalar(s)
  })

  return <group ref={ref}>{children}</group>
}

function BoardScene({ activeId, progress }) {
  const group = useRef()
  const camTarget = useMemo(() => new THREE.Vector3(9.5, 7.2, 4.2), [])
  const look = useMemo(() => new THREE.Vector3(0, 0.2, 0), [])
  const hot = (id) => activeId === id

  useFrame(({ camera }) => {
    const p = progress.current ?? 0
    // Pulled back so full board + pop lift stays in frame
    camTarget.set(9.2, 7.0, 4.0 - p * 0.35)
    camera.position.lerp(camTarget, 0.12)
    look.set(0, 0.25, 0)
    camera.lookAt(look)
    if (!group.current) return
    group.current.rotation.y = THREE.MathUtils.degToRad(p * 6)
  })

  const pinZs = useMemo(() => Array.from({ length: 15 }, (_, i) => 1.9 - i * 0.275), [])

  return (
    <>
      <ambientLight intensity={1.0} />
      <directionalLight castShadow position={[8, 7, 4]} intensity={1.35} shadow-mapSize={[1024, 1024]} />
      <directionalLight position={[-4, 5, -3]} intensity={0.4} />
      <pointLight position={[2, 2, 1]} intensity={0.3} />

      <group ref={group} position={[0, 0.1, 0]} scale={0.92}>
        {/* PCB base — stays put */}
        <mesh castShadow receiveShadow position={[0, 0, 0]}>
          <boxGeometry args={[3.05, 0.14, 5.35]} />
          <meshStandardMaterial color="#e8e4dc" roughness={0.78} metalness={0.02} />
        </mesh>
        <mesh position={[0, -0.09, 0]} receiveShadow>
          <boxGeometry args={[3.05, 0.04, 5.35]} />
          <meshStandardMaterial color="#b9b3a6" roughness={0.7} />
        </mesh>
        <mesh position={[0, 0.075, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <planeGeometry args={[2.7, 4.9]} />
          <meshStandardMaterial color="#dcd7ce" roughness={0.85} />
        </mesh>

        {[
          [-1.28, 2.3],
          [1.28, 2.3],
          [-1.28, -2.3],
          [1.28, -2.3],
        ].map(([x, z], i) => (
          <mesh key={i} position={[x, 0.08, z]} rotation={[-Math.PI / 2, 0, 0]}>
            <circleGeometry args={[0.12, 20]} />
            <meshStandardMaterial color="#1c1c1a" />
          </mesh>
        ))}

        <PopPart id="power" activeId={activeId} position={[0, 0.12, 2.4]} lift={0.28}>
          <mesh>
            <boxGeometry args={[1.75, 0.05, 0.32]} />
            <Mat hot={hot('power')} color="#d5d0c5" />
          </mesh>
          <mesh position={[0, 0.04, 0]}>
            <boxGeometry args={[1.8, 0.01, 0.36]} />
            <meshStandardMaterial color={hot('power') ? ACCENT : '#2c2c2a'} wireframe />
          </mesh>
        </PopPart>

        <PopPart id="antenna" activeId={activeId} position={[0, 0.12, 1.95]} lift={0.26}>
          <mesh>
            <boxGeometry args={[1.2, 0.05, 0.45]} />
            <Mat hot={hot('antenna')} color="#cfc9bc" />
          </mesh>
          {[-0.32, -0.12, 0.08, 0.28].map((x, i) => (
            <mesh key={i} position={[x, 0.05, 0]}>
              <boxGeometry args={[0.08, 0.03, 0.32]} />
              <Mat hot={hot('antenna')} color="#c9a227" metalness={0.8} roughness={0.28} />
            </mesh>
          ))}
        </PopPart>

        <PopPart id="module" activeId={activeId} position={[0, 0.28, 1.05]} lift={0.32}>
          <mesh castShadow>
            <boxGeometry args={[1.8, 0.38, 1.4]} />
            <Mat hot={hot('module')} color="#a8a397" metalness={0.55} roughness={0.32} />
          </mesh>
          <mesh position={[0, 0.2, 0]}>
            <boxGeometry args={[1.68, 0.03, 1.28]} />
            <Mat hot={hot('module')} color="#d2cdc3" metalness={0.6} roughness={0.28} />
          </mesh>
          {Array.from({ length: 9 }).map((_, i) => (
            <mesh key={i} position={[-0.72 + i * 0.18, 0.22, 0]}>
              <boxGeometry args={[0.04, 0.015, 1.18]} />
              <meshStandardMaterial color="#8f8a7e" metalness={0.5} roughness={0.35} />
            </mesh>
          ))}
          <mesh position={[0, 0.24, 0.08]} castShadow>
            <boxGeometry args={[1.15, 0.06, 0.55]} />
            <Mat hot={hot('module')} color="#efebe3" roughness={0.5} />
          </mesh>
        </PopPart>

        <PopPart id="gpio-l" activeId={activeId} position={[-1.42, 0, 0]} lift={0.26}>
          {pinZs.map((z, i) => (
            <group key={i}>
              <mesh position={[0.03, -0.22, z]} castShadow>
                <boxGeometry args={[0.12, 0.32, 0.08]} />
                <Mat hot={hot('gpio-l')} color="#2c2c2a" metalness={0.6} roughness={0.3} />
              </mesh>
              <mesh position={[0.04, 0.1, z]} castShadow>
                <boxGeometry args={[0.16, 0.06, 0.1]} />
                <Mat hot={hot('gpio-l')} color="#5a5650" metalness={0.5} roughness={0.35} />
              </mesh>
            </group>
          ))}
        </PopPart>

        <PopPart id="gpio-r" activeId={activeId} position={[1.42, 0, 0]} lift={0.26}>
          {pinZs.map((z, i) => (
            <group key={i}>
              <mesh position={[-0.03, -0.22, z]} castShadow>
                <boxGeometry args={[0.12, 0.32, 0.08]} />
                <Mat hot={hot('gpio-r')} color="#2c2c2a" metalness={0.6} roughness={0.3} />
              </mesh>
              <mesh position={[-0.04, 0.1, z]} castShadow>
                <boxGeometry args={[0.16, 0.06, 0.1]} />
                <Mat hot={hot('gpio-r')} color="#5a5650" metalness={0.5} roughness={0.35} />
              </mesh>
            </group>
          ))}
        </PopPart>

        <PopPart id="regulator" activeId={activeId} position={[0, 0.16, -0.2]} lift={0.28}>
          <mesh position={[0, 0, 0.25]} castShadow>
            <boxGeometry args={[1.15, 0.14, 0.42]} />
            <Mat hot={hot('regulator')} color="#c4beb2" />
          </mesh>
          <mesh position={[0, 0.02, -0.3]} castShadow>
            <boxGeometry args={[0.8, 0.18, 0.35]} />
            <Mat hot={hot('regulator')} color="#2a2826" metalness={0.4} roughness={0.4} />
          </mesh>
          <mesh position={[0.28, 0.02, -0.3]}>
            <boxGeometry args={[0.16, 0.22, 0.12]} />
            <Mat hot={hot('regulator')} color="#1a1816" metalness={0.45} roughness={0.35} />
          </mesh>
        </PopPart>

        <PopPart id="usb" activeId={activeId} position={[0, 0.12, -1.7]} lift={0.28}>
          <mesh position={[0, 0.03, 0.7]} castShadow>
            <boxGeometry args={[1.2, 0.14, 0.45]} />
            <Mat hot={hot('usb')} color="#1f1f1d" roughness={0.45} />
          </mesh>
          {[-0.45, -0.25, 0.25, 0.45].map((x, i) => (
            <mesh key={i} position={[x, 0.08, 0.75]}>
              <boxGeometry args={[0.12, 0.05, 0.08]} />
              <meshStandardMaterial color="#6a6560" />
            </mesh>
          ))}
          <mesh position={[0, -0.04, -0.8]} castShadow>
            <boxGeometry args={[0.95, 0.28, 0.42]} />
            <Mat hot={hot('usb')} color="#151513" metalness={0.5} roughness={0.32} />
          </mesh>
          <mesh position={[0, -0.04, -0.95]}>
            <boxGeometry args={[0.6, 0.14, 0.22]} />
            <meshStandardMaterial color="#050505" metalness={0.6} roughness={0.25} />
          </mesh>
        </PopPart>

        <PopPart id="buttons" activeId={activeId} position={[0, 0.14, -1.5]} lift={0.3}>
          {[-0.8, 0.8].map((x, i) => (
            <group key={i} position={[x, 0, 0]}>
              <mesh castShadow>
                <cylinderGeometry args={[0.2, 0.2, 0.1, 28]} />
                <Mat hot={hot('buttons')} color="#3f3d3a" roughness={0.45} />
              </mesh>
              <mesh position={[0, 0.07, 0]}>
                <cylinderGeometry args={[0.11, 0.11, 0.06, 28]} />
                <Mat hot={hot('buttons')} color="#d0cbc2" metalness={0.55} roughness={0.3} />
              </mesh>
            </group>
          ))}
        </PopPart>
      </group>

      <ContactShadows position={[0, -1.2, 0]} opacity={0.3} scale={12} blur={2.6} far={5} color="#2c2c2a" />
    </>
  )
}

export default function Esp32Board3D({ activeId, progressRef }) {
  return (
    <div className="hw-board__canvas" aria-label="ESP32 DevKit 3D model">
      <Canvas
        camera={{ position: [9.2, 7.0, 4.0], fov: 32, near: 0.1, far: 100 }}
        dpr={[1, 2]}
        gl={{ antialias: true, alpha: true }}
        shadows
        onCreated={({ gl }) => {
          gl.setClearColor(0x000000, 0)
        }}
      >
        <BoardScene activeId={activeId} progress={progressRef} />
      </Canvas>
    </div>
  )
}

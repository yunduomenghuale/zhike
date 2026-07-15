<template>
  <div ref="containerRef" class="login-background">
    <canvas ref="canvasRef" class="login-canvas" />
    <div class="login-overlay" />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as THREE from 'three'

const containerRef = ref(null)
const canvasRef = ref(null)

let renderer = null
let scene = null
let camera = null
let animationId = null
let particles = null
let lines = null
let geometries = []
let dataFlows = []

// 鼠标交互
const mouseTarget = { x: 0, y: 0 }
const mouseCurrent = { x: 0, y: 0 }
const mouseWorld = { x: 0, y: 0 }

// 粒子配置
const PARTICLE_COUNT = 320
const CONNECTION_DISTANCE = 150
const MAX_CONNECTIONS = 4
const COLORS = [0x2563eb, 0x4f46e5, 0x7c3aed, 0x60a5fa, 0x34d399]
const MOUSE_INFLUENCE = 60

function init() {
  if (!containerRef.value || !canvasRef.value) return

  const width = containerRef.value.offsetWidth
  const height = containerRef.value.offsetHeight

  // 场景
  scene = new THREE.Scene()

  // 相机
  camera = new THREE.PerspectiveCamera(75, width / height, 1, 1000)
  camera.position.z = 220

  // 渲染器
  renderer = new THREE.WebGLRenderer({
    canvas: canvasRef.value,
    alpha: true,
    antialias: true,
  })
  renderer.setSize(width, height)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))

  // 创建粒子
  createParticles(width, height)

  // 创建连线
  createLines()

  // 创建浮动几何体
  createFloatingGeometries()

  // 创建数据流
  createDataFlows()

  // 开始动画
  animate()

  // 监听事件
  window.addEventListener('resize', onResize)
  window.addEventListener('mousemove', onMouseMove)
}

function createParticles(width, height) {
  const geometry = new THREE.BufferGeometry()
  const positions = new Float32Array(PARTICLE_COUNT * 3)
  const colors = new Float32Array(PARTICLE_COUNT * 3)
  const sizes = new Float32Array(PARTICLE_COUNT)
  const velocities = []

  const colorPalette = COLORS.map((c) => new THREE.Color(c))

  for (let i = 0; i < PARTICLE_COUNT; i++) {
    const i3 = i * 3
    positions[i3] = (Math.random() - 0.5) * width * 1.4
    positions[i3 + 1] = (Math.random() - 0.5) * height * 1.4
    positions[i3 + 2] = (Math.random() - 0.5) * 150

    const color = colorPalette[Math.floor(Math.random() * colorPalette.length)]
    colors[i3] = color.r
    colors[i3 + 1] = color.g
    colors[i3 + 2] = color.b

    sizes[i] = Math.random() * 4 + 2

    velocities.push({
      x: (Math.random() - 0.5) * 0.4,
      y: (Math.random() - 0.5) * 0.4,
      z: (Math.random() - 0.5) * 0.15,
      baseX: positions[i3],
      baseY: positions[i3 + 1],
    })
  }

  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
  geometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1))
  geometry.userData.velocities = velocities

  const material = new THREE.PointsMaterial({
    size: 4,
    vertexColors: true,
    transparent: true,
    opacity: 0.85,
    blending: THREE.AdditiveBlending,
    sizeAttenuation: true,
    depthWrite: false,
  })

  particles = new THREE.Points(geometry, material)
  scene.add(particles)
}

function createLines() {
  const geometry = new THREE.BufferGeometry()
  const maxLines = PARTICLE_COUNT * MAX_CONNECTIONS
  const positions = new Float32Array(maxLines * 6)
  const colors = new Float32Array(maxLines * 6)

  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
  geometry.setDrawRange(0, 0)

  const material = new THREE.LineBasicMaterial({
    vertexColors: true,
    transparent: true,
    opacity: 0.45,
    blending: THREE.AdditiveBlending,
  })

  lines = new THREE.LineSegments(geometry, material)
  scene.add(lines)
}

function createFloatingGeometries() {
  const shapes = [
    new THREE.IcosahedronGeometry(12, 0),
    new THREE.OctahedronGeometry(14, 0),
    new THREE.TorusGeometry(12, 3, 8, 24),
    new THREE.BoxGeometry(16, 16, 16),
  ]

  const material = new THREE.MeshBasicMaterial({
    color: 0x4f46e5,
    transparent: true,
    opacity: 0.18,
    wireframe: true,
    blending: THREE.AdditiveBlending,
  })

  for (let i = 0; i < 8; i++) {
    const geo = shapes[Math.floor(Math.random() * shapes.length)]
    const mesh = new THREE.Mesh(geo, material.clone())

    mesh.position.set(
      (Math.random() - 0.5) * 900,
      (Math.random() - 0.5) * 700,
      (Math.random() - 0.5) * 200 - 100,
    )

    mesh.userData = {
      rotX: (Math.random() - 0.5) * 0.01,
      rotY: (Math.random() - 0.5) * 0.01,
      floatY: Math.random() * Math.PI * 2,
      floatSpeed: 0.005 + Math.random() * 0.01,
      floatAmp: 10 + Math.random() * 20,
    }

    scene.add(mesh)
    geometries.push(mesh)
  }
}

function createDataFlows() {
  // 创建流动的数据线条
  const material = new THREE.LineBasicMaterial({
    color: 0x3b82f6,
    transparent: true,
    opacity: 0.55,
    blending: THREE.AdditiveBlending,
  })

  for (let i = 0; i < 12; i++) {
    const geometry = new THREE.BufferGeometry()
    const startX = (Math.random() - 0.5) * 900
    const startY = (Math.random() - 0.5) * 700
    const endX = startX + (Math.random() - 0.5) * 200
    const endY = startY + (Math.random() - 0.5) * 200

    const positions = new Float32Array([
      startX, startY, (Math.random() - 0.5) * 100,
      endX, endY, (Math.random() - 0.5) * 100,
    ])

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))

    const line = new THREE.Line(geometry, material.clone())
    line.userData = {
      progress: Math.random(),
      speed: 0.005 + Math.random() * 0.01,
      startX, startY, endX, endY,
      z: positions[2],
    }

    scene.add(line)
    dataFlows.push(line)
  }
}

function updateConnections() {
  if (!particles || !lines) return

  const positions = particles.geometry.attributes.position.array
  const linePositions = lines.geometry.attributes.position.array
  const lineColors = lines.geometry.attributes.color.array
  const color = new THREE.Color(0x4f46e5)

  let lineIndex = 0

  for (let i = 0; i < PARTICLE_COUNT; i++) {
    let connections = 0
    const ix = i * 3

    for (let j = i + 1; j < PARTICLE_COUNT; j++) {
      if (connections >= MAX_CONNECTIONS) break

      const jx = j * 3
      const dx = positions[ix] - positions[jx]
      const dy = positions[ix + 1] - positions[jx + 1]
      const dz = positions[ix + 2] - positions[jx + 2]
      const distance = Math.sqrt(dx * dx + dy * dy + dz * dz)

      if (distance < CONNECTION_DISTANCE) {
        const li = lineIndex * 6
        const opacity = (1 - distance / CONNECTION_DISTANCE) * 0.8

        linePositions[li] = positions[ix]
        linePositions[li + 1] = positions[ix + 1]
        linePositions[li + 2] = positions[ix + 2]
        linePositions[li + 3] = positions[jx]
        linePositions[li + 4] = positions[jx + 1]
        linePositions[li + 5] = positions[jx + 2]

        lineColors[li] = color.r * opacity
        lineColors[li + 1] = color.g * opacity
        lineColors[li + 2] = color.b * opacity
        lineColors[li + 3] = color.r * opacity
        lineColors[li + 4] = color.g * opacity
        lineColors[li + 5] = color.b * opacity

        lineIndex++
        connections++
      }
    }
  }

  lines.geometry.setDrawRange(0, lineIndex * 2)
  lines.geometry.attributes.position.needsUpdate = true
  lines.geometry.attributes.color.needsUpdate = true
}

function updateDataFlows() {
  dataFlows.forEach((line) => {
    const ud = line.userData
    ud.progress += ud.speed
    if (ud.progress > 1) ud.progress = 0

    const positions = line.geometry.attributes.position.array
    const dashSize = 0.15

    // 数据流：一段短线在路径上移动
    positions[0] = ud.startX + (ud.endX - ud.startX) * ud.progress
    positions[1] = ud.startY + (ud.endY - ud.startY) * ud.progress
    positions[2] = ud.z
    positions[3] = ud.startX + (ud.endX - ud.startX) * Math.min(ud.progress + dashSize, 1)
    positions[4] = ud.startY + (ud.endY - ud.startY) * Math.min(ud.progress + dashSize, 1)
    positions[5] = ud.z

    line.geometry.attributes.position.needsUpdate = true

    // 头部亮，尾部淡
    line.material.opacity = Math.sin(ud.progress * Math.PI) * 0.6 + 0.2
  })
}

function updateFloatingGeometries() {
  const time = Date.now() * 0.001

  geometries.forEach((mesh) => {
    const ud = mesh.userData
    mesh.rotation.x += ud.rotX
    mesh.rotation.y += ud.rotY
    mesh.position.y += Math.sin(time * ud.floatSpeed + ud.floatY) * 0.2
  })
}

function animate() {
  animationId = requestAnimationFrame(animate)

  if (!particles || !camera) return

  const positions = particles.geometry.attributes.position.array
  const velocities = particles.geometry.userData.velocities

  // 平滑插值鼠标位置
  mouseCurrent.x += (mouseTarget.x - mouseCurrent.x) * 0.06
  mouseCurrent.y += (mouseTarget.y - mouseCurrent.y) * 0.06

  // 计算鼠标在世界坐标中的位置
  mouseWorld.x = mouseCurrent.x * 400
  mouseWorld.y = mouseCurrent.y * 300

  for (let i = 0; i < PARTICLE_COUNT; i++) {
    const i3 = i * 3

    // 基础运动
    positions[i3] += velocities[i].x
    positions[i3 + 1] += velocities[i].y
    positions[i3 + 2] += velocities[i].z

    // 边界反弹
    if (Math.abs(positions[i3]) > 500) velocities[i].x *= -1
    if (Math.abs(positions[i3 + 1]) > 380) velocities[i].y *= -1
    if (Math.abs(positions[i3 + 2]) > 150) velocities[i].z *= -1

    // 鼠标吸引效果
    const dx = mouseWorld.x - positions[i3]
    const dy = mouseWorld.y - positions[i3 + 1]
    const dist = Math.sqrt(dx * dx + dy * dy)
    const attractRadius = 250

    if (dist < attractRadius && dist > 10) {
      const force = ((attractRadius - dist) / attractRadius) * 0.035
      velocities[i].x += (dx / dist) * force
      velocities[i].y += (dy / dist) * force
    }

    // 阻尼，让速度不会无限增大
    velocities[i].x *= 0.995
    velocities[i].y *= 0.995
    velocities[i].z *= 0.995

    // 限制最大速度
    velocities[i].x = Math.max(-2, Math.min(2, velocities[i].x))
    velocities[i].y = Math.max(-2, Math.min(2, velocities[i].y))
    velocities[i].z = Math.max(-1, Math.min(1, velocities[i].z))
  }

  particles.geometry.attributes.position.needsUpdate = true

  // 相机随鼠标轻微移动
  camera.position.x = mouseCurrent.x * MOUSE_INFLUENCE
  camera.position.y = mouseCurrent.y * MOUSE_INFLUENCE
  camera.lookAt(mouseCurrent.x * 20, mouseCurrent.y * 20, 0)

  // 整体缓慢旋转 + 鼠标影响
  particles.rotation.z += 0.0002
  particles.rotation.x = mouseCurrent.y * 0.08
  particles.rotation.y = mouseCurrent.x * 0.08

  updateConnections()
  updateDataFlows()
  updateFloatingGeometries()

  renderer.render(scene, camera)
}

function onResize() {
  if (!containerRef.value || !renderer || !camera) return

  const width = containerRef.value.offsetWidth
  const height = containerRef.value.offsetHeight

  camera.aspect = width / height
  camera.updateProjectionMatrix()
  renderer.setSize(width, height)
}

function onMouseMove(e) {
  mouseTarget.x = (e.clientX / window.innerWidth) * 2 - 1
  mouseTarget.y = -(e.clientY / window.innerHeight) * 2 + 1
}

function cleanup() {
  window.removeEventListener('resize', onResize)
  window.removeEventListener('mousemove', onMouseMove)
  if (animationId) cancelAnimationFrame(animationId)

  if (renderer) {
    renderer.dispose()
    renderer.forceContextLoss()
  }

  if (particles) {
    particles.geometry.dispose()
    particles.material.dispose()
  }

  if (lines) {
    lines.geometry.dispose()
    lines.material.dispose()
  }

  geometries.forEach((mesh) => {
    mesh.geometry.dispose()
    mesh.material.dispose()
  })

  dataFlows.forEach((line) => {
    line.geometry.dispose()
    line.material.dispose()
  })

  scene = null
  camera = null
  renderer = null
  particles = null
  lines = null
  geometries = []
  dataFlows = []
}

onMounted(init)
onBeforeUnmount(cleanup)
</script>

<style scoped>
.login-background {
  position: absolute;
  inset: 0;
  overflow: hidden;
  z-index: 0;
}

.login-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}

.login-overlay {
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.72) 0%, rgba(248, 250, 252, 0.62) 50%, rgba(255, 255, 255, 0.72) 100%);
  pointer-events: none;
}
</style>

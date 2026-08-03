<template>
  <div
    ref="stageRef"
    class="helix-carousel"
    :style="rootStyle"
    :aria-label="ariaLabel"
    role="region"
    @mouseenter="handleEnter"
    @mouseleave="handleLeave"
    @wheel.prevent="handleWheel"
    @pointerdown="handlePointerDown"
    @pointermove="handlePointerMove"
    @pointerup="handlePointerUp"
    @pointercancel="handlePointerUp"
  >
    <div class="helix-carousel__collection">
      <div ref="listRef" class="helix-carousel__list">
        <div
          v-for="item in renderedItems"
          :key="item._helixKey"
          class="helix-carousel__item"
          :data-primary="item._isPrimary"
        >
          <button
            class="helix-carousel__card"
            type="button"
            :disabled="item.disabled"
            @pointerdown.stop
            @click.stop="selectItem(item)"
          >
            <slot name="item" :item="item">
              <span
                class="helix-carousel__icon"
                :style="{
                  color: item.color || defaultIconColor,
                  background: item.background || item.bg || defaultIconBackground,
                }"
              >
                <slot name="icon" :item="item">
                  <component v-if="item.icon" :is="item.icon" />
                </slot>
              </span>
              <span class="helix-carousel__text">
                <span class="helix-carousel__title">{{ item.label }}</span>
                <span class="helix-carousel__description">
                  {{ item.description ?? item.desc }}
                </span>
              </span>
            </slot>
          </button>
        </div>
      </div>
    </div>
    <div class="helix-carousel__vignette" aria-hidden="true" />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  items: { type: Array, required: true },
  ariaLabel: { type: String, default: '功能入口' },
  background: { type: String, default: '#f6f9fd' },
  autoSpeed: { type: Number, default: -0.16 },
  wheelSensitivity: { type: Number, default: 0.0025 },
  dragSensitivity: { type: Number, default: 0.018 },
  rotationDegrees: { type: Number, default: 42 },
  helixCount: { type: Number, default: 2 },
  repeatCount: { type: Number, default: 2 },
  minScale: { type: Number, default: 0.62 },
  backFade: { type: Number, default: 0.76 },
  backBlur: { type: Number, default: 0.32 },
  pauseOnHover: { type: Boolean, default: false },
  defaultIconColor: { type: String, default: '#2563eb' },
  defaultIconBackground: { type: String, default: '#eff6ff' },
})

const emit = defineEmits(['select'])

const stageRef = ref(null)
const listRef = ref(null)
const stageWidth = ref(1280)
const stageHeight = ref(820)
const paused = ref(false)
const prefersReducedMotion = ref(false)

const safeHelixCount = computed(() => Math.max(1, Math.round(props.helixCount)))
const safeRepeatCount = computed(() => Math.max(1, Math.round(props.repeatCount)))
const cardsPerHelix = computed(() => Math.max(1, props.items.length * safeRepeatCount.value))
const rotationAngle = computed(() => props.rotationDegrees * Math.PI / 180)
const cardGap = computed(() => Math.min(116, Math.max(96, stageHeight.value * 0.108)))
const orbitDepth = computed(() => Math.min(530, Math.max(310, stageWidth.value * 0.37)))
const rootStyle = computed(() => ({ '--helix-bg': props.background }))

const renderedItems = computed(() => {
  const output = []
  for (let helix = 0; helix < safeHelixCount.value; helix += 1) {
    for (let copy = 0; copy < safeRepeatCount.value; copy += 1) {
      props.items.forEach((item, index) => {
        const identity = item.id ?? item.key ?? item.path ?? item.label ?? index
        output.push({
          ...item,
          _source: item,
          _helix: helix,
          _order: copy * props.items.length + index,
          _helixKey: `${helix}-${copy}-${identity}-${index}`,
          _isPrimary: helix === 0 && copy === 0,
        })
      })
    }
  }
  return output
})

let frameId = 0
let lastFrame = 0
let orbitOffset = 0
let velocity = props.autoSpeed
let isDragging = false
let lastPointerY = 0
let resizeObserver = null
let motionQuery = null

function wrapAround(value, size) {
  return ((value % size) + size) % size
}

function centeredPosition(order) {
  const count = cardsPerHelix.value
  return wrapAround(order - orbitOffset + count / 2, count) - count / 2
}

function applyItemStyles() {
  const elements = listRef.value?.children
  if (!elements) return

  renderedItems.value.forEach((item, index) => {
    const element = elements[index]
    if (!element) return

    const relative = centeredPosition(item._order)
    const phase = item._helix * (Math.PI * 2 / safeHelixCount.value)
    const angle = relative * rotationAngle.value + phase
    const cos = Math.cos(angle)
    const sin = Math.sin(angle)
    const backAmount = (1 - cos) / 2
    const verticalFade = Math.max(0, 1 - Math.abs(relative) / (cardsPerHelix.value * 0.43))
    const frontAmount = (cos + 1) / 2
    const x = sin * orbitDepth.value
    const z = (cos - 1) * orbitDepth.value
    const y = relative * cardGap.value
    const scale = props.minScale + frontAmount * 0.28
    const opacity = Math.max(0.12, verticalFade * (1 - backAmount * props.backFade))
    const blur = Math.pow(backAmount, 2) * props.backBlur
    const recede = Math.min(0.82, backAmount * 0.7 + (1 - verticalFade) * 0.32)
    const contentOpacity = frontAmount > 0.5 && verticalFade > 0.38 ? 1 : 0
    const clickable = frontAmount > 0.24 && verticalFade > 0.24
    const zIndex = Math.round(frontAmount * 1000 + verticalFade * 100)

    element.style.transform = [
      'translate(-50%, -50%)',
      `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, ${z.toFixed(1)}px)`,
      `rotateY(${(angle * 180 / Math.PI).toFixed(1)}deg)`,
      `scale(${scale.toFixed(3)})`,
    ].join(' ')
    element.style.opacity = opacity.toFixed(3)
    element.style.filter = `blur(${blur.toFixed(3)}em)`
    element.style.setProperty('--recede', recede.toFixed(3))
    element.style.setProperty('--content-opacity', String(contentOpacity))

    const pointerEvents = clickable ? 'auto' : 'none'
    if (element.style.zIndex !== String(zIndex)) element.style.zIndex = String(zIndex)
    if (element.style.pointerEvents !== pointerEvents) element.style.pointerEvents = pointerEvents
  })
}

function selectItem(item) {
  if (!item.disabled) emit('select', item._source)
}

function handleWheel(event) {
  if (!prefersReducedMotion.value) velocity += event.deltaY * props.wheelSensitivity
}

function handlePointerDown(event) {
  if (prefersReducedMotion.value) return
  isDragging = true
  paused.value = true
  lastPointerY = event.clientY
  event.currentTarget.setPointerCapture?.(event.pointerId)
}

function handlePointerMove(event) {
  if (!isDragging) return
  const delta = event.clientY - lastPointerY
  lastPointerY = event.clientY
  velocity += delta * props.dragSensitivity
}

function handlePointerUp(event) {
  isDragging = false
  paused.value = false
  event.currentTarget.releasePointerCapture?.(event.pointerId)
}

function handleEnter() {
  if (props.pauseOnHover) paused.value = true
}

function handleLeave() {
  isDragging = false
  paused.value = false
}

function tick(now) {
  if (!lastFrame) lastFrame = now
  const delta = Math.min(64, now - lastFrame)
  lastFrame = now
  const targetVelocity = paused.value ? 0 : props.autoSpeed
  velocity += (targetVelocity - velocity) * Math.min(1, delta / 900)
  orbitOffset = wrapAround(
    orbitOffset + velocity * delta / 1000,
    cardsPerHelix.value,
  )
  applyItemStyles()
  frameId = window.requestAnimationFrame(tick)
}

function startAnimation() {
  if (frameId || prefersReducedMotion.value) return
  lastFrame = 0
  frameId = window.requestAnimationFrame(tick)
}

function stopAnimation() {
  if (frameId) window.cancelAnimationFrame(frameId)
  frameId = 0
  lastFrame = 0
}

function updateMotionPreference(event) {
  prefersReducedMotion.value = event.matches
  if (event.matches) stopAnimation()
  else startAnimation()
}

function reset() {
  orbitOffset = 0
  velocity = props.autoSpeed
  nextTick(applyItemStyles)
}

watch(
  () => [
    props.items,
    props.helixCount,
    props.repeatCount,
    props.rotationDegrees,
    props.minScale,
    props.backFade,
    props.backBlur,
  ],
  reset,
)
watch(() => props.autoSpeed, (value) => { velocity = value })

onMounted(() => {
  const updateStageSize = () => {
    if (!stageRef.value) return
    const rect = stageRef.value.getBoundingClientRect()
    stageWidth.value = rect.width
    stageHeight.value = rect.height
  }
  updateStageSize()
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      updateStageSize()
      applyItemStyles()
    })
    resizeObserver.observe(stageRef.value)
  }

  motionQuery = window.matchMedia?.('(prefers-reduced-motion: reduce)') || null
  prefersReducedMotion.value = Boolean(motionQuery?.matches)
  motionQuery?.addEventListener?.('change', updateMotionPreference)
  applyItemStyles()
  startAnimation()
})

onBeforeUnmount(() => {
  stopAnimation()
  resizeObserver?.disconnect()
  motionQuery?.removeEventListener?.('change', updateMotionPreference)
})

defineExpose({ reset, pause: () => { paused.value = true }, resume: () => { paused.value = false } })
</script>

<style scoped>
.helix-carousel {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: clip;
  cursor: grab;
  user-select: none;
  touch-action: pan-x;
}

.helix-carousel:active { cursor: grabbing; }
.helix-carousel__collection,
.helix-carousel__list { position: absolute; inset: 0; }
.helix-carousel__list {
  perspective: 76em;
  perspective-origin: 50% 48%;
  transform-style: preserve-3d;
}
.helix-carousel__item {
  position: absolute;
  top: 50%;
  left: 50%;
  transform-style: preserve-3d;
  will-change: transform, opacity;
}
.helix-carousel__card {
  position: relative;
  width: clamp(15.75rem, 20vw, 18.75rem);
  aspect-ratio: 3 / 2;
  padding: 1.25em 1.35em 1.25em 1.2em;
  display: flex;
  align-items: center;
  gap: 0.95em;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.54);
  border-radius: 0.9em;
  background: linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(246, 249, 253, 0.94));
  box-shadow:
    0 2.9em 5.6em rgba(37, 99, 235, 0.13),
    0 1.4em 3em rgba(15, 23, 42, 0.08),
    inset 0 1px 1px rgba(255, 255, 255, 0.98),
    inset 0 -1px 2px rgba(37, 99, 235, 0.08),
    0 0 0 1px rgba(37, 99, 235, 0.1) inset;
  color: #0f172a;
  cursor: pointer;
  text-align: left;
  transform-style: preserve-3d;
  backface-visibility: hidden;
}
.helix-carousel__card::before {
  content: '';
  position: absolute;
  inset: 0.08em;
  z-index: 1;
  border-radius: 0.78em;
  background:
    linear-gradient(110deg, rgba(255, 255, 255, 0.82), transparent 38%),
    linear-gradient(to bottom, rgba(255, 255, 255, 0.45), transparent 42%);
  opacity: 0.56;
  pointer-events: none;
}
.helix-carousel__card::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 4;
  background: var(--helix-bg);
  opacity: var(--recede, 0);
  pointer-events: none;
}
.helix-carousel__card:hover {
  border-color: rgba(96, 165, 250, 0.82);
  box-shadow:
    0 3.1em 6.4em rgba(37, 99, 235, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.94);
}
.helix-carousel__card:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.38);
  outline-offset: 4px;
}
.helix-carousel__card:disabled { cursor: not-allowed; opacity: 0.55; }
.helix-carousel__icon,
.helix-carousel__text { position: relative; z-index: 2; }
.helix-carousel__icon {
  width: 4.8em;
  height: 4.8em;
  flex: 0 0 4.8em;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 1.05em;
  font-size: 1.55em;
}
.helix-carousel__icon :deep(svg) { width: 1em; height: 1em; }
.helix-carousel__text {
  flex: 1;
  min-width: 0;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  gap: 0.5em;
}
.helix-carousel__title {
  overflow: hidden;
  color: #0f172a;
  font-size: 1.38em;
  font-weight: 800;
  line-height: 1.18;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.helix-carousel__description {
  overflow: hidden;
  color: #64748b;
  font-size: 0.86em;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.helix-carousel__vignette {
  position: absolute;
  inset: 0;
  z-index: 30;
  pointer-events: none;
  background:
    linear-gradient(to bottom, var(--helix-bg) 0%, color-mix(in srgb, var(--helix-bg) 54%, transparent) 14%, transparent 25%, transparent 72%, color-mix(in srgb, var(--helix-bg) 64%, transparent) 86%, var(--helix-bg) 100%),
    linear-gradient(to right, var(--helix-bg) 0%, color-mix(in srgb, var(--helix-bg) 62%, transparent) 9%, transparent 24%, transparent 76%, color-mix(in srgb, var(--helix-bg) 72%, transparent) 91%, var(--helix-bg) 100%);
  opacity: 0.88;
}

@media (max-width: 1100px), (prefers-reduced-motion: reduce) {
  .helix-carousel { height: auto; min-height: auto; overflow: visible; cursor: default; }
  .helix-carousel__collection,
  .helix-carousel__list { position: relative; }
  .helix-carousel__list {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 16px;
    perspective: none;
  }
  .helix-carousel__item {
    position: relative;
    top: auto;
    left: auto;
    transform: none !important;
    opacity: 1 !important;
    filter: none !important;
    pointer-events: auto !important;
  }
  .helix-carousel__item[data-primary='false'] { display: none; }
  .helix-carousel__card { width: 100%; min-height: 126px; }
  .helix-carousel__vignette { display: none; }
}
</style>

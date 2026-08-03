# HelixFeatureCarousel

与业务无关的 Vue 3 双螺旋功能卡片组件。组件不依赖 Vue Router 或 Element Plus；图标可以传入任意 Vue 组件。

```vue
<script setup>
import { Rocket, Settings } from 'lucide-vue-next'
import HelixFeatureCarousel from './HelixFeatureCarousel.vue'

const items = [
  { id: 'start', label: '开始使用', description: '创建第一个项目', icon: Rocket },
  { id: 'settings', label: '项目设置', description: '配置团队和权限', icon: Settings },
]

function handleSelect(item) {
  console.log(item.id)
}
</script>

<template>
  <div style="height: 720px">
    <HelixFeatureCarousel :items="items" @select="handleSelect" />
  </div>
</template>
```

常用属性：

- `items`：卡片数组，支持 `id/key/path`、`label`、`description/desc`、`icon`、`color`、`background/bg` 和 `disabled`。
- `auto-speed`：自动旋转速度，默认 `-0.16`；设为 `0` 可停止自动旋转。
- `helix-count`：螺旋数量，默认 `2`。
- `rotation-degrees`：相邻卡片旋转角度，默认 `42`。
- `pause-on-hover`：鼠标悬停时暂停。
- `background`：组件背景色，用于远端卡片遮罩。

事件与插槽：

- `select(item)`：点击可见卡片时触发。
- `#icon="{ item }"`：自定义图标。
- `#item="{ item }"`：完全自定义卡片内容。

组件会在宽度不超过 `1100px` 或用户启用“减少动态效果”时自动降级为普通网格。

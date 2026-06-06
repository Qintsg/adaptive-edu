<script setup lang="ts">
import { computed } from 'vue'
import { NIcon } from 'naive-ui'
import { getIconComponent } from '@/theme/icons'

const props = withDefaults(defineProps<{
  name?: string
  size?: number | string
  color?: string
}>(), {
  size: 18
})

const iconComponent = computed(() => getIconComponent(props.name))
</script>

<template>
  <n-icon :size="size" :color="color" class="app-icon">
    <component :is="iconComponent" />
  </n-icon>
</template>

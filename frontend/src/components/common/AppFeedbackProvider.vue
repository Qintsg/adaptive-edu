<script setup lang="ts">
import { onBeforeUnmount } from 'vue'
import { useDialog, useLoadingBar, useMessage, useNotification } from 'naive-ui'
import { clearFeedbackApi, setFeedbackApi } from '@/utils/feedback'

const message = useMessage()
const dialog = useDialog()
const notification = useNotification()
const loadingBar = useLoadingBar()

setFeedbackApi({ message, dialog, notification, loadingBar })
onBeforeUnmount(clearFeedbackApi)
</script>

<template>
  <slot />
</template>

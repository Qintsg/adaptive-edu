/**
 * 对话框与抽屉兼容组件，统一限制移动端宽度。
 */
import { defineComponent, h } from 'vue'
import {
  NDrawer as NaiveDrawer,
  NDrawerContent as NaiveDrawerContent,
  NModal as NaiveModal
} from 'naive-ui'

/**
 * 规范化旧模板传入的对话框宽度。
 * :param {number|string|undefined} width - 宽度属性
 * :returns {string|undefined} CSS 宽度
 */
function resolveDialogWidth(width) {
  if (width === null || width === undefined || width === '') return undefined
  return typeof width === 'number' ? `${width}px` : width
}

export const NDialogAdapter = defineComponent({
  name: 'NDialog',
  inheritAttrs: false,
  props: ['modelValue', 'title', 'width', 'destroyOnClose'],
  emits: ['update:modelValue', 'close'],
  setup(props, { attrs, slots, emit }) {
    return () => h(NaiveModal, {
      ...attrs,
      show: props.modelValue,
      preset: 'card',
      title: props.title,
      style: {
        width: resolveDialogWidth(props.width),
        maxWidth: 'calc(100vw - 32px)',
        maxHeight: 'calc(100dvh - 32px)',
        overflowY: 'auto'
      },
      displayDirective: props.destroyOnClose ? 'if' : 'show',
      onUpdateShow: value => emit('update:modelValue', value),
      onClose: () => emit('close')
    }, slots)
  }
})

export const NDrawerAdapter = defineComponent({
  name: 'NDrawer',
  inheritAttrs: false,
  props: ['modelValue', 'show', 'title', 'size', 'width', 'destroyOnClose', 'direction'],
  emits: ['update:modelValue', 'update:show', 'close'],
  setup(props, { attrs, slots, emit }) {
    return () => h(NaiveDrawer, {
      ...attrs,
      show: props.show ?? props.modelValue,
      width: props.width || props.size,
      style: { maxWidth: 'calc(100vw - 16px)' },
      placement: props.direction === 'ltr' ? 'left' : 'right',
      displayDirective: props.destroyOnClose ? 'if' : 'show',
      onUpdateShow: value => {
        emit('update:show', value)
        emit('update:modelValue', value)
      },
      onClose: () => emit('close')
    }, {
      default: () => h(NaiveDrawerContent, { title: props.title, closable: true }, slots)
    })
  }
})

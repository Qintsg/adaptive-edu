/**
 * 旧版标签页模板与 Naive UI 标签页的兼容组件。
 * Naive UI 在渲染前读取直接子节点，因此需要先把兼容组件转换为 NTabPane。
 */
import { defineComponent, Fragment, h } from 'vue'
import { NTabPane as NaiveTabPane, NTabs as NaiveTabs } from 'naive-ui'

/**
 * 展开模板生成的 Fragment，但保留各标签页的内容插槽。
 * :param {Array|Object|undefined} nodes - 默认插槽节点
 * :returns {Array} 顶层节点
 */
function flattenTabNodes(nodes) {
  const entries = Array.isArray(nodes) ? nodes : nodes ? [nodes] : []
  return entries.flatMap(node => (
    node?.type === Fragment ? flattenTabNodes(node.children) : [node]
  ))
}

/**
 * 将兼容标签页节点转换为 Naive UI 可识别的直接子节点。
 * :param {Object} node - Vue 虚拟节点
 * :returns {Object} 标签页节点
 */
function toNaiveTabPane(node) {
  if (node?.type?.name !== 'NTabPane') return node
  const { label, ...paneProps } = node.props || {}
  return h(NaiveTabPane, {
    ...paneProps,
    key: node.key,
    tab: paneProps.tab ?? label
  }, node.children)
}

export const NTabsAdapter = defineComponent({
  name: 'NTabs',
  inheritAttrs: false,
  props: ['modelValue', 'value', 'type'],
  emits: ['update:modelValue', 'update:value', 'change'],
  setup(props, { attrs, slots, emit }) {
    return () => h(NaiveTabs, {
      ...attrs,
      value: props.value ?? props.modelValue,
      type: props.type === 'border-card' ? 'card' : props.type,
      onUpdateValue: value => {
        emit('update:modelValue', value)
        emit('update:value', value)
        emit('change', value)
      }
    }, {
      default: () => flattenTabNodes(slots.default?.()).map(toNaiveTabPane)
    })
  }
})

export const NTabPaneAdapter = defineComponent({
  name: 'NTabPane',
  inheritAttrs: false,
  props: ['name', 'label', 'tab', 'disabled', 'displayDirective'],
  setup(props, { attrs, slots }) {
    return () => h(NaiveTabPane, {
      ...attrs,
      name: props.name,
      tab: props.tab ?? props.label,
      disabled: props.disabled,
      displayDirective: props.displayDirective
    }, slots)
  }
})

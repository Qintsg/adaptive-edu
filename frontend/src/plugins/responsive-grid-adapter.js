/**
 * Element 风格的行列兼容组件。
 * 将 xs/sm/md/lg/xl 属性映射为响应式 CSS 网格跨度。
 */
import { defineComponent, h } from 'vue'

/**
 * 将列跨度约束在 1 到 24 之间。
 * :param {number|Object|undefined} value - 列跨度或带 span 的配置
 * :returns {number} 可用列跨度
 */
function normalizeSpan(value) {
  const rawValue = value && typeof value === 'object' ? value.span : value
  const span = Number(rawValue)
  return Number.isFinite(span) && span > 0 ? Math.min(24, Math.round(span)) : 24
}

/**
 * 生成各断点的列跨度，并向较大断点继承较小断点的值。
 * :param {Object} props - 行列组件属性
 * :returns {Object} CSS 自定义属性
 */
function buildColumnSpans(props) {
  return {
    '--adapter-col-xs': normalizeSpan(props.xs ?? props.span),
    '--adapter-col-sm': normalizeSpan(props.sm ?? props.xs ?? props.span),
    '--adapter-col-md': normalizeSpan(props.md ?? props.sm ?? props.xs ?? props.span),
    '--adapter-col-lg': normalizeSpan(props.lg ?? props.md ?? props.sm ?? props.xs ?? props.span),
    '--adapter-col-xl': normalizeSpan(props.xl ?? props.lg ?? props.md ?? props.sm ?? props.xs ?? props.span)
  }
}

export const NRowAdapter = defineComponent({
  name: 'NRow',
  inheritAttrs: false,
  props: ['gutter'],
  setup(props, { attrs, slots }) {
    return () => {
      const columnGap = Array.isArray(props.gutter) ? props.gutter[0] : props.gutter
      const rowGap = Array.isArray(props.gutter) ? props.gutter[1] ?? columnGap : columnGap
      return h('div', {
        ...attrs,
        class: ['n-row-adapter', attrs.class],
        style: {
          '--adapter-column-gap': `${columnGap || 0}px`,
          '--adapter-row-gap': `${rowGap || 0}px`,
          ...attrs.style
        }
      }, slots)
    }
  }
})

export const NColAdapter = defineComponent({
  name: 'NCol',
  inheritAttrs: false,
  props: ['span', 'xs', 'sm', 'md', 'lg', 'xl'],
  setup(props, { attrs, slots }) {
    return () => h('div', {
      ...attrs,
      class: ['n-col-adapter', attrs.class],
      style: { ...buildColumnSpans(props), ...attrs.style }
    }, slots)
  }
})

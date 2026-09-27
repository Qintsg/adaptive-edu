/**
 * Element 风格表格与分页的 Naive UI 兼容组件。
 * 保留列宽、空状态和操作列，并为窄屏提供独立横向滚动。
 */
import { defineComponent, Fragment, h } from 'vue'
import { NPagination as NaivePagination, NTable as NaiveTable } from 'naive-ui'

/**
 * 展开列定义中的 Fragment。
 * :param {Array|Object|undefined} nodes - 默认插槽节点
 * :returns {Array} 表格列节点
 */
function flattenColumns(nodes) {
  const entries = Array.isArray(nodes) ? nodes : nodes ? [nodes] : []
  return entries.flatMap(node => {
    if (node?.type === Fragment) return flattenColumns(node.children)
    if (Array.isArray(node?.children)) return flattenColumns(node.children)
    return node ? [node] : []
  })
}

/**
 * 将数字列宽转换为可用的像素宽度。
 * :param {unknown} value - 列宽属性
 * :param {number} fallback - 默认宽度
 * :returns {number} 像素宽度
 */
function toColumnWidth(value, fallback = 140) {
  const width = Number(value)
  return Number.isFinite(width) && width > 0 ? Math.max(60, width) : fallback
}

/**
 * 获取列的最低宽度。
 * :param {Object} column - 列节点
 * :returns {number} 最低宽度
 */
function getMinimumWidth(column) {
  const props = column.props || {}
  return toColumnWidth(props.minWidth ?? props['min-width'] ?? props.width)
}

/**
 * 渲染单元格内容，兼容模板插槽与旧格式化函数。
 * :param {Object} column - 列节点
 * :param {Object} row - 行数据
 * :param {number} index - 行序号
 * :returns {unknown} 单元格内容
 */
function renderCell(column, row, index) {
  if (column.children?.default) return column.children.default({ row, $index: index })
  if (column.props?.type === 'index') return index + 1
  const prop = column.props?.prop ?? column.props?.property
  const value = prop ? row?.[prop] : undefined
  if (column.props?.formatter) return column.props.formatter(row, column.props, value, index)
  return value ?? ''
}

/**
 * 为标题和数据单元格生成相同的宽度与对齐样式。
 * :param {Object} column - 列节点
 * :returns {Object} 样式对象
 */
function getCellStyle(column) {
  const props = column.props || {}
  return {
    width: props.width ? `${toColumnWidth(props.width)}px` : undefined,
    minWidth: `${getMinimumWidth(column)}px`,
    textAlign: props.align
  }
}

/**
 * 为固定列和长文本列添加样式标记。
 * :param {Object} column - 列节点
 * :returns {Array<string>} 单元格类名
 */
function getCellClasses(column) {
  const props = column.props || {}
  return [
    props.fixed === 'right' ? 'app-table-cell--fixed-right' : '',
    props.showOverflowTooltip || props['show-overflow-tooltip'] ? 'app-table-cell--ellipsis' : ''
  ].filter(Boolean)
}

export const NTableColumnAdapter = defineComponent({
  name: 'NTableColumn',
  props: ['prop', 'property', 'label', 'width', 'minWidth', 'align', 'formatter', 'type', 'fixed', 'showOverflowTooltip'],
  setup() {
    return () => null
  }
})

export const NTableAdapter = defineComponent({
  name: 'NTable',
  inheritAttrs: false,
  props: ['data', 'stripe', 'border', 'height', 'maxHeight', 'emptyText'],
  setup(props, { attrs, slots }) {
    return () => {
      const columns = flattenColumns(slots.default?.()).filter(node => node.type?.name === 'NTableColumn')
      const rows = Array.isArray(props.data) ? props.data : []
      const minimumTableWidth = columns.reduce((total, column) => total + getMinimumWidth(column), 0)
      const table = h(NaiveTable, {
        striped: props.stripe,
        bordered: props.border !== false,
        class: 'app-adapter-table',
        style: { width: '100%', minWidth: `${minimumTableWidth}px`, tableLayout: 'fixed' }
      }, {
        default: () => [
          h('thead', [h('tr', columns.map(column => h('th', {
            class: getCellClasses(column),
            style: getCellStyle(column)
          }, column.props?.label || '')))]),
          h('tbody', rows.length
            ? rows.map((row, rowIndex) => h('tr', { key: row.id ?? rowIndex }, columns.map(column => {
              const value = renderCell(column, row, rowIndex)
              return h('td', {
                class: getCellClasses(column),
                style: getCellStyle(column),
                title: typeof value === 'string' || typeof value === 'number' ? String(value) : undefined
              }, value)
            })))
            : [h('tr', [h('td', {
              colspan: Math.max(columns.length, 1), class: 'app-adapter-table__empty'
            }, slots.empty?.() || props.emptyText || '暂无数据')])])
        ]
      })
      return h('div', {
        ...attrs,
        class: ['app-table-scroll', attrs.class],
        tabindex: '0'
      }, [table])
    }
  }
})

export const NPaginationAdapter = defineComponent({
  name: 'NPagination',
  inheritAttrs: false,
  props: ['modelValue', 'currentPage', 'pageSize', 'total', 'pageSizes', 'layout'],
  emits: ['update:modelValue', 'update:currentPage', 'update:pageSize', 'current-change', 'size-change'],
  setup(props, { attrs, emit }) {
    return () => h(NaivePagination, {
      ...attrs,
      page: props.currentPage ?? props.modelValue,
      pageSize: props.pageSize,
      itemCount: props.total,
      pageSizes: props.pageSizes,
      showSizePicker: String(props.layout || '').includes('sizes'),
      onUpdatePage: value => {
        emit('update:modelValue', value)
        emit('update:currentPage', value)
        emit('current-change', value)
      },
      onUpdatePageSize: value => {
        emit('update:pageSize', value)
        emit('size-change', value)
      }
    })
  }
})

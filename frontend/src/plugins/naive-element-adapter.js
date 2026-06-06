import { defineComponent, h, Fragment, ref } from 'vue'
import {
  NAlert as NaiveAlert,
  NAvatar as NaiveAvatar,
  NButton as NaiveButton,
  NButtonGroup as NaiveButtonGroup,
  NCard as NaiveCard,
  NCheckbox as NaiveCheckbox,
  NCheckboxGroup as NaiveCheckboxGroup,
  NCollapse as NaiveCollapse,
  NCollapseItem as NaiveCollapseItem,
  NDatePicker as NaiveDatePicker,
  NDescriptions as NaiveDescriptions,
  NDescriptionsItem as NaiveDescriptionsItem,
  NDivider as NaiveDivider,
  NDropdown as NaiveDropdown,
  NDrawer as NaiveDrawer,
  NDrawerContent as NaiveDrawerContent,
  NEmpty as NaiveEmpty,
  NForm as NaiveForm,
  NFormItem as NaiveFormItem,
  NIcon as NaiveIcon,
  NInput as NaiveInput,
  NInputGroup as NaiveInputGroup,
  NInputNumber as NaiveInputNumber,
  NMenu as NaiveMenu,
  NModal as NaiveModal,
  NPageHeader as NaivePageHeader,
  NPagination as NaivePagination,
  NProgress as NaiveProgress,
  NRadio as NaiveRadio,
  NRadioGroup as NaiveRadioGroup,
  NScrollbar as NaiveScrollbar,
  NSelect as NaiveSelect,
  NSkeleton as NaiveSkeleton,
  NSpace as NaiveSpace,
  NStatistic as NaiveStatistic,
  NSwitch as NaiveSwitch,
  NTabPane as NaiveTabPane,
  NTable as NaiveTable,
  NTabs as NaiveTabs,
  NTag as NaiveTag,
  NTimeline as NaiveTimeline,
  NTimelineItem as NaiveTimelineItem,
  NTooltip as NaiveTooltip,
  NTree as NaiveTree,
  NUpload as NaiveUpload
} from 'naive-ui'

const typeMap = {
  danger: 'error',
  default: 'default',
  info: 'info',
  primary: 'primary',
  success: 'success',
  warning: 'warning'
}

function mapType(type) {
  return typeMap[type] || type || 'default'
}

function toArray(nodes) {
  return Array.isArray(nodes) ? nodes : nodes ? [nodes] : []
}

function flattenVNodes(nodes) {
  return toArray(nodes).flatMap(node => {
    if (node?.type === Fragment) return flattenVNodes(node.children)
    if (Array.isArray(node?.children)) return flattenVNodes(node.children)
    return node ? [node] : []
  })
}

function readModelValue(props) {
  return props.value ?? props.modelValue ?? props.show ?? props.currentPage
}

function emitModel(emit, value) {
  emit('update:modelValue', value)
  emit('update:value', value)
}

function readFileFromUploadInfo(fileInfo) {
  return fileInfo?.raw ?? fileInfo?.file ?? null
}

function toElementUploadFile(fileInfo) {
  if (!fileInfo || typeof fileInfo !== 'object') return fileInfo
  const rawFile = readFileFromUploadInfo(fileInfo)
  return {
    ...fileInfo,
    file: rawFile,
    raw: rawFile,
    name: fileInfo.name ?? rawFile?.name ?? '',
    size: fileInfo.size ?? rawFile?.size ?? 0,
    type: fileInfo.type ?? rawFile?.type ?? ''
  }
}

function normalizeUploadFileList(fileList) {
  return Array.isArray(fileList) ? fileList.map(toElementUploadFile) : []
}

function renderIcon(component) {
  if (!component) return undefined
  return () => h(NaiveIcon, null, { default: () => h(component) })
}

const NButtonAdapter = defineComponent({
  name: 'NButton',
  inheritAttrs: false,
  props: ['type', 'size', 'loading', 'disabled', 'plain', 'link', 'text', 'round', 'circle', 'icon'],
  emits: ['click'],
  setup(props, { attrs, slots, emit }) {
    return () => h(NaiveButton, {
      ...attrs,
      type: mapType(props.type),
      size: props.size,
      loading: props.loading,
      disabled: props.disabled,
      ghost: props.plain,
      text: props.link || props.text,
      round: props.round,
      circle: props.circle,
      renderIcon: renderIcon(props.icon),
      onClick: event => emit('click', event)
    }, slots)
  }
})

const NCardAdapter = defineComponent({
  name: 'NCard',
  inheritAttrs: false,
  props: ['shadow'],
  setup(_props, { attrs, slots }) {
    return () => h(NaiveCard, { ...attrs, embedded: false, bordered: true }, slots)
  }
})

const NFormAdapter = defineComponent({
  name: 'NForm',
  inheritAttrs: false,
  props: ['model', 'rules', 'labelWidth', 'labelPosition', 'labelPlacement', 'inline'],
  setup(props, { attrs, slots, expose }) {
    const formRef = ref(null)
    expose({
      validate: (...args) => formRef.value?.validate?.(...args),
      validateItem: (...args) => formRef.value?.validateItem?.(...args),
      restoreValidation: (...args) => formRef.value?.restoreValidation?.(...args)
    })
    return () => h(NaiveForm, {
      ref: formRef,
      ...attrs,
      model: props.model,
      rules: props.rules,
      labelWidth: props.labelWidth,
      labelPlacement: props.labelPlacement || (props.labelPosition === 'top' ? 'top' : 'left'),
      inline: props.inline
    }, slots)
  }
})

const NFormItemAdapter = defineComponent({
  name: 'NFormItem',
  inheritAttrs: false,
  props: ['label', 'prop', 'path', 'required'],
  setup(props, { attrs, slots }) {
    return () => h(NaiveFormItem, {
      ...attrs,
      label: props.label,
      path: props.path || props.prop,
      required: props.required
    }, slots)
  }
})

const NInputAdapter = defineComponent({
  name: 'NInput',
  inheritAttrs: false,
  props: ['modelValue', 'value', 'type', 'rows', 'disabled', 'placeholder', 'clearable', 'size', 'autosize', 'showPasswordOn'],
  emits: ['update:modelValue', 'update:value', 'input', 'change', 'keyup'],
  setup(props, { attrs, slots, emit }) {
    return () => h(NaiveInput, {
      ...attrs,
      value: props.value ?? props.modelValue,
      type: props.type,
      disabled: props.disabled,
      placeholder: props.placeholder,
      clearable: props.clearable,
      size: props.size,
      autosize: props.autosize || (props.rows ? { minRows: Number(props.rows) } : undefined),
      showPasswordOn: props.showPasswordOn || (props.type === 'password' ? 'click' : undefined),
      onUpdateValue: value => emitModel(emit, value),
      onInput: value => emit('input', value),
      onChange: value => emit('change', value),
      onKeyup: event => emit('keyup', event)
    }, slots)
  }
})

const NInputNumberAdapter = defineComponent({
  name: 'NInputNumber',
  inheritAttrs: false,
  props: ['modelValue', 'value', 'min', 'max', 'step', 'size', 'disabled'],
  emits: ['update:modelValue', 'update:value'],
  setup(props, { attrs, emit }) {
    return () => h(NaiveInputNumber, {
      ...attrs,
      value: props.value ?? props.modelValue,
      min: props.min,
      max: props.max,
      step: props.step,
      size: props.size,
      disabled: props.disabled,
      onUpdateValue: value => emitModel(emit, value)
    })
  }
})

const NDatePickerAdapter = defineComponent({
  name: 'NDatePicker',
  inheritAttrs: false,
  props: [
    'modelValue',
    'value',
    'formattedValue',
    'type',
    'format',
    'valueFormat',
    'rangeSeparator',
    'startPlaceholder',
    'endPlaceholder',
    'placeholder',
    'clearable',
    'disabled',
    'size'
  ],
  emits: ['update:modelValue', 'update:value', 'update:formattedValue', 'change'],
  setup(props, { attrs, slots, emit }) {
    return () => {
      const { onChange: _deprecatedOnChange, ...safeAttrs } = attrs
      const usesFormattedValue = Boolean(props.valueFormat)
      const currentValue = readModelValue(props)
      const updateModel = (value, formattedValue) => {
        const nextValue = usesFormattedValue ? formattedValue : value
        emit('update:modelValue', nextValue)
        emit('update:value', nextValue)
        emit('update:formattedValue', formattedValue)
        emit('change', nextValue)
      }

      return h(NaiveDatePicker, {
        ...safeAttrs,
        type: props.type,
        format: props.format,
        valueFormat: props.valueFormat,
        separator: props.rangeSeparator,
        startPlaceholder: props.startPlaceholder,
        endPlaceholder: props.endPlaceholder,
        placeholder: props.placeholder,
        clearable: props.clearable,
        disabled: props.disabled,
        size: props.size,
        value: usesFormattedValue ? undefined : currentValue,
        formattedValue: usesFormattedValue ? (props.formattedValue ?? currentValue) : props.formattedValue,
        onUpdateValue: updateModel,
        onUpdateFormattedValue: formattedValue => {
          emit('update:modelValue', formattedValue)
          emit('update:value', formattedValue)
          emit('update:formattedValue', formattedValue)
          emit('change', formattedValue)
        }
      }, slots)
    }
  }
})

const NOptionAdapter = defineComponent({
  name: 'NOption',
  props: ['label', 'value', 'disabled'],
  setup() {
    return () => null
  }
})

const NSelectAdapter = defineComponent({
  name: 'NSelect',
  inheritAttrs: false,
  props: ['modelValue', 'value', 'options', 'placeholder', 'clearable', 'disabled', 'size', 'multiple'],
  emits: ['update:modelValue', 'update:value', 'change'],
  setup(props, { attrs, slots, emit }) {
    const extractOptions = () => flattenVNodes(slots.default?.()).map(node => ({
      label: node.props?.label ?? node.children,
      value: node.props?.value,
      disabled: node.props?.disabled
    })).filter(option => option.value !== undefined)

    return () => h(NaiveSelect, {
      ...attrs,
      value: props.value ?? props.modelValue,
      options: props.options || extractOptions(),
      placeholder: props.placeholder,
      clearable: props.clearable,
      disabled: props.disabled,
      size: props.size,
      multiple: props.multiple,
      onUpdateValue: value => {
        emitModel(emit, value)
        emit('change', value)
      }
    })
  }
})

const NTagAdapter = defineComponent({
  name: 'NTag',
  inheritAttrs: false,
  props: ['type', 'size', 'effect', 'closable'],
  setup(props, { attrs, slots }) {
    return () => h(NaiveTag, {
      ...attrs,
      type: mapType(props.type),
      size: props.size,
      bordered: props.effect !== 'plain',
      closable: props.closable
    }, slots)
  }
})

const NValueGroupAdapter = (name, Component) => defineComponent({
  name,
  inheritAttrs: false,
  props: ['modelValue', 'value', 'disabled'],
  emits: ['update:modelValue', 'update:value', 'change'],
  setup(props, { attrs, slots, emit }) {
    return () => h(Component, {
      ...attrs,
      value: props.value ?? props.modelValue,
      disabled: props.disabled,
      onUpdateValue: value => {
        emitModel(emit, value)
        emit('change', value)
      }
    }, slots)
  }
})

const NRadioGroupAdapter = NValueGroupAdapter('NRadioGroup', NaiveRadioGroup)
const NCheckboxGroupAdapter = NValueGroupAdapter('NCheckboxGroup', NaiveCheckboxGroup)

const NTabsAdapter = defineComponent({
  name: 'NTabs',
  inheritAttrs: false,
  props: ['modelValue', 'value', 'type'],
  emits: ['update:modelValue', 'update:value', 'change'],
  setup(props, { attrs, slots, emit }) {
    const mappedType = () => {
      if (props.type === 'border-card') return 'card'
      return props.type
    }
    return () => h(NaiveTabs, {
      ...attrs,
      value: props.value ?? props.modelValue,
      type: mappedType(),
      onUpdateValue: value => {
        emitModel(emit, value)
        emit('change', value)
      }
    }, slots)
  }
})

const NDialogAdapter = defineComponent({
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
      style: props.width ? { width: typeof props.width === 'number' ? `${props.width}px` : props.width } : undefined,
      displayDirective: props.destroyOnClose ? 'if' : 'show',
      onUpdateShow: value => emit('update:modelValue', value),
      onClose: () => emit('close')
    }, slots)
  }
})

const NDrawerAdapter = defineComponent({
  name: 'NDrawer',
  inheritAttrs: false,
  props: ['modelValue', 'show', 'title', 'size', 'width', 'destroyOnClose', 'direction'],
  emits: ['update:modelValue', 'update:show', 'close'],
  setup(props, { attrs, slots, emit }) {
    const width = props.width || props.size
    return () => h(NaiveDrawer, {
      ...attrs,
      show: props.show ?? props.modelValue,
      width,
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

const NTableColumnAdapter = defineComponent({
  name: 'NTableColumn',
  props: ['prop', 'property', 'label', 'width', 'minWidth', 'align', 'formatter', 'type', 'fixed'],
  setup() {
    return () => null
  }
})

function renderCell(column, row, index) {
  if (column.children?.default) return column.children.default({ row, $index: index })
  if (column.props?.type === 'index') return index + 1
  const prop = column.props?.prop ?? column.props?.property
  const value = prop ? row?.[prop] : undefined
  if (column.props?.formatter) return column.props.formatter(row, column.props, value, index)
  return value ?? ''
}

const NTableAdapter = defineComponent({
  name: 'NTable',
  inheritAttrs: false,
  props: ['data', 'stripe', 'border', 'height', 'maxHeight'],
  setup(props, { attrs, slots }) {
    return () => {
      const columns = flattenVNodes(slots.default?.()).filter(node => node.type?.name === 'NTableColumn')
      const rows = props.data || []
      return h(NaiveTable, { ...attrs, striped: props.stripe, bordered: props.border !== false, class: 'app-adapter-table' }, {
        default: () => [
          h('thead', [h('tr', columns.map(column => h('th', {
            style: {
              width: column.props?.width ? `${column.props.width}px` : undefined,
              textAlign: column.props?.align
            }
          }, column.props?.label || '')))]),
          h('tbody', rows.length
            ? rows.map((row, rowIndex) => h('tr', { key: row.id ?? rowIndex }, columns.map(column => h('td', {
              style: { textAlign: column.props?.align }
            }, renderCell(column, row, rowIndex)))))
            : [h('tr', [h('td', { colspan: Math.max(columns.length, 1), class: 'app-adapter-table__empty' }, slots.empty?.() || '暂无数据')])])
        ]
      })
    }
  }
})

const NRowAdapter = defineComponent({
  name: 'NRow',
  inheritAttrs: false,
  props: ['gutter'],
  setup(props, { attrs, slots }) {
    const gap = Array.isArray(props.gutter) ? props.gutter[0] : props.gutter
    return () => h('div', { ...attrs, class: ['n-row-adapter', attrs.class], style: { '--adapter-row-gap': `${gap || 0}px`, ...attrs.style } }, slots)
  }
})

const NColAdapter = defineComponent({
  name: 'NCol',
  inheritAttrs: false,
  props: ['span', 'xs', 'sm', 'md', 'lg', 'xl'],
  setup(props, { attrs, slots }) {
    const span = props.span || props.md || props.sm || props.xs || 24
    return () => h('div', {
      ...attrs,
      class: ['n-col-adapter', attrs.class],
      style: { '--adapter-col-span': Number(span), ...attrs.style }
    }, slots)
  }
})

const NPaginationAdapter = defineComponent({
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

const NSwitchAdapter = defineComponent({
  name: 'NSwitch',
  inheritAttrs: false,
  props: ['modelValue', 'value', 'disabled'],
  emits: ['update:modelValue', 'update:value', 'change'],
  setup(props, { attrs, emit }) {
    return () => h(NaiveSwitch, {
      ...attrs,
      value: props.value ?? props.modelValue,
      disabled: props.disabled,
      onUpdateValue: value => {
        emitModel(emit, value)
        emit('change', value)
      }
    })
  }
})

const NUploadAdapter = defineComponent({
  name: 'NUpload',
  inheritAttrs: false,
  setup(_props, { attrs, slots }) {
    return () => {
      const {
        beforeUpload,
        onBeforeUpload,
        onChange,
        onRemove,
        fileList,
        ...safeAttrs
      } = attrs
      const normalizeOptions = options => ({
        ...options,
        file: toElementUploadFile(options?.file),
        fileList: normalizeUploadFileList(options?.fileList)
      })
      const handleBeforeUpload = options => {
        const normalized = normalizeOptions(options)
        const legacyHandler = beforeUpload || onBeforeUpload
        return legacyHandler ? legacyHandler(normalized.file, normalized.fileList) : true
      }
      const handleChange = options => {
        const normalized = normalizeOptions(options)
        onChange?.(normalized.file, normalized.fileList, normalized)
      }
      const handleRemove = options => {
        const normalized = normalizeOptions(options)
        return onRemove ? onRemove(normalized.file, normalized.fileList, normalized) : true
      }
      return h('div', { class: 'app-upload-adapter' }, [
        h(NaiveUpload, {
          ...safeAttrs,
          fileList,
          beforeUpload: handleBeforeUpload,
          onBeforeUpload: handleBeforeUpload,
          onChange: handleChange,
          onRemove: handleRemove
        }, slots),
        slots.tip ? h('div', { class: 'app-upload-adapter__tip' }, slots.tip()) : null
      ])
    }
  }
})

const NTreeAdapter = defineComponent({
  name: 'NTree',
  inheritAttrs: false,
  props: ['data', 'props', 'nodeKey', 'defaultExpandAll'],
  emits: ['node-click'],
  setup(props, { attrs, emit }) {
    const findNode = (items, key, keyField) => {
      for (const item of items || []) {
        if (item?.[keyField] === key) return item
        const found = findNode(item?.[props.props?.children || 'children'], key, keyField)
        if (found) return found
      }
      return null
    }
    return () => {
      const keyField = props.nodeKey || 'id'
      const labelField = props.props?.label || 'label'
      const childrenField = props.props?.children || 'children'
      return h(NaiveTree, {
        ...attrs,
        data: props.data,
        keyField,
        labelField,
        childrenField,
        defaultExpandAll: props.defaultExpandAll,
        selectable: true,
        blockLine: true,
        onUpdateSelectedKeys: keys => {
          const node = findNode(props.data, keys?.[0], keyField)
          if (node) emit('node-click', node)
        }
      })
    }
  }
})

const NTabPaneAdapter = defineComponent({
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

function createSemanticAdapter(tagName) {
  return defineComponent({
    name: tagName,
    inheritAttrs: false,
    props: ['height'],
    setup(props, { attrs, slots }) {
      return () => h(tagName.toLowerCase().replace(/^n/, ''), {
        ...attrs,
        style: {
          ...(props.height ? { height: props.height } : {}),
          ...attrs.style
        }
      }, slots)
    }
  })
}

const simpleAdapters = {
  NAlert: NaiveAlert,
  NAvatar: NaiveAvatar,
  NButtonGroup: NaiveButtonGroup,
  NCheckbox: NaiveCheckbox,
  NCollapse: NaiveCollapse,
  NCollapseItem: NaiveCollapseItem,
  NDescriptions: NaiveDescriptions,
  NDescriptionsItem: NaiveDescriptionsItem,
  NDivider: NaiveDivider,
  NDrawerContent: NaiveDrawerContent,
  NDropdown: NaiveDropdown,
  NEmpty: NaiveEmpty,
  NIcon: NaiveIcon,
  NInputGroup: NaiveInputGroup,
  NMenu: NaiveMenu,
  NPageHeader: NaivePageHeader,
  NProgress: NaiveProgress,
  NRadio: NaiveRadio,
  NScrollbar: NaiveScrollbar,
  NSkeleton: NaiveSkeleton,
  NSkeletonItem: NaiveSkeleton,
  NSpace: NaiveSpace,
  NStatistic: NaiveStatistic,
  NTimeline: NaiveTimeline,
  NTimelineItem: NaiveTimelineItem,
  NTooltip: NaiveTooltip
}

const adapters = {
  ...simpleAdapters,
  NButton: NButtonAdapter,
  NCard: NCardAdapter,
  NCheckboxGroup: NCheckboxGroupAdapter,
  NCol: NColAdapter,
  NContainer: createSemanticAdapter('NDiv'),
  NDatePicker: NDatePickerAdapter,
  NDialog: NDialogAdapter,
  NDrawer: NDrawerAdapter,
  NFooter: createSemanticAdapter('NFooter'),
  NForm: NFormAdapter,
  NFormItem: NFormItemAdapter,
  NHeader: createSemanticAdapter('NHeader'),
  NInput: NInputAdapter,
  NInputNumber: NInputNumberAdapter,
  NMain: createSemanticAdapter('NMain'),
  NOption: NOptionAdapter,
  NPagination: NPaginationAdapter,
  NRadioGroup: NRadioGroupAdapter,
  NRow: NRowAdapter,
  NSelect: NSelectAdapter,
  NSwitch: NSwitchAdapter,
  NTabs: NTabsAdapter,
  NTabPane: NTabPaneAdapter,
  NTable: NTableAdapter,
  NTableColumn: NTableColumnAdapter,
  NTag: NTagAdapter,
  NTree: NTreeAdapter,
  NUpload: NUploadAdapter
}

const loadingStyle = `
.app-loading-host {
  position: relative;
}
.app-loading-overlay {
  position: absolute;
  inset: 0;
  z-index: 3000;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--primary-color, #0f6cbd);
  background: rgba(255, 255, 255, 0.74);
  backdrop-filter: blur(2px);
}
.app-loading-overlay.is-fullscreen {
  position: fixed;
}
.app-loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid rgba(15, 108, 189, 0.18);
  border-top-color: var(--primary-color, #0f6cbd);
  border-radius: 50%;
  animation: app-loading-spin 0.8s linear infinite;
}
.app-loading-text {
  max-width: 520px;
  padding: 0 24px;
  color: var(--text-secondary, #616161);
  font-size: 14px;
  line-height: 1.6;
  text-align: center;
}
@keyframes app-loading-spin {
  to {
    transform: rotate(360deg);
  }
}
`

function ensureLoadingStyle() {
  if (typeof document === 'undefined' || document.getElementById('app-loading-directive-style')) return
  const style = document.createElement('style')
  style.id = 'app-loading-directive-style'
  style.textContent = loadingStyle
  document.head.appendChild(style)
}

function getLoadingText(el) {
  return el.getAttribute('element-loading-text') || el.getAttribute('data-element-loading-text') || ''
}

function removeLoadingOverlay(el) {
  const state = el.__appLoadingState
  if (!state) return
  state.overlay.remove()
  if (state.target === el && state.restorePosition) {
    el.style.position = state.originalPosition
  }
  if (state.target === el) {
    el.classList.remove('app-loading-host')
  }
  delete el.__appLoadingState
}

function updateLoading(el, binding) {
  const active = Boolean(binding.value)
  if (!active) {
    removeLoadingOverlay(el)
    return
  }
  ensureLoadingStyle()
  const fullscreen = Boolean(binding.modifiers?.fullscreen)
  const target = fullscreen ? document.body : el
  if (el.__appLoadingState) {
    const textNode = el.__appLoadingState.overlay.querySelector('.app-loading-text')
    if (textNode) textNode.textContent = getLoadingText(el)
    return
  }
  const overlay = document.createElement('div')
  overlay.className = fullscreen ? 'app-loading-overlay is-fullscreen' : 'app-loading-overlay'
  overlay.innerHTML = `<span class="app-loading-spinner"></span><span class="app-loading-text"></span>`
  overlay.querySelector('.app-loading-text').textContent = getLoadingText(el)

  const originalPosition = el.style.position
  const restorePosition = !fullscreen && getComputedStyle(el).position === 'static'
  if (!fullscreen) {
    el.classList.add('app-loading-host')
    if (restorePosition) el.style.position = 'relative'
  }
  target.appendChild(overlay)
  el.__appLoadingState = { overlay, target, originalPosition, restorePosition }
}

const loadingDirective = {
  mounted: updateLoading,
  updated: updateLoading,
  beforeUnmount: removeLoadingOverlay
}

export function installNaiveElementAdapter(app) {
  for (const [name, component] of Object.entries(adapters)) {
    app.component(name, component)
  }
  app.directive('loading', loadingDirective)
}

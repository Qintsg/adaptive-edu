/** Naive UI 与旧版 Element 风格模板的兼容注册入口。 */
import { defineComponent, h, ref } from 'vue'
import { NColAdapter, NRowAdapter } from './responsive-grid-adapter'
import { loadingDirective } from './loading-directive'
import { NTabPaneAdapter, NTabsAdapter } from './tabs-adapter'
import { NPaginationAdapter, NTableAdapter, NTableColumnAdapter } from './table-adapter'
import { NDialogAdapter, NDrawerAdapter } from './overlay-adapter'
import { NOptionAdapter, NSelectAdapter } from './select-adapter'
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
  NDrawerContent as NaiveDrawerContent,
  NEmpty as NaiveEmpty,
  NForm as NaiveForm,
  NFormItem as NaiveFormItem,
  NIcon as NaiveIcon,
  NInput as NaiveInput,
  NInputGroup as NaiveInputGroup,
  NInputNumber as NaiveInputNumber,
  NMenu as NaiveMenu,
  NPageHeader as NaivePageHeader,
  NProgress as NaiveProgress,
  NRadio as NaiveRadio,
  NRadioGroup as NaiveRadioGroup,
  NScrollbar as NaiveScrollbar,
  NSkeleton as NaiveSkeleton,
  NSpace as NaiveSpace,
  NStatistic as NaiveStatistic,
  NSwitch as NaiveSwitch,
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

export function installNaiveElementAdapter(app) {
  for (const [name, component] of Object.entries(adapters)) {
    app.component(name, component)
  }
  app.directive('loading', loadingDirective)
}

/**
 * Element 风格下拉选项与 Naive UI Select 的兼容组件。
 */
import { defineComponent, h } from 'vue'
import { NSelect as NaiveSelect } from 'naive-ui'
import { flattenVNodes } from './adapter-vnodes'

/**
 * 从旧模板的选项节点提取 Naive UI 选项。
 * :param {Function|undefined} defaultSlot - 默认插槽
 * :returns {Array} 选项数组
 */
function extractOptions(defaultSlot) {
  return flattenVNodes(defaultSlot?.()).map(node => ({
    label: node.props?.label ?? node.children,
    value: node.props?.value,
    disabled: node.props?.disabled
  })).filter(option => option.value !== undefined)
}

export const NOptionAdapter = defineComponent({
  name: 'NOption',
  props: ['label', 'value', 'disabled'],
  setup() {
    return () => null
  }
})

export const NSelectAdapter = defineComponent({
  name: 'NSelect',
  inheritAttrs: false,
  props: ['modelValue', 'value', 'options', 'placeholder', 'clearable', 'disabled', 'size', 'multiple'],
  emits: ['update:modelValue', 'update:value', 'change'],
  setup(props, { attrs, slots, emit }) {
    return () => {
      const selectedValue = props.value ?? props.modelValue
      return h(NaiveSelect, {
        ...attrs,
        value: selectedValue === '' ? null : selectedValue,
        options: props.options || extractOptions(slots.default),
        placeholder: props.placeholder,
        clearable: props.clearable,
        disabled: props.disabled,
        size: props.size,
        multiple: props.multiple,
        onUpdateValue: value => {
          emit('update:modelValue', value)
          emit('update:value', value)
          emit('change', value)
        }
      })
    }
  }
})

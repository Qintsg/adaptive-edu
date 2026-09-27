/**
 * 兼容适配器共用的顶层虚拟节点展开工具。
 */
import { Fragment } from 'vue'

/**
 * 将插槽结果转换为节点数组。
 * :param {Array|Object|undefined} nodes - 插槽结果
 * :returns {Array} 节点数组
 */
function toArray(nodes) {
  return Array.isArray(nodes) ? nodes : nodes ? [nodes] : []
}

/**
 * 展开 Fragment 与数组子节点。
 * :param {Array|Object|undefined} nodes - 插槽结果
 * :returns {Array} 叶节点数组
 */
export function flattenVNodes(nodes) {
  return toArray(nodes).flatMap(node => {
    if (node?.type === Fragment) return flattenVNodes(node.children)
    if (Array.isArray(node?.children)) return flattenVNodes(node.children)
    return node ? [node] : []
  })
}

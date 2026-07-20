import type { SymbolDescriptor } from '../types/mklink'

export interface SymbolTreeNode {
  key: string
  label: string
  kind: 'branch' | 'leaf'
  descriptor: SymbolDescriptor | null
  children: SymbolTreeNode[]
  leafCount: number
}

export interface VisibleSymbolRow {
  node: SymbolTreeNode
  depth: number
  expanded: boolean
  selectedLeafCount: number
}

export interface VisibleSymbolOptions {
  expanded: ReadonlySet<string>
  selected: ReadonlySet<string>
  query: string
  selectedOnly: boolean
}

interface MutableSymbolTreeNode extends SymbolTreeNode {
  childIndex: Map<string, MutableSymbolTreeNode>
  children: MutableSymbolTreeNode[]
}

function pathTokens(path: string): string[] {
  return path.match(/[^.[\]]+|\[\d+\]/g) ?? [path]
}

function appendPath(parent: string, token: string): string {
  if (!parent) return token
  return token.startsWith('[') ? `${parent}${token}` : `${parent}.${token}`
}

function createNode(key: string, label: string, descriptor: SymbolDescriptor | null): MutableSymbolTreeNode {
  return {
    key,
    label,
    kind: descriptor ? 'leaf' : 'branch',
    descriptor,
    children: [],
    childIndex: new Map(),
    leafCount: descriptor ? 1 : 0,
  }
}

function finalizeNode(node: MutableSymbolTreeNode): SymbolTreeNode {
  const children = node.children.map(finalizeNode)
  return {
    key: node.key,
    label: node.label,
    kind: node.kind,
    descriptor: node.descriptor,
    children,
    leafCount: node.kind === 'leaf'
      ? 1
      : children.reduce((total, child) => total + child.leafCount, 0),
  }
}

export function buildSymbolTree(items: readonly SymbolDescriptor[]): SymbolTreeNode[] {
  const roots: MutableSymbolTreeNode[] = []
  const rootIndex = new Map<string, MutableSymbolTreeNode>()

  for (const descriptor of items) {
    const tokens = pathTokens(descriptor.path)
    let parentKey = ''
    let siblings = roots
    let siblingIndex = rootIndex

    tokens.forEach((token, index) => {
      const key = appendPath(parentKey, token)
      const isLeaf = index === tokens.length - 1
      let node = siblingIndex.get(key)
      if (!node) {
        node = createNode(key, token, isLeaf ? descriptor : null)
        siblingIndex.set(key, node)
        siblings.push(node)
      }
      parentKey = key
      siblings = node.children
      siblingIndex = node.childIndex
    })
  }

  return roots.map(finalizeNode)
}

export function visibleSymbolRows(
  roots: readonly SymbolTreeNode[],
  options: VisibleSymbolOptions,
): VisibleSymbolRow[] {
  const query = options.query.trim().toLocaleLowerCase()
  const forceExpanded = Boolean(query) || options.selectedOnly
  const visible = new Map<string, boolean>()
  const selectedCounts = new Map<string, number>()

  function isVisible(node: SymbolTreeNode): boolean {
    const cached = visible.get(node.key)
    if (cached !== undefined) return cached
    let result: boolean
    if (node.kind === 'leaf') {
      const descriptor = node.descriptor
      const selectedMatch = !options.selectedOnly || options.selected.has(node.key)
      const queryMatch = !query || Boolean(
        descriptor
        && (descriptor.path.toLocaleLowerCase().includes(query)
          || descriptor.type_name.toLocaleLowerCase().includes(query)),
      )
      result = selectedMatch && queryMatch
    } else {
      result = node.children.some(isVisible)
    }
    visible.set(node.key, result)
    return result
  }

  function selectedLeafCount(node: SymbolTreeNode): number {
    const cached = selectedCounts.get(node.key)
    if (cached !== undefined) return cached
    const count = node.kind === 'leaf'
      ? Number(options.selected.has(node.key))
      : node.children.reduce((total, child) => total + selectedLeafCount(child), 0)
    selectedCounts.set(node.key, count)
    return count
  }

  const rows: VisibleSymbolRow[] = []
  function appendVisible(node: SymbolTreeNode, depth: number): void {
    if (!isVisible(node)) return
    const expanded = node.kind === 'branch' && (forceExpanded || options.expanded.has(node.key))
    rows.push({
      node,
      depth,
      expanded,
      selectedLeafCount: selectedLeafCount(node),
    })
    if (!expanded) return
    node.children.forEach(child => appendVisible(child, depth + 1))
  }

  roots.forEach(root => appendVisible(root, 0))
  return rows
}

export function collectBranchKeys(roots: readonly SymbolTreeNode[]): Set<string> {
  const keys = new Set<string>()
  function visit(node: SymbolTreeNode): void {
    if (node.kind !== 'branch') return
    keys.add(node.key)
    node.children.forEach(visit)
  }
  roots.forEach(visit)
  return keys
}

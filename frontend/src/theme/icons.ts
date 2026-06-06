import { h, type Component } from 'vue'
import { NIcon } from 'naive-ui'
import {
  Add24Regular,
  ArrowLeft24Regular,
  AppsList24Regular,
  ArrowSync24Regular,
  ArrowUpload24Regular,
  Board24Regular,
  BookOpen24Regular,
  Bot24Regular,
  Chat24Regular,
  CheckmarkCircle24Regular,
  ChevronDown24Regular,
  Copy24Regular,
  DataBarVertical24Regular,
  Delete24Regular,
  DismissCircle24Regular,
  Document24Regular,
  Edit24Regular,
  ErrorCircle24Regular,
  Eye24Regular,
  EyeOff24Regular,
  Filter24Regular,
  FolderOpen24Regular,
  HatGraduation24Regular,
  Home24Regular,
  Info24Regular,
  Key24Regular,
  Link24Regular,
  List24Regular,
  LockClosed24Regular,
  Mail24Regular,
  Navigation24Regular,
  Notebook24Regular,
  People24Regular,
  Person24Regular,
  Save24Regular,
  Search24Regular,
  Settings24Regular,
  Share24Regular,
  SignOut24Regular,
  Sparkle24Regular,
  TaskListAdd24Regular,
  Trophy24Regular,
  Video24Regular,
  Wand24Regular,
  Warning24Regular
} from '@vicons/fluent'

export const appIcons = {
  Add: Add24Regular,
  ArrowLeft: ArrowLeft24Regular,
  Back: ArrowLeft24Regular,
  AppsList: AppsList24Regular,
  ArrowSync: ArrowSync24Regular,
  Upload: ArrowUpload24Regular,
  Board: Board24Regular,
  Reading: BookOpen24Regular,
  ChatDotRound: Chat24Regular,
  CheckCircle: CheckmarkCircle24Regular,
  ChevronDown: ChevronDown24Regular,
  Copy: Copy24Regular,
  DataAnalysis: DataBarVertical24Regular,
  DataBoard: DataBarVertical24Regular,
  Delete: Delete24Regular,
  DismissCircle: DismissCircle24Regular,
  Document: Document24Regular,
  Edit: Edit24Regular,
  ErrorCircle: ErrorCircle24Regular,
  Eye: Eye24Regular,
  EyeOff: EyeOff24Regular,
  Files: AppsList24Regular,
  Filter: Filter24Regular,
  FolderOpened: FolderOpen24Regular,
  Guide: Navigation24Regular,
  Home: Home24Regular,
  House: Home24Regular,
  Info: Info24Regular,
  Key: Key24Regular,
  Link: Link24Regular,
  List: List24Regular,
  Lock: LockClosed24Regular,
  Mail: Mail24Regular,
  MagicStick: Wand24Regular,
  Notebook: Notebook24Regular,
  People: People24Regular,
  Plus: Add24Regular,
  Question: TaskListAdd24Regular,
  ReadingList: BookOpen24Regular,
  Save: Save24Regular,
  School: HatGraduation24Regular,
  Search: Search24Regular,
  Setting: Settings24Regular,
  Settings: Settings24Regular,
  Share: Share24Regular,
  SignOut: SignOut24Regular,
  Sparkle: Sparkle24Regular,
  Task: TaskListAdd24Regular,
  Trophy: Trophy24Regular,
  User: Person24Regular,
  Video: Video24Regular,
  Warning: Warning24Regular,
  Bot: Bot24Regular
} satisfies Record<string, Component>

export type AppIconName = keyof typeof appIcons

export function getIconComponent(name?: string | Component): Component {
  if (typeof name !== 'string') {
    return name ?? Document24Regular
  }
  return appIcons[name as AppIconName] ?? Document24Regular
}

export function renderIcon(icon: string | Component | undefined, size = 18) {
  const iconComponent = getIconComponent(icon)
  return () => h(NIcon, { size }, { default: () => h(iconComponent) })
}

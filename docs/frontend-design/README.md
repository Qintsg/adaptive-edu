# 自适应学习前端设计原型

这是 `docs/前端设计方案.md` 的可交互高保真原型，用于在生产代码改造前确认视觉语言、信息层级、角色差异和响应式行为。

优秀学习产品与图谱工具的吸收、舍弃和落地规则见 `docs/前端优秀项目基准.md`。

## 查看原型

在仓库根目录运行：

```powershell
uv run --project backend python -m http.server 4173 --directory docs/frontend-design --bind 127.0.0.1
```

然后访问：

```text
http://127.0.0.1:4173/prototype.html
```

页面右下角的“设计评审”面板可以切换角色和页面。也可以通过查询参数直接定位：

```text
?role=student&view=student-home
?role=student&view=student-path
?role=student&view=student-task
?role=student&view=student-assessment
?role=student&view=student-assignments
?role=student&view=student-resources
?role=student&view=student-graph
?role=student&view=student-ai
?role=student&view=student-agent
?role=student&view=student-courses
?role=student&view=student-profile
?role=student&view=student-settings
?role=teacher&view=teacher-workspace
?role=teacher&view=teacher-content
?role=teacher&view=teacher-classroom
?role=admin&view=admin-governance
?role=admin&view=admin-content
?role=admin&view=admin-access
?role=auth&view=auth-preview
```

## 文件

- `prototype.html`：语义结构与真实业务文案。
- `prototype.css`：设计令牌、桌面/移动布局、状态与动效。
- `prototype.js`：角色/页面切换和推荐依据等评审交互。

## 原型边界

- 原型不调用后端 API，不写入业务数据。
- 示例数据来自本项目本机测试数据的典型结构。
- 原型用于确认设计，不替代 Vue 生产实现和组件测试。
- 全部现有路由的页面结构、主操作和状态设计见 `docs/前端功能设计清单.md`。
- 生产实现应按照设计方案中的 Phase 0 → Phase 4 逐步迁移，不应直接复制成单体页面。

## 已验证视口

- 桌面：1280 × 720。
- 移动：390 × 844。
- 共验证 19 个页面视图：学生 12、教师 3、管理 3、认证 1。
- 每个视图均只有一个活动页面和一个 `h1`，无整页横向溢出或控制台错误。
- 管理端数据表在移动端保留表格容器内部横向滚动，页面本身不横向溢出。

## 内容密度基线

- 课程资源：59 项总量，原型首批展示 8 项、6 种类型，并包含知识点、来源、进度、推荐原因和学习队列。
- 知识图谱：74 个课程节点，当前章节展示 18 个节点、4 类掌握状态和 3 类主要关系。
- 学习画像：8 个章节、掌握证据、能力、习惯和路径变更。
- 教师内容工作区：74 个节点、121 条关系、59 项资源、192 道题和发布检查。
- 管理端：用户首批 8 行，并补充课程、班级、激活码和高影响审计记录。

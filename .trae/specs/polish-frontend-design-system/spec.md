# 前端设计系统与可用性针对性优化 Spec

## Why

当前 SynthDraft 前端（Next.js 14 + React 18 + Tailwind + shadcn/ui）功能已贯通三个工作台（审图 / 生成 / 知识库），但存在一批影响**用户体验**与专业度的结构性缺陷：暗色模式 token 已写好却因未注入 `next-themes` 而完全失效；侧边栏无 active 高亮、无移动端折叠；5+ 业务组件硬编码 `bg-green-500`/`bg-red-500` 绕过 token 系统；两份 `TaskProgress` 近重复；`review/FileUploader` 与 `generate/InputTabs` 内 `SketchUploader` 复制粘贴 ~150 行；`ws.ts` 存在闭包陷阱且无重连；多处 `Label`/`Textarea` 缺 `htmlFor`/`aria-label`；`apiFetch` 错误处理过于简陋。

此外，**用户体验层面**还有明显短板：状态切换无过渡动画、loading 态仅用裸 `Loader2` 旋转无骨架屏、按钮 disabled 无 inline 原因提示、空状态缺引导性 CTA、表单无内联校验、错误态缺重试入口、长任务运行中无取消确认、WS 断连用户无感知、Toast 仅 sonner 默认样式无语义分级、移动端无手势关闭抽屉、键盘焦点环不可见。

本 spec 利用 `trae-remote-official:frontend-design`（视觉/token/品牌/微交互）、`trae-remote-official:web-app-development`（组件拆分/性能/a11y/状态机）、`trae-remote-official:stark`（设计 token / web-design 规范 / UX 流）三个插件的能力进行针对性、最小化的优化完善，**不重写整体架构、不引入新业务功能**，并在最后阶段对所有页面与交互进行全面实际测试，确保功能无异常、显示正常、交互正常。

## What Changes

### 设计 Token 与主题
- **BREAKING（仅视觉）**: 在 `globals.css` 新增 `--success/--warning/--info` 语义 token（含 foreground/ring），并扩展 `tailwind.config.ts` 的 `colors` 映射。
- 在 `app/layout.tsx` 注入 `next-themes` 的 `ThemeProvider attribute="class"`，`<html>` 加 `suppressHydrationWarning`。
- Header 增加主题切换按钮（Sun/Moon 图标），替换无意义的"开发模式"Badge 为环境标识（dev/staging，基于 `NODE_ENV`）。
- 修复 `tailwind.config.ts` 的 `fontFamily.sans` 映射到 `--font-sans` 变量；调整 `--ring` 与 `--primary` 对比度。
- 全局 `globals.css` base 层补 `:focus-visible` 环、`::selection`、滚动条样式。

### 导航与布局
- 侧边栏使用 `usePathname()` 比对 `item.href`，active 项切换为 `secondary` 变体并加 `aria-current="page"`，附左侧高亮条（`border-l-2 border-primary`）增强视觉锚点。
- `md:` 以下侧边栏切换为 Sheet/Drawer 抽屉，Header 加汉堡按钮触发；支持 Esc 关闭、点击遮罩关闭、路由切换后自动关闭。
- 在 `tailwind.config.ts` 增加 `layout.header.height` / `layout.sidebar.width` token，移除魔法数 `h-14`/`w-60`。

### 共享组件抽取
- 新建 `src/components/shared/TaskProgress.tsx` 合并两份近重复组件，接口支持 `labels`/`connected` props；`review` 与 `generate` 页面引用同一份，`review` 页同时透传 `connected`。
- 新建 `src/components/shared/FileDropZone.tsx` + `src/lib/useFileUpload.ts` hook，替代 `review/FileUploader` 与 `generate/InputTabs` 内的 `SketchUploader`，通过 `accept`/`maxSize`/`icon`/`hint` 参数差异化。
- 新建 `src/components/shared/States.tsx`（`EmptyState`/`LoadingState`/`ErrorState` 三件套，`ErrorState` 支持 `onRetry`；`EmptyState` 支持 `action` CTA 按钮）。
- 新建 `src/components/shared/MetaRow.tsx`，移除 `review/page.tsx` 与 `generate/page.tsx` 内的两份重复定义。
- 新建 `src/components/shared/Skeleton.tsx`（卡片骨架、表格骨架、详情骨架），替代裸 `Loader2` 旋转，提升感知性能。

### 用户体验（UX）增强
- **状态过渡**：所有 Card 进出（提交中 → 运行中 → 完成/失败）使用 `transition-opacity`/`animate-in fade-in` 平滑过渡；Tailwind 配置补 `fade-in`/`slide-in-right`/`shimmer` keyframes。
- **按钮 disabled 内联原因**：所有主操作按钮 disabled 时，下方 hint 用 `aria-describedby` 与按钮关联，hint 文案明确说明"为什么不能点"（如"请先上传图纸文件"、"请输入自然语言描述"、"任务进行中"）。
- **空状态引导**：`/kb` 未搜索时显示推荐查询示例（点击填入）；`/review` 与 `/generate` 未上传/未输入时给出"3 步上手"引导。
- **表单内联校验**：`kb/SearchPanel` 的查询输入失焦时校验长度（≥1 字符），不通过时 Input 下方红字提示；`OutputFormatSelector` 已选格式在卡片角标显示对勾。
- **Toast 语义分级**：封装 `useToast` 工具或扩展 sonner 配置，统一 success/warning/error/info 四档样式（success 用 `--success` token，error 用 `--destructive`，warning 用 `--warning`，info 用 `--info`），含图标 + 关闭按钮 + 4s 自动消失（error 持续至手动关闭）。
- **长任务取消确认**：`TaskProgress` 增加"取消任务"按钮，点击弹 `AlertDialog` 二次确认（避免误触），确认后调 `cancelTask` 并 toast"任务已取消"。
- **WS 断连感知**：`TaskProgress` 在 `connected === false` 时顶部显示 `Badge variant="warning"`"连接中断，重试中…"，重连成功后切换为 `success`"已重连"并 2s 后淡出。
- **复制成功反馈**：`CodePanel` 的"复制代码"按钮点击后文案临时切换为"已复制"2s，同时 toast.success。
- **结果下载反馈**：`DownloadList` 下载按钮点击后显示"下载中…"loading，完成（`<a>` 的 click 触发）后 toast.success。
- **键盘快捷键**：`/review`/`/generate` 支持 `Cmd/Ctrl+Enter` 提交主表单；`Esc` 关闭 Dialog/Sheet；`/` 聚焦搜索框（仅 `/kb`）。
- **可访问性焦点**：所有可交互元素 `:focus-visible` 显示 2px 实线环（用 `--ring` token），不依赖默认 outline。
- **移动端手势**：Sheet 抽屉支持从左向右滑动关闭（用 shadcn Sheet 内置 drag handle 或 Vaul 依赖；若不引入 Vaul 则跳过该项并在 checklist 标记 N/A）。

### 工具与类型
- 新建 `src/lib/format.ts` 统一 `formatElapsed`/`formatSize`/`formatNumber`/`formatBoundingBox`/`getExtension`，消除三处 `formatElapsed` 重复（且签名不一致）。
- 在 `types.ts` 扩展 `ReviewResult.status` 为 `"completed"|"failed"|"pending"|"running"`，移除 `ReviewResultAnyStatus` patch 类型。
- 新增 `GenerationMetadata`/`ReviewMetadata` 子类型替代 `Record<string, unknown>`，消除 `as string` 断言。
- 将 `ReindexResponse`、`CATEGORY_OPTIONS`、`PRESET_STANDARDS` 移到 `types.ts`/`constants.ts` 单一来源。

### 状态色与 Badge
- 扩展 `components/ui/badge.tsx` 的 cva，新增 `success`/`warning`/`info` variant。
- 将 `ScoreCard`/`DefectsTable`/`GeometryValidationCard`/`ClauseCard`/`ExecutionResultCard` 中所有硬编码 `bg-green-500`/`bg-red-500`/`bg-yellow-500` 替换为语义 token 或 Badge variant。

### WebSocket 与 API
- 修复 `lib/ws.ts` 的闭包陷阱（`onclose` 读取 stale `error`），实现指数退避重连（1s/2s/4s/8s/16s，max 5 次），重连成功后状态对齐。
- `WS_BASE` 默认值改为基于 `window.location` 推导，与 `API_BASE` 同源策略一致。
- `lib/api.ts` 引入 `ApiError` 类（带 `status`/`detail`），解析 FastAPI `{detail}` 响应体；支持 `AbortSignal`；提供 `apiUpload(file)` 走统一上传入口。
- 轮询与 WS 双触发收敛：WS `onCompleted` 后立即取消 polling（`AbortController`），polling 改为退避（800/1600/3200ms）。

### 可访问性
- `kb/SearchPanel.tsx`：3 处 `<Label>` 补 `htmlFor`，对应控件补 `id`；DropdownMenu trigger 补 `aria-haspopup`/`aria-expanded`。
- `generate/CodePanel.tsx` 与 `generate/InputTabs.tsx`：`<Textarea>` 补 `aria-label` 或 `Label htmlFor`。
- `review/DefectsTable.tsx`：展开行补 `tabIndex={0}`/`role="button"`/`aria-expanded`/`onKeyDown(Enter|Space)`；`<Fragment key={i}>` 改用稳定 key。
- `review/ScoreCard.tsx`：评分块加 `role="meter"` + `aria-valuenow/min/max`。
- `generate/OutputFormatSelector.tsx`：视觉圆点加 `aria-hidden="true"`。

### 首页与品牌
- 改造 `app/page.tsx` 为轻量 dashboard：保留 hero，新增"系统状态"（后端连通性，调 `GET /health`）+ "工作台入口"卡片组重排版（含图标 + 进入按钮 + 一句话价值主张），去除与 sidebar 信息冗余。
- Header 增加 logo mark（SVG），规范 header（`text-lg`）/ page-title（`text-2xl`）字号阶梯。

### 最终阶段：全面实际测试（必须完整执行）
- **测试矩阵**：以矩阵形式覆盖 4 个页面 × 2 主题 × 4 断点（sm 375px / md 768px / lg 1024px / xl 1440px）= 32 个组合的视觉回归截图。
- **功能链路实测**：每条主链路 MUST 端到端走通并保存证据（截图/录屏/网络请求）：
  1. `/review`：上传图纸（拖拽 + 点击两种）→ 选规范 → 提交 → WS 进度 → 结果（含缺陷表格键盘展开）→ 下载 HTML/PDF 报告 → 重新发起
  2. `/generate`：自然语言输入 → 提交 → WS 进度 → 结果（代码 + 执行结果 + 几何校验 + 下载）→ 编辑代码 → 重新执行 → 多轮修改指令
  3. `/generate`：草图输入（拖拽 + 点击）→ 提交 → 进度 → 结果
  4. `/kb`：列规范 → 重建索引 → 输入查询 → 选过滤 → 检索 → 查看条款卡片 → 清空
  5. `/`：系统状态卡片加载 → 工作台入口跳转
- **交互专项测试**：主题切换持久化、移动端抽屉开关、Cmd+Enter 提交、Esc 关闭、`/` 聚焦搜索、复制代码反馈、下载反馈、取消任务二次确认、Toast 自动消失。
- **异常路径测试**：网络断开时提交 → 错误 toast；WS 断连 → 重连提示 → 恢复；上传超限文件 → inline 错误；后端返回 422 → 可读错误；轮询超时 → 重试入口。
- **可访问性自动化**：使用 `@axe-core/playwright` 或 Chrome DevTools Accessibility 面板扫描 4 个页面，0 critical 违规。
- **性能基线**：Chrome DevTools Performance 面板记录 LCP/CLS/INP，记录基线值（不要求严格阈值，但必须可观测）。
- **跨浏览器**：Chrome / Edge / Firefox 三浏览器各跑一遍主链路。
- **回归报告**：在 `frontend/tmp_audit_logs/frontend_polish_verification_report.md` 输出完整报告，含测试矩阵、截图清单、问题列表、修复记录、最终结论。

## Impact

- **Affected specs**: 无（本 spec 自包含，不修改其他 spec 的需求）。
- **Affected code**:
  - `frontend/src/app/layout.tsx`、`frontend/src/app/page.tsx`、`frontend/src/app/globals.css`
  - `frontend/tailwind.config.ts`
  - `frontend/src/components/ui/{badge,sonner}.tsx`
  - `frontend/src/components/shared/`（新建目录：TaskProgress / FileDropZone / States / MetaRow / Skeleton）
  - `frontend/src/components/{review,generate,kb}/*.tsx`（替换硬编码色、引用共享组件、补 a11y、加 UX 微交互）
  - `frontend/src/lib/{api.ts, ws.ts, types.ts, format.ts(新), constants.ts(新), useFileUpload.ts(新)}`
- **依赖**: `next-themes` 已在 `package.json` 中；可能新增 `@axe-core/playwright`（devDep，仅测试用）；shadcn `sheet`/`alert-dialog`/`skeleton` 组件通过 `npx shadcn@latest add` 按需添加；移动端手势如需则引入 `vaul`（可选，未引入则该项 N/A）。
- **风险**: 主题切换会改变用户视觉体验，需在 light/dark 双模式下验证所有工作台；TaskProgress/FileDropZone 合并需保证两个工作台行为不回归；UX 微交互不得破坏现有功能。

## ADDED Requirements

### Requirement: 主题系统与设计 Token
系统 SHALL 在 light/dark 双模式下提供一致的语义色（success/warning/info），并通过 `next-themes` 支持用户切换；所有业务组件 MUST NOT 使用硬编码的 `bg-green-*`/`bg-red-*`/`bg-yellow-*` 等绕过 token 的颜色类。

#### Scenario: 用户切换暗色模式
- **WHEN** 用户点击 Header 的主题切换按钮
- **THEN** `<html>` 获得 `dark` 类，所有 token 驱动的组件切换为暗色变量，刷新后保持上次选择

#### Scenario: ScoreCard 在暗色下可读
- **WHEN** 评分卡渲染且当前为暗色模式
- **THEN** success/warning/destructive 三档背景与文字均使用 `--success` 等 token，对比度满足 WCAG AA

### Requirement: 响应式导航
系统 SHALL 在 `md:` 以上断点显示固定侧边栏，在 `md:` 以下断点收起为抽屉，并标识当前激活路由。

#### Scenario: 桌面端激活路由高亮
- **WHEN** 用户位于 `/review`
- **THEN** 侧边栏"审图工作台"项渲染为 `secondary` 变体且 `aria-current="page"`，左侧显示 `border-primary` 高亮条

#### Scenario: 移动端抽屉
- **WHEN** 视口宽度 < 768px
- **THEN** 侧边栏隐藏，Header 显示汉堡按钮，点击后以 Sheet 形式从左侧滑出，点击导航项后自动关闭

### Requirement: 共享组件单一来源
系统 SHALL 提供唯一的 `TaskProgress`、`FileDropZone`、`States`、`MetaRow`、`Skeleton` 共享组件，三个工作台 MUST 引用同一份实现。

#### Scenario: 两工作台复用 TaskProgress
- **WHEN** 审图与生成工作台渲染任务进度
- **THEN** 两者均 import `@/components/shared/TaskProgress`，仅通过 `labels` prop 差异化文案

### Requirement: 用户体验微交互
系统 SHALL 为所有主操作提供即时反馈、平滑过渡、disabled 原因提示、空状态引导、错误重试入口。

#### Scenario: 按钮 disabled 原因可读
- **WHEN** 主提交按钮 disabled
- **THEN** 按钮通过 `aria-describedby` 关联下方 hint 文案，hint 明确说明"为什么不能点"（如"请先上传图纸文件"）

#### Scenario: 状态切换平滑过渡
- **WHEN** 工作台从"提交中"切换到"运行中"再到"已完成"
- **THEN** 各 Card 之间使用 `fade-in` 过渡，无突变闪烁

#### Scenario: WS 断连用户可感知
- **WHEN** 任务运行中 WebSocket 连接中断
- **THEN** TaskProgress 顶部显示 `warning` Badge"连接中断，重试中…"，重连成功后切换为 `success`"已重连"并 2s 后淡出

#### Scenario: 长任务可取消
- **WHEN** 用户在任务运行中点击"取消任务"按钮
- **THEN** 弹出 AlertDialog 二次确认，确认后调 `cancelTask`，toast"任务已取消"，状态切换为 failed

#### Scenario: 复制与下载反馈
- **WHEN** 用户点击"复制代码"或"下载"按钮
- **THEN** 按钮显示 loading 或文案切换（"已复制"2s），完成后 toast.success

### Requirement: WebSocket 鲁棒性
系统 SHALL 在 WebSocket 非正常关闭时按指数退避策略重连，且 `onclose` 闭包 MUST NOT 引用 stale state。

#### Scenario: 网络抖动后自动恢复
- **WHEN** 任务运行中 WS 连接被 RST
- **THEN** 客户端按 1s/2s/4s/8s/16s 间隔重试（最多 5 次），重连成功后继续接收进度，不丢失任务状态

### Requirement: 表单可访问性
所有可见表单控件 MUST 与 `<Label>` 通过 `htmlFor`/`id` 程序化关联，或提供 `aria-label`；可交互的非表单元素（如可展开的表格行）MUST 支持键盘操作。

#### Scenario: 读屏识别自然语言输入
- **WHEN** 读屏软件聚焦生成工作台的自然语言输入框
- **THEN** 宣告"自然语言描述"（通过关联的 `<Label>` 或 `aria-label`）

#### Scenario: 键盘展开缺陷行
- **WHEN** 用户在缺陷表格行上按 Tab 聚焦后按 Enter/Space
- **THEN** 该行展开/收起，`aria-expanded` 状态同步更新

### Requirement: API 错误可读化
`apiFetch` SHALL 解析后端 `{detail}` JSON 响应体并抛出 `ApiError`（带 `status`/`detail`），调用方可基于 `status` 分支处理。

#### Scenario: 后端返回 422 校验错误
- **WHEN** 后端返回 `{"detail":[{"loc":...,"msg":"..."}]}`
- **THEN** `apiFetch` 抛出 `ApiError`，`error.detail` 为可读字符串，`error.status === 422`，调用方 toast 显示可读错误

### Requirement: 全面实际测试（最终阶段强制执行）
系统 MUST 在所有优化完成后通过覆盖 4 页面 × 2 主题 × 4 断点的视觉回归、5 条主链路端到端实测、交互专项、异常路径、a11y 自动化、跨浏览器、性能基线的全面测试，并在 `frontend/tmp_audit_logs/` 输出验证报告。

#### Scenario: 主链路端到端通过
- **WHEN** 测试人员按测试矩阵执行 `/review`/`/generate`/`/kb`/`/` 全部主链路
- **THEN** 每条链路无功能异常，所有交互（上传/提交/进度/结果/下载/重置）正常，截图与网络请求证据已保存

#### Scenario: a11y 自动化零 critical 违规
- **WHEN** 使用 `@axe-core/playwright` 扫描 4 个页面
- **THEN** critical 级别违规数为 0，serious 级别违规数 ≤ 3 且每项有记录

#### Scenario: 跨浏览器一致
- **WHEN** 在 Chrome / Edge / Firefox 三浏览器各跑一遍主链路
- **THEN** 三浏览器视觉与功能一致，无浏览器专属 bug

## MODIFIED Requirements

### Requirement: 前端工作台状态展示
原：各工作台自定义 Empty/Loading/Error 与 MetaRow。
现：所有工作台统一引用 `shared/States` 与 `shared/MetaRow`，loading 态用 `shared/Skeleton` 替代裸旋转，错误态支持 `onRetry` 回调，空状态支持 `action` CTA，文案与视觉一致。

## REMOVED Requirements

### Requirement: `ReviewResultAnyStatus` patch 类型
**Reason**: 该类型是为绕过 `ReviewResult.status` 仅 `"completed"|"failed"` 限制而定义的运行时补丁，与后端实际行为不一致。
**Migration**: 在 `types.ts` 扩展 `ReviewResult.status` 后，删除该类型并直接使用 `ReviewResult`。

# Tasks

> 实施顺序按依赖与影响排序；同一阶段的子任务可并行。所有任务 MUST 复用 `trae-remote-official:frontend-design`、`trae-remote-official:web-app-development`、`trae-remote-official:stark` 三个插件的设计 token 规范与组件最佳实践。最终阶段（Task 18-22）为**全面实际测试**，必须完整执行，禁止跳过任何子项。

## 阶段一：设计 Token 与主题基础（前置阻塞）

- [ ] Task 1: 扩展 `globals.css` 与 `tailwind.config.ts` 语义 token
  - [ ] SubTask 1.1: 在 `globals.css` 的 `:root` 与 `.dark` 中新增 `--success`/`--success-foreground`/`--warning`/`--warning-foreground`/`--info`/`--info-foreground`（及 ring 变体），light/dark 双套对比度满足 WCAG AA
  - [ ] SubTask 1.2: 在 `tailwind.config.ts` 的 `theme.extend.colors` 映射 `success`/`warning`/`info` 三组语义色；扩展 `chart-1..5` 色板；映射 `fontFamily.sans` 到 `var(--font-sans)`
  - [ ] SubTask 1.3: 在 `tailwind.config.ts` 增加 `layout.header.height`（14, 3.5rem）与 `layout.sidebar.width`（60, 15rem）token
  - [ ] SubTask 1.4: 调整 `--ring` 使其与 `--primary` 在 light/dark 下均对比可辨
  - [ ] SubTask 1.5: `globals.css` base 层补 `:focus-visible` 环（2px solid var(--ring)）、`::selection`、滚动条样式（webkit + firefox）
  - [ ] SubTask 1.6: 在 `tailwind.config.ts` 增加 `fade-in`/`slide-in-right`/`shimmer` keyframes 与 animation 工具类

- [ ] Task 2: 注入 `next-themes` ThemeProvider 与主题切换按钮
  - [ ] SubTask 2.1: 在 `app/layout.tsx` 包裹 `ThemeProvider attribute="class" defaultTheme="system" enableSystem`，`<html>` 加 `suppressHydrationWarning`
  - [ ] SubTask 2.2: 在 Header 右侧新增主题切换按钮（`Moon`/`Sun` 图标，`useTheme` 切换），替换"开发模式"Badge 为基于 `process.env.NODE_ENV` 的环境标识（仅 dev 显示"开发模式"）
  - [ ] SubTask 2.3: 验证 `next-themes` 与 Next.js 14 App Router 的 SSR 兼容，避免 hydration mismatch

## 阶段二：导航与布局

- [ ] Task 3: 侧边栏 active 高亮与移动端折叠
  - [ ] SubTask 3.1: 在 `app/layout.tsx` 使用 `usePathname()` 比对 `item.href`，active 项切换为 `secondary` 变体并加 `aria-current="page"`，附左侧 `border-l-2 border-primary` 高亮条
  - [ ] SubTask 3.2: 引入 shadcn `Sheet` 组件（`npx shadcn@latest add sheet`），`md:` 以下将 sidebar 内容放入 Sheet 抽屉，Header 加 `Menu`/`X` 汉堡按钮触发
  - [ ] SubTask 3.3: Sheet 支持 Esc 关闭、点击遮罩关闭、路由切换后自动关闭（监听 `usePathname` 变化时 setOpen(false)）
  - [ ] SubTask 3.4: 将 `h-14`/`w-60` 魔法数替换为 `layout.header.height`/`layout.sidebar.width` token
  - [ ] SubTask 3.5: Header 增加 logo mark（lucide `Layers` 图标 + 品牌色背景 + 白色图标），规范 header（`text-lg`）/ page-title（`text-2xl`）字号阶梯

## 阶段三：共享组件抽取（TaskProgress / FileDropZone / States / MetaRow / Skeleton）

- [ ] Task 4: 合并两份 TaskProgress 为共享组件
  - [ ] SubTask 4.1: 新建 `src/components/shared/TaskProgress.tsx`，接口 `interface TaskProgressProps { taskId; status; progress; error; connected?: boolean; labels?: Partial<Record<TaskStatus,string>> }`，默认 `STATUS_LABEL` 可被 `labels` 覆写
  - [ ] SubTask 4.2: `review/page.tsx` 与 `generate/page.tsx` 改为 `import { TaskProgress } from "@/components/shared/TaskProgress"`，传入不同 `labels.running`（"审图中..."/"生成中..."）
  - [ ] SubTask 4.3: `review/page.tsx` 透传 `useTaskProgress` 返回的 `connected`
  - [ ] SubTask 4.4: 删除 `components/review/TaskProgress.tsx` 与 `components/generate/TaskProgress.tsx`

- [ ] Task 5: 抽离 `FileDropZone` + `useFileUpload` hook
  - [ ] SubTask 5.1: 新建 `src/lib/useFileUpload.ts`，封装拖拽、`onChange`、大小/类型校验、上传请求（走 `apiUpload`）、错误处理，返回 `{ isDragging, uploading, error, uploaded, upload, clear, dragProps }`
  - [ ] SubTask 5.2: 新建 `src/components/shared/FileDropZone.tsx`，接受 `accept`/`maxSize`/`icon`/`hint`/`disabled`/`uploaded`/`onUploaded`/`onClear` props，内部用 `useFileUpload`
  - [ ] SubTask 5.3: `review/FileUploader.tsx` 改为薄包装，内部用 `FileDropZone`（accept 图纸格式、maxSize 50MB、icon `FileSearch`）
  - [ ] SubTask 5.4: `generate/InputTabs.tsx` 内的 `SketchUploader` 改用 `FileDropZone`（accept 草图格式、maxSize 20MB、icon `PencilRuler`），删除内联 `SketchUploader` 定义
  - [ ] SubTask 5.5: 抽离 `formatSize`/`getExtension` 到 `src/lib/format.ts`，两处引用同一份

- [ ] Task 6: 新建 `States`、`MetaRow`、`Skeleton` 共享组件
  - [ ] SubTask 6.1: 新建 `src/components/shared/States.tsx`，导出 `EmptyState`（`icon`/`title`/`description`/`action?`）、`LoadingState`（`text?`）、`ErrorState`（`title?`/`description`/`onRetry?`）
  - [ ] SubTask 6.2: 新建 `src/components/shared/MetaRow.tsx`，移除 `review/page.tsx` 与 `generate/page.tsx` 内的重复定义
  - [ ] SubTask 6.3: 新建 `src/components/shared/Skeleton.tsx`，导出 `CardSkeleton`/`TableSkeleton`/`DetailSkeleton`，用 `animate-pulse` + `bg-muted` 实现
  - [ ] SubTask 6.4: 在 `review/page.tsx`、`generate/page.tsx`、`kb/ResultsList.tsx`、`kb/StandardsList.tsx` 中将自定义 Empty/Loading/Error 替换为 `States` 三件套；loading 态优先用 `Skeleton`

## 阶段四：工具与类型清理

- [ ] Task 7: 新建 `src/lib/format.ts` 统一格式化函数
  - [ ] SubTask 7.1: 实现 `formatElapsed(ms: number | unknown)`、`formatSize(bytes: number)`、`formatNumber(n: number, digits?)`、`formatBoundingBox(bb)`、`getExtension(name: string)`
  - [ ] SubTask 7.2: 替换 `review/page.tsx`、`generate/page.tsx`、`ExecutionResultCard.tsx`、`GeometryValidationCard.tsx`、`FileUploader.tsx`、`InputTabs.tsx` 中的本地实现
  - [ ] SubTask 7.3: 为 `format.ts` 增加 vitest 单元测试（覆盖 ms/s 边界、0 字节、负数、undefined）

- [ ] Task 8: 收敛 `types.ts` 与 `constants.ts`
  - [ ] SubTask 8.1: 在 `types.ts` 扩展 `ReviewResult.status` 为 `"completed"|"failed"|"pending"|"running"`，删除 `ReviewResultAnyStatus`
  - [ ] SubTask 8.2: 新增 `GenerationMetadata { model_name?: string; generated_at?: string; elapsed_ms?: number }` 与 `ReviewMetadata { elapsed_ms?: number; [k: string]: unknown }`，替换 `metadata: Record<string, unknown>`，消除 `as string` 断言
  - [ ] SubTask 8.3: 统一 `ReviewResult.file_type` 与 `UploadResponse.file_type` 为 `UploadFileType`
  - [ ] SubTask 8.4: 新建 `src/lib/constants.ts`，将 `PRESET_STANDARDS`、`CATEGORY_OPTIONS`、`SKETCH_ACCEPT`、`ACCEPTED_SKETCH_EXT`、`DEFAULT_STANDARD_IDS`、`DEFAULT_TOP_K` 集中到单一来源
  - [ ] SubTask 8.5: 将 `ReindexResponse` 从 `kb/StandardsList.tsx` 移到 `types.ts`

## 阶段五：状态色与 Badge 扩展

- [ ] Task 9: 扩展 `badge.tsx` 并替换硬编码色
  - [ ] SubTask 9.1: 在 `components/ui/badge.tsx` 的 cva variant 增加 `success`/`warning`/`info`，分别映射 `bg-success/15 text-success` 等 token
  - [ ] SubTask 9.2: `review/ScoreCard.tsx` 用 `Badge variant="success/warning/destructive"` 替换 `bg-green-50`/`bg-yellow-50`/`bg-red-50`
  - [ ] SubTask 9.3: `review/DefectsTable.tsx` 用 `Badge variant="destructive/warning/secondary"` 替换 `bg-red-500`/`bg-orange-500`/`bg-yellow-500`/`bg-gray-400`
  - [ ] SubTask 9.4: `generate/GeometryValidationCard.tsx` 用 `Badge variant="success"` 替换 `bg-green-600`
  - [ ] SubTask 9.5: `generate/ExecutionResultCard.tsx` 用 `States` + `warning` token 替换硬编码 `border-yellow-500/40 bg-yellow-50`
  - [ ] SubTask 9.6: `kb/ClauseCard.tsx` 用 `Badge variant="warning/success"` 替换 `bg-yellow-500/10`/`bg-green-500/10`

## 阶段六：WebSocket 与 API 鲁棒性

- [ ] Task 10: 修复 `ws.ts` 闭包陷阱与重连
  - [ ] SubTask 10.1: 用 `errorRef`/`closedRef` 替代 `onclose` 内对 `error` state 的直接读取，修复"非正常关闭"误判
  - [ ] SubTask 10.2: 实现指数退避重连（delays = [1000, 2000, 4000, 8000, 16000]，max 5 次），重连成功重置计数，达到上限后停止并 setError
  - [ ] SubTask 10.3: `WS_BASE` 默认改为基于 `window.location.host` 推导（`ws(s)://${host}/api/v1`），与 `API_BASE` 同源
  - [ ] SubTask 10.4: `cancelTask` 改用 `apiFetch<void>` 走统一入口
  - [ ] SubTask 10.5: 移除未使用的 `lastMessage` state（或仅在回调中暴露，避免无谓渲染）
  - [ ] SubTask 10.6: `useTaskProgress` 暴露 `reconnectCount` 与 `connected`，供 TaskProgress 显示重连状态

- [ ] Task 11: 升级 `api.ts` 为 `ApiError` + `AbortSignal` + `apiUpload`
  - [ ] SubTask 11.1: 定义 `class ApiError extends Error { status: number; detail: unknown }`，`apiFetch` 解析 `Content-Type: application/json` 响应体取 `detail`，构造 `ApiError`
  - [ ] SubTask 11.2: `apiFetch` 接受 `init.signal?: AbortSignal` 透传给 `fetch`
  - [ ] SubTask 11.3: 新增 `apiUpload(file: File, endpoint: string, signal?)` 走 FormData，不强制 `Content-Type`，返回 `UploadResponse`
  - [ ] SubTask 11.4: `FileUploader`/`FileDropZone` 改用 `apiUpload`
  - [ ] SubTask 11.5: `review/page.tsx` 与 `generate/page.tsx` 的轮询循环改为退避（800/1600/3200ms）+ WS 成功后取消（用 `AbortController`）

## 阶段七：可访问性整改

- [ ] Task 12: 表单控件 a11y 配对
  - [ ] SubTask 12.1: `kb/SearchPanel.tsx`：3 处 `<Label>` 补 `htmlFor`，对应 `<Select>`/`<Button>` 补 `id`；DropdownMenu trigger 补 `aria-haspopup="listbox"`/`aria-expanded`
  - [ ] SubTask 12.2: `generate/CodePanel.tsx`：`<Textarea>` 加 `id` + `<Label htmlFor>` 或 `aria-label="生成代码"`，只读模式加 `aria-readonly`
  - [ ] SubTask 12.3: `generate/InputTabs.tsx`：自然语言 `<Textarea>` 加 `aria-label="自然语言描述"`
  - [ ] SubTask 12.4: `generate/OutputFormatSelector.tsx`：视觉圆点 `<span>` 加 `aria-hidden="true"`
  - [ ] SubTask 12.5: `review/FileDropZone` 隐藏 `<input type="file">` 加 `aria-label`

- [ ] Task 13: 可交互非表单元素键盘化
  - [ ] SubTask 13.1: `review/DefectsTable.tsx`：展开行 `<TableRow>` 加 `tabIndex={0}`/`role="button"`/`aria-expanded`/`onKeyDown(Enter|Space)`；`<Fragment key={i}>` 改用稳定 key（`defect.id || defect.clause_id || i`）
  - [ ] SubTask 13.2: `review/ScoreCard.tsx`：评分块加 `role="meter"` + `aria-valuenow`/`aria-valuemin={0}`/`aria-valuemax={100}` + `aria-label="合规分数"`

## 阶段八：UX 微交互增强

- [ ] Task 14: 状态过渡与 disabled 提示
  - [ ] SubTask 14.1: `review/page.tsx` 与 `generate/page.tsx` 的 Card 容器加 `animate-in fade-in` 过渡（提交中→运行中→完成/失败）
  - [ ] SubTask 14.2: 主操作按钮 disabled 时，下方 hint `<span>` 加 `id`，按钮加 `aria-describedby` 关联；hint 文案根据原因动态切换（无上传/无输入/任务进行中）
  - [ ] SubTask 14.3: `kb/SearchPanel.tsx` 查询输入失焦校验，长度 < 1 时 Input 下方红字 `text-destructive` 提示"请输入查询文本"
  - [ ] SubTask 14.4: `OutputFormatSelector.tsx` 已选格式卡片角标显示 `Check` 图标

- [ ] Task 15: Toast 语义分级与取消确认
  - [ ] SubTask 15.1: 扩展 `components/ui/sonner.tsx`，配置 `toastOptions={{ style, classNames: { success/error/warning/info } }}`，success 4s 自动消失，error 持续至手动关闭
  - [ ] SubTask 15.2: 全局 `toast.success/error/warning/info` 调用统一带图标（`CheckCircle`/`XCircle`/`AlertTriangle`/`Info`）
  - [ ] SubTask 15.3: `TaskProgress` 增加"取消任务"按钮（`X` 图标），点击弹 shadcn `AlertDialog`（`npx shadcn@latest add alert-dialog`）二次确认，确认后调 `cancelTask` 并 `toast.warning("任务已取消")`
  - [ ] SubTask 15.4: `TaskProgress` 在 `connected === false` 时顶部显示 `Badge variant="warning"`"连接中断，重试中…"；重连成功后切换为 `Badge variant="success"`"已重连"并 2s 后淡出（用 `setTimeout` + state）

- [ ] Task 16: 复制/下载反馈与键盘快捷键
  - [ ] SubTask 16.1: `CodePanel.tsx` 复制按钮点击后文案切换为"已复制"2s（用 `useState` + `setTimeout`），同时 `toast.success("代码已复制")`
  - [ ] SubTask 16.2: `DownloadList.tsx` 下载按钮点击后显示 `Loader2` "下载中…"2s，完成后 `toast.success("下载已开始")`
  - [ ] SubTask 16.3: `review/page.tsx` 与 `generate/page.tsx` 监听 `Cmd/Ctrl+Enter` 触发主提交
  - [ ] SubTask 16.4: `kb/page.tsx` 监听 `/` 键聚焦查询输入（避免在已聚焦 Input 时拦截）
  - [ ] SubTask 16.5: 全局监听 `Esc` 关闭当前打开的 Dialog/Sheet（shadcn 组件内置，仅需验证）

- [ ] Task 17: 空状态引导与首页 dashboard
  - [ ] SubTask 17.1: `kb/ResultsList.tsx` 未搜索时 `EmptyState` 显示推荐查询示例（如"螺栓标记方法"、"尺寸公差选用"），点击填入查询框
  - [ ] SubTask 17.2: `review/page.tsx` 与 `generate/page.tsx` 未上传/未输入时显示"3 步上手"引导卡（用 `EmptyState` + `action`）
  - [ ] SubTask 17.3: `app/page.tsx` 改造为 dashboard：保留 hero，新增"系统状态"卡片（调 `GET /health` 显示后端连通性，用 `Badge variant="success/destructive"`），加载/失败态用 `States`
  - [ ] SubTask 17.4: "工作台入口"卡片组重排版（图标 + 进入按钮 + 一句话价值主张），去除与 sidebar 重复描述

## 阶段九：全面实际测试（最终阶段，必须完整执行）

- [ ] Task 18: 静态检查与单元测试
  - [ ] SubTask 18.1: 运行 `npm run lint`，记录退出码与 warning 数量（warnings 不阻塞，critical 必须修复）
  - [ ] SubTask 18.2: 运行 `npx tsc --noEmit`，确保零 TS 错误
  - [ ] SubTask 18.3: 运行 `npm run build`，确保生产构建通过，记录 bundle 大小
  - [ ] SubTask 18.4: 运行 `npx vitest run`（含 `format.test.ts`），全部通过

- [ ] Task 19: 视觉回归矩阵（4 页面 × 2 主题 × 4 断点 = 32 截图）
  - [ ] SubTask 19.1: 启动 `npm run dev`，用 Chrome DevTools 设备模拟依次在 375px / 768px / 1024px / 1440px 下访问 `/`、`/review`、`/generate`、`/kb`
  - [ ] SubTask 19.2: 每个组合在 light 与 dark 两种主题下各截一张全页截图，保存到 `frontend/tmp_audit_logs/screenshots/` 命名为 `{page}-{theme}-{breakpoint}.png`
  - [ ] SubTask 19.3: 人工检查每张截图：布局无错位、文字无溢出、对比度可读、暗色下无残留 light 色、移动端抽屉可开关

- [ ] Task 20: 功能链路端到端实测（5 条主链路，每条保存截图与网络请求证据）
  - [ ] SubTask 20.1: `/review` 链路：拖拽上传图纸 → 选规范 → 提交 → WS 进度显示 → 结果渲染（ScoreCard + DefectsTable 键盘 Tab+Enter 展开） → 下载 HTML 报告 → 点击"重新发起" → 状态归零
  - [ ] SubTask 20.2: `/review` 链路：点击上传选择文件 → 走通同上链路，验证两种上传方式一致
  - [ ] SubTask 20.3: `/generate` 自然语言链路：输入"生成一个直径 20 的圆柱" → 选 STEP 格式 → 提交 → WS 进度 → 结果（CodePanel + ExecutionResultCard + GeometryValidationCard + DownloadList） → 编辑代码 → 重新执行 → 多轮修改指令
  - [ ] SubTask 20.4: `/generate` 草图链路：拖拽 + 点击两种方式上传草图 → 走通同上链路
  - [ ] SubTask 20.5: `/kb` 链路：列规范 → 重建索引 → 输入查询 → 选规范过滤 + 分类过滤 → 检索 → 查看条款卡片 → 清空 → 推荐查询示例点击填入
  - [ ] SubTask 20.6: `/` 链路：系统状态卡片加载 → 显示后端连通性 → 点击工作台入口跳转

- [ ] Task 21: 交互专项 + 异常路径 + a11y 自动化 + 跨浏览器
  - [ ] SubTask 21.1: 交互专项：主题切换持久化（刷新后保持）、移动端抽屉开关、Cmd+Enter 提交、Esc 关闭 Dialog、`/` 聚焦搜索、复制代码反馈（"已复制"2s）、下载反馈（loading 2s）、取消任务二次确认、Toast 自动消失（success 4s / error 持续）
  - [ ] SubTask 21.2: 异常路径 1：DevTools Offline 模式下点提交 → 错误 toast 显示可读错误 → Online 后重试
  - [ ] SubTask 21.3: 异常路径 2：任务运行中 DevTools Network 面板 WS 阻断 5s → TaskProgress 显示"连接中断" → 恢复后"已重连" → 任务继续
  - [ ] SubTask 21.4: 异常路径 3：上传超限文件（>50MB 图纸 / >20MB 草图）→ inline 错误提示 + toast
  - [ ] SubTask 21.5: 异常路径 4：手动构造后端 422（如空 prompt）→ toast 显示可读 detail
  - [ ] SubTask 21.6: 异常路径 5：轮询超时（后端不响应）→ "获取结果超时"提示 + "重试"按钮
  - [ ] SubTask 21.7: a11y 自动化：安装 `@axe-core/playwright`，扫描 `/`、`/review`、`/generate`、`/kb` 四页，记录 critical 与 serious 违规数（目标 critical=0，serious≤3）
  - [ ] SubTask 21.8: 性能基线：Chrome DevTools Performance 面板记录每页 LCP/CLS/INP，填入报告
  - [ ] SubTask 21.9: 跨浏览器：Chrome / Edge / Firefox 三浏览器各跑一遍 `/review` 主链路，记录差异

- [ ] Task 22: 生成验证报告
  - [ ] SubTask 22.1: 在 `frontend/tmp_audit_logs/frontend_polish_verification_report.md` 输出完整报告：测试矩阵表、截图清单、5 条主链路通过情况、交互专项结果、异常路径结果、a11y 扫描结果、性能基线、跨浏览器差异、问题列表与修复记录、最终结论
  - [ ] SubTask 22.2: 报告 MUST 含"功能无异常 / 各页面显示正常 / 所有交互正常"三项明确结论，任一不达标则回到对应 Task 修复后重测

# Task Dependencies

- Task 2 依赖 Task 1（主题切换需要语义 token + 动画 keyframes）
- Task 3 可与 Task 1-2 并行（导航逻辑不依赖 token，但 SubTask 3.4 依赖 Task 1.3 的 layout token）
- Task 4/5/6 互相独立，可并行
- Task 7 优先于 Task 5/6（format 工具被 FileDropZone/MetaRow 引用）—— 实际可让 SubTask 在引用时同步替换，不严格阻塞
- Task 8 优先于 Task 11（ApiError 类型被 api.ts 使用）
- Task 9 依赖 Task 1（语义 token）与 Task 2（dark mode 才能验证对比度）
- Task 14-17（UX 微交互）依赖 Task 6（States/Skeleton）与 Task 9（Badge variant）
- Task 15.3 依赖 Task 11.1（ApiError）和 Task 10.4（cancelTask 用 apiFetch）
- Task 12/13 独立，可并行
- Task 17 依赖 Task 6（用 States 三件套）
- Task 18-22 依赖所有前置任务完成，且必须按顺序执行（18→19→20→21→22）
- 若 Task 19-21 任一项发现 bug，必须新增 fix task 修复后回到对应 Task 重测

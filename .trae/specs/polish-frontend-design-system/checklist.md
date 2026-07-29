# Checklist

> 每项检查 MUST 基于真实文件/运行结果打勾，禁止假设。所有检查在 `frontend/` 目录下执行。最终阶段（阶段九）的检查项任一不达标 MUST 修复后重测，禁止跳过。

## 阶段一：设计 Token 与主题基础

- [ ] `globals.css` 在 `:root` 与 `.dark` 中均存在 `--success`/`--success-foreground`/`--warning`/`--warning-foreground`/`--info`/`--info-foreground`（及 ring 变体）
- [ ] `tailwind.config.ts` 的 `theme.extend.colors` 映射了 `success`/`warning`/`info` 三组语义色
- [ ] `tailwind.config.ts` 的 `theme.extend.fontFamily.sans` 指向 `var(--font-sans)`
- [ ] `tailwind.config.ts` 存在 `layout.header.height` 与 `layout.sidebar.width` token
- [ ] `tailwind.config.ts` 含 `fade-in`/`slide-in-right`/`shimmer` keyframes 与 animation
- [ ] `globals.css` base 层包含 `:focus-visible`（2px solid var(--ring)）、`::selection`、滚动条样式
- [ ] `app/layout.tsx` 的 `<html>` 标签含 `suppressHydrationWarning`
- [ ] `app/layout.tsx` 包裹 `next-themes` 的 `ThemeProvider attribute="class"`
- [ ] Header 含主题切换按钮（点击可在 light/dark/system 间切换）
- [ ] "开发模式" Badge 仅在 `NODE_ENV === "development"` 时显示
- [ ] 在浏览器中点击主题切换按钮后 `<html>` 类名变化（light ↔ dark），刷新后保持上次选择

## 阶段二：导航与布局

- [ ] `app/layout.tsx` 使用 `usePathname()` 比对路由
- [ ] 当前路由对应的侧边栏项渲染为 `secondary` 变体且含 `aria-current="page"`，左侧含 `border-l-2 border-primary` 高亮条
- [ ] `md:` 以下断点侧边栏隐藏，Header 出现汉堡按钮
- [ ] 点击汉堡按钮弹出 Sheet 抽屉，含全部导航项
- [ ] Sheet 支持 Esc 关闭、点击遮罩关闭、路由切换后自动关闭
- [ ] `h-14`/`w-60` 已替换为 token utility（如 `h-layout-header`/`w-layout-sidebar`）
- [ ] Header 含 logo mark（图标 + 品牌色背景）

## 阶段三：共享组件抽取

- [ ] 存在 `src/components/shared/TaskProgress.tsx`，接受 `labels` 与 `connected` props
- [ ] `review/page.tsx` 与 `generate/page.tsx` 均 `import { TaskProgress } from "@/components/shared/TaskProgress"`
- [ ] `review/page.tsx` 向 `TaskProgress` 透传 `connected`
- [ ] 旧的 `components/review/TaskProgress.tsx` 与 `components/generate/TaskProgress.tsx` 已删除
- [ ] 存在 `src/lib/useFileUpload.ts` hook
- [ ] 存在 `src/components/shared/FileDropZone.tsx`
- [ ] `review/FileUploader.tsx` 内部使用 `FileDropZone`（不再含内联拖拽逻辑）
- [ ] `generate/InputTabs.tsx` 内的 `SketchUploader` 已移除，改用 `FileDropZone`
- [ ] 存在 `src/components/shared/States.tsx`，导出 `EmptyState`/`LoadingState`/`ErrorState`
- [ ] 存在 `src/components/shared/Skeleton.tsx`，导出 `CardSkeleton`/`TableSkeleton`/`DetailSkeleton`
- [ ] 存在 `src/components/shared/MetaRow.tsx`
- [ ] `review/page.tsx` 与 `generate/page.tsx` 不再含本地 `MetaRow` 定义
- [ ] `kb/ResultsList.tsx` 与 `kb/StandardsList.tsx` 使用 `States` 三件套

## 阶段四：工具与类型清理

- [ ] 存在 `src/lib/format.ts`，导出 `formatElapsed`/`formatSize`/`formatNumber`/`formatBoundingBox`/`getExtension`
- [ ] `review/page.tsx`/`generate/page.tsx`/`ExecutionResultCard.tsx`/`GeometryValidationCard.tsx`/`FileUploader.tsx`/`InputTabs.tsx` 不再含本地 `formatElapsed`/`formatSize`/`getExtension` 定义
- [ ] 存在 `src/lib/format.test.ts` 且 `npx vitest run` 全部通过
- [ ] `types.ts` 中 `ReviewResult.status` 类型为 `"completed"|"failed"|"pending"|"running"`
- [ ] `review/page.tsx` 不再含 `ReviewResultAnyStatus` 类型定义
- [ ] `types.ts` 含 `GenerationMetadata` 与 `ReviewMetadata` 子类型
- [ ] `generate/page.tsx` 不再含 `as string` 断言（model_name/generated_at）
- [ ] `ReviewResult.file_type` 与 `UploadResponse.file_type` 类型一致（均为 `UploadFileType`）
- [ ] 存在 `src/lib/constants.ts`，集中 `PRESET_STANDARDS`/`CATEGORY_OPTIONS`/`SKETCH_ACCEPT`/`ACCEPTED_SKETCH_EXT`/`DEFAULT_STANDARD_IDS`/`DEFAULT_TOP_K`
- [ ] `kb/StandardsList.tsx` 不再含本地 `ReindexResponse` 定义（已移到 `types.ts`）

## 阶段五：状态色与 Badge 扩展

- [ ] `components/ui/badge.tsx` 的 cva variant 含 `success`/`warning`/`info`
- [ ] `grep -rn "bg-green-\|bg-red-\|bg-yellow-\|bg-orange-" frontend/src/components/` 返回 0 命中（业务组件无硬编码状态色）
- [ ] `review/ScoreCard.tsx` 使用 `Badge variant="success/warning/destructive"`
- [ ] `review/DefectsTable.tsx` 使用 `Badge variant="destructive/warning/secondary"`
- [ ] `generate/GeometryValidationCard.tsx` 使用 `Badge variant="success"`
- [ ] `generate/ExecutionResultCard.tsx` 使用 `States` 或 `warning` token
- [ ] `kb/ClauseCard.tsx` 使用 `Badge variant="warning/success"`

## 阶段六：WebSocket 与 API 鲁棒性

- [ ] `lib/ws.ts` 的 `onclose` 不再直接读取 `error` state（改用 ref）
- [ ] `lib/ws.ts` 含指数退避重连逻辑（delays = [1000, 2000, 4000, 8000, 16000]）
- [ ] `lib/ws.ts` 的 `WS_BASE` 默认基于 `window.location.host` 推导，不再硬编码 `localhost`
- [ ] `lib/ws.ts` 的 `cancelTask` 使用 `apiFetch`
- [ ] `lib/ws.ts` 不再返回未使用的 `lastMessage`（或仅在回调中暴露）
- [ ] `useTaskProgress` 暴露 `reconnectCount` 与 `connected`
- [ ] `lib/api.ts` 定义 `class ApiError extends Error` 含 `status`/`detail`
- [ ] `apiFetch` 解析 `application/json` 响应体取 `detail` 字段
- [ ] `apiFetch` 接受 `init.signal` 透传给 `fetch`
- [ ] `lib/api.ts` 导出 `apiUpload(file, endpoint, signal?)`
- [ ] `FileDropZone`/`FileUploader` 使用 `apiUpload`
- [ ] `review/page.tsx` 与 `generate/page.tsx` 的轮询在 WS 成功后取消，且改为退避（800/1600/3200ms）

## 阶段七：可访问性整改

- [ ] `kb/SearchPanel.tsx` 中 3 处 `<Label>` 均含 `htmlFor`，对应控件含 `id`
- [ ] `kb/SearchPanel.tsx` 的 DropdownMenu trigger 含 `aria-haspopup`/`aria-expanded`
- [ ] `generate/CodePanel.tsx` 的 `<Textarea>` 含 `id`+`<Label htmlFor>` 或 `aria-label`，只读模式含 `aria-readonly`
- [ ] `generate/InputTabs.tsx` 的自然语言 `<Textarea>` 含 `aria-label="自然语言描述"`
- [ ] `generate/OutputFormatSelector.tsx` 的视觉圆点含 `aria-hidden="true"`
- [ ] `review/FileDropZone` 的隐藏 `<input type="file">` 含 `aria-label`
- [ ] `review/DefectsTable.tsx` 的展开行含 `tabIndex={0}`/`role="button"`/`aria-expanded`/`onKeyDown`
- [ ] `review/DefectsTable.tsx` 的 `<Fragment key={i}>` 改用稳定 key
- [ ] `review/ScoreCard.tsx` 的评分块含 `role="meter"` + `aria-valuenow/min/max` + `aria-label`
- [ ] 在 Chrome DevTools 的 Accessibility 面板中，缺陷展开行可被键盘 Tab 聚焦且 Enter/Space 可触发展开

## 阶段八：UX 微交互增强

- [ ] `review/page.tsx` 与 `generate/page.tsx` 的 Card 容器含 `animate-in fade-in` 过渡
- [ ] 主操作按钮 disabled 时通过 `aria-describedby` 关联下方 hint，hint 文案明确说明原因
- [ ] `kb/SearchPanel.tsx` 查询输入失焦校验，长度 < 1 时显示红字提示
- [ ] `OutputFormatSelector.tsx` 已选格式卡片角标显示 `Check` 图标
- [ ] `components/ui/sonner.tsx` 配置了 success/error/warning/info 四档样式（含图标 + 关闭按钮）
- [ ] success toast 4s 自动消失，error toast 持续至手动关闭
- [ ] `TaskProgress` 含"取消任务"按钮，点击弹 `AlertDialog` 二次确认
- [ ] `TaskProgress` 在 `connected === false` 时显示 `warning` Badge"连接中断，重试中…"
- [ ] `TaskProgress` 重连成功后显示 `success` Badge"已重连"并 2s 后淡出
- [ ] `CodePanel.tsx` 复制按钮点击后文案切换"已复制"2s + toast.success
- [ ] `DownloadList.tsx` 下载按钮点击后显示"下载中…"2s + toast.success
- [ ] `review/page.tsx` 与 `generate/page.tsx` 支持 `Cmd/Ctrl+Enter` 提交
- [ ] `kb/page.tsx` 支持 `/` 键聚焦查询输入
- [ ] Esc 可关闭 Dialog/Sheet（shadcn 内置，已验证）
- [ ] `kb/ResultsList.tsx` 未搜索时 `EmptyState` 显示推荐查询示例，点击填入
- [ ] `review/page.tsx` 与 `generate/page.tsx` 未上传/未输入时显示"3 步上手"引导卡
- [ ] `app/page.tsx` 含"系统状态"卡片，调用 `GET /health`，加载/失败态用 `States`
- [ ] 工作台入口卡片不再重复 sidebar 描述文案，含图标 + 进入按钮 + 价值主张

## 阶段九：全面实际测试（必须完整执行）

### Task 18: 静态检查与单元测试
- [ ] `npm run lint` 退出码 0（warnings 不阻塞，critical 已修复）
- [ ] `npx tsc --noEmit` 退出码 0
- [ ] `npm run build` 退出码 0，bundle 大小已记录
- [ ] `npx vitest run` 全部通过

### Task 19: 视觉回归矩阵（32 截图）
- [ ] `frontend/tmp_audit_logs/screenshots/` 下存在 32 张截图，命名为 `{page}-{theme}-{breakpoint}.png`
- [ ] 4 个页面（`/`、`/review`、`/generate`、`/kb`）× 2 主题（light/dark）× 4 断点（375/768/1024/1440）组合齐全
- [ ] 人工检查 32 张截图：布局无错位、文字无溢出、对比度可读
- [ ] 暗色下无残留 light 色（无 `bg-green-500` 等亮色硬编码）
- [ ] 移动端（375px）抽屉可开关

### Task 20: 功能链路端到端实测（5 条主链路）
- [ ] `/review` 拖拽上传链路：上传→选规范→提交→WS 进度→结果→键盘展开缺陷→下载 HTML→重新发起，全通过
- [ ] `/review` 点击上传链路：与拖拽一致
- [ ] `/generate` 自然语言链路：输入→选格式→提交→WS 进度→结果→编辑代码→重新执行→多轮修改，全通过
- [ ] `/generate` 草图链路：拖拽 + 点击两种方式均通过
- [ ] `/kb` 链路：列规范→重建索引→查询→过滤→检索→条款卡片→清空→推荐示例点击填入，全通过
- [ ] `/` 链路：系统状态卡片加载→显示连通性→工作台入口跳转，全通过
- [ ] 每条链路截图与网络请求证据已保存

### Task 21: 交互专项 + 异常路径 + a11y + 跨浏览器
- [ ] 主题切换持久化（刷新后保持）已验证
- [ ] 移动端抽屉开关已验证
- [ ] Cmd+Enter 提交已验证
- [ ] Esc 关闭 Dialog 已验证
- [ ] `/` 聚焦搜索已验证
- [ ] 复制代码反馈（"已复制"2s）已验证
- [ ] 下载反馈（loading 2s）已验证
- [ ] 取消任务二次确认已验证
- [ ] Toast 自动消失（success 4s / error 持续）已验证
- [ ] 异常路径 1：Offline 提交 → 错误 toast → Online 重试，已验证
- [ ] 异常路径 2：WS 阻断 5s → "连接中断" → 恢复"已重连" → 任务继续，已验证
- [ ] 异常路径 3：上传超限文件 → inline 错误 + toast，已验证
- [ ] 异常路径 4：后端 422 → toast 显示可读 detail，已验证
- [ ] 异常路径 5：轮询超时 → "获取结果超时" + "重试"按钮，已验证
- [ ] `@axe-core/playwright` 扫描 4 页面，critical 违规数 = 0
- [ ] `@axe-core/playwright` 扫描 4 页面，serious 违规数 ≤ 3 且每项有记录
- [ ] Chrome DevTools Performance 面板记录每页 LCP/CLS/INP，已填入报告
- [ ] Chrome / Edge / Firefox 三浏览器 `/review` 主链路均通过，差异已记录

### Task 22: 验证报告
- [ ] `frontend/tmp_audit_logs/frontend_polish_verification_report.md` 存在且内容完整
- [ ] 报告含测试矩阵表、截图清单、5 条主链路通过情况、交互专项结果、异常路径结果、a11y 扫描结果、性能基线、跨浏览器差异、问题列表与修复记录
- [ ] 报告含三项明确结论："功能无异常" / "各页面显示正常" / "所有交互正常"
- [ ] 任一结论不达标已回到对应 Task 修复后重测

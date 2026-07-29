# AI驱动工程设计辅助系统 Spec

## Why

机械/工程设计领域长期面临两个核心痛点：

1. **图纸审查效率低、漏审率高**：传统人工审图依赖"老师傅"经验判断，对 GB/T 1182（形位公差）、GB/T 4457.4（尺寸注法）、GB/T 17450（图线）、GB/T 18229（CAD工程制图规则）等规范的核对耗时且易漏；CoLab AutoReview、PKPM-AIChecker、InspectMind、数匠云等商业/学术产品已验证 AI 审图的市场价值，但大多面向建筑/施工领域，机械装配、形位公差、GD&T 等场景仍缺乏可定制、可私有化部署的解决方案。
2. **CAD 建模门槛高**：SolidWorks 等专业软件命令繁杂，非专业人员难以快速产出参数化模型；Zoo Text-to-CAD、Text-to-CadQuery、CAD-HLLM、AssemCAD、VideoCAD 等 2025-2026 年的研究成果证明，自然语言→可执行 CAD 代码（CadQuery / OpenSCAD / SolidWorks API 调用序列）的范式已具备工程化可行性，但缺少面向企业级、支持 SolidWorks 原生文件（SLDPRT/SLDASM）输出的整合方案。

本项目旨在构建一套可私有化部署、面向机械工程设计的"AI驱动工程设计辅助系统"，提供智能审图与智能生成两大核心能力，降低设计门槛、提升合规性、缩短返工周期。

## What Changes

本项目从零构建一个全新的全栈系统，主要交付内容：

- **新增 智能审图模块**：接受 SolidWorks 原生文件（SLDPRT/SLDASM）、CAD 源文件（DWG/DXF）、PDF 或截图作为输入，输出合规性评分、缺陷列表、定位标注与具体修改建议；用户可一键触发"基于缺陷的图纸优化"流程，由智能生成模块协同产出修订后的图纸。
- **新增 智能生成模块**：接受自然语言描述或手绘草图作为输入，输出可编辑的 CAD 文件（DXF/STEP/IGES）或 SolidWorks 原生文件（SLDPRT/SLDASM）。
- **新增 工程规范知识库**：构建 GB/JB/ISO 国标/行标/国际标准条目的结构化知识库与向量检索能力，作为审图与生成模块的合规推理基础。
- **新增 多模态图纸理解管线**：图像预处理 → 区域检测 → 区域受限 OCR → 几何/拓扑/语义分层解析 → 结构化数据转译，覆盖"感知→语义→工程语义"四层认知框架。
- **新增 CAD 文件解析与生成底座**：基于 ezdxf + ODA File Converter + OpenCASCADE（pythonOCC）+ FreeCAD + CadQuery 的多层级 CAD 处理栈；SolidWorks 原生文件通过 SolidWorks API（C#/.NET 或 Python win32com）操作。
- **新增 Web 后端服务 + 桌面/插件前端**：FastAPI 后端 + Celery 任务队列 + React 管理后台 + 可选 SolidWorks Add-in。
- **新增 私有化部署能力**：支持本地 GPU 推理、本地化规范知识库、企业数据不出域。

无 BREAKING 变更（绿地项目）。

## Impact

- **Affected specs**: 无（首个 spec）
- **Affected code**: 全新项目，主要模块包含：
  - `backend/`：FastAPI 服务、Celery Worker、CAD 解析/生成引擎、SolidWorks API 桥接
  - `ai/`：多模态理解、LLM 推理、RAG 知识库、向量检索
  - `kb/`：国标/行标知识库构建与维护工具
  - `frontend/`：React Web 控制台
  - `solidworks_addin/`（可选）：C# SolidWorks 插件
  - `infra/`：Docker Compose、模型部署、ODA/OpenCASCADE/SolidWorks 运行时依赖
- **External dependencies**: SolidWorks（生成 SLDPRT/SLDASM 必需，需许可证）、ODA File Converter（免费）、OpenCASCADE（LGPL）、FreeCAD（LGPL）、ezdxf（MIT）、CadQuery（Apache 2.0）、Python/C# 工具链、LLM 推理服务（开源模型如 Qwen2.5-VL / GLM-4V，或商业 API）、向量数据库（Qdrant/Milvus）。

---

## 调研与对标分析

本节为深度技术调研结论，作为后续选型依据。所有结论来源于实际查询（遵循"以认真查询为荣，以瞎猜接口为耻"原则），关键参考来源见末尾。

### 1. AI 智能审图领域对标

| 产品/项目 | 类型 | 输入 | 核心技术 | 借鉴价值 |
|---|---|---|---|---|
| **CoLab AutoReview**（加拿大，2025） | 商业 SaaS | Creo/NX/SolidWorks/CATIA 2D/3D | 自研 ML + 历史 DES 数据学习，几何/元数据/文本/图像多模态分析 | 多源数据融合、DES 决策过程沉淀、跨 CAD 平台支持 |
| **PKPM-AIChecker**（构力科技） | 商业，本地化 | 建筑 CAD（DWG） | 二维图纸智能审查、5 分钟单体审查、CAD 端边审边改 | "边审边改"工作流、本地化离线部署、图层配置与嵌套块识别 |
| **InspectMind**（YC W24） | 商业云 | 施工图 PDF | 多模态 OCR + 向量几何 + callout 图谱 + 约束空间检查 + RAG 代码解释 | 跨图纸引用关系建模、callout graph、RAG 规范推理、无硬编码规则 |
| **数匠云 AI CAD 智能审图** | 商业，本地化 | 工程多专业 CAD | 工程专属视觉识别算法 + 深度学习 + 国标对标 | 国标强条筛查、本地化离线、问题可视化定位 |
| **BeesFPD / BumbleBee（图形大模型）** | 商业 | 建筑施工图 | BoE-Vector 识别 + BoE-Parse 解析 + BumbleBee-Know 规范推理 + BumbleBee-Gen 自动布置 | "识别→解析→推理→生成→输出可编辑 DWG"闭环管线 |
| **BLUEPRINT**（Oak Ridge NL，2026） | 学术开源 | 工程图纸档案（混合格式） | 区域检测 + 区域受限 VLM OCR + 标识符归一化 + 混合稀疏/密集检索 + 区域级重排 | 大规模图纸档案的结构化元数据生成、检索增强 |

**关键洞察**：
- 通用多模态大模型（GPT-4V/Claude/Gemini）擅长 OCR 与布局理解，但**几何精度天然不足**；市面"一键审图"产品背后普遍挂载传统几何计算引擎，LLM 仅作交互与规则判断。
- 行业共识的"混合智能"四步法：**几何引擎预处理 → 结构化数据转译 → 大模型逻辑推理 → 报告生成与闭环**。
- 工程图纸理解四层认知框架（智绘工软提出）：① 图像文字层 ② 几何符号层 ③ 拓扑关系层 ④ 工程语义层；判断系统"懂图纸"的标准是能否输出**带坐标、带属性、带关系的结构化结果**。

### 2. AI 生成 CAD 领域对标

| 产品/项目 | 类型 | 输入 | 输出 | 核心技术 | 借鉴价值 |
|---|---|---|---|---|---|
| **Zoo Text-to-CAD**（KittyCAD） | 商业（UI 开源） | 自然语言 Prompt | 3D 模型 + KCL 代码 | LLM 生成 KCL（KittyCAD Modeling Language）→ 内核执行 | 文本→DSL→CAD 的轻量范式、UI/UX 参考 |
| **Text-to-CadQuery**（ASU，2025） | 学术开源 | 自然语言 | CadQuery Python 代码 | 170K CadQuery 注释微调 6 个开源 LLM，top-1 exact match 69.3%，Chamfer Distance ↓48.6% | 直接生成 Python CAD 代码，复用 LLM 的 Python 能力，无需中间表示 |
| **CAD-HLLM**（PMLR 304，2025） | 学术 | 自然语言 | CAD 命令序列 | 分层 LLM：Plan Generator（高层符号计划）+ Parameter Completor（参数化命令）+ 集成选择 | 分层规划思路，提升参数精度与形状相似度 |
| **AssemCAD**（上海 AI 实验室，2026） | 学术 | 自然语言 | 装配体（多零件 + mates） | axiom-grounded：类型化零件 + 几何 port + 可执行 mate + 工程公理；确定性验证管线 | 装配体生成范式、公理化可验证规范 |
| **VideoCAD**（MIT，2025） | 学术 | 2D 草图 | 3D 模型（CAD 软件内） | 41K 视频训练 UI Agent，模拟键鼠操作 CAD 软件 | UI Agent 范式，可复用现有 CAD 软件（含 SolidWorks）的全部能力 |
| **GenCAD / Sketch2CAD / Free2CAD / CADrawer / CADAssistant** | 开源 | 手绘草图/照片 | 3D 实体/参数化 CAD 脚本 | Transformer + 扩散模型 / VLM 解析几何 → FreeCAD 脚本 | 草图→CAD 的多种路径，从轮廓提取到 VLM 驱动 |

**关键洞察**：
- 两条主流技术路径：① **生成 CAD 代码/DSL**（CadQuery/OpenSCAD/KCL）→ 执行生成模型；② **UI Agent 模拟人操作 CAD 软件**。前者轻量可控，后者可触达 SolidWorks 全部原生能力。
- LLM 生成 Python/CadQuery 代码是当前性价比最高的路径，因 LLM 已具备 Python 与空间推理能力。
- AssemCAD 的"公理化可验证装配规范"为生产级装配生成提供了可解释、可复用、可验证的范式。

### 3. SolidWorks 二次开发技术调研

SolidWorks API 基于 COM（Component Object Model）技术，提供完整对象模型（SldWorks → ModelDoc2 → PartDoc/AssemblyDoc/DrawingDoc → FeatureManager 等）。

| 语言 | 调用方式 | 优势 | 劣势 | 适用场景 |
|---|---|---|---|---|
| **C++** | 直接 COM | 高性能、底层控制 | 开发难度高 | 高性能需求 |
| **C# / VB.NET** | COM 互操作（SolidWorks.Interop.sldworks / swconst） | 功能全面、编译型高性能、生态丰富、可开发 Add-in/EXE/Web | 学习曲线陡峭、需 VS | **企业级推荐**：插件、外部集成、Web 后端 |
| **VBA** | 内置 | 入门低、宏录制 | 功能有限、性能差 | 简单宏、临时验证 |
| **Python** | win32com / pywin32（Dispatch "SldWorks.Application"） | 语法简洁、AI 生态融合 | 解释型性能、COM 调用细节繁琐 | **AI 管线集成推荐**：脚本驱动、自动化任务 |

**关键 API 能力**（已通过查询确认，遵循"以瞎猜接口为耻"原则）：
- `swApp.OpenDoc6 / NewDocument`：打开/创建 SLDPRT/SLDASM/SLDDRW
- `ModelDoc2.FeatureManager.FeatureExtrusion2`：拉伸特征
- `SketchManager.CreateCenterRectangle / InsertSketch`：草图绘制
- `ModelDoc2.SaveAs3`：保存为 SLDPRT 或导出 STEP/IGES/STL
- `PartDoc.GetFirstFeature / Feature.GetNextFeature`：特征树遍历（用于审图）
- `ModelDoc2.Extension.SelectByID2`：选择图元
- `swDocumentTypes_e`：swDocPART=1, swDocASSEMBLY=2, swDocDRAWING=3
- 通过 `ExportToPdf` 或 eDrawings API 可输出审图批注

**部署约束**：SolidWorks 原生文件（SLDPRT/SLDASM）的生成与编辑**必须**在装有 SolidWorks 的 Windows 机器上通过 API 完成；不可绕过。需采用"AI 服务无状态 + SolidWorks Worker 有状态"的分离架构。

### 4. CAD 文件解析/生成底座调研

| 库/工具 | 语言 | 协议 | 能力 | 适用 |
|---|---|---|---|---|
| **ezdxf** | Python | MIT | DXF 读写、图层/块/标注/实体全覆盖 | DXF 解析与生成主力 |
| **ODA File Converter** | 命令行 | 免费（需注册） | DWG↔DXF 批量转换，无需 AutoCAD，支持 R12-R2018 | DWG 输入前置转换 |
| **ezdxf.addons.odafc** | Python | ezdxf 扩展 | 包装 ODA File Converter，Python 内统一接口 | DWG 流程封装 |
| **OpenCASCADE（OCCT）/ pythonOCC** | C++/Python | LGPL | B-Rep 几何内核、NURBS、布尔、STEP/IGES/BRep 读写 | 几何计算与验证引擎 |
| **FreeCAD** | C++/Python | LGPL | 参数化建模、可作为 Python 模块、多格式（STEP/IGES/STL/DXF/DWG） | 复杂 CAD 操作与格式转换 |
| **CadQuery** | Python | Apache 2.0 | 基于 OpenCASCADE 的参数化 CAD 脚本语言 | AI 生成 CAD 代码的执行内核 |
| **OpenSCAD** | 自有 | GPL | CSG 建模、脚本式 | 简单零件生成 |
| **ACadSharp** | C# | MIT | DWG/DXF 全版本读写 | .NET 栈替代方案 |
| **pyautocad / win32com（AutoCAD）** | Python | 商业 | 通过 AutoCAD COM 操作 DWG | 已有 AutoCAD 环境的企业 |

**关键决策**：
- DWG 处理：ezdxf（DXF）+ ODA File Converter（DWG↔DXF）作为统一管线，无需 AutoCAD 授权。
- 几何验证：pythonOCC / FreeCAD 作为几何计算引擎，与 LLM 解耦——LLM 不算坐标，几何引擎不算语义。
- AI 生成代码执行：CadQuery（首选，Python 生态融合）+ SolidWorks API（生成 SLDPRT 时必选）。

### 5. 规范知识库与多模态理解调研

**国标体系**（基于查询确认）：
- 顶层：GB/T 18229-2023《CAD 工程制图规则》、GB/T 50001-2023《房屋建筑制图统一标准》、GB/T 13361《技术制图 通用术语》
- 图线/字体/比例：GB/T 17450《技术制图 图线》、GB/T 14665《机械工程 CAD 制图规则》
- 视图/标注：GB/T 17452-17453《剖面/断面图》、GB/T 4457.4《尺寸注法》、GB/T 4458.4《尺寸公差注法》
- 公差：GB/T 1182《形位公差》、GB/T 1804《一般公差》、GB/T 131《表面结构表示法》
- 装配/明细：GB/T 4458.2《明细栏》、GB/T 4459《简化画法》
- 行业：JB/T 8836（机械加工工艺）、HG（化工）、QC（汽车）等
- 国际：ISO 128（技术制图通用原则）、ISO 1101（几何公差）

**多模态图纸理解管线**（综合 BLUEPRINT + 智绘工软 + BeesFPD）：
1. 模态路由：矢量 CAD / 光栅扫描 / PDF 分流
2. 区域检测：标题栏、修订表、明细栏、视图区、标注区（YOLO/DETR + LayoutLMv3）
3. 区域受限 OCR：PaddleOCR + VLM 双重识别（避免文字/线条重叠失败）
4. 标识符归一化：图号/版本/件号/材料牌号结构化
5. 几何/拓扑/语义分层解析：线段→符号→连接关系→工程语义
6. 结构化数据转译：输出 JSON/Markdown，剔除冗余几何，仅保留语义信息
7. LLM 推理：基于 RAG 检索规范条文，双重验证（关键结论必须引用原文）

**LLM 选型**（截至 2026-07，国内可商用、支持多模态与 Function Calling 的开源/开放模型）：
- 多模态理解：Qwen2.5-VL-72B / GLM-4V-9B / InternVL2.5（开源可私有部署）
- 推理与代码生成：Qwen2.5-Coder / DeepSeek-V3 / GLM-4.5（开源）
- 商业 API 备选：Claude 3.5 Sonnet / GPT-4o / Gemini 2.0（合规与精度更高，但有数据出域风险）

---

## 技术栈选型

基于"以复用现有为荣，以创造接口为耻"原则，优先复用成熟开源组件：

### 后端
- **主语言**：Python 3.11+（AI/CAD 生态融合）
- **Web 框架**：FastAPI（异步、OpenAPI 自动文档）
- **任务队列**：Celery + Redis（CAD/SolidWorks 长任务异步化）
- **数据库**：PostgreSQL（结构化业务数据）+ Qdrant（向量检索）
- **对象存储**：MinIO（图纸与生成产物）
- **运行时**：Docker Compose（开发与中等规模部署）+ Kubernetes（可选）

### CAD 处理
- **DXF**：ezdxf（解析与生成主力）
- **DWG**：ODA File Converter + ezdxf.addons.odafc（DWG↔DXF）
- **几何内核**：pythonOCC（OpenCASCADE Python 绑定）
- **参数化建模**：CadQuery（AI 生成代码执行）
- **格式转换/复杂操作**：FreeCAD（作为 Python 模块）
- **SolidWorks 桥接**：Python win32com（AI 管线侧）+ C#/.NET Add-in（SolidWorks 客户端侧，可选）

### AI
- **多模态理解**：Qwen2.5-VL-72B（私有部署）或 Claude 3.5 Sonnet（API）
- **LLM 推理/代码生成**：Qwen2.5-Coder-32B / DeepSeek-V3（私有部署）
- **OCR**：PaddleOCR（中文工程图优化）
- **区域检测**：YOLOv11 / RT-DETR（图纸区域检测微调）
- **文档理解**：LayoutLMv3（版面分析）
- **Embedding**：bge-m3（中英双语，用于规范 RAG）
- **向量库**：Qdrant（性能与易用性平衡）
- **RAG 框架**：LlamaIndex（结构化文档检索能力强）
- **推理服务**：vLLM（高吞吐）+ Ollama（本地开发）

### 前端
- **Web 控制台**：React 18 + Next.js 14（App Router）+ TypeScript + Tailwind CSS + shadcn/ui
- **图纸查看**：Autodesk Forge Viewer（云）/ LibreCAD Web / 自研 SVG 渲染（轻量）
- **状态管理**：TanStack Query（服务端状态）+ Zustand（客户端状态）
- **SolidWorks 插件**（可选 P1）：C# + SolidWorks API + WinForms/WPF

### 工程规范知识库
- **结构化存储**：PostgreSQL（条文-条款-版本）+ Qdrant（语义检索）
- **构建工具**：自研 Python 工具链（PDF→结构化条文→向量化）
- **覆盖范围**（P0）：GB/T 1182、GB/T 4457.4、GB/T 17450、GB/T 1804、GB/T 131、GB/T 18229
- **覆盖范围**（P1）：GB/T 4458 系列、GB/T 14665、ISO 128、ISO 1101
- **覆盖范围**（P2）：JB/T 8836 等行业规范、企业自定义规范

---

## 系统架构设计（初步）

```
┌─────────────────────────────────────────────────────────────────┐
│                    用户层（Web / SolidWorks Add-in）              │
│   React 控制台        审图工作台        生成工作台     SW 插件      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTPS / WebSocket
┌──────────────────────────▼──────────────────────────────────────┐
│                    API 网关（FastAPI）                            │
│   鉴权 │ 限流 │ 路由 │ 文件上传/下载 │ WebSocket 通知              │
└──┬──────────────┬──────────────┬──────────────┬─────────────────┘
   │              │              │              │
┌──▼─────┐  ┌────▼─────┐  ┌────▼─────┐  ┌────▼─────────┐
│审图服务│  │生成服务  │  │知识库服务│  │文件/CAD 服务 │
│(Python)│  │(Python) │  │(Python) │  │  (Python)    │
└──┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────────┘
   │             │             │             │
   └──────┬──────┴──────┬──────┘             │
          │             │                    │
   ┌──────▼──────┐ ┌────▼─────┐      ┌──────▼──────┐
   │ AI 推理层   │ │ RAG 引擎 │      │ CAD 引擎层  │
   │ vLLM/Ollama │ │ LlamaIndex│     │ ezdxf/ODA   │
   │ Qwen-VL/LLM │ │ Qdrant   │      │ pythonOCC   │
   └─────────────┘ └──────────┘      │ FreeCAD     │
                                     │ CadQuery    │
                                     └──────┬──────┘
                                            │
                                    ┌───────▼────────┐
                                    │ SolidWorks     │
                                    │ Worker Pool    │
                                    │ (Windows VM,   │
                                    │  win32com/.NET)│
                                    │  生成 SLDPRT    │
                                    └────────────────┘

异步任务：Celery + Redis    持久化：PostgreSQL + MinIO
```

**关键架构原则**：
1. **AI 服务无状态、SolidWorks Worker 有状态**：SolidWorks 必须运行在装有其许可证的 Windows 机器上，通过 Worker Pool 池化复用，避免每次启动开销。
2. **LLM 与几何引擎解耦**：LLM 不直接算坐标/角度，仅做语义理解与规则判断；几何校验交由 pythonOCC/FreeCAD 完成。
3. **混合智能管线**：审图严格遵循"几何预处理 → 结构化转译 → LLM 推理 → 双重验证 → 报告闭环"五步法。
4. **私有化优先**：所有 AI 模型与知识库均可本地部署，企业数据不出域；商业 API 作为可选增强。
5. **可观测性**：全链路 tracing（OpenTelemetry）、任务进度 WebSocket 推送、审查报告可溯源（每条结论引用规范原文 + 图纸坐标）。
6. **阶段化交付与硬门控**：项目严格按 P0 → P1 → P2 三阶段推进，每阶段完成后必须经过"自检 → 全面深入测试 → 阶段审核报告 → 用户书面批准"四步门控，**未获用户批准不得进入下一阶段**。

---

## 阶段交付与审批流程（HARD GATE）

本项目采用严格的阶段化交付模式，杜绝"心急跨阶段推进"。每个阶段必须完成以下四步门控，方可进入下一阶段：

### 阶段退出准则（四步门控）

1. **自检（Self-Check）**：开发完成后，由实施 Sub-Agent 对照本阶段 checklist 逐项自检，输出自检报告（每项 checkpoint 状态 + 证据链接：代码位置/测试日志/截图）。
2. **全面深入测试（Deep Testing）**：交由独立验证 Sub-Agent 执行，**不限于 happy path**，必须覆盖：
   - 功能测试：每个 Scenario 至少 1 个正向 + 2 个边界 + 1 个异常用例
   - 集成测试：跨模块接口、消息队列、文件流端到端验证
   - 性能测试：本阶段声明的 SLA（如 P0 审图 ≤ 5 分钟）实测验证
   - 安全测试：沙箱逃逸、文件上传越权、注入攻击等基础渗透
   - 兼容性测试：多版本 DWG/SolidWorks/浏览器覆盖
   - 数据完整性测试：异常中断后数据可恢复、无泄漏
3. **阶段审核报告（Stage Review Report）**：汇总自检 + 测试结果，输出标准化报告（含未达标项、修复计划、风险变化），交付用户。
4. **用户书面批准（Explicit User Approval）**：用户审阅阶段审核报告后**明确书面批准**，方可启动下一阶段任务。**任何"默认通过"或"沉默视为同意"均禁止**。

### 各阶段交付物清单

#### 阶段一（P0）交付物
- 可运行 MVP：DWG/DXF 审图 + 自然语言生成 STEP 两条闭环
- 工程规范知识库 v0（6 部 GB/T 规范）
- Web 控制台 v0
- 自检报告 + 测试报告 + 阶段审核报告
- **HARD STOP：等待用户批准方可进入 P1**

#### 阶段二（P1）交付物
- SolidWorks 原生文件（SLDPRT/SLDASM）读写能力
- PDF/截图审图精度增强（区域检测 + 区域受限 OCR）
- 装配体生成（AssemCAD 范式）
- 审图→生成协同闭环
- 草图转 CAD
- 可选 SolidWorks Add-in
- 自检报告 + 测试报告 + 阶段审核报告
- **HARD STOP：等待用户批准方可进入 P2**

#### 阶段三（P2）交付物
- 私有化部署完善（离线安装包）
- 企业规范自定义
- 规范知识库扩展（行业/国际规范）
- 可观测性仪表盘
- 性能优化
- 完整文档与交付物
- 自检报告 + 测试报告 + 最终验收报告
- **HARD STOP：等待用户最终验收**

### 禁止行为

- ❌ 跨阶段并行启动任务（如 P0 未批准即启动 P1 SolidWorks 集成）
- ❌ 跳过测试直接申请批准
- ❌ 用"部分通过"作为阶段完成依据
- ❌ 在用户未批准前修改本 spec 的阶段划分
- ❌ 将"用户未回复"解读为"默认同意"

---

## ADDED Requirements

### Requirement: 智能审图模块

系统 SHALL 提供智能审图能力，接受 SolidWorks 原生文件（SLDPRT/SLDASM）、CAD 源文件（DWG/DXF）、PDF 或图片（PNG/JPG）作为输入，输出合规性评分、缺陷列表、定位标注与具体修改建议。

#### Scenario: 上传 SolidWorks 零件图进行审图
- **WHEN** 用户上传 SLDPRT 文件并选择"机械制图规范审查"
- **THEN** 系统通过 SolidWorks API 提取特征树、尺寸标注、形位公差、表面粗糙度、技术要求
- **AND** 系统将提取结果结构化为 JSON（坐标/属性/关系）
- **AND** 系统 RAG 检索相关 GB/T 条文
- **AND** LLM 基于结构化数据 + 规范条文输出缺陷列表，每条缺陷包含：类别、严重等级、位置坐标、违规条文引用、修改建议
- **AND** 系统输出合规性评分（0-100）与可下载的审查报告（PDF/HTML）
- **AND** 全流程在 5 分钟内完成（中等复杂度零件）

#### Scenario: 上传 DWG/DXF 工程图进行审图
- **WHEN** 用户上传 DWG 文件
- **THEN** 系统通过 ODA File Converter 转 DXF，ezdxf 解析图层/实体/标注/标题栏
- **AND** 渲染为图片送多模态 VLM 进行区域检测与 OCR
- **AND** 融合矢量数据与视觉理解结果，输出结构化语义对象
- **AND** 后续流程同 SLDPRT（RAG → LLM → 缺陷列表 → 报告）

#### Scenario: 上传 PDF 或截图进行审图
- **WHEN** 用户上传扫描版 PDF 或图片
- **THEN** 系统进行去噪/校正预处理
- **AND** 多模态 VLM 完成区域检测 + 区域受限 OCR + 标识符归一化
- **AND** 重建几何/拓扑/语义三层结构
- **AND** 后续流程同上，但精度等级标注为"参考级"（区别于矢量级）

#### Scenario: 一键触发图纸优化
- **WHEN** 用户在审图结果页点击"基于缺陷优化图纸"
- **THEN** 系统将缺陷列表 + 原图纸信息传入智能生成模块
- **AND** 生成模块产出修订后的 CAD 文件（优先 SLDPRT，其次 DXF/STEP）
- **AND** 系统对修订后文件自动复审，输出修订前后对比报告

#### Scenario: 审图可溯源
- **WHEN** 用户点击任意一条缺陷
- **THEN** 系统展示该缺陷对应的规范原文条款、图纸定位高亮、LLM 推理链路
- **AND** 用户可标记"误报"或"采纳"，反馈进入知识库迭代

---

### Requirement: 智能生成模块

系统 SHALL 提供智能生成能力，接受自然语言描述或手绘草图作为输入，输出可编辑的 CAD 文件（DXF/STEP/IGES）或 SolidWorks 原生文件（SLDPRT/SLDASM）。

#### Scenario: 自然语言生成简单零件
- **WHEN** 用户输入"设计一个法兰盘，外径 100mm，内径 50mm，6 个均布孔直径 10mm，厚度 10mm"
- **THEN** LLM 将需求分解为参数化建模步骤
- **AND** 生成 CadQuery Python 代码并执行，输出 STEP/IGES/STL
- **AND** 若用户选择"生成 SolidWorks 文件"，系统调用 SolidWorks Worker 通过 API 重建特征树，输出 SLDPRT
- **AND** 生成后自动调用审图模块进行合规性自检

#### Scenario: 自然语言生成装配体
- **WHEN** 用户输入"设计一个由轴、轴承、轴承座、端盖组成的传动组件"
- **THEN** 系统采用 AssemCAD 范式：先构造装配规范（类型化零件 + port + mate + 工程公理）
- **AND** 为每个零件合成参数化组件工厂
- **AND** 确定性验证管线检查接口有效性、干涉一致性、图连通性、自由度约束
- **AND** 输出 SLDASM + 明细栏 + 装配图

#### Scenario: 手绘草图转 CAD
- **WHEN** 用户上传手绘草图图片
- **THEN** 系统通过 VLM 解析几何特征（圆/线/矩形/孔/倒角）
- **AND** 生成 CadQuery 代码或 SolidWorks API 调用序列
- **AND** 输出可编辑 DXF 或 SLDPRT
- **AND** 标注"草图级精度"，提示用户人工校准尺寸

#### Scenario: 生成代码可解释可编辑
- **WHEN** 用户查看生成结果
- **THEN** 系统展示底层 CadQuery/SolidWorks API 代码
- **AND** 用户可直接编辑代码并重新执行
- **AND** 系统记录参数化版本历史，支持回滚

#### Scenario: 多轮对话修改
- **WHEN** 用户在生成结果后输入"把外径改为 120mm，孔数改为 8"
- **THEN** 系统 diff 修改意图，仅调整对应参数与特征
- **AND** 增量更新模型，无需完全重建

---

### Requirement: 工程规范知识库

系统 SHALL 构建可向量化检索的国标/行标/国际标准规范知识库，作为审图与生成模块的合规推理基础。

#### Scenario: 规范条文结构化存储
- **WHEN** 知识库构建工具导入 GB/T 1182-2018 PDF
- **THEN** 系统提取条款编号、标题、正文、表格、图示、引用关系
- **AND** 存储为 PostgreSQL 结构化记录 + Qdrant 向量
- **AND** 支持版本管理（同规范多版本并存）

#### Scenario: RAG 检索
- **WHEN** 审图模块查询"圆度公差标注要求"
- **THEN** 系统检索相关 GB/T 1182 条款
- **AND** 返回条文原文 + 出处 + 适用场景
- **AND** 关键结论必须引用原文，杜绝 LLM 幻觉

---

### Requirement: 私有化部署与数据安全

系统 SHALL 支持完全私有化部署，企业数据不出域。

#### Scenario: 离线部署
- **WHEN** 企业选择私有化部署
- **THEN** 所有 AI 模型（LLM/VLM/Embedding/OCR）支持本地 GPU 推理
- **AND** 规范知识库本地化
- **AND** SolidWorks Worker 在企业内网运行
- **AND** 无任何外部 API 调用

#### Scenario: 商业 API 增强模式
- **WHEN** 企业选择商业 API 增强（如 Claude 3.5）
- **THEN** 系统明确告知数据出域范围
- **AND** 仅发送脱敏文本，不发送原始图纸
- **AND** 用户可随时切换回纯本地模式

---

## 关键风险与应对预案

| 风险 | 等级 | 应对预案 |
|---|---|---|
| **R1: SolidWorks 原生文件格式闭源**——SLDPRT/SLDASM 必须依赖 SolidWorks API，无法纯开源解析 | 高 | 架构上分离 AI 服务（无状态）与 SolidWorks Worker（有状态、Windows + SolidWorks 许可证）；Worker 池化复用降低成本；提供"无 SolidWorks 降级模式"输出 STEP/IGES + DXF |
| **R2: LLM 在几何精度上的天然缺陷**——算坐标/角度/面积不可靠 | 高 | 严格"混合智能"架构：LLM 不算几何，几何引擎（pythonOCC/FreeCAD）不算语义；几何校验全部走确定性算法 |
| **R3: LLM 幻觉**——编造规范条款或对模糊区域虚假合格 | 高 | RAG 强制检索 + 双重验证机制：关键结论必须引用规范原文条款编号；用户反馈（误报/采纳）持续迭代知识库 |
| **R4: 国标规范复杂、版本繁多、跨规范引用** | 中 | 知识库结构化（条文-版本-引用关系），支持多版本并存与冲突提示；与权威标准出版方合作或采购结构化规范数据 |
| **R5: 多模态 VLM 对工程图理解精度不足**——文字与线条重叠、字体多样、符号变体 | 中 | 区域检测 + 区域受限 OCR 双重识别；专用微调（YOLOv11 检测标题栏/标注/视图区，PaddleOCR 中文优化）；精度分级标注（矢量级 vs 参考级） |
| **R6: SolidWorks API 性能与稳定性**——COM 调用易超时/Crash，长任务阻塞 | 中 | Worker 进程隔离 + 任务超时 + 自动重试 + 健康检查；SolidWorks 2024+ 支持 Background Processing 缓解 UI 阻塞 |
| **R7: 草图转 CAD 精度有限**——开源方案无法 100% 自动出工程级精确图纸 | 中 | 输出明确标注"草图级精度"，强制人工校准尺寸环节；优先支持标注完整的工程草图而非随手涂鸦 |
| **R8: 大型装配体上下文超 LLM 窗口** | 中 | 分层 RAG：先检索相关零件/规范，再局部推理；长上下文模型（Qwen2.5-72B 支持 128K）+ 摘要压缩 |
| **R9: 数据安全与企业 IP 顾虑** | 高 | 私有化部署为默认选项；商业 API 模式仅发送脱敏文本；通过等保三级/ISO 27001 认证（运营目标） |
| **R10: AI 生成代码执行安全**——CadQuery/Python 代码可能含恶意调用 | 中 | 沙箱执行（Docker 容器 + 资源限制 + 网络隔离 + 仅白名单 API）；生成代码静态扫描 |
| **R11: SolidWorks 许可证成本** | 中 | 仅在最终生成 SLDPRT/SLDASM 时调用 SolidWorks；中间过程使用 CadQuery/FreeCAD；提供"无 SolidWorks"输出路径 |
| **R12: 跨平台一致性**（Windows SolidWorks vs Linux AI 服务） | 中 | Docker 容器化 AI 服务（Linux）；SolidWorks Worker 独立 Windows 节点；通过消息队列解耦 |

---

## 关键参考来源

- CoLab AutoReview：https://www.cechina.cn/m/article.aspx?ID=79730
- PKPM-AIChecker：https://product.pkpm.cn/productDetails?productId=37
- InspectMind (YC W24)：https://news.ycombinator.com/item?id=46219386
- 数匠云 AI CAD 智能审图：https://m.sohu.com/a/1040808124_121889246/
- BLUEPRINT (Oak Ridge NL, 2026)：https://arxiv.org/pdf/2602.13345
- 工程图纸理解四层认知框架：https://m.sohu.com/a/1033577577_122155911/
- 图形大模型 BeesFPD：https://segmentfault.com/a/1190000047942262
- Text-to-CadQuery (ASU, 2025)：https://arxiv.org/html/2505.06507v1/
- Text2CAD 数据集：https://www.selectdataset.com/dataset/d697f13444db3560bcca7d912d4c6109/Text2CAD
- CAD-HLLM (PMLR 304, 2025)：https://proceedings.mlr.press/v304/zuo26a.html
- AssemCAD (上海 AI 实验室, 2026)：https://arxiv.org/html/2607.05123v1
- VideoCAD (MIT, 2025)：https://news.mit.edu/2025/new-ai-agent-learns-use-cad-create-3d-objects-sketches-1119
- Zoo Text-to-CAD：https://zoo.dev / https://github.com/KittyCAD/text-to-cad-ui
- 草图转 CAD 开源项目分类：https://blog.csdn.net/weixin_42917352/article/details/163025448
- SolidWorks API 二次开发语言对比：https://juejin.cn/post/7552827123934887990
- Python + SolidWorks（pywin32）：https://docs.pingcode.com/baike/933309
- FreeCAD 特性（OpenCASCADE 内核）：https://www.freecad.org/features
- ezdxf + ODA File Converter：https://ezdxf.readthedocs.io/en/stable/addons/odafc.html
- GLM-4V-9B 工程图纸实战：https://blog.csdn.net/weixin_36304957/article/details/158029598
- DeepSeek 工程制图规范检查：https://www.php.cn/faq/1920461.html
- 企业级 CAD 制图标准化规范（GB/T 18229/50001/17450/1182/4457/1804 等）：https://wenku.csdn.net/doc/13wmyz6fzf

# eDrawings Export CLI

C# CLI 工具，使用 eDrawings EModelViewControl OCX 加载 SLDPRT/SLDASM 文件并导出 PNG 预览图。

## 编译

需要 .NET 8 SDK 和 eDrawings 安装（提供 EModelView.dll）。

```bash
cd backend/app/services/solidworks/edrawings_export
dotnet build -c Release
```

编译产物：`bin/edrawings_export.exe`

## 用法

```bash
edrawings_export.exe <input.sldprt|sldasm> <output.png> [--edrawings <path>]
```

## 依赖

- .NET 8 SDK
- eDrawings 2026（https://www.edrawingsviewer.com/）
- EModelViewControl OCX（eDrawings 安装时自动注册）

## 注意事项

- 此工具为骨架实现，实际 EModelViewControl API 调用可能因版本差异需要调整
- 加载文件使用 Thread.Sleep(2000) 等待，生产环境应使用事件回调
- 导出分辨率默认 1024×768，可按需调整

using System;
using System.IO;
using System.Threading;
using System.Windows.Forms;
using eDrawings.Interop.EModelViewControl;

namespace edrawings_export;

/// <summary>
/// eDrawings CLI 包装器：加载 SLDPRT/SLDASM 并导出 PNG 预览图。
///
/// 用法：edrawings_export.exe &lt;input.sldprt|sldasm&gt; &lt;output.png&gt; [--edrawings &lt;path&gt;]
///
/// 实现参考 CodeStack xPort 官方示例（eDrawings API 批量导出）：
/// https://jiaqiwang969.github.io/solidworks-GPT/zh-Hans/docs/codestack/edrawings-api/output/export/
///
/// 机制：EModelViewControl 是 ActiveX 控件，托管在 AxHost 中。
/// 加载文档通过 OpenDoc 异步触发 OnFinishedLoadingDocument 事件，
/// 然后调用 Save(outputPath, false, "") 导出，文件扩展名决定输出格式（.png → PNG）。
/// Save 是 eDrawings 内部渲染导出，不需要可见窗口（Form Minimized）。
///
/// 双保险机制：
/// - 主路径：COM 事件连接点（OnFinishedLoadingDocument → Save → OnFinishedSavingDocument）
/// - 兜底：Forms.Timer 轮询（检查 FileName 匹配 → Save → 检查输出文件存在）
///
/// 退出码：0=成功, 1=参数错误, 2=OCX 加载失败, 3=文档加载失败, 4=导出失败, 5=超时
/// </summary>
internal class Program
{
    private const int TIMEOUT_MS = 55000;
    private const int POLL_INTERVAL_MS = 500;

    // 轮询状态机
    private enum State { Loading, Saving, Done, Failed }

    private static string? _inputPath;
    private static string? _outputPath;
    private static int _exitCode = 1;
    private static string? _errorMessage;
    // 用 dynamic 后期绑定调用 COM 方法，绕过自生成互操作程序集可能的方法签名问题。
    // 互操作程序集（TypeLibConverter 生成）的 OpenDoc/Save 方法调用阻塞且不返回，
    // COM 事件连接点也不触发。用 dynamic 直接通过 IDispatch 调用 COM 方法。
    private static dynamic? _control;
    private static Form? _mainForm;
    private static System.Threading.Timer? _hardTimeoutTimer;
    private static System.Windows.Forms.Timer? _pollTimer;
    private static State _state = State.Loading;
    private static int _tickCount;
    // 防止 Save 被重复调用（事件 + 轮询可能同时触发）
    private static bool _saveCalled;

    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length < 2)
        {
            Console.Error.WriteLine(
                "用法: edrawings_export <input.sldprt|sldasm> <output.png> [--edrawings <path>]");
            return 1;
        }

        _inputPath = args[0];
        _outputPath = args[1];

        if (!File.Exists(_inputPath))
        {
            Console.Error.WriteLine($"输入文件不存在: {_inputPath}");
            return 1;
        }

        string? outDir = Path.GetDirectoryName(_outputPath);
        if (!string.IsNullOrEmpty(outDir))
        {
            Directory.CreateDirectory(outDir);
        }

        // 硬超时：线程池 Timer，不受消息泵阻塞影响
        _hardTimeoutTimer = new System.Threading.Timer(
            _ =>
            {
                Console.Error.WriteLine($"[trace] 超时 ({TIMEOUT_MS}ms)，状态={_state}，强制退出");
                Console.Error.Flush();
                Environment.Exit(5);
            },
            null, TIMEOUT_MS, Timeout.Infinite);

        try
        {
            Trace("创建 EDrawingsHost");
            var host = new EDrawingsHost();
            host.ControlLoaded += OnControlLoaded;

            _mainForm = new Form
            {
                ShowIcon = false,
                ShowInTaskbar = false,
                FormBorderStyle = FormBorderStyle.None,
                StartPosition = FormStartPosition.Manual,
                // Save 方法导出 OCX 渲染画面，需要足够大的客户区。
                // Minimized 窗口客户区极小（如 118x4），导致导出的 PNG 尺寸过小。
                // 用离屏位置 (-10000,-10000) 避免窗口可见，同时保持正常客户区大小。
                Location = new System.Drawing.Point(-10000, -10000),
                Size = new System.Drawing.Size(1024, 768),
            };
            _mainForm.Controls.Add(host);
            host.Dock = DockStyle.Fill;

            Trace("启动 ShowDialog（消息泵）");
            _mainForm.ShowDialog();

            Trace("ShowDialog 返回，清理");
            _hardTimeoutTimer.Dispose();
            _pollTimer?.Dispose();
            host.Dispose();
        }
        catch (Exception ex)
        {
            Trace($"异常: {ex}");
            Console.Error.WriteLine($"错误: {ex.Message}");
            Console.Error.Flush();
            return _exitCode == 1 ? 2 : _exitCode;
        }

        if (_exitCode == 0)
        {
            if (!File.Exists(_outputPath))
            {
                Console.Error.WriteLine($"导出声称成功但输出文件不存在: {_outputPath}");
                Console.Error.Flush();
                return 4;
            }
            Console.WriteLine($"导出成功: {_outputPath}");
        }
        else
        {
            Console.Error.WriteLine($"失败: {_errorMessage ?? "未知错误"}");
        }

        Console.Out.Flush();
        Console.Error.Flush();
        return _exitCode;
    }

    private static void Trace(string msg)
    {
        Console.Error.WriteLine($"[trace] {msg}");
        Console.Error.Flush();
    }

    private static void OnControlLoaded(EModelViewControl control)
    {
        Trace("OnControlLoaded: OCX 已加载");
        _control = control;

        // 订阅 COM 事件（官方互操作程序集应正确支持事件连接点）
        // 事件签名参考 xPort 官方实现：
        // - OnFinishedLoadingDocument(string fileName)
        // - OnFailedLoadingDocument(string fileName, int errorCode, string errorString)
        // - OnFinishedSavingDocument()
        // - OnFailedSavingDocument(string fileName, int errorCode, string errorString)
        try
        {
            control.OnFinishedLoadingDocument += OnDocLoadedEvent;
            control.OnFailedLoadingDocument += OnDocLoadFailedEvent;
            control.OnFinishedSavingDocument += OnDocSavedEvent;
            control.OnFailedSavingDocument += OnSaveFailedEvent;
            Trace("事件订阅完成（官方互操作程序集）");
        }
        catch (Exception ex)
        {
            Trace($"事件订阅异常（将依赖轮询）: {ex.Message}");
        }

        // 启动轮询定时器（兜底：若 COM 事件不触发，靠轮询检测 FileName 和文件存在）
        _pollTimer = new System.Windows.Forms.Timer { Interval = POLL_INTERVAL_MS };
        _pollTimer.Tick += PollTick;
        _pollTimer.Start();
        Trace("轮询定时器已启动");

        // 异步调用 OpenDoc，避免阻塞 OnControlLoaded
        // 参数与 xPort 官方实现一致：OpenDoc(file, false, false, false, "")
        _mainForm!.BeginInvoke(new Action(() =>
        {
            try
            {
                Trace($"BeginInvoke: 调用 OpenDoc: {_inputPath}");
                _control!.OpenDoc(_inputPath!, false, false, false, "");
                Trace("BeginInvoke: OpenDoc 已返回");
            }
            catch (Exception ex)
            {
                Trace($"BeginInvoke: OpenDoc 异常: {ex}");
                _errorMessage = $"OpenDoc 异常: {ex.Message}";
                _exitCode = 3;
                _state = State.Failed;
                CloseForm();
            }
        }));
        Trace("OpenDoc 已投递到消息队列");
    }

    /// <summary>轮询定时器：兜底检测文档加载状态和导出文件是否存在。</summary>
    private static void PollTick(object? sender, EventArgs e)
    {
        _tickCount++;
        if (_control == null || _state == State.Done || _state == State.Failed)
        {
            return;
        }

        // 防止 WinForms Timer 重入（COM 调用会泵送消息导致重入）
        if (_state == State.Saving)
        {
            // 检查输出文件是否存在
            if (File.Exists(_outputPath))
            {
                var fi = new FileInfo(_outputPath);
                if (fi.Length > 0)
                {
                    Trace($"轮询 #{_tickCount}: 导出文件已生成 ({fi.Length} bytes)");
                    _state = State.Done;
                    _exitCode = 0;
                    // 直接退出，避免 CloseActiveDoc COM 调用阻塞
                    Console.Out.Flush();
                    Console.Error.Flush();
                    Environment.Exit(0);
                }
            }

            if (_tickCount >= 80) // Save 后 40s 仍无文件
            {
                Trace($"轮询 #{_tickCount}: Save 后 40s 仍无输出文件");
                _errorMessage = "Save 调用后未生成输出文件";
                _exitCode = 4;
                _state = State.Failed;
                CloseForm();
            }
            return;
        }

        // State.Loading：检查文档是否已加载
        try
        {
            string fn = "";
            try { fn = (string)_control.FileName; }
            catch { /* OCX 可能未就绪 */ }

            // 规范化路径分隔符后再比较：OCX FileName 返回 backslash，
            // 但输入路径可能含 forward slash（如 Python 传入 d:/path/file.sldprt），
            // OrdinalIgnoreCase 比较不规范化分隔符，会导致匹配失败。
            string fnNorm = fn.Replace('/', '\\');
            string inputNorm = (_inputPath ?? "").Replace('/', '\\');
            if (!string.IsNullOrEmpty(fn) &&
                fnNorm.Equals(inputNorm, StringComparison.OrdinalIgnoreCase))
            {
                Trace($"轮询 #{_tickCount}: 文档已加载 (FileName={fn})，调用 Save");
                DoSave();
            }
            else
            {
                if (_tickCount % 4 == 0) // 每 2s 输出一次
                {
                    Trace($"轮询 #{_tickCount}: 等待加载 (FileName='{fn}')");
                }

                // Fallback：10s 后 FileName 仍为空，尝试直接设置 FileName 属性
                if (_tickCount == 20) // 10s = 20 * 500ms
                {
                    Trace("轮询: 10s 未加载，尝试 set_FileName fallback");
                    try
                    {
                        _control.FileName = _inputPath!;
                        Trace("轮询: set_FileName 已调用");
                    }
                    catch (Exception ex)
                    {
                        Trace($"轮询: set_FileName 异常: {ex.Message}");
                    }
                }
            }
        }
        catch (Exception ex)
        {
            Trace($"轮询异常: {ex}");
            _errorMessage = $"轮询异常: {ex.Message}";
            _exitCode = 4;
            _state = State.Failed;
            CloseForm();
        }
    }

    /// <summary>调用 Save 导出 PNG（防止重复调用）。</summary>
    private static void DoSave()
    {
        if (_saveCalled)
        {
            return;
        }
        _saveCalled = true;
        _state = State.Saving;
        _tickCount = 0;

        try
        {
            Trace($"调用 Save: {_outputPath}");
            // Save 方法：文件扩展名决定输出格式（.png → PNG）
            // 参考 xPort 官方实现：m_Ctrl.Save(outputFilePath, false, "")
            _control!.Save(_outputPath!, false, "");
            Trace("Save 已返回");
        }
        catch (Exception ex)
        {
            Trace($"Save 异常: {ex.Message}");
            _errorMessage = $"Save 异常: {ex.Message}";
            _exitCode = 4;
            _state = State.Failed;
            CloseForm();
        }
    }

    // ── COM 事件回调（官方互操作程序集应正确触发） ──

    private static void OnDocLoadedEvent(string fileName)
    {
        Trace($"事件 OnFinishedLoadingDocument: {fileName}");
        if (_state == State.Loading)
        {
            DoSave();
        }
    }

    private static void OnDocLoadFailedEvent(string fileName, int errorCode, string errorString)
    {
        Trace($"事件 OnFailedLoadingDocument: {errorString} [code={errorCode}]");
        _errorMessage = $"文档加载失败: {errorString} [code={errorCode}]";
        _exitCode = 3;
        _state = State.Failed;
        CloseForm();
    }

    private static void OnDocSavedEvent()
    {
        Trace("事件 OnFinishedSavingDocument");
        if (File.Exists(_outputPath) && new FileInfo(_outputPath).Length > 0)
        {
            _state = State.Done;
            _exitCode = 0;
            Console.Out.Flush();
            Console.Error.Flush();
            Environment.Exit(0);
        }
        else
        {
            _state = State.Saving;
            _tickCount = 0;
        }
    }

    private static void OnSaveFailedEvent(string fileName, int errorCode, string errorString)
    {
        Trace($"事件 OnFailedSavingDocument: {errorString} [code={errorCode}]");
        _errorMessage = $"导出失败: {errorString} [code={errorCode}]";
        _exitCode = 4;
        _state = State.Failed;
        CloseForm();
    }

    private static void CloseForm()
    {
        Trace("CloseForm");
        _pollTimer?.Stop();
        _mainForm?.Close();
    }
}

/// <summary>
/// AxHost 容器，承载 EModelViewControl ActiveX 控件。
/// CLSID {22945A69-1191-4DCF-9E6F-409BDE94D101} = EModelNonVersionSpecificViewControl
/// （版本无关，eDrawings 安装时注册）。
/// </summary>
internal sealed class EDrawingsHost : AxHost
{
    private const string EMODEL_VIEW_CLSID = "22945A69-1191-4DCF-9E6F-409BDE94D101";
    private bool _isLoaded;

    public event Action<EModelViewControl>? ControlLoaded;

    public EDrawingsHost() : base(EMODEL_VIEW_CLSID) { }

    protected override void OnCreateControl()
    {
        base.OnCreateControl();
        if (_isLoaded)
        {
            return;
        }
        _isLoaded = true;

        Console.Error.WriteLine("[trace] OnCreateControl: 获取 OCX 实例");
        Console.Error.Flush();

        var ctrl = GetOcx() as EModelViewControl;
        if (ctrl == null)
        {
            Console.Error.WriteLine("[trace] GetOcx() as EModelViewControl 返回 null");
            Console.Error.Flush();
            Environment.Exit(2);
        }

        Console.Error.WriteLine($"[trace] OCX 类型: {ctrl!.GetType().Name}");
        Console.Error.Flush();

        ControlLoaded?.Invoke(ctrl);
    }
}

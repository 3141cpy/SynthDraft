using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows.Forms;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swpublished;

namespace SynthDraftAddIn
{
    /// <summary>
    /// SynthDraft SolidWorks Add-in.
    ///
    /// Provides three command-bar buttons:
    /// 1. Upload current document to the SynthDraft review service.
    /// 2. View review results and highlight defect positions.
    /// 3. One-click optimize from review defects.
    ///
    /// Implements ISwAddin (verified signature from SolidWorks.Interop.swpublished):
    ///   bool ConnectToSW(object ThisSW, int Cookie)
    ///   bool DisconnectFromSW()
    ///
    /// API references (verified via reflection on SolidWorks 2025 interop):
    /// - ISldWorks.SetAddinCallbackInfo(int ModuleHandle, object AddinCallbacks, int Cookie)
    /// - ISldWorks.GetCommandManager(int Cookie) → CommandManager
    /// - ICommandManager.CreateCommandGroup2(int, string, string, string, int, bool, ref int) → CommandGroup
    /// - ICommandGroup.AddCommandItem2(string, int, string, string, int, string, string, int, int)
    /// - IModelDoc2.SaveAs(string) / GetTitle() / GetPathName() / GetType()
    /// </summary>
    [ComVisible(true)]
    [Guid("B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D")]
    [ProgId("SynthDraft.AddIn")]
    [ClassInterface(ClassInterfaceType.AutoDispatch)]
    public class SynthDraftAddIn : ISwAddin
    {
        // ===== SolidWorks objects =====
        private ISldWorks swApp;
        private ICommandManager cmdMgr;
        private int addInCookie;

        // ===== Backend client (HTTP) =====
        private BackendClient backend;

        // ===== Last task IDs (for chaining review → optimize) =====
        private string lastReviewTaskId;

        // ===== Command group / item IDs =====
        // Unique IDs for the command group (must not collide with other add-ins).
        private const int CmdGroupId = 9910;
        // swCommandItemType_e: swMenuItem=1, swToolbarItem=2, swMenuAndToolbar=3
        private const int SwMenuAndToolbar = 3;
        // swDocumentTypes_e for ShowInDocumentType bitmask
        private const int SwDocAll = 7; // swDocPART(1) | swDocASSEMBLY(2) | swDocDRAWING(4)

        // swDocumentTypes_e
        private const int SwDocPart = 1;
        private const int SwDocAssembly = 2;
        private const int SwDocDrawing = 3;

        /// <summary>
        /// Called by SolidWorks when the add-in is loaded.
        /// Registers the callback object, creates the command group and buttons.
        /// </summary>
        public bool ConnectToSW(object ThisSW, int Cookie)
        {
            try
            {
                swApp = (ISldWorks)ThisSW;
                addInCookie = Cookie;

                // Register this object as the callback handler for command buttons.
                // ModuleHandle=0 (not used for managed add-ins), AddinCallbacks=this, Cookie=addInCookie.
                swApp.SetAddinCallbackInfo(0, this, Cookie);

                // Initialize backend client.
                backend = new BackendClient();

                // Create command group and buttons.
                cmdMgr = (ICommandManager)swApp.GetCommandManager(Cookie);
                if (cmdMgr == null)
                {
                    LogError("GetCommandManager returned null");
                    return false;
                }

                bool ok = CreateCommandGroup();
                if (!ok)
                {
                    LogError("CreateCommandGroup failed");
                    return false;
                }

                LogInfo("SynthDraft Add-in connected successfully.");
                return true;
            }
            catch (Exception ex)
            {
                LogError("ConnectToSW failed: " + ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Called by SolidWorks when the add-in is unloaded.
        /// Removes the command group and releases references.
        /// </summary>
        public bool DisconnectFromSW()
        {
            try
            {
                if (cmdMgr != null)
                {
                    cmdMgr.RemoveCommandGroup(CmdGroupId);
                    cmdMgr = null;
                }

                if (backend != null)
                {
                    backend.Dispose();
                    backend = null;
                }

                swApp = null;
                return true;
            }
            catch (Exception ex)
            {
                LogError("DisconnectFromSW failed: " + ex.Message);
                return false;
            }
        }

        // ===== Command group creation (SubTask 8.2) =====

        private bool CreateCommandGroup()
        {
            int errors = 0;
            // CreateCommandGroup2 signature (verified):
            // (int UserID, string Title, string ToolTip, string Hint, int Position,
            //  bool IgnorePreviousVersion, ref int Errors)
            CommandGroup cmdGroup = cmdMgr.CreateCommandGroup2(
                CmdGroupId,
                "SynthDraft 审图",
                "SynthDraft 审图",
                "SynthDraft 审图插件",
                -1,                  // Position: -1 = append at end
                true,                // IgnorePreviousVersion
                ref errors);

            if (cmdGroup == null)
            {
                LogError("CreateCommandGroup2 returned null, errors=" + errors);
                return false;
            }

            // Show in all document types (parts, assemblies, drawings).
            cmdGroup.ShowInDocumentType = SwDocAll;

            // AddCommandItem2 signature (verified):
            // (string Name, int Position, string HintString, string ToolTip,
            //  int ImageListIndex, string CallbackFunction, string EnableMethod,
            //  int UserID, int MenuTBOption)
            // ImageListIndex = -1 means use default icon.
            // CallbackFunction and EnableMethod are method names on this object
            // (resolved via IDispatch::GetIDsOfNames).

            // Button 1: 上传审图
            cmdGroup.AddCommandItem2(
                "上传审图", -1,
                "将当前文档上传到 SynthDraft 审图服务",
                "上传审图", -1,
                "UploadReview", "EnableIfDocOpen",
                0, SwMenuAndToolbar);

            // Button 2: 查看审查结果
            cmdGroup.AddCommandItem2(
                "查看审查结果", -1,
                "查看审图结果并高亮缺陷位置",
                "查看审查结果", -1,
                "ViewReviewResults", "EnableIfDocOpen",
                1, SwMenuAndToolbar);

            // Button 3: 一键优化
            cmdGroup.AddCommandItem2(
                "一键优化", -1,
                "基于审图缺陷自动优化图纸",
                "一键优化", -1,
                "OptimizeFromReview", "EnableIfDocOpen",
                2, SwMenuAndToolbar);

            cmdGroup.HasToolbar = true;
            cmdGroup.HasMenu = true;

            bool activated = cmdGroup.Activate();
            return activated;
        }

        // ===== Callback: Upload current document for review (SubTask 8.2 button 1) =====

        /// <summary>
        /// Saves the active document to a temp file, uploads it to the backend,
        /// and submits a review task.
        /// </summary>
        public void UploadReview()
        {
            try
            {
                IModelDoc2 doc = GetActiveDoc();
                if (doc == null)
                {
                    ShowMessage("没有打开的文档。");
                    return;
                }

                // Determine document type and file extension.
                int docType = doc.GetType();
                string fileExt;
                string fileType;
                switch (docType)
                {
                    case SwDocPart:
                        fileExt = ".SLDPRT";
                        fileType = "sldprt";
                        break;
                    case SwDocAssembly:
                        fileExt = ".SLDASM";
                        fileType = "sldasm";
                        break;
                    case SwDocDrawing:
                        // Drawings are exported as DXF for the backend.
                        fileExt = ".DXF";
                        fileType = "dxf";
                        break;
                    default:
                        ShowMessage("不支持的文档类型: " + docType);
                        return;
                }

                // Save a copy to temp.
                string tempFile = Path.Combine(Path.GetTempPath(),
                    "synthdraft_" + Guid.NewGuid().ToString("N") + fileExt);
                bool saved = doc.SaveAs(tempFile);
                if (!saved || !File.Exists(tempFile))
                {
                    // Fall back to the original file path if save failed.
                    string origPath = doc.GetPathName();
                    if (!string.IsNullOrEmpty(origPath) && File.Exists(origPath))
                    {
                        tempFile = origPath;
                        // Infer fileType from original extension for drawings saved as SLDDRW.
                        if (docType == SwDocDrawing && origPath.EndsWith(".SLDDRW",
                            StringComparison.OrdinalIgnoreCase))
                        {
                            ShowMessage("工程图导出 DXF 失败，请先保存工程图后重试。");
                            return;
                        }
                    }
                    else
                    {
                        ShowMessage("保存临时文件失败，请确保文档已保存。");
                        return;
                    }
                }

                ShowMessage("正在上传文档到审图服务...");

                // Upload file and submit review asynchronously.
                Task.Run(async () =>
                {
                    try
                    {
                        // Step 1: Upload the file.
                        var uploadResult = await backend.UploadFileAsync(tempFile);
                        string fileKey = uploadResult["file_key"] as string;
                        if (string.IsNullOrEmpty(fileKey))
                        {
                            ShowMessageAsync("上传失败：未获取到 file_key。");
                            return;
                        }

                        // Step 2: Submit review.
                        var reviewResult = await backend.SubmitReviewAsync(
                            fileKey, fileType,
                            new List<string> { "GB/T 1182", "GB/T 4457.4" });

                        lastReviewTaskId = reviewResult["task_id"] as string;
                        ShowMessageAsync(string.Format(
                            "审图任务已提交！\n任务 ID: {0}\n\n可在「查看审查结果」中查询进度。",
                            lastReviewTaskId));
                    }
                    catch (Exception ex)
                    {
                        ShowMessageAsync("上传/提交审图失败: " + ex.Message);
                    }
                });
            }
            catch (Exception ex)
            {
                ShowMessage("UploadReview 异常: " + ex.Message);
            }
        }

        // ===== Callback: View review results and highlight defects (SubTask 8.2 button 2) =====

        /// <summary>
        /// Prompts for a task ID (defaults to the last submitted), queries the
        /// review result, and highlights defect coordinates in the active document.
        /// </summary>
        public void ViewReviewResults()
        {
            try
            {
                string taskId = lastReviewTaskId;
                if (string.IsNullOrEmpty(taskId))
                {
                    taskId = PromptInput("请输入审图任务 ID:");
                    if (string.IsNullOrEmpty(taskId))
                        return;
                }
                else
                {
                    string input = PromptInput("请输入审图任务 ID (留空使用上次任务 " + taskId + "):");
                    if (!string.IsNullOrEmpty(input))
                        taskId = input;
                }

                Task.Run(async () =>
                {
                    try
                    {
                        var result = await backend.GetReviewResultAsync(taskId);
                        string status = result.ContainsKey("status")
                            ? (result["status"] as string ?? "unknown") : "unknown";

                        if (status == "pending" || status == "running")
                        {
                            ShowMessageAsync(string.Format(
                                "任务 {0} 状态: {1}\n请稍后重试。",
                                taskId, status));
                            return;
                        }

                        if (status == "failed")
                        {
                            string err = result.ContainsKey("error")
                                ? (result["error"] as string ?? "") : "";
                            ShowMessageAsync(string.Format(
                                "任务 {0} 失败: {1}", taskId, err));
                            return;
                        }

                        // status == "completed"
                        double score = 0;
                        if (result.ContainsKey("compliance_score"))
                        {
                            object sc = result["compliance_score"];
                            if (sc != null)
                                double.TryParse(sc.ToString(), out score);
                        }

                        var defects = result.ContainsKey("defects")
                            ? (result["defects"] as List<object>) : null;

                        int defectCount = defects != null ? defects.Count : 0;

                        // Build summary message.
                        string summary = string.Format(
                            "审图结果（任务 {0}）\n合规性评分: {1:F1}\n缺陷数量: {2}\n\n",
                            taskId, score, defectCount);

                        // Highlight defects with coordinates in the active document.
                        int highlighted = 0;
                        if (defects != null && defects.Count > 0)
                        {
                            for (int i = 0; i < defects.Count; i++)
                            {
                                var defect = defects[i] as Dictionary<string, object>;
                                if (defect == null) continue;

                                summary += string.Format(
                                    "[{0}] {1} / {2}\n  条文: {3}\n  建议: {4}\n",
                                    i + 1,
                                    defect.ContainsKey("category") ? defect["category"] : "?",
                                    defect.ContainsKey("severity") ? defect["severity"] : "?",
                                    defect.ContainsKey("standard_ref") ? defect["standard_ref"] : "?",
                                    defect.ContainsKey("suggestion") ? defect["suggestion"] : "?");

                                // Attempt to highlight by coordinate.
                                if (defect.ContainsKey("coordinate") &&
                                    defect["coordinate"] is Dictionary<string, object> coord)
                                {
                                    bool highlightedThis = HighlightCoordinate(coord, i);
                                    if (highlightedThis) highlighted++;
                                }
                            }
                        }

                        if (defectCount > 0)
                        {
                            summary += string.Format(
                                "\n已在图纸中高亮 {0}/{1} 个缺陷位置。", highlighted, defectCount);
                        }

                        ShowMessageAsync(summary);
                    }
                    catch (Exception ex)
                    {
                        ShowMessageAsync("查询审图结果失败: " + ex.Message);
                    }
                });
            }
            catch (Exception ex)
            {
                ShowMessage("ViewReviewResults 异常: " + ex.Message);
            }
        }

        /// <summary>
        /// Attempts to highlight a defect coordinate in the active document
        /// using ModelDocExtension.SelectByID2 with empty entity name (selects
        /// geometry at the given coordinates).
        /// </summary>
        private bool HighlightCoordinate(Dictionary<string, object> coord, int defectIndex)
        {
            try
            {
                double x = 0, y = 0, z = 0;
                if (coord.ContainsKey("x"))
                    double.TryParse(coord["x"]?.ToString() ?? "0", out x);
                if (coord.ContainsKey("y"))
                    double.TryParse(coord["y"]?.ToString() ?? "0", out y);
                if (coord.ContainsKey("z"))
                    double.TryParse(coord["z"]?.ToString() ?? "0", out z);

                // SolidWorks uses meters internally; coordinates from review
                // are in mm (model space). Convert mm → m.
                x /= 1000.0;
                y /= 1000.0;
                z /= 1000.0;

                IModelDoc2 doc = GetActiveDoc();
                if (doc == null) return false;

                // Access Extension via dynamic (avoids embedded interop type issues).
                dynamic dynDoc = doc;
                dynamic ext = dynDoc.Extension;
                if (ext == null) return false;

                // SelectByID2 signature (verified on IModelDocExtension):
                // (string Name, string Type, double X, double Y, double Z,
                //  bool Append, int Mark, Callout Callout, int SelectOption)
                // Name="" and Type="" selects geometry at the coordinate.
                // Append=true so multiple defects can be highlighted.
                bool ok = ext.SelectByID2(
                    "", "",       // name, type
                    x, y, z,      // coordinates (meters)
                    true,         // append to current selection
                    defectIndex + 1, // mark with defect index
                    null,         // callout
                    0);           // select option
                return ok;
            }
            catch
            {
                return false;
            }
        }

        // ===== Callback: One-click optimize from review (SubTask 8.2 button 3) =====

        /// <summary>
        /// Submits an optimize-from-review request for the last review task.
        /// </summary>
        public void OptimizeFromReview()
        {
            try
            {
                string taskId = lastReviewTaskId;
                if (string.IsNullOrEmpty(taskId))
                {
                    taskId = PromptInput("请输入需要优化的审图任务 ID:");
                    if (string.IsNullOrEmpty(taskId))
                        return;
                }
                else
                {
                    string input = PromptInput(
                        "请输入审图任务 ID (留空使用上次任务 " + taskId + "):");
                    if (!string.IsNullOrEmpty(input))
                        taskId = input;
                }

                Task.Run(async () =>
                {
                    try
                    {
                        var result = await backend.OptimizeFromReviewAsync(taskId);
                        string genTaskId = result.ContainsKey("generation_task_id")
                            ? (result["generation_task_id"] as string ?? "") : "";

                        ShowMessageAsync(string.Format(
                            "优化任务已派发！\n原审图任务: {0}\n生成任务: {1}\n\n" +
                            "生成完成后将自动触发复审。",
                            taskId, genTaskId));
                    }
                    catch (Exception ex)
                    {
                        ShowMessageAsync("优化请求失败: " + ex.Message);
                    }
                });
            }
            catch (Exception ex)
            {
                ShowMessage("OptimizeFromReview 异常: " + ex.Message);
            }
        }

        // ===== Enable callback: enables buttons only when a document is open =====

        /// <summary>
        /// Enable method for all command buttons.
        /// Returns 1 (enabled) if a document is open, 0 (disabled) otherwise.
        /// </summary>
        public int EnableIfDocOpen()
        {
            try
            {
                return GetActiveDoc() != null ? 1 : 0;
            }
            catch
            {
                return 0;
            }
        }

        // ===== Helpers =====

        private IModelDoc2 GetActiveDoc()
        {
            if (swApp == null) return null;
            object obj = swApp.ActiveDoc;
            return obj as IModelDoc2;
        }

        private void ShowMessage(string msg)
        {
            try
            {
                if (swApp != null)
                    swApp.SendMsgToUser(msg);
                else
                    MessageBox.Show(msg, "SynthDraft");
            }
            catch
            {
                try { MessageBox.Show(msg, "SynthDraft"); } catch { }
            }
        }

        /// <summary>
        /// Shows a message box on the UI thread (for async callbacks).
        /// SolidWorks SendMsgToUser must be called from the main thread.
        /// </summary>
        private void ShowMessageAsync(string msg)
        {
            try
            {
                if (swApp != null)
                {
                    // Marshal to the SolidWorks main thread via SendMsgToUser.
                    // This is thread-safe because it posts to the SW message loop.
                    swApp.SendMsgToUser(msg);
                }
                else
                {
                    MessageBox.Show(msg, "SynthDraft");
                }
            }
            catch
            {
                try { MessageBox.Show(msg, "SynthDraft"); } catch { }
            }
        }

        private string PromptInput(string prompt)
        {
            // Simple input dialog using WinForms.
            // SolidWorks doesn't have a built-in input box, so we use a Form.
            using (var form = new Form())
            {
                form.Text = "SynthDraft";
                form.Width = 450;
                form.Height = 150;
                form.StartPosition = FormStartPosition.CenterScreen;

                var label = new Label();
                label.Text = prompt;
                label.Left = 10;
                label.Top = 10;
                label.Width = 420;
                label.Height = 30;

                var textBox = new TextBox();
                textBox.Left = 10;
                textBox.Top = 40;
                textBox.Width = 420;

                var okButton = new Button();
                okButton.Text = "确定";
                okButton.Left = 250;
                okButton.Top = 70;
                okButton.Width = 80;
                okButton.DialogResult = DialogResult.OK;

                var cancelButton = new Button();
                cancelButton.Text = "取消";
                cancelButton.Left = 340;
                cancelButton.Top = 70;
                cancelButton.Width = 80;
                cancelButton.DialogResult = DialogResult.Cancel;

                form.Controls.Add(label);
                form.Controls.Add(textBox);
                form.Controls.Add(okButton);
                form.Controls.Add(cancelButton);
                form.AcceptButton = okButton;
                form.CancelButton = cancelButton;

                if (form.ShowDialog() == DialogResult.OK)
                    return textBox.Text;
                return null;
            }
        }

        private void LogInfo(string msg)
        {
            try
            {
                string logDir = Path.Combine(
                    System.Environment.GetFolderPath(System.Environment.SpecialFolder.LocalApplicationData),
                    "SynthDraft", "logs");
                Directory.CreateDirectory(logDir);
                string logFile = Path.Combine(logDir, "addin.log");
                File.AppendAllText(logFile,
                    string.Format("[{0}] INFO: {1}\r\n",
                    DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"), msg));
            }
            catch { }
        }

        private void LogError(string msg)
        {
            try
            {
                string logDir = Path.Combine(
                    System.Environment.GetFolderPath(System.Environment.SpecialFolder.LocalApplicationData),
                    "SynthDraft", "logs");
                Directory.CreateDirectory(logDir);
                string logFile = Path.Combine(logDir, "addin.log");
                File.AppendAllText(logFile,
                    string.Format("[{0}] ERROR: {1}\r\n",
                    DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"), msg));
            }
            catch { }
        }
    }
}

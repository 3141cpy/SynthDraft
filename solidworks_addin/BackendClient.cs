using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using Microsoft.Win32;

namespace SynthDraftAddIn
{
    /// <summary>
    /// HTTP/WebSocket client for communicating with the SynthDraft backend.
    ///
    /// Backend API (verified from backend/app/api/v1/):
    /// - POST   /api/v1/uploads                              (multipart/form-data) → file_key
    /// - POST   /api/v1/reviews                               (JSON body) → task_id
    /// - GET    /api/v1/reviews/{task_id}/result              → status, defects, compliance_score
    /// - GET    /api/v1/reviews/{task_id}/report?format=html  → HTML report
    /// - POST   /api/v1/collaboration/optimize-from-review    (JSON body) → generation_task_id
    /// - WS     /api/v1/ws/tasks/{task_id}                     → progress updates
    ///
    /// Backend URL is read from registry (HKCU\Software\SynthDraft\backend_url),
    /// defaulting to http://localhost:8000.
    ///
    /// JSON serialization uses System.Web.Script.Serialization.JavaScriptSerializer
    /// (built into .NET Framework 4.8 via System.Web.Extensions, no external deps).
    /// </summary>
    public class BackendClient : IDisposable
    {
        private static readonly HttpClient httpClient;
        private static readonly JavaScriptSerializer jsonSerializer;

        // Registry key for configuration.
        private const string RegKeyPath = @"Software\SynthDraft";
        private const string RegValueBackendUrl = "backend_url";

        private readonly string baseUrl;
        private bool disposed;

        static BackendClient()
        {
            httpClient = new HttpClient();
            httpClient.Timeout = TimeSpan.FromMinutes(5); // uploads can be large
            jsonSerializer = new JavaScriptSerializer();
            jsonSerializer.MaxJsonLength = int.MaxValue;
        }

        public BackendClient()
        {
            baseUrl = GetBackendUrl().TrimEnd('/');
        }

        /// <summary>
        /// Reads the backend URL from the registry, defaulting to
        /// http://localhost:8000. Validates the value as an absolute
        /// http/https URI; falls back to the default when malformed.
        /// </summary>
        public static string GetBackendUrl()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RegKeyPath))
                {
                    if (key != null)
                    {
                        object val = key.GetValue(RegValueBackendUrl);
                        if (val is string s && !string.IsNullOrEmpty(s))
                        {
                            // Validate as an absolute http/https URI before
                            // returning; fall back to the default if the
                            // registry value is malformed or uses a non-http scheme.
                            if (Uri.TryCreate(s, UriKind.Absolute, out Uri uri) &&
                                (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps))
                            {
                                return s;
                            }
                        }
                    }
                }
            }
            catch { }
            return "http://localhost:8000";
        }

        /// <summary>
        /// Uploads a file to the backend via multipart/form-data.
        /// POST /api/v1/uploads
        /// </summary>
        /// <returns>Dictionary with file_key, file_name, file_type, size, content_type.</returns>
        public async Task<Dictionary<string, object>> UploadFileAsync(string filePath)
        {
            if (!File.Exists(filePath))
                throw new FileNotFoundException("文件不存在: " + filePath);

            using (var form = new MultipartFormDataContent())
            using (var fileContent = new StreamContent(File.OpenRead(filePath)))
            {
                fileContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(
                    "application/octet-stream");
                string fileName = Path.GetFileName(filePath);
                form.Add(fileContent, "file", fileName);

                string url = baseUrl + "/api/v1/uploads";
                HttpResponseMessage response = await httpClient.PostAsync(url, form);
                string responseBody = await response.Content.ReadAsStringAsync();

                if (!response.IsSuccessStatusCode)
                {
                    throw new Exception(string.Format(
                        "上传失败: HTTP {0} - {1}", (int)response.StatusCode, responseBody));
                }

                return ParseJson(responseBody);
            }
        }

        /// <summary>
        /// Submits a review task.
        /// POST /api/v1/reviews
        /// </summary>
        /// <returns>Dictionary with task_id, status, websocket_url.</returns>
        public async Task<Dictionary<string, object>> SubmitReviewAsync(
            string fileKey, string fileType, List<string> standardSet)
        {
            var payload = new Dictionary<string, object>
            {
                { "file_key", fileKey },
                { "file_type", fileType },
                { "standard_set", standardSet ?? new List<string>() }
            };

            string json = jsonSerializer.Serialize(payload);
            string url = baseUrl + "/api/v1/reviews";

            using (var content = new StringContent(json, Encoding.UTF8, "application/json"))
            {
                HttpResponseMessage response = await httpClient.PostAsync(url, content);
                string responseBody = await response.Content.ReadAsStringAsync();

                if (!response.IsSuccessStatusCode)
                {
                    throw new Exception(string.Format(
                        "提交审图失败: HTTP {0} - {1}", (int)response.StatusCode, responseBody));
                }

                return ParseJson(responseBody);
            }
        }

        /// <summary>
        /// Queries the review task result.
        /// GET /api/v1/reviews/{task_id}/result
        /// </summary>
        /// <returns>Dictionary with task_id, status, defects, compliance_score, etc.</returns>
        public async Task<Dictionary<string, object>> GetReviewResultAsync(
            string taskId, CancellationToken cancellationToken = default(CancellationToken))
        {
            string url = baseUrl + "/api/v1/reviews/" + Uri.EscapeDataString(taskId) + "/result";
            HttpResponseMessage response = await httpClient.GetAsync(url, cancellationToken);
            string responseBody = await response.Content.ReadAsStringAsync();

            if (!response.IsSuccessStatusCode)
            {
                throw new Exception(string.Format(
                    "查询审图结果失败: HTTP {0} - {1}", (int)response.StatusCode, responseBody));
            }

            return ParseJson(responseBody);
        }

        /// <summary>
        /// Downloads the HTML review report.
        /// GET /api/v1/reviews/{task_id}/report?format=html
        /// </summary>
        /// <returns>HTML report content as string.</returns>
        public async Task<string> DownloadReviewReportAsync(string taskId)
        {
            string url = baseUrl + "/api/v1/reviews/" + Uri.EscapeDataString(taskId)
                         + "/report?format=html";
            HttpResponseMessage response = await httpClient.GetAsync(url);
            string responseBody = await response.Content.ReadAsStringAsync();

            if (!response.IsSuccessStatusCode)
            {
                throw new Exception(string.Format(
                    "下载报告失败: HTTP {0} - {1}", (int)response.StatusCode, responseBody));
            }

            return responseBody;
        }

        /// <summary>
        /// Submits an optimize-from-review request.
        /// POST /api/v1/collaboration/optimize-from-review
        /// </summary>
        /// <returns>Dictionary with generation_task_id, original_review_task_id, etc.</returns>
        public async Task<Dictionary<string, object>> OptimizeFromReviewAsync(
            string reviewTaskId, string outputFormat = "dxf", bool autoReReview = true)
        {
            var payload = new Dictionary<string, object>
            {
                { "review_task_id", reviewTaskId },
                { "output_format", outputFormat },
                { "auto_re_review", autoReReview }
            };

            string json = jsonSerializer.Serialize(payload);
            string url = baseUrl + "/api/v1/collaboration/optimize-from-review";

            using (var content = new StringContent(json, Encoding.UTF8, "application/json"))
            {
                HttpResponseMessage response = await httpClient.PostAsync(url, content);
                string responseBody = await response.Content.ReadAsStringAsync();

                if (!response.IsSuccessStatusCode)
                {
                    throw new Exception(string.Format(
                        "优化请求失败: HTTP {0} - {1}", (int)response.StatusCode, responseBody));
                }

                return ParseJson(responseBody);
            }
        }

        /// <summary>
        /// Submits user feedback for a specific defect.
        /// POST /api/v1/collaboration/feedback
        /// </summary>
        public async Task<Dictionary<string, object>> SubmitFeedbackAsync(
            string reviewTaskId, int defectIndex, string action, string comment = "")
        {
            var payload = new Dictionary<string, object>
            {
                { "review_task_id", reviewTaskId },
                { "defect_index", defectIndex },
                { "action", action },
                { "comment", comment }
            };

            string json = jsonSerializer.Serialize(payload);
            string url = baseUrl + "/api/v1/collaboration/feedback";

            using (var content = new StringContent(json, Encoding.UTF8, "application/json"))
            {
                HttpResponseMessage response = await httpClient.PostAsync(url, content);
                string responseBody = await response.Content.ReadAsStringAsync();

                if (!response.IsSuccessStatusCode)
                {
                    throw new Exception(string.Format(
                        "反馈提交失败: HTTP {0} - {1}", (int)response.StatusCode, responseBody));
                }

                return ParseJson(responseBody);
            }
        }

        /// <summary>
        /// Connects to the WebSocket endpoint to receive task progress updates.
        /// Falls back gracefully if the backend is unreachable.
        /// WS /api/v1/ws/tasks/{task_id}
        ///
        /// This is optional; the add-in primarily uses HTTP polling.
        /// </summary>
        /// <param name="taskId">The task ID to monitor.</param>
        /// <param name="onProgress">Callback invoked with each progress message.</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        public async Task SubscribeToTaskProgressAsync(
            string taskId,
            Action<string> onProgress,
            CancellationToken cancellationToken = default(CancellationToken))
        {
            string wsUrl = baseUrl.Replace("http://", "ws://").Replace("https://", "wss://")
                          + "/api/v1/ws/tasks/" + Uri.EscapeDataString(taskId);

            try
            {
                using (var ws = new ClientWebSocket())
                {
                    await ws.ConnectAsync(new Uri(wsUrl), cancellationToken);

                    var buffer = new byte[8192];
                    while (ws.State == WebSocketState.Open && !cancellationToken.IsCancellationRequested)
                    {
                        WebSocketReceiveResult result = await ws.ReceiveAsync(
                            new ArraySegment<byte>(buffer), cancellationToken);

                        if (result.MessageType == WebSocketMessageType.Text)
                        {
                            string message = Encoding.UTF8.GetString(buffer, 0, result.Count);
                            onProgress?.Invoke(message);
                        }
                        else if (result.MessageType == WebSocketMessageType.Close)
                        {
                            break;
                        }
                    }
                }
            }
            catch (OperationCanceledException)
            {
                // Expected when cancelled.
            }
            catch (Exception ex)
            {
                onProgress?.Invoke("WebSocket 连接失败（降级为 HTTP 轮询）: " + ex.Message);
            }
        }

        /// <summary>
        /// Polls the review result until the task completes or times out.
        /// Used as a fallback when WebSocket is unavailable.
        /// The deadline bounds both individual HTTP requests (via a
        /// CancellationToken) and the polling delay so the method exits
        /// close to timeoutSeconds.
        /// </summary>
        public async Task<Dictionary<string, object>> PollReviewResultAsync(
            string taskId, int timeoutSeconds = 300, int pollIntervalMs = 2000)
        {
            using (var cts = new CancellationTokenSource(TimeSpan.FromSeconds(timeoutSeconds)))
            {
                CancellationToken token = cts.Token;
                try
                {
                    while (!token.IsCancellationRequested)
                    {
                        var result = await GetReviewResultAsync(taskId, token);
                        string status = result.ContainsKey("status")
                            ? (result["status"] as string ?? "") : "";

                        if (status == "completed" || status == "failed")
                            return result;

                        // Task.Delay honors the token, capping the wait to the
                        // remaining deadline so the loop exits on schedule.
                        await Task.Delay(pollIntervalMs, token);
                    }
                }
                catch (OperationCanceledException)
                {
                    // Deadline reached; fall through to TimeoutException.
                }
            }
            throw new TimeoutException("审图任务超时: " + taskId);
        }

        // ===== JSON helpers =====

        /// <summary>
        /// Parses a JSON string into a Dictionary.
        /// JavaScriptSerializer deserializes nested arrays as List&lt;object&gt;
        /// and nested objects as Dictionary&lt;string, object&gt;.
        /// </summary>
        private static Dictionary<string, object> ParseJson(string json)
        {
            object result = jsonSerializer.DeserializeObject(json);
            if (result is Dictionary<string, object> dict)
                return dict;
            // Wrap non-object results.
            return new Dictionary<string, object> { { "result", result } };
        }

        public void Dispose()
        {
            if (!disposed)
            {
                disposed = true;
            }
        }
    }
}

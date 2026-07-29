# SynthDraft 离线安装包

适用于无外网访问的私有化部署环境。

## 一、构建离线包（在有网络的构建机执行）

```bash
# 进入项目根目录
cd /path/to/SynthDraft

# Dry-run 预览（不下载）
python infra/offline_install/build_offline_package.py --dry-run

# 实际打包（不含 Docker 镜像，约 12-15 GB）
python infra/offline_install/build_offline_package.py \
  --output /tmp/synthdraft_offline

# 含 Docker 镜像 tar（需本机 docker，约 +3 GB）
python infra/offline_install/build_offline_package.py \
  --output /tmp/synthdraft_offline \
  --include-images
```

构建产物目录结构：

```
synthdraft_offline/
├── manifest.json              # 清单（含所有文件列表与预期大小）
├── wheels/                    # Python 依赖 wheel
├── models/
│   ├── huggingface/           # HF 模型权重（bge-m3 等）
│   └── ollama/                # Ollama 模型清单（部署时 ollama pull）
├── spec_library/              # 规范库 PDF/DOCX
├── docker_images/             # Docker 镜像 tar（可选）
└── backend_code.tar           # 后端代码归档
```

## 二、目标机器离线安装步骤

### 2.1 准备基础环境

```bash
# 1. 安装 Docker 与 Docker Compose（如已安装可跳过）
#    CentOS/RHEL: 参考 https://docs.docker.com/engine/install/centos/
#    Ubuntu:      参考 https://docs.docker.com/engine/install/ubuntu/

# 2. 解压离线包到目标目录
mkdir -p /opt/synthdraft
cp synthdraft_offline.tar.gz /opt/synthdraft/
cd /opt/synthdraft
tar xzf synthdraft_offline.tar.gz
```

### 2.2 导入 Docker 镜像（如离线包含 images）

```bash
cd /opt/synthdraft/synthdraft_offline
for img_tar in docker_images/*.tar; do
  echo "Loading $img_tar..."
  docker load -i "$img_tar"
done
```

### 2.3 安装 Python 依赖

```bash
# 推荐创建独立 venv
python3.13 -m venv /opt/synthdraft/backend/.venv
source /opt/synthdraft/backend/.venv/bin/activate

# 离线安装 wheels
pip install --no-index --find-links=/opt/synthdraft/synthdraft_offline/wheels \
  -r /opt/synthdraft/backend/requirements.txt
```

### 2.4 预下载模型权重

#### Ollama 模型（通过离线包中的 ollama_data 卷）

如果离线包中包含 `models/ollama/*.blob` 文件（构建机已 ollama pull 后导出）：

```bash
# 复制到 ollama 数据卷
mkdir -p /var/lib/ollama
cp -r models/ollama/* /var/lib/ollama/
```

否则，需在目标机器联网一次拉取模型（首次部署）：

```bash
# 临时联网拉取（仅需一次）
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5-vl:7b
# 拉取后断网即可，模型缓存在 /root/.ollama 或 /var/lib/ollama
```

#### HuggingFace 模型（bge-m3 嵌入模型）

```bash
# 离线模式：直接使用离线包中的 HF 模型快照
export HF_HOME=/opt/synthdraft/synthdraft_offline/models/huggingface
export TRANSFORMERS_OFFLINE=1
export HF_HUB_OFFLINE=1
```

或修改 `infra/.env`：

```env
HF_ENDPOINT=https://hf-mirror.com  # 镜像加速（仍需联网）
# 或离线模式
TRANSFORMERS_OFFLINE=1
HF_HUB_OFFLINE=1
```

### 2.5 配置 .env 启用离线模式

编辑 `infra/.env`：

```env
# 启用离线模式（禁用所有外部网络调用）
OFFLINE_MODE=true

# vLLM GPU 推理（如有 GPU 节点）
VLLM_ENABLED=true
VLLM_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct
VLLM_QUANTIZATION=awq  # 或 gptq / int8 / 留空
VLLM_TENSOR_PARALLEL_SIZE=1
VLLM_GPU_MEMORY_UTILIZATION=0.9

# 启用商业 API 脱敏（如使用 OpenAI/Anthropic）
COMMERCIAL_API_MODE=strict

# 启用审计日志
AUDIT_LOG_ENABLED=true
AUDIT_LOG_RETENTION_DAYS=180
```

### 2.6 启动服务

```bash
cd /opt/synthdraft/infra

# 启动基础服务（PostgreSQL / Redis / Qdrant / MinIO / Ollama）
docker compose --env-file .env up -d

# 启动 vLLM GPU 服务（如有 GPU 节点）
docker compose --env-file .env --profile gpu up -d vllm

# 启动后端
docker compose --env-file .env up -d backend celery_worker
```

### 2.7 验证部署

```bash
# 健康检查
curl http://localhost:8000/api/v1/health

# 运行 Task 13 自测
cd /opt/synthdraft/backend
.venv/bin/python tests/verify_task13.py
```

## 三、降级路径

| 组件         | 故障场景                  | 降级行为                                  |
|--------------|---------------------------|-------------------------------------------|
| vLLM         | GPU 故障 / VLLM_ENABLED=false | 自动回退到 Ollama（CPU 推理，速度较慢）  |
| Ollama       | 服务不可达                | LLM 调用返回空 ChatResponse，pipeline 静默降级 |
| OpenAI/Anthropic | API Key 未配置        | 返回空 ChatResponse，不抛异常             |
| HuggingFace  | 离线模式 + 模型未预下载   | embedder 初始化失败，KB 检索不可用        |

## 四、注意事项

1. **模型权重体积**：完整离线包约 15-20 GB（含 7B 量化模型 + bge-m3）
2. **首次启动**：vLLM 加载 7B 模型约需 30-60 秒，请耐心等待
3. **GPU 驱动**：使用 vLLM 需预装 NVIDIA Driver + Container Toolkit
4. **审计日志**：默认保留 180 天，过期自动清理（需配置 cron 或 celery beat）
5. **合规要求**：等保三级 / ISO 27001 自评请运行 `python -m app.security.compliance`

#!/usr/bin/env bash
# SynthDraft 开发环境一键启动脚本（Linux / macOS）
# 1. 检查并创建 .env（从 .env.example 拷贝）
# 2. 启动 Docker Compose 全部服务
# 3. 输出各服务访问地址
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$REPO_ROOT/infra"

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
WHITE='\033[1;37m'
NC='\033[0m'

step()  { echo -e "${CYAN}==> $1${NC}"; }
ok()    { echo -e "  ${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "  ${YELLOW}[!]${NC}  $1"; }

# 可选参数
REBUILD=0
DOWN=0
LOGS=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --rebuild) REBUILD=1; shift ;;
        --down)    DOWN=1; shift ;;
        --logs)    LOGS=1; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ "$DOWN" -eq 1 ]]; then
    step "停止所有 SynthDraft 服务"
    (cd "$INFRA_DIR" && docker compose --env-file .env down)
    ok "已停止"
    exit 0
fi

# 1. 检查 Docker
step "检查 Docker 引擎"
if ! docker info >/dev/null 2>&1; then
    warn "Docker 未运行，请先启动 Docker"
    exit 1
fi
ok "Docker 引擎正常"

# 2. 检查 .env
cd "$INFRA_DIR"
if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
        step "从 .env.example 创建 .env"
        cp .env.example .env
        ok ".env 已创建（请按需修改密码/密钥）"
    else
        warn "未找到 .env.example，请手动创建 .env"
        exit 1
    fi
else
    ok ".env 已存在"
fi

# 3. 启动服务
step "启动 Docker Compose 服务"
COMPOSE_ARGS=(compose --env-file .env up -d)
if [[ "$REBUILD" -eq 1 ]]; then
    COMPOSE_ARGS+=(--build)
fi
docker "${COMPOSE_ARGS[@]}"

# 4. 输出访问地址
step "服务访问地址"
echo ""
echo -e "  ${WHITE}FastAPI 文档:    http://localhost:8000/docs${NC}"
echo -e "  ${WHITE}健康检查:        http://localhost:8000/api/v1/healthz${NC}"
echo -e "  ${WHITE}就绪检查:        http://localhost:8000/api/v1/readyz${NC}"
echo -e "  ${WHITE}MinIO 控制台:    http://localhost:9001${NC}"
echo -e "  ${WHITE}Qdrant 控制台:   http://localhost:6333/dashboard${NC}"
echo -e "  ${WHITE}PostgreSQL:      localhost:5432${NC}"
echo -e "  ${WHITE}Redis:           localhost:6379${NC}"
echo -e "  ${WHITE}Ollama API:      http://localhost:11434${NC}"
echo ""

if [[ "$LOGS" -eq 1 ]]; then
    step "跟踪日志（Ctrl+C 退出）"
    docker compose --env-file .env logs -f
fi

ok "启动完成"

"""允许通过 `python -m app.main` 启动开发服务器。"""

from __future__ import annotations

import uvicorn

from app.config import settings


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.APP_DEBUG and not settings.is_production,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()

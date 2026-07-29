"""安全模块（SubTask 13.4 升级为 package）。

原 ``app.security`` 单文件模块（JWT/密码哈希）的内容已迁移到本 ``__init__.py``，
确保 ``from app.security import hash_password`` 等既有 import 不被破坏。

新增子模块（SubTask 13.4）：
- compliance：等保三级 / ISO 27001 自评检查器
- audit_log：审计日志增强（用户操作 / 数据访问 / 管理员操作三类）

遵循"以复用现有为荣"原则：迁移而非重写，新增而非破坏。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """对明文密码做 bcrypt 哈希。"""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    return _pwd_context.verify(plain, hashed)


def create_access_token(
    subject: str | int,
    extra_claims: Optional[dict[str, Any]] = None,
    expires_minutes: Optional[int] = None,
) -> str:
    """签发 JWT access token。"""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(
        minutes=expires_minutes or settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """解码并校验 JWT。失败抛出 JWTError。"""
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )


def is_valid_token(token: str) -> bool:
    """快速判定 token 是否合法（不抛异常）。"""
    try:
        decode_access_token(token)
        return True
    except JWTError:
        return False

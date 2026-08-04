"""安全模块（SubTask 13.4 升级为 package）。

原 ``app.security`` 单文件模块（JWT/密码哈希）的内容已迁移到本 ``__init__.py``，
确保 ``from app.security import hash_password`` 等既有 import 不被破坏。

新增子模块（SubTask 13.4）：
- compliance：等保三级 / ISO 27001 自评检查器
- audit_log：审计日志增强（用户操作 / 数据访问 / 管理员操作三类）

遵循"以复用现有为荣"原则：迁移而非重写，新增而非破坏。
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Fernet 单例（懒加载）：从 JWT_SECRET_KEY 经 HKDF 派生 32 字节密钥。
# 选用 HKDF 而非直接使用 JWT_SECRET_KEY，因 Fernet 要求 urlsafe-base64 编码的
# 32 字节密钥，且派生可隔离 JWT 签名与配置加密的密钥用途。
# 密钥在 JWT_SECRET_KEY 不变时跨重启稳定；如需独立轮换可后续新增
# CONFIG_ENCRYPTION_KEY 配置项。
_fernet: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    """懒加载 Fernet 实例（从 JWT_SECRET_KEY 派生密钥）。"""
    global _fernet
    if _fernet is not None:
        return _fernet
    material = (settings.JWT_SECRET_KEY or "synthdraft-dev-fallback").encode("utf-8")
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"synthdraft-config-encryption",
        info=b"fernet-key",
    )
    key = base64.urlsafe_b64encode(kdf.derive(material))
    _fernet = Fernet(key)
    return _fernet


def encrypt_value(plain: str) -> str:
    """使用 Fernet 加密明文字符串。

    空字符串原样返回空字符串（本地模型无 api_key 时存空串，避免无意义密文）。
    """
    if not plain:
        return ""
    return _get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_value(cipher: str) -> str:
    """解密 Fernet 密文。

    空字符串原样返回空字符串。密文损坏或密钥不匹配时抛 ``InvalidToken``，
    由调用方决定降级策略（通常返回空串并告警）。
    """
    if not cipher:
        return ""
    return _get_fernet().decrypt(cipher.encode("utf-8")).decode("utf-8")


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

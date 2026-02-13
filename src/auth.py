"""
用户认证和权限管理模块
"""

import uuid
from datetime import datetime, timedelta
from dataclasses import asdict
from typing import Any

import bcrypt
from jose import JWTError, jwt

from src.models import User, UserRole, BUILTIN_AVATARS, InvitationCode, PasswordResetToken
from src.storage import get_data_dir, load_json, save_json

USERS_FILE = "users.json"
INVITATIONS_FILE = "invitations.json"
PASSWORD_RESETS_FILE = "password_resets.json"
SECRET_KEY = "geekbang-crawler-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


def get_users_path():
    """获取用户数据文件路径"""
    return get_data_dir() / USERS_FILE


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """创建JWT访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any] | None:
    """解码JWT令牌"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


class AuthManager:
    """认证管理器单例"""
    _instance: "AuthManager | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._users: dict[str, User] = {}
        self._load_users()
        self._initialized = True

    def _load_users(self):
        """从文件加载用户数据"""
        data = load_json(get_users_path())
        if isinstance(data, dict):
            users_data = data.get("users", [])
        elif isinstance(data, list):
            users_data = data
        else:
            users_data = []

        for user_data in users_data:
            try:
                role = UserRole(user_data.get("role", "user"))
                username = user_data["username"]
                # 向后兼容：如果旧数据没有 email，使用 username 作为 email
                email = user_data.get("email", username)
                # 向后兼容：如果旧数据没有 is_active，默认为 True
                is_active = user_data.get("is_active", True)
                user = User(
                    id=user_data["id"],
                    username=username,
                    password_hash=user_data["password_hash"],
                    nickname=user_data["nickname"],
                    avatar=user_data["avatar"],
                    role=role,
                    is_active=is_active,
                    created_at=user_data.get("created_at", ""),
                    last_login=user_data.get("last_login", ""),
                    email=email,
                )
                self._users[user.username] = user
            except (KeyError, ValueError):
                continue

    def _save_users(self):
        """保存用户数据到文件"""
        users_data = []
        for user in self._users.values():
            user_dict = asdict(user)
            user_dict["role"] = user.role.value  # Convert enum to string
            users_data.append(user_dict)
        save_json(get_users_path(), {"users": users_data})

    def get_user(self, username: str) -> User | None:
        """根据用户名获取用户"""
        return self._users.get(username)

    def get_user_by_id(self, user_id: str) -> User | None:
        """根据用户ID获取用户"""
        for user in self._users.values():
            if user.id == user_id:
                return user
        return None

    def authenticate(self, username: str, password: str) -> User | None:
        """验证用户登录"""
        user = self.get_user(username)
        if not user:
            return None
        if not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None

        user.last_login = datetime.utcnow().isoformat()
        self._save_users()
        return user

    def register(
        self,
        username: str,
        password: str,
        nickname: str,
        avatar: str,
        role: UserRole = UserRole.USER,
    ) -> tuple[bool, str, User | None]:
        """注册新用户

        Returns:
            (success, message, user)
        """
        if len(password) < 8:
            return False, "密码长度必须大于等于8位", None

        if username in self._users:
            return False, "用户名已存在", None

        if avatar not in BUILTIN_AVATARS:
            avatar = BUILTIN_AVATARS[0]

        user = User(
            id=str(uuid.uuid4()),
            username=username,  # username 就是邮箱地址
            password_hash=get_password_hash(password),
            nickname=nickname,
            avatar=avatar,
            role=role,
            created_at=datetime.utcnow().isoformat(),
            last_login=datetime.utcnow().isoformat(),
            email=username,  # email 与 username 相同
        )

        self._users[username] = user
        self._save_users()

        return True, "注册成功", user

    def create_token(self, user: User) -> str:
        """为用户创建访问令牌"""
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        token_data = {
            "sub": user.id,
            "username": user.username,
            "role": user.role.value,
        }
        return create_access_token(token_data, access_token_expires)

    def verify_token(self, token: str) -> User | None:
        """验证令牌并返回用户"""
        payload = decode_access_token(token)
        if not payload:
            return None

        user_id = payload.get("sub")
        if not user_id:
            return None

        return self.get_user_by_id(user_id)

    def get_all_users(self) -> list[User]:
        """获取所有用户（仅管理员可用）"""
        return list(self._users.values())

    def delete_user(self, username: str) -> bool:
        """删除用户（仅管理员可用）"""
        if username not in self._users:
            return False

        del self._users[username]
        self._save_users()
        return True

    def update_user_role(self, username: str, role: UserRole) -> bool:
        """更新用户角色（仅管理员可用）"""
        user = self.get_user(username)
        if not user:
            return False

        user.role = role
        self._save_users()
        return True

    def reset_user_password(self, username: str, new_password: str = "pwd@12345") -> bool:
        """重置用户密码（仅管理员可用）"""
        user = self.get_user(username)
        if not user:
            return False

        user.password_hash = get_password_hash(new_password)
        self._save_users()
        return True

    def toggle_user_status(self, username: str) -> bool:
        """切换用户启用/禁用状态（仅管理员可用）"""
        user = self.get_user(username)
        if not user:
            return False

        user.is_active = not user.is_active
        self._save_users()
        return True

    def has_users(self) -> bool:
        """检查是否有用户存在"""
        return len(self._users) > 0

    def is_first_setup(self) -> bool:
        """检查是否首次设置（无用户）"""
        return not self.has_users()

    def update_user(self, user: User) -> bool:
        """更新用户信息"""
        if user.username not in self._users:
            return False
        self._users[user.username] = user
        self._save_users()
        return True


class InvitationManager:
    """邀请码管理器单例"""
    _instance: "InvitationManager | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._invitations: dict[str, InvitationCode] = {}
        self._load_invitations()
        self._initialized = True

    def _load_invitations(self):
        """从文件加载邀请码数据"""
        data = load_json(get_data_dir() / INVITATIONS_FILE)
        if isinstance(data, dict):
            invitations_data = data.get("invitations", [])
        elif isinstance(data, list):
            invitations_data = data
        else:
            invitations_data = []

        for inv_data in invitations_data:
            try:
                inv = InvitationCode(
                    id=inv_data["id"],
                    code=inv_data["code"],
                    created_by=inv_data["created_by"],
                    created_at=inv_data["created_at"],
                    expires_at=inv_data["expires_at"],
                    used=inv_data.get("used", False),
                    used_by=inv_data.get("used_by", ""),
                    used_at=inv_data.get("used_at", ""),
                )
                self._invitations[inv.code] = inv
            except (KeyError, ValueError):
                continue

    def _save_invitations(self):
        """保存邀请码数据到文件"""
        invitations_data = []
        for inv in self._invitations.values():
            inv_dict = {
                "id": inv.id,
                "code": inv.code,
                "created_by": inv.created_by,
                "created_at": inv.created_at,
                "expires_at": inv.expires_at,
                "used": inv.used,
                "used_by": inv.used_by,
                "used_at": inv.used_at,
            }
            invitations_data.append(inv_dict)
        save_json(get_data_dir() / INVITATIONS_FILE, {"invitations": invitations_data})

    def create_invitation(self, created_by: str, days: int = 3) -> InvitationCode:
        """创建邀请码"""
        import secrets
        import string

        code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        now = datetime.utcnow()
        expires_at = (now + timedelta(days=days)).isoformat()

        inv = InvitationCode(
            id=str(uuid.uuid4()),
            code=code,
            created_by=created_by,
            created_at=now.isoformat(),
            expires_at=expires_at,
            used=False,
        )

        self._invitations[code] = inv
        self._save_invitations()
        return inv

    def validate_invitation(self, code: str) -> tuple[bool, str]:
        """验证邀请码是否有效"""
        inv = self._invitations.get(code)
        if not inv:
            return False, "邀请码不存在"

        if inv.used:
            return False, "邀请码已被使用"

        now = datetime.utcnow()
        if now > datetime.fromisoformat(inv.expires_at):
            return False, "邀请码已过期"

        return True, ""

    def use_invitation(self, code: str, used_by: str) -> bool:
        """使用邀请码"""
        inv = self._invitations.get(code)
        if not inv or inv.used:
            return False

        inv.used = True
        inv.used_by = used_by
        inv.used_at = datetime.utcnow().isoformat()
        self._save_invitations()
        return True

    def get_all_invitations(self) -> list[InvitationCode]:
        """获取所有邀请码"""
        return list(self._invitations.values())

    def delete_invitation(self, code: str) -> bool:
        """删除邀请码"""
        if code not in self._invitations:
            return False

        del self._invitations[code]
        self._save_invitations()
        return True


class PasswordResetManager:
    """密码重置管理器单例"""
    _instance: "PasswordResetManager | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._tokens: dict[str, PasswordResetToken] = {}
        self._load_tokens()
        self._initialized = True

    def _load_tokens(self):
        """从文件加载密码重置令牌数据"""
        data = load_json(get_data_dir() / PASSWORD_RESETS_FILE)
        if isinstance(data, dict):
            tokens_data = data.get("tokens", [])
        elif isinstance(data, list):
            tokens_data = data
        else:
            tokens_data = []

        for token_data in tokens_data:
            try:
                token = PasswordResetToken(
                    id=token_data["id"],
                    user_id=token_data["user_id"],
                    token=token_data["token"],
                    email=token_data["email"],
                    created_at=token_data["created_at"],
                    expires_at=token_data["expires_at"],
                    used=token_data.get("used", False),
                )
                self._tokens[token.token] = token
            except (KeyError, ValueError):
                continue

    def _save_tokens(self):
        """保存密码重置令牌数据到文件"""
        tokens_data = []
        for token in self._tokens.values():
            token_dict = {
                "id": token.id,
                "user_id": token.user_id,
                "token": token.token,
                "email": token.email,
                "created_at": token.created_at,
                "expires_at": token.expires_at,
                "used": token.used,
            }
            tokens_data.append(token_dict)
        save_json(get_data_dir() / PASSWORD_RESETS_FILE, {"tokens": tokens_data})

    def create_reset_token(self, user_id: str, email: str) -> PasswordResetToken:
        """创建密码重置令牌"""
        import secrets

        token = secrets.token_urlsafe(32)
        now = datetime.utcnow()
        expires_at = (now + timedelta(hours=1)).isoformat()

        reset_token = PasswordResetToken(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token=token,
            email=email,
            created_at=now.isoformat(),
            expires_at=expires_at,
            used=False,
        )

        self._tokens[token] = reset_token
        self._save_tokens()
        return reset_token

    def validate_token(self, token: str) -> tuple[bool, str, PasswordResetToken | None]:
        """验证密码重置令牌"""
        reset_token = self._tokens.get(token)
        if not reset_token:
            return False, "重置令牌无效", None

        if reset_token.used:
            return False, "重置令牌已被使用", None

        now = datetime.utcnow()
        if now > datetime.fromisoformat(reset_token.expires_at):
            return False, "重置令牌已过期", None

        return True, "", reset_token

    def use_token(self, token: str) -> bool:
        """标记令牌为已使用"""
        reset_token = self._tokens.get(token)
        if not reset_token or reset_token.used:
            return False

        reset_token.used = True
        self._save_tokens()
        return True


auth_manager = AuthManager()
invitation_manager = InvitationManager()
password_reset_manager = PasswordResetManager()

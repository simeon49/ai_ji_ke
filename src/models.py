from dataclasses import dataclass, field
from enum import Enum


class LessonType(Enum):
    TEXT = "text"
    VIDEO = "video"
    AUDIO = "audio"


class UserRole(Enum):
    ADMIN = "admin"
    USER = "user"


BUILTIN_AVATARS = [
    "avatar_1.png",
    "avatar_2.png",
    "avatar_3.png",
    "avatar_4.png",
    "avatar_5.png",
    "avatar_6.png",
    "avatar_7.png",
    "avatar_8.png",
]


@dataclass
class Lesson:
    id: str
    title: str
    url: str
    type: LessonType = LessonType.TEXT
    duration: str = ""
    is_free: bool = False
    order: int = 0
    chapter_order: int = 0


@dataclass
class Chapter:
    title: str
    order: int = 0
    lessons: list[Lesson] = field(default_factory=list)


@dataclass
class AuthorInfo:
    """讲师信息"""

    name: str = ""
    intro: str = ""  # 简短介绍
    avatar: str = ""  # 头像URL
    brief: str = ""  # 详细介绍（纯文本）
    brief_html: str = ""  # 详细介绍（HTML格式）


@dataclass
class CourseModule:
    """课程模块内容（如课程介绍、你将获得等）"""

    name: str  # 模块标识
    title: str  # 模块标题
    content: str  # HTML内容
    type: str = "normal"  # 类型：normal, activity 等
    is_top: bool = False


@dataclass
class CourseIntro:
    """课程扩展信息，从 v3/column/info API 获取"""

    title: str
    subtitle: str = ""

    # 课程基本信息
    course_type: str = ""  # 类型标识：c1 等
    unit: str = ""  # 总课程数，如 "22讲"
    is_finish: bool = False  # 是否完结
    cover_url: str = ""  # 封面图（square）

    # SEO 关键词
    keywords: list[str] = field(default_factory=list)

    # 讲师信息
    author: AuthorInfo = field(default_factory=AuthorInfo)

    # 课程模块（从 extra.modules 获取）
    modules: list[CourseModule] = field(default_factory=list)

    # 向后兼容的旧字段
    author_name: str = ""
    author_intro: str = ""
    author_header: str = ""  # 讲师头像
    total_lessons: int = 0
    is_finished: bool = False
    description: str = ""  # 课程介绍 (column_intro)
    description_html: str = ""  # 课程介绍HTML格式 (从intro页面获取)
    # intro 页面详细信息
    highlights: list[str] = field(default_factory=list)  # 你将获得
    audience: list[str] = field(default_factory=list)  # 适合人群
    outline: list[dict] = field(default_factory=list)  # 课程大纲 [{title, articles: [{title}]}]
    learn_count: int = 0  # 学习人数
    catalog_pics: list[str] = field(default_factory=list)  # 目录图片


@dataclass
class Course:
    id: str
    title: str
    author: str
    description: str = ""
    chapters: list[Chapter] = field(default_factory=list)
    intro: CourseIntro | None = None
    raw_data: dict = field(default_factory=dict)  # 原始 column_info API 数据

    @property
    def all_lessons(self) -> list[Lesson]:
        lessons = []
        for chapter in self.chapters:
            lessons.extend(chapter.lessons)
        return lessons


@dataclass
class CommentReply:
    id: int
    content: str
    user_name: str
    ctime: int
    ip_address: str = ""


@dataclass
class Comment:
    id: int
    user_name: str
    content: str
    ctime: int
    like_count: int = 0
    ip_address: str = ""
    user_header: str = ""
    is_top: bool = False
    replies: list[CommentReply] = field(default_factory=list)


@dataclass
class LessonContent:
    lesson: Lesson
    html_content: str = ""
    text_content: str = ""
    images: list[str] = field(default_factory=list)
    audio_url: str = ""
    video_url: str = ""
    comments: list[Comment] = field(default_factory=list)


@dataclass
class User:
    id: str
    username: str  # 登录账号，同时也是邮箱地址
    password_hash: str
    nickname: str
    avatar: str
    role: UserRole = UserRole.USER
    is_active: bool = True
    created_at: str = ""
    last_login: str = ""
    email: str = ""  # 与 username 相同，用于找回密码等功能

    def __post_init__(self):
        """确保 email 字段与 username 同步"""
        if not self.email and self.username:
            self.email = self.username


@dataclass
class InvitationCode:
    id: str
    code: str
    created_by: str  # username of admin who created it
    created_at: str
    expires_at: str
    used: bool = False
    used_by: str = ""  # username of user who used it
    used_at: str = ""


@dataclass
class PasswordResetToken:
    id: str
    user_id: str
    token: str
    email: str
    created_at: str
    expires_at: str
    used: bool = False

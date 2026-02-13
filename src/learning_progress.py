import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.storage import get_learning_record_path


_executor = ThreadPoolExecutor(max_workers=2)


@dataclass
class LessonCompletion:
    """小节完成记录"""
    lesson_id: str
    completed_at: str
    completion_type: str  # "scroll" | "media" | "bottom"


@dataclass
class UserLearningProgress:
    """用户学习进度"""
    user_id: str
    username: str
    completed_lessons: dict[str, LessonCompletion] = field(default_factory=dict)
    
    def is_lesson_completed(self, lesson_id: str) -> bool:
        """检查小节是否已完成"""
        return lesson_id in self.completed_lessons
    
    def mark_lesson_completed(self, lesson_id: str, completion_type: str = "scroll"):
        """标记小节为已完成"""
        self.completed_lessons[lesson_id] = LessonCompletion(
            lesson_id=lesson_id,
            completed_at=datetime.now().isoformat(),
            completion_type=completion_type
        )
    
    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化的字典"""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "completed_lessons": {
                lid: {
                    "lesson_id": lc.lesson_id,
                    "completed_at": lc.completed_at,
                    "completion_type": lc.completion_type
                }
                for lid, lc in self.completed_lessons.items()
            }
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserLearningProgress":
        """从字典恢复"""
        completed_lessons = {}
        for lid, lc_data in data.get("completed_lessons", {}).items():
            completed_lessons[lid] = LessonCompletion(**lc_data)
        
        return cls(
            user_id=data["user_id"],
            username=data["username"],
            completed_lessons=completed_lessons
        )


@dataclass
class CourseLearningProgress:
    """课程学习进度（包含所有用户）"""
    users: dict[str, UserLearningProgress] = field(default_factory=dict)
    
    def get_user_progress(self, user_id: str, username: str) -> UserLearningProgress:
        """获取或创建用户进度"""
        if user_id not in self.users:
            self.users[user_id] = UserLearningProgress(user_id=user_id, username=username)
        return self.users[user_id]
    
    def is_lesson_completed(self, user_id: str, lesson_id: str) -> bool:
        """检查用户是否已完成某小节"""
        if user_id not in self.users:
            return False
        return self.users[user_id].is_lesson_completed(lesson_id)
    
    def mark_lesson_completed(self, user_id: str, username: str, lesson_id: str, completion_type: str = "scroll"):
        """标记用户完成某小节"""
        user_progress = self.get_user_progress(user_id, username)
        user_progress.mark_lesson_completed(lesson_id, completion_type)
    
    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化的字典"""
        return {
            "users": {
                uid: up.to_dict()
                for uid, up in self.users.items()
            }
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CourseLearningProgress":
        """从字典恢复"""
        users = {}
        for uid, up_data in data.get("users", {}).items():
            users[uid] = UserLearningProgress.from_dict(up_data)
        
        return cls(users=users)


class LearningProgressManager:
    """学习进度管理器"""

    def __init__(self, course_id: str, course_dir: Path | None = None):
        self.course_id = course_id
        self.course_dir = course_dir  # 用于获取课程目录信息（可选）
        self.progress_file = get_learning_record_path(course_id)
        self._progress: CourseLearningProgress | None = None

    def load(self) -> CourseLearningProgress:
        """加载学习进度"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._progress = CourseLearningProgress.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                self._progress = CourseLearningProgress()
        else:
            self._progress = CourseLearningProgress()

        return self._progress

    def _save_sync(self):
        """同步保存"""
        if not self._progress:
            return
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.progress_file, "w", encoding="utf-8") as f:
            json.dump(self._progress.to_dict(), f, ensure_ascii=False, indent=2)

    def save(self):
        """异步保存"""
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            loop.run_in_executor(_executor, self._save_sync)
        except RuntimeError:
            self._save_sync()

    @property
    def progress(self) -> CourseLearningProgress | None:
        return self._progress

    def is_lesson_completed(self, user_id: str, lesson_id: str) -> bool:
        """检查用户是否已完成某小节"""
        if not self._progress:
            return False
        return self._progress.is_lesson_completed(user_id, lesson_id)

    def mark_lesson_completed(self, user_id: str, username: str, lesson_id: str, completion_type: str = "scroll"):
        """标记用户完成某小节"""
        if not self._progress:
            self.load()

        assert self._progress is not None
        normalized_lesson_id = lesson_id.replace("org_courses/", "")
        self._progress.mark_lesson_completed(user_id, username, normalized_lesson_id, completion_type)
        self.save()

    def get_user_completed_lessons(self, user_id: str) -> list[str]:
        """获取用户已完成的小节列表"""
        if not self._progress:
            return []
        if user_id not in self._progress.users:
            return []
        return list(self._progress.users[user_id].completed_lessons.keys())

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


_executor = ThreadPoolExecutor(max_workers=2)


@dataclass
class LessonProgress:
    lesson_id: str
    title: str
    content_done: bool = False
    images_done: bool = False
    audio_done: bool = False
    video_done: bool = False
    completed_at: str | None = None
    error: str | None = None
    
    @property
    def is_complete(self) -> bool:
        return self.content_done
    
    def mark_complete(self):
        self.completed_at = datetime.now().isoformat()


@dataclass
class CourseProgress:
    course_id: str
    course_title: str
    lessons: dict[str, LessonProgress] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: str | None = None
    total_lessons: int = 0
    
    @property
    def completed_count(self) -> int:
        return sum(1 for lp in self.lessons.values() if lp.is_complete)
    
    @property
    def is_complete(self) -> bool:
        return self.total_lessons > 0 and self.completed_count >= self.total_lessons
    
    def get_lesson_progress(self, lesson_id: str) -> LessonProgress | None:
        return self.lessons.get(lesson_id)
    
    def is_lesson_complete(self, lesson_id: str) -> bool:
        lp = self.lessons.get(lesson_id)
        return lp is not None and lp.is_complete
    
    def set_lesson_progress(self, lesson_id: str, title: str, **kwargs) -> LessonProgress:
        """设置或更新课程进度"""
        if lesson_id not in self.lessons:
            self.lessons[lesson_id] = LessonProgress(lesson_id=lesson_id, title=title)
        
        lp = self.lessons[lesson_id]
        for key, value in kwargs.items():
            if hasattr(lp, key):
                setattr(lp, key, value)
        
        self.updated_at = datetime.now().isoformat()
        return lp
    
    def mark_lesson_complete(
        self, 
        lesson_id: str, 
        title: str,
        images_done: bool = False,
        audio_done: bool = False,
        video_done: bool = False,
    ):
        """标记课程为完成"""
        lp = self.set_lesson_progress(
            lesson_id, title, 
            content_done=True,
            images_done=images_done,
            audio_done=audio_done,
            video_done=video_done,
        )
        lp.mark_complete()
        self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化的字典"""
        return {
            "course_id": self.course_id,
            "course_title": self.course_title,
            "lessons": {
                lid: asdict(lp) for lid, lp in self.lessons.items()
            },
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "total_lessons": self.total_lessons,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CourseProgress":
        """从字典恢复"""
        lessons = {}
        for lid, lp_data in data.get("lessons", {}).items():
            lessons[lid] = LessonProgress(**lp_data)
        
        return cls(
            course_id=data["course_id"],
            course_title=data["course_title"],
            lessons=lessons,
            started_at=data.get("started_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            completed_at=data.get("completed_at"),
            total_lessons=data.get("total_lessons", 0),
        )


class ProgressManager:
    """进度管理器 - 负责加载/保存进度文件"""
    
    PROGRESS_FILE = ".progress.json"
    
    def __init__(self, course_dir: Path):
        self.course_dir = course_dir
        self.progress_file = course_dir / self.PROGRESS_FILE
        self._progress: CourseProgress | None = None
    
    def load(self, course_id: str, course_title: str) -> CourseProgress:
        if self.progress_file.exists():
            try:
                with open(self.progress_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._progress = CourseProgress.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                self._progress = CourseProgress(course_id=course_id, course_title=course_title)
        else:
            self._progress = CourseProgress(course_id=course_id, course_title=course_title)
        
        return self._progress
    
    def _save_sync(self):
        if not self._progress:
            return
        self._progress.updated_at = datetime.now().isoformat()
        self.course_dir.mkdir(parents=True, exist_ok=True)
        with open(self.progress_file, "w", encoding="utf-8") as f:
            json.dump(self._progress.to_dict(), f, ensure_ascii=False, indent=2)
    
    def save(self):
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(_executor, self._save_sync)
        except RuntimeError:
            self._save_sync()
    
    @property
    def progress(self) -> CourseProgress | None:
        return self._progress
    
    def is_lesson_complete(self, lesson_id: str) -> bool:
        """检查课程是否已完成"""
        if not self._progress:
            return False
        return self._progress.is_lesson_complete(lesson_id)
    
    def mark_lesson_complete(
        self, 
        lesson_id: str, 
        title: str,
        images_done: bool = False,
        audio_done: bool = False,
        video_done: bool = False,
    ):
        """标记课程为完成并保存"""
        if not self._progress:
            return
        self._progress.mark_lesson_complete(
            lesson_id, title,
            images_done=images_done,
            audio_done=audio_done,
            video_done=video_done,
        )
        self.save()
    
    def update_lesson_progress(self, lesson_id: str, title: str, **kwargs):
        """更新课程进度并保存"""
        if not self._progress:
            return
        self._progress.set_lesson_progress(lesson_id, title, **kwargs)
        self.save()
    
    def set_total_lessons(self, total: int):
        """设置总课程数"""
        if not self._progress:
            return
        self._progress.total_lessons = total
        self.save()
    
    def get_pending_lessons(self, all_lesson_ids: list[str]) -> list[str]:
        if not self._progress:
            return all_lesson_ids
        return [lid for lid in all_lesson_ids if not self._progress.is_lesson_complete(lid)]
    
    def print_summary(self):
        pass

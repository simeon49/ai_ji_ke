import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Any

from src.storage import load_tasks, save_tasks


AUTO_DELETE_DELAY = 30


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskProgress:
    current: int = 0
    total: int = 0
    current_item: str = ""
    
    @property
    def percentage(self) -> int:
        if self.total == 0:
            return 0
        return int((self.current / self.total) * 100)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "total": self.total,
            "current_item": self.current_item,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TaskProgress":
        return cls(
            current=data.get("current", 0),
            total=data.get("total", 0),
            current_item=data.get("current_item", ""),
        )


@dataclass
class CrawlTask:
    id: str
    url: str
    status: TaskStatus = TaskStatus.PENDING
    course_title: str = ""
    course_id: str = ""
    output_dir: str = ""
    progress: TaskProgress = field(default_factory=TaskProgress)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str = ""
    logs: list[str] = field(default_factory=list)
    
    headless: bool = True
    download_images: bool = True
    download_audio: bool = True
    download_video: bool = True
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "status": self.status.value,
            "course_title": self.course_title,
            "course_id": self.course_id,
            "output_dir": self.output_dir,
            "progress": {
                "current": self.progress.current,
                "total": self.progress.total,
                "percentage": self.progress.percentage,
                "current_item": self.progress.current_item,
            },
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            "logs": self.logs[-50:],
            "headless": self.headless,
            "download_images": self.download_images,
            "download_audio": self.download_audio,
            "download_video": self.download_video,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CrawlTask":
        progress_data = data.get("progress", {})
        progress = TaskProgress(
            current=progress_data.get("current", 0),
            total=progress_data.get("total", 0),
            current_item=progress_data.get("current_item", ""),
        )
        
        def parse_datetime(s: str | None) -> datetime | None:
            if not s:
                return None
            try:
                return datetime.fromisoformat(s)
            except (ValueError, TypeError):
                return None
        
        return cls(
            id=data["id"],
            url=data["url"],
            status=TaskStatus(data.get("status", "pending")),
            course_title=data.get("course_title", ""),
            course_id=data.get("course_id", ""),
            output_dir=data.get("output_dir", ""),
            progress=progress,
            created_at=parse_datetime(data.get("created_at")) or datetime.now(),
            started_at=parse_datetime(data.get("started_at")),
            completed_at=parse_datetime(data.get("completed_at")),
            error_message=data.get("error_message", ""),
            logs=data.get("logs", []),
            headless=data.get("headless", True),
            download_images=data.get("download_images", True),
            download_audio=data.get("download_audio", True),
            download_video=data.get("download_video", True),
        )


class TaskManager:
    def __init__(self, max_concurrent: int = 1):
        self._tasks: dict[str, CrawlTask] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._max_concurrent = max_concurrent
        self._running_count = 0
        self._worker_task: asyncio.Task | None = None
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._global_subscribers: list[asyncio.Queue] = []
        self._runner: Callable | None = None
        
        self._pause_events: dict[str, asyncio.Event] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}
        
        self._load_from_storage()
    
    def _load_from_storage(self):
        tasks_data = load_tasks()
        for task_data in tasks_data:
            try:
                task = CrawlTask.from_dict(task_data)
                if task.status == TaskStatus.RUNNING:
                    task.status = TaskStatus.PENDING
                self._tasks[task.id] = task
            except (KeyError, ValueError):
                continue
    
    def _save_to_storage(self):
        tasks_data = [task.to_dict() for task in self._tasks.values()]
        save_tasks(tasks_data)
    
    async def _restore_pending_tasks(self):
        for task in self._tasks.values():
            if task.status == TaskStatus.PENDING:
                await self._queue.put(task.id)
    
    def set_runner(self, runner: Callable):
        self._runner = runner
    
    def create_task(
        self,
        url: str,
        output_dir: str = "./output",
        headless: bool = True,
        download_images: bool = True,
        download_audio: bool = True,
        download_video: bool = True,
    ) -> CrawlTask:
        task_id = str(uuid.uuid4())[:8]
        task = CrawlTask(
            id=task_id,
            url=url,
            output_dir=output_dir,
            headless=headless,
            download_images=download_images,
            download_audio=download_audio,
            download_video=download_video,
        )
        self._tasks[task_id] = task
        self._save_to_storage()
        return task
    
    async def enqueue(self, task: CrawlTask):
        await self._queue.put(task.id)
        await self._notify_global({"type": "task_queued", "task": task.to_dict()})
    
    def get_task(self, task_id: str) -> CrawlTask | None:
        return self._tasks.get(task_id)
    
    def get_all_tasks(self) -> list[CrawlTask]:
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
    
    def get_tasks_by_status(self, status: TaskStatus) -> list[CrawlTask]:
        return [t for t in self._tasks.values() if t.status == status]
    
    async def cancel_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        if task.status == TaskStatus.PENDING:
            task.status = TaskStatus.CANCELLED
            self._save_to_storage()
            await self._notify_task(task_id, {"type": "cancelled"})
            await self._notify_global({"type": "task_cancelled", "task": task.to_dict()})
            return True
        
        if task.status == TaskStatus.RUNNING:
            if task_id in self._cancel_events:
                self._cancel_events[task_id].set()
            if task_id in self._running_tasks:
                self._running_tasks[task_id].cancel()
            return True
        
        return False
    
    async def pause_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        if task.status == TaskStatus.PENDING:
            task.status = TaskStatus.PAUSED
            self._save_to_storage()
            await self._notify_task(task_id, {"type": "paused"})
            await self._notify_global({"type": "task_paused", "task": task.to_dict()})
            return True
        
        if task.status == TaskStatus.RUNNING:
            if task_id in self._pause_events:
                self._pause_events[task_id].clear()
            task.status = TaskStatus.PAUSED
            self._save_to_storage()
            await self._notify_task(task_id, {"type": "paused"})
            await self._notify_global({"type": "task_paused", "task": task.to_dict()})
            return True
        
        return False
    
    async def resume_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        if task.status == TaskStatus.PAUSED:
            task.status = TaskStatus.PENDING
            self._save_to_storage()
            await self._queue.put(task_id)
            await self._notify_task(task_id, {"type": "resumed"})
            await self._notify_global({"type": "task_resumed", "task": task.to_dict()})
            return True
        
        return False
    
    async def retry_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        if task.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False
        
        task.status = TaskStatus.PENDING
        task.error_message = ""
        task.started_at = None
        task.completed_at = None
        task.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 任务重试")
        self._save_to_storage()
        
        await self._queue.put(task_id)
        await self._notify_task(task_id, {"type": "retrying"})
        await self._notify_global({"type": "task_retrying", "task": task.to_dict()})
        return True
    
    def delete_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        if task.status == TaskStatus.RUNNING:
            return False
        
        del self._tasks[task_id]
        self._cleanup_task_events(task_id)
        self._save_to_storage()
        return True
    
    def _cleanup_task_events(self, task_id: str):
        self._pause_events.pop(task_id, None)
        self._cancel_events.pop(task_id, None)
        self._running_tasks.pop(task_id, None)
    
    def is_cancelled(self, task_id: str) -> bool:
        if task_id in self._cancel_events:
            return self._cancel_events[task_id].is_set()
        return False
    
    async def update_task_progress(
        self,
        task_id: str,
        current: int | None = None,
        total: int | None = None,
        current_item: str | None = None,
    ):
        task = self._tasks.get(task_id)
        if not task:
            return
        
        if current is not None:
            task.progress.current = current
        if total is not None:
            task.progress.total = total
        if current_item is not None:
            task.progress.current_item = current_item
        
        await self._notify_task(task_id, {
            "type": "progress",
            "progress": {
                "current": task.progress.current,
                "total": task.progress.total,
                "percentage": task.progress.percentage,
                "current_item": task.progress.current_item,
            }
        })
    
    async def add_task_log(self, task_id: str, message: str):
        task = self._tasks.get(task_id)
        if not task:
            return
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        task.logs.append(log_entry)
        
        await self._notify_task(task_id, {"type": "log", "message": log_entry})
    
    async def set_task_course_info(self, task_id: str, course_id: str, course_title: str):
        task = self._tasks.get(task_id)
        if not task:
            return
        
        task.course_id = course_id
        task.course_title = course_title
        
        await self._notify_task(task_id, {
            "type": "course_info",
            "course_id": course_id,
            "course_title": course_title,
        })
        await self._notify_global({"type": "task_updated", "task": task.to_dict()})
    
    def subscribe_task(self, task_id: str) -> asyncio.Queue:
        if task_id not in self._subscribers:
            self._subscribers[task_id] = []
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[task_id].append(queue)
        return queue
    
    def unsubscribe_task(self, task_id: str, queue: asyncio.Queue):
        if task_id in self._subscribers:
            try:
                self._subscribers[task_id].remove(queue)
            except ValueError:
                pass
    
    def subscribe_global(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._global_subscribers.append(queue)
        return queue
    
    def unsubscribe_global(self, queue: asyncio.Queue):
        try:
            self._global_subscribers.remove(queue)
        except ValueError:
            pass
    
    async def _notify_task(self, task_id: str, event: dict):
        event["task_id"] = task_id
        for queue in self._subscribers.get(task_id, []):
            try:
                await queue.put(event)
            except Exception:
                pass
    
    async def _notify_global(self, event: dict):
        for queue in self._global_subscribers:
            try:
                await queue.put(event)
            except Exception:
                pass
    
    async def start_worker(self):
        if self._worker_task is not None:
            return
        await self._restore_pending_tasks()
        self._worker_task = asyncio.create_task(self._worker_loop())
    
    async def stop_worker(self):
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
    
    async def _worker_loop(self):
        from src.crawler_runner import TaskPaused
        
        while True:
            task_id = await self._queue.get()
            task = self._tasks.get(task_id)
            
            if not task or task.status == TaskStatus.CANCELLED:
                self._queue.task_done()
                continue
            
            if task.status == TaskStatus.PAUSED:
                self._queue.task_done()
                continue
            
            self._pause_events[task_id] = asyncio.Event()
            self._pause_events[task_id].set()
            self._cancel_events[task_id] = asyncio.Event()
            
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now()
            self._save_to_storage()
            await self._notify_task(task_id, {"type": "started"})
            await self._notify_global({"type": "task_started", "task": task.to_dict()})
            
            try:
                if self._runner:
                    runner_task = asyncio.create_task(self._runner(task, self))
                    self._running_tasks[task_id] = runner_task
                    await runner_task
                
                if task.status == TaskStatus.PAUSED:
                    pass
                else:
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = datetime.now()
                    self._save_to_storage()
                    await self._notify_task(task_id, {"type": "completed"})
                    await self._notify_global({"type": "task_completed", "task": task.to_dict()})
                    asyncio.create_task(self._schedule_auto_delete(task_id))
            
            except TaskPaused:
                self._save_to_storage()
                await self.add_task_log(task_id, "任务已暂停，浏览器会话已关闭")
                await self._notify_task(task_id, {"type": "paused"})
                await self._notify_global({"type": "task_paused", "task": task.to_dict()})
            
            except asyncio.CancelledError:
                if task.status != TaskStatus.PAUSED:
                    task.status = TaskStatus.CANCELLED
                    self._save_to_storage()
                    await self._notify_task(task_id, {"type": "cancelled"})
                    await self._notify_global({"type": "task_cancelled", "task": task.to_dict()})
            
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                task.completed_at = datetime.now()
                self._save_to_storage()
                await self.add_task_log(task_id, f"Error: {e}")
                await self._notify_task(task_id, {"type": "failed", "error": str(e)})
                await self._notify_global({"type": "task_failed", "task": task.to_dict()})
            
            finally:
                self._cleanup_task_events(task_id)
                self._queue.task_done()
    
    async def _schedule_auto_delete(self, task_id: str):
        await asyncio.sleep(AUTO_DELETE_DELAY)
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.COMPLETED:
            del self._tasks[task_id]
            self._save_to_storage()
            await self._notify_global({"type": "task_deleted", "task_id": task_id})


task_manager = TaskManager()

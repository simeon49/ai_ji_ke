import asyncio
import json
from contextlib import asynccontextmanager
from functools import wraps
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request, Form, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel

from src.task_manager import task_manager, TaskStatus
from src.crawler_runner import run_crawl_task
from src.settings import settings_manager
from src.auth import auth_manager, invitation_manager, password_reset_manager, UserRole
from src.models import User, BUILTIN_AVATARS
from src.learning_progress import LearningProgressManager
from src.label_manager import get_label_manager, CourseLabels
from urllib.parse import unquote

# 初始化标签管理器
label_manager = get_label_manager()


def get_current_user(request: Request) -> User | None:
    """从请求中获取当前登录用户"""
    token = request.cookies.get("access_token")
    if not token:
        return None
    return auth_manager.verify_token(token)


def require_auth():
    """要求用户登录的依赖"""
    def dependency(request: Request) -> User:
        user = get_current_user(request)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": f"/auth/login?next={request.url.path}"}
            )
        return user
    return Depends(dependency)


def require_admin():
    """要求管理员权限的依赖"""
    def dependency(request: Request) -> User:
        user = get_current_user(request)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": f"/auth/login?next={request.url.path}"}
            )
        if user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="需要管理员权限")
        return user
    return Depends(dependency)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task_manager.set_runner(run_crawl_task)
    await task_manager.start_worker()
    yield
    await task_manager.stop_worker()


app = FastAPI(title="Geekbang Crawler Manager", lifespan=lifespan)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

TEMPLATES_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

ORG_COURSES_DIR = Path("./org_courses")
if ORG_COURSES_DIR.exists():
    app.mount("/course_files", StaticFiles(directory=str(ORG_COURSES_DIR)), name="course_files")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if auth_manager.is_first_setup():
        return RedirectResponse(url="/auth/register", status_code=303)
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)
    return RedirectResponse(url="/courses", status_code=303)


@app.get("/auth/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = "", message: str = ""):
    current_user = get_current_user(request)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": error,
            "message": message,
            "current_user": current_user,
        },
    )


@app.post("/auth/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = "/courses",
):
    user = auth_manager.authenticate(username, password)
    if not user:
        return RedirectResponse(
            url=f"/auth/login?error=用户名或密码错误&next={next}",
            status_code=303
        )

    token = auth_manager.create_token(user)
    response = RedirectResponse(url=next, status_code=303)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,
        samesite="lax",
    )
    return response


@app.get("/auth/register", response_class=HTMLResponse)
async def register_page(request: Request, error: str = ""):
    if not auth_manager.is_first_setup():
        user = get_current_user(request)
        if user and user.role == UserRole.ADMIN:
            return RedirectResponse(url="/admin/users", status_code=303)
        elif user:
            return RedirectResponse(url="/courses", status_code=303)

    is_first = auth_manager.is_first_setup()
    return templates.TemplateResponse(
        "register.html",
        {
            "request": request,
            "error": error,
            "avatars": BUILTIN_AVATARS,
            "current_user": None,
            "is_first_setup": is_first,
        },
        )


@app.post("/auth/register")
async def register(
    request: Request,
    username: str = Form(...),  # username 就是邮箱地址
    password: str = Form(...),
    nickname: str = Form(...),
    avatar: str = Form(BUILTIN_AVATARS[0]),
    invitation_code: str = Form(""),
):
    is_first = auth_manager.is_first_setup()
    role = UserRole.ADMIN if is_first else UserRole.USER

    if not is_first:
        valid, msg = invitation_manager.validate_invitation(invitation_code)
        if not valid:
            return RedirectResponse(
                url=f"/auth/register?error={msg}",
                status_code=303
            )

    success, message, user = auth_manager.register(
        username=username,
        password=password,
        nickname=nickname,
        avatar=avatar,
        role=role,
    )

    if not success:
        return RedirectResponse(
            url=f"/auth/register?error={message}",
            status_code=303
        )

    assert user is not None

    if not is_first:
        invitation_manager.use_invitation(invitation_code, username)

    token = auth_manager.create_token(user)
    response = RedirectResponse(url="/courses", status_code=303)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,
        samesite="lax",
    )
    return response


@app.get("/auth/logout")
async def logout():
    response = RedirectResponse(url="/auth/login", status_code=303)
    response.delete_cookie("access_token")
    return response


@app.get("/auth/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request, error: str = "", message: str = ""):
    current_user = get_current_user(request)
    return templates.TemplateResponse(
        "forgot_password.html",
        {
            "request": request,
            "error": error,
            "message": message,
            "current_user": current_user,
        },
    )


@app.post("/auth/forgot-password")
async def forgot_password(
    request: Request,
    username: str = Form(...),
):
    user = auth_manager.get_user(username)
    if not user or not user.email:
        return RedirectResponse(
            url="/auth/forgot-password?message=如果用户存在且有邮箱，重置链接已发送",
            status_code=303
        )

    reset_token = password_reset_manager.create_reset_token(user.id, user.email)

    reset_link = f"{request.url.scheme}://{request.url.netloc}/auth/reset-password?token={reset_token.token}"

    return RedirectResponse(
        url=f"/auth/forgot-password?message=重置链接: {reset_link}",
        status_code=303
    )


@app.get("/auth/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str = "", error: str = ""):
    current_user = get_current_user(request)
    return templates.TemplateResponse(
        "reset_password.html",
        {
            "request": request,
            "token": token,
            "error": error,
            "current_user": current_user,
        },
    )


@app.post("/auth/reset-password")
async def reset_password(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
):
    valid, msg, reset_token = password_reset_manager.validate_token(token)
    if not valid:
        return RedirectResponse(
            url=f"/auth/reset-password?token={token}&error={msg}",
            status_code=303
        )

    if len(new_password) < 8:
        return RedirectResponse(
            url=f"/auth/reset-password?token={token}&error=密码长度必须大于等于8位",
            status_code=303
        )

    user = auth_manager.get_user_by_id(reset_token.user_id)
    if not user:
        return RedirectResponse(
            url=f"/auth/reset-password?token={token}&error=用户不存在",
            status_code=303
        )

    from src.auth import get_password_hash
    user.password_hash = get_password_hash(new_password)
    auth_manager.update_user(user)
    password_reset_manager.use_token(token)

    return RedirectResponse(url="/auth/login?message=密码已重置，请重新登录", status_code=303)


@app.post("/auth/me/profile")
async def update_profile(
    request: Request,
    nickname: str = Form(...),
    avatar: str = Form(...),
    current_user: User = require_auth(),
):
    if avatar not in BUILTIN_AVATARS:
        avatar = current_user.avatar

    current_user.nickname = nickname
    current_user.avatar = avatar
    auth_manager.update_user(current_user)

    return RedirectResponse(url="/settings?message=个人设置已更新", status_code=303)


@app.post("/auth/me/password")
async def update_password(
    request: Request,
    old_password: str = Form(...),
    new_password: str = Form(...),
    current_user: User = require_auth(),
):
    from src.auth import verify_password, get_password_hash

    if not verify_password(old_password, current_user.password_hash):
        return RedirectResponse(url="/settings?error=原密码错误", status_code=303)

    if len(new_password) < 8:
        return RedirectResponse(url="/settings?error=密码长度必须大于等于8位", status_code=303)

    current_user.password_hash = get_password_hash(new_password)
    auth_manager.update_user(current_user)

    return RedirectResponse(url="/auth/login?message=密码已修改，请重新登录", status_code=303)


@app.get("/admin/invitations", response_class=HTMLResponse)
async def admin_invitations_page(request: Request, current_user: User = require_admin()):
    from datetime import datetime
    invitations = invitation_manager.get_all_invitations()
    return templates.TemplateResponse(
        "admin_invitations.html",
        {
            "request": request,
            "invitations": invitations,
            "current_user": current_user,
            "now": datetime.utcnow().isoformat(),
        },
    )


@app.post("/admin/invitations/create")
async def admin_create_invitation(
    days: int = Form(3),
    current_user: User = require_admin(),
):
    invitation = invitation_manager.create_invitation(current_user.username, days)
    return JSONResponse({"status": "created", "code": invitation.code})


@app.delete("/admin/invitations/{code}")
async def admin_delete_invitation(code: str, current_user: User = require_admin()):
    success = invitation_manager.delete_invitation(code)
    if not success:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    return JSONResponse({"status": "deleted"})


@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request, current_user: User = require_admin()):
    users = auth_manager.get_all_users()
    return templates.TemplateResponse(
        "admin_users.html",
        {
            "request": request,
            "users": users,
            "UserRole": UserRole,
            "current_user": current_user,
        },
    )


@app.delete("/admin/users/{username}")
async def admin_delete_user(username: str, current_user: User = require_admin()):
    if username == current_user.username:
        raise HTTPException(status_code=400, detail="不能删除自己")

    success = auth_manager.delete_user(username)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    return JSONResponse({"status": "deleted"})


@app.post("/admin/users/{username}/role")
async def admin_update_user_role(
    username: str,
    role: str = Form(...),
    current_user: User = require_admin(),
):
    if username == current_user.username:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")

    try:
        new_role = UserRole(role)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的角色")

    success = auth_manager.update_user_role(username, new_role)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    return JSONResponse({"status": "updated"})


@app.post("/admin/users/{username}/reset-password")
async def admin_reset_user_password(
    username: str,
    password: str = Form("pwd@12345"),
    current_user: User = require_admin(),
):
    """管理员重置用户密码"""
    if username == current_user.username:
        raise HTTPException(status_code=400, detail="不能重置自己的密码")

    success = auth_manager.reset_user_password(username, password)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    return JSONResponse({"status": "password_reset"})


@app.post("/admin/users/{username}/toggle-status")
async def admin_toggle_user_status(
    username: str,
    current_user: User = require_admin(),
):
    """切换用户启用/禁用状态"""
    if username == current_user.username:
        raise HTTPException(status_code=400, detail="不能禁用自己的账号")

    success = auth_manager.toggle_user_status(username)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    return JSONResponse({"status": "toggled"})


@app.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request, current_user: User = require_auth()):
    return templates.TemplateResponse(
        "tasks.html",
        {
            "request": request,
            "current_user": current_user,
        },
    )


def _parse_form_bool(value: str) -> bool:
    """解析表单布尔值，处理 checkbox hidden field 模式"""
    return value.lower() == "true"


@app.post("/tasks/create")
async def create_task(
    url: str = Form(...),
    headless: str = Form("true"),
    download_images: str = Form("true"),
    download_audio: str = Form("true"),
    download_video: str = Form("true"),
    current_user: User = require_auth(),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只有管理员可以创建任务")

    if not settings_manager.is_configured():
        return RedirectResponse(url="/settings?message=请先配置账号信息", status_code=303)

    task = task_manager.create_task(
        url=url,
        output_dir=settings_manager.default_output_dir,
        headless=_parse_form_bool(headless),
        download_images=_parse_form_bool(download_images),
        download_audio=_parse_form_bool(download_audio),
        download_video=_parse_form_bool(download_video),
    )
    await task_manager.enqueue(task)
    return RedirectResponse(url=f"/tasks/{task.id}", status_code=303)


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: str, current_user: User = require_auth()):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return templates.TemplateResponse(
        "task_detail.html",
        {
            "request": request,
            "task": task,
            "TaskStatus": TaskStatus,
            "current_user": current_user,
        },
    )


@app.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, current_user: User = require_auth()):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只有管理员可以操作任务")
    success = await task_manager.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot cancel task")
    return JSONResponse({"status": "cancelled"})


@app.post("/tasks/{task_id}/pause")
async def pause_task(task_id: str, current_user: User = require_auth()):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只有管理员可以操作任务")
    success = await task_manager.pause_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot pause task")
    return JSONResponse({"status": "paused"})


@app.post("/tasks/{task_id}/resume")
async def resume_task(task_id: str, current_user: User = require_auth()):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只有管理员可以操作任务")
    success = await task_manager.resume_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot resume task")
    return JSONResponse({"status": "resumed"})


@app.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str, current_user: User = require_auth()):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只有管理员可以操作任务")
    success = await task_manager.retry_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot retry task")
    return JSONResponse({"status": "retrying"})


@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str, current_user: User = require_auth()):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只有管理员可以操作任务")
    success = task_manager.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot delete task")
    return JSONResponse({"status": "deleted"})


@app.get("/api/tasks")
async def list_tasks(current_user: User = require_auth()):
    tasks = task_manager.get_all_tasks()
    return [t.to_dict() for t in tasks]


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str, current_user: User = require_auth()):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@app.get("/api/tasks/{task_id}/events")
async def task_events(request: Request, task_id: str, current_user: User = require_auth()):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        queue = task_manager.subscribe_task(task_id)
        try:
            yield {"event": "init", "data": json.dumps(task.to_dict())}

            while True:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield {"event": event.get("type", "update"), "data": json.dumps(event)}

                    if event.get("type") in ("completed", "failed", "cancelled"):
                        break
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
        finally:
            task_manager.unsubscribe_task(task_id, queue)

    return EventSourceResponse(event_generator())


@app.get("/api/events")
async def global_events(request: Request, current_user: User = require_auth()):
    async def event_generator():
        queue = task_manager.subscribe_global()
        try:
            tasks = task_manager.get_all_tasks()
            yield {"event": "init", "data": json.dumps([t.to_dict() for t in tasks])}

            while True:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield {"event": event.get("type", "update"), "data": json.dumps(event)}
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
        finally:
            task_manager.unsubscribe_global(queue)

    return EventSourceResponse(event_generator())


@app.get("/courses", response_class=HTMLResponse)
async def list_courses(request: Request, current_user: User = require_auth()):
    output_dirs = [
        Path("./org_courses"),
    ]

    courses = []
    for output_dir in output_dirs:
        if not output_dir.exists():
            continue

        for course_dir in output_dir.iterdir():
            if not course_dir.is_dir():
                continue
            if course_dir.name.startswith("."):
                continue

            course_info = _parse_course_info(course_dir)
            courses.append(course_info)

    courses.sort(key=lambda c: c.get("updated_at", ""), reverse=True)

    return templates.TemplateResponse(
        "courses.html",
        {
            "request": request,
            "courses": courses,
            "current_user": current_user,
        },
    )


def _parse_course_info(course_dir: Path) -> dict:
    course_info = {
        "name": course_dir.name,
        "path": str(course_dir),
        "title": "",
        "subtitle": "",
        "author_name": "",
        "author_intro": "",
        "cover_url": "",
        "unit": "",
        "is_finished": False,
        "learn_count": 0,
        "keywords": [],
        "status": "unknown",
        "status_label": "未知",
        "completed_at": None,
        "updated_at": "",
        "total_lessons": 0,
        "downloaded_lessons": 0,
        "labels": None,
    }

    name_parts = course_dir.name.split("__", 1)
    if len(name_parts) == 2:
        course_info["title"] = name_parts[1]
    else:
        course_info["title"] = course_dir.name

    progress_file = course_dir / ".progress.json"
    if progress_file.exists():
        try:
            progress_data = json.loads(progress_file.read_text(encoding="utf-8"))
            course_info["total_lessons"] = progress_data.get("total_lessons", 0)
            lessons = progress_data.get("lessons", {})
            course_info["downloaded_lessons"] = len([
                l for l in lessons.values()
                if l.get("content_done")
            ])
            course_info["updated_at"] = progress_data.get("updated_at", "")

            completed_at = progress_data.get("completed_at")
            total = course_info["total_lessons"]
            downloaded = course_info["downloaded_lessons"]

            if completed_at or (total > 0 and downloaded >= total):
                course_info["status"] = "completed"
                course_info["status_label"] = "爬取完成"
                course_info["completed_at"] = completed_at or course_info["updated_at"]
            elif downloaded > 0:
                course_info["status"] = "in_progress"
                course_info["status_label"] = "爬取中"
            else:
                course_info["status"] = "pending"
                course_info["status_label"] = "等待中"
        except Exception:
            pass

    json_info = _parse_column_info_json(course_dir)
    if json_info:
        course_info.update(json_info)
    else:
        intro_file = course_dir / "intro.md"
        if intro_file.exists():
            try:
                intro_content = intro_file.read_text(encoding="utf-8")
                course_info.update(_parse_intro_md(intro_content, course_dir))
            except Exception:
                pass

    # 优先使用本地封面图，替代外链图片
    local_cover_jpg = course_dir / "images" / "[intro]__cover.jpg"
    local_cover_png = course_dir / "images" / "[intro]__cover.png"
    if local_cover_jpg.exists():
        course_info["cover_url"] = f"/course_files/{course_dir.name}/images/[intro]__cover.jpg"
    elif local_cover_png.exists():
        course_info["cover_url"] = f"/course_files/{course_dir.name}/images/[intro]__cover.png"

    labels_info = _parse_labels_json(course_dir)
    if labels_info:
        course_info["labels"] = labels_info

    return course_info


def _parse_labels_json(course_dir: Path) -> dict | None:
    labels_file = course_dir / ".labels.json"
    if not labels_file.exists():
        return None

    try:
        labels_data = json.loads(labels_file.read_text(encoding="utf-8"))
        return {
            "direction_id": labels_data.get("direction_id", "uncategorized"),
            "direction_name": labels_data.get("direction_name", "未分类"),
            "category_ids": labels_data.get("category_ids", []),
            "category_names": labels_data.get("category_names", [])
        }
    except Exception:
        return None


def _parse_column_info_json(course_dir: Path) -> dict | None:
    """解析 .column_info.json 文件获取课程信息
    
    优先从 JSON 获取课程元数据，支持以下字段：
    - title: 课程标题
    - subtitle: 课程副标题
    - unit: 课程讲数
    - is_finish: 是否已完结
    - author.name: 讲师名
    - author.intro: 讲师简介
    - author.brief: 讲师详细介绍
    - seo.keywords: 关键词列表
    - cover.square: 课程封面 URL
    - extra.modules: 课程模块（包含"你将获得"、"课程介绍"等）
    """
    column_info_file = course_dir / ".column_info.json"
    if not column_info_file.exists():
        return None
    
    try:
        column_data = json.loads(column_info_file.read_text(encoding="utf-8"))
        data = column_data.get("data", {})
        
        info = {}
        
        # 基本信息
        if "title" in data:
            info["title"] = data["title"]
        
        if "subtitle" in data:
            info["subtitle"] = data["subtitle"]
        
        if "unit" in data:
            info["unit"] = data["unit"]
        
        if "is_finish" in data:
            info["is_finished"] = data["is_finish"]
        
        # 讲师信息
        author = data.get("author", {})
        if "name" in author:
            info["author_name"] = author["name"]
        
        if "intro" in author:
            info["author_intro"] = author["intro"]
        elif "brief" in author:
            # 如果没有 intro，使用 brief（纯文本版本）
            info["author_intro"] = author["brief"].strip()
        
        # 关键词
        seo = data.get("seo", {})
        if "keywords" in seo:
            info["keywords"] = seo["keywords"]
        
        # 封面 URL
        cover = data.get("cover", {})
        if "square" in cover:
            info["cover_url"] = cover["square"]
        
        return info if info else None
    except Exception:
        return None


def _parse_intro_md(content: str, course_dir: Path) -> dict:
    import re
    
    info = {}
    
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if title_match:
        info["title"] = title_match.group(1).strip()
    
    subtitle_match = re.search(r"^\*\*(.+)\*\*\s*$", content, re.MULTILINE)
    if subtitle_match:
        info["subtitle"] = subtitle_match.group(1).strip()
    
    unit_match = re.search(r"\*\*总课程数\*\*:\s*(.+)", content)
    if unit_match:
        info["unit"] = unit_match.group(1).strip()
    
    if "已完结" in content:
        info["is_finished"] = True
    
    learn_count_match = re.search(r"\*\*学习人数\*\*:\s*(\d+)", content)
    if learn_count_match:
        info["learn_count"] = int(learn_count_match.group(1))
    
    keywords_match = re.search(r"##\s*关键词\s*\n\n(.+)", content)
    if keywords_match:
        info["keywords"] = [k.strip() for k in keywords_match.group(1).split(",")]
    
    author_section_match = re.search(
        r"##\s*讲师介绍\s*\n\n###\s*(.+)\s*\n\n\*\*(.+)\*\*", 
        content
    )
    if author_section_match:
        info["author_name"] = author_section_match.group(1).strip()
        info["author_intro"] = author_section_match.group(2).strip()
    
    cover_match = re.search(r"!\[课程封面\]\((.+)\)", content)
    if cover_match:
        cover_path = cover_match.group(1).strip()
        full_cover_path = course_dir / cover_path
        if full_cover_path.exists():
            info["cover_url"] = f"/course_files/{course_dir.name}/{cover_path}"
    
    return info


@app.get("/api/courses")
async def list_courses_api(
    current_user: User = require_auth(),
    search: str = "",
    status: str = "",
    keyword: str = "",
    direction: str = "",
    category: str = ""
):
    """获取课程列表API，支持搜索和筛选"""
    output_dirs = [Path("./org_courses")]

    courses = []
    for output_dir in output_dirs:
        if not output_dir.exists():
            continue

        for course_dir in output_dir.iterdir():
            if not course_dir.is_dir():
                continue
            if course_dir.name.startswith("."):
                continue

            course_info = _parse_course_info(course_dir)
            courses.append(course_info)

    # 搜索过滤
    if search:
        search_lower = search.lower()
        courses = [
            c for c in courses
            if search_lower in c.get("title", "").lower()
            or search_lower in c.get("author_name", "").lower()
            or search_lower in c.get("subtitle", "").lower()
        ]

    # 状态过滤
    if status:
        courses = [c for c in courses if c.get("status") == status]

    # 关键词过滤
    if keyword:
        courses = [
            c for c in courses
            if keyword in c.get("keywords", [])
        ]

    # 方向过滤
    if direction:
        courses = [
            c for c in courses
            if c.get("labels") and c["labels"].get("direction_id") == direction
        ]

    # 分类过滤
    if category:
        courses = [
            c for c in courses
            if c.get("labels") and category in c["labels"].get("category_ids", [])
        ]

    # 获取所有分类（关键词）
    all_keywords = set()
    for course in courses:
        all_keywords.update(course.get("keywords", []))

    courses.sort(key=lambda c: c.get("updated_at", ""), reverse=True)

    # 获取所有方向列表
    directions = label_manager.get_all_directions()

    return {
        "courses": courses,
        "keywords": sorted(list(all_keywords)),
        "directions": directions,
        "total": len(courses)
    }


@app.get("/api/labels/categories")
async def get_categories_by_direction_api(
    direction: str,
    current_user: User = require_auth()
):
    """获取指定方向下的分类列表"""
    categories = label_manager.get_categories_by_direction(direction)
    return {"categories": categories}


@app.get("/courses/{course_path:path}", response_class=HTMLResponse)
async def course_detail(request: Request, course_path: str, current_user: User = require_auth()):
    # Ensure course_path includes org_courses/ prefix
    if not course_path.startswith("org_courses/"):
        course_path = f"org_courses/{course_path}"
    course_dir = Path(course_path)
    if not course_dir.exists():
        raise HTTPException(status_code=404, detail="Course not found")

    # 从课程目录名提取课程ID
    course_id = course_dir.name

    # 加载学习进度
    learning_mgr = LearningProgressManager(course_id, course_dir)
    learning_mgr.load()
    completed_lessons = learning_mgr.get_user_completed_lessons(current_user.id)

    chapters = []
    for chapter_dir in sorted(course_dir.iterdir()):
        if not chapter_dir.is_dir():
            continue
        if chapter_dir.name.startswith(".") or chapter_dir.name in ("images", "audio", "video"):
            continue

        lessons = []
        for md_file in sorted(chapter_dir.glob("*.md")):
            lesson_path = str(md_file)
            # 标准化：移除 org_courses/ 前缀用于比较
            normalized_lesson_path = lesson_path.replace("org_courses/", "")
            lessons.append(
                {
                    "name": md_file.stem,
                    "path": lesson_path,
                    "url": f"/course_lesson_preview/{lesson_path}",
                    "completed": normalized_lesson_path in completed_lessons
                }
            )

        chapters.append(
            {
                "name": chapter_dir.name,
                "lessons": lessons,
            }
        )

    intro_file = course_dir / "intro.md"
    intro_content = None
    if intro_file.exists():
        intro_content = intro_file.read_text()

    # 转换为相对路径用于模板
    # 确保从课程目录名开始，去掉 org_courses/ 前缀
    # 因为静态文件挂载点 /course_files 已经指向 org_courses
    if course_dir.name.startswith('['):
        # 如果是课程目录（以 [ 开头），直接使用目录名
        course_path_for_template = course_dir.name
    else:
        # 否则，尝试从路径中提取课程目录名
        parts = course_dir.parts
        if 'org_courses' in parts:
            org_idx = parts.index('org_courses')
            if org_idx + 1 < len(parts):
                course_path_for_template = '/'.join(parts[org_idx + 1:])
            else:
                course_path_for_template = course_dir.name
        else:
            course_path_for_template = course_dir.name

    display_name = course_dir.name.split('__')[-1]

    return templates.TemplateResponse(
        "course_detail.html",
        {
            "request": request,
            "course_name": display_name,
            "course_path": course_path_for_template,
            "chapters": chapters,
            "intro_content": intro_content,
            "current_user": current_user,
        },
    )


@app.get("/api/courses/{course_path:path}/catalog")
async def get_course_catalog(course_path: str, current_user: User = require_auth()):
    """获取课程目录数据API，用于学习页侧边栏"""
    # 如果 course_path 不包含 org_courses，添加前缀
    if not course_path.startswith("org_courses/"):
        course_path = f"org_courses/{course_path}"
    course_dir = Path(course_path)
    if not course_dir.exists():
        raise HTTPException(status_code=404, detail="Course not found")

    # 从课程目录名提取课程ID
    course_id = course_dir.name

    chapters = []
    all_lessons = []

    # 加载学习进度
    learning_mgr = LearningProgressManager(course_id, course_dir)
    learning_mgr.load()
    completed_lessons = learning_mgr.get_user_completed_lessons(current_user.id)

    for chapter_dir in sorted(course_dir.iterdir()):
        if not chapter_dir.is_dir():
            continue
        if chapter_dir.name.startswith(".") or chapter_dir.name in ("images", "audio", "video"):
            continue

        lessons = []
        for md_file in sorted(chapter_dir.glob("*.md")):
            lesson_path = str(md_file)
            lesson_data = {
                "name": md_file.stem,
                "path": lesson_path,
                "url": f"/course_lesson_preview/{lesson_path}",
                "completed": lesson_path in completed_lessons
            }
            lessons.append(lesson_data)
            all_lessons.append(lesson_data)

        chapters.append({
            "name": chapter_dir.name,
            "lessons": lessons
        })

    return {
        "chapters": chapters,
        "all_lessons": all_lessons
    }


@app.get("/api/courses/{course_path:path}/learning-progress")
async def get_learning_progress(course_path: str, current_user: User = require_auth()):
    """获取用户学习进度"""
    # 如果 course_path 不包含 org_courses，添加前缀
    if not course_path.startswith("org_courses/"):
        course_path = f"org_courses/{course_path}"
    course_dir = Path(course_path)
    if not course_dir.exists():
        raise HTTPException(status_code=404, detail="Course not found")

    # 从课程目录名提取课程ID
    course_id = str(course_dir.name)

    learning_mgr = LearningProgressManager(course_id, course_dir)
    learning_mgr.load()
    completed_lessons = learning_mgr.get_user_completed_lessons(current_user.id)

    return {
        "completed_lessons": completed_lessons
    }


class MarkLessonCompletedRequest(BaseModel):
    lesson_path: str
    completion_type: str = "scroll"  # "scroll" | "media" | "bottom"


@app.post("/api/courses/{course_path:path}/learning-progress")
async def mark_lesson_completed(
    course_path: str,
    request: MarkLessonCompletedRequest,
    current_user: User = require_auth()
):
    """标记小节为已完成"""
    # 如果 course_path 不包含 org_courses，添加前缀
    if not course_path.startswith("org_courses/"):
        course_path = f"org_courses/{course_path}"
    course_dir = Path(course_path)
    if not course_dir.exists():
        raise HTTPException(status_code=404, detail="Course not found")

    # 从课程目录名提取课程ID
    course_id = str(course_dir.name)

    learning_mgr = LearningProgressManager(course_id, course_dir)
    learning_mgr.load()

    # 使用 lesson_path 作为 lesson_id（因为课程内小节路径是唯一的）
    # 需要解码 URL 编码的路径
    lesson_id = unquote(request.lesson_path)
    learning_mgr.mark_lesson_completed(
        user_id=current_user.id,
        username=current_user.username,
        lesson_id=lesson_id,
        completion_type=request.completion_type
    )

    return {"status": "marked", "lesson_id": lesson_id}


@app.get("/course_lesson_preview/{file_path:path}", response_class=HTMLResponse)
async def preview_markdown(request: Request, file_path: str, current_user: User = require_auth()):
    md_file = Path(file_path)
    if not md_file.exists() or not md_file.suffix == ".md":
        raise HTTPException(status_code=404, detail="File not found")

    content = md_file.read_text()

    # 获取课程目录
    course_dir = md_file.parent.parent
    # 转换为相对路径用于模板
    # 确保从课程目录名开始，去掉 org_courses/ 前缀
    # 因为静态文件挂载点 /course_files 已经指向 org_courses
    if course_dir.name.startswith('['):
        # 如果是课程目录（以 [ 开头），直接使用目录名
        course_path_for_template = course_dir.name
    else:
               # 否则，尝试从路径中提取课程目录名
        parts = course_dir.parts
        if 'org_courses' in parts:
            org_idx = parts.index('org_courses')
            if org_idx + 1 < len(parts):
                course_path_for_template = '/'.join(parts[org_idx + 1:])
            else:
                course_path_for_template = course_dir.name
        else:
            course_path_for_template = course_dir.name

    # 从课程目录名提取课程ID
    course_id = str(course_dir.name)

    # 加载学习进度
    learning_mgr = LearningProgressManager(course_id, course_dir)
    learning_mgr.load()
    completed_lessons = learning_mgr.get_user_completed_lessons(current_user.id)

    chapters = []
    all_lessons = []
    current_lesson_path = str(md_file)

    for chapter_dir in sorted(course_dir.iterdir()):
        if not chapter_dir.is_dir():
            continue
        if chapter_dir.name.startswith(".") or chapter_dir.name in ("images", "audio", "video"):
            continue

        lessons = []
        for md_file_chapter in sorted(chapter_dir.glob("*.md")):
            lesson_path = str(md_file_chapter)
            # 标准化：移除 org_courses/ 前缀用于比较
            normalized_lesson_path = lesson_path.replace("org_courses/", "")
            lesson_data = {
                "name": md_file_chapter.stem,
                "path": lesson_path,
                "url": f"/course_lesson_preview/{lesson_path}",
                "is_current": lesson_path == current_lesson_path,
                "completed": normalized_lesson_path in completed_lessons
            }
            lessons.append(lesson_data)
            all_lessons.append(lesson_data)

        chapters.append({
            "name": chapter_dir.name,
            "lessons": lessons
        })
    display_name = course_dir.name.split('__')[-1]

    return templates.TemplateResponse(
        "course_lesson_preview.html",
        {
            "request": request,
            "file_name": md_file.name,
            "content": content,
            "course_name": display_name,
            "course_path": course_path_for_template,
            "chapters": chapters,
            "all_lessons": all_lessons,
            "current_user": current_user,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, current_user: User = require_auth()):
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "current_user": current_user,
            "avatars": BUILTIN_AVATARS,
        },
    )


@app.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings_page(request: Request, current_user: User = require_admin()):
    return templates.TemplateResponse(
        "admin_settings.html",
        {
            "request": request,
            "current_user": current_user,
        },
    )


class SettingsModel(BaseModel):
    phone: str = ""
    password: str = ""
    default_output_dir: str = "./org_courses"
    delay_min: float = 1.0
    delay_max: float = 3.0
    headless: bool = True
    download_images: bool = True
    download_audio: bool = True
    download_video: bool = True
    compress_media: bool = True
    compress_video_crf: int = 28
    compress_video_preset: str = "medium"
    compress_video_max_height: int = 720
    compress_audio_bitrate: str = "64k"
    compress_keep_original: bool = False


@app.get("/api/settings")
async def get_settings(current_user: User = require_admin()):
    return settings_manager.settings.to_dict()


@app.post("/api/settings")
async def sync_settings(settings: SettingsModel, current_user: User = require_admin()):
    settings_manager.update_from_dict(settings.model_dump())
    return {"status": "ok"}


def run_server(host: str = "0.0.0.0", port: int = 8000):
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()

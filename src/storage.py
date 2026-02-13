"""
本地存储模块 - 使用 appdirs 管理配置和任务持久化

存储位置：
- macOS: ~/Library/Application Support/geekbang-crawler/
- Windows: C:\\Users\\<user>\\AppData\\Local\\geekbang-crawler\\
- Linux: ~/.local/share/geekbang-crawler/
"""

import json
from pathlib import Path
from typing import Any

import appdirs


APP_NAME = "geekbang-crawler"
APP_AUTHOR = "geekbang"

SETTINGS_FILE = "settings.json"
TASKS_FILE = "tasks.json"
LEARNING_RECORDS_DIR = "learning_records"


def get_data_dir() -> Path:
    """获取应用数据目录，不存在则创建"""
    data_dir = Path(appdirs.user_data_dir(APP_NAME, APP_AUTHOR))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_settings_path() -> Path:
    """获取设置文件路径"""
    return get_data_dir() / SETTINGS_FILE


def get_tasks_path() -> Path:
    """获取任务文件路径"""
    return get_data_dir() / TASKS_FILE


def get_learning_records_dir() -> Path:
    """获取学习记录目录，不存在则创建"""
    records_dir = get_data_dir() / LEARNING_RECORDS_DIR
    records_dir.mkdir(parents=True, exist_ok=True)
    return records_dir


def get_learning_record_path(course_id: str) -> Path:
    """获取指定课程的学习记录文件路径"""
    return get_learning_records_dir() / f"{course_id}.json"


def load_json(file_path: Path) -> dict[str, Any] | list[Any]:
    """从 JSON 文件加载数据"""
    if not file_path.exists():
        return {}
    
    try:
        content = file_path.read_text(encoding="utf-8")
        return json.loads(content)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Failed to load {file_path}: {e}")
        return {}


def save_json(file_path: Path, data: dict[str, Any] | list[Any]) -> bool:
    """保存数据到 JSON 文件"""
    try:
        content = json.dumps(data, ensure_ascii=False, indent=2)
        file_path.write_text(content, encoding="utf-8")
        return True
    except OSError as e:
        print(f"Warning: Failed to save {file_path}: {e}")
        return False


def load_settings() -> dict[str, Any]:
    """加载设置"""
    return load_json(get_settings_path())  # type: ignore


def save_settings(settings: dict[str, Any]) -> bool:
    """保存设置"""
    return save_json(get_settings_path(), settings)


def load_tasks() -> list[dict[str, Any]]:
    """加载任务列表"""
    data = load_json(get_tasks_path())
    if isinstance(data, list):
        return data
    return data.get("tasks", [])


def save_tasks(tasks: list[dict[str, Any]]) -> bool:
    """保存任务列表"""
    return save_json(get_tasks_path(), tasks)

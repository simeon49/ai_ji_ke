"""
设置管理模块 - 使用本地文件持久化（appdirs）
"""

from dataclasses import dataclass, asdict

from src.storage import load_settings, save_settings


DEFAULT_OUTPUT_DIR = "./org_courses"


@dataclass
class AppSettings:
    phone: str = ""
    password: str = ""

    default_output_dir: str = DEFAULT_OUTPUT_DIR

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

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        return cls(
            phone=data.get("phone", ""),
            password=data.get("password", ""),
            default_output_dir=data.get("default_output_dir", DEFAULT_OUTPUT_DIR),
            delay_min=float(data.get("delay_min", 1.0)),
            delay_max=float(data.get("delay_max", 3.0)),
            headless=data.get("headless", True),
            download_images=data.get("download_images", True),
            download_audio=data.get("download_audio", True),
            download_video=data.get("download_video", True),
            compress_media=data.get("compress_media", True),
            compress_video_crf=int(data.get("compress_video_crf", 28)),
            compress_video_preset=data.get("compress_video_preset", "medium"),
            compress_video_max_height=int(data.get("compress_video_max_height", 720)),
            compress_audio_bitrate=data.get("compress_audio_bitrate", "64k"),
            compress_keep_original=data.get("compress_keep_original", False),
        )

    def is_configured(self) -> bool:
        return bool(self.phone and self.password)


class SettingsManager:
    """设置管理器，使用本地文件持久化"""
    _instance: "SettingsManager | None" = None
    _settings: AppSettings

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        stored_data = load_settings()
        if stored_data:
            self._settings = AppSettings.from_dict(stored_data)
        else:
            self._settings = AppSettings()
        
        self._initialized = True

    @property
    def settings(self) -> AppSettings:
        return self._settings

    @property
    def default_output_dir(self) -> str:
        return self._settings.default_output_dir

    @default_output_dir.setter
    def default_output_dir(self, value: str):
        self._settings.default_output_dir = value
        self._save()

    def _save(self):
        """保存设置到本地文件"""
        save_settings(self._settings.to_dict())

    def update(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self._settings, key):
                setattr(self._settings, key, value)
        self._save()

    def update_from_dict(self, data: dict):
        """从字典更新设置"""
        self._settings = AppSettings.from_dict(data)
        self._save()

    def reset(self):
        self._settings = AppSettings()
        self._save()

    def is_configured(self) -> bool:
        return self._settings.is_configured()
    
    def reload(self):
        """从文件重新加载设置"""
        stored_data = load_settings()
        if stored_data:
            self._settings = AppSettings.from_dict(stored_data)
        else:
            self._settings = AppSettings()


settings_manager = SettingsManager()

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from src.settings import settings_manager

if TYPE_CHECKING:
    from src.compressor import CompressionConfig


@dataclass
class Config:
    phone: str
    password: str
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    delay_min: float = 1.0
    delay_max: float = 3.0
    headless: bool = False
    download_images: bool = True
    download_audio: bool = True
    download_video: bool = True
    
    compress_media: bool = True
    compress_video_crf: int = 28
    compress_video_preset: str = "medium"
    compress_video_max_height: int = 720
    compress_audio_bitrate: str = "64k"
    compress_keep_original: bool = False
    
    def to_compression_config(self) -> "CompressionConfig":
        """创建压缩配置对象"""
        from src.compressor import CompressionConfig
        return CompressionConfig(
            enabled=self.compress_media,
            video_crf=self.compress_video_crf,
            video_preset=self.compress_video_preset,
            video_max_height=self.compress_video_max_height,
            audio_bitrate=self.compress_audio_bitrate,
            keep_original=self.compress_keep_original,
        )
    
    @classmethod
    def from_settings(cls) -> "Config":
        s = settings_manager.settings
        
        if not s.phone or not s.password:
            raise ValueError("请先在设置页面配置手机号和密码")
        
        return cls(
            phone=s.phone,
            password=s.password,
            output_dir=Path(s.default_output_dir),
            delay_min=s.delay_min,
            delay_max=s.delay_max,
            headless=s.headless,
            download_images=s.download_images,
            download_audio=s.download_audio,
            download_video=s.download_video,
            compress_media=s.compress_media,
            compress_video_crf=s.compress_video_crf,
            compress_video_preset=s.compress_video_preset,
            compress_video_max_height=s.compress_video_max_height,
            compress_audio_bitrate=s.compress_audio_bitrate,
            compress_keep_original=s.compress_keep_original,
        )

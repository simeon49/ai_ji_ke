"""
音视频压缩模块

使用 FFmpeg 对教学视频和音频进行压缩：
- 视频：H.264 编码，CRF 质量控制，可选分辨率调整
- 音频：AAC/MP3 编码，合适的比特率

FFmpeg 必须预先安装在系统上。
"""

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

console = Console()


@dataclass
class CompressionConfig:
    """压缩配置"""
    enabled: bool = True
    
    # 视频设置
    video_crf: int = 28  # 质量因子，18-28 合理，越大文件越小
    video_preset: str = "medium"  # 编码速度：ultrafast, fast, medium, slow
    video_max_height: int = 720  # 最大高度，0 表示不调整
    
    # 音频设置
    audio_bitrate: str = "64k"  # 教学音频 64-128k 足够
    
    # 保留原文件
    keep_original: bool = False


def _check_ffmpeg() -> bool:
    """检查 FFmpeg 是否可用"""
    return shutil.which("ffmpeg") is not None


def _check_ffprobe() -> bool:
    """检查 ffprobe 是否可用"""
    return shutil.which("ffprobe") is not None


async def get_media_duration(file_path: Path) -> float | None:
    """获取媒体文件时长（秒）"""
    if not _check_ffprobe():
        return None
    
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0 and stdout:
            return float(stdout.decode().strip())
    except (ValueError, OSError):
        pass
    return None


async def get_video_resolution(file_path: Path) -> tuple[int, int] | None:
    """获取视频分辨率"""
    if not _check_ffprobe():
        return None
    
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0 and stdout:
            parts = stdout.decode().strip().split(",")
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
    except (ValueError, OSError):
        pass
    return None


async def compress_video(
    input_path: Path,
    config: CompressionConfig,
    output_path: Path | None = None,
) -> Path | None:
    """
    压缩视频文件
    
    返回压缩后的文件路径，失败返回 None
    """
    if not _check_ffmpeg():
        console.print("[yellow]FFmpeg 未安装，跳过视频压缩[/yellow]")
        return input_path
    
    if not input_path.exists():
        return None
    
    if output_path is None:
        output_path = input_path.with_suffix(".compressed.mp4")
    
    temp_output = output_path.with_suffix(".tmp.mp4")
    
    # 构建 FFmpeg 命令
    cmd = [
        "ffmpeg",
        "-i", str(input_path),
        "-c:v", "libx264",
        "-crf", str(config.video_crf),
        "-preset", config.video_preset,
        "-c:a", "aac",
        "-b:a", config.audio_bitrate,
        "-movflags", "+faststart",  # Web 优化
        "-y",  # 覆盖输出
    ]
    
    # 检查是否需要调整分辨率
    if config.video_max_height > 0:
        resolution = await get_video_resolution(input_path)
        if resolution and resolution[1] > config.video_max_height:
            # 按比例缩放，高度为 max_height，宽度自动（保持偶数）
            cmd.extend(["-vf", f"scale=-2:{config.video_max_height}"])
    
    cmd.append(str(temp_output))
    
    try:
        original_size = input_path.stat().st_size
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]压缩视频...[/cyan]"),
            BarColumn(),
            TextColumn("{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("", total=None)
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            _, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                console.print(f"[red]视频压缩失败: {stderr.decode()[:200]}[/red]")
                if temp_output.exists():
                    temp_output.unlink()
                return input_path
        
        # 压缩成功
        if temp_output.exists():
            new_size = temp_output.stat().st_size
            ratio = (1 - new_size / original_size) * 100 if original_size > 0 else 0
            
            # 只有压缩有效果才替换
            if new_size < original_size:
                if config.keep_original:
                    # 保留原文件，重命名压缩后的文件
                    final_output = input_path.with_stem(input_path.stem + "_compressed")
                    temp_output.rename(final_output)
                    console.print(f"[green]视频压缩完成: {_format_size(original_size)} → {_format_size(new_size)} (-{ratio:.1f}%)[/green]")
                    return final_output
                else:
                    # 替换原文件
                    temp_output.rename(input_path)
                    console.print(f"[green]视频压缩完成: {_format_size(original_size)} → {_format_size(new_size)} (-{ratio:.1f}%)[/green]")
                    return input_path
            else:
                console.print(f"[yellow]压缩后文件更大，保留原文件[/yellow]")
                temp_output.unlink()
                return input_path
    
    except Exception as e:
        console.print(f"[red]视频压缩出错: {e}[/red]")
        if temp_output.exists():
            temp_output.unlink()
        return input_path
    
    return input_path


async def compress_audio(
    input_path: Path,
    config: CompressionConfig,
    output_path: Path | None = None,
) -> Path | None:
    """
    压缩音频文件
    
    返回压缩后的文件路径，失败返回 None
    """
    if not _check_ffmpeg():
        console.print("[yellow]FFmpeg 未安装，跳过音频压缩[/yellow]")
        return input_path
    
    if not input_path.exists():
        return None
    
    if output_path is None:
        output_path = input_path.with_suffix(".compressed.mp3")
    
    temp_output = output_path.with_suffix(".tmp.mp3")
    
    cmd = [
        "ffmpeg",
        "-i", str(input_path),
        "-c:a", "libmp3lame",
        "-b:a", config.audio_bitrate,
        "-y",
        str(temp_output),
    ]
    
    try:
        original_size = input_path.stat().st_size
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]压缩音频...[/cyan]"),
            console=console,
        ) as progress:
            progress.add_task("", total=None)
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            _, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                console.print(f"[red]音频压缩失败: {stderr.decode()[:200]}[/red]")
                if temp_output.exists():
                    temp_output.unlink()
                return input_path
        
        if temp_output.exists():
            new_size = temp_output.stat().st_size
            ratio = (1 - new_size / original_size) * 100 if original_size > 0 else 0
            
            if new_size < original_size:
                if config.keep_original:
                    final_output = input_path.with_stem(input_path.stem + "_compressed")
                    temp_output.rename(final_output)
                    console.print(f"[green]音频压缩完成: {_format_size(original_size)} → {_format_size(new_size)} (-{ratio:.1f}%)[/green]")
                    return final_output
                else:
                    # 替换原文件（可能扩展名变了）
                    final_path = input_path.with_suffix(".mp3")
                    temp_output.rename(final_path)
                    if final_path != input_path and input_path.exists():
                        input_path.unlink()
                    console.print(f"[green]音频压缩完成: {_format_size(original_size)} → {_format_size(new_size)} (-{ratio:.1f}%)[/green]")
                    return final_path
            else:
                console.print(f"[yellow]压缩后文件更大，保留原文件[/yellow]")
                temp_output.unlink()
                return input_path
    
    except Exception as e:
        console.print(f"[red]音频压缩出错: {e}[/red]")
        if temp_output.exists():
            temp_output.unlink()
        return input_path
    
    return input_path


def _format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


class MediaCompressor:
    """媒体压缩器"""
    
    def __init__(self, config: CompressionConfig | None = None):
        self.config = config or CompressionConfig()
        self._ffmpeg_available: bool | None = None
    
    def is_available(self) -> bool:
        """检查 FFmpeg 是否可用"""
        if self._ffmpeg_available is None:
            self._ffmpeg_available = _check_ffmpeg()
            if not self._ffmpeg_available:
                console.print("[yellow]FFmpeg 未安装，压缩功能不可用[/yellow]")
                console.print("[dim]安装方法: brew install ffmpeg (macOS) / apt install ffmpeg (Linux)[/dim]")
        return self._ffmpeg_available
    
    async def compress_video(self, input_path: Path) -> Path | None:
        """压缩视频"""
        if not self.config.enabled or not self.is_available():
            return input_path
        return await compress_video(input_path, self.config)
    
    async def compress_audio(self, input_path: Path) -> Path | None:
        """压缩音频"""
        if not self.config.enabled or not self.is_available():
            return input_path
        return await compress_audio(input_path, self.config)

"""
公共工具函数模块

整合项目中重复使用的工具函数，避免代码冗余。
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models import Course, Chapter


def sanitize_name(name: str, max_length: int = 100) -> str:
    """
    清理文件/目录名，移除非法字符
    
    Args:
        name: 原始名称
        max_length: 最大长度限制
    
    Returns:
        清理后的安全名称
    """
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = re.sub(r'\s+', '_', name)
    return name.strip('._')[:max_length]


def build_course_dir_name(course: "Course") -> str:
    """
    构建课程目录名
    
    格式: [课程ID]__课程名
    """
    return f"[{course.id}]__{sanitize_name(course.title)}"


def build_chapter_dir_name(chapter: "Chapter") -> str:
    """
    构建章节目录名
    
    格式: 序号__章节名
    """
    return f"{chapter.order:02d}__{sanitize_name(chapter.title)}"


async def download_lesson(
    lesson,
    content,
    downloader,
    md_generator,
    compressor,
    config,
    chapter_dir: Path,
    course_dir: Path,
    images_dir: Path,
    audio_dir: Path,
    video_dir: Path,
) -> dict:
    """
    下载单个课程的核心逻辑
    
    Args:
        lesson: 课程对象
        content: 已解析的课程内容 (LessonContent)
        downloader: 下载器实例
        md_generator: Markdown 生成器实例
        compressor: 媒体压缩器实例
        config: 配置对象
        chapter_dir: 章节目录
        course_dir: 课程目录
        images_dir: 图片目录
        audio_dir: 音频目录
        video_dir: 视频目录
    
    Returns:
        包含下载结果的字典
    """
    lesson_name = sanitize_name(lesson.title)
    
    # 下载图片
    image_mapping = {}
    if config.download_images and content.images:
        image_mapping = await downloader.download_images(
            content.images, images_dir, prefix=lesson_name
        )
    
    # 下载音频
    audio_path = None
    if config.download_audio and content.audio_url:
        audio_dir.mkdir(exist_ok=True)
        audio_path = await downloader.download_audio(
            content.audio_url, audio_dir, lesson_name
        )
        if audio_path and config.compress_media:
            audio_path = await compressor.compress_audio(audio_path)
    
    # 下载视频
    video_path = None
    if config.download_video and content.video_url:
        video_dir.mkdir(exist_ok=True)
        video_path = await downloader.download_video(
            content.video_url, video_dir, lesson_name
        )
        if video_path and config.compress_media:
            video_path = await compressor.compress_video(video_path)
    
    # 生成 Markdown
    md_generator.generate(
        lesson=lesson,
        content=content,
        chapter_dir=chapter_dir,
        course_dir=course_dir,
        image_mapping=image_mapping,
        audio_path=audio_path,
        video_path=video_path,
    )
    
    # 判断媒体下载状态
    # images_done: 配置不下载 或 (配置下载且无图片) 或 (配置下载且有图片且全部成功)
    images_done = (
        not config.download_images or 
        not content.images or 
        len(image_mapping) == len(content.images)
    )
    # audio_done: 配置不下载 或 无音频 或 下载成功
    audio_done = (
        not config.download_audio or 
        not content.audio_url or 
        audio_path is not None
    )
    # video_done: 配置不下载 或 无视频 或 下载成功
    video_done = (
        not config.download_video or 
        not content.video_url or 
        video_path is not None
    )
    
    return {
        "image_mapping": image_mapping,
        "audio_path": audio_path,
        "video_path": video_path,
        "images_done": images_done,
        "audio_done": audio_done,
        "video_done": video_done,
    }

from pathlib import Path

from src.config import Config
from src.browser import BrowserManager
from src.parser import CourseParser
from src.downloader import Downloader
from src.markdown import MarkdownGenerator
from src.progress import ProgressManager
from src.compressor import MediaCompressor
from src.task_manager import CrawlTask, TaskManager, TaskStatus
from src.utils import sanitize_name, build_course_dir_name, build_chapter_dir_name, download_lesson


class TaskCancelled(Exception):
    pass


class TaskPaused(Exception):
    pass


async def run_crawl_task(task: CrawlTask, manager: TaskManager):
    config = Config.from_settings()
    config.output_dir = Path(task.output_dir)
    config.headless = task.headless
    config.download_images = task.download_images
    config.download_audio = task.download_audio
    config.download_video = task.download_video

    async def check_task_state():
        if manager.is_cancelled(task.id):
            raise TaskCancelled()
        task_obj = manager.get_task(task.id)
        if task_obj and task_obj.status == TaskStatus.PAUSED:
            raise TaskPaused()

    await manager.add_task_log(task.id, f"Starting crawl for: {task.url}")
    await manager.add_task_log(task.id, f"Output directory: {config.output_dir}")

    compressor = MediaCompressor(config.to_compression_config())

    async with BrowserManager(config) as browser:
        if not await browser.login():
            raise RuntimeError("登录失败，请检查账号密码")
        
        await manager.add_task_log(task.id, "登录成功")
        
        parser = CourseParser(browser)
        downloader = Downloader(config.output_dir)
        md_generator = MarkdownGenerator(config.output_dir)
        
        await manager.add_task_log(task.id, "Parsing course structure...")
        course = await parser.parse_course(task.url)
        
        await manager.set_task_course_info(task.id, course.id, course.title)
        await manager.add_task_log(task.id, f"Course: {course.title} by {course.author}")
        
        course_dir_name = build_course_dir_name(course)
        
        # 检查 output_dir 是否已经是课程目录（恢复任务时）
        if config.output_dir.name == course_dir_name:
            course_dir = config.output_dir
        else:
            course_dir = config.output_dir / course_dir_name
        
        course_dir.mkdir(parents=True, exist_ok=True)
        task.output_dir = str(course_dir)
        
        # 保存原始 column_info API 数据
        if course.raw_data:
            import json
            column_info_file = course_dir / ".column_info.json"
            with open(column_info_file, "w", encoding="utf-8") as f:
                json.dump(course.raw_data, f, ensure_ascii=False, indent=2)
            await manager.add_task_log(task.id, f"Saved column info to {column_info_file.name}")
        
        progress_mgr = ProgressManager(course_dir)
        progress_mgr.load(course.id, course.title)
        
        images_dir = course_dir / "images"
        audio_dir = course_dir / "audio"
        video_dir = course_dir / "video"
        images_dir.mkdir(exist_ok=True)
        
        total_lessons = len(course.all_lessons)
        progress_mgr.set_total_lessons(total_lessons)
        await manager.update_task_progress(task.id, current=0, total=total_lessons)
        await manager.add_task_log(task.id, f"Found {len(course.chapters)} chapters, {total_lessons} lessons")
        
        if course.intro:
            await manager.add_task_log(task.id, "Generating course intro...")
            cover_path = None
            if config.download_images and course.intro.cover_url:
                cover_path = await downloader.download_file(
                    course.intro.cover_url,
                    images_dir,
                    filename="[intro]__cover",
                    show_progress=False,
                )
            await md_generator.generate_intro(
                course.intro,
                course_dir,
                cover_path,
                images_dir=images_dir if config.download_images else None,
                downloader=downloader if config.download_images else None,
            )
        
        lesson_count = 0
        
        for chapter in course.chapters:
            await check_task_state()
            
            chapter_dir_name = build_chapter_dir_name(chapter)
            chapter_dir = course_dir / chapter_dir_name
            chapter_dir.mkdir(parents=True, exist_ok=True)
            
            await manager.add_task_log(task.id, f"Chapter: {chapter.title}")
            
            for lesson in chapter.lessons:
                await check_task_state()
                
                lesson_count += 1
                await manager.update_task_progress(
                    task.id,
                    current=lesson_count,
                    current_item=lesson.title[:50],
                )
                
                if progress_mgr.is_lesson_complete(lesson.id):
                    await manager.add_task_log(task.id, f"Skip (completed): {lesson.title}")
                    continue
                
                try:
                    await check_task_state()
                    await manager.add_task_log(task.id, f"Downloading: {lesson.title}")
                    content = await parser.parse_lesson_content(lesson)
                    
                    result = await download_lesson(
                        lesson=lesson,
                        content=content,
                        downloader=downloader,
                        md_generator=md_generator,
                        compressor=compressor,
                        config=config,
                        chapter_dir=chapter_dir,
                        course_dir=course_dir,
                        images_dir=images_dir,
                        audio_dir=audio_dir,
                        video_dir=video_dir,
                    )
                    
                    progress_mgr.mark_lesson_complete(
                        lesson.id, lesson.title,
                        images_done=result["images_done"],
                        audio_done=result["audio_done"],
                        video_done=result["video_done"],
                    )
                    await manager.add_task_log(task.id, f"Done: {lesson.title}")
                
                except TaskCancelled:
                    raise
                except TaskPaused:
                    raise
                except PermissionError as e:
                    await manager.add_task_log(task.id, f"登录失效: {e}，重新登录...")
                    if await browser.login():
                        await manager.add_task_log(task.id, "重新登录成功，重试当前小节...")
                        try:
                            content = await parser.parse_lesson_content(lesson)
                            result = await download_lesson(
                                lesson=lesson,
                                content=content,
                                downloader=downloader,
                                md_generator=md_generator,
                                compressor=compressor,
                                config=config,
                                chapter_dir=chapter_dir,
                                course_dir=course_dir,
                                images_dir=images_dir,
                                audio_dir=audio_dir,
                                video_dir=video_dir,
                            )
                            progress_mgr.mark_lesson_complete(
                                lesson.id, lesson.title,
                                images_done=result["images_done"],
                                audio_done=result["audio_done"],
                                video_done=result["video_done"],
                            )
                            await manager.add_task_log(task.id, f"Done: {lesson.title}")
                        except Exception as retry_e:
                            await manager.add_task_log(task.id, f"重试失败 ({lesson.title}): {retry_e}")
                            progress_mgr.update_lesson_progress(lesson.id, lesson.title, error=str(retry_e))
                    else:
                        raise RuntimeError("重新登录失败，任务终止")
                except Exception as e:
                    await manager.add_task_log(task.id, f"Error ({lesson.title}): {e}")
                    progress_mgr.update_lesson_progress(lesson.id, lesson.title, error=str(e))
                
                await browser.random_delay()
        
        await manager.add_task_log(task.id, f"Crawl completed! Output: {course_dir}")

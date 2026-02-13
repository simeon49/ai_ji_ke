import asyncio
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.config import Config
from src.browser import BrowserManager
from src.parser import CourseParser
from src.downloader import Downloader
from src.markdown import MarkdownGenerator
from src.progress import ProgressManager
from src.compressor import MediaCompressor
from src.utils import (
    sanitize_name,
    build_course_dir_name,
    build_chapter_dir_name,
    download_lesson,
)

console = Console()


async def _crawl_course(url: str, config: Config):
    console.print(
        Panel.fit(
            f"[bold cyan]极客时间课程爬虫[/bold cyan]\n"
            f"课程URL: {url}\n"
            f"输出目录: {config.output_dir}",
            title="开始爬取",
        )
    )

    compressor = MediaCompressor(config.to_compression_config())

    async with BrowserManager(config) as browser:
        if not await browser.login():
            console.print("[red]登录失败，请检查账号密码[/red]")
            return

        parser = CourseParser(browser)
        downloader = Downloader(config.output_dir)
        md_generator = MarkdownGenerator(config.output_dir)

        course = await parser.parse_course(url)

        course_dir_name = build_course_dir_name(course)
        course_dir = config.output_dir / course_dir_name
        course_dir.mkdir(parents=True, exist_ok=True)

        progress_mgr = ProgressManager(course_dir)
        progress_mgr.load(course.id, course.title)

        images_dir = course_dir / "images"
        audio_dir = course_dir / "audio"
        video_dir = course_dir / "video"
        images_dir.mkdir(exist_ok=True)

        total_lessons = len(course.all_lessons)
        progress_mgr.set_total_lessons(total_lessons)

        console.print(f"\n[green]课程: {course.title}[/green]")
        console.print(f"[green]作者: {course.author}[/green]")
        console.print(f"[green]共 {len(course.chapters)} 章, {total_lessons} 节课程[/green]")

        progress_mgr.print_summary()
        console.print("")

        if course.intro:
            console.print("[cyan]生成课程介绍...[/cyan]")
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
            console.print("[green]✓ intro.md[/green]")

        lesson_count = 0
        skipped_count = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("爬取课程...", total=total_lessons)

            for chapter in course.chapters:
                chapter_dir_name = build_chapter_dir_name(chapter)
                chapter_dir = course_dir / chapter_dir_name
                chapter_dir.mkdir(parents=True, exist_ok=True)

                console.print(f"\n[cyan]章节: {chapter.title}[/cyan]")

                for lesson in chapter.lessons:
                    lesson_count += 1
                    progress.update(
                        task, description=f"[{lesson_count}/{total_lessons}] {lesson.title[:30]}..."
                    )

                    if progress_mgr.is_lesson_complete(lesson.id):
                        console.print(f"[dim]⏭ {lesson.title} (已完成)[/dim]")
                        skipped_count += 1
                        progress.advance(task)
                        continue

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
                            lesson.id,
                            lesson.title,
                            images_done=result["images_done"],
                            audio_done=result["audio_done"],
                            video_done=result["video_done"],
                        )
                        console.print(f"[green]✓[/green] {lesson.title}")

                    except Exception as e:
                        console.print(f"[red]✗ {lesson.title}: {e}[/red]")
                        progress_mgr.update_lesson_progress(lesson.id, lesson.title, error=str(e))

                    progress.advance(task)
                    await browser.random_delay()

        summary_lines = [
            f"[bold green]爬取完成！[/bold green]",
            f"课程: {course.title}",
            f"输出目录: {course_dir}",
            f"新下载: {lesson_count - skipped_count} 节",
        ]
        if skipped_count > 0:
            summary_lines.append(f"跳过已完成: {skipped_count} 节")

        console.print(Panel.fit("\n".join(summary_lines), title="完成"))

import re
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
import markdownify

from src.models import Lesson, LessonContent, CourseIntro, Comment, CourseModule
from src.utils import sanitize_name


class MarkdownGenerator:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
    
    def _convert_html_to_markdown(
        self,
        html: str,
        image_mapping: dict[str, Path] | None = None,
        base_dir: Path | None = None,
        relative_prefix: Path | None = None,
        detect_code_language: bool = True,
    ) -> str:
        soup = BeautifulSoup(html, "lxml")
        
        if image_mapping and base_dir:
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src", "")
                if src in image_mapping:
                    rel_path = image_mapping[src].relative_to(base_dir)
                    if relative_prefix:
                        rel_path = relative_prefix / rel_path
                    img["src"] = str(rel_path)
        
        for tag in soup.find_all(["script", "style", "video"]):
            tag.decompose()
        
        callback = self._detect_code_language if detect_code_language else None
        md = markdownify.markdownify(
            str(soup),
            heading_style="ATX",
            bullets="-",
            code_language_callback=callback,
        )
        
        md = re.sub(r'\n{3,}', '\n\n', md)
        
        return md.strip()
    
    def _detect_code_language(self, el) -> str | None:
        classes = el.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        
        for cls in classes:
            if cls.startswith("language-"):
                return cls.replace("language-", "")
            if cls.startswith("lang-"):
                return cls.replace("lang-", "")
        
        return None
    
    async def generate_intro(
        self,
        intro: CourseIntro,
        course_dir: Path,
        cover_path: Path | None = None,
        images_dir: Path | None = None,
        downloader=None,
    ) -> Path:
        intro_path = course_dir / "intro.md"
        all_image_mapping: dict[str, Path] = {}
        
        lines = [
            f"# {intro.title}",
            "",
        ]
        
        if intro.subtitle:
            lines.extend([f"**{intro.subtitle}**", ""])
        
        lines.extend([
            "## 课程信息",
            "",
            f"- **课程类型**: {intro.course_type}",
            f"- **总课程数**: {intro.unit}",
            f"- **状态**: {'已完结' if intro.is_finish else '更新中'}",
        ])
        
        if intro.learn_count > 0:
            lines.append(f"- **学习人数**: {intro.learn_count}")
        
        lines.append("")
        
        if cover_path and cover_path.exists():
            relative_cover = cover_path.relative_to(course_dir)
            lines.extend([
                "## 封面",
                "",
                f"![课程封面]({relative_cover})",
                "",
            ])
        
        if intro.keywords:
            lines.extend([
                "## 关键词",
                "",
                ", ".join(intro.keywords),
                "",
            ])
        
        if intro.author.name:
            lines.extend([
                "## 讲师介绍",
                "",
                f"### {intro.author.name}",
                "",
            ])
            if intro.author.intro:
                lines.extend([f"**{intro.author.intro}**", ""])
            
            if intro.author.brief_html and images_dir and downloader:
                img_mapping = await self._download_intro_images(
                    intro.author.brief_html, images_dir, downloader, prefix="author"
                )
                all_image_mapping.update(img_mapping)
                md_content = self._convert_html_to_markdown(
                    intro.author.brief_html,
                    image_mapping=all_image_mapping,
                    base_dir=course_dir,
                    detect_code_language=False,
                )
                lines.extend([md_content, ""])
            elif intro.author.brief:
                lines.extend([intro.author.brief, ""])
        
        for module in intro.modules:
            if module.name == "gain":
                lines.extend([
                    "## 你将获得",
                    "",
                ])
                if module.content and images_dir and downloader:
                    img_mapping = await self._download_intro_images(
                        module.content, images_dir, downloader, prefix="gain"
                    )
                    all_image_mapping.update(img_mapping)
                    md_content = self._convert_html_to_markdown(
                        module.content,
                        image_mapping=all_image_mapping,
                        base_dir=course_dir,
                        detect_code_language=False,
                    )
                    lines.extend([md_content, ""])
                elif intro.highlights:
                    for highlight in intro.highlights:
                        lines.append(f"- {highlight}")
                    lines.append("")
            
            elif module.name == "class_intro":
                lines.extend([
                    "## 课程介绍",
                    "",
                ])
                if module.content and images_dir and downloader:
                    img_mapping = await self._download_intro_images(
                        module.content, images_dir, downloader, prefix="class_intro"
                    )
                    all_image_mapping.update(img_mapping)
                    md_content = self._convert_html_to_markdown(
                        module.content,
                        image_mapping=all_image_mapping,
                        base_dir=course_dir,
                        detect_code_language=False,
                    )
                    lines.extend([md_content, ""])
            
            elif module.name == "class_menu":
                lines.extend([
                    "## 课程目录",
                    "",
                ])
                if module.content and images_dir and downloader:
                    img_mapping = await self._download_intro_images(
                        module.content, images_dir, downloader, prefix="class_menu"
                    )
                    all_image_mapping.update(img_mapping)
                    md_content = self._convert_html_to_markdown(
                        module.content,
                        image_mapping=all_image_mapping,
                        base_dir=course_dir,
                        detect_code_language=False,
                    )
                    lines.extend([md_content, ""])
            
            elif module.name == "crowd":
                lines.extend([
                    "## 适合人群",
                    "",
                ])
                if module.content and images_dir and downloader:
                    img_mapping = await self._download_intro_images(
                        module.content, images_dir, downloader, prefix="crowd"
                    )
                    all_image_mapping.update(img_mapping)
                    md_content = self._convert_html_to_markdown(
                        module.content,
                        image_mapping=all_image_mapping,
                        base_dir=course_dir,
                        detect_code_language=False,
                    )
                    lines.extend([md_content, ""])
                elif intro.audience:
                    for aud in intro.audience:
                        lines.append(f"- {aud}")
                    lines.append("")
        
        final_content = "\n".join(lines)
        intro_path.write_text(final_content, encoding="utf-8")
        
        return intro_path
    
    async def _download_intro_images(
        self,
        html: str,
        images_dir: Path,
        downloader,
        prefix: str = "intro",
    ) -> dict[str, Path]:
        soup = BeautifulSoup(html, "lxml")
        image_urls = []
        
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if src:
                image_urls.append(src)
        
        if not image_urls:
            return {}
        
        return await downloader.download_images(image_urls, images_dir, prefix=f"[{prefix}]")
    
    def generate(
        self,
        lesson: Lesson,
        content: LessonContent,
        chapter_dir: Path,
        course_dir: Path,
        image_mapping: dict[str, Path],
        audio_path: Path | None = None,
        video_path: Path | None = None,
    ) -> Path:
        chapter_dir.mkdir(parents=True, exist_ok=True)
        
        lesson_filename = f"{sanitize_name(lesson.title)}.md"
        lesson_path = chapter_dir / lesson_filename
        
        md_content = self._convert_html_to_markdown(
            content.html_content,
            image_mapping=image_mapping,
            base_dir=course_dir,
            relative_prefix=Path(".."),
        )
        
        lines = [
            f"# {lesson.title}",
            "",
        ]
        
        if audio_path and audio_path.exists():
            relative_audio = Path("..") / audio_path.relative_to(course_dir)
            lines.extend([
                f"**音频**: [{audio_path.name}]({relative_audio})",
                "",
            ])
        
        if video_path and video_path.exists():
            relative_video = Path("..") / video_path.relative_to(course_dir)
            lines.extend([
                f"**视频**: [{video_path.name}]({relative_video})",
                "",
            ])
        
        lines.extend([
            "---",
            "",
            md_content,
        ])
        
        if content.comments:
            lines.extend(self._render_comments(content.comments))
        
        final_content = "\n".join(lines)
        lesson_path.write_text(final_content, encoding="utf-8")
        
        return lesson_path
    
    def _format_time(self, timestamp: int) -> str:
        if timestamp <= 0:
            return ""
        try:
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""
    
    def _render_comments(self, comments: list[Comment]) -> list[str]:
        if not comments:
            return []
        
        lines = [
            "",
            "---",
            "",
            "## 精选留言",
            "",
        ]
        
        for comment in comments:
            time_str = self._format_time(comment.ctime)
            location = f" · {comment.ip_address}" if comment.ip_address else ""
            top_badge = " 🔝" if comment.is_top else ""
            like_str = f" · 👍 {comment.like_count}" if comment.like_count > 0 else ""
            
            lines.extend([
                f"### {comment.user_name}{top_badge}",
                f"*{time_str}{location}{like_str}*",
                "",
                comment.content,
                "",
            ])
            
            for reply in comment.replies:
                reply_time = self._format_time(reply.ctime)
                reply_location = f" · {reply.ip_address}" if reply.ip_address else ""
                lines.extend([
                    f"> **{reply.user_name}** *{reply_time}{reply_location}*",
                    f"> ",
                    f"> {reply.content}",
                    "",
                ])
        
        return lines

import asyncio
import re
import json
from urllib.parse import urlparse
from playwright.async_api import Page
from rich.console import Console

from src.models import Course, Chapter, Lesson, LessonType, LessonContent, CourseIntro, Comment, CommentReply, AuthorInfo, CourseModule
from src.browser import BrowserManager

console = Console()


class CourseParser:
    BASE_URL = "https://time.geekbang.org"
    API_ARTICLE = "https://time.geekbang.org/serv/v1/article"
    API_COLUMN_INFO = "https://time.geekbang.org/serv/v3/column/info"
    API_COLUMN_ARTICLES = "https://time.geekbang.org/serv/v1/column/articles"
    API_COMMENT_LIST = "https://time.geekbang.org/serv/v4/comment/list"
    
    def __init__(self, browser: BrowserManager):
        self.browser = browser
        self._column_id: str | None = None
    
    def _extract_column_id_from_url(self, url: str) -> str | None:
        match = re.search(r'/column/intro/(\d+)', url)
        return match.group(1) if match else None
    
    async def get_column_id(self, url: str) -> str:
        if self._column_id:
            return self._column_id
        
        column_id = self._extract_column_id_from_url(url)
        if column_id:
            # 对于 intro 页面，需要先导航到页面以建立 session context
            await self.browser.page.goto(url)
            await self.browser.page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(0.3)
            self._column_id = column_id
            return column_id
        
        raise ValueError(f"Cannot extract column ID from URL: {url} (仅支持 /column/intro/ 格式)")
    
    async def parse_course(self, url: str) -> Course:
        column_id = await self.get_column_id(url)
        console.print(f"[cyan]解析课程 (column_id={column_id})[/cyan]")
        
        page = self.browser.page
        
        js_code = f"""
        async () => {{
            const res = await fetch('{self.API_COLUMN_INFO}', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{product_id: {column_id}, with_recommend_article: true}}),
                credentials: 'include'
            }});
            return await res.json();
        }}
        """
        
        result = await page.evaluate(js_code)
        
        if result and result.get("data"):
            data = result["data"]
            title = data.get("title", "Unknown Course")
            author = data.get("author", {}).get("name", "Unknown")
        else:
            title = "Unknown Course"
            author = "Unknown"
        
        course = Course(
            id=column_id,
            title=title,
            author=author,
            raw_data=result,  # 保存原始 API 响应数据
        )
        
        course.intro = await self._parse_course_intro(column_id, result)
        
        await self._parse_chapters(course)
        
        console.print(f"[green]课程解析完成: {course.title}, 共 {len(course.all_lessons)} 节[/green]")
        return course
    
    async def _parse_course_intro(self, column_id: str, column_info_result: dict | None) -> CourseIntro:
        data = column_info_result.get("data", {}) if column_info_result else {}
        
        author_data = data.get("author", {})
        author_info = AuthorInfo(
            name=author_data.get("name", ""),
            intro=author_data.get("intro", ""),
            avatar=author_data.get("avatar", ""),
            brief=author_data.get("brief", ""),
            brief_html=author_data.get("brief_html", ""),
        )
        
        extra = data.get("extra", {})
        modules = []
        for mod in extra.get("modules", []):
            modules.append(CourseModule(
                name=mod.get("name", ""),
                title=mod.get("title", ""),
                content=mod.get("content", ""),
                type=mod.get("type", "normal"),
                is_top=mod.get("is_top", False),
            ))
        
        seo_keywords = data.get("seo", {}).get("keywords", [])
        keywords = [k for k in seo_keywords if k]
        
        cover_data = data.get("cover", {})
        cover_url = cover_data.get("square", "") if cover_data else ""
        
        intro = CourseIntro(
            title=data.get("title", ""),
            subtitle=data.get("subtitle", ""),
            course_type=data.get("type", ""),
            unit=data.get("unit", ""),
            is_finish=data.get("is_finish", False),
            cover_url=cover_url,
            keywords=keywords,
            author=author_info,
            modules=modules,
            author_name=author_info.name,
            author_intro=author_info.intro,
            author_header=author_info.avatar,
            learn_count=extra.get("sub", {}).get("count", 0),
        )
        
        for mod in modules:
            if mod.name == "gain":
                intro.highlights = self._extract_list_items_from_html(mod.content)
            elif mod.name == "crowd":
                intro.audience = self._extract_list_items_from_html(mod.content)
        
        return intro
    
    def _extract_list_items_from_html(self, html: str) -> list[str]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        items = []
        for li in soup.find_all("li"):
            text = li.get_text(strip=True)
            if text:
                items.append(text)
        return items
    
    async def _parse_chapters(self, course: Course):
        page = self.browser.page
        
        chapters_js = f"""
        async () => {{
            const res = await fetch('https://time.geekbang.org/serv/v1/chapters', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{cid: '{course.id}'}}),
                credentials: 'include'
            }});
            return await res.json();
        }}
        """
        
        chapters_result = await page.evaluate(chapters_js)
        chapter_id_to_info: dict[str, dict] = {}
        
        if chapters_result and chapters_result.get("data"):
            for idx, ch in enumerate(chapters_result["data"]):
                chapter_id_to_info[ch["id"]] = {
                    "title": ch["title"],
                    "order": idx,
                }
        
        articles_js = f"""
        async () => {{
            const res = await fetch('{self.API_COLUMN_ARTICLES}', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    cid: {course.id},
                    order: "earliest",
                    prev: 0,
                    sample: false,
                    size: 500
                }}),
                credentials: 'include'
            }});
            return await res.json();
        }}
        """
        
        result = await page.evaluate(articles_js)
        
        if not result or not result.get("data") or not result["data"].get("list"):
            console.print("[yellow]无法获取课程列表，尝试从页面解析...[/yellow]")
            await self._parse_chapters_from_page(course)
            return
        
        articles = result["data"]["list"]
        
        chapters_map: dict[str, Chapter] = {}
        lesson_order_in_chapter: dict[str, int] = {}
        
        for article in articles:
            chapter_id = str(article.get("chapter_id", ""))
            
            if chapter_id and chapter_id in chapter_id_to_info:
                chapter_info = chapter_id_to_info[chapter_id]
                chapter_title = chapter_info["title"]
                chapter_order = chapter_info["order"]
            else:
                chapter_title = "全部课程"
                chapter_order = 999
            
            if chapter_title not in chapters_map:
                chapters_map[chapter_title] = Chapter(title=chapter_title, order=chapter_order)
                lesson_order_in_chapter[chapter_title] = 0
            
            chapter = chapters_map[chapter_title]
            lesson_order = lesson_order_in_chapter[chapter_title]
            
            article_id = str(article.get("id", ""))
            article_title = article.get("article_title", "Unknown")
            
            lesson_type = LessonType.TEXT
            video_time_raw = article.get("video_time", 0)
            audio_time_raw = article.get("audio_time", 0)
            audio_download_raw = article.get("audio_download_time", 0)
            
            def parse_time(val) -> int:
                if not val:
                    return 0
                if isinstance(val, int):
                    return val
                if isinstance(val, str):
                    if ':' in val:
                        parts = val.split(':')
                        try:
                            if len(parts) == 2:
                                return int(parts[0]) * 60 + int(parts[1])
                            elif len(parts) == 3:
                                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                        except ValueError:
                            return 0
                    try:
                        return int(val)
                    except ValueError:
                        return 0
                return 0
            
            video_time = parse_time(video_time_raw)
            audio_time = parse_time(audio_time_raw)
            
            if video_time > 0:
                lesson_type = LessonType.VIDEO
            elif audio_time > 0:
                lesson_type = LessonType.AUDIO
            
            duration = ""
            time_seconds = video_time or audio_time or parse_time(audio_download_raw)
            if time_seconds > 0:
                minutes = time_seconds // 60
                seconds = time_seconds % 60
                duration = f"{minutes}:{seconds:02d}"
            
            lesson = Lesson(
                id=article_id,
                title=article_title,
                url=f"{self.BASE_URL}/column/article/{article_id}",
                type=lesson_type,
                duration=duration,
                is_free=article.get("is_free", False),
                order=lesson_order,
                chapter_order=chapter.order,
            )
            
            chapter.lessons.append(lesson)
            lesson_order_in_chapter[chapter_title] += 1
        
        for chapter in chapters_map.values():
            if chapter.lessons:
                course.chapters.append(chapter)
        
        course.chapters.sort(key=lambda c: c.order)
    
    async def _parse_chapters_from_page(self, course: Course):
        page = self.browser.page
        
        try:
            await page.wait_for_selector('[class*="catalog"], [class*="chapter"], [class*="article-list"]', timeout=10000)
        except Exception:
            console.print("[red]无法加载课程目录[/red]")
            return
        
        expand_buttons = await page.query_selector_all('[class*="expand"], [class*="collapse"], [class*="fold"]')
        for btn in expand_buttons:
            try:
                await btn.click()
                await self.browser.random_delay()
            except Exception:
                pass
        
        default_chapter = Chapter(title="全部课程")
        lesson_links = await page.query_selector_all('a[href*="/column/article/"]')
        
        for idx, link in enumerate(lesson_links):
            lesson = await self._parse_lesson_link(link, idx)
            if lesson:
                default_chapter.lessons.append(lesson)
        
        if default_chapter.lessons:
            course.chapters.append(default_chapter)
    
    async def _parse_lesson_link(self, link, order: int) -> Lesson | None:
        href = await link.get_attribute("href")
        if not href:
            return None
        
        title_text = await link.inner_text()
        title = title_text.strip()
        
        # 清理标题
        title = re.sub(r'\s+', ' ', title)
        
        # 检测课程类型
        lesson_type = LessonType.TEXT
        parent_html = await link.evaluate("el => el.parentElement ? el.parentElement.innerHTML : ''")
        
        if "视频" in parent_html or "video" in parent_html.lower():
            lesson_type = LessonType.VIDEO
        elif "音频" in parent_html or "audio" in parent_html.lower():
            lesson_type = LessonType.AUDIO
        
        # 提取时长
        duration = ""
        duration_match = re.search(r'(\d+:\d+)', parent_html)
        if duration_match:
            duration = duration_match.group(1)
        
        # 检测是否免费
        is_free = "免费" in parent_html or "free" in parent_html.lower()
        
        # 获取课程ID
        lesson_id = href.split("/")[-1].split("?")[0]
        
        full_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
        
        return Lesson(
            id=lesson_id,
            title=title,
            url=full_url,
            type=lesson_type,
            duration=duration,
            is_free=is_free,
            order=order,
        )
    
    async def parse_lesson_content(self, lesson: Lesson) -> LessonContent:
        console.print(f"[cyan]解析小节: {lesson.title}[/cyan]")
        
        page = self.browser.page
        await page.goto(lesson.url)
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(0.5)
        
        content = LessonContent(lesson=lesson)
        
        js_code = f"""
        async () => {{
            const res = await fetch('{self.API_ARTICLE}', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{id: {lesson.id}}}),
                credentials: 'include'
            }});
            return await res.json();
        }}
        """
        
        result = await page.evaluate(js_code)
        
        if result:
            error_code = result.get("code", 0)
            if error_code != 0:
                error_msg = result.get("error", {}).get("msg", "未知错误")
                console.print(f"[yellow]API返回错误 (code={error_code}): {error_msg}[/yellow]")
                
                # code=-1 且消息包含"未购买"或"未登录"表示需要重新登录
                if error_code == -1 and ("未购买" in error_msg or "未登录" in error_msg or "登录" in error_msg):
                    raise PermissionError(f"登录状态失效: {error_msg}")
            
            if result.get("data"):
                data = result["data"]
                
                article_content = data.get("article_content", "")
                article_content_short = data.get("article_content_short", "")
                
                if article_content:
                    content.html_content = article_content
                elif article_content_short:
                    console.print(f"[yellow]警告: 仅获取到摘要内容，可能未登录或未购买此课程[/yellow]")
                    # 如果只有摘要内容，也可能是登录失效
                    raise PermissionError("仅获取到摘要内容，登录状态可能已失效")
                
                audio_download_url = data.get("audio_download_url", "")
                if audio_download_url:
                    content.audio_url = audio_download_url
                
                video_media = data.get("video_media", "")
                if video_media:
                    content.video_url = video_media
        
        if not content.html_content:
            article_el = await page.query_selector('[class*="article-content"], [class*="main-content"], article, [class*="Post_content"]')
            
            if article_el:
                content.html_content = await article_el.inner_html()
        
        if content.html_content:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content.html_content, "lxml")
            
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src")
                if src:
                    content.images.append(src)
            
            if not content.video_url:
                for video in soup.find_all("video"):
                    for source in video.find_all("source"):
                        src = source.get("src", "")
                        src_type = source.get("type", "")
                        if src and "mp4" in src_type.lower():
                            content.video_url = src
                            break
                        elif src and src.endswith(".mp4"):
                            content.video_url = src
                            break
                    if not content.video_url:
                        for source in video.find_all("source"):
                            src = source.get("src", "")
                            if src and not src.endswith(".m3u8"):
                                content.video_url = src
                                break
                    if content.video_url:
                        break
        
        if not content.audio_url:
            audio_el = await page.query_selector("audio source, audio[src]")
            if audio_el:
                content.audio_url = await audio_el.get_attribute("src") or ""
        
        if not content.video_url:
            video_el = await page.query_selector("video source, video[src]")
            if video_el:
                content.video_url = await video_el.get_attribute("src") or ""
        
        if not content.video_url and lesson.type == LessonType.VIDEO:
            content.video_url = await self._extract_video_url(page)
        
        content.comments = await self._fetch_comments(lesson.id)
        
        return content
    
    async def _fetch_comments(self, article_id: str) -> list[Comment]:
        page = self.browser.page
        
        comments = []
        prev = 0
        
        while True:
            js_code = f"""
            async () => {{
                const res = await fetch('{self.API_COMMENT_LIST}', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        aid: {article_id},
                        order_by: 2,
                        prev: {prev},
                        size: 50
                    }}),
                    credentials: 'include'
                }});
                return await res.json();
            }}
            """
            
            result = await page.evaluate(js_code)
            
            if not result or result.get("code") != 0:
                break
            
            data = result.get("data", {})
            comment_list = data.get("list", [])
            
            if not comment_list:
                break
            
            for item in comment_list:
                replies = []
                for reply_item in item.get("replies") or []:
                    replies.append(CommentReply(
                        id=reply_item.get("id", 0),
                        content=reply_item.get("content", ""),
                        user_name=reply_item.get("user_name", ""),
                        ctime=reply_item.get("ctime", 0),
                        ip_address=reply_item.get("ip_address", ""),
                    ))
                
                comments.append(Comment(
                    id=item.get("id", 0),
                    user_name=item.get("user_name", ""),
                    content=item.get("comment_content", ""),
                    ctime=item.get("comment_ctime", 0),
                    like_count=item.get("like_count", 0),
                    ip_address=item.get("ip_address", ""),
                    user_header=item.get("user_header", ""),
                    is_top=item.get("comment_is_top", False),
                    replies=replies,
                ))
            
            page_info = data.get("page", {})
            if not page_info.get("more", False):
                break
            
            prev = comments[-1].id if comments else 0
        
        return comments
    
    async def _extract_video_url(self, page: Page) -> str:
        # 尝试从网络请求中捕获视频URL
        try:
            # 点击播放按钮
            play_btn = await page.query_selector('[class*="play"], button[aria-label*="play"]')
            if play_btn:
                await play_btn.click()
                await self.browser.random_delay()
            
            # 等待视频元素出现
            video_el = await page.wait_for_selector("video[src], video source[src]", timeout=5000)
            if video_el:
                return await video_el.get_attribute("src") or ""
        except Exception:
            pass
        
        return ""

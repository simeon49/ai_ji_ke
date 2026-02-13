import asyncio
import hashlib
from pathlib import Path
from urllib.parse import urlparse, unquote

import aiohttp
import aiofiles

from src.utils import sanitize_name


class Downloader:
    def __init__(self, output_dir: Path, concurrent_limit: int = 3):
        self.output_dir = output_dir
        self.concurrent_limit = concurrent_limit
        self._semaphore = asyncio.Semaphore(concurrent_limit)
    
    def _get_extension(self, url: str, content_type: str = "") -> str:
        parsed = urlparse(url)
        path = unquote(parsed.path)
        
        if "." in path.split("/")[-1]:
            ext = "." + path.split(".")[-1].split("?")[0]
            if len(ext) <= 5:
                return ext
        
        content_type_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "audio/mpeg": ".mp3",
            "audio/mp4": ".m4a",
            "audio/ogg": ".ogg",
            "video/mp4": ".mp4",
            "video/webm": ".webm",
        }
        
        for ct, ext in content_type_map.items():
            if ct in content_type.lower():
                return ext
        
        return ""
    
    def _url_hash(self, url: str) -> str:
        return hashlib.md5(url.encode()).hexdigest()[:8]
    
    async def download_file(
        self,
        url: str,
        save_dir: Path,
        filename: str | None = None,
        show_progress: bool = True,
    ) -> Path | None:
        async with self._semaphore:
            try:
                timeout = aiohttp.ClientTimeout(total=300, connect=30)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as response:
                        if response.status != 200:
                            return None
                        
                        content_type = response.headers.get("Content-Type", "")
                        ext = self._get_extension(url, content_type)
                        
                        if not filename:
                            filename = f"{self._url_hash(url)}{ext}"
                        elif not filename.endswith(ext) and ext:
                            filename = f"{filename}{ext}"
                        
                        filename = sanitize_name(filename, max_length=200)
                        save_dir.mkdir(parents=True, exist_ok=True)
                        save_path = save_dir / filename
                        
                        if save_path.exists():
                            return save_path
                        
                        async with aiofiles.open(save_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(65536):
                                await f.write(chunk)
                                await asyncio.sleep(0)
                        
                        return save_path
            
            except asyncio.TimeoutError:
                return None
            except Exception:
                return None
    
    async def download_images(
        self,
        urls: list[str],
        save_dir: Path,
        prefix: str = "",
    ) -> dict[str, Path]:
        results = {}
        
        tasks = []
        for url in urls:
            url_hash = self._url_hash(url)
            if prefix:
                filename = f"{prefix}__{url_hash}"
            else:
                filename = url_hash
            tasks.append(self.download_file(url, save_dir, filename=filename, show_progress=False))
        
        downloaded = await asyncio.gather(*tasks)
        
        for url, path in zip(urls, downloaded):
            if path:
                results[url] = path
        
        return results
    
    async def download_audio(self, url: str, save_dir: Path, filename: str = "audio") -> Path | None:
        if not url:
            return None
        return await self.download_file(url, save_dir, filename)
    
    async def download_video(self, url: str, save_dir: Path, filename: str = "video") -> Path | None:
        if not url:
            return None
        return await self.download_file(url, save_dir, filename)

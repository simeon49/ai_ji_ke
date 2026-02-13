#!/usr/bin/env python3

import subprocess
import re
import os
import shlex
from pathlib import Path
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.panel import Panel
from typing import List, Dict, Optional

LOCAL_COURSES_DIR = Path("org_courses")
REMOTE_HOST = "ubuntu@goodseed.work"
REMOTE_BASE_DIR = "/home/ubuntu/WorkSpace/ai_ji_ke/org_courses"

RSYNC_ARGS = [
    "-avz",
    "--progress",
    "--partial",
    "--delete",
    "-e", "ssh",
]

console = Console()


class CourseUploader:
    def __init__(self, local_dir: Path, remote_host: str, remote_dir: str):
        self.local_dir = local_dir
        self.remote_host = remote_host
        self.remote_dir = remote_dir
        self.courses: List[Path] = []
        self.results: Dict[str, Dict] = {}

    def scan_courses(self) -> List[Path]:
        if not self.local_dir.exists():
            console.print(f"[red]错误: 本地目录不存在: {self.local_dir}[/red]")
            return []

        courses = sorted([
            d for d in self.local_dir.iterdir()
            if d.is_dir() and d.name.startswith("[")
        ])

        self.courses = courses
        console.print(f"[green]找到 {len(courses)} 个课程[/green]")
        return courses

    def get_course_size(self, course_path: Path) -> int:
        total = 0
        for root, dirs, files in os.walk(course_path):
            for file in files:
                total += os.path.getsize(os.path.join(root, file))
        return total

    def format_size(self, size: int) -> str:
        size_float = float(size)
        for unit in ["B", "KB", "MB", "GB"]:
            if size_float < 1024:
                return f"{size_float:.2f} {unit}"
            size_float /= 1024
        return f"{size_float:.2f} TB"

    def parse_rsync_output(self, line: str) -> Optional[Dict]:
        pattern = r"^\s*(\d+[\d,]*)\s+(\d+)%\s+([\d.]+[KMG]?B/s)\s*"
        match = re.match(pattern, line)
        if match:
            return {
                "transferred": int(match.group(1).replace(",", "")),
                "percent": int(match.group(2)),
                "speed": match.group(3),
            }
        return None

    def upload_course(self, course_path: Path, task_id, progress: Progress) -> bool:
        course_name = course_path.name
        escaped_course_name = shlex.quote(course_name)
        remote_path = f"{self.remote_host}:{self.remote_dir}/{escaped_course_name}"

        console.print(f"\n[bold blue]开始上传: {course_name}[/bold blue]")

        cmd = ["rsync"] + RSYNC_ARGS + [str(course_path) + "/", remote_path]

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            assert process.stdout is not None
            assert process.stderr is not None

            stderr_lines = []
            while True:
                line_bytes = process.stdout.readline()
                if not line_bytes:
                    break

                try:
                    line = line_bytes.decode('utf-8', errors='replace').strip()
                except:
                    continue

                if not line:
                    continue

                progress_info = self.parse_rsync_output(line)
                if progress_info:
                    progress.update(
                        task_id,
                        completed=progress_info["percent"],
                        description=f"[cyan]{course_name}[/cyan]",
                    )
                    console.print(
                        f"  {course_name}: {progress_info['percent']}% "
                        f"({progress_info['speed']})",
                        end="\r",
                    )

            process.wait()
            success = process.returncode == 0

            if success:
                console.print(f"  [green]✓ {course_name} 上传完成[/green]")
                self.results[course_name] = {"status": "success"}
            else:
                stderr_output = process.stderr.read().decode('utf-8', errors='replace')
                console.print(f"  [red]✗ {course_name} 上传失败 (返回码: {process.returncode})[/red]")
                if stderr_output.strip():
                    console.print(f"  [red]错误信息: {stderr_output.strip()}[/red]")
                self.results[course_name] = {"status": "failed", "code": process.returncode, "error": stderr_output.strip()}

            return success

        except Exception as e:
            console.print(f"  [red]✗ {course_name} 上传异常: {e}[/red]")
            self.results[course_name] = {"status": "error", "message": str(e)}
            return False

    def upload_all(self):
        courses = self.scan_courses()
        if not courses:
            return

        self.show_course_list(courses)

        console.print("\n[yellow]按 Enter 开始上传，Ctrl+C 取消...[/yellow]")
        input()

        total_size = sum(self.get_course_size(c) for c in courses)
        console.print(f"[cyan]总大小: {self.format_size(total_size)}[/cyan]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task_ids = {}
            for i, course in enumerate(courses):
                task_id = progress.add_task(
                    f"[cyan]{course.name}[/cyan]",
                    total=100,
                    completed=0,
                )
                task_ids[course] = task_id

            success_count = 0
            for course in courses:
                task_id = task_ids[course]
                if self.upload_course(course, task_id, progress):
                    success_count += 1
                    progress.update(task_id, completed=100)

        self.show_summary(success_count, len(courses))

    def show_course_list(self, courses: List[Path]):
        table = Table(title="待上传课程列表")
        table.add_column("序号", style="cyan", width=6)
        table.add_column("课程名称", style="green")
        table.add_column("大小", style="yellow", justify="right")

        for i, course in enumerate(courses, 1):
            size = self.get_course_size(course)
            table.add_row(str(i), course.name, self.format_size(size))

        console.print(table)

    def show_summary(self, success: int, total: int):
        console.print("\n" + "=" * 60)
        console.print(f"[bold]上传完成[/bold]")
        console.print(f"  总计: {total} 个课程")
        console.print(f"  成功: [green]{success}[/green]")
        console.print(f"  失败: [red]{total - success}[/red]")

        if self.results:
            console.print("\n[bold]详细结果:[/bold]")
            for course_name, result in self.results.items():
                if result["status"] == "success":
                    console.print(f"  [green]✓[/green] {course_name}")
                else:
                    console.print(f"  [red]✗[/red] {course_name} - {result}")


def main():
    console.print(Panel.fit(
        "[bold cyan]本地课程上传工具[/bold cyan]\n"
        f"本地目录: {LOCAL_COURSES_DIR}\n"
        f"远程服务器: {REMOTE_HOST}\n"
        f"远程目录: {REMOTE_BASE_DIR}",
        title="配置信息"
    ))

    if not LOCAL_COURSES_DIR.exists():
        console.print(f"[red]错误: 本地目录不存在: {LOCAL_COURSES_DIR}[/red]")
        return

    try:
        subprocess.run(["rsync", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        console.print("[red]错误: rsync 未安装或不可用[/red]")
        console.print("[yellow]请安装 rsync: brew install rsync (macOS) 或 apt install rsync (Ubuntu)[/yellow]")
        return

    uploader = CourseUploader(LOCAL_COURSES_DIR, REMOTE_HOST, REMOTE_BASE_DIR)
    uploader.upload_all()


if __name__ == "__main__":
    main()

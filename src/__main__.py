"""
极客时间课程爬虫 CLI 入口

用法:
    python -m geekbang_crawler              # 启动 Web 管理服务 (默认端口 8986)
    python -m geekbang_crawler --port 9000  # 指定端口启动服务
"""

from src.cli import cli

if __name__ == "__main__":
    cli()

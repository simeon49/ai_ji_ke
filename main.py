#!/usr/bin/env python3
"""
极客时间课程爬虫 CLI 入口

用法:
    uv run python ./main              # 启动 Web 管理服务 (默认端口 8986)
    uv run python ./main --port 9000  # 指定端口启动服务
"""

import sys
from pathlib import Path

# 添加 src 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.cli import cli

if __name__ == "__main__":
    cli()

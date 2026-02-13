# 爱极客 - 极客时间课程爬虫与本地学习平台
# 基于 Python 3.12 + Playwright + FastAPI

FROM python:3.12-slim-bookworm

# 设置工作目录
WORKDIR /app

# 安装系统依赖
# - Playwright 运行需要的依赖
# - FFmpeg 用于音视频处理
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    procps \
    xvfb \
    libgconf-2-4 \
    libnss3 \
    libatk-bridge2.0-0 \
    libxss1 \
    libgtk-3-0 \
    libgbm-dev \
    libasound2 \
    fonts-liberation \
    libu2f-udev \
    libvulkan1 \
    xdg-utils \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 安装 Playwright 浏览器（Chromium）
# 注意：Playwright 浏览器体积较大，这一步可能需要一些时间
# 官方源下载浏览器（国内镜像源版本不全）
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple playwright && \
    playwright install chromium && \
    playwright install-deps chromium

# 复制项目依赖文件
COPY pyproject.toml requirements.txt ./

# 安装 Python 依赖
RUN pip install --no-cache-dir -e .

# 复制项目源码
COPY src/ ./src/
COPY main.py ./

# 创建课程存储目录
RUN mkdir -p /app/org_courses

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright

# 暴露 Web 服务端口
EXPOSE 8986

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8986/health')" 2>/dev/null || exit 1

# 启动命令
CMD ["python", "main.py", "--port", "8986"]

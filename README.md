# 爱极客(个人学习平台项目, 仅供学习研究使用, 禁止一切商业使用目的)

## 概述

**爱极客(AI Ji Ke)** - 极客时间课程爬虫与本地学习平台

一个用于爬取极客时间课程内容的个人学习工具，提供：
- 基于 Playwright 的异步爬虫，自动登录并下载课程内容
- FastAPI 构建的 Web 管理界面，支持任务管理、用户系统、学习进度跟踪
- 本地 Markdown 课程浏览，支持学习进度标记
- 音视频压缩与媒体文件管理

**技术栈**: Python 3.10+, Playwright, FastAPI, Jinja2, Rich, Typer

**⚠️ 重要**: 仅供个人学习研究使用，禁止商业用途

## 目录结构

```
.
├── src/                          # 核心源码
│   ├── app.py                    # FastAPI 应用主入口 (路由、视图、API)
│   ├── main.py                   # 课程爬虫核心逻辑
│   ├── cli.py                    # Typer CLI 命令行入口
│   ├── __main__.py               # python -m src 启动入口
│   │
│   ├── models.py                 # 数据模型定义 (dataclass)
│   ├── config.py                 # 爬虫配置类
│   ├── settings.py               # 应用设置管理 (单例模式)
│   │
│   ├── browser.py                # Playwright 浏览器管理
│   ├── parser.py                 # 课程页面解析器
│   ├── downloader.py             # 媒体文件下载器
│   ├── markdown.py               # Markdown 生成器
│   ├── compressor.py             # 音视频压缩器
│   │
│   ├── auth.py                   # 用户认证、JWT、邀请码管理
│   ├── task_manager.py           # 异步任务队列管理
│   ├── crawler_runner.py         # 爬虫任务执行器
│   ├── learning_progress.py      # 用户学习进度管理
│   ├── label_manager.py          # 课程分类标签管理
│   ├── progress.py               # 课程下载进度跟踪
│   │
│   ├── storage.py                # 本地文件存储封装
│   ├── utils.py                  # 工具函数
│   ├── assign_labels.py          # 批量标签分配脚本
│   │
│   ├── templates/                # Jinja2 HTML 模板
│   │   ├── base.html             # 基础布局
│   │   ├── login.html            # 登录页面
│   │   ├── register.html         # 注册页面
│   │   ├── courses.html          # 课程列表
│   │   ├── course_detail.html    # 课程详情
│   │   ├── course_lesson_preview.html  # Markdown 阅读器
│   │   ├── tasks.html            # 任务管理
│   │   ├── task_detail.html      # 任务详情
│   │   ├── settings.html         # 个人设置
│   │   ├── admin_*.html          # 管理后台页面
│   │   └── _course_base.html     # 课程页基础模板
│   │
│   ├── static/                   # 静态资源
│   │   ├── avatars/              # 内置头像
│   │   └── marked.min.js         # Markdown 渲染库
│   │
│   └── labels_config.json        # 课程分类配置
│
├── org_courses/                  # 课程下载目录（默认输出位置）
│   └── [课程ID]__课程名/         # 课程目录命名格式
│       ├── images/               # 图片资源
│       ├── audio/                # 音频文件
│       ├── video/                # 视频文件
│       ├── 00__章节名/           # 章节目录
│       │   └── 00_标题.md        # 课程内容 Markdown
│       ├── intro.md              # 课程介绍
│       ├── .progress.json        # 下载进度记录
│       └── .labels.json          # 课程标签
│
├── pyproject.toml                # 项目配置 (uv/setuptools)
├── uv.lock                       # uv 依赖锁定
├── requirements.txt              # pip 依赖
└── main.py                       # 开发启动脚本
```

## 开发命令

```bash
# 安装依赖 (推荐 uv)
uv sync

# 或使用 pip
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium

# 启动 Web 服务 (默认端口 8986)
python ./main.py
# 或
uv run python ./main.py

# 指定端口
python ./main.py --port 9000

# 运行测试
pytest
```

## 课程目录结构

```
org_courses/
└── [课程ID]__课程名/
    ├── images/
    │   ├── abc12345.png
    │   └── def67890.jpg
    ├── audio/
    │   └── 00_开篇词.mp3
    ├── video/
    │   └── 01_基础篇.mp4
    ├── 00__章节名/
    │   ├── 00_开篇词_共生而非替代.md
    │   └── 01_基础篇_入门指南.md
    └── intro.md
```

## 注意事项

1. 仅供个人学习使用，请尊重版权
2. 请勿频繁请求，以免被封号
3. 建议使用默认延迟设置（1-3秒）
4. 如遇验证码，程序会等待你手动完成验证
5. 首次运行需通过 Web 界面配置账号信息

import webbrowser

import typer
from rich.console import Console

DEFAULT_PORT = 8986

cli = typer.Typer(
    name="geekbang-crawler",
    help="极客时间课程爬虫 - Web 管理界面",
    add_completion=False,
)
console = Console()


def _start_server(port: int, open_browser: bool = False):
    import uvicorn
    from src.app import app

    url = f"http://localhost:{port}"
    console.print(f"[bold cyan]启动AI极客管理服务[/bold cyan]")
    console.print(f"[green]访问地址: {url}[/green]")

    if open_browser:
        webbrowser.open(url)

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


@cli.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    port: int = typer.Option(
        DEFAULT_PORT,
        "--port", "-p",
        help="Web 服务端口",
    ),
    open_browser: bool = typer.Option(
        False,
        "--open-browser", "-b",
        help="Web 服务模式下启动服务后自动打开浏览器"
    ),
):
    if ctx.invoked_subcommand is not None:
        return

    try:
        _start_server(port=port, open_browser=open_browser)
    except KeyboardInterrupt:
        console.print("\n[yellow]服务已停止[/yellow]")
        raise typer.Exit(0)

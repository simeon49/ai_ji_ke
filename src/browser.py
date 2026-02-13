import asyncio
import random
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from rich.console import Console

from src.config import Config

console = Console()


class BrowserManager:
    LOGIN_URL = "https://account.geekbang.org/signin"
    BASE_URL = "https://time.geekbang.org"
    
    def __init__(self, config: Config):
        self.config = config
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
    
    async def __aenter__(self):
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def start(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        self._page = await self._context.new_page()
    
    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
    
    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser not started")
        return self._page
    
    async def random_delay(self):
        delay = random.uniform(self.config.delay_min, self.config.delay_max)
        await asyncio.sleep(delay)
    
    async def login(self) -> bool:
        console.print("[yellow]正在登录极客时间...[/yellow]")
        
        await self.page.goto(self.LOGIN_URL)
        await self.page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(0.5)
        
        password_tab = self.page.get_by_text("密码登录")
        if await password_tab.count() > 0:
            await password_tab.first.click()
            await self.page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(0.5)
        
        phone_input = self.page.get_by_placeholder("手机号")
        if await phone_input.count() > 0:
            await phone_input.fill(self.config.phone)
            await self.random_delay()
        else:
            console.print("[red]找不到手机号输入框[/red]")
            return False
        
        password_input = self.page.get_by_placeholder("密码")
        if await password_input.count() == 0:
            password_input = self.page.locator('input[type="password"]')
        if await password_input.count() == 0:
            all_inputs = self.page.locator('input')
            if await all_inputs.count() >= 2:
                password_input = all_inputs.nth(1)
        
        if await password_input.count() > 0:
            await password_input.fill(self.config.password)
            await self.random_delay()
        else:
            console.print("[red]找不到密码输入框[/red]")
            return False
        
        agreement_checkbox = self.page.locator('input[type="checkbox"]')
        if await agreement_checkbox.count() > 0:
            is_checked = await agreement_checkbox.is_checked()
            if not is_checked:
                await agreement_checkbox.click()
                await self.random_delay()
        
        login_btn = self.page.locator('div:text-is("登录"), button:text-is("登录")')
        if await login_btn.count() == 0:
            login_btn = self.page.get_by_role("button", name="登录")
        if await login_btn.count() == 0:
            login_btn = self.page.locator('[class*="login-btn"], [class*="submit"]')
        
        if await login_btn.count() > 0:
            await login_btn.first.click()
        else:
            console.print("[red]找不到登录按钮[/red]")
            return False
        
        try:
            await self.page.wait_for_url(
                lambda url: "time.geekbang.org" in url and "signin" not in url and "login" not in url,
                timeout=30000
            )
            console.print("[green]登录成功！[/green]")
            return True
        except Exception:
            pass
        
        captcha = self.page.locator('[class*="captcha"], [class*="slider"], [class*="verify"], [class*="geetest"]')
        if await captcha.count() > 0:
            console.print("[yellow]检测到验证码，请手动完成验证（2分钟超时）...[/yellow]")
            try:
                await self.page.wait_for_url(
                    lambda url: "time.geekbang.org" in url and "signin" not in url and "login" not in url,
                    timeout=120000
                )
                console.print("[green]登录成功！[/green]")
                return True
            except Exception:
                console.print("[red]验证超时[/red]")
                return False
        
        error_msg = self.page.locator('[class*="error"], [class*="toast"], [class*="message"]')
        if await error_msg.count() > 0:
            error_text = await error_msg.first.inner_text()
            if error_text.strip():
                console.print(f"[red]登录失败: {error_text}[/red]")
                return False
        
        current_url = self.page.url
        if "account.geekbang.org" in current_url:
            console.print("[yellow]登录处理中，等待页面跳转...[/yellow]")
            try:
                await self.page.wait_for_url(
                    lambda url: "time.geekbang.org" in url,
                    timeout=30000
                )
                console.print("[green]登录成功！[/green]")
                return True
            except Exception as e:
                console.print(f"[red]登录失败: 页面未跳转 ({e})[/red]")
                return False
        
        console.print("[green]登录成功！[/green]")
        return True

import asyncio
import os
import random
from playwright.async_api import async_playwright, Page
from utils.logger import log


class WeComRPA:
    """企业微信自动化填报类"""

    def __init__(self, form_url: str = None, user_data_dir: str = None):
        self.form_url = form_url or os.getenv("WECOM_FORM_URL", "")
        # 默认使用相对路径或环境配置
        default_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "../.browser_profiles/wecom"
        )
        self.user_data_dir = user_data_dir or os.getenv(
            "WECOM_USER_DATA_DIR", default_dir
        )
        # 处理可能的相对路径
        if not os.path.isabs(self.user_data_dir):
            self.user_data_dir = os.path.normpath(
                os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), self.user_data_dir
                )
            )

        self.browser_context = None
        self.page = None
        self.playwright = None

    async def _human_sleep(self, base: float = 1.0):
        """模拟人类随机停顿"""
        await asyncio.sleep(base + random.uniform(0.5, 1.5))

    async def _get_executable_path(self) -> str:
        """寻找本地安装的 Chrome 路径 (Windows)"""
        default_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        for path in default_paths:
            if os.path.exists(path):
                log.info(f"✨ 发现本地 Chrome 浏览器: {path}")
                return path
        return None

    async def init_browser(self, headless: bool = True):
        """初始化持久化浏览器环境"""
        log.info("🌐 [RPA] 正在初始化浏览器引擎...")
        self.playwright = await async_playwright().start()
        # 确保目录存在
        os.makedirs(self.user_data_dir, exist_ok=True)

        launch_params = {
            "user_data_dir": self.user_data_dir,
            "headless": headless,
            "args": ["--disable-blink-features=AutomationControlled"],
            "viewport": {"width": 1280, "height": 800},
        }

        # 优先使用本地物理路径
        exec_path = await self._get_executable_path()
        if exec_path:
            launch_params["executable_path"] = exec_path
        else:
            log.info("ℹ️ 未发现本地 Chrome，将回退使用 Playwright 默认渠道...")
            launch_params["channel"] = "chrome"

        self.browser_context = await self.playwright.chromium.launch_persistent_context(
            **launch_params
        )
        self.page = await self.browser_context.new_page()
        # 注入反检测脚本
        await self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        log.info("✅ [RPA] 浏览器启动成功。")

    async def handle_login(self) -> bool:
        """登录检测逻辑"""
        log.info(f"🚀 正在访问表单: {self.form_url}")
        await self.page.goto(self.form_url)
        await self._human_sleep(2)

        # 检测需要登录的二维码
        qr_selector = ".wwLogin_panel_middle .wwLogin_qrcode"
        if await self.page.query_selector(qr_selector):
            log.warning("🔑 检测到登录二维码，请在弹出的浏览器窗口中手动扫码完成登录！")
            # 轮询等待二维码消失
            while await self.page.query_selector(qr_selector):
                await asyncio.sleep(2)
            log.info("✅ 扫码成功，页面已跳转。")

        # 验证是否进入填报页
        await self.page.wait_for_selector(".HoverBtn_btn__2ansF", timeout=60000)
        log.info("🎯 已进入填报页面，环境准备就绪。")
        return True

    async def _trigger_modal(self):
        """触发填报模态框 (模仿人类点击路径)"""
        # 悬停激活
        hover_btn = ".HoverBtn_btn__2ansF"
        await self.page.hover(hover_btn)
        await self._human_sleep(0.5)

        # 点击日期 (腾讯文档报表的典型激活逻辑)
        date_trigger = ".question-main .form-date-main"
        await self.page.click(date_trigger)

        # 选今天
        today_btn = ".rc-calendar-footer-btn"
        await self.page.wait_for_selector(today_btn)
        await self.page.click(today_btn)
        await self._human_sleep(1)

        # 点击表格行打开弹窗
        row_selector = ".table-area-wrapper tbody .table-body-line-wrapper"
        try:
            await self.page.wait_for_selector(".table-area-wrapper", timeout=5000)
            rows = await self.page.query_selector_all(row_selector)
            if not rows:
                log.info("➕ 表格为空，点击'新增一行'开始填报...")
                await self.page.click(".add-area .add-line-wrapper")
            else:
                log.info("📝 点击现有表格首行开启表单...")
                await self.page.click(
                    f"{row_selector}:nth-child(2)"
                )  # 点击第二行通常是首个数据行
            await self._human_sleep(1)
        except Exception as e:
            log.error(f"❌ 无法调起填报模态框: {e}")
            raise

    async def _fill_input(self, title: str, value: str, dbl_click: bool = False):
        """通用输入框填充逻辑"""
        if not value:
            return
        # 复合定位器寻找对应标题的输入框
        base = f'.dui-modal-content .question:has(.question-title span:has-text("{title}")) .question-content'
        wrapper = f"{base} .Input-module_inputWrapper__pgeTK"

        try:
            el = await self.page.wait_for_selector(wrapper)
            if dbl_click:
                await el.dblclick()
            else:
                await el.click()
            await self._human_sleep(0.3)

            input_el = await el.query_selector("textarea, input")
            if input_el:
                await input_el.fill(value)
            else:
                await self.page.keyboard.press("Control+A")
                await self.page.keyboard.type(value)
        except Exception as e:
            log.warning(f"⚠️ 填充 '{title}' 失败: {e}")

    async def _fill_time(self, title: str, time_str: str):
        """处理时间选择器 (双列滚动)"""
        if not time_str or ":" not in time_str:
            return
        h, m = time_str.split(":")

        trigger = f'.dui-modal-content .question:has(.question-title span:has-text("{title}")) .rc-time-picker .form-time-main'
        await self.page.click(trigger)
        await self.page.wait_for_selector(".rc-time-picker-panel")

        # 小时与分钟定位
        await self.page.click(
            f'.rc-time-picker-panel-select:nth-child(1) li:has-text("{h}")'
        )
        await self.page.click(
            f'.rc-time-picker-panel-select:nth-child(2) li:has-text("{m}")'
        )

        # 强制失焦关闭
        await self.page.keyboard.press("Escape")
        await self._human_sleep(0.5)

    async def _fill_dropdown(self, title: str, option: str):
        """处理下拉菜单"""
        if not option:
            return
        trigger = f'.dui-modal-content .question:has(.question-title span:has-text("{title}")) .dropdown-choice-fill-module_dropdownWrapper__-jSfm'

        await self.page.click(trigger)
        await self._human_sleep(0.5)
        # 寻找对应选项
        item_selector = (
            f'.dropdown-choice-fill-module_dropdownMenuItem__EIDOY:has-text("{option}")'
        )
        try:
            item = await self.page.wait_for_selector(item_selector, timeout=3000)
            await item.click()
        except:
            # 兜底模糊匹配
            await self.page.click(f'text="{option}"')
        await self._human_sleep(0.3)

    async def fill_all(self, data_list: list):
        """循环执行所有条目填报"""
        await self._trigger_modal()

        for i, item in enumerate(data_list):
            log.info(
                f"📑 正在填充条目 [{i+1}/{len(data_list)}]: {item.get('content')[:15]}..."
            )

            # 核心填充
            is_first = i == 0
            await self._fill_input(
                "工作内容", item.get("content", ""), dbl_click=is_first
            )
            await self._fill_input(
                "工作成果", item.get("result", ""), dbl_click=is_first
            )
            await self._fill_time("开始时间", item.get("start_time", ""))
            await self._fill_time("结束时间", item.get("end_time", ""))
            await self._fill_dropdown("工作类型", item.get("type", ""))
            await self._fill_dropdown("业务中心", item.get("project", ""))

            # 重要性 (单选)
            priority = item.get("priority", "")
            if priority:
                await self.page.click(
                    f'.dui-modal-content label:has-text("{priority}")'
                )

            # 换行控制
            if i < len(data_list) - 1:
                # 使用 self.page.click 而不是隐式的 logger
                await self.page.click('.dui-modal-content span:has-text("新增一行")')
                await self._human_sleep(1)

        # 完成弹窗
        await self.page.click('.dui-modal-content button:has-text("完成")')
        await self._human_sleep(2)
        log.info("✨ 数据填充成功，请在浏览器中核对，确保无误后点击页面右下角的【提交】。")

    async def close(self):
        """关闭浏览器与驱动"""
        if self.browser_context:
            await self.browser_context.close()
        if self.playwright:
            await self.playwright.stop()

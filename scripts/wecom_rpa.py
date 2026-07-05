import asyncio
import os
import random
from typing import Any, List
from playwright.async_api import async_playwright
from logger import log
from config import config


class WeComRPA:
    """企业微信自动化填报类"""

    LOGIN_QRCODE_SELECTOR = ".wwLogin_panel_middle .wwLogin_qrcode"

    def __init__(
        self, form_url: str = None, user_data_dir: str = None, feishu_sender=None
    ):
        self.form_url = form_url or os.getenv("WECOM_FORM_URL", "")
        self.feishu_sender = feishu_sender
        # 默认使用脚本同级目录下的隐藏文件夹，避免污染根目录
        default_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".browser_profiles/wecom"
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

        # 模拟运行速度 (0.1~1.0, 越小越快, 默认 0.6)
        raw_speed = os.getenv("WECOM_RPA_SPEED") or config.get("rpa.speed", 0.6)
        try:
            self.speed_val = float(raw_speed)
            if not (0.1 <= self.speed_val <= 1.0):
                self.speed_val = 0.6
        except (ValueError, TypeError):
            self.speed_val = 0.6

        # 计算键盘键入延迟 (ms): speed=1.0 -> 50ms, speed=0.1 -> 5ms (缩短延迟以加快输入速度)
        self.typing_delay = int(self.speed_val * 50)
        self.max_retry = int(config.get("rpa.max_retry", 1))
        self.login_timeout = int(config.get("rpa.login_timeout", 60))

    async def _human_sleep(self, base_delay: float = 1.0):
        """
        模拟真人随机延迟
        :param base_delay: 基础延迟时间(秒)
        """
        # 使用数值倍率进行调整
        delay = base_delay * self.speed_val
        # 增加 20% - 70% 的随机扰动，使动作间隔不固定
        jitter = delay * random.uniform(0.2, 0.7)
        total_delay = delay + jitter
        await asyncio.sleep(total_delay)

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

    async def init_browser(self, headless: bool = False):
        """初始化持久化浏览器环境"""
        # 优先读取环境参数是否开启无头浏览器，默认 false
        env_headless = os.getenv("WECOM_RPA_HEADLESS")
        if env_headless is not None:
            headless = env_headless.lower() == "true"
        else:
            # 兼容普通环境变量 HEADLESS
            env_common_headless = os.getenv("HEADLESS")
            if env_common_headless is not None:
                headless = env_common_headless.lower() == "true"
            else:
                headless = False

        log.info(f"🌐 [RPA] 正在初始化浏览器引擎 (Headless={headless})...")
        self.playwright = await async_playwright().start()
        # 确保目录存在
        os.makedirs(self.user_data_dir, exist_ok=True)

        launch_params = {
            "user_data_dir": self.user_data_dir,
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--start-maximized",
            ],
            "viewport": None,  # 允许浏览器窗口决定实际视口大小
            "no_viewport": True,  # 禁用 Playwright 的默认固定视口缩放
            "slow_mo": int(self.speed_val * 100),
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "ignore_default_args": ["--enable-automation"],
        }

        exec_path = await self._get_executable_path()
        if exec_path:
            launch_params["executable_path"] = exec_path
        else:
            launch_params["channel"] = "chrome"

        self.browser_context = await self.playwright.chromium.launch_persistent_context(
            **launch_params
        )

        self.page = await self.browser_context.new_page()
        # 设置全局超时 (90秒)
        self.page.set_default_navigation_timeout(90000)
        self.page.set_default_timeout(90000)

        # 注册导航事件监听，使用 log.debug 避免控制台杂乱
        def on_nav(frame):
            if frame == self.page.main_frame:
                log.debug(f"📍 [RPA 导航] 页面重定向至: {self.page.url}")

        self.page.on("framenavigated", on_nav)

        # 注入多重反检测脚本
        await self.page.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
            Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) return 'Intel Inc.';
                if (parameter === 37446) return 'Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0';
                return getParameter.apply(this, arguments);
            }; 
        """
        )
        log.info("✅ [RPA] 浏览器启动成功。")

    async def check_health(self) -> bool:
        """
        环境预检：检查是否可以正常访问填报页且已登录
        """
        if not self.form_url:
            log.warning("⚠️ 未配置 WECOM_FORM_URL，跳过预检。")
            return True

        try:
            log.info(f"🔍 [RPA 预检] 正在尝试访问填报页: {self.form_url}")
            await self.page.goto(
                self.form_url, wait_until="domcontentloaded", timeout=30000
            )
            await asyncio.sleep(2)

            qr_selectors = [
                ".dui-snackbar-container.login-dialog",
                ".login-dialog",
                ".wwLogin_panel_middle .wwLogin_qrcode",
                "#login_frame",
                "iframe[src*='login']",
            ]

            for sel in qr_selectors:
                if await self.page.query_selector(sel):
                    log.error(
                        f"❌ [RPA 预检] 检测到登录组件 ({sel})，当前处于未登录状态。"
                    )
                    return False

            target_selector = ".HoverBtn_btn__2ansF, .question-main"
            if await self.page.query_selector(target_selector):
                log.info("✅ [RPA 预检] 成功进入填报页面，环境正常。")
                return True

            log.warning("⚠️ [RPA 预检] 未能检测到填报按钮，尝试等待 5 秒...")
            try:
                await self.page.wait_for_selector(target_selector, timeout=5000)
                log.info("✅ [RPA 预检] 经过等待，填报元素已出现。")
                return True
            except:
                log.error("❌ [RPA 预检] 页面加载异常或结构已变动。")
                return False

        except Exception as e:
            log.error(f"❌ [RPA 预检] 访问发生异常: {e}")
            return False

    async def handle_login(self) -> bool:
        """登录检测与表单访问逻辑"""
        if not self.form_url:
            log.error(f"[RPA] 未配置 form_url，请在 config.yaml 中检查。")
            return False

        log.info(f"[RPA] 正在打开目标链接...")
        await self.page.goto(self.form_url)

        # 1. 检查网络错误并重试
        if not await self._check_and_handle_page_error(max_retries=self.max_retry):
            log.warning(f"[RPA] 页面多次刷新无效，尝试新开一个标签页重新访问...")
            if getattr(self, "page", None):
                try:
                    await self.page.close()
                except Exception:
                    pass
            self.page = await self.browser_context.new_page()
            await self.page.goto(self.form_url)
            await self._human_sleep(3)

            if not await self._check_and_handle_page_error(max_retries=self.max_retry):
                raise Exception("新开标签页后仍然网络请求错误，无法恢复程序")

        await self._human_sleep(3)

        qr_selectors = [
            ".dui-snackbar-container.login-dialog",
            ".login-dialog",
            self.LOGIN_QRCODE_SELECTOR,
            "#login_frame",
            "iframe[src*='login']",
        ]

        start_wait = asyncio.get_event_loop().time()

        while True:
            try:
                # 检查是否超时
                if asyncio.get_event_loop().time() - start_wait > self.login_timeout:
                    log.error(
                        f"⏰ [RPA] 扫码超时 ({self.login_timeout}s)，任务自动失败结束。"
                    )
                    return False

                # 2. 循环检测中也进行网络错误静默检查
                if not await self._check_and_handle_page_error(
                    max_retries=1, silent=True
                ):
                    return False

                # 检查是否存在登录二维码
                qr_code = await self.page.query_selector(self.LOGIN_QRCODE_SELECTOR)
                if qr_code:
                    log.warning("🔑 检测到登录二维码，请手动扫描二维码登录...")

                    # 轮询检测二维码是否消失
                    while await self.page.query_selector(self.LOGIN_QRCODE_SELECTOR):
                        await self._human_sleep(2)
                        if asyncio.get_event_loop().time() - start_wait > self.login_timeout:
                            log.error(f"⏰ [RPA] 扫码超时，任务自动失败结束。")
                            return False
                    log.info("✅ 二维码已消失，登录成功或已跳过。")

                # 检查是否已进入表单内容页
                current_url = self.page.url
                if (
                    "doc.weixin.qq.com/journal" in current_url
                    or "doc.weixin.qq.com/forms/j/" in current_url
                ) and "/error" not in current_url:
                    # 通过页面关键元素确认
                    hover_btn = await self.page.query_selector(
                        ".HoverBtn_btn__2ansF, .question-main"
                    )
                    if hover_btn:
                        log.info(f"🎯 已进入填报页面，环境准备就绪。")
                        return True
                    else:
                        log.debug("[RPA] URL 匹配成功但尚未发现填报元素，继续等待...")
                        await self._human_sleep(2)
                else:
                    log.debug(
                        f"[RPA] 当前 URL: {current_url}，等待页面到达目标区域..."
                    )
                    await self._human_sleep(5)
            except Exception as e:
                if "Execution context was destroyed" in str(e):
                    log.debug("[RPA] 检测到页面跳转导致的上下文切换，正在重试检测...")
                    await self._human_sleep(2)
                else:
                    err_msg = str(e)
                    if (
                        "Target page, context or browser has been closed" in err_msg
                        or "Browser closed" in err_msg
                    ):
                        raise e
                    log.error(f"[RPA] 登录检测发生异常: {e}")
                    await self._human_sleep(5)

    async def _trigger_modal(self):
        """触发填报模态框"""
        # 1. 悬停按钮
        hover_btn = ".HoverBtn_btn__2ansF"
        await self.page.wait_for_selector(hover_btn)
        await self.page.hover(hover_btn)
        await self._human_sleep(1)

        # 2. 点击日期激活
        date_trigger = ".question-main .form-date-main"
        await self.page.click(date_trigger)
        await self._human_sleep(0.5)

        # 3. 点击“今天”
        today_btn = ".rc-calendar-footer-btn"
        await self.page.wait_for_selector(today_btn)
        await self.page.click(today_btn)
        await self._human_sleep(1)

        # 4. 触发逻辑：点击表格行或新增行打开模态框
        row_selector = ".table-area-wrapper tbody .table-body-line-wrapper"
        try:
            # 确保表格区域已加载
            await self.page.wait_for_selector(".table-area-wrapper", timeout=5000)

            # 检测当前表格行数
            rows = await self.page.query_selector_all(row_selector)
            if not rows:
                log.info("[RPA] 检测到表格为空，点击'新增一行'开始填报...")
                await self.page.click(".add-area .add-line-wrapper")
            else:
                log.info("📝 点击现有表格首行开启表单...")
                await self.page.click(f"{row_selector}:nth-child(2)")
            await self._human_sleep(1)
        except Exception as e:
            log.error(f"❌ 无法调起填报模态框: {e}")
            raise

    async def _fill_modal_input(self, title: str, value: str, dbl_click: bool = False):
        """填充模态框内的文本/多行输入框"""
        if not value:
            return
        base_selector = f'.dui-modal-content .question:has(.question-main-content > .question-title > div:first-child span:has-text("{title}")) .question-content'
        wrapper_selector = f"{base_selector} .Input-module_inputWrapper__pgeTK"

        log.debug(f'[RPA] 正在尝试填充 "{title}": {value}')

        try:
            wrapper = await self.page.wait_for_selector(wrapper_selector)
            if dbl_click:
                await wrapper.dblclick()
            else:
                await wrapper.click()
            await self._human_sleep(0.5)

            # 支持标准 input/textarea 以及 contenteditable 属性的 div，大大提高填充速度
            input_element = await wrapper.query_selector("textarea, input, [contenteditable='true']")
            if input_element:
                await input_element.fill(value)
            else:
                await self.page.keyboard.press("Control+A")
                await self.page.keyboard.press("Backspace")
                await self.page.keyboard.type(value, delay=self.typing_delay)
        except Exception as e:
            log.warning(f"⚠️ 填充 '{title}' 失败: {e}")

    async def _fill_modal_time(self, title: str, time_str: str):
        """处理开始/结束时间选择 (双列滚动)"""
        if not time_str or ":" not in time_str:
            return
        hour, minute = time_str.split(":")

        trigger_selector = f'.dui-modal-content .question:has(.question-main-content > .question-title > div:first-child span:has-text("{title}")) .question-content .rc-time-picker .form-time-main'
        log.debug(f'[RPA] 正在设置 "{title}": {time_str}')
        await self.page.click(trigger_selector)

        panel_selector = ".rc-time-picker-panel"
        await self.page.wait_for_selector(panel_selector)

        # 小时与分钟定位
        await self.page.click(
            f'.rc-time-picker-panel-select:nth-child(1) li:has-text("{hour}")'
        )
        await self._human_sleep(0.3)
        await self.page.click(
            f'.rc-time-picker-panel-select:nth-child(2) li:has-text("{minute}")'
        )
        await self._human_sleep(0.3)

        # 强制关闭面板
        await self.page.keyboard.press("Escape")
        await self._human_sleep(0.5)

    async def _fill_modal_dropdown(self, title: str, option_text: str):
        """处理下拉菜单"""
        if not option_text:
            return
        wrapper_selector = f'.dui-modal-content .question:has(.question-main-content > .question-title > div:first-child span:has-text("{title}")) .question-content .dropdown-choice-fill-module_dropdownWrapper__-jSfm span.form-input-affix-wrapper'
        log.debug(f'[RPA] 正在选择下拉项 "{title}": {option_text}')

        try:
            wrapper = await self.page.wait_for_selector(wrapper_selector, timeout=5000)
            await wrapper.click()
            await self._human_sleep(0.8)
        except Exception as e:
            log.warning(f"⚠️ 无法点击下拉框 trigger '{title}': {e}")
            return

        menu_selector = ".dropdown-choice-fill-module_dropdownMenuList__soKw0"
        try:
            await self.page.wait_for_selector(menu_selector, timeout=5000)
        except:
            pass

        item_selector = f'.dropdown-choice-fill-module_dropdownMenuItem__EIDOY:has(.dropdown-choice-fill-module_dropdownMenuItem_text__Nom3Y:has-text("{option_text}"))'

        clicked = False
        try:
            target_item = await self.page.wait_for_selector(item_selector, timeout=2000)
            if target_item:
                await target_item.click()
                clicked = True
        except:
            pass

        # 兜底模糊匹配
        if not clicked:
            try:
                menu_items = await self.page.query_selector_all(
                    'div[class*="dropdownMenuList"] div[class*="dropdownMenuItem_text"]'
                )
                if not menu_items:
                    menu_items = await self.page.query_selector_all(
                        'div[class*="dropdownMenuList"] div[class*="dropdownMenuItem"]'
                    )

                for item in menu_items:
                    text = (await item.inner_text()).strip()
                    if text and (text in option_text or option_text in text):
                        await item.scroll_into_view_if_needed()
                        await self._human_sleep(0.1)
                        await item.click()
                        clicked = True
                        break
            except Exception as e:
                log.debug(f"[RPA] 模糊匹配下拉项出错: {e}")

        if not clicked:
            try:
                await self.page.click(f'text="{option_text}"')
                clicked = True
            except:
                pass

        if not clicked:
            log.warning(f"⚠️ 下拉菜单 '{title}' 无法选中选项 '{option_text}'")
            await self.page.keyboard.press("Escape")
        else:
            await self._human_sleep(0.3)

    async def _fill_modal_choice(self, title: str, choice: str):
        """处理单选组"""
        if not choice:
            return
        container_selector = f'.dui-modal-content .question:has(.question-main-content > .question-title > div:first-child span:has-text("{title}")) .question-content .form-choice-new'
        log.debug(f'[RPA] 正在尝试选择 "{title}": {choice}')

        try:
            container = await self.page.wait_for_selector(container_selector)
            await container.scroll_into_view_if_needed()

            option_selector = f'{container_selector} label:has-text("{choice}"), {container_selector} .choice-fill-module_radioItem_title__D0gAG:has-text("{choice}")'
            target_option = await self.page.wait_for_selector(option_selector)
            await target_option.click()
            await self._human_sleep(0.5)
        except Exception as e:
            log.warning(f"⚠️ 无法选择单选项 '{choice}': {e}")

    async def _click_add_line(self):
        """点击“新增一行”按钮"""
        add_line_btn = '.dui-modal-content .form-subform-fill-footer-pc_action span:has-text("新增一行")'
        try:
            btn = await self.page.wait_for_selector(add_line_btn)
            await btn.click()
        except Exception as e:
            log.error(f"[RPA] 点击“新增一行”失败: {e}")
            raise

    async def _click_finish(self):
        """点击“完成”按钮"""
        finish_btn = '.dui-modal-content .form-subform-fill-panel-pc_submit button .dui-button-container:has-text("完成")'
        try:
            btn = await self.page.wait_for_selector(finish_btn)
            await btn.click()
        except Exception as e:
            log.error(f"[RPA] 点击“完成”失败: {e}")
            raise

    async def _click_submit(self):
        """点击“提交”按钮"""
        submit_btn = '.form-fill-pc .FillFooter_footer__X07QG button:has-text("提交")'
        try:
            btn = await self.page.wait_for_selector(submit_btn)
            await btn.click()
            log.info("[RPA] 提交按钮已点击。")
        except Exception as e:
            log.error(f"[RPA] 点击“提交”失败: {e}")
            raise

    async def _check_and_handle_page_error(
        self, max_retries: int = None, silent: bool = False
    ) -> bool:
        """检查页面是否出现网络请求错误，并尝试刷新"""
        if max_retries is None:
            max_retries = self.max_retry

        retry_count = 0
        error_text = "网络请求错误，请再试一次"

        while retry_count < max_retries:
            try:
                error_msg = await self.page.query_selector(f'text="{error_text}"')
                if error_msg:
                    retry_count += 1
                    log.warning(
                        f"[RPA] 检测到页面报错 '{error_text}' (第 {retry_count} 次)。"
                    )
                    await self.page.goto(self.form_url)
                    await self._human_sleep(5)
                else:
                    return True
            except Exception as e:
                if "Execution context was destroyed" in str(e):
                    return True
                err_msg = str(e)
                if (
                    "Target page, context or browser has been closed" in err_msg
                    or "Browser closed" in err_msg
                ):
                    raise e
                raise

        if not silent:
            log.error(f"[RPA] 页面加载持续失败 (多次重试仍然报错: {error_text})。")
        return False

    async def _cleanup_defect_rows(self):
        """检查并删除表单中的缺陷行（包含 empty-placeholder 的行）"""
        log.info("[RPA] 正在检查并清理表单缺陷行...")

        defect_row_selector = (
            ".table-area-wrapper tr.table-body-line-wrapper:has(.empty-placeholder)"
        )
        trashbin_selector = ".hover-tool-bar .hover-tool-bar-trashbin-wrapper"

        try:
            while True:
                rows = await self.page.query_selector_all(defect_row_selector)
                if not rows:
                    log.info("[RPA] 未发现缺陷行，清理完毕。")
                    break

                for i in range(len(rows) - 1, -1, -1):
                    row = rows[i]
                    await row.scroll_into_view_if_needed()
                    await row.hover()
                    await self._human_sleep(1)

                    trashbin = await self.page.query_selector(trashbin_selector)
                    if trashbin:
                        await trashbin.click()
                        await self._human_sleep(1)

                        confirm_modal_selector = ".dui-modal.form-confirm"
                        confirm_btn_selector = (
                            f"{confirm_modal_selector} .dui-modal-footer-ok"
                        )
                        try:
                            confirm_btn = await self.page.wait_for_selector(
                                confirm_btn_selector, timeout=3000
                            )
                            if confirm_btn:
                                await confirm_btn.click()
                                log.info("[RPA] 已点击“确认”删除缺陷行。")
                                await self._human_sleep(1)
                        except Exception as e:
                            log.warning(f"[RPA] 未检测到删除确认弹窗或点击确认失败: {e}")
                    else:
                        log.warning(
                            "[RPA] 未能找到删除图标，跳过该行。"
                        )
                await self._human_sleep(0.5)
        except Exception as e:
            log.error(f"[RPA] 清理缺陷行时发生异常: {e}")

    async def fill_all(self, data_list: list):
        """执行表单填充逻辑"""
        items = data_list if isinstance(data_list, list) else [data_list]
        if not items:
            log.warning("[RPA] 无可用填报数据。")
            return

        # 1. 触发模态框
        await self._trigger_modal()

        # 2. 循环处理数据记录
        for index, item in enumerate(items):
            log.info(
                f"📑 正在填充条目 [{index + 1}/{len(items)}]: {item.get('content', '')[:20]}..."
            )

            # 等待模态框内容加载
            modal_selector = ".dui-modal-content"
            await self.page.wait_for_selector(modal_selector, timeout=10000)

            # 填充字段 (仅第一条记录使用双击全选覆盖，后续新增行使用单击)
            is_first = index == 0
            await self._fill_modal_input(
                "工作内容", item.get("content", ""), dbl_click=is_first
            )
            await self._fill_modal_input(
                "工作成果", item.get("result", ""), dbl_click=is_first
            )
            await self._fill_modal_time("开始时间", item.get("start_time", ""))
            await self._fill_modal_time("结束时间", item.get("end_time", ""))
            await self._fill_modal_choice("重要性与紧急度", item.get("priority", ""))
            await self._fill_modal_dropdown("工作类型", item.get("type", ""))
            await self._fill_modal_dropdown("业务中心", item.get("project", ""))

            # 循环控制逻辑
            if index < len(items) - 1:
                await self._click_add_line()
                await self._human_sleep(1)
            else:
                log.info("[RPA] 所有条目已填充完毕。")

        # 3. 点击“完成”
        await self._click_finish()
        await self._human_sleep(2)

        # 4. 清理可能存在的缺陷行（空行）
        auto_cleanup = config.get("rpa.auto_cleanup", True)
        if auto_cleanup:
            await self._cleanup_defect_rows()

        # 5. 检查环境参数或配置决定是否点击“提交”
        env_submit = os.getenv("WECOM_RPA_AUTO_SUBMIT")
        if env_submit is not None:
            auto_submit = env_submit.lower() == "true"
        else:
            auto_submit = config.get("rpa.auto_submit", False)

        if auto_submit:
            log.info("[RPA] 检测到 auto_submit=true，执行最终提交...")
            await self._click_submit()
        else:
            log.info("✨ 数据填充成功，请在浏览器中核对，确保无误后点击页面右下角的【提交】。")

    async def close(self):
        """优雅关闭浏览器与驱动资源"""
        try:
            if self.browser_context:
                await self.browser_context.close()
                self.browser_context = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
        except Exception:
            pass

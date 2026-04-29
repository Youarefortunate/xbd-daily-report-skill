import asyncio
import os
import random
from playwright.async_api import async_playwright, Page
from logger import log
from config import config


class WeComRPA:
    """企业微信自动化填报类"""

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

        # 模拟运行速度 (0.1~1.0, 越小越快, 默认 1)
        self.speed_val = float(config.get("rpa.speed", 1))
        # 登录超时时间
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

        # log.debug(f"[RPA] 模拟延迟: {total_delay:.2f}s") # 生产模式下可静默
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

    async def init_browser(self, headless: bool = True):
        """初始化持久化浏览器环境"""
        # 在 GitHub Actions 环境下，如果不手动指定 HEADLESS=false，则默认开启无头模式
        # 但我们现在支持通过 XVFB 运行有头模式，所以移除强制 True 逻辑
        is_ci = os.getenv("GITHUB_ACTIONS") == "true"
        if is_ci and os.getenv("HEADLESS") != "false":
            log.info(
                "🚀 [RPA] 检测到 GitHub Actions 环境且未指定 Headful，默认启用无头模式。"
            )
            headless = True

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
                "--disable-dev-shm-usage",  # 关键：防止 Linux CI 环境下 /dev/shm 空间不足导致页面挂死
                "--disable-gpu",  # 无头模式下通常建议禁用 GPU 加速以减少资源冲突
            ],
            "viewport": {"width": 1280, "height": 800},
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
        }

        # 伪装标准 Chrome User-Agent，移除 HeadlessChrome 标识
        is_headless = headless
        if is_headless:
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            launch_params["user_agent"] = ua
            log.info(f"🕵️ [RPA] 已启用 User-Agent 伪装: {ua[:50]}...")

        # CI 环境策略：不显式指定 channel="chrome"，除非确定环境中有 Google Chrome
        # GitHub Actions 的 ubuntu-latest 通常带有 Chrome，但使用默认的 chromium 更稳。
        if is_ci:
            log.info("ℹ️ 处于 CI 环境，将直接启动 Playwright 默认浏览器...")
        else:
            exec_path = await self._get_executable_path()
            if exec_path:
                launch_params["executable_path"] = exec_path
            else:
                log.info("ℹ️ 未发现本地 Chrome，将通过 Playwright 渠道启动...")
                launch_params["channel"] = "chrome"

        self.browser_context = await self.playwright.chromium.launch_persistent_context(
            **launch_params
        )

        self.page = await self.browser_context.new_page()
        # 设置全局超时 (90秒)
        self.page.set_default_navigation_timeout(90000)
        self.page.set_default_timeout(90000)

        # 注入多重反检测脚本，绕过常规浏览器特征检测
        await self.page.add_init_script(
            """
            // 1. 移除 webdriver 标记
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            // 2. 伪造 chrome 运行对象
            window.chrome = { runtime: {} };
            // 3. 固化语言和平台属性
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
            Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
            // 4. 伪装 WebGL 渲染器信息 (常见检测点)
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
        :return: True 如果一切正常, False 如果需要登录或页面不可用
        """
        if not self.form_url:
            log.warning("⚠️ 未配置 WECOM_FORM_URL，跳过预检。")
            return True

        try:
            log.info(f"🔍 [RPA 预检] 正在尝试访问填报页: {self.form_url}")
            # 预检阶段使用较短的超时
            await self.page.goto(
                self.form_url, wait_until="domcontentloaded", timeout=30000
            )
            await asyncio.sleep(2)

            # 1. 检查是否出现登录组件
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

            # 2. 检查关键填报元素是否存在
            # .HoverBtn_btn__2ansF 是报表的悬浮填报按钮
            target_selector = ".HoverBtn_btn__2ansF"
            if await self.page.query_selector(target_selector):
                log.info("✅ [RPA 预检] 成功进入填报页面，环境正常。")
                return True

            # 3. 兜底逻辑：如果既没有登录框，也没有填报按钮，可能是页面加载不完整
            log.warning("⚠️ [RPA 预检] 未能检测到填报按钮，尝试等待 5 秒...")
            try:
                await self.page.wait_for_selector(target_selector, timeout=5000)
                log.info("✅ [RPA 预检] 经过等待，填报按钮已出现。")
                return True
            except:
                log.error("❌ [RPA 预检] 页面加载异常或结构已变动。")
                return False

        except Exception as e:
            log.error(f"❌ [RPA 预检] 访问发生异常: {e}")
            return False

    async def handle_login(self) -> bool:
        """登录检测与表单访问逻辑"""
        qr_path = os.path.join(os.path.dirname(self.user_data_dir), "login_qr.png")
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                log.info(
                    f"🚀 正在访问表单 {'(重试中...)' if attempt > 0 else ''}: {self.form_url}"
                )
                # 调整为 domcontentloaded 提高在 CI 中的成功率，随后再等待关键元素
                await self.page.goto(
                    self.form_url, wait_until="domcontentloaded", timeout=90000
                )
                break
            except Exception as e:
                if attempt < max_retries:
                    log.warning(f"⚠️ 访问超时，正在进行第 {attempt + 1} 次重试... ({e})")
                    await asyncio.sleep(5)
                    continue
                else:
                    log.error(f"❌ 访问表单最终失败: {e}")
                    raise

        await self._human_sleep(2)

        # 检测需要登录的对话框或二维码
        # 优先使用用户提供的 .login-dialog，因为它包含了完整的登录 UI
        qr_selectors = [
            ".dui-snackbar-container.login-dialog",
            ".login-dialog",
            ".wwLogin_panel_middle .wwLogin_qrcode",
            "#login_frame",
            "iframe[src*='login']",
        ]

        target_element = None
        # --- 增强诊断：监听所有重定向和响应 ---
        qr_buffer = None

        async def on_response(response):
            nonlocal qr_buffer
            # 匹配二维码图片的特征 URL
            if "qr" in response.url.lower() and ("image" in response.headers.get("content-type", "")):
                try:
                    qr_buffer = await response.body()
                    log.info(f"⚡ [RPA] 成功在网络层拦截到二维码图片流: {response.url[:60]}...")
                except:
                    pass

        self.page.on("response", on_response)
        
        def on_nav(frame):
            if frame == self.page.main_frame:
                log.info(f"📍 [RPA 导航] 页面重定向至: {self.page.url}")
        
        self.page.on("framenavigated", on_nav)

        for sel in qr_selectors:
            target_element = await self.page.query_selector(sel)
            if target_element:
                log.info(f"🔍 匹配到登录组件: {sel}")
                break

        if target_element:
            log.warning("🔑 检测到登录入口，请查看飞书推送的二维码并扫码登录！")

            # [GA 适配] 在 CI 环境下（即便开启了 XVFB 有头模式），也需要推送到飞书，因为人工无法直接看到屏幕
            is_headless = getattr(self.browser_context, "_options", {}).get(
                "headless", False
            )
            is_ci = os.getenv("GITHUB_ACTIONS") == "true"
            
            if self.feishu_sender and (is_headless or is_ci):
                try:
                    # 等待一下确保基础渲染完成或拦截到流
                    await asyncio.sleep(5)

                    qr_path = os.path.join(
                        os.path.dirname(self.user_data_dir), "login_qr.png"
                    )
                    
                    if qr_buffer:
                        # 方案 A: 使用拦截到的网络流 (最稳、最快)
                        with open(qr_path, "wb") as f:
                            f.write(qr_buffer)
                        log.info("✅ [RPA] 成功通过网络拦截获取二维码。")
                    else:
                        # 方案 B: 如果拦截失败，尝试深度扫描 Frames
                        log.info("🔍 [RPA] 未截获流，正在深度扫描 Frames...")
                        qr_data = None
                        for frame in self.page.frames:
                            try:
                                qr_data = await frame.evaluate("""
                                    (selectors) => {
                                        for (const sel of selectors) {
                                            const el = document.querySelector(sel);
                                            if (!el) continue;
                                            const img = el.tagName === 'IMG' ? el : el.querySelector('img');
                                            if (img && img.src && (img.src.startsWith('data:image') || img.src.includes('qr'))) {
                                                return img.src;
                                            }
                                        }
                                        return null;
                                    }
                                """, qr_selectors)
                                if qr_data: break
                            except: continue

                        if qr_data and qr_data.startswith("data:image"):
                            import base64
                            header, encoded = qr_data.split(",", 1)
                            with open(qr_path, "wb") as f:
                                f.write(base64.b64decode(encoded))
                            log.info("✅ [RPA] 成功从 Frame 中提取 Base64 二维码。")
                        else:
                            # 方案 C: 最后的倔强 - 无超时截图
                            log.info(f"📸 [RPA] 提取仍失败，尝试零超时全页截图: {qr_path}")
                            await self.page.screenshot(path=qr_path, timeout=60000)

                    image_key = self.feishu_sender.upload_image(qr_path)
                    if image_key:
                        self.feishu_sender.send_qr_code(
                            image_key, title="🔑 企业微信场景登录"
                        )
                    else:
                        log.error("❌ [RPA] 二维码上传失败，流程终止。")
                        return False
                except Exception as e:
                    log.error(f"❌ [RPA] 飞书二维码推送失败 (将终止流程): {e}")
                    # 如果被重定向到了腾讯安全页面，记录一下
                    if "aq.qq.com" in self.page.url:
                        log.error("🛡️ [RPA] 检测到被重定向至腾讯安全风控页，环境可能已被拉黑。")
                    return False
                finally:
                    if os.path.exists(qr_path):
                        try: os.remove(qr_path)
                        except: pass

            # 轮询等待登录状态改变（即登录组件消失）
            log.info(f"⏳ 等待扫码中 (限时 {self.login_timeout}s)...")
            import time

            start_wait = time.time()

            try:
                while True:
                    # 检查是否超时
                    if time.time() - start_wait > self.login_timeout:
                        log.error(
                            f"⏰ [RPA] 扫码超时 ({self.login_timeout}s)，任务自动失败结束。"
                        )
                        return False

                    # 检查登录组件是否仍然存在
                    still_there = any(
                        [await self.page.query_selector(sel) for sel in qr_selectors]
                    )
                    if not still_there:
                        log.info("✅ 登录组件已消失，扫码可能已成功。")
                        break
                    await asyncio.sleep(2)
            finally:
                # 统一清理临时二维码图片（唯一出口）
                if os.path.exists(qr_path):
                    try:
                        os.remove(qr_path)
                        log.info("🧹 已清理临时二维码图片。")
                    except:
                        pass

        # 验证是否进入填报页
        await self._human_sleep(3)  # 给予页面跳转和动态渲染额外缓冲
        try:
            # 增加超时时间到 90s，并提供失败截图
            await self.page.wait_for_selector(".HoverBtn_btn__2ansF", timeout=90000)
            log.info("🎯 已进入填报页面，环境准备就绪。")
            return True
        except Exception as e:
            error_img = os.path.join(
                os.path.dirname(self.user_data_dir), "error_page.png"
            )
            await self.page.screenshot(path=error_img, full_page=True)
            
            # [GA] 记录当前 URL 和 标题，帮助分析是否被重定向到了异常页面
            current_url = self.page.url
            current_title = await self.page.title()
            log.error(f"❌ 未能检测到填报页关键元素: {e}")
            log.error(f"📍 失败时 URL: {current_url}")
            log.error(f"🏷️ 失败时标题: {current_title}")
            log.info(f"📸 已保存错误全屏截图至: {error_img}")

            # [GA] 在 Action 环境下，如果推送了飞书，可以把这张图也推过去方便调试
            if self.feishu_sender and os.getenv("GITHUB_ACTIONS") == "true":
                try:
                    img_key = self.feishu_sender.upload_image(error_img)
                    if img_key:
                        self.feishu_sender.send_text(
                            f"🚨 RPA 填报页加载失败\nURL: {current_url}\nTitle: {current_title}\nError: {e}"
                        )
                except:
                    pass
            return False

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

        # [GA 适配] 在无头模式下自动提交
        # 本地模式下保持原样，方便用户手动复核
        is_headless = await self.page.evaluate(
            "() => !window.chrome || !window.chrome.runtime"
        )
        # 简单判断，或者直接检查 self.browser_context._options['headless']
        # 实际上我们可以在 init_browser 里存一个 self.is_headless

        if os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("HEADLESS") == "true":
            log.info("🚀 [RPA] 检测到静默模式，正在尝试自动点击【提交】按钮...")
            submit_selectors = [
                'button.dui-button-type-primary:has-text("提交")',
                'span:has-text("提交")',
                ".footer-submit-btn",
            ]
            for sel in submit_selectors:
                try:
                    btn = await self.page.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        log.info(f"✅ [RPA] 已触发自动提交 ({sel})")
                        await self._human_sleep(3)
                        break
                except:
                    continue
        else:
            log.info(
                "✨ 数据填充成功，请在浏览器中核对，确保无误后点击页面右下角的【提交】。"
            )

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

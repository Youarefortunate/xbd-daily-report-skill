import os
import json
import asyncio
from dotenv import load_dotenv
from logger import log
from camouflage import camouflage_history_manager
from config import config
from wecom_sender import send_wecom_report
import warnings

# 忽略 asyncio 在 Windows 退出时的常见底层资源警告 (ProactorEventLoop 遗留问题)
warnings.filterwarnings(
    "ignore", category=RuntimeWarning, message=".*Event loop is closed.*"
)
warnings.filterwarnings("ignore", category=ResourceWarning)


def print_raw_commits(commits, fake_items=None):
    if not commits and not fake_items:
        return

    log.info("")
    log.info("  平台: GITLAB")

    # 1. 打印今日真实工作
    if commits:
        grouped_real = {}
        for c in commits:
            p = c.get("project", "未知项目")
            p_name = c.get("project_name", "")
            p_display = f"{p} ({p_name})" if p_name else p
            d_key = c.get("date", "未知日期")[:10]
            grouped_real.setdefault(p_display, {}).setdefault(d_key, []).append(c)

        log.info("    📦 [今日真实工作]")
        for p_display, dates in grouped_real.items():
            log.info(f"    数据源: {p_display}")
            for d_key in sorted(dates.keys(), reverse=True):
                log.info(f"      📅 日期: {d_key}")
                for c in dates[d_key]:
                    # 提取时间
                    time_str = "00:00"
                    try:
                        from datetime import datetime

                        dt = datetime.fromisoformat(
                            c.get("date", "").replace("Z", "+00:00")
                        )
                        time_str = dt.strftime("%H:%M")
                    except:
                        pass
                    log.info(
                        f"        - [{time_str}]({c.get('branch', 'unknown')}) {c.get('title', '')}"
                    )

    # 2. 打印待伪装素材
    if fake_items:
        grouped_fake = {}
        for item in fake_items:
            p_display = f"{item.source} ({item.repo_path})"
            d_key = item.date or "未知日期"
            grouped_fake.setdefault(p_display, {}).setdefault(d_key, []).append(item)

        log.info("    🎭 [待伪装素材 - GITLAB]")
        for p_display, dates in grouped_fake.items():
            log.info(f"      数据源: {p_display}")
            for d_key in sorted(dates.keys(), reverse=True):
                log.info(f"        📅 日期: {d_key}")
                for item in dates[d_key]:
                    log.info(f"          - {item.content}")
    log.info("")


def print_polished_report(report_items):
    if not report_items:
        return

    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")

    log.info(f"  📊 [每日工作总结-AI润色] (日期: {today})")
    for item in report_items:
        log.info(f"    - {item.get('content', '无')}")
        log.info(f"        └─ 成果: {item.get('result', '无')}100%")
        # 构造详情行
        start = item.get("start_time", "09:00")
        end = item.get("end_time", "18:00")
        priority = item.get("priority", "普通")
        p_emoji = "🔴" if "重要" in priority else "🟢"
        type_str = item.get("type", "编码")
        project = item.get("project", "核心")

        details = (
            f"🕒 {start}~{end} | {p_emoji} {priority} | 🏷️ {type_str} | 🏢 {project}"
        )
        log.info(f"        └─ 详情: {details}")
        log.info("")


async def is_github_actions_environment() -> bool:
    """步骤 0: 是否为Github Actions环境，并判断今日是否需要执行"""
    is_headless = os.getenv("HEADLESS", "false").lower() == "true"
    if is_headless:
        weekdays_config = str(config.get("scheduler.weekdays", "1,2,3,4,5"))
        if weekdays_config:
            from datetime import datetime

            # weekday() 返回 0-6 (周一至周日)，转换为 1-7 对应配置
            current_day = str(datetime.now().weekday() + 1)
            allowed_days = [d.strip() for d in weekdays_config.split(",") if d.strip()]
            if current_day not in allowed_days:
                log.info(
                    f"📅 [跳过] 静默模式检测到今日 (周{current_day}) 不在预设工作日 [{weekdays_config}] 内，程序已停止。"
                )
                return False
    return True


async def rpa_health_check():
    """步骤 0.5: RPA 环境预检 (提前启动浏览器检查)"""
    from wecom_rpa import WeComRPA
    from feishu_sender import FeishuSender

    feishu = FeishuSender()
    # 临时检查是否启用飞书，用于 RPA 推送二维码
    feishu_enabled = (
        all([feishu.app_id, feishu.app_secret, feishu.target_chat_id])
        and "xxx" not in feishu.app_id
    )

    rpa = WeComRPA(feishu_sender=feishu if feishu_enabled else None)
    is_headless = os.getenv("HEADLESS", "false").lower() == "true"

    if rpa.form_url:
        log.info("🔍 [预检] 正在进行 RPA 运行环境检查...")
        try:
            await rpa.init_browser(headless=is_headless)
            # handle_login 会检测是否需要扫码，并在 CI 环境下推送到飞书
            if not await rpa.handle_login():
                log.error(
                    "❌ [预检] RPA 环境异常（扫码超时或页面不可用），已提前终止流程以节省资源。"
                )
                await rpa.close()
                return None, None, False
        except Exception as e:
            log.error(f"❌ [预检] RPA 初始化失败: {e}，流程终止。")
            await rpa.close()
            return None, None, False
    else:
        log.info("ℹ️ 未配置 WECOM_FORM_URL，跳过 RPA 预检。")
        rpa = None

    return rpa, feishu, feishu_enabled


async def collect_data(repo_configs):
    """步骤 1: 采集 GitLab 数据与飞书动态指令"""
    from gitlab_collector import GitLabCollector
    from feishu_sender import FeishuSender

    collector = GitLabCollector()
    commits = collector.run(repo_configs)

    # 1.3 伪装数据补全
    camouflage_threshold = int(config.get("camouflage.threshold", 8))
    fake_items = []
    if len(commits) < camouflage_threshold:
        needed = camouflage_threshold - len(commits)
        fake_items = collector.generate_camouflage_data(
            repo_configs,
            needed,
            lookback_days=int(config.get("camouflage.lookback", 14)),
            cooldown_days=int(config.get("camouflage.cooldown", 10)),
        )

    print_raw_commits(commits, fake_items=fake_items)

    # 1.5 从飞书拉取额外补报
    feishu = FeishuSender()
    log.info("📡 正在检查飞书实时指令...")
    feishu_extra = feishu.fetch_extra_work()

    return commits, fake_items, feishu_extra


async def polish_report(commits, fake_items, feishu_extra, extra_path, prompt_path):
    """步骤 2: AI 润色处理"""
    from ai_processor import AIProcessor

    processor = AIProcessor()
    report_items = await processor.process(
        git_commits=commits,
        extra_report_path=extra_path,
        system_prompt_path=prompt_path,
        fake_items=fake_items,
        extra_report_items=feishu_extra,
    )
    return report_items


async def send_to_feishu(report_items, fake_items, feishu=None):
    """步骤 3: 飞书推送日报卡片"""
    from feishu_sender import FeishuSender

    if not feishu:
        feishu = FeishuSender()

    feishu_enabled = (
        all([feishu.app_id, feishu.app_secret, feishu.target_chat_id])
        and "xxx" not in feishu.app_id
    )

    if feishu_enabled:
        log.info("\n🚀 正在推送精致日报卡片至飞书...")
        card = feishu.build_daily_report_card(report_items)
        if feishu.send(card):
            # 只有发送成功才更新伪装素材使用记录
            if fake_items:
                log.info(
                    f"💾 [伪装] 任务成功，正在为 {len(fake_items)} 个素材更新记录..."
                )
                variant = json.dumps(report_items, ensure_ascii=False)
                for item in fake_items:
                    camouflage_history_manager.update_usage(item, variant)

    return feishu, feishu_enabled


async def fill_rpa(report_items, feishu, feishu_enabled, rpa=None):
    """步骤 4: 企业微信 RPA 填报"""
    from wecom_rpa import WeComRPA

    # 允许在 GH Actions 下运行 RPA，前提是配置了飞书以便推送二维码
    is_ci = os.getenv("GITHUB_ACTIONS") == "true"
    if is_ci and not feishu_enabled:
        log.info(
            "\nℹ️ 提示: 检测到 GitHub Actions 环境但未配置飞书推送，自动跳过 RPA 填报。"
        )
        return

    # 如果没有传入预检好的 rpa 对象，则在此初始化
    if not rpa:
        rpa = WeComRPA(feishu_sender=feishu if feishu_enabled else None)

    if not rpa.form_url:
        log.info("\nℹ️ 提示: 未配置 WECOM_FORM_URL，跳过 RPA 自动填报。")
        return

    log.info("\n🚀 正在启动企业微信 RPA 自动填报...")
    is_headless = os.getenv("HEADLESS", "false").lower() == "true"
    try:
        # 如果 rpa 已经初始化过（通过预检），则跳过 init_browser
        if not rpa.page:
            await rpa.init_browser(headless=is_headless)

        if await rpa.handle_login():
            await rpa.fill_all(report_items)
            if not is_headless:
                log.info("⏳ 填报完成，浏览器将保持开启 5 分钟以便人工核对。")
                await asyncio.sleep(300)
            else:
                log.info("✨ 无头模式填报完成，直接退出。")
    except Exception as e:
        err_msg = str(e)
        if "Target page, context or browser has been closed" in err_msg:
            log.info("\n👋 [RPA] 检测到浏览器窗口已手动关闭，正在退出流程。")
        else:
            log.error(f"❌ RPA 填报环节发生异常: {e}")
    finally:
        try:
            await rpa.close()
        except:
            pass


async def run_daily_bot():
    """主编排逻辑"""
    # 0. 准入检查 (已注释：不再需要 GitHub Actions 环境限制)
    # if not await is_github_actions_environment():
    #     return

    log.info("🎬 [系统] 开始执行日报生成流水线...")
    load_dotenv()

    current_dir = os.path.dirname(os.path.abspath(__file__))
    extra_path_val = config.get("extra_report_path", "extra_report.txt")
    extra_path = os.path.join(current_dir, extra_path_val)
    prompt_path = os.path.normpath(
        os.path.join(current_dir, "..", "references", "system_prompt.md")
    )

    # 0.5 RPA 环境预检 (已注释：已改为 HTTP 直推方式)
    # rpa, feishu, feishu_enabled = await rpa_health_check()
    # if rpa is None and config.get("wecom.form_url"):
    #     return

    from feishu_sender import FeishuSender

    feishu = FeishuSender()
    feishu_enabled = (
        all([feishu.app_id, feishu.app_secret, feishu.target_chat_id])
        and "xxx" not in feishu.app_id
    )

    # 1. 采集数据
    commits, fake_items, feishu_extra = await collect_data(config.gitlab_repos)

    # 2. AI 润色
    report_items = await polish_report(
        commits, fake_items, feishu_extra, extra_path, prompt_path
    )

    if not report_items:
        log.warning("⚠️ 提示: 没有生成任何日报条目，终止后续流程。")
        # if rpa: await rpa.close()
        return

    print_polished_report(report_items)

    # 3. 飞书推送
    feishu, feishu_enabled = await send_to_feishu(
        report_items, fake_items, feishu=feishu
    )

    # 4. 企业微信表单推送
    send_wecom_report(report_items)

    # 4. 企业微信 RPA (已注释，改为上面的 HTTP 直推方式)
    # await fill_rpa(report_items, feishu, feishu_enabled, rpa=rpa)


if __name__ == "__main__":
    try:
        asyncio.run(run_daily_bot())
    except KeyboardInterrupt:
        log.warning("\n👋 用户终止运行。")
    except Exception as e:
        err_msg = str(e)
        # 再次拦截可能冒泡到顶层的浏览器关闭错误
        if "Target page, context or browser has been closed" in err_msg:
            log.info("\n👋 任务已由用户手动关闭窗口结束。")
        else:
            log.error(f"\n❌ 程序非正常退出: {e}")

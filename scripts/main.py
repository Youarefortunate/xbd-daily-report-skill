import os
import json
import argparse
import asyncio
from dotenv import load_dotenv
from logger import log
from camouflage import camouflage_history_manager
from config import config
from wecom_sender import send_wecom_report
from report_printer import print_raw_commits, print_polished_report
import warnings

# 忽略 asyncio 在 Windows 退出时的常见底层资源警告 (ProactorEventLoop 遗留问题)
warnings.filterwarnings(
    "ignore", category=RuntimeWarning, message=".*Event loop is closed.*"
)
warnings.filterwarnings("ignore", category=ResourceWarning)


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


async def collect_data(repo_configs, camouflage_enabled=True):
    """步骤 1: 采集 GitLab 数据与飞书动态指令"""
    from gitlab_collector import GitLabCollector
    from feishu_sender import FeishuSender

    collector = GitLabCollector()
    commits = collector.run(repo_configs)

    # 1.3 伪装数据补全
    camouflage_threshold = int(config.get("camouflage.threshold", 8))
    fake_items = []
    if camouflage_enabled and len(commits) < camouflage_threshold:
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


def _env_bool(env_key: str, default: bool) -> bool:
    """从环境变量读取布尔值，用于 argparse default。"""
    val = os.getenv(env_key, "")
    if val == "":
        return default
    return val.lower() == "true"


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """为子命令添加通用可选参数，均支持环境变量作为默认值。"""
    parser.add_argument(
        "--feishu",
        action="store_true",
        default=_env_bool("DAILYBOT_FEISHU_ENABLED", False),
        help="启用飞书推送（默认关闭，通过 DAILYBOT_FEISHU_ENABLED 环境变量控制）",
    )
    parser.add_argument(
        "--no-camouflage",
        action="store_true",
        default=not _env_bool("DAILYBOT_CAMOUFLAGE_ENABLED", True),
        help="禁用伪装数据补全（默认开启，通过 DAILYBOT_CAMOUFLAGE_ENABLED 环境变量控制）",
    )
    parser.add_argument(
        "--extra-report",
        default=os.getenv("DAILYBOT_EXTRA_REPORT_PATH", "extra_report.txt"),
        help="额外补充日报文件路径（默认 extra_report.txt）",
    )


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器，支持 rpa / push 两种子命令。"""
    parser = argparse.ArgumentParser(description="日报生成流水线")
    subparsers = parser.add_subparsers(dest="mode")

    rpa_parser = subparsers.add_parser("rpa", help="RPA 浏览器自动化填报（默认模式）")
    _add_common_args(rpa_parser)

    push_parser = subparsers.add_parser("push", help="一键 API 推送至企业微信")
    _add_common_args(push_parser)

    # 在 subparsers 之后设置默认值，以防其被覆盖，并为没有指定子命令直接运行时的参数提供默认值
    parser.set_defaults(
        mode="rpa",
        feishu=_env_bool("DAILYBOT_FEISHU_ENABLED", False),
        no_camouflage=not _env_bool("DAILYBOT_CAMOUFLAGE_ENABLED", True),
        extra_report=os.getenv("DAILYBOT_EXTRA_REPORT_PATH", "extra_report.txt"),
    )

    return parser


async def run_daily_bot(args: argparse.Namespace):
    """主编排逻辑 — 通过 argparse + 环境变量控制运行模式"""
    log.info("🎬 [系统] 开始执行日报生成流水线...")
    load_dotenv()

    mode = args.mode or "rpa"
    feishu_push_enabled = args.feishu
    camouflage_enabled = not args.no_camouflage
    extra_report_filename = args.extra_report

    current_dir = os.path.dirname(os.path.abspath(__file__))
    extra_path = os.path.join(current_dir, extra_report_filename)
    prompt_path = os.path.normpath(
        os.path.join(current_dir, "..", "references", "system_prompt.md")
    )

    # 1. 采集数据
    commits, fake_items, feishu_extra = await collect_data(
        config.gitlab_repos, camouflage_enabled=camouflage_enabled
    )

    # 2. AI 润色
    report_items = await polish_report(
        commits, fake_items, feishu_extra, extra_path, prompt_path
    )

    if not report_items:
        log.warning("⚠️ 提示: 没有生成任何日报条目，终止后续流程。")
        return

    print_polished_report(report_items)

    # 3. 飞书推送（默认关闭，需 --feishu 或 DAILYBOT_FEISHU_ENABLED=true 才会推送）
    if feishu_push_enabled:
        await send_to_feishu(report_items, fake_items)
    else:
        log.info(
            "ℹ️ [飞书] 推送已禁用（使用 --feishu 或 DAILYBOT_FEISHU_ENABLED=true 可开启）"
        )

    # 4. 根据模式推送企业微信
    if mode == "push":
        log.info("\n🚀 [一键推送] 正在直接推送至企业微信...")
        send_wecom_report(report_items)
    else:
        log.info(f"\n🤖 [RPA 模式] 当前模式: {mode}")
        await fill_rpa(report_items, feishu=None, feishu_enabled=False, rpa=None)


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(run_daily_bot(args))
    except KeyboardInterrupt:
        log.warning("\n👋 用户终止运行。")
    except Exception as e:
        err_msg = str(e)
        if "Target page, context or browser has been closed" in err_msg:
            log.info("\n👋 任务已由用户手动关闭窗口结束。")
        else:
            log.error(f"\n❌ 程序非正常退出: {e}")

import os
import json
import asyncio
from dotenv import load_dotenv
from logger import log
from camouflage import camouflage_history_manager


def load_repo_configs():
    """从环境变量加载 GitLab 仓库配置"""
    configs = []
    i = 0
    while True:
        path = os.getenv(f"GITLAB_REPO_{i}_PATH")
        if not path:
            break

        branches_str = os.getenv(f"GITLAB_REPO_{i}_BRANCH", "")
        branches = [b.strip() for b in branches_str.split(",") if b.strip()]
        date_range = os.getenv(f"GITLAB_REPO_{i}_DATE_RANGE")

        name = os.getenv(f"GITLAB_REPO_{i}_NAME", "")
        configs.append(
            {
                "path": path,
                "branches": branches,
                "date_range": date_range,
                "name": name,
            }
        )
        i += 1
    return configs


def print_raw_commits(commits, fake_items=None):
    """按项目分组打印原始采集到的素材预览 (深度复刻 04-07 风格)"""
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
                        dt = datetime.fromisoformat(c.get("date", "").replace("Z", "+00:00"))
                        time_str = dt.strftime("%H:%M")
                    except: pass
                    log.info(f"        - [{time_str}]({c.get('branch', 'unknown')}) {c.get('title', '')}")

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
    """深度复刻 04-07 AI 润色报告样式 (2-4-8 缩进)"""
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

        details = f"🕒 {start}~{end} | {p_emoji} {priority} | 🏷️ {type_str} | 🏢 {project}"
        log.info(f"        └─ 详情: {details}")
        log.info("")


async def run_daily_bot():
    # 0. 环境初始化
    log.info("🎬 [系统] 开始执行日报生成流水线...")
    load_dotenv()
    
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # 获取动态路径配置
    extra_path = os.path.join(
        current_dir, os.getenv("EXTRA_REPORT_PATH", "extra_report.txt")
    )
    prompt_path = os.path.normpath(
        os.path.join(current_dir, "..", "references", "system_prompt.md")
    )

    # 1. 采集 GitLab 数据
    from gitlab_collector import GitLabCollector

    repo_configs = load_repo_configs()
    collector = GitLabCollector()
    commits = collector.run(repo_configs)
    
    # [伪装技能] 检查是否需要补全素材
    fake_items = []
    # 阈值配置（可以后续移至 .env）
    threshold = int(os.getenv("CAMOUFLAGE_THRESHOLD", "3"))
    if len(commits) < threshold:
        needed = threshold - len(commits)
        fake_items = collector.generate_camouflage_data(
            repo_configs, 
            needed_count=needed,
            lookback_days=int(os.getenv("CAMOUFLAGE_LOOKBACK", "14")),
            cooldown_days=int(os.getenv("CAMOUFLAGE_COOLDOWN", "10"))
        )

    print_raw_commits(commits, fake_items=fake_items)

    # 1.5 从飞书拉取额外补报
    from feishu_sender import FeishuSender
    feishu = FeishuSender()
    log.info("📡 正在检查飞书实时指令...")
    feishu_extra = feishu.fetch_extra_work()

    # 2. AI 润色处理
    from ai_processor import AIProcessor

    processor = AIProcessor()
    report_items = await processor.process(
        git_commits=commits,
        extra_report_path=extra_path,
        system_prompt_path=prompt_path,
        fake_items=fake_items,
        extra_report_items=feishu_extra
    )

    if not report_items:
        log.warning("⚠️ 提示: 没有生成任何日报条目，终止后续流程。")
        return

    print_polished_report(report_items)

    # 3. 飞书发送
    from feishu_sender import FeishuSender
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
                log.info(f"💾 [伪装] 任务成功，正在为 {len(fake_items)} 个素材更新记录...")
                # 将整个 AI 润色结果作为变体参考记录
                variant = json.dumps(report_items, ensure_ascii=False)
                for item in fake_items:
                    camouflage_history_manager.update_usage(item, variant)

    # 4. 企业微信 RPA 填报
    from wecom_rpa import WeComRPA
    
    # 允许在 GH Actions 下运行 RPA，前提是配置了飞书以便推送二维码
    is_ci = os.getenv("GITHUB_ACTIONS") == "true"
    if is_ci and not feishu_enabled:
        log.info("\nℹ️ 提示: 检测到 GitHub Actions 环境但未配置飞书推送，自动跳过 RPA 填报。")
        return

    rpa = WeComRPA(feishu_sender=feishu if feishu_enabled else None)
    if rpa.form_url:
        log.info("\n🚀 正在启动企业微信 RPA 自动填报...")
        # 从环境变量读取 HEADLESS 配置，默认 False（本地有头），CI 环境下通常为 True
        is_headless = os.getenv("HEADLESS", "false").lower() == "true"
        try:
            await rpa.init_browser(headless=is_headless)
            if await rpa.handle_login():
                await rpa.fill_all(report_items)
                if not is_headless:
                    log.info("⏳ 填报完成，浏览器将保持开启 5 分钟以便人工核对。")
                    await asyncio.sleep(300)
                else:
                    log.info("✨ 无头模式填报完成，直接退出。")
        except Exception as e:
            log.error(f"❌ RPA 填报环节发生异常: {e}")
        finally:
            await rpa.close()
    else:
        log.info("\nℹ️ 提示: 未配置 WECOM_FORM_URL，跳过 RPA 自动填报。")


if __name__ == "__main__":
    try:
        asyncio.run(run_daily_bot())
    except KeyboardInterrupt:
        log.warning("\n👋 用户终止运行。")
    except Exception as e:
        log.error(f"\n❌ 程序非正常退出: {e}")

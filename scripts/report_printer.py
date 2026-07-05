"""日报数据 / 润色结果终端打印模块。"""

from datetime import datetime
from logger import log


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
                    time_str = "00:00"
                    try:
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

    today = datetime.now().strftime("%Y-%m-%d")

    log.info(f"  📊 [每日工作总结-AI润色] (日期: {today})")
    for item in report_items:
        log.info(f"    - {item.get('content', '无')}")
        log.info(f"        └─ 成果: {item.get('result', '无')}100%")
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

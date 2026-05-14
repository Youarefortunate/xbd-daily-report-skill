import os
import json
import datetime
import requests
from logger import log


PRIORITY_OPTION_MAP = {
    "重要、紧急": "1",
    "重要、不紧急": "2",
    "不重要、紧急": "3",
    "不重要、不紧急": "4",
}

PROJECT_OPTION_MAP = {
    "产权平台大屏": "1",
    "村财": "2",
    "监管平台": "3",
    "清产核资": "4",
    "农融易": "5",
    "企财": "6",
    "村（居）委财务系统": "7",
    "村务易": "8",
    "管理费用": "9",
    "其它": "10",
}

TYPE_OPTION_MAP = {
    "需求评审会议": "1",
    "需求分析": "2",
    "系统设计": "3",
    "文档编写": "4",
    "需求沟通会议": "5",
    "编码": "6",
    "联调": "7",
    "BUG修订": "8",
    "数据对接联调": "9",
    "运营协助": "10",
    "编写测试用例": "11",
    "部署测试环境": "12",
    "测试BUG验证": "13",
    "公司会议": "14",
    "外部沟通会议": "15",
    "部门会议": "16",
    "人才储备工作": "17",
    "小组会议": "18",
    "研发基线统计": "19",
    "产研状态统计": "20",
    "问题排查": "21",
    "系统发布": "22",
    "系统维护": "23",
    "内部培训": "24",
    "团队建设": "25",
    "其它工作": "26",
}


def _get_state_file_path():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(current_dir, "logs", ".wecom_submit_state.json")


def _load_submit_state():
    state_path = _get_state_file_path()
    if os.path.exists(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_submit_state(state):
    state_path = _get_state_file_path()
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def _get_submit_type():
    if os.getenv("GITHUB_ACTIONS") == "true":
        log.info("    🤖 CI 环境")
        return "8"

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    state = _load_submit_state()
    last_date = state.get("last_submit_date", "")

    if last_date != today:
        state["last_submit_date"] = today
        state["submit_count_today"] = 1
        _save_submit_state(state)
        log.info("    📝 今日首次提交")
        return "8"

    count = state.get("submit_count_today", 0) + 1
    state["submit_count_today"] = count
    _save_submit_state(state)
    log.info(f"    📝 今日第 {count} 次提交")
    return "9"


def _parse_cookie_string(cookie_str):
    """将 cookie 字符串解析为 dict"""
    cookies = {}
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            key, _, value = item.partition("=")
            cookies[key.strip()] = value.strip()
    return cookies


def convert_to_form_tasks(report_items):
    tasks = []
    for item in report_items:
        task_type = item.get("type", "其它工作")
        priority = item.get("priority", "不重要、不紧急")
        project = item.get("project", "其它")

        task = {
            "items": [
                {
                    "question_id": "2",
                    "text_reply": item.get("content", ""),
                },
                {
                    "question_id": "10",
                    "text_reply": item.get("result", ""),
                },
                {
                    "question_id": "8",
                    "text_reply": item.get("start_time", "09:00"),
                },
                {
                    "question_id": "9",
                    "text_reply": item.get("end_time", "18:00"),
                },
                {
                    "question_id": "1",
                    "option_reply": [PRIORITY_OPTION_MAP.get(priority, "4")],
                },
                {
                    "question_id": "12",
                    "option_reply": [TYPE_OPTION_MAP.get(task_type, "26")],
                },
                {
                    "question_id": "11",
                    "option_reply": [PROJECT_OPTION_MAP.get(project, "10")],
                },
            ]
        }
        tasks.append(task)
    return tasks


def submit_daily_report(tasks):
    cookie_str = os.getenv("WECOM_COOKIE", "")
    if not cookie_str:
        log.error("❌ 未配置 WECOM_COOKIE 环境变量，跳过企业微信提交。")
        return False

    cookies = _parse_cookie_string(cookie_str)
    sid = cookies.get("wedoc_sid", "")

    headers = {
        "authority": "doc.weixin.qq.com",
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9",
        "origin": "https://doc.weixin.qq.com",
        "referer": "https://doc.weixin.qq.com/forms/j/AEoAdAfTAA8AZIAWgZUAEUCNWiktTWA0j_fork?journaluuid=AHb2T7dGzUo1N2TbUqyn42V92VRp3tRD8Qe25LD5mC5g1daA5sVPqVGdpNDNP2U8tJ&template_id=3WN6ibh95xy8vSQ6VfPTgDo5AyaWvGUf2JMqrHzd",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    url = "https://doc.weixin.qq.com/formcol/answer_page"
    params = {
        "sid": sid,
        "wedoc_xsrf": "1",
    }

    today_date = datetime.datetime.now().strftime("%Y年%m月%d日")

    form_reply = {
        "items": [
            {"question_id": "1", "text_reply": today_date},
            {"question_id": "2", "table_replys": tasks},
        ]
    }

    submit_type = _get_submit_type()

    files = {
        "form_id": (None, "AEoAdAfTAA8AZIAWgZUAEUCNAMTNLUG6j_base"),
        "form_reply": (None, json.dumps(form_reply, ensure_ascii=False)),
        "type": (None, submit_type),
        "check_setting": (None, '{"can_anonymous":2}'),
        "use_anonymous": (None, "false"),
        "submit_again": (None, "true"),
        "wwjournal_data": (
            None,
            '{"entry":{"mngreporter":[{"vid":"1688858256245493"},{"vid":"1688858005714619"},{"vid":"1688857251600180"}],"reporter":[],"templateid":"3WN6ibh95xy8vSQ6VfPTgDo5AyaWvGUf2JMqrHzd","doc_info":{"type":2,"form_id":"AEoAdAfTAA8AZIAWgZUAEUCNAMTNLUG6j_base","template_id":"3WN6ibh95xy8vSQ6VfPTgDo5AyaWvGUf2JMqrHzd"}}}',
        ),
        "isSendToRoom": (None, "false"),
        "f": (None, "json"),
    }

    try:
        response = requests.post(
            url, headers=headers, cookies=cookies, params=params, files=files
        )
        response.raise_for_status()
        log.info(f"✅ [{today_date}] 日报提交成功！")
        log.info(f"   服务器返回: {response.text}")
        return True
    except Exception as e:
        log.error(f"❌ [{today_date}] 日报提交失败: {str(e)}")
        return False


def send_wecom_report(report_items):
    """将 AI 润色后的日报推送到企业微信表单（主线入口）"""
    if not report_items:
        log.warning("⚠️ 没有日报条目，跳过企业微信推送。")
        return False

    log.info(f"\n📋 正在推送日报至企业微信表单 (共 {len(report_items)} 条)...")
    tasks = convert_to_form_tasks(report_items)
    return submit_daily_report(tasks)

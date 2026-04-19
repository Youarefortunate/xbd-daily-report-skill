import os
import json
from curl_cffi import requests
from datetime import datetime
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class WeComJournalSender:
    """
    企业微信日报提交流转类 (使用 curl_cffi 模拟浏览器指纹)
    通过逆向请求方式直接提交日报，跳过 RPA 模拟，支持 TLS 指纹伪装
    """

    def __init__(self):
        self.cookie = os.getenv("WECOM_COOKIE")
        self.sid = os.getenv("WECOM_SID")
        self.xsrf = os.getenv("WECOM_XSRF")
        self.form_url = os.getenv("WECOM_FORM_URL")
        
        if not all([self.cookie, self.sid, self.xsrf, self.form_url]):
            raise ValueError("请确保 .env 中配置了 WECOM_COOKIE, WECOM_SID, WECOM_XSRF 和 WECOM_FORM_URL")

        # 使用 curl_cffi 的 Session 并模拟 Chrome 浏览器指纹
        self.session = requests.Session(impersonate="chrome110")
        self.headers = {
            'authority': 'doc.weixin.qq.com',
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'cache-control': 'no-cache',
            'pragma': 'no-cache',
            'cookie': self.cookie,
            'origin': 'https://doc.weixin.qq.com',
            'sec-ch-ua': '"Microsoft Edge";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
        }

    def get_redirect_info(self):
        """
        第一步：访问初始配置的日报链接，获取重定向后的 Location 和动态参数
        """
        import re
        resp = self.session.get(self.form_url, headers=self.headers, allow_redirects=False)
        location = self.form_url
        if resp.status_code == 302:
            location = resp.headers.get('Location')
            print(f"成功获取重定向地址: {location}")
        
        # 提取 form_id
        form_id = None
        form_id_match = re.search(r'/forms/j/([^?&]+)', location)
        if form_id_match:
            form_id = form_id_match.group(1)
            print(f"提取到动态 Form ID: {form_id}")
        
        # 提取 journaluuid
        journal_uuid = None
        uuid_match = re.search(r'journaluuid=([^&]+)', location)
        if uuid_match:
            journal_uuid = uuid_match.group(1)
            print(f"提取到 Journal UUID: {journal_uuid}")

        return {
            "url": location,
            "form_id": form_id,
            "journal_uuid": journal_uuid
        }

    def build_form_reply(self, date_str: str, report_items: list):
        """
        核心数据构造逻辑
        :param date_str: 格式 yyyy年MM月dd日
        :param report_items: 列表，每个元素包含工作详情
        """
        table_replys = []
        for item in report_items:
            table_replys.append({
                "items": [
                    {"question_id": "2", "text_reply": item.get('content', '')},
                    {"question_id": "10", "text_reply": item.get('result', '')},
                    {"question_id": "8", "text_reply": item.get('start_time', '09:00')},
                    {"question_id": "9", "text_reply": item.get('end_time', '18:00')},
                    {"question_id": "1", "option_reply": [str(item.get('priority', '2'))]},
                    {"question_id": "12", "option_reply": [str(item.get('work_type', '6'))]},
                    {"question_id": "11", "option_reply": [str(item.get('center', '6'))]}
                ]
            })

        return {
            "items": [
                {"question_id": "1", "text_reply": date_str},
                {
                    "question_id": "2",
                    "table_replys": table_replys
                }
            ]
        }

    def submit(self, report_data: dict):
        """
        执行提交操作
        :param report_data: 包含 items, mngreporters, form_id 等信息的字典
        """
        # 1. 获取重定向信息和动态参数
        info = self.get_redirect_info()
        self.headers['referer'] = info['url']
        
        # 优先使用动态提取的 form_id
        form_id = info['form_id'] or report_data.get('form_id', "AEoAdAfTAA8AZIAWgZUAEUCNAMTNLUG6j_base")
        template_id = report_data.get('template_id', "3WN6ibh95xy8vSQ6VfPTgDo5AyaWvGUf2JMqrHzd")
        journal_uuid = info['journal_uuid']

        # 2. 构造数据
        date_str = report_data.get('date', datetime.now().strftime("%Y年%m月%d日"))
        form_reply = self.build_form_reply(date_str, report_data.get('items', []))
        
        wwjournal_data = {
            "entry": {
                "mngreporter": report_data.get('mngreporters', []),
                "reporter": [],
                "templateid": template_id,
                "doc_info": {
                    "type": 2,
                    "form_id": form_id,
                    "template_id": template_id
                }
            }
        }
        
        # 如果获取到了 journal_uuid，也可以考虑加入（根据逆向观测，有时在 outer 层面有这个词）
        # 这里暂时保持用户提供的基本结构，但确保 form_id 是对的

        # 3. 构造 Payload 字典
        payload = {
            'form_id': form_id,
            'form_reply': json.dumps(form_reply, ensure_ascii=False),
            'type': str(report_data.get('type', 8)),
            'check_setting': '{"can_anonymous":2}',
            'use_anonymous': 'false',
            'submit_again': 'true',
            'wwjournal_data': json.dumps(wwjournal_data, ensure_ascii=False),
            'isSendToRoom': 'false',
            'f': 'json'
        }
        
        # 如果存在 journal_uuid，补充到 payload 中（部分版本需要）
        if journal_uuid:
            payload['journaluuid'] = journal_uuid

        # 4. 构造 Multipart 报文（curl_cffi 专用）
        from curl_cffi import CurlMime
        mp = CurlMime()
        for k, v in payload.items():
            mp.addpart(name=k, data=str(v).encode('utf-8'))

        url = f"https://doc.weixin.qq.com/formcol/answer_page?sid={self.sid}&wedoc_xsrf={self.xsrf}"
        
        print(f"正在使用 curl_cffi 提交日报 [ID: {form_id}] 到: {url}")
        
        response = self.session.post(url, headers=self.headers, multipart=mp)
        mp.close()
        
        if response.status_code == 200:
            try:
                result = response.json()
                if result.get('errCode') == 0:
                    print("日报提交成功！")
                else:
                    print(f"日报提交返回异常: {result}")
                return result
            except Exception as e:
                print(f"解析 JSON 失败: {e}, 原始内容: {response.text}")
                return None
        else:
            print(f"请求失败，状态码: {response.status_code}, 内容: {response.text}")
            return None

# 测试运行脚本
if __name__ == "__main__":
    # 配置数据
    example_data = {
        "date": "2026年04月16日", # 16号
        "mngreporters": ["1688858256245493", "1688858005714619", "1688857251600180"],
        "form_id": "AEoAdAfTAA8AZIAWgZUAEUCNAMTNLUG6j_base", # 尝试使用原 ID
        "type": 8, # 仍先尝试 8
        "items": [
            {
                "content": "测试：动态提取与原 ID 兼容性验证",
                "result": "验证 -60156 报错原因",
                "start_time": "09:00",
                "end_time": "10:30",
                "priority": "2",
                "work_type": "8",
                "center": "6"
            }
        ]
    }
    
    try:
        sender = WeComJournalSender()
        sender.submit(example_data)
    except Exception as e:
        print(f"执行失败: {e}")

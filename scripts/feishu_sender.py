import os
import json
import lark_oapi as lark
from utils.logger import log


class FeishuSender:
    """
    飞书消息发送模块 (基于 Lark SDK)
    """

    def __init__(self):
        self.app_id = os.getenv("FEISHU_APP_ID", "")
        self.app_secret = os.getenv("FEISHU_APP_SECRET", "")
        self.target_chat_id = os.getenv("FEISHU_TARGET_CHAT_ID", "")
        self.template_color = "blue"

        # 初始化 SDK Client
        self.client = (
            lark.Client.builder()
            .app_id(self.app_id)
            .app_secret(self.app_secret)
            .log_level(lark.LogLevel.ERROR)
            .build()
        )

    def build_daily_report_card(self, items: list, date_str: str = "今日") -> str:
        """构建飞书交互式卡片 JSON"""
        if not items:
            return ""
        if items[0].get("date"):
            date_str = items[0].get("date")

        elements = []
        for item in items:
            priority = item.get("priority", "普通")
            emoji = (
                "🔴" if "紧急" in priority else ("🟡" if "重要" in priority else "🟢")
            )
            content = f"**{item.get('content', '无描述')}**"
            result = f"成果：{item.get('result', '进行中')}"
            meta_info = f"🕒 {item.get('start_time', '')}~{item.get('end_time', '')} | {emoji} {priority} | 🏷️ {item.get('type', '其他')} | 🏢 {item.get('project', '其他')}"

            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"{content}\n{result}\n<font color='grey'>{meta_info}</font>",
                    },
                }
            )
            elements.append({"tag": "hr"})

        if elements and elements[-1]["tag"] == "hr":
            elements.pop()
        card = {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"📅 每日工作总结 | {date_str}",
                },
                "template": self.template_color,
            },
            "elements": elements,
        }
        return json.dumps(card)

    def send(self, card_json: str) -> bool:
        """执行发送 (自动识别群聊 oc_ 或用户 ou_)"""
        if not self.app_id or not self.target_chat_id:
            log.warning("⚠️ 提示: [飞书] 配置缺失，请检查 .env")
            return False

        # 自动识别接收 ID 类型
        receive_id_type = "chat_id"
        if self.target_chat_id.startswith("ou_"):
            receive_id_type = "open_id"
        elif self.target_chat_id.startswith("on_"):
            receive_id_type = "union_id"

        request = (
            lark.im.v1.CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                lark.im.v1.CreateMessageRequestBody.builder()
                .receive_id(self.target_chat_id)
                .msg_type("interactive")
                .content(card_json)
                .build()
            )
            .build()
        )

        try:
            response = self.client.im.v1.message.create(request)
            if response.success():
                log.info("✅ [飞书] 日报卡片已成功推送至目标终端。")
                return True
            else:
                log.error(f"❌ [飞书] 推送失败 (代码 {response.code}): {response.msg}")
                return False
        except Exception as e:
            log.error(f"❌ [飞书] 卡片推送网关发生异常: {e}")
            return False

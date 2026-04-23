import os
import json
import lark_oapi as lark
import io
from logger import log


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

    def upload_image(self, image_path: str) -> str:
        """上传图片到飞书并返回 image_key"""
        if not os.path.exists(image_path):
            log.error(f"❌ [飞书] 上传失败: 文件不存在 {image_path}")
            return ""

        try:
            import time
            start = time.time()
            with open(image_path, "rb") as f:
                image_content = f.read()

            request = (
                lark.im.v1.CreateImageRequest.builder()
                .request_body(
                    lark.im.v1.CreateImageRequestBody.builder()
                    .image_type("message")
                    .image(io.BytesIO(image_content))
                    .build()
                )
                .build()
            )
            log.info(f"⏳ [飞书] 正在上传图片至服务器...")
            response = self.client.im.v1.image.create(request)
            duration = time.time() - start
            if response.success():
                image_key = response.data.image_key
                log.info(f"✅ [飞书] 图片上传成功 (耗时 {duration:.2f}s): {image_key}")
                return image_key
            else:
                log.error(f"❌ [飞书] 图片上传失败 (代码 {response.code}): {response.msg}")
                return ""
        except Exception as e:
            log.error(f"❌ [飞书] 图片上传发生异常: {e}")
            return ""

    def send_qr_code(self, image_key: str, title: str = "🔑 企业微信扫码登录") -> bool:
        """发送二维码图片卡片"""
        if not image_key:
            return False

        card = {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "orange",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": "⚠️ **检测到环境未登录**\n请使用手机企业微信扫描下方二维码（有效时间60S）。"},
                },
                {
                    "tag": "img",
                    "img_key": image_key,
                    "alt": {"tag": "plain_text", "content": "登录二维码"},
                },
                {
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": "提示：扫码成功后系统将自动继续，无需手动操作工作流。"}]
                }
            ],
        }
        return self.send(json.dumps(card))

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

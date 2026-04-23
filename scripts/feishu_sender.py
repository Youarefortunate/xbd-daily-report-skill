import os
import json
import lark_oapi as lark
import io
import time
from datetime import datetime, date
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

    def fetch_extra_work(self) -> list:
        """
        从飞书私聊/群聊中拉取今日带有 /add 前缀的消息作为额外工作
        """
        if not self.app_id or not self.target_chat_id:
            return []

        # 1. 确定 ID 类型 (如果是 ou_ 需要转换为 oc_)
        resolved_id = self._resolve_chat_id()
        container_id_type = "chat"
        
        # 2. 构造请求：获取今日消息
        # 获取今日 0 点的时间戳 (秒)
        today_start = int(datetime.combine(date.today(), datetime.min.time()).timestamp())
        
        request = (
            lark.im.v1.ListMessageRequest.builder()
            .container_id_type(container_id_type)
            .container_id(resolved_id)
            .start_time(str(today_start)) # SDK 要求字符串
            .build()
        )

        extra_items = []
        try:
            log.info(f"🔍 [飞书] 正在拉取今日指令消息 (Start: {today_start})...")
            response = self.client.im.v1.message.list(request)
            if not response.success():
                log.error(f"❌ [飞书] 拉取消息失败: {response.msg}")
                return []

            messages = response.data.items if response.data and response.data.items else []
            for msg in messages:
                # 只处理文本消息
                if msg.msg_type != "text":
                    continue
                
                # 飞书文本内容是 JSON 字符串，例如 '{"text":"/add hello"}'
                try:
                    content_dict = json.loads(msg.body.content)
                    raw_text = content_dict.get("text", "").strip()
                    
                    if raw_text.startswith("/add"):
                        # 提取内容
                        content = raw_text[4:].strip()
                        if not content:
                            continue
                            
                        # 处理多行输入（用户可能输入 1. xxx 2. xxx）
                        lines = [line.strip() for line in content.split("\n") if line.strip()]
                        for line in lines:
                            # 去掉前面的序号 如 "1、" 或 "1."
                            import re
                            clean_line = re.sub(r'^\d+[\.、\s\-]+', '', line).strip()
                            
                            # --- 智能过滤 ---
                            # 1. 长度过滤 (太短没意义)
                            if len(clean_line) < 2:
                                continue
                            
                            # 2. 关键词/模式过滤 (过滤掉 test, freege, ..., 纯数字等)
                            lower_line = clean_line.lower()
                            meaningless_patterns = [
                                r'^test$', r'^testing$', r'^[\.\s\?！!]+$', 
                                r'^freege$', r'^\d+$', r'^[a-zA-Z]$', r'^ok$', r'^111+$'
                            ]
                            is_meaningless = False
                            for pattern in meaningless_patterns:
                                if re.match(pattern, lower_line):
                                    is_meaningless = True
                                    break
                            
                            if is_meaningless:
                                log.debug(f"🗑️ [飞书] 过滤无意义补报: {clean_line}")
                                continue
                                
                            extra_items.append(clean_line)
                            log.info(f"➕ [飞书] 识别到有效补报: {clean_line}")
                except:
                    continue
                    
        except Exception as e:
            log.error(f"❌ [飞书] 拉取消息发生异常: {e}")
            
        return extra_items

    def _resolve_chat_id(self) -> str:
        """
        将 open_id/union_id 转换为列表查询所需的 chat_id
        """
        if not self.target_chat_id or self.target_chat_id.startswith("oc_"):
            return self.target_chat_id

        # 如果是 ou_ 或 on_，需要通过创建/获取会话接口换取 chat_id
        try:
            receive_id_type = "open_id"
            if self.target_chat_id.startswith("on_"):
                receive_id_type = "union_id"

            request = (
                lark.im.v1.CreateChatRequest.builder()
                .request_body(
                    lark.im.v1.CreateChatRequestBody.builder()
                    .name("Direct Chat Resolver")
                    .build()
                )
                .build()
            )
            # 注意：im.v1.chat.create 是创建群组。
            # 获取 P2P 会话 ID 的正确方式是：如果没有 oc_，则目前的 List API 可能无法直接拉取，
            # 除非使用“获取用户或机器人所在的群列表”并匹配。
            # 鉴于权限复杂性，我们先记录警告并尝试直接使用。
            
            # 备选方案：提示用户使用 oc_ ID。
            log.warning(f"⚠️ [飞书] 当前配置的是用户 ID ({self.target_chat_id})而非群聊 ID，指令拉取可能受限。建议在飞书后台查询以 oc_ 开头的 Chat ID。")
            return self.target_chat_id
        except:
            return self.target_chat_id

# 飞书推送配置与 ID 获取指南

本 Skill 的飞书模块已升级为基于官方 `lark-oapi` SDK 的**工业级实现**。支持自动 Token 托管及交互式卡片推送。

---

## 1. 核心参数说明 (`.env`)

| 变量名 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- |
| **FEISHU_APP_ID** | 是 | 飞书自建应用的 App ID | `cli_9fxxxxxx` |
| **FEISHU_APP_SECRET** | 是 | 飞书自建应用的 App Secret | `xxxxxx` |
| **FEISHU_TARGET_CHAT_ID**| 是 | 推送目标 ID (支持群聊或私聊) | `oc_xxx` 或 `ou_xxx` |

---

## 2. 自动化识别逻辑

系统会根据 `FEISHU_TARGET_CHAT_ID` 的**前缀**自动判断推送路径：

- **`oc_` 前缀**：自动识别为 **ChatID**，消息将发送至**群聊**。
- **`ou_` 前缀**：自动识别为 **OpenID**，消息将通过机器人**私聊**发送给个人。

---

## 3. 技术特性：无需 Token 管理
与传统 Webhook 或手动 Auth 不同，本模块利用 SDK 的内存缓存机制：
- **无感刷新**: SDK 会在后台自动处理 `tenant_access_token` 的获取与刷新。
- **无需持久化**: 不再产生 `feishu_token.json` 等本地文件，提升了环境的整洁度与安全性。

---

## 4. 获取目标 ID 的快速方法

### A. 获取群聊 ID (`oc_` 前缀)

1. **添加机器人**：先将您的自建应用机器人邀请进目标群聊。
2. **使用 API 调试台**：通过 [获取群列表接口](https://open.feishu.cn/api-explorer?from=op_doc&apiName=list&project=im&resource=chat&version=v1) 直接查看。

### B. 获取个人 OpenID (`ou_` 前缀)
最直接的方法是通过 [飞书 API 调试台 - 获取当前登录身份的用户 ID](https://open.feishu.cn/api-explorer?from=op_doc&apiName=get&project=contact&resource=user&version=v3)，点击“开始调试”即可在结果中找到您的 `open_id`。

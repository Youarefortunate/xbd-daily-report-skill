# 🎬 信巴迪 (Daily Bot) - 自动化日报生成流水线

> 一个集 GitLab 实时更新、AI 深度润色、飞书卡片推送及企业微信 RPA 自动填报于一体的高效日报助手。

## 🌟 核心特性

- **多源数据采集**：自动抓取 GitLab 指定分支的提交记录，并支持通过飞书指令（`/add`）实时补充当面沟通等非 Git 产出内容。
- **AI 智能润色**：基于大模型实现日报条目的结构化、专业化升级（支持工作内容、工作成果、时间分配、优先级等多维度生成）。
- **隐私脱敏架构**：采用 `config.yaml` 管理非敏感全局配置，`.env` 严防隐私密钥，确保代码可开源、可分享。
- **全自动填报 (RPA)**：基于 Playwright 模拟真人行为，自动完成企业微信腾讯文档报表的填充与提交。
- **双模运行**：
  - **本地模式**：可视化运行，支持人工核对后再提交。
  - **云端模式 (GitHub Actions)**：静默运行，配合飞书二维码推送，实现“随时随地，扫码即报”。

---

## 🚀 快速开始

### 1. 环境准备

本项目建议使用 Python 3.10+ 及虚拟环境管理。

```bash
# 创建虚拟环境
python -m venv .venv

# 激活环境 (Windows)
.venv\Scripts\activate

# 安装所有依赖
pip install -r scripts/requirements.txt

# 运行主程序
python scripts/main.py
```

### 2. 配置说明

#### A. 业务配置 (`scripts/config.yaml`)
修改非敏感配置，如 AI 模型、RPA 速度、运行日期等：
```yaml
openai:
  base_url: "https://your-api-base"
  model: "your-model"
  
scheduler:
  weekdays: "1,2,3,4,5"  # 周一至周五运行
  time: "18:20"
```

#### B. 敏感配置 (`scripts/.env`)
请参照示例在 `.env` 中填入您的隐私 Token：
- `GITLAB_TOKEN`: 您的私有令牌。
- `OPENAI_API_KEY`: AI 密钥。
- `FEISHU_APP_ID/SECRET`: 用于飞书推送和指令交互。

---

## 🛠️ 技术架构 (模块化设计)

主流程 `scripts/main.py` 严格遵循 0-1-2-3-4 序数化步骤：

- **Step 0: `is_github_actions_environment`** - 环境与静默准入检查。
- **Step 1: `collect_data`** - GitLab + 飞书动态数据采集。
- **Step 2: `polish_report`** - AI 结构化润色加工。
- **Step 3: `send_to_feishu`** - 精致日报卡片推送。
- **Step 4: `fill_rpa`** - 浏览器自动化模拟填报。

---

## 📅 版本记录

- **v2.0**: 引入 YAML 配置引擎，实现敏感数据彻底分离；主逻辑重构为模块化函数。
- **v1.5**: 增加飞书二维码推流机制，支持 GitHub Actions 静默填报。
- **v1.0**: 实现 GitLab 采集与 AI 基础润色。

---

## 📄 开源协议
MIT License

---
name: dailybot-miao
description: 高级自动化日报工作流 (日报喵)。采用面向对象重构，集成 GitLab 提交记录采集、AI 智能润色、飞书交互式卡片推送及企业微信 RPA 自动填报。支持 uv 环境管理，实现内存级数据直穿与精美的终端结果预览。
---

# DailyBot Miao 自动化日报工作流

## 📚 配置指南 (References)
各个功能模块的配置指南已存放至 `references/`：
- [🚀 GitLab 采集器配置](references/crawler_config.md) (多仓索引、分支策略)
- [🤖 AI 处理器配置](references/ai_config.md) (OpenAI 协议、配置自加载)
- [📝 AI 润色提示词规范](references/system_prompt.md) (日报喵系统指令)
- [📧 飞书推送中心配置](references/feishu_config.md) (SDK 模式、群聊/私聊自动识别)
- [⏰ Windows 调度器配置](references/scheduler_config.md) (定时任务、开机自启、PATH 注入)

## 核心架构

```text
scripts/
├── main.py                # 统一调度执行入口。负责加载环境、实例化各功能模块。
├── scheduler.py           # 调度管家。负责 Windows 计划任务 (schtasks) 和注册表的自动化管理。
├── gitlab_collector.py     # 基于 GitLab REST API 的历史记录采集器。
├── ai_processor.py        # 基于 OpenAI 协议的大模型生成逻辑。
├── feishu_sender.py       # 飞书推送模块，支持交互式卡片。
├── wecom_rpa.py           # 基于 Playwright 的 RPA 引擎，模拟真人行为完成企业微信填报。
├── xbd.bat                # [自动生成] Windows 引导脚本，支持全局命令行调用。
├── .env                   # 本地环境变量配置文件 (含 API Key、Token 等)。
├── requirements.txt       # 模块依赖清单。
├── extra_report.txt       # [手动指定新增] 增补报告临时存储文件。
├── logger.py              # 统一日志格式化组件。
└── logs/                  # [自动生成] 运行日志存放目录。
```

## 环境与运行

### 1. 初始化环境
建议在项目根目录下或 `scripts/` 目录下执行：
```powershell
uv venv
uv pip install -r requirements.txt
uv run playwright install chrome
```

### 2. 部署自动化调度 (可选)
根据 `.env` 配置一键挂载 Windows 定时任务：
```powershell
# 安装并同步配置 (含定时任务、自启动、PATH 注入)
uv run python scripts/scheduler.py --install

# 查看当前注册状态
uv run python scripts/scheduler.py --status
```

### 3. 一键运行 (手动模式)
```powershell
uv run python scripts/main.py
```
若已开启 `SCHEDULER_AUTO_PATH`，可在任意位置直接运行：
```powershell
xbd # 直接运行，或者加上 --run 参数
xbd --install  # 安装并同步配置 (含定时任务、自启动、PATH 注入)
xbd --uninstall  # 卸载所有任务
xbd --status  # 查看当前注册状态
```

## 视觉交互特性
- **📦 原始素材预览**: 自动将不同仓库的提交记录按项目路径进行分组展示，结构清晰。
- **✨ 润色结果预览**: 在正式填报前，以精美的终端边框形式展示 AI 生成的日报草稿，包含时间段、优先级和项目归类。
- **有才打印，无才静默**: 极致的日志控制逻辑，仅在有实际数据产出时才会显示对应的标题栏和边框。
- **阅后即焚 (Auto-Cleanup)**: 流程执行成功后，`extra_report.txt` 会被自动复位，确保第二天数据纯净。

## 注意事项
- **配置内聚**: 各模块均具备从环境变量读取默认值的能力，不再依赖 `main.py` 传参，极大地提升了模块独立性。
- **Playwright 持久化**: 模块会自动检测并尝试复用本地已安装的 Chrome 浏览器，共享登录缓存，实现免扫码运行。
- **稳定版本**: 依赖项版本已全部锁定，确保在不同机器上运行的一致性。

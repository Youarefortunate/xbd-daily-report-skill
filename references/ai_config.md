# AI 处理器配置指南

本处理器（`AIProcessor` 类）是日报流的智能核心，基于 OpenAI 兼容协议实现。

## 1. 环境变量配置

配置存放于 `scripts/.env`。

| 环境变量 | 默认值 | 描述 |
| :--- | :--- | :--- |
| `OPENAI_API_KEY` | (必填) | AI 平台的 API 密钥 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API 基础地址 |
| `OPENAI_MODEL` | (必填) | 模型 ID（如 doubao-2.0-preview） |
| `EXTRA_REPORT_PATH` | `extra_report.txt` | 手动补充文件的存放路径 |

## 2. “阅后即焚” 机制

当 `main.py` 调用调用 `AIProcessor.process` 且 AI 成功返回合法的 JSON 条目后，**系统会自动清空 `extra_report.txt`**。

> [!TIP]
> 这一机制确保了您的手动输入是“一次性”的，避免了重复填报，但在测试阶段如果您想保留数据，请先对该文件进行备份。

## 3. 调用接口 (API)

如果您需要在其他地方调用该处理器：
```python
processor = AIProcessor() # 自动加载配置
items = processor.process(commits_list, extra_path, prompt_path)
# 返回值示例: [{'content': '...', 'result': '...', ...}, ...]
```

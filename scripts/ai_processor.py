import os
import json
from openai import OpenAI
from utils.logger import log


class AIProcessor:
    """AI 润色处理类"""

    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        """
        初始化 AI 处理器
        :param api_key: OpenAI API Key (可选，默认从环境读取)
        :param base_url: API 基础地址 (可选，默认从环境读取)
        :param model: 模型名称 (可选，默认从环境读取)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.base_url = base_url or os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )
        self.model = model or os.getenv("OPENAI_MODEL", "")
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def _load_file_content(self, file_path: str) -> str:
        if not os.path.exists(file_path):
            return ""

        encodings = ["utf-8", "utf-8-sig", "utf-16", "gbk"]
        for enc in encodings:
            try:
                with open(file_path, "r", encoding=enc) as f:
                    return f.read().strip()
            except (UnicodeDecodeError, UnicodeError):
                continue
            except Exception as e:
                log.warning(f"⚠️ 警告: 读取文件 {file_path} 时发生未知错误 ({enc}): {e}")
                break
        return ""

    def _clear_file(self, file_path: str) -> bool:
        """清空文件内容"""
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.truncate(0)
            return True
        except Exception as e:
            log.warning(f"⚠️ 警告: 清空文件 {file_path} 失败: {e}")
            return False

    def polish(self, system_prompt: str, user_content: str) -> str:
        """调用 OpenAI 兼容接口进行润色"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
                stream=False,
            )
            return response.choices[0].message.content
        except Exception as e:
            raise Exception(f"AI 调用失败: {e}")

    def process(
        self, git_commits: list, extra_report_path: str, system_prompt_path: str
    ) -> str:
        """
        执行完整的润色流程
        :param git_commits: Git 提交记录列表
        :param extra_report_path: 额外补充信息文件路径
        :param system_prompt_path: 系统提示词文件路径
        :return: 润色后的 JSON 字符串
        """
        # 1. 加载系统提示词
        system_prompt = self._load_file_content(system_prompt_path)
        if not system_prompt:
            raise Exception(f"错误: 无法加载提示词文件: {system_prompt_path}")

        # 2. 加载额外信息内容
        extra_content = self._load_file_content(extra_report_path)

        if extra_content:
            log.info("\n📝 额外补充信息")
            log.info("-" * 60)
            log.info(f" 📂 采集文件: {os.path.basename(extra_report_path)}")
            log.info(f" └─ 补充内容: \n{extra_content}")
            log.info("-" * 60 + "\n")

        # 边界检查
        if not git_commits and not extra_content:
            log.warning("ℹ️ 提示: 未发现任何 Git 提交记录且离线补充为空，跳过润色。")
            return []

        # 3. 用户额外补充内容拼接
        user_input = ""
        if git_commits:
            user_input += (
                f"[Git提交记录]\n{json.dumps(git_commits, ensure_ascii=False)}\n\n"
            )
        if extra_content:
            user_input += f"[额外信息补充]\n{extra_content}\n"

        # 4. 驱动 AI 润色
        log.info(f"🚀 正在发送数据至 AI ({self.model}) 进行润色...")
        try:
            raw_result = self.polish(system_prompt, user_input)

            # 5. 处理 Markdown 代码块包裹的情况
            clean_json = raw_result.strip()
            if clean_json.startswith("```json"):
                clean_json = (
                    clean_json.replace("```json", "").replace("```", "").strip()
                )
            elif clean_json.startswith("```"):
                clean_json = clean_json.replace("```", "").strip()

            # 6. 验证 JSON 合法性
            items = json.loads(clean_json)

            # 清空已处理的额外信息文件
            if extra_content:
                log.info(
                    f"🧹 正在清空已处理的额外补充信息: {os.path.basename(extra_report_path)}"
                )
                self._clear_file(extra_report_path)

            log.info(
                f"✨ [AI] 润色成功，生成了 {len(items) if isinstance(items, list) else 1} 条结构化条目。"
            )
            return items if isinstance(items, list) else [items]
        except json.JSONDecodeError:
            return []

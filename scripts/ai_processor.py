import os
import json
import httpx
from openai import AsyncOpenAI
from logger import log


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
        
        # 显式初始化异步 httpx 客户端
        http_client = httpx.AsyncClient(
            base_url=self.base_url,
            follow_redirects=True,
            timeout=60.0
        )
        self.client = AsyncOpenAI(
            api_key=self.api_key, 
            base_url=self.base_url,
            http_client=http_client
        )

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

    async def polish(self, system_prompt: str, user_content: str) -> str:
        """调用 OpenAI 兼容接口进行润色 (异步)"""
        try:
            response = await self.client.chat.completions.create(
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

    async def close(self):
        """关闭客户端资源"""
        await self.client.close()

    async def process(
        self,
        git_commits: list,
        extra_report_path: str,
        system_prompt_path: str,
        fake_items: list = None,
        extra_report_items: list = None,
    ) -> list:
        """
        执行完整的润色流程 (异步)
        :param git_commits: Git 提交记录列表
        :param extra_report_path: 额外补充信息文件路径
        :param system_prompt_path: 系统提示词文件路径
        :param fake_items: 伪装素材列表
        :param extra_report_items: 动态补充的工作内容列表 (如来自飞书)
        :return: 润色后的 JSON 列表
        """
        # 1. 加载系统提示词
        system_prompt = self._load_file_content(system_prompt_path)
        if not system_prompt:
            raise Exception(f"错误: 无法加载提示词文件: {system_prompt_path}")

        # 2. 加载额外信息内容
        local_extra = self._load_file_content(extra_report_path)
        
        # 合并本地文件与动态传入的内容
        merged_extra = []
        if local_extra:
            merged_extra.append(local_extra)
        if extra_report_items:
            merged_extra.extend(extra_report_items)
            
        extra_content = "\n".join(merged_extra) if merged_extra else ""

        if extra_content:
            log.info("\n📝 额外补充信息 (含飞书指令)")
            log.info("-" * 60)
            if local_extra:
                log.info(f" 📂 采集文件: {os.path.basename(extra_report_path)}")
            if extra_report_items:
                log.info(f" 💬 飞书拉取: {len(extra_report_items)} 条指令内容")
            log.info(f" └─ 补充详情: \n{extra_content}")
            log.info("-" * 60 + "\n")

        # 边界检查
        if not git_commits and not extra_content and not fake_items:
            log.warning("ℹ️ 提示: 未发现任何 Git 提交记录且离线补充/伪装素材为空，跳过润色。")
            return []

        # 3. 用户输入拼接
        user_input = ""
        if git_commits:
            user_input += "  平台: GITLAB\n"
            user_input += "    📦 [今日真实工作]\n"
            # 按项目分组
            project_map = {}
            for c in git_commits:
                p = f"{c['project']} ({c['project_name']})" if c.get('project_name') else c['project']
                project_map.setdefault(p, []).append(c)
            
            for p, p_commits in project_map.items():
                user_input += f"      数据源: {p}\n"
                # 按日期分组
                date_map = {}
                for c in p_commits:
                    d = c['date'][:10]
                    date_map.setdefault(d, []).append(c)
                
                for d in sorted(date_map.keys(), reverse=True):
                    user_input += f"        📅 日期: {d}\n"
                    for c in date_map[d]:
                        # 提取时间
                        time_str = "00:00"
                        try:
                            from datetime import datetime
                            dt = datetime.fromisoformat(c.get("date", "").replace("Z", "+00:00"))
                            time_str = dt.strftime("%H:%M")
                        except: pass
                        user_input += f"          - [{time_str}] {c['title']}\n"

        if fake_items:
            user_input += "\n    🎭 [待伪装素材]\n"
            source_map = {}
            for item in fake_items:
                p = f"{item.source} ({item.repo_path})"
                source_map.setdefault(p, []).append(item)
            
            for p, items in source_map.items():
                user_input += f"      数据源: {p}\n"
                date_map = {}
                for item in items:
                    d = item.date or "未知日期"
                    date_map.setdefault(d, []).append(item)
                
                for d in sorted(date_map.keys(), reverse=True):
                    user_input += f"        📅 日期: {d}\n"
                    for item in date_map[d]:
                        user_input += f"          - {item.content}\n"

        if extra_content:
            user_input += f"\n    📝 [额外信息补充]\n{extra_content}\n"

        # 4. 驱动 AI 润色
        log.info(f"🚀 正在发送数据至 AI ({self.model}) 进行润色...")
        try:
            raw_result = await self.polish(system_prompt, user_input)

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
            log.error(f"❌ [AI] 润色结果 JSON 解析失败: {raw_result}")
            return []
        except Exception as e:
            log.error(f"❌ [AI] 润色流程异常: {e}")
            return []
        finally:
            # 及时释放连接池
            await self.close()

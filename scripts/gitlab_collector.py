from datetime import datetime, timezone, timedelta
import urllib.parse
import requests
import os
from logger import log


class GitLabCollector:
    """GitLab 提交记录采集类"""

    # 东八区时区
    TZ_CHINESE = timezone(timedelta(hours=8))

    def __init__(self, url: str = None, token: str = None, author: str = None):
        self.url = (url or os.getenv("GITLAB_URL", "")).rstrip("/")
        self.token = token or os.getenv("GITLAB_TOKEN", "")
        self.author = author or os.getenv("GITLAB_AUTHOR", "")
        self.headers = {"PRIVATE-TOKEN": self.token}

    def _get_all_branches(self, project_path: str) -> list:
        """获取项目的所有分支名"""
        encoded_path = urllib.parse.quote_plus(project_path)
        url = f"{self.url}/api/v4/projects/{encoded_path}/repository/branches"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return [b["name"] for b in response.json()]
        except Exception as e:
            log.warning(f"⚠️ 警告: 获取 {project_path} 的分支列表失败: {e}")
            return ["master"]

    def _fetch_commits_by_branch(
        self, project_path: str, branch: str, since: str, until: str
    ) -> list:
        """针对单个分支执行分页采集"""
        encoded_path = urllib.parse.quote_plus(project_path)
        url = f"{self.url}/api/v4/projects/{encoded_path}/repository/commits"
        params = {
            "ref_name": branch,
            "since": since,
            "until": until,
            "per_page": 100,
            "page": 1,
        }

        branch_commits = []
        while True:
            try:
                resp = requests.get(
                    url, headers=self.headers, params=params, timeout=15
                )
                resp.raise_for_status()
                data = resp.json()
                if not data:
                    break

                for c in data:
                    # 本地作者过滤
                    if self.author:
                        a_lower = self.author.lower()
                        if (
                            a_lower not in c.get("author_name", "").lower()
                            and a_lower not in c.get("author_email", "").lower()
                        ):
                            continue
                    branch_commits.append(c)

                if len(data) < 100:
                    break
                params["page"] += 1
            except Exception as e:
                log.error(f"❌ 错误: 采集分支 {branch} 时发生异常: {e}")
                break
        return branch_commits

    def _parse_date_range(
        self, date_config: str, default_since: str, default_until: str
    ):
        """解析日期范围"""
        if not date_config:
            return default_since, default_until, "今日"
        parts = [p.strip() for p in date_config.split(",") if p.strip()]
        try:
            if len(parts) == 1:
                d = datetime.strptime(parts[0], "%Y-%m-%d").replace(
                    tzinfo=self.TZ_CHINESE
                )
                s = d.replace(hour=0, minute=0, second=0).isoformat()
                u = d.replace(hour=23, minute=59, second=59).isoformat()
                return s, u, f"{parts[0]} (全天)"
            elif len(parts) == 2:
                d_s = datetime.strptime(parts[0], "%Y-%m-%d").replace(
                    tzinfo=self.TZ_CHINESE
                )
                d_u = datetime.strptime(parts[1], "%Y-%m-%d").replace(
                    tzinfo=self.TZ_CHINESE
                )
                s = d_s.replace(hour=0, minute=0, second=0).isoformat()
                u = d_u.replace(hour=23, minute=59, second=59).isoformat()
                return s, u, f"{parts[0]} 至 {parts[1]}"
        except Exception as e:
            log.warning(f"⚠️ 警告: 日期格式解析失败 '{date_config}': {e}")
        return default_since, default_until, "默认"

    def run(self, repo_configs: list) -> list:
        """驱动多仓库采集流"""
        if not repo_configs:
            return []

        # 默认日期 (今日)
        now = datetime.now(self.TZ_CHINESE)
        def_s = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        def_u = now.isoformat()

        log.info("\n🚀 开始执行 GitLab 提交记录采集...")
        log.info(f"🐠 目标作者: {self.author if self.author else '全部'}")
        log.info("-" * 50)

        all_commits_map = {}
        for idx, repo in enumerate(repo_configs):
            path = repo["path"]
            s, u, label = self._parse_date_range(repo.get("date_range"), def_s, def_u)

            target_branches = repo.get("branches", [])
            if not target_branches:
                target_branches = self._get_all_branches(path)
                branch_label = "全部分支"
            else:
                branch_label = f"指定分支: {target_branches}"

            log.info(f"项目 [{idx}]: {path}")
            log.info(f"├─ 采集日期: {label}")
            log.info(f"└─ 采集范围: {branch_label}")

            for branch in target_branches:
                log.info(f"   · 正在抓取分支: {branch}...")
                commits = self._fetch_commits_by_branch(path, branch, s, u)
                log.info(f"     [找到 {len(commits)} 条]")

                for c in commits:
                    key = f"{path}:{c['id']}"
                    if key not in all_commits_map:
                        all_commits_map[key] = {
                            "id": c["id"][:8],
                            "title": c["title"],
                            "date": c["created_at"],
                            "author": c["author_name"],
                            "project": path,
                            "project_name": repo.get("name", ""),
                            "branch": branch,
                        }
            log.info(" " + "-" * 30)

        final_list = list(all_commits_map.values())
        final_list.sort(key=lambda x: x["date"], reverse=True)
        print(f"\n✅ 采集完成! 共发现 {len(final_list)} 条唯一提交记录。")
        return final_list

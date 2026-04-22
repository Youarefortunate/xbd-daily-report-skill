import os
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from pydantic import BaseModel
from logger import log

# 东八区时区
_TZ = timezone(timedelta(hours=8))


class CamouflageItem(BaseModel):
    """
    统一的伪装素材结构模型
    """

    id: str  # 素材唯一标识 ID (如 commit hash)
    source: str  # 素材来源项目名称 (如 "农融易小程序")
    repo_path: str  # 仓库路径 (如 "frontend_b2bwings/b2b-wings-easyloan-mini")
    content: str  # 素材的具体内容 (如 commit message)
    platform: str  # 所属平台名称 (如 gitlab/github)
    author: Optional[str] = None  # 素材作者名称
    date: Optional[str] = None  # 素材原始日期 (YYYY-MM-DD)
    created_at: Optional[str] = None  # 素材原始创建时间 (ISO 格式)

    @classmethod
    def builder(cls):
        return CamouflageItemBuilder()


class CamouflageItemBuilder:
    def __init__(self):
        self._id = None
        self._source = None
        self._repo_path = None
        self._content = None
        self._platform = None
        self._author = None
        self._date = None
        self._created_at = None

    def set_id(self, item_id: str):
        self._id = item_id
        return self

    def set_source(self, source: str):
        self._source = source
        return self

    def set_repo_path(self, repo_path: str):
        self._repo_path = repo_path
        return self

    def set_content(self, content: str):
        self._content = content
        return self

    def set_platform(self, platform: str):
        self._platform = platform
        return self

    def set_author(self, author: str):
        self._author = author
        return self

    def set_date(self, date: str):
        self._date = date
        return self

    def set_created_at(self, created_at: str):
        self._created_at = created_at
        return self

    def build(self) -> CamouflageItem:
        return CamouflageItem(
            id=self._id,
            source=self._source,
            repo_path=self._repo_path,
            content=self._content,
            platform=self._platform,
            author=self._author,
            date=self._date,
            created_at=self._created_at,
        )


class CamouflageHistory(BaseModel):
    """
    LRU 历史纪录模型，用于记录素材的使用轨迹
    """

    last_used: str  # 最后一次被使用作为伪装素材的日期 (YYYY-MM-DD)
    variants: List[str]  # 该素材曾经生成过的所有 AI 润色变体列表
    # 冗余存储素材关键信息，方便查阅历史
    content: Optional[str] = None
    source_name: Optional[str] = None
    repo_path: Optional[str] = None
    platform: Optional[str] = None
    author: Optional[str] = None
    original_date: Optional[str] = None


class CamouflageHistoryManager:
    """
    负责管理伪装素材的使用历史与 LRU 冷却逻辑 (按日期分组存储)
    """

    def __init__(self, history_file: str = "camouflage_history.json"):
        # 将历史文件存放在 scripts 目录下或用户指定目录
        self.history_file = history_file
        # 结构：{ "2026-02-28": { "item_id": CamouflageHistory } }
        self.history: Dict[str, Dict[str, CamouflageHistory]] = {}
        self.load()

    def load(self):
        data = {}
        if os.path.exists(self.history_file):
            try:
                if os.path.getsize(self.history_file) > 0:
                    with open(self.history_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
            except Exception as e:
                log.warning(f"⚠️ 加载伪装历史记录失败: {e}")
                data = {}

        for date_str, items in data.items():
            if not isinstance(items, dict):
                continue
            self.history[date_str] = {}
            for k, v in items.items():
                try:
                    self.history[date_str][k] = CamouflageHistory(**v)
                except Exception as e:
                    log.warning(f"⚠️ 解析日期 {date_str} 下的历史项 {k} 失败: {e}")

    def save(self):
        try:
            data = {}
            for date_str, items in self.history.items():
                data[date_str] = {k: v.model_dump() for k, v in items.items()}
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            log.debug(f"💾 [伪装] 历史记录已保存至 {self.history_file}")
        except Exception as e:
            log.error(f"❌ [伪装] 保存历史记录失败: {e}")

    def is_in_cooldown(self, item_id: str, cooldown_days: int) -> bool:
        """
        全量遍历日期分组，寻找该 ID 最后一次出现的时间
        """
        latest_date = None
        for date_str, items in self.history.items():
            if item_id in items:
                try:
                    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_TZ)
                    if latest_date is None or d > latest_date:
                        latest_date = d
                except Exception:
                    continue

        if latest_date:
            return (datetime.now(_TZ) - latest_date).days < cooldown_days
        return False

    def update_usage(self, item: CamouflageItem, variant_raw: str):
        now_str = datetime.now(_TZ).strftime("%Y-%m-%d")
        item_id = item.id

        if now_str not in self.history:
            self.history[now_str] = {}

        # 简单记录变体（这里可以根据需要进一步精简 AI 输出）
        variant = variant_raw[:500] 

        if item_id in self.history[now_str]:
            if variant not in self.history[now_str][item_id].variants:
                self.history[now_str][item_id].variants.append(variant)
        else:
            self.history[now_str][item_id] = CamouflageHistory(
                last_used=now_str,
                variants=[variant],
                content=item.content,
                source_name=item.source,
                repo_path=item.repo_path,
                platform=item.platform,
                author=item.author,
                original_date=item.date,
            )
        self.save()


# 全局单例
camouflage_history_manager = CamouflageHistoryManager(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "camouflage_history.json")
)

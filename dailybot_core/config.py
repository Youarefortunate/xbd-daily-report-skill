import os
import yaml
from pathlib import Path
from logger import log

class Config:
    """项目配置管理器 (YAML + ENV 双引擎)"""
    
    def __init__(self):
        self._data = {}
        self._load_yaml()
        
    def _load_yaml(self):
        config_path = Path(__file__).parent / "config.yaml"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    self._data = yaml.safe_load(f) or {}
                log.info(f"📖 [配置] 已加载 YAML 配置文件: {config_path}")
            except Exception as e:
                log.error(f"❌ [配置] YAML 加载失败: {e}")
        else:
            log.warning(f"⚠️ [配置] 未发现 config.yaml，将完全依赖环境变量。")

    def get(self, key_path: str, default=None):
        """
        按照路径获取配置，支持环境变量覆盖。
        示例: get("gitlab.url") -> 优先检查 GITLAB_URL 环境变量，再检查 YAML
        """
        # 1. 尝试从环境变量获取 (全大写，点号转下划线)
        env_key = key_path.replace(".", "_").upper()
        env_val = os.getenv(env_key)
        if env_val is not None:
            # 简单类型转换
            if env_val.lower() == "true": return True
            if env_val.lower() == "false": return False
            try:
                if "." in env_val: return float(env_val)
                return int(env_val)
            except:
                return env_val

        # 2. 从 YAML 获取
        keys = key_path.split(".")
        val = self._data
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val if val is not None else default

    @property
    def gitlab_repos(self) -> list:
        """从环境变量动态扫描仓库配置 (回退至原始逻辑以保护敏感隐私)"""
        yaml_repos = self.get("gitlab.repos", [])
        if yaml_repos:
            return yaml_repos
            
        configs = []
        i = 0
        while True:
            path = os.getenv(f"GITLAB_REPO_{i}_PATH")
            if not path:
                break

            branches_str = os.getenv(f"GITLAB_REPO_{i}_BRANCH", "")
            branches = [b.strip() for b in branches_str.split(",") if b.strip()]
            date_range = os.getenv(f"GITLAB_REPO_{i}_DATE_RANGE")
            name = os.getenv(f"GITLAB_REPO_{i}_NAME", "")
            
            configs.append({
                "path": path,
                "branches": branches,
                "date_range": date_range,
                "name": name,
            })
            i += 1
        return configs

# 全局单例
config = Config()

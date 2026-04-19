# GitLab 采集器配置指南

本采集器（`GitLabCollector` 类）负责高效抓取指定项目下的最新研发动态。

## 1. 核心特性
- **类封装**: 支持实例化多个采集器（如果需要访问不同的 GitLab 实例）。
- **多分支合并**: 能够针对同一个项目，同时抓取 master、test、release 等多个分支的提交。
- **智能去重**: 在 `run` 方法中会自动根据 Commit ID 进行全局去重，确保合并后的记录不重复。

## 2. 配置项说明
环境变量读取逻辑已内置：

| 环境变量 | 描述 | 示例 |
| :--- | :--- | :--- |
| `GITLAB_URL` | GitLab REST API 根地址 | `http://git.b2bwings.com` |
| `GITLAB_TOKEN` | Private Access Token | `glpat-xxxxxxxx` |
| `GITLAB_AUTHOR` | (可选) 作者名称过滤 | `liangan` |

## 3. 动态索引逻辑
`main.py` 通过 `load_repo_configs` 支持无限数量的项目配置，格式如下：
```env
# 项目 0
GITLAB_REPO_0_PATH=namespace/project1
GITLAB_REPO_0_BRANCH=branch1, branch2
GITLAB_REPO_0_DATE_RANGE=2024-04-09 # 可选

# 项目 1
GITLAB_REPO_1_PATH=namespace/project2
...
```

## 4. 采集策略
1. **日期锁定**: 支持配置特定的日期或日期跨度（闭区间）。
2. **分支感知**: 如果未指定 `GITLAB_REPO_N_BRANCH`，采集器将自动请求 API 获取并扫描该项目下的 **所有远端分支**。

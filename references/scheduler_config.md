# Windows 自动化调度配置指南

本 Skill 集成了与主项目对齐的 Windows 调度中心，旨在实现无人值守的日报自动化流。

---

## 1. 核心调度参数 (`.env`)

| 变量名 | 默认值 | 描述 |
| :--- | :--- | :--- |
| `SCHEDULER_TIME` | `18:00` | 每天触发定时任务的时间点。格式为 `HH:mm`。 |
| `SCHEDULER_WEEKDAYS` | `1,2,3,4,5`| 运行日期。1-7 代表周一至周日。建议设为工作日。 |
| `SCHEDULER_AUTO_START` | `false` | 是否开启系统登录自启动。 |
| `SCHEDULER_AUTO_PATH` | `false` | 是否自动将项目根目录添加至系统 PATH 以支持全局指令。 |
| `SCHEDULER_INTERPRETER`| (自动探测) | 可选。手动指定 Python 解释器路径。 |

---

## 2. 部署与管理指令

所有的调度操作均通过 `scripts/scheduler.py` 完成。

### A. 安装/同步任务
当您在 `.env` 中修改了时间或开关后，必须运行安装指令以同步至系统：
```powershell
uv run python scripts/scheduler.py --install
```

### B. 查看状态
查看当前计划任务是否注册成功，以及系统使用的是哪个 Python 解释器：
```powershell
uv run python scripts/scheduler.py --status
```

### C. 卸载清理
如果您希望完全从系统中移除该 Skill 的所有痕迹（含计划任务、注册表项、引导脚本及环境变量）：
```powershell
uv run python scripts/scheduler.py --uninstall
```

### D. 全局便捷指令 (推荐)
如果您在 `.env` 中开启了 `SCHEDULER_AUTO_PATH=true`，您可以直接在 **任意** 终端中使用 `xbd` 指令，无需进入目录或使用 `uv run`：

- **查看状态**: `xbd --status`
- **同步配置**: `xbd --install`
- **手动触发**: `xbd --run` (立即执行一次日报流)
- **卸载系统**: `xbd --uninstall`

---

## 3. 技术实现细节

- **解释器锁定**: 模块会自动寻找项目下的 `.venv`。如果同事克隆了代码，`install` 指令会自动适配他的本地路径。
- **引导脚本**: 开启 `AUTO_PATH` 后，系统会生成 `xbd.bat`。它封装了 Python 路径逻辑，使得全局调用变得极其简单。
- **静默运行**: 所有的计划任务均配置为“仅在用户登录时运行”的最高优先级静默模式，不会中断您的日常操作。

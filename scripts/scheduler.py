import os
import sys
import argparse
import subprocess

try:
    import winreg
    import ctypes
except ImportError:
    # 非 Windows 环境下，调度器逻辑不适用
    if os.name != "nt":
        pass
    else:
        raise
from pathlib import Path
from logger import log
from config import config

# --- 1. 基础配置 ---
TASK_NAME = "DailyBot_Miao"
REGISTRY_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_VALUE_NAME = "DailyBotMiao"


def get_app_dir():
    """获取脚本所在目录的父目录（项目根目录）"""
    return str(Path(__file__).parent.parent.absolute())


def get_python_exe():
    """锁定 Python 解释器路径 (支持多级溯源与手动覆盖)"""
    # 1. 优先读取手动配置 (为特殊环境留的口子)
    manual_env = config.get("scheduler.interpreter")
    if manual_env and os.path.exists(manual_env):
        return manual_env

    # 2. 多级向上溯源搜索 (支持 .venv, venv, env)
    app_dir = get_app_dir()
    current = Path(app_dir)
    venv_names = [".venv", "venv", "env"]

    for _ in range(5):  # 向上溯源 5 层
        for vname in venv_names:
            # 适配 Windows (Scripts) 和 Linux/macOS (bin)
            for bin_dir in ["Scripts", "bin"]:
                candidate = (
                    current
                    / vname
                    / bin_dir
                    / ("python.exe" if os.name == "nt" else "python")
                )
                if candidate.exists():
                    return str(candidate.absolute())
        if current.parent == current:
            break
        current = current.parent

    # 3. 最终回退：使用当前运行脚本的解释器
    return sys.executable


# --- 2. 注册表管理 (自启动与 PATH) ---


def manage_startup(enabled: bool):
    """管理开机自启动逻辑"""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REGISTRY_RUN_PATH, 0, winreg.KEY_SET_VALUE
        )
        if enabled:
            # 这里的自启动主要是为了让程序保持“在场”，调度器触发时使用 --install
            cmd = (
                f'"{get_python_exe()}" "{get_app_dir()}/scripts/scheduler.py" --install'
            )
            winreg.SetValueEx(key, REGISTRY_VALUE_NAME, 0, winreg.REG_SZ, cmd)
            log.info("✅ 已注册开机同步任务。")
        else:
            try:
                winreg.DeleteValue(key, REGISTRY_VALUE_NAME)
                log.info("✅ 已移除开机自启动。")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        log.error(f"❌ 注册表操作失败: {e}")


def manage_path(enabled: bool):
    """自动将脚本所在目录添加到用户 PATH，并生成引导脚本"""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    bat_path = os.path.join(scripts_dir, "xbd.bat")

    try:
        if enabled:
            # 生成全能引导文件 (指向当前脚本并透传所有参数)
            # 使用单行紧凑模式 + exit /b，确保在 --uninstall 自删除时 Cmd 已经在内存中读取了整行逻辑，从而避免报错
            with open(bat_path, "w") as f:
                f.write(
                    f'@echo off & ("{get_python_exe()}" "{os.path.abspath(__file__)}" %*) & exit /b'
                )
            log.info(f"✅ [系统] 已生成全能引导脚本: {bat_path}")
        else:
            if os.path.exists(bat_path):
                # 启动一个独立的后台进程，等待 1 秒（确保当前脚本和调用它的 Cmd 已退出）后再删除文件
                subprocess.Popen(
                    f'timeout /t 1 > nul & del /f /q "{bat_path}"',
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS
        ) as key:
            try:
                current_path, _ = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current_path = ""

            # 1. 提取现有路径，并清理掉旧的、冗余的本程序相关路径
            # 我们保留不包含 daily-report-flow 的路径，或者正好是当前脚本目录的路径
            norm_scripts_dir = os.path.normpath(scripts_dir).lower()
            old_paths = [p.strip() for p in current_path.split(";") if p.strip()]
            new_paths = []

            for p in old_paths:
                p_norm = os.path.normpath(p).lower()
                # 过滤掉所有包含 daily-report-flow 的路径（稍后会把正确的加回来）
                if "daily-report-flow" in p_norm:
                    continue
                new_paths.append(p)

            if enabled:
                # 2. 将正确的脚本目录加入列表
                if scripts_dir not in new_paths:
                    new_paths.append(scripts_dir)

                final_path = ";".join(new_paths)
                if final_path != current_path:
                    winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, final_path)
                    log.info(f"✅ [系统] 已优化并同步用户 PATH (主推: {scripts_dir})")
                    # 广播环境变更 (WM_SETTINGCHANGE)
                    ctypes.windll.user32.SendMessageTimeoutW(
                        0xFFFF,
                        0x001A,
                        0,
                        "Environment",
                        0x0002,
                        1000,
                        ctypes.byref(ctypes.c_size_t()),
                    )
                else:
                    log.info("ℹ️ [系统] PATH 路径已是最新，无需更新。")
            else:
                final_path = ";".join(new_paths)
                if final_path != current_path:
                    winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, final_path)
                    log.info(f"✅ [系统] 已从 PATH 中清理相关路径。")
    except Exception as e:
        log.error(f"❌ PATH 注入失败: {e}")


# --- 3. Windows 计划任务 (schtasks) ---


def manage_schtask(enabled: bool, time_str: str, weekdays_str: str = ""):
    """通过 schtasks 命令行管理定时任务，支持固定日期"""
    # 先尝试删除旧任务（无论是否启用，保证幂等性）
    subprocess.run(
        f'schtasks /delete /tn "{TASK_NAME}" /f', shell=True, capture_output=True
    )

    if enabled:
        # 1. 构造日期映射 (1-7 -> MON-SUN)
        day_map = {
            "1": "MON",
            "2": "TUE",
            "3": "WED",
            "4": "THU",
            "5": "FRI",
            "6": "SAT",
            "7": "SUN",
        }

        # 2. 判断运行模式
        sch_type = "/sc DAILY"
        desc = "每日"
        if weekdays_str and weekdays_str.strip():
            days = [
                day_map.get(d.strip())
                for d in weekdays_str.split(",")
                if d.strip() in day_map
            ]
            if days:
                day_str = ",".join(days)
                sch_type = f"/sc WEEKLY /d {day_str}"
                desc = f"每周 {day_str}"

        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        bat_path = os.path.join(scripts_dir, "xbd.bat")

        # 直接让计划任务调用生成的 xbd.bat
        command = f'cmd.exe /c "{bat_path}"'

        create_cmd = f'schtasks /create /tn "{TASK_NAME}" /tr "{command}" {sch_type} /st {time_str} /f'
        result = subprocess.run(create_cmd, shell=True, capture_output=True, text=True)

        if result.returncode == 0:
            log.info(f"✅ [调度] 已成功注册计划任务: {desc} {time_str} 运行。")
        else:
            log.error(f"❌ [调度] 注册计划任务失败: {result.stderr}")


# --- 4. 入口逻辑 ---


def run_flow():
    """导入并运行 main.py 的核心逻辑"""
    log.info("\n" + "=" * 60)
    log.info("🚀 [执行] 正在拉起 XBD 日报自动化流...")
    log.info("=" * 60 + "\n")

    # 将 scripts 目录加入路径，确保 main 模块可被导入
    scripts_dir = os.path.join(get_app_dir(), "scripts")
    if scripts_dir not in sys.path:
        sys.path.append(scripts_dir)

    # 切换到 scripts 目录运行，确保相对路径（如 .env）正常工作
    os.chdir(scripts_dir)

    try:
        from main import run_daily_bot
        import asyncio

        asyncio.run(run_daily_bot())
    except Exception as e:
        log.error(f"❌ [执行] 核心流水线运行失败: {e}")


def sync_all():
    """根据配置状态全量同步同步配置"""
    auto_start = config.get("scheduler.auto_start", False)
    auto_path = config.get("scheduler.auto_path", False)
    run_time = config.get("scheduler.time", "18:00")
    weekdays = str(config.get("scheduler.weekdays", ""))

    log.info("🔄 [系统] 正在同步调度器配置...")
    manage_startup(auto_start)
    manage_path(auto_path)
    manage_schtask(True, run_time, weekdays)
    log.info("🎉 [系统] 调度同步完成！")


def show_status():
    """查看当前注册状态 (精装修版)"""
    # 读取配置
    auto_start = config.get("scheduler.auto_start", False)
    auto_path = config.get("scheduler.auto_path", False)
    run_time = config.get("scheduler.time", "18:00")
    weekdays = config.get("scheduler.weekdays", "全部")

    log.info("\n" + "╔" + "═" * 58 + "╗")
    log.info("║" + " " * 17 + "🚀 XBD 日报自动化流 · 系统仪表盘" + " " * 10 + "║")
    log.info("╠" + "═" * 58 + "╣")

    # 1. 基础运行环境
    log.info("║ 🛠️  运行环境:")
    log.info(f"║    ├─ 项目根目录: {get_app_dir()}")
    log.info(f"║    ├─ 当前解释器: {get_python_exe()}")
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    log.info(
        f"║    └─ 引导脚本:   {'✅ [xbd.bat] 已就绪' if os.path.exists(os.path.join(scripts_dir, 'xbd.bat')) else '❌ 未生成'}"
    )

    # 2. 定时任务 (schtasks)
    log.info("║")
    log.info("║ ⏰ 调度计划 (Windows Task Scheduler):")
    res = subprocess.run(
        f'schtasks /query /tn "{TASK_NAME}" /fo LIST',
        shell=True,
        capture_output=True,
        text=True,
        encoding="gbk",
    )
    if res.returncode == 0:
        log.info(f"║    ├─ 任务状态:   ✅ 已成功注册 ({TASK_NAME})")
        log.info(f"║    ├─ 运行周期:   📅 每周 [{weekdays}]")
        for line in res.stdout.splitlines():
            if "Next Run Time" in line or "下次运行时间" in line:
                val = line.split(":", 1)[1].strip()
                log.info(f"║    └─ 下次触发:   🕒 {val}")
    else:
        log.info(f"║    └─ 任务状态:   ❌ 未发现已注册的计划任务")

    # 3. 系统级集成 (Registry)
    log.info("║")
    log.info("║ ⚙️  系统集成状态:")
    # 检查开机自启
    start_registered = "未知"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REGISTRY_RUN_PATH, 0, winreg.KEY_READ
        ) as key:
            winreg.QueryValueEx(key, REGISTRY_VALUE_NAME)
            start_registered = "✅ 已注册"
    except:
        start_registered = "❌ 未注册"

    # 检查 PATH
    path_in_env = "❌ 未注入"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ
        ) as key:
            val, _ = winreg.QueryValueEx(key, "Path")
            scripts_dir = os.path.dirname(os.path.abspath(__file__))
            if scripts_dir in val:
                path_in_env = "✅ 已激活"
    except:
        pass

    log.info(f"║    ├─ 开机自启动: {start_registered} (配置负载: {auto_start})")
    log.info(f"║    └─ 全局 PATH:  {path_in_env} (配置负载: {auto_path})")

    log.info("╚" + "═" * 58 + "╝\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="XBD 调度与执行引擎")
    parser.add_argument("--install", action="store_true", help="同步配置并安装任务")
    parser.add_argument("--uninstall", action="store_true", help="卸载所有任务")
    parser.add_argument("--status", action="store_true", help="查看当前状态")
    parser.add_argument("--run", action="store_true", help="直接运行日报流")
    args = parser.parse_args()

    if args.install:
        sync_all()
    elif args.uninstall:
        manage_schtask(False, "", "")
        manage_startup(False)
        manage_path(False)
        log.info("✅ 已清理所有调度项。")
    elif args.status:
        show_status()
    elif args.run:
        run_flow()
    else:
        # 如果没有任何参数，默认执行 run_flow 逻辑
        run_flow()

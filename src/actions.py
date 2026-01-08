from typing import Dict
from src.models import TaskModel, CompiledFragment


class ActionGenerator:
    def generate(self, task: TaskModel) -> CompiledFragment:
        raise NotImplementedError

class ClickGenerator(ActionGenerator):
    def generate(self, task: TaskModel) -> CompiledFragment:
        x, y = task.p1, task.p2
        log_cmd = f'    log_info "[STEP] 点击: {x}, {y}"\n'
        adb_cmd = f'    input tap {x} {y}\n'

        # 直接实例化 Pydantic 对象
        return CompiledFragment(main_code=log_cmd + adb_cmd)


class SwipeGenerator(ActionGenerator):
    def generate(self, task: TaskModel) -> CompiledFragment:
        # 默认滑动时间 300ms
        duration = 300
        x1, y1, x2, y2 = task.p1, task.p2, task.p3, task.p4

        log_cmd = f'    log_info "[STEP] 滑动: {x1},{y1} -> {x2},{y2}"\n'
        adb_cmd = f'    input swipe {x1} {y1} {x2} {y2} {duration}\n'

        return CompiledFragment(main_code=log_cmd + adb_cmd)


class WaitGenerator(ActionGenerator):
    def generate(self, task: TaskModel) -> CompiledFragment:
        # 处理默认值，如果 p1 没填，默认等待 1 秒
        seconds = task.p1 if task.p1 else "1"

        log_cmd = f'    log_info "[STEP] 等待: {seconds}秒"\n'
        adb_cmd = f'    sleep {seconds}\n'

        return CompiledFragment(main_code=log_cmd + adb_cmd)


class TextGenerator(ActionGenerator):
    def generate(self, task: TaskModel) -> CompiledFragment:
        raw_txt = task.p1 if task.p1 else ""

        # 简单清洗：处理空格和引号，防止 Shell 语法错误
        # Android input text 不支持空格，通常用 %s 代替
        clean_txt = raw_txt.replace(" ", "%s").replace("'", "").replace('"', '')

        log_cmd = f'    log_info "[STEP] 输入文本: {clean_txt}"\n'
        # 注意给文本加单引号，防止特殊字符炸裂
        adb_cmd = f"    input text '{clean_txt}'\n"

        return CompiledFragment(main_code=log_cmd + adb_cmd)


class KeyGenerator(ActionGenerator):
    def generate(self, task: TaskModel) -> CompiledFragment:
        key_code = task.p1
        log_cmd = f'    log_info "[STEP] 按键: {key_code}"\n'
        adb_cmd = f'    input keyevent {key_code}\n'
        return CompiledFragment(main_code=log_cmd + adb_cmd)


class ShellGenerator(ActionGenerator):
    def generate(self, task: TaskModel) -> CompiledFragment:
        # 直接执行原生 Shell 命令
        cmd = task.p1
        # 双引号转义，防止破坏 echo 语句
        cmd = task.p1 if task.p1 else ""

        if not cmd:
            print("警告: 发现空的 SHELL 指令，已跳过。")
            return CompiledFragment()  # 返回空碎片，不做任何事

        clean_cmd_log = cmd.replace('"', '\\"')

        log_cmd = f'    log_info "[STEP] Shell: {clean_cmd_log}"\n'
        adb_cmd = f'    {cmd}\n'
        return CompiledFragment(main_code=log_cmd + adb_cmd)


class StopGenerator(ActionGenerator):
    def generate(self, task: TaskModel) -> CompiledFragment:
        # 使用模板里的全局变量 ${TARGET_PKG}
        log_cmd = '    log_info "[STEP] 停止应用"\n'
        adb_cmd = '    am force-stop ${TARGET_PKG}\n'
        return CompiledFragment(main_code=log_cmd + adb_cmd)


class StartGenerator(ActionGenerator):
    def generate(self, task: TaskModel) -> CompiledFragment:
        # 使用模板里的全局变量 ${START_URI}
        log_cmd = '    log_info "[STEP] 启动应用"\n'
        adb_cmd = '    am start -n ${START_URI}\n'
        return CompiledFragment(main_code=log_cmd + adb_cmd)


ACTION_REGISTRY: Dict[str, ActionGenerator] = {
    "CLICK": ClickGenerator(),
    "SWIPE": SwipeGenerator(),
    "WAIT":  WaitGenerator(),
    "TEXT":  TextGenerator(),
    "KEY":   KeyGenerator(),
    "SHELL": ShellGenerator(),
    "STOP":  StopGenerator(),
    "START": StartGenerator(),
}
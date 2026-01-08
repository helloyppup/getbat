import os
from typing import List
from src.models import ProjectModel, TaskModel, CompiledFragment
from src.actions import ACTION_REGISTRY


class StressCompiler:
    def __init__(self, project: ProjectModel):
        self.project = project  # 这里面包含了 config 和 plans

    def compile(self) -> str:
        """
        核心方法：将整个项目编译成一个 Shell 脚本字符串
        """

        # === 准备三个“桶” (对应三个插槽) ===
        bucket_functions = []  # 装 function_code
        bucket_setup = []  # 装 setup_code
        bucket_main = []  # 装 main_code (循环体内的逻辑)

        # === 第一阶段：遍历所有 Plan，让 Action 干活 ===
        for plan in self.project.plans:

            # 生成 Sheet 之间的注释，方便阅读
            bucket_main.append(f"\n    # >>> Sheet: {plan.name} (Loop: {plan.loop_count}) <<<\n")
            bucket_main.append(f"    sheet_count=0\n")
            bucket_main.append(f"    while [ $sheet_count -lt {plan.loop_count} ]; do\n")
            bucket_main.append(f"        sheet_count=$((sheet_count + 1))\n")

            # 遍历每一个任务
            for task in plan.tasks:
                generator = ACTION_REGISTRY.get(task.action)

                if not generator:
                    print(f"⚠️ 警告: 未知的指令 [{task.action}]，跳过。")
                    continue

                fragment: CompiledFragment = generator.generate(task)

                if fragment.function_code:
                    bucket_functions.append(fragment.function_code)

                if fragment.setup_code:
                    bucket_setup.append(fragment.setup_code)

                if fragment.main_code:
                    if task.repeat>1:
                        bucket_main.append(f"        # Step Repeat: {task.repeat} times\n")
                        bucket_main.append(f"        step_i=0\n")
                        bucket_main.append(f"        while [ $step_i -lt {task.repeat} ]; do\n")

                        bucket_main.append(fragment.main_code)  # 核心代码放中间

                        bucket_main.append(f"            step_i=$((step_i + 1))\n")
                        bucket_main.append(f"        done\n")
                    else:
                        bucket_main.append(fragment.main_code)
                    # 自动插入哨兵检查
                    bucket_main.append("        check_health_fast\n")

            bucket_main.append("    done\n")  # 结束这个 Sheet 的循环

        # === 第二阶段：组装成文 ===
        # 去重：函数定义不能重复，setup 代码也不建议重复
        final_functions = "\n".join(sorted(list(set(bucket_functions))))
        final_setup = "\n".join(sorted(list(set(bucket_setup))))
        final_main = "".join(bucket_main)

        # === 第三阶段：读取模板并注入 Config ===
        tpl_path = os.path.join(os.path.dirname(__file__), "../shell/stress_template.sh")
        tpl_path = os.path.abspath(tpl_path)
        print(f"模板位置---{tpl_path}")

        try:
            with open(tpl_path, "r", encoding="utf-8") as f:
                template_content = f.read()
        except FileNotFoundError:
            print("Error: Template not found!")
            return "Error: Template not found!"

        # 注入通用 Config
        # 这里把 Python 里的配置值，填入 Shell 模板
        script = template_content \
            .replace("{{TARGET_PKG}}", self.project.config.target_pkg) \
            .replace("{{START_URI}}", self.project.config.start_activity) \
            .replace("{{DURATION_SEC}}", str(self.project.config.duration_sec)) \
            .replace("{{PING_TARGET}}", self.project.config.ping_target) \
            .replace("{{LOG_WHITELIST}}", self.project.config.log_whitelist) \
            .replace("{{DEVICE_NAME}}", self.project.config.device_name or "") \
            .replace("{{FEISHU_WEBHOOK}}", self.project.config.feishu_webhook or "") \
            .replace("# {{CUSTOM_FUNCTIONS}}", final_functions) \
            .replace("# {{SETUP_BLOCK}}", final_setup) \
            .replace("# {{TASK_SEQUENCE_HERE}}", final_main)

        return script
import os
import sys

# 确保能找到 src
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.excel_loader import ExcelLoader
from src.compiler import StressCompiler
from src.launcher_generator import LauncherGenerator


def main():
    # 1. 路径配置
    base_dir = os.path.dirname(os.path.abspath(__file__))
    excel_path = os.path.join(base_dir, "config", "test plan.xlsx")
    dist_dir = os.path.join(base_dir, "dist")

    if not os.path.exists(dist_dir):
        os.makedirs(dist_dir)

    sh_filename = "stress_core.sh"
    sh_file_path = os.path.join(dist_dir, sh_filename)

    print("-" * 30)
    print("初始化压测生成工具...")

    # Loader 加载
    loader = ExcelLoader(excel_path)
    try:
        project = loader.load_project()
        print(f"任务加载成功: {len(project.plans)} 个 Sheet")
    except Exception as e:
        print(f"加载失败: {e}")
        return

    # Compiler 编译
    compiler = StressCompiler(project)
    script_content = compiler.compile()

    # 写入 Shell 文件
    try:
        with open(sh_file_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(script_content)
        print(f"核心脚本生成完毕: {sh_filename}")
    except Exception as e:
        print(f"写入失败: {e}")
        return

    #Generator 生成配套工具 (BAT)
    # 实例化生成器，传入输出目录
    launcher_gen = LauncherGenerator(dist_dir)

    # 生成两个 BAT
    # 注意：这里的第二个参数 "/sdcard/dognoise_stress" 必须和 template.sh 里的 WORKDIR 保持一致！
    launcher_gen.generate_all(
        sh_filename=sh_filename,
        remote_log_dir="/sdcard/dognoise_stress"
    )

    print("\n 全部完成！请查看 dist 目录。")
    print("-" * 30)


if __name__ == "__main__":
    main()
import os
import sys

import pandas as pd
from typing import List, Dict
from src.models import *


DEFAULT_CONFIG = {
    "target_pkg": "cn.net.cloudthink.smartmirror",
    "duration_sec": 86400 * 3,
    "start_activity": ".MainActivity",
    "ping_target": "www.baidu.com",
    "log_whitelist": "MainActivity",
    "device_name": "",
    # 建议把 Webhook 放在 Excel 配置里，这里先保留默认值
    "feishu_webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/e162c2e1-d3b6-4211-9a23-58ff22c76986"
}

class ExcelLoader:
    def __init__(self,file_path=None):
        if file_path is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            EXCEL_FILE = os.path.join(current_dir, "test plan.xlsx")
            file_path = EXCEL_FILE

        self._sheet_cache: Dict[str, List[TaskModel]] = {}
        self.file_path=file_path

    def _load_global_config(self) -> ProjectConfig:
        df_kv = pd.read_excel(self.file_path, sheet_name='Config', usecols=[0, 1], header=None)
        raw_dict = dict(zip(df_kv.iloc[:, 0], df_kv.iloc[:, 1]))
        clean_dict = {k: v for k, v in raw_dict.items() if pd.notna(v)}
        return ProjectConfig(**clean_dict)

    def _load_sheet_tasks(self, sheet_name: str) -> List[TaskModel]:
        # 查缓存：如果读过，直接返回，省得 IO 慢
        if sheet_name in self._sheet_cache:
            return self._sheet_cache[sheet_name]

        try:
            df = pd.read_excel(self.file_path, sheet_name=sheet_name)
        except Exception:
            print(f"警告: 找不到 Sheet [{sheet_name}]")
            return []



        col_map = {
            "action": ["action", "指令", "动作", "cmd", "command"],
            "p1": ["p1", "参数1", "param1","参数1 (p1)"],
            "p2": ["p2", "参数2", "param2","参数2 (p2)"],
            "p3": ["p3", "参数3", "param3","参数3 (p3)"],
            "p4": ["p4", "参数4", "param4","参数4 (p4)"],
            "repeat": ["repeat", "重复次数", "loop"]
        }

        real_cols = {}

        for std_key, aliases in col_map.items():
            # 遍历 DataFrame 的所有列
            for df_col in df.columns:
                # 把列名转小写并去空格，进行比对
                clean_col = str(df_col).lower().strip()
                # 只要匹配到了别名列表里的任何一个
                if clean_col == std_key or clean_col in aliases:
                    real_cols[std_key] = df_col
                    break

        if 'action' not in real_cols:
            print(f"跳过 Sheet [{sheet_name}]: 找不到 'Action' 或 '指令' 列。当前列名: {df.columns.tolist()}")
            return []

        tasks = []

        for idx, row in df.iterrows():
            act_col = real_cols['action']
            raw_action = row.get(act_col)

            if pd.isna(raw_action) or str(raw_action).strip() == "" or str(raw_action).lower() == "nan":
                continue

            p1 = row.get(real_cols.get('p1'))
            p2 = row.get(real_cols.get('p2'))
            p3 = row.get(real_cols.get('p3'))
            p4 = row.get(real_cols.get('p4'))
            repeat = row.get('repeat', 1)


            def clean_val(v):
                if pd.isna(v) or str(v).lower() == 'nan': return None
                return str(v).strip()

            try:
                task = TaskModel(
                    action=str(raw_action).strip(),
                    p1=clean_val(p1),
                    p2=clean_val(p2),
                    p3=clean_val(p3),
                    p4=clean_val(p4)
                )
                tasks.append(task)
            except Exception as e:
                print(f"行解析失败 (Sheet: {sheet_name}, Row: {idx + 2}): {e}")

        # 存入缓存
        self._sheet_cache[sheet_name] = tasks
        return tasks

    def load_project(self) -> ProjectModel:
        print(f"正在加载项目: {self.file_path}")

        # 1. 调用方法1：拿配置
        config = self._load_global_config()

        # 2. 读取执行计划
        plans = []
        try:
            # 重新读取 Config Sheet 来找计划表
            df_full = pd.read_excel(self.file_path, sheet_name='Config')
        except Exception:
            # 防御：万一 Config sheet 都不存在
            return ProjectModel(config=config, plans=[])

        # 模糊匹配列名
        seq_col = next((c for c in df_full.columns if "执行顺序" in str(c) or "Sheet" in str(c)), None)
        loop_col = next((c for c in df_full.columns if "本轮循环" in str(c) or "Loop" in str(c)), None)

        # 只有当找到了“执行顺序”列，才继续
        if seq_col:
            # 【补丁1】安全切片：只有 loop_col 存在时才把它加进选择列表
            cols_to_use = [seq_col]
            if loop_col:
                cols_to_use.append(loop_col)

            # 过滤掉空的 Sheet 名
            plan_df = df_full[cols_to_use].dropna(subset=[seq_col])

            for _, row in plan_df.iterrows():
                sheet_name = str(row[seq_col]).strip()
                # 跳过无关行
                if sheet_name in ["执行顺序", "Sheet Name", "nan", ""]:
                    continue

                # 先给默认值 1
                loop_count = 1
                if loop_col and pd.notna(row.get(loop_col)):
                    try:
                        # 先转 float 再转 int，防止 Excel 读出来是 5.0 导致报错
                        loop_count = int(float(row[loop_col]))
                    except ValueError:
                        print(f"Sheet [{sheet_name}] 循环次数格式错误，重置为 1")
                        loop_count = 1

                # 读取该 Sheet 的任务
                raw_tasks = self._load_sheet_tasks(sheet_name)

                if not raw_tasks:
                    print(f" Sheet [{sheet_name}] 是空的或不存在，跳过。")
                    continue

                # 组装 Plan
                plan = PlanModel(
                    name=sheet_name,
                    loop_count=loop_count,
                    tasks=raw_tasks
                )
                plans.append(plan)

        return ProjectModel(config=config, plans=plans)



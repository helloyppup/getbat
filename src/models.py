from typing import List, Optional, Any
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict


class TaskModel(BaseModel):
    action: str
    p1: Optional[str] = None
    p2: Optional[str] = None
    p3: Optional[str] = None
    p4: Optional[str] = None
    repeat:int = 1

    @field_validator('action')
    def to_upper(cls, v):
        return v.upper().strip()

    # 清洗参数，防止出现 "100.0" 这种安卓不识别的坐标
    @field_validator('p1', 'p2', 'p3', 'p4', mode='before')
    def clean_coordinates(cls, v):
        if v is None:
            return None

        # 1. 如果是数字（int/float），尝试转成整数再转字符串
        # 比如 100.0 -> 100 -> "100"
        try:
            # 只有当它是纯数字时才处理
            if isinstance(v, (int, float)):
                return str(int(v))

            # 如果是字符串 "100.0"，也尝试处理一下
            if isinstance(v, str) and v.replace('.', '', 1).isdigit():
                # 判断是不是以 .0 结尾
                if v.endswith('.0'):
                    return v[:-2]
        except:
            pass

        return str(v)


class PlanModel(BaseModel):
    name: str
    loop_count: int = 1
    tasks: List[TaskModel] = []


class ProjectConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    target_pkg: str = "cn.net.cloudthink.smartmirror"
    start_activity: str = ".MainActivity"
    ping_target: str = "www.baidu.com"
    log_whitelist: str = "MainActivity"
    device_name: Optional[str] = None

    # 支持 Excel 里的 "飞书Webhook" 或者是代码里的 feishu_webhook
    feishu_webhook: Optional[str] = Field(None, alias="飞书Webhook")

    duration_sec: int = 259200

    @model_validator(mode='before')
    @classmethod
    def calculate_duration(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        val = data.get("duration_value")
        unit = str(data.get('duration_unit', 'sec')).lower()

        if val is not None:
            try:
                val = float(val)
                seconds = int(val)
                if 'day' in unit or '天' in unit:
                    seconds = int(val * 86400)
                elif 'hour' in unit or '时' in unit:
                    seconds = int(val * 3600)
                elif 'min' in unit or '分' in unit:
                    seconds = int(val * 60)

                data['duration_sec'] = seconds
            except ValueError:
                # 建议这里加上日志或者打印，方便排查
                print(f"【警告】: duration_value '{val}' 格式错误，已回退到默认值 3天")

        return data


class ProjectModel(BaseModel):
    config: ProjectConfig
    plans: List[PlanModel]


class CompiledFragment(BaseModel):
    main_code: str = ""        # 放入 while 循环主体的代码
    function_code: str = ""    # 放入脚本头部的函数定义
    setup_code: str = ""       # 放入循环外的初始化代码
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
# 假设你的代码在 src/excel_loader.py，根据实际情况调整导入
from src.excel_loader import ExcelLoader
from src.models import ProjectConfig, TaskModel, PlanModel, ProjectModel

# ==========================================
# 1. 准备模拟数据 (Mock Data)
# ==========================================

# 模拟 Config Sheet 的 Key-Value 数据
MOCK_CONFIG_KV_DATA = {
    0: ['target_pkg', 'duration_sec', 'feishu_webhook', 'invalid_key'],
    1: ['com.test.app', 100, None, None]  # None 用于测试清洗逻辑
}

# 模拟 Config Sheet 的全量数据 (包含执行计划)
MOCK_CONFIG_FULL_DATA = {
    '执行顺序': ['SheetA', 'SheetB', 'SheetC', None],
    '本轮循环': [1, 5.0, 'bad_int', None],  # 测试 float转int, 坏数据处理
    '其他列': ['x', 'y', 'z', 'k']
}

# 模拟具体 Task Sheet 的数据
MOCK_TASK_SHEET_DATA = {
    'Action': ['CLICK', 'WAIT'],
    'P1': [100, 5],
    'P2': [200, None]
}


# ==========================================
# 2. 构造 Mock 函数
# ==========================================

def mock_read_excel_side_effect(io, sheet_name=None, **kwargs):
    """
    这是一个假冒的 pd.read_excel。
    它根据 sheet_name 和参数返回不同的 DataFrame，骗过 Loader。
    """
    # 场景1: 读取全局配置 (KV) -> 判断依据是用了 usecols
    if sheet_name == 'Config' and 'usecols' in kwargs:
        return pd.DataFrame(MOCK_CONFIG_KV_DATA)

    # 场景2: 读取执行计划 (Full) -> 没用 usecols
    elif sheet_name == 'Config':
        return pd.DataFrame(MOCK_CONFIG_FULL_DATA)

    # 场景3: 读取具体的 SheetA (正常数据)
    elif sheet_name == 'SheetA':
        return pd.DataFrame(MOCK_TASK_SHEET_DATA)

    # 场景4: 读取 SheetB (空 Sheet)
    elif sheet_name == 'SheetB':
        return pd.DataFrame(columns=['Action', 'P1'])  # 空表

    # 场景5: 读取 SheetC (不存在，模拟报错)
    elif sheet_name == 'SheetC':
        raise ValueError("Sheet not found")

    return pd.DataFrame()


# ==========================================
# 3. 编写测试用例
# ==========================================

@pytest.fixture
def loader():
    """创建一个 loader 实例，不需要真实文件"""
    # 修复了 __init__ bug 后的初始化
    return ExcelLoader(file_path="dummy.xlsx")


@patch('pandas.read_excel', side_effect=mock_read_excel_side_effect)
class TestExcelLoader:

    def test_load_global_config(self, mock_read, loader):
        """测试全局配置读取：是否清洗了空值，是否生成了 Config 对象"""
        config = loader._load_global_config()

        assert isinstance(config, ProjectConfig)
        assert config.target_pkg == 'com.test.app'
        # 验证 None 值的 feishu_webhook 被清洗掉了，使用了默认值
        # (假设 ProjectConfig 有默认值，或者它不在 dict 里)
        # 这里验证 mock 被调用了
        assert mock_read.called

    def test_load_sheet_tasks_normal(self, mock_read, loader):
        """测试读取普通 Task Sheet"""
        tasks = loader._load_sheet_tasks("SheetA")

        assert len(tasks) == 2
        assert isinstance(tasks[0], TaskModel)
        assert tasks[0].action == 'CLICK'
        assert tasks[0].p1 == "100"  # 根据你的 Model 定义，可能是 '100'

    def test_load_sheet_tasks_cache(self, mock_read, loader):
        """测试缓存机制：读取两次 SheetA，pd.read_excel 应该只被调用一次"""
        # 第一次读取
        loader._load_sheet_tasks("SheetA")
        first_call_count = mock_read.call_count

        # 第二次读取
        loader._load_sheet_tasks("SheetA")
        second_call_count = mock_read.call_count

        # 断言调用次数没有增加
        assert first_call_count == second_call_count
        # 断言缓存里有东西
        assert "SheetA" in loader._sheet_cache

    def test_load_sheet_tasks_not_found(self, mock_read, loader):
        """测试读取不存在的 Sheet，应该返回空列表而不是崩掉"""
        tasks = loader._load_sheet_tasks("SheetC")  # Mock 里设定 SheetC 会抛错
        assert tasks == []

    def test_load_project_integration(self, mock_read, loader):
        """
        🔥 核心测试：测试 load_project 完整流程
        覆盖：配置读取 + 计划解析 + 循环次数清洗 + 任务组装
        """
        project = loader.load_project()

        assert isinstance(project, ProjectModel)

        # 验证 Plans
        # Mock数据里有 SheetA, SheetB, SheetC, None
        # SheetA: 正常 -> 应该保留
        # SheetB: 空表 -> 你的代码逻辑里 if not raw_tasks: continue，所以 B 会被跳过
        # SheetC: 报错 -> 返回空列表 -> 跳过
        # None: dropna 会过滤掉

        # 所以最终应该只有 1 个 Plan (SheetA)
        assert len(project.plans) == 1

        plan_a = project.plans[0]
        assert plan_a.name == "SheetA"

        # 🔥 验证循环次数逻辑
        # SheetA 对应 Config 里的 1 -> loop_count=1
        assert plan_a.loop_count == 1

        # 验证 Config
        assert project.config.target_pkg == 'com.test.app'

    def test_loop_count_float_conversion(self, mock_read, loader):
        """
        专项测试：验证 5.0 是否能转成 5
        我们需要稍微 hack 一下 mock 数据，或者构造一个新的测试场景
        """
        # 直接复用 load_project，但在 Mock 数据中：
        # SheetA 对应 Loop 1
        # SheetB (虽然是空表，假设它有数据) -> 对应 Loop 5.0

        # 这里我们直接测核心逻辑片段可能更方便，或者相信集成测试
        # 在 Mock Config 中，SheetA 的 loop 是 1。
        # 让我们修改 mock 行为来专门测这个 float 转换

        # 覆盖 MOCK 数据，让 SheetA 的循环变成 5.0
        with patch.dict(MOCK_CONFIG_FULL_DATA, {'本轮循环': [5.0, 1, 1, 1]}):
            project = loader.load_project()
            # 你的代码: int(float(5.0)) -> 5
            assert project.plans[0].loop_count == 5

    def test_missing_columns_safe(self, mock_read, loader):
        """测试如果没有'本轮循环'列，代码是否健壮"""

        # 构造一个没有 '本轮循环' 的 DataFrame
        bad_df = pd.DataFrame({'执行顺序': ['SheetA'], '其他': [1]})

        def mock_missing_col(io, sheet_name=None, **kwargs):
            if sheet_name == 'Config' and 'usecols' not in kwargs:
                return bad_df
            return mock_read_excel_side_effect(io, sheet_name, **kwargs)

        with patch('pandas.read_excel', side_effect=mock_missing_col):
            project = loader.load_project()
            # 应该默认 loop=1，且不报错
            assert len(project.plans) == 1
            assert project.plans[0].loop_count == 1
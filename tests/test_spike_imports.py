"""测试 spike/insights/ 脚本能正常 import (M-26 修复)。

旧实现: 5 个脚本头部 sys.path.insert(0, dirname(__file__)) + from _common import ...
依赖隐式相对导入, 触发 sys.path 被污染, 跨目录跑可能 ImportError。

修复后: 应使用 from spike.insights._common import ... 绝对导入。
"""
import importlib
import sys


def test_spike_s11_clustering_imports_without_sys_path_hack():
    """M-26: s11_clustering 不依赖 sys.path hack, 直接 import 不抛。"""
    # 模拟"clean sys.path" (移除 spike/insights/ 路径后, 仍能 import)
    saved_path = list(sys.path)
    try:
        # 删除所有 spike 相关路径, 强制走 package import
        sys.path = [p for p in saved_path if 'spike' not in p]
        # 清缓存避免上一次 sys.path.insert 的影响
        for k in list(sys.modules):
            if k.startswith('spike.insights.'):
                del sys.modules[k]
        # 重新加入项目根 (project root) 让 spike 包可被找到
        project_root = r'D:\Users\Katysia\Desktop\EyeFocus Insight'
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        m = importlib.import_module('spike.insights.s11_clustering')
        # 模块应有 run_spike 入口
        assert hasattr(m, 'run_spike'), "s11_clustering 应暴露 run_spike 入口"
    finally:
        sys.path = saved_path


def test_spike_s12_changepoint_imports_without_sys_path_hack():
    """M-26: s12_changepoint 同样用绝对导入。"""
    saved_path = list(sys.path)
    try:
        sys.path = [p for p in saved_path if 'spike' not in p]
        for k in list(sys.modules):
            if k.startswith('spike.insights.'):
                del sys.modules[k]
        project_root = r'D:\Users\Katysia\Desktop\EyeFocus Insight'
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        m = importlib.import_module('spike.insights.s12_changepoint')
        assert hasattr(m, 'run_spike'), "s12_changepoint 应暴露 run_spike 入口"
    finally:
        sys.path = saved_path


def test_spike_s13_anomaly_imports_without_sys_path_hack():
    """M-26: s13_anomaly 同样用绝对导入。"""
    saved_path = list(sys.path)
    try:
        sys.path = [p for p in saved_path if 'spike' not in p]
        for k in list(sys.modules):
            if k.startswith('spike.insights.'):
                del sys.modules[k]
        project_root = r'D:\Users\Katysia\Desktop\EyeFocus Insight'
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        m = importlib.import_module('spike.insights.s13_anomaly')
        assert hasattr(m, 'run_spike'), "s13_anomaly 应暴露 run_spike 入口"
    finally:
        sys.path = saved_path


def test_spike_s14_temporal_imports_without_sys_path_hack():
    """M-26: s14_temporal 同样用绝对导入。"""
    saved_path = list(sys.path)
    try:
        sys.path = [p for p in saved_path if 'spike' not in p]
        for k in list(sys.modules):
            if k.startswith('spike.insights.'):
                del sys.modules[k]
        project_root = r'D:\Users\Katysia\Desktop\EyeFocus Insight'
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        m = importlib.import_module('spike.insights.s14_temporal')
        assert hasattr(m, 'run_spike'), "s14_temporal 应暴露 run_spike 入口"
    finally:
        sys.path = saved_path


def test_spike_s15_attribution_imports_without_sys_path_hack():
    """M-26: s15_attribution 同样用绝对导入。"""
    saved_path = list(sys.path)
    try:
        sys.path = [p for p in saved_path if 'spike' not in p]
        for k in list(sys.modules):
            if k.startswith('spike.insights.'):
                del sys.modules[k]
        project_root = r'D:\Users\Katysia\Desktop\EyeFocus Insight'
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        m = importlib.import_module('spike.insights.s15_attribution')
        assert hasattr(m, 'run_spike'), "s15_attribution 应暴露 run_spike 入口"
    finally:
        sys.path = saved_path


def test_spike_s11_no_sys_path_hack_in_source():
    """M-26: 源代码不应再含 sys.path.insert(0, os.path.dirname(__file__))。

    用文本搜索确保 spike/insights/ 5 个 spike 脚本都已清掉 hack。
    """
    from pathlib import Path
    spike_dir = Path(r'D:\Users\Katysia\Desktop\EyeFocus Insight\spike\insights')
    for script in ['s11_clustering.py', 's12_changepoint.py', 's13_anomaly.py',
                   's14_temporal.py', 's15_attribution.py']:
        src = (spike_dir / script).read_text(encoding='utf-8')
        assert 'sys.path.insert' not in src, f"{script} 仍含 sys.path hack"
        assert 'os.path.dirname(os.path.abspath(__file__))' not in src, \
            f"{script} 仍含 os.path.dirname hack"
        # 应使用 spike.insights._common 绝对导入
        assert 'from spike.insights._common import' in src, \
            f"{script} 应使用 from spike.insights._common import ..."

"""
app — EyeFocus Insight 主程序拆分包

strangler 模式：将 main.py 中的独立类逐步迁移至此包。
main.py 从中 import 并 re-export，保持测试兼容性。
"""

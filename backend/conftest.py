"""Pytest 根级 conftest。

放置于 backend/ 下，使 pytest 在 prepend 模式下将 backend/ 加入 sys.path，
便于 `import app...`。
"""

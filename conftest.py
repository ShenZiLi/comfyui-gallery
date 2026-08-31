"""pytest 根 conftest：src layout 下保证可导入 artmirror 包（与 pythonpath 双保险）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

"""pytest 根 conftest：仓库根即包，保证 artmirror / artmirror_embed 等可直接导入。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

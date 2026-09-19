"""薄壳：保持 `python apps/cli.py` 与 `gym` 两条入口等价。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gym.cli import main  # noqa: E402

if __name__ == "__main__":
    main()

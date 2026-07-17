import sys
from pathlib import Path

WORKER_ROOT = Path(__file__).resolve().parents[2] / "apps" / "worker"
sys.path.insert(0, str(WORKER_ROOT))

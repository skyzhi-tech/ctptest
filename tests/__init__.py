from pathlib import Path
import tempfile


def temp_directory():
    base = Path(__file__).resolve().parents[1] / "data" / "test-tmp"
    base.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=base)

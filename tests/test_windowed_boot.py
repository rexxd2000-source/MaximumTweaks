"""Windowed (console=False) builds must boot cleanly.

The frozen exe ships windowed so no console window ever pops up when the
GUI opens; in that mode Python starts with sys.stdout/sys.stderr = None.
Everything that runs at import/boot - especially the logger - has to survive
that without raising, and CLI output must still work when a console exists.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_maxlog_boots_with_no_stdout(tmp_path):
    """maxlog's console mirror must not be attached when stdout is None."""
    out = tmp_path / "probe.txt"
    # Point the log at a private file first: the subprocess must not fight
    # the in-process suite's handlers over Logs\\maximumtweaks.log rotation.
    code = (
        "import sys\n"
        "sys.stdout = None\n"
        "sys.stderr = None\n"
        "from pathlib import Path\n"
        "import config.app_config as _cfg\n"
        f"_cfg.LOG_FILE = Path(r'{tmp_path / 'maxlog.log'}')\n"
        "import maxlog\n"
        "maxlog.logger.info('windowed boot')\n"
        "maxlog.logger.error('windowed error')\n"
        f"open(r'{out}', 'w', encoding='utf-8').write('ok')\n"
    )
    res = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                         capture_output=True, stdin=subprocess.DEVNULL,
                         timeout=120)
    assert res.returncode == 0, res.stderr
    assert out.read_text(encoding="utf-8") == "ok"
    assert "windowed boot" in (tmp_path / "maxlog.log").read_text(
        encoding="utf-8")

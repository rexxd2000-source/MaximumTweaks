"""Package entry point so PyInstaller can run this as a real package."""
import sys

from admin_desktop.main import main

if __name__ == "__main__":
    sys.exit(main())
import sys
from unittest.mock import MagicMock

# pydualsense loads libhidapi at import time via ctypes; mock it so the test
# suite runs on any machine without the system library installed.
sys.modules.setdefault("hidapi", MagicMock())

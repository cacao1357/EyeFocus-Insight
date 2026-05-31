"""
pytest configuration — shared path setup for all tests.
"""

import sys
import os

# Add project root to Python path so all test files can import from spike/, analyzer/, etc.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

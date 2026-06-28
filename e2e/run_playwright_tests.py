#!/usr/bin/env python3
"""
Runner for Playwright E2E tests
Uses Playwright via Python instead of Node.js
"""

import subprocess
import sys
import os

def run_playwright_tests():
    """Run Playwright tests using Python"""
    # Install Playwright first
    print("Installing Playwright...")
    subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)

    # Install Playwright browsers
    print("Installing Playwright browsers...")
    subprocess.run([sys.executable, "-m", "playwright", "install"], check=True)

    # Run tests
    print("\nRunning E2E tests...")
    result = subprocess.run([
        sys.executable, "-m", "pytest",
        "tests/",
        "-v",
        "--tb=short"
    ])

    return result.returncode

if __name__ == "__main__":
    os.chdir(os.path.dirname(__file__))
    exit_code = run_playwright_tests()
    sys.exit(exit_code)
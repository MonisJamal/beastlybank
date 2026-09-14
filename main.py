"""
Universal entry point for hosting providers that default to main.py.
Redirects execution directly to bot.py.
"""
import sys
import runpy

if __name__ == "__main__":
    runpy.run_path("bot.py", run_name="__main__")

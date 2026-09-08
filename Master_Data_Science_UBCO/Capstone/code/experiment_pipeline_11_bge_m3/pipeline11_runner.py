#!/usr/bin/env python3
"""Compatibility-free entry point for Pipeline 11.

The implementation lives in ``pipeline10_runner.py`` temporarily so diffs from
Pipeline 10 stay easy to inspect. Use this file for new Pipeline 11 runs.
"""

from pipeline10_runner import main


if __name__ == "__main__":
    main()

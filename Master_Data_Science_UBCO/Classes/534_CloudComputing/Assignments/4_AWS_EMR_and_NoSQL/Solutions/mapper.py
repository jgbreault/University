#!/usr/bin/env python3
import sys

for line in sys.stdin:
    line = line.strip()
    parts = line.split('\t')

    if len(parts) >= 3:
        word = parts[0].lower()
        year = parts[1]
        count = parts[2]

        if "google" in word:
            print(f"{year}\t{count}")
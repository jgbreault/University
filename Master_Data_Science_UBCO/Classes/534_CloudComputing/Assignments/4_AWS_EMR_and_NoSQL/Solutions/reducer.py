#!/usr/bin/env python3
import sys

current_year = None
current_count = 0

for line in sys.stdin:
    line = line.strip()
    year, count = line.split('\t', 1)

    try:
        count = int(count)
    except ValueError:
        continue

    if current_year == year:
        current_count += count
    else:
        if current_year:
            print(f"{current_year}\t{current_count}")
        current_year = year
        current_count = count

if current_year == year:
    print(f"{current_year}\t{current_count}")
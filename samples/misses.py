import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.lineparse import SetIndex, parse_line  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
offers = json.load(open(os.path.join(HERE, "offers.json"), encoding="utf-8"))
idx = SetIndex.load()

# Classify every set-miss: is there ANY alphabetic content left that could have
# named a set, or did the seller simply not state one?
buckets = collections.Counter()
had_content = []
for o in offers:
    p = parse_line(o["line"], idx, o.get("eng_name", ""), o.get("rus_name", ""), [o.get("name", "")])
    if p.set_code:
        continue
    # strip punctuation/digits from residue to see if real words remain
    words = re.findall(r"[A-Za-zА-Яа-я]{2,}", p.residue)
    if not words:
        buckets["seller stated nothing (unknowable)"] += 1
    else:
        buckets["words left over -> possible miss"] += 1
        had_content.append((o["source"], o["line"], p.residue, words))

print("=== set-miss breakdown ===")
for k, n in buckets.most_common():
    print("  %-38s %s" % (k, n))
print()
print("=== all misses that still had words (candidates for improvement) ===")
seen = collections.Counter()
for src, line, res, words in had_content:
    key = " ".join(words).lower()
    seen[key] += 1
for key, n in seen.most_common(40):
    print("  %3d  %s" % (n, key[:100]))

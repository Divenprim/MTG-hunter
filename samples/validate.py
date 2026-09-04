import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.lineparse import SetIndex, parse_line  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
offers = json.load(open(os.path.join(HERE, "offers.json"), encoding="utf-8"))
idx = SetIndex.load()

stats = collections.Counter()
conf = collections.Counter()
residues = collections.Counter()
per_source_miss = collections.defaultdict(int)
per_source_total = collections.Counter()
examples = []

for o in offers:
    p = parse_line(o["line"], idx, o.get("eng_name", ""), o.get("rus_name", ""), [o.get("name", "")])
    stats["total"] += 1
    per_source_total[o["source"]] += 1
    if p.set_code:
        stats["set"] += 1
    else:
        per_source_miss[o["source"]] += 1
    if p.collector_number:
        stats["number"] += 1
    if p.language:
        stats["lang"] += 1
    if p.condition:
        stats["cond"] += 1
    if p.foil is not None:
        stats["foil_stated"] += 1
    if p.treatments:
        stats["treatments"] += 1
    if p.mixed:
        stats["mixed"] += 1
    if p.price_in_line:
        stats["price"] += 1
    conf[p.set_confidence] += 1
    if p.residue:
        residues[p.residue.lower()] += 1
    examples.append((o, p))

t = stats["total"]
print("=== coverage over %d real listings ===" % t)
for k in ("set", "number", "lang", "cond", "foil_stated", "treatments", "price", "mixed"):
    print("  %-13s %5d  %5.1f%%" % (k, stats[k], 100.0 * stats[k] / t))

print()
print("=== set confidence ===")
for k, n in conf.most_common():
    print("  %-13s %5d  %5.1f%%" % (k, n, 100.0 * n / t))

print()
print("=== set-miss rate by source ===")
for src, tot in per_source_total.most_common():
    miss = per_source_miss[src]
    print("  %-22s %4d/%4d missed  %5.1f%%" % (src, miss, tot, 100.0 * miss / tot))

print()
print("=== top 30 leftover residues (what we still do not understand) ===")
for r, n in residues.most_common(30):
    print("  %4d  %s" % (n, repr(r)[:110]))

print()
print("=== 12 fully parsed examples ===")
shown = 0
for o, p in examples:
    if p.set_code and p.language and p.condition:
        print("  LINE : %s" % repr(o["line"])[:120])
        print("       -> %s #%s %s %s foil=%s %s" % (
            p.set_code, p.collector_number, p.language, p.condition, p.foil, p.treatments))
        shown += 1
    if shown >= 12:
        break

print()
print("=== 12 set-misses ===")
shown = 0
for o, p in examples:
    if not p.set_code:
        print("  %-20s %s" % (o["source"][:20], repr(o["line"])[:120]))
        print("       residue=%s warn=%s" % (repr(p.residue)[:70], p.warnings))
        shown += 1
    if shown >= 12:
        break

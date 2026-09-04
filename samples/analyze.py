import collections
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
offers = json.load(open(os.path.join(HERE, "offers.json"), encoding="utf-8"))

print("offers:", len(offers))
print()
print("--- by source ---")
for s, n in collections.Counter(o["source"] for o in offers).most_common():
    print("  %-22s %s" % (s, n))

print()
print("--- has HTML tags in line ---")
html_n = sum(1 for o in offers if "<" in o["line"])
print("  %d / %d" % (html_n, len(offers)))

print()
print("--- price present inside line? ---")
withprice = sum(1 for o in offers if re.search(r"\d{2,6}", o["line"]))
print("  %d" % withprice)

print()
print("=== stratified sample: up to 6 lines per seller ===")
by_seller = collections.defaultdict(list)
for o in offers:
    key = (o["source"], o["seller"]["name"])
    by_seller[key].append(o)

for (src, name), lst in sorted(by_seller.items(), key=lambda kv: -len(kv[1]))[:22]:
    print()
    print("### %s / %s  (%d offers)" % (src, name, len(lst)))
    for o in lst[:6]:
        print("   ", repr(o["line"])[:170])

"""One-off: simplify Natural Earth admin-0 countries (India point-of-view boundaries, public domain)
into tools/world.json for the article card images.

Usage: python3 tools/make_world.py /path/to/ind.geojson
"""
import json, pathlib, sys

TOL = 0.12  # degrees; Douglas-Peucker tolerance (card images are small)

def dp(pts, tol):
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = (dx * dx + dy * dy) ** 0.5 or 1e-12
    i, dmax = 0, -1.0
    for k in range(1, len(pts) - 1):
        d = abs(dy * pts[k][0] - dx * pts[k][1] + x2 * y1 - y2 * x1) / norm
        if d > dmax:
            i, dmax = k, d
    if dmax <= tol:
        return [pts[0], pts[-1]]
    return dp(pts[: i + 1], tol)[:-1] + dp(pts[i:], tol)

def area(r):
    return abs(sum(r[i][0] * r[i - 1][1] - r[i - 1][0] * r[i][1] for i in range(len(r)))) / 2

src = json.load(open(sys.argv[1]))
out = {}
for f in src["features"]:
    p, g = f["properties"], f["geometry"]
    if p["ADMIN"] == "Antarctica":
        continue
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    rings = []
    for poly in polys:
        outer = poly[0]
        if area(outer) < 0.15 and p["ADMIN"] != "India":  # drop specks, keep all of India
            continue
        pts = [(round(x, 2), round(y, 2)) for x, y in outer]
        h = len(pts) // 2  # a closed ring starts and ends on the same point: simplify its two halves
        s = dp(pts[: h + 1], TOL)[:-1] + dp(pts[h:], TOL)
        if len(s) >= 4:
            rings.append(s)
    if rings:
        out[p["ADMIN"]] = {"iso": p["ISO_A3"] if p["ISO_A3"] != "-99" else p["ADM0_A3"],
                           "c": [round(p["LABEL_X"], 2), round(p["LABEL_Y"], 2)], "r": rings}
dst = pathlib.Path(__file__).with_name("world.json")
dst.write_text(json.dumps(out, separators=(",", ":")))
print(len(out), "countries,", sum(len(r) for v in out.values() for r in v["r"]), "points,", dst.stat().st_size // 1024, "KB")

"""Small lon/lat geometry helpers shared by the data scripts (standard library only)."""
import math


def douglas_peucker(pts, tol):
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    tol2 = tol * tol
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        best, best_i = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if seg == 0:
                d = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
                d = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d > best:
                best, best_i = d, i
        if best > tol2:
            keep[best_i] = True
            stack += [(a, best_i), (best_i, b)]
    return [p for p, k in zip(pts, keep) if k]


def ring_area(r):
    """Planar (degree^2) area of a closed ring."""
    return abs(sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))) / 2


def geodesic_ring_area_km2(ring):
    """Area of a lon/lat ring on a sphere (R = 6371 km)."""
    R = 6371.0088
    total = 0.0
    for i in range(len(ring) - 1):
        lon1, lat1 = map(math.radians, ring[i])
        lon2, lat2 = map(math.radians, ring[i + 1])
        total += (lon2 - lon1) * (2 + math.sin(lat1) + math.sin(lat2))
    return abs(total) * R * R / 2


def polygon_area_km2(rings):
    return geodesic_ring_area_km2(rings[0]) - sum(geodesic_ring_area_km2(r) for r in rings[1:])


def simplify_polygon(rings, tol):
    out = []
    for i, ring in enumerate(rings):
        if i > 0 and ring_area(ring) < 4 * tol * tol:
            continue  # drop holes too small to see
        s = douglas_peucker(ring, tol)
        if len(s) < 4:
            if i > 0:
                continue
            s = ring  # never lose an outer ring
        out.append([[round(x, 4), round(y, 4)] for x, y in s])
    return out


def in_ring(x, y, ring):
    c = False
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[i - 1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = not c
    return c


def in_multipolygon(x, y, polys):
    return any(in_ring(x, y, p[0]) and not any(in_ring(x, y, h) for h in p[1:]) for p in polys)


def grid_points(polys, step):
    xs = [x for p in polys for x, _ in p[0]]
    ys = [y for p in polys for _, y in p[0]]
    pts = []
    y = math.floor(min(ys) / step) * step + step / 2
    while y < max(ys):
        x = math.floor(min(xs) / step) * step + step / 2
        while x < max(xs):
            if in_multipolygon(x, y, polys):
                pts.append((round(x, 3), round(y, 3)))
            x += step
        y += step
    return pts


def sample_points(polys, step, max_points):
    """Points on a regular grid inside the polygons, at least one, at most max_points (thinned evenly)."""
    pts = grid_points(polys, step)
    s = step
    while not pts and s > step / 64:  # small polygon: refine until something lands inside
        s /= 2
        pts = grid_points(polys, s)
        if pts:
            pts = [pts[len(pts) // 2]]
    if not pts:  # last resort: a vertex of the largest outer ring
        ring = max((p[0] for p in polys), key=len)
        pts = [tuple(round(v, 3) for v in ring[0])]
    if len(pts) > max_points:
        pts = [pts[round((i + 0.5) * len(pts) / max_points - 0.5)] for i in range(max_points)]
    return pts


def label_point(polys):
    """A point inside the largest polygon, near its middle (for bubbles and labels)."""
    big = max(polys, key=lambda p: ring_area(p[0]))
    xs = [x for x, _ in big[0]]
    ys = [y for _, y in big[0]]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    if in_multipolygon(cx, cy, [big]):
        return round(cx, 3), round(cy, 3)
    for n in (8, 16, 32, 64):
        step = max(max(xs) - min(xs), max(ys) - min(ys)) / n
        pts = grid_points([big], step)
        if pts:
            return min(pts, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
    return tuple(round(v, 3) for v in big[0][0])

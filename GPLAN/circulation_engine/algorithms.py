"""Connected routing on a fixed graph of complete shared-wall runs.

A node activates one entire coordinated wall run. Its weight is that run's
length, not the distance between its junctions. This makes the shortest mode's
precise (limited) claim independently reproducible.
"""

from dataclasses import dataclass
import heapq
from collections import deque

from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from .models import EPS, fail


@dataclass(frozen=True)
class WallGroup:
    id: str
    orientation: str
    coordinate: float
    start: float
    end: float
    negative: tuple
    positive: tuple
    supported: bool

    @property
    def length(self):
        return self.end - self.start

    @property
    def rooms(self):
        return set(self.negative) | set(self.positive)

    @property
    def line(self):
        if self.orientation == "v":
            return LineString([(self.coordinate, self.start), (self.coordinate, self.end)])
        return LineString([(self.start, self.coordinate), (self.end, self.coordinate)])


def wall_graph(request):
    contacts = []
    for index, first in enumerate(request.rooms):
        ax0, ay0, ax1, ay1 = first.bounds
        for second in request.rooms[index + 1:]:
            bx0, by0, bx1, by1 = second.bounds
            y0, y1, x0, x1 = max(ay0, by0), min(ay1, by1), max(ax0, bx0), min(ax1, bx1)
            if y1 - y0 > EPS and (abs(ax1 - bx0) <= EPS or abs(bx1 - ax0) <= EPS):
                negative, positive = (first, second) if abs(ax1 - bx0) <= EPS else (second, first)
                contacts.append(("v", negative.bounds[2], y0, y1, negative.id, positive.id))
            if x1 - x0 > EPS and (abs(ay1 - by0) <= EPS or abs(by1 - ay0) <= EPS):
                negative, positive = (first, second) if abs(ay1 - by0) <= EPS else (second, first)
                contacts.append(("h", negative.bounds[3], x0, x1, negative.id, positive.id))
    contacts.sort()
    runs = []
    for contact in contacts:
        if (runs and runs[-1][0][0] == contact[0] and abs(runs[-1][0][1] - contact[1]) <= EPS
                and contact[2] <= max(c[3] for c in runs[-1]) + EPS):
            runs[-1].append(contact)
        else:
            runs.append([contact])
    room_map = {r.id: r for r in request.rooms}
    groups = []
    for index, run in enumerate(runs):
        orientation, coordinate = run[0][:2]
        negative, positive = tuple(sorted({c[4] for c in run})), tuple(sorted({c[5] for c in run}))
        supported = True
        for room_id in set(negative + positive):
            r = room_map[room_id]
            expected = r.bounds[3] - r.bounds[1] if orientation == "v" else r.bounds[2] - r.bounds[0]
            intervals = [LineString([(c[2], 0), (c[3], 0)]) for c in run if room_id in c[4:]]
            if abs(unary_union(intervals).length - expected) > EPS:
                supported = False
        groups.append(WallGroup(f"wall-{index + 1}", orientation, coordinate, min(c[2] for c in run), max(c[3] for c in run), negative, positive, supported))
    if len(groups) > 96:
        fail("unsupported_complexity", "This plan exceeds the supported 96 shared-wall runs.")
    supported = {g.id: g for g in groups if g.supported}
    graph = {gid: set() for gid in supported}
    for i, first in enumerate(supported.values()):
        for second in list(supported.values())[i + 1:]:
            if first.line.distance(second.line) <= EPS:
                graph[first.id].add(second.id)
                graph[second.id].add(first.id)
    roots = sorted(g.id for g in supported.values() if g.line.distance(Point(request.entry)) <= EPS)
    if not roots:
        fail("unsupported_entry", "Choose an entrance at a shared-wall termination on the exterior. The shifted room sides must be fully covered by contiguous shared walls; a partial side bordering outdoor space cannot be widened safely.",
             unsupported_wall_groups=[g.id for g in groups if not g.supported])
    return supported, graph, roots


def coverage(selected, groups):
    return set().union(*(groups[gid].rooms for gid in selected)) if selected else set()


def connected(selected, graph):
    if not selected:
        return False
    seen, todo = set(), [min(selected)]
    while todo:
        node = todo.pop()
        if node not in seen:
            seen.add(node)
            todo.extend((graph[node] & selected) - seen)
    return seen == selected


def shortest_paths(groups, graph, starts, paid=frozenset()):
    distances, paths, heap = {}, {}, []
    for root in sorted(starts):
        cost = 0.0 if root in paid else groups[root].length
        distances[root], paths[root] = cost, (root,)
        heapq.heappush(heap, (cost, (root,), root))
    while heap:
        cost, path, node = heapq.heappop(heap)
        if (cost, path) != (distances[node], paths[node]):
            continue
        for neighbor in sorted(graph[node]):
            next_cost = cost + (0 if neighbor in paid else groups[neighbor].length)
            next_path = path + (neighbor,)
            if neighbor in path:
                continue
            if neighbor not in distances or (next_cost, next_path) < (distances[neighbor], paths[neighbor]):
                distances[neighbor], paths[neighbor] = next_cost, next_path
                heapq.heappush(heap, (next_cost, next_path, neighbor))
    return distances, paths


def route(request, mode, groups, graph, root):
    required = set(request.required)
    if mode == "shortest":
        if len(required) != 1:
            fail("unsupported_scope", "Shortest route requires exactly one selected destination. Use compact circulation for multiple rooms.")
        distances, paths = shortest_paths(groups, graph, [root])
        terminals = [gid for gid in paths if groups[gid].rooms & required]
        if not terminals:
            fail("infeasible_coverage", "The destination cannot be reached from this entrance along supported shared walls.")
        target = min(terminals, key=lambda gid: (distances[gid], paths[gid]))
        return set(paths[target])
    if mode == "spanning":
        selected, queue, seen = set(), deque([root]), {root}
        while queue and not required <= coverage(selected, groups):
            gid = queue.popleft()
            selected.add(gid)
            for neighbor in sorted(graph[gid]):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        if not required <= coverage(selected, groups):
            fail("infeasible_coverage", "Some required rooms are disconnected from this entrance on the supported wall graph.", room_ids=sorted(required - coverage(selected, groups)))
        return selected
    selected = {root}
    while not required <= coverage(selected, groups):
        missing = required - coverage(selected, groups)
        distances, paths = shortest_paths(groups, graph, selected, selected)
        options = []
        for gid, path in paths.items():
            gain = len(coverage(set(path), groups) & missing)
            if gain:
                options.append((distances[gid] / gain, distances[gid], path))
        if not options:
            fail("infeasible_coverage", "Required rooms cannot be served without crossing an unsupported wall or private room.", room_ids=sorted(missing))
        selected.update(min(options)[2])
    # Coverage-only pruning is unsafe. Every deletion checks root connectivity.
    for gid in sorted(selected - {root}, key=lambda n: (-groups[n].length, n)):
        trial = selected - {gid}
        if connected(trial, graph) and required <= coverage(trial, groups):
            selected = trial
    return selected

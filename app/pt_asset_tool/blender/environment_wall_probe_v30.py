"""Optional visual-only wall-contact guess for foliage without a detected trunk.

Never writes Stage data and never claims an actual support point.  The caller
can leave the original V24 anchor unchanged if this heuristic cannot decide.
"""
import math

from mathutils import Vector
from mathutils.bvhtree import BVHTree


def build_wall_probe(source, tree_faces):
    """Build once from non-vegetation surfaces; game/world scene may be huge."""
    mesh = source.data
    matrix = source.matrix_world
    vertices = [tuple(matrix @ vertex.co) for vertex in mesh.vertices]
    polygons = []
    for poly in mesh.polygons:
        if poly.index not in tree_faces and len(poly.vertices) >= 3:
            polygons.append(tuple(poly.vertices))
    if not polygons:
        return None
    return BVHTree.FromPolygons(vertices, polygons, all_triangles=False, epsilon=0.00001)


def candidate_wall_contact(bvh, source, group):
    """Return (point, unit outward normal, hit distance), or None.

    Samples the lower portion of the foliage bbox, casting horizontally.
    It cannot determine whether the foliage is tree, shrub, or wall decoration.
    """
    if bvh is None or group.get('trunk_faces'):
        return None
    mesh = source.data
    matrix = source.matrix_world
    coords = []
    for idx in group.get('faces', []):
        for vi in mesh.polygons[idx].vertices:
            coords.append(matrix @ mesh.vertices[vi].co)
    if not coords:
        return None
    lo = [min(vec[k] for vec in coords) for k in range(3)]
    hi = [max(vec[k] for vec in coords) for k in range(3)]
    height = max(.1, hi[2]-lo[2])
    width = max(hi[0]-lo[0],hi[1]-lo[1])
    centre_x = .5*(lo[0]+hi[0]); centre_y=.5*(lo[1]+hi[1])
    max_dist = max(.35, min(2.0, width*.40))
    nearest = None
    for frac in (.12, .30, .50):
        origin = Vector((centre_x,centre_y,lo[2]+frac*height))
        for i in range(12):
            angle = 2*math.pi*i/12
            direction = Vector((math.cos(angle),math.sin(angle),0.))
            hit, normal, face_id, distance = bvh.ray_cast(origin,direction,max_dist)
            if hit is None or normal is None or abs(normal.z) > .40 or distance < .0001:
                continue
            if nearest is None or distance < nearest[2]:
                outward = normal.normalized()
                if outward.dot(origin-hit) < 0:
                    outward.negate()
                nearest = (hit.copy(),outward,float(distance))
    return nearest

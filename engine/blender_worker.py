"""
blender_worker.py - Headless Blender script for GLB to 3D-Print conversion,
Smart Splitting & Multi-Part Region/Lasso Extraction.
Executes inside Blender (Windows, macOS, Linux).
"""

import sys
import os
import json
import argparse
import time
import zipfile
import numpy as np
import bpy
import bmesh

def log(msg):
    print(f"[GLB2PRINT-WORKER] {msg}", flush=True)

def parse_args():
    raw_args = sys.argv
    if "--" in raw_args:
        app_args = raw_args[raw_args.index("--") + 1:]
    else:
        app_args = []

    parser = argparse.ArgumentParser(description="Blender GLB to 3D Print Processor & Splitter")
    parser.add_argument("--input", required=True, help="Input GLB file path")
    parser.add_argument("--output-obj", default="", help="Output OBJ file path")
    parser.add_argument("--output-3mf", default="", help="Output 3MF file path")
    parser.add_argument("--texture-res", type=int, default=0, help="Max texture dimension (e.g. 1024, 2048, 0=original)")
    parser.add_argument("--decimate-ratio", type=float, default=1.0, help="Decimation ratio 0.01 - 1.0")
    parser.add_argument("--target-triangles", type=int, default=0, help="Target triangle count (overrides ratio if > 0)")
    parser.add_argument("--ground-z", action="store_true", help="Align bottom of model to Z=0 print bed")
    parser.add_argument("--height-mm", type=float, default=0.0, help="Target model height in mm (0 = keep original scale)")

    # Smart Splitting / Planar Cut options
    parser.add_argument("--split-axis", choices=["none", "x", "y", "z"], default="none", help="Cut plane normal axis")
    parser.add_argument("--split-coord", type=float, default=0.0, help="Cut plane position along split axis")
    parser.add_argument("--plane-point", default="", help="Arbitrary cut plane point 'x,y,z'")
    parser.add_argument("--plane-normal", default="", help="Arbitrary cut plane normal 'nx,ny,nz'")
    parser.add_argument("--add-pegs", action="store_true", help="Add snap-fit male peg & female socket at cut interface")
    parser.add_argument("--peg-radius", type=float, default=2.0, help="Radius of alignment peg in mm (default: 2.0)")
    parser.add_argument("--peg-height", type=float, default=5.0, help="Height of alignment peg in mm (default: 5.0)")
    parser.add_argument("--solidify-mm", type=float, default=0.0, help="Print volume mode: < 0 = Full Solid (slicer infill), > 0 = hollow shell wall mm, 0 = raw mesh")
    parser.add_argument("--split-cap", action="store_true", default=True, help="Cap cut surfaces for watertight printing")
    parser.add_argument("--no-split-cap", dest="split_cap", action="store_false", help="Do not cap cut surfaces")

    # Multi-Part Lasso / Region Extraction
    parser.add_argument("--parts-json", default="", help="Path to JSON file containing part names and face indices")

    return parser.parse_args(app_args)

def export_3mf(filepath, mesh, loop_colors):
    """Exports mesh and colors to a standard 3MF file with color groups."""
    num_verts = len(mesh.vertices)
    verts = np.empty(num_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get('co', verts)
    verts_reshaped = verts.reshape((num_verts, 3))

    num_polys = len(mesh.polygons)
    poly_loop_starts = np.empty(num_polys, dtype=np.int32)
    mesh.polygons.foreach_get('loop_start', poly_loop_starts)

    num_loops = len(mesh.loops)
    loop_verts = np.empty(num_loops, dtype=np.int32)
    mesh.loops.foreach_get('vertex_index', loop_verts)

    tri_v0 = loop_verts[poly_loop_starts]
    tri_v1 = loop_verts[poly_loop_starts + 1]
    tri_v2 = loop_verts[poly_loop_starts + 2]

    c0 = loop_colors[poly_loop_starts, :3]
    c1 = loop_colors[poly_loop_starts + 1, :3]
    c2 = loop_colors[poly_loop_starts + 2, :3]
    tri_colors = np.clip(((c0 + c1 + c2) / 3.0 * 255.0), 0, 255).astype(np.uint8)

    hex_colors = [f"#{r:02X}{g:02X}{b:02X}FF" for r, g, b in tri_colors]
    unique_colors, color_indices = np.unique(hex_colors, return_inverse=True)

    log(f"Building 3MF with {num_verts} vertices, {num_polys} triangles, {len(unique_colors)} color entries...")

    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02">\n',
        '<resources>\n',
        '<m:colorgroup id="1">\n'
    ]

    for c in unique_colors:
        xml_parts.append(f'<m:color color="{c}"/>\n')
    xml_parts.append('</m:colorgroup>\n<object id="2" type="model">\n<mesh>\n<vertices>\n')

    for vx, vy, vz in verts_reshaped:
        xml_parts.append(f'<vertex x="{vx:.4f}" y="{vy:.4f}" z="{vz:.4f}"/>\n')
    xml_parts.append('</vertices>\n<triangles>\n')

    for i in range(num_polys):
        xml_parts.append(f'<triangle v1="{tri_v0[i]}" v2="{tri_v1[i]}" v3="{tri_v2[i]}" pid="1" p1="{color_indices[i]}"/>\n')
    xml_parts.append('</triangles>\n</mesh>\n</object>\n</resources>\n<build>\n<item objectid="2"/>\n</build>\n</model>')

    model_xml = "".join(xml_parts).encode('utf-8')

    with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>""")
        zf.writestr('_rels/.rels', """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>""")
        zf.writestr('3D/3dmodel.model', model_xml)

    log(f"Exported 3MF: {os.path.basename(filepath)} ({os.path.getsize(filepath) / (1024*1024):.2f} MB)")

def export_object(obj, obj_filepath, mf_filepath, ground_z=False):
    """Exports a specific Blender mesh object to OBJ and/or 3MF."""
    mesh = obj.data
    if ground_z and len(mesh.vertices) > 0:
        verts_co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get('co', verts_co)
        min_z = float(np.min(verts_co.reshape((-1, 3))[:, 2]))
        if abs(min_z) > 1e-6:
            z_offset = -min_z
            log(f"Grounding '{obj.name}' to print bed (shifting Z by {z_offset:.4f})...")
            verts_reshaped = verts_co.reshape((-1, 3))
            verts_reshaped[:, 2] += z_offset
            mesh.vertices.foreach_set('co', verts_reshaped.flatten())
            mesh.update()

    if mf_filepath:
        num_loops = len(mesh.loops)
        color_layer = mesh.color_attributes.get('Color') or mesh.color_attributes.active_color
        if color_layer and getattr(color_layer, 'data_type', None) in ('BYTE_COLOR', 'FLOAT_COLOR'):
            mesh.color_attributes.active_color = color_layer
            raw_c = np.empty(num_loops * 4, dtype=np.float32)
            color_layer.data.foreach_get('color', raw_c)
            active_loop_colors = raw_c.reshape((num_loops, 4))
        else:
            active_loop_colors = np.ones((num_loops, 4), dtype=np.float32)
        export_3mf(mf_filepath, mesh, active_loop_colors)

    if obj_filepath:
        color_layer = mesh.color_attributes.get('Color')
        if color_layer and getattr(color_layer, 'data_type', None) in ('BYTE_COLOR', 'FLOAT_COLOR'):
            mesh.color_attributes.active_color = color_layer
        t_obj = time.time()
        for o in bpy.data.objects:
            o.select_set(o == obj)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.wm.obj_export(
            filepath=obj_filepath,
            export_colors=True,
            export_materials=False,
            export_selected_objects=True,
            export_triangulated_mesh=True,
            forward_axis='Y',
            up_axis='Z'
        )
        log(f"Exported OBJ: {os.path.basename(obj_filepath)} in {time.time()-t_obj:.2f}s ({os.path.getsize(obj_filepath) / (1024*1024):.2f} MB)")

def bisect_mesh(obj, plane_co, plane_no, clear_outer, clear_inner, cap_cut):
    """Performs planar cut on `obj`.
    When `cap_cut` is True and `obj` is a closed manifold (e.g. pre-solidified), uses Blender's
    MANIFOLD Boolean INTERSECT against a half-space box so the wall cross-section is capped
    watertight (0 boundary edges, 0 cavity bridging). Falls back to `bpy.ops.mesh.bisect` otherwise."""
    import mathutils
    p_co = mathutils.Vector(plane_co)
    p_no = mathutils.Vector(plane_no).normalized()
    # Determine which side to keep: clear_inner=True keeps +p_no; clear_outer=True keeps -p_no
    keep_no = (-p_no) if (clear_outer and not clear_inner) else p_no

    used_manifold = False
    if cap_cut:
        bm_chk = bmesh.new()
        bm_chk.from_mesh(obj.data)
        open_edges = sum(1 for e in bm_chk.edges if len(e.link_faces) == 1)
        bm_chk.free()

        if open_edges == 0 and len(obj.data.polygons) > 0:
            box_size = max(20.0, max(obj.dimensions) * 10.0)
            quat = mathutils.Vector((0.0, 0.0, 1.0)).rotation_difference(keep_no)
            loc = p_co + keep_no * (box_size * 0.5)
            bpy.ops.mesh.primitive_cube_add(size=box_size, location=loc, rotation=quat.to_euler())
            box = bpy.context.active_object
            try:
                mod = obj.modifiers.new(name='BisectManifold', type='BOOLEAN')
                mod.operation = 'INTERSECT'
                mod.object = box
                mod.solver = 'MANIFOLD'
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.modifier_apply(modifier='BisectManifold')
                if len(obj.data.polygons) > 0:
                    used_manifold = True
            except Exception as e:
                log(f"MANIFOLD boolean cut fallback to mesh.bisect ({e})")
            finally:
                if box.name in bpy.data.objects:
                    bpy.data.objects.remove(box, do_unlink=True)

    if not used_manifold:
        for o in bpy.data.objects:
            o.select_set(o == obj)
        bpy.context.view_layer.objects.active = obj

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.bisect(
            plane_co=tuple(p_co),
            plane_no=tuple(p_no),
            use_fill=bool(cap_cut),
            clear_inner=bool(clear_inner),
            clear_outer=bool(clear_outer)
        )
        bpy.ops.object.mode_set(mode='OBJECT')

    bm = bmesh.new()
    bm.from_mesh(obj.data)

    # Color cap faces on the cut plane using adjacent seam colors
    cap_faces = [f for f in bm.faces if all(abs((v.co - p_co).dot(keep_no)) < 2e-4 for v in f.verts)]
    if cap_faces:
        cap_set = set(cap_faces)
        color_layer = bm.loops.layers.color.active
        if color_layer:
            seam_colors = []
            for f in cap_faces:
                for e in f.edges:
                    for nf in e.link_faces:
                        if nf not in cap_set:
                            for l in nf.loops:
                                try:
                                    seam_colors.append(l[color_layer])
                                except Exception:
                                    pass
                            break
            if seam_colors:
                avg_c = tuple(np.mean(np.array([c[:4] for c in seam_colors]), axis=0))
                for f in cap_faces:
                    for l in f.loops:
                        l[color_layer] = avg_c

    if not used_manifold:
        bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
        bmesh.ops.dissolve_degenerate(bm, dist=1e-5, edges=bm.edges[:])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    else:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

    bm.to_mesh(obj.data)
    bm.free()


def lay_flat_on_cut_plane(obj, cut_planes):
    """
    Rotates `obj` so its largest-area cut plane's outward cap normal points straight down (0, 0, -1),
    ready to sit flat at Z = 0 on the print bed when grounded.
    `cut_planes` is a list of (plane_co, plane_no, keep_sign) tuples.
    """
    import mathutils, math
    if not cut_planes or len(obj.data.polygons) == 0:
        return

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    best_area = -1.0
    best_outward = None

    for p_co, p_no, keep_sign in cut_planes:
        co_v = mathutils.Vector(p_co)
        no_v = mathutils.Vector(p_no).normalized()
        outward_no = (-keep_sign * no_v).normalized()
        area = sum(
            f.calc_area() for f in bm.faces
            if all(abs((v.co - co_v).dot(no_v)) < 3e-4 for v in f.verts)
        )
        if area > best_area:
            best_area = area
            best_outward = outward_no

    bm.free()

    if best_outward is None:
        co_v, no_v, keep_sign = cut_planes[0]
        best_outward = (-keep_sign * mathutils.Vector(no_v).normalized()).normalized()

    target = mathutils.Vector((0.0, 0.0, -1.0))
    dot = max(-1.0, min(1.0, best_outward.dot(target)))
    if dot > 0.99999:
        return
    if dot < -0.99999:
        rot = mathutils.Quaternion(mathutils.Vector((1.0, 0.0, 0.0)), math.pi)
    else:
        rot = best_outward.rotation_difference(target)

    obj.data.transform(rot.to_matrix().to_4x4())
    obj.data.update()
    log(f"Oriented '{obj.name}' flat onto cut plane (outward normal rotated to -Z).")

def build_bulkhead_slab(part_obj, plane_co, plane_no, keep_sign=1.0, thickness_mm=2.5):
    """
    Closes the hollow interior on the cut plane with a real solid flat bulkhead floor
    extruded `thickness_mm` inward along `keep_sign * plane_no` and MANIFOLD-unioned onto `part_obj`.
    Clusters cut vertices by 2D proximity so separate islands don't bridge empty air, and gently
    tapers the interior top rim inward so the slab never protrudes through sloped outer walls.
    """
    import mathutils
    p_co = mathutils.Vector(plane_co)
    p_no = mathutils.Vector(plane_no).normalized()
    slab_dir = (p_no * keep_sign).normalized()

    max_dim = max(part_obj.dimensions)
    scale_fac = 0.001 if max_dim < 10.0 else 1.0
    T = max(0.4, float(thickness_mm)) * scale_fac
    cluster_radius = 12.0 * scale_fac
    min_span = 10.0 * scale_fac
    inset_u = min(2.0 * scale_fac, T)

    if abs(p_no.z) < 0.9:
        t1 = p_no.cross(mathutils.Vector((0.0, 0.0, 1.0))).normalized()
    else:
        t1 = p_no.cross(mathutils.Vector((0.0, 1.0, 0.0))).normalized()
    t2 = p_no.cross(t1).normalized()

    bm = bmesh.new()
    bm.from_mesh(part_obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    cut_verts = [v for v in bm.verts if abs((v.co - p_co).dot(p_no)) < 2e-4]
    if len(cut_verts) < 6:
        bm.free()
        return
    cut_vert_set = set(cut_verts)
    vert_to_cidx = {v: idx for idx, v in enumerate(cut_verts)}

    # Sample seam color for the new bulkhead faces
    seam_color = (0.8, 0.8, 0.8, 1.0)
    color_layer = bm.loops.layers.color.active
    has_color = color_layer is not None
    if has_color:
        cols = []
        for v in cut_verts[:200]:
            for l in v.link_loops:
                try:
                    cols.append(l[color_layer][:4])
                except Exception:
                    pass
        if cols:
            seam_color = tuple(float(x) for x in np.mean(np.array(cols), axis=0))

    # Cluster cut vertices via BOTH cut-plane mesh edge connectivity AND 3D proximity
    # so low-poly long edges (e.g. a 40mm cube) stay unified while detached islands stay separate
    kd = mathutils.kdtree.KDTree(len(cut_verts))
    for idx, v in enumerate(cut_verts):
        kd.insert(v.co, idx)
    kd.balance()

    visited = [False] * len(cut_verts)
    clusters = []
    for i in range(len(cut_verts)):
        if visited[i]:
            continue
        comp = []
        stack = [i]
        visited[i] = True
        while stack:
            cur = stack.pop()
            v_cur = cut_verts[cur]
            comp.append(v_cur.co.copy())
            for e in v_cur.link_edges:
                other = e.other_vert(v_cur)
                if other in cut_vert_set:
                    oi = vert_to_cidx[other]
                    if not visited[oi]:
                        visited[oi] = True
                        stack.append(oi)
            for _, nbr_idx, _ in kd.find_range(v_cur.co, cluster_radius):
                if not visited[nbr_idx]:
                    visited[nbr_idx] = True
                    stack.append(nbr_idx)
        if len(comp) >= 6:
            clusters.append(comp)
    bm.free()

    slab_bm = bmesh.new()
    slabs_built = 0
    for pts_3d in clusters:
        pts_2d = [mathutils.Vector(((p - p_co).dot(t1), (p - p_co).dot(t2))) for p in pts_3d]
        hull_idx = mathutils.geometry.convex_hull_2d(pts_2d)
        if len(hull_idx) < 3:
            continue

        # Deduplicate near-coincident hull vertices to keep slab clean
        raw_h2d = [pts_2d[idx] for idx in hull_idx]
        h2d = []
        for hp in raw_h2d:
            if not h2d or (hp - h2d[-1]).length >= 0.2 * scale_fac:
                h2d.append(hp)
        if len(h2d) > 2 and (h2d[0] - h2d[-1]).length < 0.2 * scale_fac:
            h2d.pop()
        if len(h2d) < 3:
            continue

        span = max(max(p.x for p in h2d) - min(p.x for p in h2d),
                   max(p.y for p in h2d) - min(p.y for p in h2d))
        if span < min_span:
            continue

        hull_pts_3d = [p_co + t1 * p.x + t2 * p.y for p in h2d]
        center_3d = sum(hull_pts_3d, mathutils.Vector((0.0, 0.0, 0.0))) / len(hull_pts_3d)

        bot_vs = [slab_bm.verts.new(p) for p in hull_pts_3d]
        top_vs = []
        for p in hull_pts_3d:
            inward = center_3d - p
            if inward.length > 1e-6:
                p_in = p + inward.normalized() * min(inset_u, inward.length * 0.25)
            else:
                p_in = p
            top_vs.append(slab_bm.verts.new(p_in + slab_dir * T))

        try:
            slab_bm.faces.new(list(reversed(bot_vs)))
            slab_bm.faces.new(top_vs)
            n_h = len(hull_pts_3d)
            for i in range(n_h):
                j = (i + 1) % n_h
                slab_bm.faces.new([bot_vs[i], bot_vs[j], top_vs[j], top_vs[i]])
            slabs_built += 1
        except Exception as e:
            log(f"Skipping degenerate bulkhead island on '{part_obj.name}': {e}")

    if slabs_built == 0:
        slab_bm.free()
        return

    bmesh.ops.recalc_face_normals(slab_bm, faces=slab_bm.faces[:])
    bmesh.ops.triangulate(slab_bm, faces=slab_bm.faces[:])

    slab_mesh = bpy.data.meshes.new('BulkheadSlabMesh')
    slab_bm.to_mesh(slab_mesh)
    slab_bm.free()

    if has_color and len(slab_mesh.loops) > 0:
        ca = slab_mesh.color_attributes.new(name='Color', type='BYTE_COLOR', domain='CORNER')
        ca.data.foreach_set('color', np.tile(np.array(seam_color, dtype=np.float32), len(slab_mesh.loops)))
        slab_mesh.color_attributes.active = ca

    slab_obj = bpy.data.objects.new('BulkheadSlab', slab_mesh)
    bpy.context.collection.objects.link(slab_obj)

    for solver in ('MANIFOLD', 'FLOAT'):
        mod = part_obj.modifiers.new(name='UnionBulkhead', type='BOOLEAN')
        mod.operation = 'UNION'
        mod.object = slab_obj
        mod.solver = solver
        bpy.context.view_layer.objects.active = part_obj
        try:
            bpy.ops.object.modifier_apply(modifier='UnionBulkhead')
            log(f"Built {thickness_mm:.1f}mm flat bulkhead floor ({slabs_built} island(s), {solver}) on '{part_obj.name}'.")
            break
        except Exception as e:
            log(f"Bulkhead union ({solver}) failed on '{part_obj.name}': {e}")
            if 'UnionBulkhead' in part_obj.modifiers:
                part_obj.modifiers.remove(part_obj.modifiers['UnionBulkhead'])

    bpy.data.objects.remove(slab_obj, do_unlink=True)
    bpy.data.meshes.remove(slab_mesh, do_unlink=True)

def _has_solid_depth(check_obj, pt, ray_dir, r_cand, min_depth, scale_fac, t1, t2):
    """Returns True if `check_obj` has >= `min_depth` solid material behind the entire cylinder circle (center + 8 perimeter rays)."""
    import mathutils, math
    eps = 0.05 * scale_fac
    offsets = [mathutils.Vector((0.0, 0.0, 0.0))]
    for k in range(8):
        ang = k * (math.pi * 0.25)
        offsets.append(t1 * (math.cos(ang) * r_cand) + t2 * (math.sin(ang) * r_cand))
    for off in offsets:
        origin = pt + off + ray_dir * eps
        hit, hit_loc, _, _ = check_obj.ray_cast(origin, ray_dir)
        if not hit:
            return False
        if (hit_loc - origin).length + eps < min_depth:
            return False
    return True


def find_rim_socket_positions(part_obj, plane_co, plane_no, socket_radius_mm=2.0, socket_depth_mm=3.0,
                              num_pins=2, sign=1.0, mate_obj=None):
    """
    Finds safe socket positions inside a solid planar cut cross-section using a KDTree on
    cut-face boundary edges plus a 9-ray outer-shell containment check so cylindrical sockets
    scale cleanly to the model / cross-section size while maintaining >= 2.0mm radial wall
    clearance and >= 1.5mm behind-socket solid backing.
    Returns `(chosen_pts, r_eff, depth_eff_mm)`.
    """
    import mathutils
    plane_co = mathutils.Vector(plane_co)
    plane_no = mathutils.Vector(plane_no).normalized()
    ray_dir = (plane_no * sign).normalized()

    max_dim = max(part_obj.dimensions)
    scale_fac = 0.001 if max_dim < 10.0 else 1.0
    model_span_mm = max_dim / scale_fac
    if float(socket_radius_mm) <= 2.5:
        r_target_mm = max(2.0, min(12.0, model_span_mm * 0.015))
    else:
        r_target_mm = float(socket_radius_mm)
    r_max = r_target_mm * scale_fac
    r_min = 1.2 * scale_fac
    wall_margin = 2.0 * scale_fac  # Strict >= 2.0mm solid perimeter margin around socket
    min_half_width = r_min + wall_margin

    bm = bmesh.new()
    bm.from_mesh(part_obj.data)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    plane_faces = [
        f for f in bm.faces
        if abs((f.calc_center_median() - plane_co).dot(plane_no)) < 2e-4
        and abs(f.normal.dot(plane_no)) > 0.9
    ]
    if not plane_faces:
        bm.free()
        return [], 0.0, 0.0

    plane_face_set = set(plane_faces)
    boundary_pts = []
    sample_step = 0.5 * scale_fac
    for f in plane_faces:
        for e in f.edges:
            linked_in_plane = sum(1 for lf in e.link_faces if lf in plane_face_set)
            if linked_in_plane == 1:
                v0, v1 = e.verts[0].co, e.verts[1].co
                elen = (v1 - v0).length
                n_seg = max(2, min(128, int(elen / sample_step) + 1))
                for s in range(n_seg + 1):
                    boundary_pts.append(v0.lerp(v1, s / float(n_seg)))

    if len(boundary_pts) < 3:
        bm.free()
        return [], 0.0, 0.0

    kd = mathutils.kdtree.KDTree(len(boundary_pts))
    for i, pt in enumerate(boundary_pts):
        kd.insert(pt, i)
    kd.balance()

    if abs(plane_no.z) < 0.9:
        t1 = plane_no.cross(mathutils.Vector((0.0, 0.0, 1.0))).normalized()
    else:
        t1 = plane_no.cross(mathutils.Vector((0.0, 1.0, 0.0))).normalized()
    t2 = plane_no.cross(t1).normalized()

    us = [(p - plane_co).dot(t1) for p in boundary_pts]
    ws = [(p - plane_co).dot(t2) for p in boundary_pts]
    u_min, u_max = min(us), max(us)
    w_min, w_max = min(ws), max(ws)
    max_span = max(u_max - u_min, w_max - w_min)

    candidates = []
    for f in plane_faces:
        c = f.calc_center_median()
        _, _, dist = kd.find(c)
        if dist >= min_half_width:
            candidates.append((dist, c.copy()))

    bm.free()

    steps = 16
    for iu in range(1, steps):
        u = u_min + (u_max - u_min) * (iu / float(steps))
        for iw in range(1, steps):
            w = w_min + (w_max - w_min) * (iw / float(steps))
            pt = plane_co + t1 * u + t2 * w
            hit, loc, _, _ = part_obj.closest_point_on_mesh(pt, distance=0.5 * scale_fac)
            if hit and (loc - pt).length < 0.25 * scale_fac:
                _, _, dist = kd.find(pt)
                if dist >= min_half_width:
                    candidates.append((dist, pt))

    if not candidates:
        log(f"WARNING: No solid region >= {min_half_width/scale_fac:.1f}mm half-width on '{part_obj.name}'; skipping sockets.")
        return [], 0.0, 0.0

    candidates.sort(key=lambda x: x[0], reverse=True)
    min_sep = max(12.0 * scale_fac, max_span * 0.30)
    chosen = []
    chosen_radii = []
    chosen_depths_mm = []
    chosen_margins = []

    for sep_target in (min_sep, 12.0 * scale_fac):
        for dist, pt in candidates:
            if len(chosen) >= num_pins:
                break
            if all((pt - prev).length >= sep_target for prev in chosen):
                r_cand = min(r_max, dist - wall_margin, dist * 0.42)
                if r_cand < r_min:
                    continue
                r_cand_mm = r_cand / scale_fac
                d_desired = min(15.0, max(float(socket_depth_mm), r_cand_mm * 1.4))
                safe_d = None
                for d_try in sorted({round(d_desired, 2), round(d_desired * 0.65, 2), 3.0}, reverse=True):
                    min_solid_depth = (d_try + 1.5) * scale_fac
                    r_guard = r_cand + 1.5 * scale_fac
                    if not _has_solid_depth(part_obj, pt, ray_dir, r_guard, min_solid_depth, scale_fac, t1, t2):
                        continue
                    if mate_obj is not None and not _has_solid_depth(mate_obj, pt, -ray_dir, r_guard, min_solid_depth, scale_fac, t1, t2):
                        continue
                    safe_d = d_try
                    break
                if safe_d is None:
                    continue
                chosen.append(pt)
                chosen_radii.append(r_cand)
                chosen_depths_mm.append(safe_d)
                chosen_margins.append(dist)
        if len(chosen) >= num_pins:
            break

    if not chosen:
        log(f"WARNING: No region passed 9-ray outer-shell guard on '{part_obj.name}'; skipping sockets.")
        return [], 0.0, 0.0

    r_eff = min(chosen_radii)
    depth_eff_mm = min(chosen_depths_mm)
    for idx, (pt, d) in enumerate(zip(chosen, chosen_margins)):
        log(f"Safe solid socket #{idx+1} on '{part_obj.name}': margin={(d-r_eff)/scale_fac:.2f}mm, r={r_eff/scale_fac:.2f}mm, depth={depth_eff_mm:.2f}mm.")
    return chosen, r_eff, depth_eff_mm


def carve_sockets_at_positions(part_obj, sockets_3d, plane_no, r_socket, socket_depth_mm=3.0, sign=1.0):
    """
    Carves recessed female cylindrical sockets into `part_obj` at `sockets_3d` along `sign * plane_no`.
    Uses MANIFOLD boolean solver (with FLOAT fallback) and extends cutter 0.2mm into empty air.
    """
    import mathutils
    if not sockets_3d or r_socket <= 0:
        return []

    plane_no = mathutils.Vector(plane_no).normalized()
    max_dim = max(part_obj.dimensions)
    scale_fac = 0.001 if max_dim < 10.0 else 1.0

    clamped_depth_mm = min(float(socket_depth_mm), 15.0)
    d_socket = clamped_depth_mm * scale_fac
    air_overlap = 0.2 * scale_fac

    quat = mathutils.Vector((0, 0, 1)).rotation_difference(plane_no)
    euler = quat.to_euler()

    for idx, s_pos in enumerate(sockets_3d):
        loc = mathutils.Vector(s_pos) + plane_no * (sign * (d_socket / 2.0 - air_overlap))
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=32,
            radius=r_socket,
            depth=d_socket + 2.0 * air_overlap,
            location=loc,
            rotation=euler
        )
        cyl = bpy.context.active_object
        for solver in ('MANIFOLD', 'FLOAT'):
            mod = part_obj.modifiers.new(name=f'SocketDiff_{idx}', type='BOOLEAN')
            mod.operation = 'DIFFERENCE'
            mod.object = cyl
            mod.solver = solver
            bpy.context.view_layer.objects.active = part_obj
            try:
                bpy.ops.object.modifier_apply(modifier=f'SocketDiff_{idx}')
                break
            except Exception as e:
                log(f"Socket boolean ({solver}) failed on '{part_obj.name}': {e}")
                if f'SocketDiff_{idx}' in part_obj.modifiers:
                    part_obj.modifiers.remove(part_obj.modifiers[f'SocketDiff_{idx}'])
        bpy.data.objects.remove(cyl, do_unlink=True)

    log(f"Carved {len(sockets_3d)} alignment socket(s) (r={r_socket/scale_fac:.2f}mm, depth={clamped_depth_mm:.2f}mm) into '{part_obj.name}'.")
    return sockets_3d


def carve_part_sockets(part_obj, plane_co, plane_no, socket_radius_mm=2.0, socket_depth_mm=3.0,
                       num_pins=2, cached_sockets=None, mate_obj=None):
    """
    Carves recessed female cylindrical sockets into the solid cut face of a part.
    If `cached_sockets`=(sockets_3d, r_socket, depth_mm) is provided from a mating half,
    reuses the exact 3D coordinates, radius, and depth so pins align across the seam.
    """
    if cached_sockets and cached_sockets[0]:
        sockets_3d, r_socket, depth_mm = cached_sockets
    else:
        sockets_3d, r_socket, depth_mm = find_rim_socket_positions(
            part_obj, plane_co, plane_no,
            socket_radius_mm=socket_radius_mm,
            socket_depth_mm=socket_depth_mm,
            num_pins=num_pins,
            sign=1.0,
            mate_obj=mate_obj
        )
    if not sockets_3d:
        return [], 0.0, 0.0
    carve_sockets_at_positions(part_obj, sockets_3d, plane_no, r_socket, socket_depth_mm=depth_mm, sign=1.0)
    return sockets_3d, r_socket, depth_mm


def export_alignment_pins(output_3mf_path, output_obj_path, num_pins=4, pin_radius_mm=0.95, pin_length_mm=3.0):
    """Exports printable cylindrical dowel pins to outputs/alignment_pins.3mf and .obj."""
    import mathutils
    bm = bmesh.new()
    r = pin_radius_mm
    h = pin_length_mm
    spacing = r * 4.0

    for i in range(num_pins):
        col = i % 2
        row = i // 2
        loc = mathutils.Vector((col * spacing, row * spacing, h / 2.0))
        M = mathutils.Matrix.Translation(loc)
        bmesh.ops.create_cone(
            bm,
            cap_ends=True,
            segments=24,
            radius1=r,
            radius2=r,
            depth=h,
            matrix=M
        )

    mesh = bpy.data.meshes.new('AlignmentPinsMesh')
    bm.to_mesh(mesh)
    bm.free()

    pin_obj = bpy.data.objects.new('AlignmentPins', mesh)
    bpy.context.collection.objects.link(pin_obj)

    target_dir = os.path.dirname(output_3mf_path or output_obj_path or ".")
    if output_3mf_path:
        p3mf = os.path.join(target_dir, "alignment_pins.3mf")
        export_3mf(p3mf, mesh, np.ones((len(mesh.loops), 4), dtype=np.float32) * 0.9)
        log(f"Exported printable dowels: alignment_pins.3mf ({num_pins} pins)")

    if output_obj_path:
        pobj = os.path.join(target_dir, "alignment_pins.obj")
        for o in bpy.data.objects:
            o.select_set(o == pin_obj)
        bpy.context.view_layer.objects.active = pin_obj
        bpy.ops.wm.obj_export(
            filepath=pobj,
            export_colors=False,
            export_materials=False,
            export_selected_objects=True,
            export_triangulated_mesh=True,
            forward_axis='Y',
            up_axis='Z'
        )
        log(f"Exported printable dowels: alignment_pins.obj ({num_pins} pins)")

    bpy.data.objects.remove(pin_obj, do_unlink=True)
    bpy.data.meshes.remove(mesh, do_unlink=True)

def add_alignment_sockets_and_dowel_pins(part1, part2, plane_co, plane_no, output_3mf_path, output_obj_path,
                                        socket_radius_mm=2.0, socket_depth_mm=3.0, num_pins=2):
    """
    1. Finds safe regions on the solid cut cross-section using KDTree + 9-ray outer-shell guard.
    2. Carves matching recessed sockets (clamped <= 3.0mm depth) on Part 1 (-plane_no) and Part 2 (+plane_no).
    3. Generates companion printable dowel pins sized to match the carved sockets.
    """
    max_dim = max(max(part1.dimensions), max(part2.dimensions))
    scale_fac = 0.001 if max_dim < 10.0 else 1.0

    sockets_3d, r_socket, clamped_depth_mm = find_rim_socket_positions(
        part1, plane_co, plane_no,
        socket_radius_mm=socket_radius_mm,
        socket_depth_mm=socket_depth_mm,
        num_pins=num_pins,
        sign=-1.0,
        mate_obj=part2
    )
    if not sockets_3d:
        log("No safe solid regions passed >= 2mm outer-shell guard; skipping socket carving.")
        return

    carve_sockets_at_positions(part1, sockets_3d, plane_no, r_socket, socket_depth_mm=clamped_depth_mm, sign=-1.0)
    carve_sockets_at_positions(part2, sockets_3d, plane_no, r_socket, socket_depth_mm=clamped_depth_mm, sign=1.0)

    r_mm = r_socket / scale_fac
    pin_r_mm = max(0.5, round(r_mm - 0.15, 2))
    pin_len_mm = max(1.0, round(clamped_depth_mm * 2.0 - 0.6, 2))
    log(f"Dual alignment sockets carved successfully into both parts (r={r_mm:.2f}mm, depth={clamped_depth_mm:.2f}mm).")
    export_alignment_pins(
        output_3mf_path,
        output_obj_path,
        num_pins=len(sockets_3d),
        pin_radius_mm=pin_r_mm,
        pin_length_mm=pin_len_mm
    )

    for p in [part1, part2]:
        bm = bmesh.new()
        bm.from_mesh(p.data)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(p.data)
        bm.free()

def main():
    args = parse_args()
    log(f"Starting conversion for: {args.input}")
    if args.solidify_mm >= 0.0 and args.add_pegs:
        log("Alignment pins/sockets disabled in Hollow Shell / Raw Mesh mode (only enabled in Full Solid mode).")
        args.add_pegs = False

    t_start = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # 1. Import GLB
    t0 = time.time()
    bpy.ops.import_scene.gltf(filepath=args.input)
    log(f"GLTF imported in {time.time()-t0:.2f}s")

    mesh_objs = [o for o in bpy.data.objects if o.type == 'MESH']
    if not mesh_objs:
        log("ERROR: No mesh objects found in GLB!")
        sys.exit(1)

    if len(mesh_objs) > 1:
        log(f"Joining {len(mesh_objs)} mesh objects into one...")
        bpy.context.view_layer.objects.active = mesh_objs[0]
        for o in mesh_objs:
            o.select_set(True)
        bpy.ops.object.join()
        obj = mesh_objs[0]
    else:
        obj = mesh_objs[0]

    bpy.context.view_layer.objects.active = obj
    mesh = obj.data
    log(f"Mesh has {len(mesh.vertices)} vertices, {len(mesh.polygons)} polygons")

    # 2. Find texture image
    image = None
    for img in bpy.data.images:
        if img.size[0] > 0 and img.size[1] > 0:
            image = img
            break

    # 3. Handle Texture Resizing
    if image and args.texture_res > 0:
        orig_w, orig_h = image.size
        max_dim = max(orig_w, orig_h)
        if max_dim > args.texture_res:
            scale_fac = args.texture_res / max_dim
            new_w = max(16, int(orig_w * scale_fac))
            new_h = max(16, int(orig_h * scale_fac))
            log(f"Resizing texture from {orig_w}x{orig_h} to {new_w}x{new_h}...")
            image.scale(new_w, new_h)
            log("Texture resized.")

    # 4. Bake Texture to Vertex Colors (Vectorized NumPy Sampling)
    num_loops = len(mesh.loops)
    if image and mesh.uv_layers.active:
        log(f"Baking texture '{image.name}' ({image.size[0]}x{image.size[1]}) to {num_loops} vertex loops...")
        t_bake = time.time()
        w, h = image.size
        pixels = np.empty(w * h * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        img_grid = pixels.reshape((h, w, 4))

        color_attr = mesh.color_attributes.new(name='Color', type='BYTE_COLOR', domain='CORNER')
        mesh.color_attributes.active_color = color_attr
        uvs = np.empty(num_loops * 2, dtype=np.float32)
        mesh.uv_layers.active.data.foreach_get('uv', uvs)
        uv_grid = uvs.reshape((num_loops, 2))

        u = np.mod(uv_grid[:, 0], 1.0)
        v = np.mod(uv_grid[:, 1], 1.0)
        px = np.clip((u * (w - 1)).astype(np.int32), 0, w - 1)
        py = np.clip((v * (h - 1)).astype(np.int32), 0, h - 1)

        sampled_colors = img_grid[py, px]
        color_attr.data.foreach_set('color', sampled_colors.flatten())
        log(f"Color baking completed in {time.time()-t_bake:.2f}s")
    else:
        log("No image texture found; skipping texture color baking.")

    # 5. Handle Scaling (mm) and Grounding
    verts_co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get('co', verts_co)
    verts_mat = verts_co.reshape((-1, 3))
    min_bounds = np.min(verts_mat, axis=0)
    max_bounds = np.max(verts_mat, axis=0)
    cur_height = max_bounds[2] - min_bounds[2]

    if args.height_mm > 0.0 and cur_height > 1e-4:
        scale_factor = args.height_mm / cur_height
        log(f"Scaling model height from {cur_height:.2f}mm to {args.height_mm:.2f}mm...")
        obj.scale = (scale_factor, scale_factor, scale_factor)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        mesh = obj.data
        mesh.vertices.foreach_get('co', verts_co)
        verts_mat = verts_co.reshape((-1, 3))
        min_bounds = np.min(verts_mat, axis=0)

    def split_path(base_path, suffix):
        if not base_path:
            return ""
        d, f = os.path.split(base_path)
        stem, ext = os.path.splitext(f)
        return os.path.join(d, f"{stem}_{suffix}{ext}")

    def make_solid_volume(target_obj, label):
        bm = bmesh.new()
        bm.from_mesh(target_obj.data)
        bm.edges.ensure_lookup_table()
        open_edges = [e for e in bm.edges if len(e.link_faces) == 1]
        if not open_edges:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
            bm.to_mesh(target_obj.data)
            bm.free()
            log(f"FULL SOLID: '{label}' is already watertight (0 boundary edges); slicer handles infill.")
            return

        log(f"FULL SOLID: Closing {len(open_edges)} open boundary edge(s) on '{label}' into a solid print volume...")
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
        open_edges = [e for e in bm.edges if len(e.link_faces) == 1]
        existing_faces = set(bm.faces[:])
        if open_edges:
            try:
                bmesh.ops.holes_fill(bm, edges=open_edges, sides=0)
            except Exception as e:
                log(f"Warning: holes_fill failed on '{label}': {e}")
        new_faces = [f for f in bm.faces if f not in existing_faces]
        if new_faces:
            color_layer = bm.loops.layers.color.active
            if color_layer:
                seam_colors = []
                for f in new_faces:
                    for e in f.edges:
                        for nf in e.link_faces:
                            if nf in existing_faces:
                                for l in nf.loops:
                                    try:
                                        seam_colors.append(l[color_layer])
                                    except Exception:
                                        pass
                                break
                if seam_colors:
                    avg_c = tuple(np.mean(np.array([c[:4] for c in seam_colors]), axis=0))
                    for f in new_faces:
                        for l in f.loops:
                            l[color_layer] = avg_c
            bmesh.ops.triangulate(bm, faces=new_faces, quad_method='BEAUTY', ngon_method='BEAUTY')
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        rem_open = sum(1 for e in bm.edges if len(e.link_faces) == 1)
        bm.to_mesh(target_obj.data)
        bm.free()
        log(f"FULL SOLID: '{label}' boundary edges after cap = {rem_open}.")

    def apply_inward_solidify(target_obj, solidify_mm, label):
        if solidify_mm < 0.0:
            make_solid_volume(target_obj, label)
            return
        if solidify_mm == 0.0:
            return
        max_dim = max(target_obj.dimensions)
        scale_fac = 0.001 if max_dim < 10.0 else 1.0
        thick_u = solidify_mm * scale_fac
        log(f"HOLLOW SHELL: Adding {solidify_mm:.1f}mm wall thickness inward ({thick_u:.5f} units) to '{label}'...")
        mod_sol = target_obj.modifiers.new(name='Solidify', type='SOLIDIFY')
        mod_sol.thickness = thick_u
        mod_sol.offset = -1.0
        mod_sol.use_rim = True
        bpy.context.view_layer.objects.active = target_obj
        bpy.ops.object.modifier_apply(modifier='Solidify')

    def _pre_decimate_and_prepare(target_obj, label, prepare_volume=True):
        """Closes GLTF seams before decimation in Full Solid mode, or decimates before Solidify in Hollow mode."""
        if prepare_volume and args.solidify_mm < 0.0:
            apply_inward_solidify(target_obj, args.solidify_mm, label)

        did_decimate = False
        if args.decimate_ratio < 0.999 or (args.target_triangles > 0 and len(target_obj.data.polygons) > args.target_triangles):
            ratio = args.decimate_ratio
            if args.target_triangles > 0 and len(target_obj.data.polygons) > args.target_triangles:
                ratio = args.target_triangles / float(len(target_obj.data.polygons))
            log(f"Pre-decimating {label} from {len(target_obj.data.polygons)} to target ratio {ratio:.3f} (keeps cut holes sharp)...")
            mod = target_obj.modifiers.new(name='Decimate', type='DECIMATE')
            mod.ratio = float(ratio)
            mod.use_collapse_triangulate = True
            bpy.context.view_layer.objects.active = target_obj
            bpy.ops.object.modifier_apply(modifier='Decimate')
            did_decimate = True

        if prepare_volume and args.solidify_mm > 0.0:
            apply_inward_solidify(target_obj, args.solidify_mm, label)
        return did_decimate

    # 6. Check if Multi-Part Lasso / Region Split is requested
    if args.parts_json and os.path.isfile(args.parts_json):
        log(f"MULTI-PART SPLIT: Processing parts from {args.parts_json}...")
        with open(args.parts_json, "r", encoding="utf-8") as pf:
            raw_data = json.load(pf)

        if isinstance(raw_data, dict) and "parts" in raw_data:
            parts_dict = raw_data["parts"]
            parts_planes = raw_data.get("planes", {})
        else:
            parts_dict = raw_data
            parts_planes = {}

        log(f"Found {len(parts_dict)} staged parts to export.")
        has_lasso = any(
            not (parts_planes.get(pn) or parts_planes.get(pn.strip().replace(" ", "_")))
            for pn in parts_dict
        )
        pre_decimated = False
        if not has_lasso:
            pre_decimated = _pre_decimate_and_prepare(obj, "base mesh", prepare_volume=(args.solidify_mm != 0.0))

        total_sockets_carved = 0
        plane_socket_cache = {}
        carved_radii_mm = []
        carved_depths_mm = []

        for part_name, face_indices in parts_dict.items():
            safe_name = part_name.strip().replace(" ", "_")
            planes_for_part = parts_planes.get(part_name) or parts_planes.get(safe_name) or []
            log(f"Extracting part '{safe_name}'...")

            part_obj = obj.copy()
            part_mesh_data = obj.data.copy()
            part_obj.data = part_mesh_data
            bpy.context.collection.objects.link(part_obj)

            if planes_for_part:
                if args.solidify_mm != 0.0 and has_lasso:
                    apply_inward_solidify(part_obj, args.solidify_mm, safe_name)

                log(f"Part '{safe_name}': Applying {len(planes_for_part)} geometric planar cut(s)...")
                cut_planes_for_layout = []
                for cp in planes_for_part:
                    p_co = (float(cp["point"][0]), float(cp["point"][1]), float(cp["point"][2]))
                    p_no = (float(cp["normal"][0]), float(cp["normal"][1]), float(cp["normal"][2]))
                    cut_planes_for_layout.append((p_co, p_no, 1.0))
                    bisect_mesh(part_obj, p_co, p_no, clear_outer=False, clear_inner=True, cap_cut=args.split_cap)
                    if args.add_pegs and args.split_cap and args.solidify_mm < 0.0:
                        plane_key = (
                            round(p_co[0], 4), round(p_co[1], 4), round(p_co[2], 4),
                            round(abs(p_no[0]), 3), round(abs(p_no[1]), 3), round(abs(p_no[2]), 3)
                        )
                        cached = plane_socket_cache.get(plane_key)
                        s_carved, r_eff, d_eff_mm = carve_part_sockets(
                            part_obj, p_co, p_no,
                            socket_radius_mm=args.peg_radius if args.peg_radius > 0 else 2.0,
                            socket_depth_mm=args.peg_height if args.peg_height > 0 else 3.0,
                            cached_sockets=cached,
                            mate_obj=obj
                        )
                        if s_carved:
                            if plane_key not in plane_socket_cache:
                                plane_socket_cache[plane_key] = (s_carved, r_eff, d_eff_mm)
                            scale_fac = 0.001 if max(part_obj.dimensions) < 10.0 else 1.0
                            carved_radii_mm.append(r_eff / scale_fac)
                            carved_depths_mm.append(d_eff_mm)
                        total_sockets_carved += len(s_carved)
            else:
                keep_set = set()
                for item in face_indices:
                    if isinstance(item, list) and len(item) == 2:
                        keep_set.update(range(item[0], item[1] + 1))
                    else:
                        keep_set.add(item)

                log(f"Part '{safe_name}': {len(keep_set)} faces to retain (Lasso mode).")

                bm = bmesh.new()
                bm.from_mesh(part_obj.data)

                # 1. Identify ONLY the real cut seam edges (edges between keep_set and del_faces)
                cut_seam_edges = set()
                for e in bm.edges:
                    if len(e.link_faces) == 2:
                        f0, f1 = e.link_faces
                        if (f0.index in keep_set) != (f1.index in keep_set):
                            cut_seam_edges.add(e)

                del_faces = [f for f in bm.faces if f.index not in keep_set]
                bmesh.ops.delete(bm, geom=del_faces, context='FACES')

                # Cap boundaries if requested - ONLY on the actual cut seam edges!
                if args.split_cap and cut_seam_edges:
                    try:
                        valid_seam_edges = [e for e in cut_seam_edges if e.is_valid and e.is_boundary]
                        if valid_seam_edges:
                            log(f"Attempting cut-seam capping on {len(valid_seam_edges)} seam edges for '{safe_name}'...")
                            color_layer = bm.loops.layers.color.active
                            seam_colors = {}
                            if color_layer:
                                for e in valid_seam_edges:
                                    for l in e.link_loops:
                                        seam_colors[l.vert] = l[color_layer]
                            res = bmesh.ops.edgenet_fill(bm, edges=valid_seam_edges)
                            new_faces = res.get('faces', [])
                            if color_layer and new_faces:
                                avg_c = (0.8, 0.8, 0.8, 1.0)
                                if seam_colors:
                                    c_arr = np.array(list(seam_colors.values()))
                                    avg_c = tuple(np.mean(c_arr, axis=0))
                                for nf in new_faces:
                                    for l in nf.loops:
                                        l[color_layer] = seam_colors.get(l.vert, avg_c)
                    except Exception as cap_err:
                        log(f"Cut-seam capping skipped for '{safe_name}': {cap_err}")

                # ALWAYS triangulate all faces so slicers never encounter N-gons (> 4 vertices)
                bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
                bmesh.ops.dissolve_degenerate(bm, dist=1e-5, edges=bm.edges[:])
                bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

                bm.to_mesh(part_obj.data)
                bm.free()

                # Lasso mode solidifies after face deletion so keep_set indices match Three.js
                if args.solidify_mm > 0.0:
                    apply_inward_solidify(part_obj, args.solidify_mm, safe_name)

            # Optional decimation on the extracted part (skipped if pre-decimated before cutting)
            if not pre_decimated and (args.decimate_ratio < 0.999 or (args.target_triangles > 0 and len(part_obj.data.polygons) > args.target_triangles)):
                ratio = args.decimate_ratio
                if args.target_triangles > 0 and len(part_obj.data.polygons) > args.target_triangles:
                    ratio = args.target_triangles / float(len(part_obj.data.polygons))
                log(f"Decimating part '{safe_name}' from {len(part_obj.data.polygons)} to target ratio {ratio:.3f}...")
                mod = part_obj.modifiers.new(name='Decimate', type='DECIMATE')
                mod.ratio = float(ratio)
                mod.use_collapse_triangulate = True
                bpy.context.view_layer.objects.active = part_obj
                bpy.ops.object.modifier_apply(modifier='Decimate')

            if args.ground_z and planes_for_part:
                lay_flat_on_cut_plane(part_obj, cut_planes_for_layout)

            part_obj_out = split_path(args.output_obj, safe_name)
            part_3mf_out = split_path(args.output_3mf, safe_name)

            export_object(part_obj, part_obj_out, part_3mf_out, ground_z=args.ground_z)

            # Clean up memory immediately
            bpy.data.objects.remove(part_obj, do_unlink=True)
            bpy.data.meshes.remove(part_mesh_data, do_unlink=True)
            log(f"Part '{safe_name}' exported and memory freed.")

        if args.add_pegs and total_sockets_carved > 0:
            num_pins = max(2, total_sockets_carved // 2)
            clamped_depth = min(carved_depths_mm) if carved_depths_mm else 3.0
            pin_r_mm = max(0.5, round(min(carved_radii_mm) - 0.15, 2)) if carved_radii_mm else 1.85
            pin_len_mm = max(1.0, round(clamped_depth * 2.0 - 0.6, 2))
            export_alignment_pins(
                args.output_3mf, args.output_obj,
                num_pins=num_pins, pin_radius_mm=pin_r_mm, pin_length_mm=pin_len_mm
            )

    # 7. Check if Planar Cut is requested
    elif (args.plane_point and args.plane_normal) or (args.split_axis != "none"):
        if args.plane_point and args.plane_normal:
            try:
                co_vals = [float(x.strip()) for x in args.plane_point.split(",")]
                no_vals = [float(x.strip()) for x in args.plane_normal.split(",")]
                plane_co = (co_vals[0], co_vals[1], co_vals[2])
                plane_no = (no_vals[0], no_vals[1], no_vals[2])
                log(f"PLANAR CUT: Using arbitrary knife plane. Point={plane_co}, Normal={plane_no} (Cap: {args.split_cap}, Pegs: {args.add_pegs})...")
            except Exception as e:
                log(f"ERROR parsing plane coords ({e}), falling back to X axis.")
                plane_no = (1.0, 0.0, 0.0)
                plane_co = (0.0, 0.0, 0.0)
        else:
            axis = args.split_axis.lower()
            coord = args.split_coord
            log(f"PLANAR CUT: Splitting model along {axis.upper()} axis at coordinate {coord:.3f} (Cap: {args.split_cap}, Pegs: {args.add_pegs})...")

            plane_normals = {
                "x": (1.0, 0.0, 0.0),
                "y": (0.0, 1.0, 0.0),
                "z": (0.0, 0.0, 1.0)
            }
            plane_coords = {
                "x": (coord, 0.0, 0.0),
                "y": (0.0, coord, 0.0),
                "z": (0.0, 0.0, coord)
            }

            plane_no = plane_normals.get(axis, (1.0, 0.0, 0.0))
            plane_co = plane_coords.get(axis, (0.0, 0.0, 0.0))

        _pre_decimate_and_prepare(obj, "base mesh", prepare_volume=(args.solidify_mm != 0.0))

        part1 = obj
        part1.name = "Part_1"

        part2 = obj.copy()
        part2.data = obj.data.copy()
        part2.name = "Part_2"
        bpy.context.collection.objects.link(part2)

        bisect_mesh(part1, plane_co, plane_no, clear_outer=True, clear_inner=False, cap_cut=args.split_cap)
        bisect_mesh(part2, plane_co, plane_no, clear_outer=False, clear_inner=True, cap_cut=args.split_cap)

        if args.add_pegs and args.split_cap and args.solidify_mm < 0.0:
            add_alignment_sockets_and_dowel_pins(
                part1, part2, plane_co, plane_no,
                output_3mf_path=args.output_3mf,
                output_obj_path=args.output_obj,
                socket_radius_mm=args.peg_radius if args.peg_radius > 0 else 2.0,
                socket_depth_mm=args.peg_height if args.peg_height > 0 else 3.0,
                num_pins=2
            )

        p1_obj = split_path(args.output_obj, "part1")
        p2_obj = split_path(args.output_obj, "part2")
        p1_3mf = split_path(args.output_3mf, "part1")
        p2_3mf = split_path(args.output_3mf, "part2")

        if args.ground_z:
            lay_flat_on_cut_plane(part1, [(plane_co, plane_no, -1.0)])
            lay_flat_on_cut_plane(part2, [(plane_co, plane_no, 1.0)])

        log("Exporting Part 1...")
        export_object(part1, p1_obj, p1_3mf, ground_z=args.ground_z)
        log("Exporting Part 2...")
        export_object(part2, p2_obj, p2_3mf, ground_z=args.ground_z)

    else:
        # Standard Single-Model Decimation & Export
        init_polys = len(mesh.polygons)
        target_ratio = args.decimate_ratio
        if args.target_triangles > 0 and init_polys > args.target_triangles:
            target_ratio = args.target_triangles / float(init_polys)

        if target_ratio < 0.999:
            log(f"Decimating mesh (ratio: {target_ratio:.3f}, target ~{int(init_polys * target_ratio)} faces)...")
            t_dec = time.time()
            mod = obj.modifiers.new(name='Decimate', type='DECIMATE')
            mod.ratio = float(target_ratio)
            bpy.ops.object.modifier_apply(modifier='Decimate')
            log(f"Decimation done in {time.time()-t_dec:.2f}s. New verts: {len(mesh.vertices)}, faces: {len(mesh.polygons)}")

        if args.solidify_mm != 0.0:
            apply_inward_solidify(obj, args.solidify_mm, "base mesh")

        export_object(obj, args.output_obj, args.output_3mf, ground_z=args.ground_z)

    log(f"ALL DONE! Total processing time: {time.time()-t_start:.2f}s")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log(f"CRITICAL WORKER EXCEPTION: {e}")
        traceback.print_exc()
        sys.exit(1)

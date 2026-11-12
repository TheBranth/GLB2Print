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
    parser.add_argument("--solidify-mm", type=float, default=0.0, help="Inward wall thickness in mm for open shells (0.0=disabled)")
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

    num_loops = len(mesh.loops)
    color_layer = mesh.color_attributes.active
    if not color_layer and len(mesh.color_attributes) > 0:
        color_layer = mesh.color_attributes.get('Color') or mesh.color_attributes[0]
        mesh.color_attributes.active = color_layer

    if color_layer:
        raw_c = np.empty(num_loops * 4, dtype=np.float32)
        color_layer.data.foreach_get('color', raw_c)
        active_loop_colors = raw_c.reshape((num_loops, 4))
    else:
        active_loop_colors = np.ones((num_loops, 4), dtype=np.float32)

    if mf_filepath:
        export_3mf(mf_filepath, mesh, active_loop_colors)

    if obj_filepath:
        t_obj = time.time()
        for o in bpy.data.objects:
            o.select_set(o == obj)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.wm.obj_export(
            filepath=obj_filepath,
            export_colors=True,
            export_materials=False,
            export_selected_objects=True,
            export_triangulated_mesh=True
        )
        log(f"Exported OBJ: {os.path.basename(obj_filepath)} in {time.time()-t_obj:.2f}s ({os.path.getsize(obj_filepath) / (1024*1024):.2f} MB)")

def bisect_mesh(obj, plane_co, plane_no, clear_outer, clear_inner, cap_cut):
    """Performs bisect cut on an object's mesh using Blender's mesh.bisect(use_fill=cap_cut)
    so solidified shell walls are capped cleanly across their wall thickness without bridging hollow cavities."""
    import mathutils
    p_co = mathutils.Vector(plane_co)
    p_no = mathutils.Vector(plane_no).normalized()

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

    # Color and triangulate newly filled cap faces lying on the cut plane
    cap_faces = [f for f in bm.faces if all(abs((v.co - p_co).dot(p_no)) < 1e-4 for v in f.verts)]
    if cap_faces:
        color_layer = bm.loops.layers.color.active
        if color_layer:
            seam_colors = []
            for f in cap_faces:
                for e in f.edges:
                    for nf in e.link_faces:
                        if nf not in cap_faces:
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

    bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
    bmesh.ops.dissolve_degenerate(bm, dist=1e-5, edges=bm.edges[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

    bm.to_mesh(obj.data)
    bm.free()

def build_flat_bulkhead(obj, plane_co, plane_no):
    """
    Builds a flat 2D planar bulkhead closing the cut cross-section
    so the piece can be printed completely flat on the build plate.
    """
    import mathutils
    plane_co = mathutils.Vector(plane_co)
    plane_no = mathutils.Vector(plane_no).normalized()

    bm = bmesh.new()
    bm.from_mesh(obj.data)

    cut_verts = [v for v in bm.verts if abs((v.co - plane_co).dot(plane_no)) < 2e-4]
    if len(cut_verts) < 6:
        bm.free()
        return

    # 2D projection on the cut plane
    if abs(plane_no.z) < 0.9:
        tangent = plane_no.cross(mathutils.Vector((0, 0, 1))).normalized()
    else:
        tangent = plane_no.cross(mathutils.Vector((0, 1, 0))).normalized()
    bitangent = plane_no.cross(tangent).normalized()

    pts_2d = [mathutils.Vector(((v.co - plane_co).dot(tangent), (v.co - plane_co).dot(bitangent))) for v in cut_verts]
    hull_indices = mathutils.geometry.convex_hull_2d(pts_2d)

    if len(hull_indices) >= 3:
        hull_verts = [cut_verts[i] for i in hull_indices]

        # Inherit vertex color from seam
        color_layer = bm.loops.layers.color.active
        seam_color = (0.8, 0.8, 0.8, 1.0)
        if color_layer:
            cols = []
            for v in hull_verts:
                for l in v.link_loops:
                    try:
                        cols.append(l[color_layer])
                    except Exception:
                        pass
            if cols:
                c_mat = np.array([c[:4] for c in cols])
                seam_color = tuple(np.mean(c_mat, axis=0))

        try:
            f = bm.faces.new(hull_verts)
            if color_layer:
                for l in f.loops:
                    l[color_layer] = seam_color
            bmesh.ops.triangulate(bm, faces=[f], quad_method='BEAUTY', ngon_method='BEAUTY')
            log(f"Flat bulkhead built on '{obj.name}' with {len(hull_verts)} perimeter vertices.")
        except Exception as e:
            hull_edges = []
            for i in range(len(hull_verts)):
                v1 = hull_verts[i]
                v2 = hull_verts[(i + 1) % len(hull_verts)]
                e = bm.edges.get((v1, v2)) or bm.edges.new((v1, v2))
                hull_edges.append(e)
            res = bmesh.ops.edgenet_fill(bm, edges=hull_edges)
            new_faces = res.get('faces', [])
            if color_layer and new_faces:
                for nf in new_faces:
                    for l in nf.loops:
                        l[color_layer] = seam_color

        bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
        bmesh.ops.dissolve_degenerate(bm, dist=1e-5, edges=bm.edges[:])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

    bm.to_mesh(obj.data)
    bm.free()

def find_rim_socket_positions(part_obj, plane_co, plane_no, socket_radius_mm=1.15, num_pins=2):
    """
    Finds safe socket positions centered inside the solidified cut rim using a KDTree
    on the cut-face boundary edges, ensuring sockets sit in the thickest rim regions
    without puncturing the inner or outer walls.
    """
    import mathutils
    plane_co = mathutils.Vector(plane_co)
    plane_no = mathutils.Vector(plane_no).normalized()

    max_dim = max(part_obj.dimensions)
    scale_fac = 0.001 if max_dim < 10.0 else 1.0
    r_max = min(socket_radius_mm, 1.15) * scale_fac
    min_half_width = 1.05 * scale_fac  # Need >= ~2.1mm wall thickness for a socket

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
        return [], 0.0

    plane_face_set = set(plane_faces)
    boundary_pts = []
    for f in plane_faces:
        for e in f.edges:
            linked_in_plane = sum(1 for lf in e.link_faces if lf in plane_face_set)
            if linked_in_plane == 1:
                boundary_pts.append(e.verts[0].co.copy())
                boundary_pts.append(e.verts[1].co.copy())
                boundary_pts.append((e.verts[0].co + e.verts[1].co) * 0.5)

    if len(boundary_pts) < 3:
        bm.free()
        return [], 0.0

    kd = mathutils.kdtree.KDTree(len(boundary_pts))
    for i, pt in enumerate(boundary_pts):
        kd.insert(pt, i)
    kd.balance()

    candidates = []
    for f in plane_faces:
        c = f.calc_center_median()
        _, _, dist = kd.find(c)
        if dist >= min_half_width:
            candidates.append((dist, c.copy()))

    bm.free()

    if not candidates:
        log(f"WARNING: No rim region >= {min_half_width/scale_fac:.1f}mm half-width on '{part_obj.name}'; skipping sockets.")
        return [], 0.0

    candidates.sort(key=lambda x: x[0], reverse=True)
    min_sep = 12.0 * scale_fac
    chosen = []
    chosen_dists = []

    for dist, pt in candidates:
        if all((pt - prev).length >= min_sep for prev in chosen):
            chosen.append(pt)
            chosen_dists.append(dist)
            if len(chosen) >= num_pins:
                break

    if not chosen:
        return [], 0.0

    min_chosen_dist = min(chosen_dists)
    r_eff = min(r_max, min_chosen_dist * 0.58)
    for idx, (pt, d) in enumerate(zip(chosen, chosen_dists)):
        log(f"Safe rim socket #{idx+1} on '{part_obj.name}': half_width={d/scale_fac:.2f}mm, r={r_eff/scale_fac:.2f}mm.")
    return chosen, r_eff


def carve_sockets_at_positions(part_obj, sockets_3d, plane_no, r_socket, socket_depth_mm=1.8, sign=1.0):
    """
    Carves recessed female cylindrical sockets into `part_obj` at `sockets_3d` along `sign * plane_no`.
    Extends the cutter 0.2mm into empty air so it is non-coplanar with the cut plane for FLOAT boolean.
    """
    import mathutils
    if not sockets_3d or r_socket <= 0:
        return []

    plane_no = mathutils.Vector(plane_no).normalized()
    max_dim = max(part_obj.dimensions)
    scale_fac = 0.001 if max_dim < 10.0 else 1.0

    clamped_depth_mm = min(float(socket_depth_mm), 1.8)
    d_socket = clamped_depth_mm * scale_fac
    air_overlap = 0.2 * scale_fac

    quat = mathutils.Vector((0, 0, 1)).rotation_difference(plane_no)
    euler = quat.to_euler()

    for idx, s_pos in enumerate(sockets_3d):
        loc = mathutils.Vector(s_pos) + plane_no * (sign * (d_socket / 2.0 - air_overlap))
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=24,
            radius=r_socket,
            depth=d_socket + 2.0 * air_overlap,
            location=loc,
            rotation=euler
        )
        cyl = bpy.context.active_object
        mod = part_obj.modifiers.new(name=f'SocketDiff_{idx}', type='BOOLEAN')
        mod.operation = 'DIFFERENCE'
        mod.object = cyl
        mod.solver = 'FLOAT'
        bpy.context.view_layer.objects.active = part_obj
        bpy.ops.object.modifier_apply(modifier=f'SocketDiff_{idx}')
        bpy.data.objects.remove(cyl, do_unlink=True)

    log(f"Carved {len(sockets_3d)} alignment socket(s) (r={r_socket/scale_fac:.2f}mm, depth={clamped_depth_mm:.2f}mm) into '{part_obj.name}'.")
    return sockets_3d


def carve_part_sockets(part_obj, plane_co, plane_no, socket_radius_mm=1.15, socket_depth_mm=1.8,
                       num_pins=2, cached_sockets=None):
    """
    Carves recessed female cylindrical sockets into the solidified cut rim of a part.
    If `cached_sockets`=(sockets_3d, r_socket) is provided from a mating half, reuses the exact
    3D coordinates and radius so pins align across the seam.
    """
    if cached_sockets and cached_sockets[0]:
        sockets_3d, r_socket = cached_sockets
    else:
        sockets_3d, r_socket = find_rim_socket_positions(
            part_obj, plane_co, plane_no, socket_radius_mm=socket_radius_mm, num_pins=num_pins
        )
    if not sockets_3d:
        return [], 0.0
    carve_sockets_at_positions(part_obj, sockets_3d, plane_no, r_socket, socket_depth_mm=socket_depth_mm, sign=1.0)
    return sockets_3d, r_socket


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
            export_triangulated_mesh=True
        )
        log(f"Exported printable dowels: alignment_pins.obj ({num_pins} pins)")

    bpy.data.objects.remove(pin_obj, do_unlink=True)
    bpy.data.meshes.remove(mesh, do_unlink=True)

def add_alignment_sockets_and_dowel_pins(part1, part2, plane_co, plane_no, output_3mf_path, output_obj_path,
                                        socket_radius_mm=1.15, socket_depth_mm=1.8, num_pins=2):
    """
    1. Finds thick rim regions on the pre-solidified & bisected cut face using KDTree.
    2. Carves matching recessed sockets (clamped <= 1.8mm depth) on Part 1 (-plane_no) and Part 2 (+plane_no).
    3. Generates companion printable dowel pins sized to match the carved sockets.
    """
    max_dim = max(max(part1.dimensions), max(part2.dimensions))
    scale_fac = 0.001 if max_dim < 10.0 else 1.0

    sockets_3d, r_socket = find_rim_socket_positions(
        part1, plane_co, plane_no, socket_radius_mm=socket_radius_mm, num_pins=num_pins
    )
    if not sockets_3d:
        log("No thick rim positions found for sockets; skipping socket boolean to preserve model walls.")
        export_alignment_pins(output_3mf_path, output_obj_path, num_pins=num_pins)
        return

    clamped_depth_mm = min(float(socket_depth_mm), 1.8)
    carve_sockets_at_positions(part1, sockets_3d, plane_no, r_socket, socket_depth_mm=clamped_depth_mm, sign=-1.0)
    carve_sockets_at_positions(part2, sockets_3d, plane_no, r_socket, socket_depth_mm=clamped_depth_mm, sign=1.0)

    r_mm = r_socket / scale_fac
    pin_r_mm = max(0.5, round(r_mm - 0.15, 2))
    pin_len_mm = max(1.0, round(clamped_depth_mm * 2.0 - 0.6, 2))
    log(f"Dual alignment sockets carved successfully into both parts (r={r_mm:.2f}mm, depth={clamped_depth_mm:.2f}mm).")
    export_alignment_pins(
        output_3mf_path,
        output_obj_path,
        num_pins=len(sockets_3d) * 2,
        pin_radius_mm=pin_r_mm,
        pin_length_mm=pin_len_mm
    )

    for p in [part1, part2]:
        bm = bmesh.new()
        bm.from_mesh(p.data)
        bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(p.data)
        bm.free()

def main():
    args = parse_args()
    log(f"Starting conversion for: {args.input}")

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

    def apply_inward_solidify(target_obj, solidify_mm, label):
        if solidify_mm <= 0.0:
            return
        max_dim = max(target_obj.dimensions)
        scale_fac = 0.001 if max_dim < 10.0 else 1.0
        thick_u = solidify_mm * scale_fac
        log(f"SOLIDIFY: Adding {solidify_mm:.1f}mm wall thickness inward ({thick_u:.5f} units) to '{label}'...")
        mod_sol = target_obj.modifiers.new(name='Solidify', type='SOLIDIFY')
        mod_sol.thickness = thick_u
        mod_sol.offset = -1.0
        mod_sol.use_rim = True
        bpy.context.view_layer.objects.active = target_obj
        bpy.ops.object.modifier_apply(modifier='Solidify')

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
        if args.solidify_mm > 0.0 and not has_lasso:
            apply_inward_solidify(obj, args.solidify_mm, "base mesh")

        total_sockets_carved = 0
        plane_socket_cache = {}
        carved_radii_mm = []

        for part_name, face_indices in parts_dict.items():
            safe_name = part_name.strip().replace(" ", "_")
            planes_for_part = parts_planes.get(part_name) or parts_planes.get(safe_name) or []
            log(f"Extracting part '{safe_name}'...")

            part_obj = obj.copy()
            part_mesh_data = obj.data.copy()
            part_obj.data = part_mesh_data
            bpy.context.collection.objects.link(part_obj)

            if planes_for_part:
                if args.solidify_mm > 0.0 and has_lasso:
                    apply_inward_solidify(part_obj, args.solidify_mm, safe_name)

                log(f"Part '{safe_name}': Applying {len(planes_for_part)} geometric planar cut(s) on solidified shell...")
                for cp in planes_for_part:
                    p_co = (float(cp["point"][0]), float(cp["point"][1]), float(cp["point"][2]))
                    p_no = (float(cp["normal"][0]), float(cp["normal"][1]), float(cp["normal"][2]))
                    bisect_mesh(part_obj, p_co, p_no, clear_outer=False, clear_inner=True, cap_cut=args.split_cap)
                    if args.add_pegs and args.split_cap:
                        plane_key = (
                            round(p_co[0], 4), round(p_co[1], 4), round(p_co[2], 4),
                            round(abs(p_no[0]), 3), round(abs(p_no[1]), 3), round(abs(p_no[2]), 3)
                        )
                        cached = plane_socket_cache.get(plane_key)
                        s_carved, r_eff = carve_part_sockets(
                            part_obj, p_co, p_no,
                            socket_radius_mm=args.peg_radius if args.peg_radius > 0 else 1.15,
                            socket_depth_mm=args.peg_height if args.peg_height > 0 else 1.8,
                            cached_sockets=cached
                        )
                        if s_carved:
                            if plane_key not in plane_socket_cache:
                                plane_socket_cache[plane_key] = (s_carved, r_eff)
                            scale_fac = 0.001 if max(part_obj.dimensions) < 10.0 else 1.0
                            carved_radii_mm.append(r_eff / scale_fac)
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

            # Optional decimation on the extracted part
            if args.decimate_ratio < 0.999 or (args.target_triangles > 0 and len(part_obj.data.polygons) > args.target_triangles):
                ratio = args.decimate_ratio
                if args.target_triangles > 0 and len(part_obj.data.polygons) > args.target_triangles:
                    ratio = args.target_triangles / float(len(part_obj.data.polygons))
                log(f"Decimating part '{safe_name}' from {len(part_obj.data.polygons)} to target ratio {ratio:.3f}...")
                mod = part_obj.modifiers.new(name='Decimate', type='DECIMATE')
                mod.ratio = float(ratio)
                mod.use_collapse_triangulate = True
                bpy.context.view_layer.objects.active = part_obj
                bpy.ops.object.modifier_apply(modifier='Decimate')

            part_obj_out = split_path(args.output_obj, safe_name)
            part_3mf_out = split_path(args.output_3mf, safe_name)

            export_object(part_obj, part_obj_out, part_3mf_out, ground_z=args.ground_z)

            # Clean up memory immediately
            bpy.data.objects.remove(part_obj, do_unlink=True)
            bpy.data.meshes.remove(part_mesh_data, do_unlink=True)
            log(f"Part '{safe_name}' exported and memory freed.")

        if args.add_pegs:
            num_pins = max(2, total_sockets_carved // 2) if total_sockets_carved > 0 else len(parts_dict)
            clamped_depth = min(float(args.peg_height if args.peg_height > 0 else 1.8), 1.8)
            pin_r_mm = max(0.5, round(min(carved_radii_mm) - 0.15, 2)) if carved_radii_mm else 0.95
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

        # Solidify FIRST so bisect_mesh(use_fill=True) caps ONLY the 2.5mm cross-section
        if args.solidify_mm > 0.0:
            apply_inward_solidify(obj, args.solidify_mm, "base mesh")

        part1 = obj
        part1.name = "Part_1"

        part2 = obj.copy()
        part2.data = obj.data.copy()
        part2.name = "Part_2"
        bpy.context.collection.objects.link(part2)

        bisect_mesh(part1, plane_co, plane_no, clear_outer=True, clear_inner=False, cap_cut=args.split_cap)
        bisect_mesh(part2, plane_co, plane_no, clear_outer=False, clear_inner=True, cap_cut=args.split_cap)

        if args.add_pegs and args.split_cap:
            add_alignment_sockets_and_dowel_pins(
                part1, part2, plane_co, plane_no,
                output_3mf_path=args.output_3mf,
                output_obj_path=args.output_obj,
                socket_radius_mm=args.peg_radius if args.peg_radius > 0 else 1.15,
                socket_depth_mm=args.peg_height if args.peg_height > 0 else 1.8,
                num_pins=2
            )

        # Optional decimation on split parts
        for p, p_name in ((part1, "Part 1"), (part2, "Part 2")):
            if args.decimate_ratio < 0.999 or (args.target_triangles > 0 and len(p.data.polygons) > args.target_triangles):
                ratio = args.decimate_ratio
                if args.target_triangles > 0 and len(p.data.polygons) > args.target_triangles:
                    ratio = args.target_triangles / float(len(p.data.polygons))
                log(f"Decimating {p_name} from {len(p.data.polygons)} to target ratio {ratio:.3f}...")
                mod = p.modifiers.new(name='Decimate', type='DECIMATE')
                mod.ratio = float(ratio)
                mod.use_collapse_triangulate = True
                bpy.context.view_layer.objects.active = p
                bpy.ops.object.modifier_apply(modifier='Decimate')

        p1_obj = split_path(args.output_obj, "part1")
        p2_obj = split_path(args.output_obj, "part2")
        p1_3mf = split_path(args.output_3mf, "part1")
        p2_3mf = split_path(args.output_3mf, "part2")

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

        if args.solidify_mm > 0.0:
            max_dim = max(obj.dimensions)
            scale_fac = 0.001 if max_dim < 10.0 else 1.0
            thick_u = args.solidify_mm * scale_fac
            log(f"SOLIDIFY: Adding {args.solidify_mm:.1f}mm wall thickness inward ({thick_u:.5f} units)...")
            mod_sol = obj.modifiers.new(name='Solidify', type='SOLIDIFY')
            mod_sol.thickness = thick_u
            mod_sol.offset = -1.0
            mod_sol.use_rim = True
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier='Solidify')

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

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

def export_object(obj, obj_filepath, mf_filepath):
    """Exports a specific Blender mesh object to OBJ and/or 3MF."""
    mesh = obj.data
    num_loops = len(mesh.loops)
    color_layer = mesh.color_attributes.active
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
    """Performs bisect cut on an object's mesh with optional hole capping."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)

    res = bmesh.ops.bisect_plane(
        bm,
        geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
        plane_co=plane_co,
        plane_no=plane_no,
        clear_outer=clear_outer,
        clear_inner=clear_inner
    )

    if cap_cut:
        cut_edges = [e for e in res['geom_cut'] if isinstance(e, bmesh.types.BMEdge)]
        if cut_edges:
            bmesh.ops.edgenet_fill(bm, edges=cut_edges)

    # Always triangulate and recalculate normals so slicers receive pure valid triangles
    bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

    bm.to_mesh(obj.data)
    bm.free()

def add_alignment_pegs_and_sockets(part1, part2, plane_co, plane_no, peg_radius=2.0, peg_height=5.0, clearance=0.2):
    """
    Creates a snap-fit male peg on part1 and a matching female socket hole on part2
    at the centroid of the planar cut interface.
    """
    import mathutils
    plane_co = mathutils.Vector(plane_co)
    plane_no = mathutils.Vector(plane_no).normalized()

    # Find vertices on the cut interface
    verts1 = [v.co for v in part1.data.vertices if abs((v.co - plane_co).dot(plane_no)) < 0.25]
    if not verts1 or len(verts1) < 3:
        log("Cut interface vertices not clearly identified; placing peg at cut origin.")
        centroid = plane_co
    else:
        centroid = sum(verts1, mathutils.Vector((0.0, 0.0, 0.0))) / len(verts1)
        # Check boundary spread to prevent oversized pegs on thin walls
        dists = [(v - centroid).length for v in verts1]
        spread = min(dists) if dists else 10.0
        if spread < peg_radius * 1.5:
            adj_radius = max(0.8, spread * 0.45)
            log(f"Cut surface is narrow (spread: {spread:.2f}mm); adjusting peg radius from {peg_radius:.1f}mm to {adj_radius:.2f}mm")
            peg_radius = adj_radius

    quat = mathutils.Vector((0.0, 0.0, 1.0)).rotation_difference(plane_no)
    euler = quat.to_euler()

    # 1. Male Peg on Part 1 (protruding along plane_no)
    log(f"Adding male snap peg (radius={peg_radius:.2f}mm, height={peg_height:.2f}mm) at {centroid}...")
    try:
        bm1 = bmesh.new()
        bm1.from_mesh(part1.data)
        peg_loc = centroid + plane_no * (peg_height / 2.0 - 0.5)
        M = mathutils.Matrix.Translation(peg_loc) @ quat.to_matrix().to_4x4()
        bmesh.ops.create_cone(
            bm1,
            cap_ends=True,
            segments=24,
            radius1=peg_radius,
            radius2=peg_radius,
            depth=peg_height + 1.0,
            matrix=M
        )
        bmesh.ops.triangulate(bm1, faces=bm1.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
        bmesh.ops.recalc_face_normals(bm1, faces=bm1.faces[:])
        bm1.to_mesh(part1.data)
        bm1.free()
        log(f"Male peg integrated cleanly into Part 1 ({len(part1.data.vertices)} verts).")
    except Exception as e:
        log(f"WARNING: Could not integrate male peg: {e}")

    # 2. Female Socket on Part 2 (recessed along plane_no with clearance)
    socket_radius = peg_radius + clearance
    socket_depth = peg_height + 0.6
    socket_loc = centroid + plane_no * (socket_depth / 2.0)
    log(f"Carving female socket hole (radius={socket_radius:.2f}mm, depth={socket_depth:.2f}mm) into Part 2...")
    init_v2 = len(part2.data.vertices)
    part2_backup = part2.data.copy()
    try:
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=24,
            radius=socket_radius,
            depth=socket_depth,
            location=socket_loc,
            rotation=euler
        )
        socket_obj = bpy.context.active_object
        mod_diff = part2.modifiers.new(name='SocketDiff', type='BOOLEAN')
        mod_diff.operation = 'DIFFERENCE'
        mod_diff.object = socket_obj
        mod_diff.solver = 'EXACT'
        bpy.context.view_layer.objects.active = part2
        bpy.ops.object.modifier_apply(modifier='SocketDiff')
        bpy.data.objects.remove(socket_obj, do_unlink=True)

        if len(part2.data.vertices) < init_v2 * 0.5:
            log(f"WARNING: Socket boolean on non-manifold surface caused geometry collapse ({len(part2.data.vertices)} < {init_v2}); retaining clean flat cut face.")
            part2.data = part2_backup
        else:
            log(f"Female socket carved cleanly into Part 2 ({len(part2.data.vertices)} verts).")
            bpy.data.meshes.remove(part2_backup, do_unlink=True)
    except Exception as e:
        log(f"WARNING: Could not apply female socket boolean: {e}")
        part2.data = part2_backup

    # Triangulate and recalculate face normals for both parts
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

    if args.ground_z:
        z_offset = -min_bounds[2]
        log(f"Grounding model to print bed (shifting Z by {z_offset:.4f}mm)...")
        for v in mesh.vertices:
            v.co.z += z_offset

    def split_path(base_path, suffix):
        if not base_path:
            return ""
        d, f = os.path.split(base_path)
        stem, ext = os.path.splitext(f)
        return os.path.join(d, f"{stem}_{suffix}{ext}")

    # 6. Check if Multi-Part Lasso / Region Split is requested
    if args.parts_json and os.path.isfile(args.parts_json):
        log(f"MULTI-PART SPLIT: Processing parts from {args.parts_json}...")
        with open(args.parts_json, "r", encoding="utf-8") as pf:
            parts_dict = json.load(pf)

        log(f"Found {len(parts_dict)} staged parts to export.")

        for part_name, face_indices in parts_dict.items():
            safe_name = part_name.strip().replace(" ", "_")
            log(f"Extracting part '{safe_name}'...")

            keep_set = set()
            for item in face_indices:
                if isinstance(item, list) and len(item) == 2:
                    keep_set.update(range(item[0], item[1] + 1))
                else:
                    keep_set.add(item)

            log(f"Part '{safe_name}': {len(keep_set)} faces to retain.")

            part_obj = obj.copy()
            part_mesh_data = obj.data.copy()
            part_obj.data = part_mesh_data
            bpy.context.collection.objects.link(part_obj)

            bm = bmesh.new()
            bm.from_mesh(part_obj.data)

            # 1. Identify ONLY the real cut seam edges (edges between keep_set and del_faces)
            # NEVER treat original model boundary openings (eyes, nostrils, filigree cutouts) as cut seams!
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
                        res = bmesh.ops.edgenet_fill(bm, edges=valid_seam_edges)
                except Exception as cap_err:
                    log(f"Cut-seam capping skipped for '{safe_name}': {cap_err}")

            # ALWAYS triangulate all faces so slicers never encounter N-gons (> 4 vertices)
            bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

            bm.to_mesh(part_obj.data)
            bm.free()

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

            export_object(part_obj, part_obj_out, part_3mf_out)

            # Clean up memory immediately
            bpy.data.objects.remove(part_obj, do_unlink=True)
            bpy.data.meshes.remove(part_mesh_data, do_unlink=True)
            log(f"Part '{safe_name}' exported and memory freed.")

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

        part1 = obj
        part1.name = "Part_1"

        part2 = obj.copy()
        part2.data = obj.data.copy()
        part2.name = "Part_2"
        bpy.context.collection.objects.link(part2)

        bisect_mesh(part1, plane_co, plane_no, clear_outer=True, clear_inner=False, cap_cut=args.split_cap)
        bisect_mesh(part2, plane_co, plane_no, clear_outer=False, clear_inner=True, cap_cut=args.split_cap)

        if args.add_pegs and args.split_cap:
            add_alignment_pegs_and_sockets(part1, part2, plane_co, plane_no, peg_radius=args.peg_radius, peg_height=args.peg_height)

        p1_obj = split_path(args.output_obj, "part1")
        p2_obj = split_path(args.output_obj, "part2")
        p1_3mf = split_path(args.output_3mf, "part1")
        p2_3mf = split_path(args.output_3mf, "part2")

        log("Exporting Part 1...")
        export_object(part1, p1_obj, p1_3mf)
        log("Exporting Part 2...")
        export_object(part2, p2_obj, p2_3mf)

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

        export_object(obj, args.output_obj, args.output_3mf)

    log(f"ALL DONE! Total processing time: {time.time()-t_start:.2f}s")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log(f"CRITICAL WORKER EXCEPTION: {e}")
        traceback.print_exc()
        sys.exit(1)

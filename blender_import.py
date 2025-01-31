import bpy
import bmesh

from . import blender_materials
from . import import_options
from . import ldraw_file
from . import ldraw_node
from . import ldraw_camera
from . import filesystem
from . import blender_camera
from . import helpers
from . import ldraw_colors
from . import strings
from . import texmap
from . import special_bricks


def do_import(filepath):
    print(filepath)  # TODO: multiple filepaths?

    scene_setup()
    ldraw_file.reset_caches()
    ldraw_node.reset_caches()
    ldraw_camera.reset_caches()
    texmap.reset_caches()
    filesystem.build_search_paths(parent_filepath=filepath)
    special_bricks.reset()
    ldraw_file.read_color_table()
    blender_materials.create_blender_node_groups()

    file = ldraw_file.LDrawFile.get_file(filepath)
    if file is None:
        return

    if file.is_configuration():
        load_materials(file)
        return

    root_node = ldraw_node.LDrawNode()
    root_node.is_root = True
    root_node.file = file
    root_node.load()

    if import_options.meta_step:
        if import_options.set_end_frame:
            bpy.context.scene.frame_end = ldraw_node.current_frame + import_options.frames_per_step
            bpy.context.scene.frame_set(bpy.context.scene.frame_end)

    max_clip_end = 0
    for camera in ldraw_camera.cameras:
        camera = blender_camera.create_camera(camera, empty=ldraw_node.top_empty, collection=ldraw_node.top_collection)
        if bpy.context.scene.camera is None:
            if camera.data.clip_end > max_clip_end:
                max_clip_end = camera.data.clip_end
            bpy.context.scene.camera = camera

    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    if space.clip_end < max_clip_end:
                        space.clip_end = max_clip_end


def scene_setup():
    bpy.context.scene.eevee.use_ssr = True
    bpy.context.scene.eevee.use_ssr_refraction = True
    bpy.context.scene.eevee.use_taa_reprojection = True

    # https://blender.stackexchange.com/a/146838
    if import_options.use_freestyle_edges:
        bpy.context.scene.render.use_freestyle = True
        if len(bpy.context.view_layer.freestyle_settings.linesets) < 1:
            bpy.context.view_layer.freestyle_settings.linesets.new("LDraw LineSet")
        lineset = bpy.context.view_layer.freestyle_settings.linesets[0]
        lineset.select_by_visibility = True
        lineset.select_by_edge_types = True
        lineset.select_by_face_marks = False
        lineset.select_by_collection = False
        lineset.select_by_image_border = False
        lineset.visibility = 'VISIBLE'
        lineset.edge_type_negation = 'INCLUSIVE'
        lineset.edge_type_combination = 'OR'
        lineset.select_silhouette = False
        lineset.select_border = False
        lineset.select_contour = False
        lineset.select_suggestive_contour = False
        lineset.select_ridge_valley = False
        lineset.select_crease = False
        lineset.select_edge_mark = True
        lineset.select_external_contour = False
        lineset.select_material_boundary = False


def load_materials(file):
    colors = {}
    group_name = 'blank'
    for line in file.lines:
        clean_line = helpers.clean_line(line)
        strip_line = line.strip()

        if clean_line.startswith('0 // LDraw'):
            group_name = clean_line
            colors[group_name] = []
            continue

        if clean_line.startswith("0 !COLOUR"):
            _params = helpers.get_params(clean_line, "0 !COLOUR ", lowercase=False)
            colors[group_name].append(ldraw_colors.parse_color(_params))
            continue

    j = 0
    for collection_name, codes in colors.items():
        if collection_name not in bpy.data.collections:
            bpy.data.collections.new(collection_name)
        collection = bpy.data.collections[collection_name]
        if collection_name not in bpy.context.scene.collection.children:
            bpy.context.scene.collection.children.link(collection)

        for i, color_code in enumerate(codes):
            bm = bmesh.new()

            monkey = True
            if monkey:
                prefix = 'monkey'
                bmesh.ops.create_monkey(bm)
            else:
                prefix = 'cube'
                bmesh.ops.create_cube(bm, size=1.0)

            bm.faces.ensure_lookup_table()
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()

            for f in bm.faces:
                f.smooth = True

            mesh = bpy.data.meshes.new(f"{prefix}_{color_code}")
            mesh[strings.ldraw_color_code_key] = color_code

            material = blender_materials.get_material(color_code)

            # https://blender.stackexchange.com/questions/23905/select-faces-depending-on-material
            if material.name not in mesh.materials:
                mesh.materials.append(material)
            for face in bm.faces:
                face.material_index = mesh.materials.find(material.name)

            bm.to_mesh(mesh)
            bm.clear()
            bm.free()

            mesh.validate()
            mesh.update(calc_edges=True)

            obj = bpy.data.objects.new(mesh.name, mesh)
            obj.modifiers.new("Subdivision", type='SUBSURF')
            obj.location.x = i * 3
            obj.location.y = -j * 3
            # obj.rotation_euler.z = math.radians(90)

            color = ldraw_colors.get_color(color_code)
            obj.color = color.color + (color.alpha,)

            collection.objects.link(obj)
        j += 1

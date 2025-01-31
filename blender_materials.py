import bpy
import os
import uuid
import re

from . import strings
from . import ldraw_colors
from . import filesystem

key_map = {}


def reset_caches():
    global key_map
    key_map = {}


# https://github.com/bblanimation/abs-plastic-materials
def create_blender_node_groups():
    reset_caches()
    this_script_dir = os.path.dirname(os.path.realpath(__file__))
    path = os.path.join(this_script_dir, 'materials', 'all_monkeys.blend')
    with bpy.data.libraries.load(path, link=False) as (data_from, data_to):
        data_to.node_groups = data_from.node_groups
    for node_group in data_to.node_groups:
        node_group.use_fake_user = True


def get_material(color_code, use_edge_color=False, part_slopes=None, texmap=None):
    color = ldraw_colors.get_color(color_code)

    _key = []
    _key.append("LDraw Material")
    _key.append(color.code)
    _key.append(color.name)
    if ldraw_colors.use_alt_colors:
        _key.append("alt")
    if use_edge_color:
        _key.append("edge")
    if part_slopes is not None:
        _key.append("_".join([str(k) for k in part_slopes]))
    if texmap is not None:
        texmap_suffix = "_".join([str(k) for k in [texmap.method, texmap.texture, texmap.glossmap] if k != ''])
        _key.append(texmap_suffix)
    _key = " ".join([str(k) for k in _key])
    # _key = re.sub(r"[^a-z0-9._]", "-", _key)

    if _key not in key_map:
        key_map[_key] = str(uuid.uuid4())
    key = key_map[_key]
    key = _key

    # Reuse current material if it exists, otherwise create a new material
    if key in bpy.data.materials:
        return bpy.data.materials[key]

    material = __create_node_based_material(key, color, use_edge_color=use_edge_color, part_slopes=part_slopes, texmap=texmap)
    return material


def __create_node_based_material(key, color, use_edge_color=False, part_slopes=None, texmap=None):
    """Set Cycles Material Values."""

    material = bpy.data.materials.new(key)
    material.use_fake_user = True
    material.use_nodes = True

    nodes = material.node_tree.nodes
    links = material.node_tree.links

    nodes.clear()

    is_transparent = False

    # https://wiki.ldraw.org/wiki/Color_24
    if use_edge_color:
        diff_color = color.edge_color + (1.0,)
        material.diffuse_color = diff_color
        material["LEGO.isTransparent"] = is_transparent
        material[strings.ldraw_color_code_key] = "24"
        material[strings.ldraw_color_name_key] = color.name
        __create_cycles_standard(nodes, links, diff_color)
        return material

    is_transparent = color.alpha < 1.0

    diff_color = color.color + (1.0,)
    material.diffuse_color = diff_color
    material["LEGO.isTransparent"] = is_transparent
    material[strings.ldraw_color_code_key] = color.code
    material[strings.ldraw_color_name_key] = color.name

    if is_transparent:
        material.use_screen_refraction = True
        material.refraction_depth = 0.5

    if color.name == "Milky_White":
        __create_cycles_milky_white(nodes, links, diff_color)
    elif 'Opal' in color.name:
        material_color = color.material_color + (1.0,)
        __create_cycles_opal(nodes, links, diff_color, material_color)
    elif color.material_name == "glitter":
        material_color = color.material_color + (1.0,)
        __create_cycles_glitter(nodes, links, diff_color, material_color)
    elif color.material_name == "speckle":
        material_color = color.material_color + (1.0,)
        __create_cycles_speckle(nodes, links, diff_color, material_color)
    elif color.luminance > 0:
        __create_cycles_emission(nodes, links, diff_color, color.luminance)
    elif color.material_name == "chrome":
        __create_cycles_chrome(nodes, links, diff_color)
    elif color.material_name == "pearlescent":
        __create_cycles_pearlescent(nodes, links, diff_color)
    elif color.material_name == "metal":
        __create_cycles_metal(nodes, links, diff_color)
    elif color.material_name == "rubber":
        if is_transparent:
            __create_cycles_rubber_translucent(nodes, links, diff_color)
        else:
            __create_cycles_rubber(nodes, links, diff_color)
    elif is_transparent:
        __create_cycles_transparent(nodes, links, diff_color)
    else:
        __create_cycles_standard(nodes, links, diff_color)

    if texmap is not None:
        __create_texmap_texture(nodes, links, diff_color, texmap)

    if part_slopes is not None:
        __create_cycles_slope_texture(nodes, links, part_slopes)

    return material


def __node_slope_texture_by_angle(nodes, x, y, angles):
    node = nodes.new("ShaderNodeGroup")
    node.name = "slope_texture_by_angle"
    node.node_tree = bpy.data.node_groups["_Slope Texture By Angle"]
    node.location = x, y
    if len(angles) > 0:
        node.inputs['Angle 1'].default_value = angles[0]
    if len(angles) > 1:
        node.inputs['Angle 2'].default_value = angles[1]
    if len(angles) > 2:
        node.inputs['Angle 3'].default_value = angles[2]
    if len(angles) > 3:
        node.inputs['Angle 4'].default_value = angles[3]
    node.inputs["Strength"].default_value = 0.6
    return node


def __node_lego_standard(nodes, color, x, y):
    node = nodes.new("ShaderNodeGroup")
    node.name = "standard"
    node.node_tree = bpy.data.node_groups["LEGO Standard"]
    node.location = x, y
    node.inputs["Color"].default_value = color
    return node


def __node_lego_transparent(nodes, color, x, y):
    node = nodes.new("ShaderNodeGroup")
    node.name = "transparent"
    node.node_tree = bpy.data.node_groups["LEGO Transparent"]
    node.location = x, y
    node.inputs["Color"].default_value = color
    return node


def __node_lego_rubber(nodes, color, x, y):
    node = nodes.new("ShaderNodeGroup")
    node.name = "rubber"
    node.node_tree = bpy.data.node_groups["LEGO Rubber Solid"]
    node.location = x, y
    node.inputs["Color"].default_value = color
    return node


def __node_lego_rubber_translucent(nodes, color, x, y):
    node = nodes.new("ShaderNodeGroup")
    node.name = "rubber_translucent"
    node.node_tree = bpy.data.node_groups["LEGO Rubber Translucent"]
    node.location = x, y
    node.inputs["Color"].default_value = color
    return node


def __node_lego_emission(nodes, color, luminance, x, y):
    node = nodes.new("ShaderNodeGroup")
    node.name = "emission"
    node.node_tree = bpy.data.node_groups["LEGO Emission"]
    node.location = x, y
    node.inputs["Color"].default_value = color
    node.inputs["Luminance"].default_value = luminance
    return node


def __node_lego_chrome(nodes, color, x, y):
    node = nodes.new("ShaderNodeGroup")
    node.name = "chrome"
    node.node_tree = bpy.data.node_groups["LEGO Chrome"]
    node.location = x, y
    node.inputs["Color"].default_value = color
    return node


def __node_lego_pearlescent(nodes, color, x, y):
    node = nodes.new("ShaderNodeGroup")
    node.name = "pearlescent"
    node.node_tree = bpy.data.node_groups["LEGO Pearlescent"]
    node.location = x, y
    node.inputs["Color"].default_value = color
    return node


def __node_lego_metal(nodes, color, x, y):
    node = nodes.new("ShaderNodeGroup")
    node.name = "metal"
    node.node_tree = bpy.data.node_groups["LEGO Metal"]
    node.location = x, y
    node.inputs["Color"].default_value = color
    return node


def __node_lego_opal(nodes, color, glitter_color, x, y):
    node = nodes.new("ShaderNodeGroup")
    node.name = "opal"
    node.node_tree = bpy.data.node_groups["LEGO Opal"]
    node.location = x, y
    node.inputs["Color"].default_value = color
    node.inputs["Glitter Color"].default_value = glitter_color
    return node


def __node_lego_glitter(nodes, color, glitter_color, x, y):
    node = nodes.new("ShaderNodeGroup")
    node.name = "glitter"
    node.node_tree = bpy.data.node_groups["LEGO Glitter"]
    node.location = x, y
    node.inputs["Color"].default_value = color
    node.inputs["Glitter Color"].default_value = glitter_color
    return node


def __node_lego_speckle(nodes, color, speckle_color, x, y):
    node = nodes.new("ShaderNodeGroup")
    node.name = "speckle"
    node.node_tree = bpy.data.node_groups["LEGO Speckle"]
    node.location = x, y
    node.inputs["Color"].default_value = color
    node.inputs["Speckle Color"].default_value = speckle_color
    return node


def __node_lego_milky_white(nodes, color, x, y):
    node = nodes.new("ShaderNodeGroup")
    node.name = "milky_white"
    node.node_tree = bpy.data.node_groups["LEGO Milky White"]
    node.location = x, y
    node.inputs["Color"].default_value = color
    return node


def __node_output(nodes, x, y):
    node = nodes.new("ShaderNodeOutputMaterial")
    node.location = x, y
    return node


def __node_tex_image(nodes, x, y):
    node = nodes.new("ShaderNodeTexImage")
    node.location = x, y
    return node


def __node_mix_rgb(nodes, x, y):
    node = nodes.new("ShaderNodeMixRGB")
    node.location = x, y
    return node


def __get_group(nodes):
    for x in nodes:
        if x.type == "GROUP":
            return x
    return None


def __create_texmap_texture(nodes, links, diff_color, texmap):
    """Image texture for texmap"""

    target = __get_group(nodes)
    if target is None:
        return

    image_name = texmap.texture
    if image_name is not None:
        texmap_image = __node_tex_image(nodes, -500.0, 0.0)
        texmap_image.name = 'ldraw_texmap_image'
        texmap_image.interpolation = "Closest"
        texmap_image.extension = "CLIP"

        # TODO: requests retrieve image from ldraw.org
        # https://blender.stackexchange.com/questions/157531/blender-2-8-python-add-texture-image
        if image_name not in bpy.data.images:
            image_path = filesystem.locate(image_name)
            if image_path is not None:
                image = bpy.data.images.load(image_path)
                image.name = image_name
                image[strings.ldraw_filename_key] = image_name
                image.colorspace_settings.name = 'sRGB'

        if image_name in bpy.data.images:
            image = bpy.data.images[image_name]
            texmap_image.image = image

        mix_rgb = __node_mix_rgb(nodes, -200, 0.0)
        mix_rgb.inputs["Color1"].default_value = diff_color

        links.new(texmap_image.outputs["Color"], mix_rgb.inputs["Color2"])
        links.new(texmap_image.outputs["Alpha"], mix_rgb.inputs["Fac"])
        links.new(mix_rgb.outputs["Color"], target.inputs["Color"])

    image_name = texmap.glossmap
    if image_name != '':
        glossmap_image = __node_tex_image(nodes, -360.0, -280.0)
        glossmap_image.name = 'ldraw_glossmap_image'
        glossmap_image.interpolation = "Closest"
        glossmap_image.extension = "CLIP"

        if image_name not in bpy.data.images:
            image_path = filesystem.locate(image_name)
            if image_path is not None:
                image = bpy.data.images.load(image_path)
                image.name = image_name
                image[strings.ldraw_filename_key] = image_name
                image.colorspace_settings.name = 'Non-Color'

        if image_name in bpy.data.images:
            image = bpy.data.images[image_name]
            glossmap_image.image = image

        links.new(glossmap_image.outputs["Color"], target.inputs["Specular"])


# TODO: slight variation in strength for each material
def __create_cycles_slope_texture(nodes, links, part_slopes=None):
    """Slope face normals for Cycles render engine"""

    target = __get_group(nodes)
    if target is None:
        return

    if part_slopes is None:
        return

    if len(part_slopes) < 1:
        return

    slope_texture = __node_slope_texture_by_angle(nodes, -200, 0, part_slopes)
    links.new(slope_texture.outputs["Normal"], target.inputs["Normal"])


def __create_cycles_transparent(nodes, links, diff_color):
    """Transparent Material for Cycles render engine."""

    node = __node_lego_transparent(nodes, diff_color, 0, 0)
    out = __node_output(nodes, 200, 0)
    links.new(node.outputs["Shader"], out.inputs[0])


def __create_cycles_standard(nodes, links, diff_color):
    """Basic Material for Cycles render engine."""

    node = __node_lego_standard(nodes, diff_color, 0, 0)
    out = __node_output(nodes, 200, 0)
    links.new(node.outputs["Shader"], out.inputs[0])


def __create_cycles_emission(nodes, links, diff_color, luminance):
    """Emission material for Cycles render engine."""

    node = __node_lego_emission(nodes, diff_color, luminance / 100.0, 0, 0)
    out = __node_output(nodes, 200, 0)
    links.new(node.outputs["Shader"], out.inputs[0])


def __create_cycles_chrome(nodes, links, diff_color):
    """Chrome material for Cycles render engine."""

    node = __node_lego_chrome(nodes, diff_color, 0, 0)
    out = __node_output(nodes, 200, 0)
    links.new(node.outputs["Shader"], out.inputs[0])


def __create_cycles_pearlescent(nodes, links, diff_color):
    """Pearlescent material for Cycles render engine."""

    node = __node_lego_pearlescent(nodes, diff_color, 0, 0)
    out = __node_output(nodes, 200, 0)
    links.new(node.outputs["Shader"], out.inputs[0])


def __create_cycles_metal(nodes, links, diff_color):
    """Metal material for Cycles render engine."""

    node = __node_lego_metal(nodes, diff_color, 0, 0)
    out = __node_output(nodes, 200, 0)
    links.new(node.outputs["Shader"], out.inputs[0])


def __create_cycles_opal(nodes, links, diff_color, glitter_color):
    """Glitter material for Cycles render engine."""

    glitter_color = ldraw_colors.lighten_rgba(glitter_color, 0.5)
    node = __node_lego_opal(nodes, diff_color, glitter_color, 0, 0)
    out = __node_output(nodes, 200, 0)
    links.new(node.outputs["Shader"], out.inputs[0])


def __create_cycles_glitter(nodes, links, diff_color, glitter_color):
    """Glitter material for Cycles render engine."""

    glitter_color = ldraw_colors.lighten_rgba(glitter_color, 0.5)
    node = __node_lego_glitter(nodes, diff_color, glitter_color, 0, 0)
    out = __node_output(nodes, 200, 0)
    links.new(node.outputs["Shader"], out.inputs[0])


def __create_cycles_speckle(nodes, links, diff_color, speckle_color):
    """Speckle material for Cycles render engine."""

    speckle_color = ldraw_colors.lighten_rgba(speckle_color, 0.5)
    node = __node_lego_speckle(nodes, diff_color, speckle_color, 0, 0)
    out = __node_output(nodes, 200, 0)
    links.new(node.outputs["Shader"], out.inputs[0])


def __create_cycles_rubber(nodes, links, diff_color):
    """Rubber material colors for Cycles render engine."""

    node = __node_lego_rubber(nodes, diff_color, 0, 0)
    out = __node_output(nodes, 200, 0)
    links.new(node.outputs[0], out.inputs[0])


def __create_cycles_rubber_translucent(nodes, links, diff_color):
    """Translucent Rubber material colors for Cycles render engine."""

    node = __node_lego_rubber_translucent(nodes, diff_color, 0, 0)
    out = __node_output(nodes, 200, 0)
    links.new(node.outputs[0], out.inputs[0])


def __create_cycles_milky_white(nodes, links, diff_color):
    """Milky White material for Cycles render engine."""

    node = __node_lego_milky_white(nodes, diff_color, 0, 0)
    out = __node_output(nodes, 200, 0)
    links.new(node.outputs["Shader"], out.inputs[0])

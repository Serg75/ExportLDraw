import os
import re
import mathutils
import uuid

from . import import_options
from . import filesystem
from . import helpers
from . import ldraw_part_types
from . import special_bricks

from .ldraw_node import LDrawNode
from .ldraw_geometry import LDrawGeometry
from .texmap import TexMap
from . import ldraw_colors
from . import ldraw_camera
from . import texmap

file_lines_cache = {}
file_cache = {}
key_map = {}


def reset_caches():
    global file_lines_cache
    global file_cache
    global key_map
    file_lines_cache = {}
    file_cache = {}
    key_map = {}


def read_color_table():
    ldraw_colors.reset_caches()

    """Reads the color values from the LDConfig.ldr file. For details of the
    LDraw color system see: http://www.ldraw.org/article/547"""

    if ldraw_colors.use_alt_colors:
        filename = "LDCfgalt.ldr"
    else:
        filename = "LDConfig.ldr"

    ldraw_file = LDrawFile.get_file(filename)
    if ldraw_file is None:
        return


class LDrawFile:
    def __init__(self, filename):
        self.filepath = None
        self.filename = filename

        self.description = None
        self.name = os.path.basename(filename)
        self.author = None
        # default part_type of ldraw_file is None, which should mean "model" - see ldraw_part_types.model_types
        # it is far more likely that a part type will not be specified in models since they are are more likely
        # to be authored by a user outside of specifications
        self.part_type = None
        self.actual_part_type = None

        self.lines = []

        self.child_nodes = []
        self.geometry = LDrawGeometry()
        self.extra_child_nodes = None
        self.extra_geometry = None

        self.texmap_start = False
        self.texmap_next = False
        self.texmap_fallback = False

        self.camera = None

    def __str__(self):
        return "\n".join([
            f"filename: {self.filename}",
            f"description: {self.description}",
            f"name: {self.name}",
            f"author: {self.author}",
        ])

    @classmethod
    def get_file(cls, filename):
        filepath = None
        if filename not in file_lines_cache:
            # TODO: if missing, use a,b,c,etc parts if available
            filepath = filesystem.locate(filename)
            if filepath is None:
                return None

            is_mpd = False
            no_file = False
            first_mpd_filename = None
            current_file = None
            try:
                with open(filepath, mode='r', encoding='utf-8') as file:
                    while True:
                        line = file.readline()
                        if not line:
                            break

                        clean_line = helpers.clean_line(line)
                        strip_line = line.strip()

                        if clean_line == "":
                            continue

                        if clean_line.startswith("0 FILE "):
                            if not is_mpd:
                                is_mpd = True

                            no_file = False

                            mpd_filename = strip_line.split(maxsplit=2)[2].lower()
                            if first_mpd_filename is None:
                                first_mpd_filename = mpd_filename

                            if current_file is not None:
                                file_lines_cache[current_file.filename] = current_file
                            current_file = LDrawFile(mpd_filename)
                        elif is_mpd:
                            if no_file:
                                continue

                            if clean_line.startswith("0 NOFILE"):
                                no_file = True
                                if current_file is not None:
                                    file_lines_cache[current_file.filename] = current_file
                                current_file = None

                            elif current_file is not None:
                                current_file.lines.append(line)
                        else:
                            if filename not in file_lines_cache:
                                file_lines_cache[filename] = LDrawFile(filename)
                            file_lines_cache[filename].lines.append(line)
                    if current_file is not None:
                        file_lines_cache[current_file.filename] = current_file
            except Exception as e:
                print(e)

            if first_mpd_filename is not None:
                filename = first_mpd_filename

        ldraw_file = LDrawFile(filename)
        ldraw_file.filepath = filepath
        ldraw_file.lines = file_lines_cache[filename].lines
        ldraw_file.parse_file()
        # print(ldraw_file)
        return ldraw_file

    # create meta nodes when those commands affect the scene
    # process meta command in place if it only affects the file
    def parse_file(self):
        for line in self.lines:
            clean_line = helpers.clean_line(line)
            strip_line = line.strip()

            if clean_line.lower().startswith("0 Name: ".lower()):
                self.name = strip_line.split(maxsplit=2)[2]
                continue

            if clean_line.lower().startswith("0 Author: ".lower()):
                self.author = strip_line.split(maxsplit=2)[2]
                continue

            if clean_line.startswith("0 !LDRAW_ORG "):
                self.actual_part_type = strip_line.split(maxsplit=2)[2].lower()
                self.part_type = LDrawFile.determine_part_type(self.actual_part_type)
                continue

            if clean_line.startswith("0 LDRAW_ORG "):
                self.actual_part_type = strip_line.split(maxsplit=2)[2].lower()
                self.part_type = LDrawFile.determine_part_type(self.actual_part_type)
                continue

            if clean_line.startswith("0 Official LCAD "):
                self.actual_part_type = strip_line.split(maxsplit=3)[3].lower()
                self.part_type = LDrawFile.determine_part_type(self.actual_part_type)
                continue

            if clean_line.startswith("0 Unofficial "):
                self.actual_part_type = strip_line.split(maxsplit=2)[2].lower()
                self.part_type = LDrawFile.determine_part_type(self.actual_part_type)
                continue

            if clean_line.startswith("0 Un-official "):
                self.actual_part_type = strip_line.split(maxsplit=2)[2].lower()
                self.part_type = LDrawFile.determine_part_type(self.actual_part_type)
                continue

            if clean_line.startswith("0 !COLOUR "):
                _params = helpers.get_params(clean_line, "0 !COLOUR ", lowercase=False)
                ldraw_colors.parse_color(_params)
                continue

            if clean_line.startswith("0 STEP"):
                ldraw_node = LDrawNode()
                ldraw_node.line = clean_line
                ldraw_node.meta_command = "step"
                self.child_nodes.append(ldraw_node)
                continue

            if clean_line.startswith("0 SAVE"):
                ldraw_node = LDrawNode()
                ldraw_node.line = clean_line
                ldraw_node.meta_command = "save"
                self.child_nodes.append(ldraw_node)
                continue

            if clean_line.startswith("0 CLEAR"):
                ldraw_node = LDrawNode()
                ldraw_node.line = clean_line
                ldraw_node.meta_command = "clear"
                self.child_nodes.append(ldraw_node)
                continue

            if clean_line in ["0 PRINT", "0 WRITE"]:
                ldraw_node = LDrawNode()
                ldraw_node.line = clean_line
                ldraw_node.meta_command = "print"
                ldraw_node.meta_args["message"] = clean_line.split(maxsplit=2)[2]
                self.child_nodes.append(ldraw_node)
                continue

            if clean_line.startswith("0 !LDCAD GROUP_DEF "):
                # http://www.melkert.net/LDCad/tech/meta
                _params = re.search(r"\S+\s+\S+\s+\S+\s+(\[.*\])\s+(\[.*\])\s+(\[.*\])\s+(\[.*\])\s+(\[.*\])", clean_line)

                ldraw_node = LDrawNode()
                ldraw_node.line = clean_line
                ldraw_node.meta_command = "group_def"

                id_args = re.search(r"\[(.*)=(.*)\]", _params[2])
                ldraw_node.meta_args["id"] = id_args[2]

                name_args = re.search(r"\[(.*)=(.*)\]", _params[4])
                ldraw_node.meta_args["name"] = name_args[2]

                self.child_nodes.append(ldraw_node)
                continue

            if clean_line.startswith("0 !LDCAD GROUP_NXT "):
                _params = re.search(r"\S+\s+\S+\s+\S+\s+(\[.*\])\s+(\[.*\])", clean_line)

                ldraw_node = LDrawNode()
                ldraw_node.line = clean_line
                ldraw_node.meta_command = "group_nxt"

                id_args = re.search(r"\[(.*)=(.*)\]", _params[1])
                ldraw_node.meta_args["id"] = id_args[2]

                self.child_nodes.append(ldraw_node)
                continue

            if clean_line.startswith("0 !LEOCAD GROUP BEGIN "):
                # https://www.leocad.org/docs/meta.html
                name_args = clean_line.split(maxsplit=4)
                ldraw_node = LDrawNode()
                ldraw_node.line = clean_line
                ldraw_node.meta_command = "group_begin"
                ldraw_node.meta_args["name"] = name_args[4]
                self.child_nodes.append(ldraw_node)
                continue

            if clean_line.startswith("0 !LEOCAD GROUP END"):
                ldraw_node = LDrawNode()
                ldraw_node.line = clean_line
                ldraw_node.meta_command = "group_end"
                self.child_nodes.append(ldraw_node)
                continue

            if clean_line.startswith("0 !LEOCAD CAMERA "):
                _params = helpers.get_params(clean_line, "0 !LEOCAD CAMERA ")
                if self.camera is None:
                    self.camera = ldraw_camera.LDrawCamera()

                # https://www.leocad.org/docs/meta.html
                # "Camera commands can be grouped in the same line"
                # _params = _params[1:] at the end bumps promotes _params[2] to _params[1]
                while len(_params) > 0:
                    if _params[0] == "fov":
                        self.camera.fov = float(_params[1])
                        _params = _params[2:]
                    elif _params[0] == "znear":
                        self.camera.z_near = float(_params[1])
                        _params = _params[2:]
                    elif _params[0] == "zfar":
                        self.camera.z_far = float(_params[1])
                        _params = _params[2:]
                    elif _params[0] in ["position", "target_position", "up_vector"]:
                        (x, y, z) = map(float, _params[1:4])
                        vector = mathutils.Vector((x, y, z))

                        if _params[0] == "position":
                            self.camera.position = vector

                        elif _params[0] == "target_position":
                            self.camera.target_position = vector

                        elif _params[0] == "up_vector":
                            self.camera.up_vector = vector

                        _params = _params[4:]

                    elif _params[0] == "orthographic":
                        self.camera.orthographic = True
                        _params = _params[1:]
                    elif _params[0] == "hidden":
                        self.camera.hidden = True
                        _params = _params[1:]
                    elif _params[0] == "name":
                        # "0 !LEOCAD CAMERA NAME Camera  2".split("NAME ")[1] => "Camera  2"
                        # "NAME Camera  2".split("NAME ")[1] => "Camera  2"
                        name_args = clean_line.split("NAME ")
                        self.camera.name = name_args[1]

                        # By definition this is the last of the parameters
                        _params = []

                        ldraw_camera.cameras.append(self.camera)
                        self.camera = None
                    else:
                        _params = _params[1:]
                continue

            if clean_line.startswith("0 !TEXMAP "):
                # https://www.ldraw.org/documentation/ldraw-org-file-format-standards/language-extension-for-texture-mapping.html
                _params = helpers.get_params(clean_line, "0 !TEXMAP ")

                if self.texmap_start:
                    if _params[0].lower() in ["fallback"]:
                        self.texmap_fallback = True
                    elif _params[0].lower() in ["end"]:
                        self.set_texmap_end()
                elif _params[0].lower() in ["start", "next"]:
                    if _params[0].lower() == "start":
                        self.texmap_start = True
                    elif _params[0].lower() == "next":
                        self.texmap_next = True
                    self.texmap_fallback = False

                    new_texmap = None
                    method = _params[1].lower()
                    if method in ['planar']:
                        _params = clean_line[len("0 !TEXMAP "):].split(maxsplit=11)  # planar

                        (x1, y1, z1, x2, y2, z2, x3, y3, z3) = map(float, _params[2:11])

                        texture_params = helpers.parse_csv_line(_params[11], 2)
                        texture = texture_params[0]
                        glossmap = texture_params[1]

                        new_texmap = TexMap(
                            method=method,
                            parameters=[
                                mathutils.Vector((x1, y1, z1)),
                                mathutils.Vector((x2, y2, z2)),
                                mathutils.Vector((x3, y3, z3)),
                            ],
                            texture=texture,
                            glossmap=glossmap,
                        )
                    elif method in ['cylindrical']:
                        _params = clean_line[len("0 !TEXMAP "):].split(maxsplit=12)  # cylindrical

                        (x1, y1, z1, x2, y2, z2, x3, y3, z3, a) = map(float, _params[2:12])

                        texture_params = helpers.parse_csv_line(_params[12], 2)
                        texture = texture_params[0]
                        glossmap = texture_params[1]

                        new_texmap = TexMap(
                            method=method,
                            parameters=[
                                mathutils.Vector((x1, y1, z1)),
                                mathutils.Vector((x2, y2, z2)),
                                mathutils.Vector((x3, y3, z3)),
                                a,
                            ],
                            texture=texture,
                            glossmap=glossmap,
                        )
                    elif method in ['spherical']:
                        _params = clean_line[len("0 !TEXMAP "):].split(maxsplit=13)  # spherical

                        (x1, y1, z1, x2, y2, z2, x3, y3, z3, a, b) = map(float, _params[2:13])

                        texture_params = helpers.parse_csv_line(_params[13], 2)
                        texture = texture_params[0]
                        glossmap = texture_params[1]

                        new_texmap = TexMap(
                            method=method,
                            parameters=[
                                mathutils.Vector((x1, y1, z1)),
                                mathutils.Vector((x2, y2, z2)),
                                mathutils.Vector((x3, y3, z3)),
                                a,
                                b,
                            ],
                            texture=texture,
                            glossmap=glossmap,
                        )

                    if new_texmap is not None:
                        if texmap.texmap is not None:
                            texmap.texmaps.append(texmap.texmap)
                        texmap.texmap = new_texmap
                continue

            if self.texmap_start:
                if clean_line.startswith('0 !: '):
                    # remove 0 !: from line so that it can be parsed like a normal line
                    _clean_line = clean_line[len('0 !: '):].strip()
                    self.parse_geometry_line(_clean_line)
                else:
                    self.parse_geometry_line(clean_line)

                if self.texmap_next:
                    self.set_texmap_end()
                continue

            if not self.texmap_fallback and self.parse_geometry_line(clean_line):
                continue

            # this goes last so that description will be properly detected
            if clean_line.startswith("0"):
                if self.texmap_next:
                    # if 0 line and texmap next, error
                    # also error
                    continue
                if clean_line.startswith("0 //"):
                    continue
                if self.description is None:
                    self.description = clean_line.split(maxsplit=1)[1]
                continue

        if self.extra_geometry is not None or self.extra_child_nodes is not None:
            _key = []
            _key.append(self.filename)
            _key.append("extra")
            if texmap.texmap is not None:
                _key.append(texmap.texmap.id)
            _key = "_".join([str(k).lower() for k in _key])

            if _key not in key_map:
                key_map[_key] = str(uuid.uuid4())
            key = key_map[_key]

            if key not in file_cache:
                filename = f"{self.name}_extra"
                ldraw_file = LDrawFile(filename)
                ldraw_file.part_type = "part"
                ldraw_file.child_nodes = (self.extra_child_nodes or [])
                ldraw_file.geometry = (self.extra_geometry or LDrawGeometry())
                file_cache[key] = ldraw_file
            ldraw_file = file_cache[key]
            ldraw_node = LDrawNode()
            ldraw_node.line = ""
            ldraw_node.file = ldraw_file
            self.child_nodes.append(ldraw_node)

    # if there's a line type specified, determine what that type is
    @classmethod
    def determine_part_type(cls, actual_part_type):
        if "primitive" in actual_part_type:
            return "primitive"
        elif "subpart" in actual_part_type:
            return "subpart"
        elif "part" in actual_part_type:
            return "part"
        elif "shortcut" in actual_part_type:
            return "shortcut"
        elif "model" in actual_part_type:
            return "model"
        elif "configuration" in actual_part_type:
            return "configuration"
        return "part"

    def set_texmap_end(self):
        if len(texmap.texmaps) < 1:
            texmap.texmap = None
        else:
            texmap.texmap = texmap.texmaps.pop()
        self.texmap_start = False
        self.texmap_next = False
        self.texmap_fallback = False

    def parse_geometry_line(self, clean_line):
        _params = clean_line.split(maxsplit=14)
        if _params[0] == "1":
            color_code = _params[1]

            (x, y, z, a, b, c, d, e, f, g, h, i) = map(float, _params[2:14])
            matrix = mathutils.Matrix((
                (a, b, c, x),
                (d, e, f, y),
                (g, h, i, z),
                (0, 0, 0, 1)
            ))

            filename = _params[14].lower()

            # filename = "stud-logo.dat"
            # parts = filename.split(".") => ["stud-logo", "dat"]
            # name = parts[0] => "stud-logo"
            # name_parts = name.split('-') => ["stud", "logo"]
            # stud_name = name_parts[0] => "stud"
            # chosen_logo = special_bricks.chosen_logo => "logo5"
            # ext = parts[1] => "dat"
            # filename = f"{stud_name}-{chosen_logo}.{ext}" => "stud-logo5.dat"
            if import_options.display_logo and filename in ldraw_part_types.stud_names:
                parts = filename.split(".")
                name = parts[0]
                name_parts = name.split('-')
                stud_name = name_parts[0]
                chosen_logo = import_options.chosen_logo
                ext = parts[1]
                filename = f"{stud_name}-{chosen_logo}.{ext}"

            _key = []
            _key.append(filename)
            if texmap.texmap is not None:
                _key.append(texmap.texmap.id)
            _key = "_".join([str(k).lower() for k in _key])

            if _key not in key_map:
                key_map[_key] = str(uuid.uuid4())
            key = key_map[_key]

            if key not in file_cache:
                ldraw_file = LDrawFile.get_file(filename)
                if ldraw_file is None:
                    return True
                file_cache[key] = ldraw_file
            ldraw_file = file_cache[key]

            if import_options.no_studs and ldraw_file.is_like_stud():
                return True

            ldraw_node = LDrawNode()
            ldraw_node.line = clean_line
            ldraw_node.file = ldraw_file
            ldraw_node.color_code = color_code
            ldraw_node.matrix = matrix

            # if any line in a model file is a subpart, treat that model as a part,
            # otherwise subparts are not parsed correctly
            # if subpart found, create new LDrawNode with those subparts and add that to child_nodes
            if self.is_like_model() and (ldraw_file.is_subpart() or ldraw_file.is_primitive()):
                if self.extra_child_nodes is None:
                    self.extra_child_nodes = []
                self.extra_child_nodes.append(ldraw_node)
            else:
                self.child_nodes.append(ldraw_node)
            return True
        elif _params[0] in ["2", "3", "4", "5"]:
            # add geometry that is in a model or shortcut file to a file
            # object so that it will be parsed
            if self.is_like_model():
                if self.extra_geometry is None:
                    self.extra_geometry = LDrawGeometry()
                self.extra_geometry.parse_face(_params, texmap.texmap)
            else:
                self.geometry.parse_face(_params, texmap.texmap)
            return True
        return False

    def is_configuration(self):
        return self.part_type in ldraw_part_types.configuration_types

    # this allows shortcuts to be split into their individual parts if desired
    def is_like_model(self):
        return self.is_model() or (import_options.treat_shortcut_as_model and self.is_shortcut())

    def is_model(self):
        return self.part_type in ldraw_part_types.model_types

    def is_shortcut(self):
        return self.part_type in ldraw_part_types.shortcut_types

    def is_part(self):
        return self.part_type in ldraw_part_types.part_types

    def is_subpart(self):
        return self.part_type in ldraw_part_types.subpart_types

    def is_primitive(self):
        return self.part_type in ldraw_part_types.primitive_types

    def is_like_stud(self):
        return self.name.startswith("stud")

    def is_stud(self):
        return self.name in ldraw_part_types.stud_names

    def is_edge_logo(self):
        return self.name in ldraw_part_types.edge_logo_names

    def is_logo(self):
        return self.name in ldraw_part_types.logo_names

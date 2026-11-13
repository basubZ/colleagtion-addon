# SPDX-License-Identifier: GPL-2.0-or-later
"""
Kartonkomprom Compose Setup
Аддон для быстрой настройки композ-сцены под Blender 5.1.
"""

import math
import os
import bpy
from mathutils import Matrix


NODE_GROUP_NAME = "Collegtion compose"
BLEND_FILE = "compose.blend"

LIGHTS_BLEND = "lights.blend"
LIGHTS_ROOT_COLL = "Lights"
TORSO_BONE = "torso"

# оверлеи камеры: (файл, opacity)
CAM_OVERLAYS = (
    ("safe_zone_1.png", 0.5),
    ("safe_zone_dop.png", 1.0),
)
OVERLAY_RES = 1920

BOKEH_IMAGE = "bokeh.png"

# import characters
ASSET_LIB_NAME = "characters"
RIGS_PREFIX = "KOLLEGI_rigs"
DEFAULT_RIG_VERSION = "5.7"
CHARACTERS_COLL = "Characters"
CHARACTERS = (
    "Boss", "UST", "Buhgaltersha", "VS",
    "Security", "Baby", "IT", "SMM",
)

# import locations
LOCATION_LIB_NAME = "Location"
LOCATION_PREFIX = "Office_KK_"
DEFAULT_LOCATION_VERSION = "2.4"
LOCATION_COLL = "Location"
LOCATIONS = (
    "Office", "Boss cabinet", "Kitchen", "Corridor",
    "Lift", "WC", "Storage", "Mini corridor",
    "boss_wall", "kitchen_wall", "corridor_wall",
)

# для авто-перелинковки на открытии файла: (имя asset library, префикс файла)
RELINK_CATEGORIES = (
    (ASSET_LIB_NAME, RIGS_PREFIX),
    (LOCATION_LIB_NAME, LOCATION_PREFIX),
)

# AgX look: точный идентификатор + запасные варианты на случай другой сборки OCIO
LOOK_CANDIDATES = (
    "AgX - Medium High Contrast",
    "Medium High Contrast",
)

# Настройки рендера со скрина 2
RENDER_SETTINGS = {
    "engine": "CYCLES",
    "device": "GPU",
    # Render
    "samples": 216,
    "adaptive_threshold": 0.04,
    "adaptive_min_samples": 0,
    "time_limit": 0.0,
    "use_denoising": True,
    # Viewport
    "preview_samples": 256,
    "preview_adaptive_threshold": 0.1,
    "preview_adaptive_min_samples": 0,
    "use_preview_denoising": True,
}


# --------------------------------------------------------------------------- #
#  helpers
# --------------------------------------------------------------------------- #
def _blend_path():
    return os.path.join(os.path.dirname(__file__), BLEND_FILE)


def _get_or_append_group():
    """Возвращает нод-группу, при необходимости добавляя её из compose.blend."""
    g = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if g is not None:
        return g

    path = _blend_path()
    if not os.path.exists(path):
        return None

    with bpy.data.libraries.load(path, link=False) as (src, dst):
        if NODE_GROUP_NAME in src.node_groups:
            dst.node_groups = [NODE_GROUP_NAME]
    return bpy.data.node_groups.get(NODE_GROUP_NAME)


def _find_node(tree, bl_idname):
    for n in tree.nodes:
        if n.bl_idname == bl_idname:
            return n
    return None


def _active_group(context):
    """Композ-группа, назначенная сцене (или добавленная в файл)."""
    g = getattr(context.scene, "compositing_node_group", None)
    if g is None:
        g = bpy.data.node_groups.get(NODE_GROUP_NAME)
    return g


def _branch_insert_point(rl, alpha, socket_name):
    """Ищет, куда воткнуть блюр в ветке Background/Foreground.

    Идёт назад от входа Alpha Over до точки, где цепочка разветвляется
    (сокет с несколькими связями) или до Render Layers. Возвращает
    входной сокет, ПЕРЕД которым надо вставить ноду."""
    inp = alpha.inputs.get(socket_name)
    if inp is None or not inp.is_linked:
        return None
    seen = set()
    while inp is not None and inp.is_linked:
        link = inp.links[0]
        src_sock, src_node = link.from_socket, link.from_node
        # точка разветвления или сам Render Layers -> вставляем здесь
        if len(src_sock.links) > 1 or src_node == rl:
            return inp
        if src_node in seen:
            return inp
        seen.add(src_node)
        nxt = src_node.inputs.get("Image")
        if nxt is None or not nxt.is_linked:
            nxt = next((i for i in src_node.inputs if i.is_linked), None)
        if nxt is None:
            return inp
        inp = nxt
    return None


def _insert_vector_blur(tree, socket_name, shutter=0.2):
    """Вставляет Vector Blur в нужную ветку. Возвращает (ok, message)."""
    rl = _find_node(tree, "CompositorNodeRLayers")
    alpha = _find_node(tree, "CompositorNodeAlphaOver")
    if rl is None or alpha is None:
        return False, "Не нашёл Render Layers или Alpha Over в группе."

    target = _branch_insert_point(rl, alpha, socket_name)
    if target is None:
        return False, "Не нашёл ветку — проверь связи в композе."

    # уже вставлено?
    src_node = target.links[0].from_node if target.is_linked else None
    if src_node is not None and src_node.bl_idname == "CompositorNodeVecBlur":
        return False, "Vector Blur в этой ветке уже стоит."
    if target.node.bl_idname == "CompositorNodeVecBlur":
        return False, "Vector Blur в этой ветке уже стоит."

    for name in ("Vector", "Depth"):
        if name not in [s.name for s in rl.outputs]:
            return False, "У Render Layers нет пассов Vector/Depth — жми Set up сначала."

    src_sock = target.links[0].from_socket
    node = target.node
    vb = tree.nodes.new("CompositorNodeVecBlur")
    vb.location = (node.location.x - 210, node.location.y - 60)
    if "Shutter" in vb.inputs:
        vb.inputs["Shutter"].default_value = shutter

    links = tree.links
    links.new(src_sock, vb.inputs["Image"])
    links.new(rl.outputs["Vector"], vb.inputs["Speed"])
    links.new(rl.outputs["Depth"], vb.inputs["Depth"])
    # новая связь заменит старую в этом входе
    links.new(vb.outputs["Image"], target)
    return True, "Vector Blur добавлен, Shutter = %.2f." % shutter


def _insert_mask_vector_blur(tree, shutter=0.2):
    """Vector Blur на маску: между ID Mask.Alpha и Alpha Over.Factor."""
    rl = _find_node(tree, "CompositorNodeRLayers")
    alpha = _find_node(tree, "CompositorNodeAlphaOver")
    if rl is None or alpha is None:
        return False
    factor = alpha.inputs.get("Factor")
    if factor is None or not factor.is_linked:
        return False
    link = factor.links[0]
    src_node, src_sock = link.from_node, link.from_socket
    if src_node.bl_idname == "CompositorNodeVecBlur":
        return False  # уже стоит
    for name in ("Vector", "Depth"):
        if name not in [s.name for s in rl.outputs]:
            return False
    vb = tree.nodes.new("CompositorNodeVecBlur")
    vb.location = (alpha.location.x - 320, alpha.location.y - 320)
    if "Shutter" in vb.inputs:
        vb.inputs["Shutter"].default_value = shutter
    links = tree.links
    links.new(src_sock, vb.inputs["Image"])
    links.new(rl.outputs["Vector"], vb.inputs["Speed"])
    links.new(rl.outputs["Depth"], vb.inputs["Depth"])
    links.new(vb.outputs["Image"], factor)
    return True


BOKEH_SIZE = 10.0
HOLE_DILATE = 4      # px: насколько расширять дыру под персами
HOLE_INPAINT = 80    # px: заливка дыры, должна быть заметно больше BOKEH_SIZE
EDGE_SOFTEN = 2.0    # px: мягкость края персов


def _set_in(node, name, value, attr=None):
    """Ставит значение входа-сокета; для старых сборок — через свойство ноды."""
    sock = node.inputs.get(name)
    if sock is not None and hasattr(sock, "default_value"):
        try:
            sock.default_value = value
            return
        except Exception:
            pass
    if attr is not None:
        try:
            setattr(node, attr, value)
        except Exception:
            pass


def _insert_bokeh_blur(tree):
    """Bokeh Blur на фон без ореола вокруг персов.

    1. ID Mask -> Dilate -> Invert -> Set Alpha: персы вырезаются из фона.
    2. Inpaint заливает дыру цветами фона (это ставится сразу после
       разветвления, ДО Glare/CC, чтобы блум персов не тёк в фон).
    3. Bokeh Blur прямо перед Alpha Over.Background, без маски.
    4. Маска персов в Alpha Over.Factor: Anti-Alias + лёгкий Blur по краю.
    Возвращает (ok, message)."""
    rl = _find_node(tree, "CompositorNodeRLayers")
    alpha = _find_node(tree, "CompositorNodeAlphaOver")
    if rl is None or alpha is None:
        return False, "Не нашёл Render Layers или Alpha Over в группе."
    bg = alpha.inputs.get("Background")
    factor = alpha.inputs.get("Factor")
    if bg is None or not bg.is_linked:
        return False, "Нет связи в Background."
    if factor is None or not factor.is_linked:
        return False, "Нет маски персов в Alpha Over.Factor."
    if tree.nodes.get("KK Fill Hole") is not None:
        return False, "Bokeh Blur в фоне уже стоит."
    if bg.links[0].from_node.bl_idname == "CompositorNodeBokehBlur":
        return False, "Bokeh Blur в фоне уже стоит."

    target = _branch_insert_point(rl, alpha, "Background")
    if target is None:
        return False, "Не нашёл ветку фона — проверь связи в композе."

    path = os.path.join(os.path.dirname(__file__), BOKEH_IMAGE)
    if not os.path.exists(path):
        return False, "Нет файла %s рядом с аддоном." % BOKEH_IMAGE
    img = bpy.data.images.load(path, check_existing=True)
    try:
        img.colorspace_settings.name = "Non-Color"
    except Exception:
        pass
    if img.packed_file is None:
        try:
            img.pack()
        except Exception:
            pass

    N, links = tree.nodes, tree.links
    mask_sock = factor.links[0].from_socket      # маска персов (ID Mask / её Vector Blur)
    branch_sock = target.links[0].from_socket    # точка, где фон отделяется от персов
    tx, ty = target.node.location

    # --- 1-2. вырезать персов и залить дыру -------------------------------
    frame = N.new("NodeFrame")
    frame.name, frame.label = "KK BG Fill", "BG fill (no halo)"

    de = N.new("CompositorNodeDilateErode")
    de.name = de.label = "KK Hole Dilate"
    de.location = (tx - 720, ty - 220)
    _set_in(de, "Type", "Steps", "mode")
    _set_in(de, "Size", HOLE_DILATE, "distance")

    inv = N.new("CompositorNodeInvert")
    inv.name = inv.label = "KK Hole Invert"
    inv.location = (tx - 540, ty - 220)

    sa = N.new("CompositorNodeSetAlpha")
    sa.name = sa.label = "KK Cut Chars"
    sa.location = (tx - 360, ty)
    _set_in(sa, "Type", "Apply Mask", "mode")

    ip = N.new("CompositorNodeInpaint")
    ip.name = ip.label = "KK Fill Hole"
    ip.location = (tx - 190, ty)
    _set_in(ip, "Size", HOLE_INPAINT, "distance")

    for n in (de, inv, sa, ip):
        n.parent = frame

    links.new(mask_sock, de.inputs["Mask"])
    links.new(de.outputs["Mask"], inv.inputs["Color"])
    links.new(branch_sock, sa.inputs["Image"])
    links.new(inv.outputs["Color"], sa.inputs["Alpha"])
    links.new(sa.outputs["Image"], ip.inputs["Image"])
    links.new(ip.outputs["Image"], target)       # заменит старую связь

    # --- 3. Bokeh Blur перед Alpha Over.Background --------------------------
    bg_src = bg.links[0].from_socket
    bb = N.new("CompositorNodeBokehBlur")
    bb.location = (alpha.location.x - 280, alpha.location.y + 40)
    _set_in(bb, "Size", BOKEH_SIZE, "blur_max")

    img_node = N.new("CompositorNodeImage")
    img_node.image = img
    img_node.location = (bb.location.x - 280, bb.location.y + 220)

    links.new(bg_src, bb.inputs["Image"])
    links.new(img_node.outputs["Image"], bb.inputs["Bokeh"])
    links.new(bb.outputs["Image"], bg)

    # --- 4. мягкий край персов ----------------------------------------------
    idm = _find_node(tree, "CompositorNodeIDMask")
    if idm is not None:
        _set_in(idm, "Anti-Alias", True, "use_antialiasing")

    # в compose.blend маска уже идёт через Blur (возможно, за Vector Blur) —
    # второй не ставим
    node, seen = mask_sock.node, set()
    while node is not None and node not in seen:
        if node.bl_idname == "CompositorNodeBlur":
            return True, "Bokeh Blur в фон без ореола (Size %d)." % BOKEH_SIZE
        seen.add(node)
        nxt = node.inputs.get("Image")
        node = nxt.links[0].from_node if (nxt is not None and nxt.is_linked) else None

    soft = N.new("CompositorNodeBlur")
    soft.name = soft.label = "KK Edge Soften"
    soft.location = (alpha.location.x - 220, alpha.location.y - 300)
    _set_in(soft, "Type", "Gaussian", "filter_type")
    _set_in(soft, "Size", (EDGE_SOFTEN, EDGE_SOFTEN))
    if soft.inputs.get("Size") is None:  # старые сборки: size_x/size_y в пикселях
        soft.size_x = soft.size_y = int(EDGE_SOFTEN)

    links.new(mask_sock, soft.inputs["Image"])
    links.new(soft.outputs["Image"], factor)

    return True, "Bokeh Blur в фон без ореола (Size %d, края персов %g px)." % (
        BOKEH_SIZE, EDGE_SOFTEN)


def _lights_blend_path():
    return os.path.join(os.path.dirname(__file__), LIGHTS_BLEND)


def _append_light_rig():
    """Добавляет весь световой риг из lights.blend. Возвращает (empty, lights, new)."""
    path = _lights_blend_path()
    if not os.path.exists(path):
        return None, [], []
    before = set(bpy.data.objects)
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = list(src.objects)
    new = [o for o in bpy.data.objects if o not in before]
    for o in new:
        o.use_fake_user = False
    empty = next((o for o in new if o.type == "EMPTY"), None)
    lights = [o for o in new if o.type == "LIGHT"]
    return empty, lights, new


def _find_torso(arm):
    pb = arm.pose.bones.get(TORSO_BONE)
    if pb is not None:
        return pb
    for b in arm.pose.bones:
        if b.name.lower() == TORSO_BONE:
            return b
    return None


def _find_collection_in_scene(scene, name):
    def rec(coll):
        for ch in coll.children:
            if ch.name == name:
                return ch
            r = rec(ch)
            if r is not None:
                return r
        return None
    return rec(scene.collection)


def _ensure_lights_root(scene):
    root = _find_collection_in_scene(scene, LIGHTS_ROOT_COLL)
    if root is None:
        root = bpy.data.collections.new(LIGHTS_ROOT_COLL)
        scene.collection.children.link(root)
    return root


def _ensure_subcollection(root, name):
    for ch in root.children:
        if ch.name == name:
            return ch
    sub = bpy.data.collections.new(name)
    root.children.link(sub)
    return sub


def _armature_collection(arm, scene):
    """Коллекция, в которой лежит armature (кроме мастер-коллекции сцены)."""
    cols = [c for c in arm.users_collection if c is not scene.collection]
    if cols:
        return cols[0]
    if arm.users_collection:
        return arm.users_collection[0]
    return scene.collection


def _get_asset_lib(name):
    for lib in bpy.context.preferences.filepaths.asset_libraries:
        if lib.name.lower() == name.lower():
            return lib
    return None


def _asset_lib_path(name):
    lib = _get_asset_lib(name)
    return bpy.path.abspath(lib.path) if lib is not None else None


def _find_blend(root, filename):
    if not root or not os.path.isdir(root):
        return None
    direct = os.path.join(root, filename)
    if os.path.exists(direct):
        return direct
    for dp, _dirs, files in os.walk(root):
        if filename in files:
            return os.path.join(dp, filename)
    return None


def _relink_libraries():
    """Чинит битые пути KOLLEGI_rigs* / Office_KK_* по локальным библиотекам
    characters / Location. Возвращает (перелинковано, не найдено)."""
    relinked, unresolved = 0, 0
    for lib_name, prefix in RELINK_CATEGORIES:
        lib_obj = _get_asset_lib(lib_name)
        root = bpy.path.abspath(lib_obj.path) if lib_obj is not None else None
        cache = {}
        for lib in list(bpy.data.libraries):
            base = os.path.basename(lib.filepath)
            if not base.startswith(prefix):
                continue
            if os.path.exists(bpy.path.abspath(lib.filepath)):
                continue  # путь резолвится — не трогаем
            target = None
            if root and os.path.isdir(root):
                if base not in cache:
                    cache[base] = _find_blend(root, base)
                target = cache[base]
            if not target:
                unresolved += 1
                continue
            try:
                lib.filepath = target
                lib.reload()
                relinked += 1
            except Exception:
                unresolved += 1
    return relinked, unresolved


def _ensure_coll(scene, name):
    c = _find_collection_in_scene(scene, name)
    if c is None:
        c = bpy.data.collections.new(name)
        scene.collection.children.link(c)
    return c


def _find_layer_collection(root_lc, coll):
    if root_lc.collection == coll:
        return root_lc
    for ch in root_lc.children:
        r = _find_layer_collection(ch, coll)
        if r is not None:
            return r
    return None


def _library_has_users(lib):
    for attr in ("objects", "meshes", "armatures", "collections", "materials",
                 "node_groups", "actions", "images", "curves", "lights",
                 "cameras", "textures", "worlds"):
        data = getattr(bpy.data, attr, None)
        if data is None:
            continue
        for d in data:
            if getattr(d, "library", None) == lib:
                return True
    return False


def _remove_unused_libraries():
    """Убирает библиотеки, на которые не ссылается ни один локальный датаблок."""
    removed = 0
    for lib in list(bpy.data.libraries):
        if not _library_has_users(lib):
            try:
                bpy.data.libraries.remove(lib)
                removed += 1
            except Exception:
                pass
    return removed


def _relocate_widgets(context, new_objs, new_colls):
    """Переносит WGT-объекты в скрытую верхнеуровневую коллекцию WGTS."""
    scene = context.scene
    vl = context.view_layer
    wgts = [o for o in new_objs if o.name.startswith("WGT-")]
    if not wgts:
        return
    wcol = next((c for c in scene.collection.children if c.name == "WGTS"), None)
    made = False
    if wcol is None:
        wcol = bpy.data.collections.new("WGTS_kk_tmp")
        scene.collection.children.link(wcol)
        made = True
    for o in wgts:
        for c in list(o.users_collection):
            try:
                c.objects.unlink(o)
            except Exception:
                pass
        if o.name not in [x.name for x in wcol.objects]:
            wcol.objects.link(o)
    # убираем опустевшие приаппенденные коллекции (напр. WGTS ига)
    for c in list(new_colls):
        try:
            if len(c.objects) == 0 and len(c.children) == 0:
                bpy.data.collections.remove(c)
        except Exception:
            pass
    if made:
        try:
            wcol.name = "WGTS"
        except Exception:
            pass
    lc = _find_layer_collection(vl.layer_collection, wcol)
    if lc is not None:
        lc.exclude = True


def _append_collection(context, blend_path, coll_name, target_coll, final_name):
    """Аппенд коллекции в target_coll под именем final_name; WGT -> WGTS."""
    scene = context.scene
    dest = _ensure_coll(scene, target_coll)
    before_objs = set(bpy.data.objects)
    before_colls = set(bpy.data.collections)
    with bpy.data.libraries.load(blend_path, link=False) as (df, dt):
        if coll_name not in df.collections:
            return None, "В файле нет коллекции '%s'." % coll_name
        dt.collections = [coll_name]
    app = dt.collections[0]
    if app.name not in [c.name for c in dest.children]:
        try:
            dest.children.link(app)
        except Exception:
            pass
    if app.name != final_name:
        try:
            app.name = final_name
        except Exception:
            pass
    new_objs = [o for o in bpy.data.objects if o not in before_objs]
    new_colls = [c for c in bpy.data.collections if c not in before_colls and c is not app]
    _relocate_widgets(context, new_objs, new_colls)
    _remove_unused_libraries()
    return app, None


def _make_hierarchy_editable(root_coll):
    """Снимает флаг system override со всей иерархии, чтобы объекты можно
    было двигать сразу, без кнопки 'make fully local' (она ломает оверрайд)."""
    if root_coll is None:
        return 0
    count = 0
    ids = [root_coll]
    stack = [root_coll]
    while stack:
        c = stack.pop()
        for ch in getattr(c, "children", []):
            ids.append(ch)
            stack.append(ch)
    try:
        ids.extend(list(root_coll.all_objects))
    except Exception:
        pass
    for d in ids:
        ovl = getattr(d, "override_library", None)
        if ovl is None:
            continue
        try:
            if ovl.is_system_override:
                ovl.is_system_override = False
                count += 1
        except Exception:
            pass
    return count


def _link_and_override(context, blend_path, coll_name, target_coll,
                       final_name=None, use_relative=True):
    """Линкует коллекцию, делает library override (Selected & Content)
    и кладёт её в target_coll под именем final_name. Дубликаты чистит."""
    scene = context.scene
    vl = context.view_layer
    dest = _ensure_coll(scene, target_coll)
    before = {c.name for c in scene.collection.children}
    libs_before = set(bpy.data.libraries)
    if final_name is None:
        final_name = coll_name

    with bpy.data.libraries.load(blend_path, link=True) as (df, dt):
        if coll_name not in df.collections:
            return None, "В файле нет коллекции '%s'." % coll_name
        dt.collections = [coll_name]
    linked = dt.collections[0]

    # Путь к библиотеке -> относительный, но ТОЛЬКО если библиотека новая.
    # Уже существующую трогать нельзя: она общая для всех ранее
    # залинкованных персонажей/локаций, и битый путь снесёт их оверрайды.
    lib = getattr(linked, "library", None)
    if (lib is not None and lib not in libs_before
            and use_relative and bpy.data.filepath):
        old_path = lib.filepath
        try:
            lib.filepath = bpy.path.relpath(bpy.path.abspath(lib.filepath))
            # проверяем, что новый путь реально резолвится, иначе откат
            if not os.path.exists(bpy.path.abspath(lib.filepath)):
                lib.filepath = old_path
        except Exception:
            try:
                lib.filepath = old_path
            except Exception:
                pass

    # Blender 5.3+: оверрайд создаётся только для коллекции, которая уже стоит
    # в сцене (иначе override_hierarchy_create возвращает None). Временно
    # вешаем линк в сцену, после оверрайда убираем.
    temp_linked = False
    if linked not in scene.collection.children.values():
        try:
            scene.collection.children.link(linked)
            temp_linked = True
        except Exception:
            pass

    override = linked.override_hierarchy_create(scene, vl, do_fully_editable=True)

    if temp_linked:
        try:
            scene.collection.children.unlink(linked)
        except Exception:
            pass
    if override is None:
        return None, "Не удалось создать library override для '%s'." % coll_name
    _make_hierarchy_editable(override)

    # keeper — именно созданный оверрайд (линкнутая коллекция с тем же
    # именем могла остаться в сцене)
    new_master = [c for c in scene.collection.children if c.name not in before]
    keeper = override if override.library is None else next(
        (c for c in new_master if c.name == coll_name and c.library is None), override)

    # чистим лишние новые верхнеуровневые чайлды (дубликаты) — точечно,
    # без глобального orphans_purge, чтобы не задеть чужие оверрайды
    for c in list(scene.collection.children):
        if c is keeper or c.name in before:
            continue
        try:
            scene.collection.children.unlink(c)
        except Exception:
            continue
        try:
            if c.library is None and c.users == 0:
                bpy.data.collections.remove(c)
        except Exception:
            pass

    # keeper -> в целевую коллекцию
    if keeper.name in [c.name for c in scene.collection.children]:
        try:
            scene.collection.children.unlink(keeper)
        except Exception:
            pass
    if keeper.name not in [c.name for c in dest.children]:
        try:
            dest.children.link(keeper)
        except Exception:
            pass

    if keeper.name != final_name:
        try:
            keeper.name = final_name
        except Exception:
            pass
    return keeper, None


# --------------------------------------------------------------------------- #
#  operators
# --------------------------------------------------------------------------- #
class KK_OT_setup_file(bpy.types.Operator):
    bl_idname = "kk.setup_file"
    bl_label = "Set up file"
    bl_description = "Композ Collegtion compose, AgX, cryptomatte asset, настройки рендера"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        vl = context.view_layer

        # 1. композ-группа
        scenes_before = set(bpy.data.scenes)
        g = _get_or_append_group()
        if g is None:
            self.report({"ERROR"}, "Не нашёл '%s' в compose.blend рядом с аддоном." % NODE_GROUP_NAME)
            return {"CANCELLED"}

        scene.use_nodes = True
        scene.render.use_compositing = True
        # Post Processing: Sequencer выкл
        scene.render.use_sequencer = False
        # Cycles: Fast GI Approximation выкл
        try:
            scene.cycles.use_fast_gi = False
        except Exception:
            pass
        scene.compositing_node_group = g

        # нода Render Layers должна смотреть на текущую сцену/вьюлеер
        for n in g.nodes:
            if n.bl_idname == "CompositorNodeRLayers":
                try:
                    n.scene = scene
                    n.layer = vl.name
                except Exception:
                    pass

        # append притащил лишнюю сцену из compose.blend (Scene.001) — убираем
        for s in list(bpy.data.scenes):
            if s not in scenes_before and s is not scene:
                try:
                    bpy.data.scenes.remove(s, do_unlink=True)
                except Exception:
                    pass

        # 2. color management: AgX + Medium Low Contrast
        vs = scene.view_settings
        try:
            vs.view_transform = "AgX"
        except Exception:
            self.report({"WARNING"}, "Не удалось выставить AgX View Transform.")
        for look in LOOK_CANDIDATES:
            try:
                vs.look = look
                break
            except Exception:
                continue

        # 3. Object Index пасс (для ноды ID Mask)
        vl.use_pass_object_index = True

        # 4. настройки рендера (скрин 2)
        r = RENDER_SETTINGS
        scene.render.engine = r["engine"]
        cy = scene.cycles
        try:
            cy.device = r["device"]
        except Exception:
            pass
        cy.samples = r["samples"]
        cy.adaptive_threshold = r["adaptive_threshold"]
        cy.adaptive_min_samples = r["adaptive_min_samples"]
        cy.time_limit = r["time_limit"]
        cy.use_denoising = r["use_denoising"]
        cy.preview_samples = r["preview_samples"]
        cy.preview_adaptive_threshold = r["preview_adaptive_threshold"]
        cy.preview_adaptive_min_samples = r["preview_adaptive_min_samples"]
        cy.use_preview_denoising = r["use_preview_denoising"]

        # 5. частота кадров 10 fps
        scene.render.fps = 10
        scene.render.fps_base = 1.0

        # 6. backface culling в solid во всех 3D вьюпортах
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        try:
                            space.shading.show_backface_culling = True
                        except Exception:
                            pass

        self.report({"INFO"}, "Файл настроен: композ + AgX + Object Index + рендер + backface culling.")
        return {"FINISHED"}


class _KK_MotionBlurBase(bpy.types.Operator):
    bl_options = {"REGISTER", "UNDO"}
    socket = "Background"

    def execute(self, context):
        scene = context.scene
        vl = context.view_layer

        g = _active_group(context)
        if g is None:
            self.report({"ERROR"}, "Композ не настроен — жми Set up file.")
            return {"CANCELLED"}

        # включаем пассы Depth и Vector
        vl.use_pass_z = True
        vl.use_pass_vector = True

        # даём дереву обновить сокеты Render Layers
        rl = _find_node(g, "CompositorNodeRLayers")
        if rl is not None:
            try:
                rl.update()
            except Exception:
                pass
        try:
            g.nodes.update()
        except Exception:
            pass

        ok, msg = _insert_vector_blur(g, self.socket, shutter=0.2)
        # моушн блюр на маску (ID Mask -> Alpha Over.Factor), один раз
        mask_added = _insert_mask_vector_blur(g, shutter=0.2)
        if ok and mask_added:
            msg = "Vector Blur добавлен (ветка + маска), Shutter = 0.20."
        self.report({"INFO"} if ok else {"WARNING"}, msg)
        return {"FINISHED"} if ok else {"CANCELLED"}


class KK_OT_motion_blur_bg(_KK_MotionBlurBase):
    bl_idname = "kk.motion_blur_bg"
    bl_label = "Add motion blur to BG"
    bl_description = "Vector Blur в ветку 1 (Background)"
    socket = "Background"


class KK_OT_motion_blur_fg(_KK_MotionBlurBase):
    bl_idname = "kk.motion_blur_fg"
    bl_label = "Add motion blur to FG"
    bl_description = "Vector Blur в ветку 2 (Foreground)"
    socket = "Foreground"


class KK_OT_bokeh_blur_bg(bpy.types.Operator):
    bl_idname = "kk.bokeh_blur_bg"
    bl_label = "Add bokeh blur to BG"
    bl_description = "Bokeh Blur на фон без ореола: персы вырезаются, дыра заливается Inpaint, край персов смягчается"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        g = _active_group(context)
        if g is None:
            self.report({"ERROR"}, "Композ не настроен — жми Set up file.")
            return {"CANCELLED"}
        ok, msg = _insert_bokeh_blur(g)
        self.report({"INFO"} if ok else {"WARNING"}, msg)
        return {"FINISHED"} if ok else {"CANCELLED"}


class KK_OT_depth_of_field(bpy.types.Operator):
    bl_idname = "kk.depth_of_field"
    bl_label = "Depth of field"
    bl_description = "Пустышка Focus в 1м перед камерой + Depth of Field на неё"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        cam = obj if (obj is not None and obj.type == "CAMERA") else context.scene.camera
        if cam is None or cam.type != "CAMERA":
            self.report({"ERROR"}, "Выбери камеру (или назначь активную камеру сцены).")
            return {"CANCELLED"}

        empty = bpy.data.objects.new("Focus", None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.2

        # линкуем в ту же коллекцию, где камера
        target_coll = cam.users_collection[0] if cam.users_collection else context.scene.collection
        target_coll.objects.link(empty)

        # парентим к камере, 1 м вперёд по локальной оси (камера смотрит в -Z)
        empty.parent = cam
        empty.matrix_parent_inverse = Matrix.Identity(4)
        empty.location = (0.0, 0.0, -1.0)

        cam.data.dof.use_dof = True
        cam.data.dof.focus_object = empty

        self.report({"INFO"}, "Focus создан и привязан к камере '%s'." % cam.name)
        return {"FINISHED"}


class KK_OT_add_lights(bpy.types.Operator):
    bl_idname = "kk.add_lights"
    bl_label = "Add lights to character"
    bl_description = "Световой риг из lights.blend на кость torso выбранного armature"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        arm = context.active_object
        if arm is None or arm.type != "ARMATURE":
            self.report({"ERROR"}, "Выбери armature (сделай его активным).")
            return {"CANCELLED"}

        pb = _find_torso(arm)
        if pb is None:
            self.report({"ERROR"}, "У armature нет кости '%s'." % TORSO_BONE)
            return {"CANCELLED"}

        sub_name = "%s_lights" % arm.name
        if _find_collection_in_scene(scene, sub_name) is not None:
            self.report({"WARNING"}, "'%s' уже есть в сцене." % sub_name)
            return {"CANCELLED"}

        empty, lights, new = _append_light_rig()
        if empty is None:
            self.report({"ERROR"}, "Не нашёл пустышку со светом в lights.blend.")
            return {"CANCELLED"}

        # имя пустышки = (armature)_lights
        empty.name = sub_name

        # коллекции: Lights -> (armature)_lights
        root = _ensure_lights_root(scene)
        sub = _ensure_subcollection(root, sub_name)
        for o in new:
            sub.objects.link(o)

        # пустышка на кость torso: чистый локальный + Child Of с единичным inverse
        # -> пустышка садится ровно в кость, оси сонаправлены с костью torso
        empty.matrix_basis = Matrix.Identity(4)
        con = empty.constraints.new("CHILD_OF")
        con.name = "Child Of torso"
        con.target = arm
        con.subtarget = pb.name
        con.inverse_matrix = Matrix.Identity(4)

        # light linking: группа = коллекция, где лежит armature
        arm_coll = _armature_collection(arm, scene)
        for lt in lights:
            try:
                lt.light_linking.receiver_collection = arm_coll
            except Exception:
                pass

        context.view_layer.update()
        self.report({"INFO"}, "Свет добавлен к '%s' (%d ламп)." % (arm.name, len(lights)))
        return {"FINISHED"}


class KK_OT_add_camera_overlay(bpy.types.Operator):
    bl_idname = "kk.add_camera_overlay"
    bl_label = "Add camera overlay"
    bl_description = "Композиция 1920x1920 + 2 safe-zone оверлея в камеру"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        obj = context.active_object
        cam = obj if (obj is not None and obj.type == "CAMERA") else scene.camera
        if cam is None or cam.type != "CAMERA":
            self.report({"ERROR"}, "Выбери камеру (или назначь активную камеру сцены).")
            return {"CANCELLED"}

        # композиция 1920x1920
        scene.render.resolution_x = OVERLAY_RES
        scene.render.resolution_y = OVERLAY_RES
        scene.render.resolution_percentage = 100

        cd = cam.data
        cd.show_background_images = True

        for fname, opacity in CAM_OVERLAYS:
            path = os.path.join(os.path.dirname(__file__), fname)
            if not os.path.exists(path):
                self.report({"WARNING"}, "Нет файла %s рядом с аддоном." % fname)
                continue
            img = bpy.data.images.load(path, check_existing=True)
            try:
                img.colorspace_settings.name = "sRGB"
            except Exception:
                pass
            if img.packed_file is None:
                try:
                    img.pack()
                except Exception:
                    pass

            # не дублируем, если такой оверлей уже висит
            bg = next((b for b in cd.background_images if b.image == img), None)
            if bg is None:
                bg = cd.background_images.new()
            bg.image = img
            bg.alpha = opacity
            bg.display_depth = "FRONT"
            bg.frame_method = "FIT"

        self.report({"INFO"}, "Оверлей добавлен, композиция %dx%d." % (OVERLAY_RES, OVERLAY_RES))
        return {"FINISHED"}


def _do_import(op, context, lib_name, prefix, version, coll_name, target_coll):
    """Общий импорт: link + override нужной коллекции в target_coll."""
    if not coll_name:
        op.report({"ERROR"}, "Ничего не выбрано.")
        return {"CANCELLED"}
    version = (version or "").strip()
    if not version:
        op.report({"ERROR"}, "Укажи версию.")
        return {"CANCELLED"}
    fname = "%s%s.blend" % (prefix, version)
    lib_obj = _get_asset_lib(lib_name)
    if lib_obj is None:
        op.report({"ERROR"}, "Нет asset library '%s' в настройках." % lib_name)
        return {"CANCELLED"}
    use_relative = getattr(lib_obj, "use_relative_path", True)
    # дубликат -> подтягиваем всё равно, но с припиской (2, 3, ...)
    final_name = coll_name
    if _find_collection_in_scene(context.scene, coll_name) is not None:
        i = 2
        while _find_collection_in_scene(context.scene, "%s %d" % (coll_name, i)) is not None:
            i += 1
        final_name = "%s %d" % (coll_name, i)
    path = bpy.path.abspath(lib_obj.path)
    blend = _find_blend(path, fname)
    if not blend:
        op.report({"ERROR"}, "Не нашёл %s в '%s'." % (fname, path))
        return {"CANCELLED"}
    if context.scene.kk_import_type == "APPEND":
        ov, err = _append_collection(context, blend, coll_name, target_coll, final_name)
        note = ""
    else:
        ov, err = _link_and_override(context, blend, coll_name, target_coll,
                                     final_name=final_name, use_relative=use_relative)
        note = "" if bpy.data.filepath or not use_relative else " (сохрани файл — путь пока абсолютный)"
    if err:
        op.report({"ERROR"}, err)
        return {"CANCELLED"}
    op.report({"INFO"}, "%s импортирован в %s.%s" % (final_name, target_coll, note))
    return {"FINISHED"}


class KK_OT_import_character(bpy.types.Operator):
    bl_idname = "kk.import_character"
    bl_label = "Import character"
    bl_options = {"REGISTER", "UNDO"}

    coll_name: bpy.props.StringProperty(name="Collection", default="")

    @classmethod
    def description(cls, context, props):
        return "Импорт '%s' в коллекцию Characters (link/append по типу)" % (props.coll_name or "персонажа")

    def execute(self, context):
        scene = context.scene
        return _do_import(self, context, ASSET_LIB_NAME, RIGS_PREFIX,
                          scene.kk_rig_version, self.coll_name, CHARACTERS_COLL)


class KK_OT_import_location(bpy.types.Operator):
    bl_idname = "kk.import_location"
    bl_label = "Import location"
    bl_options = {"REGISTER", "UNDO"}

    coll_name: bpy.props.StringProperty(name="Collection", default="")

    @classmethod
    def description(cls, context, props):
        return "Импорт '%s' в коллекцию Location (link/append по типу)" % (props.coll_name or "локации")

    def execute(self, context):
        scene = context.scene
        return _do_import(self, context, LOCATION_LIB_NAME, LOCATION_PREFIX,
                          scene.kk_location_version, self.coll_name, LOCATION_COLL)


class KK_OT_pack_libraries(bpy.types.Operator):
    bl_idname = "kk.pack_libraries"
    bl_label = "Pack libraries"
    bl_description = ("Сделать всех линкнутых персонажей/локации локальными "
                      "(файл без внешних библиотек)")
    bl_options = {"REGISTER"}

    def execute(self, context):
        n_libs = len(bpy.data.libraries)
        if n_libs == 0:
            self.report({"INFO"}, "Внешних библиотек нет — всё уже локально.")
            return {"FINISHED"}
        try:
            bpy.ops.object.make_local(type="ALL")
        except Exception as e:
            self.report({"ERROR"}, "make_local не сработал: %s" % e)
            return {"CANCELLED"}
        try:
            bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
        except Exception:
            pass
        removed = _remove_unused_libraries()
        left = len(bpy.data.libraries)
        if left == 0:
            self.report({"INFO"}, "Запаковано: %d библиотек, всё локально." % (n_libs))
        else:
            self.report({"WARNING"}, "Запаковано %d, осталось %d (проверь линки)." % (removed, left))
        return {"FINISHED"}


class KK_OT_make_editable(bpy.types.Operator):
    bl_idname = "kk.make_editable"
    bl_label = "Make overrides editable"
    bl_description = ("Снять 'system override' со всех залинкованных персонажей/локаций, "
                      "чтобы двигать объекты без кнопки 'make fully local'")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        count = 0
        for coll in list(bpy.data.collections):
            if coll.override_library is None:
                continue
            count += _make_hierarchy_editable(coll)
        # одиночные объекты-оверрайды вне иерархий
        for o in list(bpy.data.objects):
            ovl = o.override_library
            if ovl is not None:
                try:
                    if ovl.is_system_override:
                        ovl.is_system_override = False
                        count += 1
                except Exception:
                    pass
        if count:
            self.report({"INFO"}, "Сделано редактируемыми: %d датаблоков." % count)
        else:
            self.report({"INFO"}, "Всё уже редактируемо.")
        return {"FINISHED"}


class KK_OT_relocate_libraries(bpy.types.Operator):
    bl_idname = "kk.relocate_libraries"
    bl_label = "Relocate libraries"
    bl_description = ("Перелинковать отвалившиеся KOLLEGI_rigs* / Office_KK_* "
                      "по библиотекам characters / Location")
    bl_options = {"REGISTER"}

    def execute(self, context):
        relinked, unresolved = _relink_libraries()
        if relinked and unresolved:
            self.report({"WARNING"}, "Перелинковано: %d, не нашлось: %d (проверь пути characters/Location)." % (relinked, unresolved))
        elif relinked:
            self.report({"INFO"}, "Перелинковано библиотек: %d." % relinked)
        elif unresolved:
            self.report({"WARNING"}, "Не нашлось %d — проверь библиотеки characters/Location." % unresolved)
        else:
            self.report({"INFO"}, "Все линки на месте — чинить нечего.")
        return {"FINISHED"}


class KK_OT_playblast(bpy.types.Operator):
    bl_idname = "kk.playblast"
    bl_label = "Playblast"
    bl_description = ("Viewport render animation без оверлеев "
                      "(кости/пустышки/свет), но с Background images камеры")
    bl_options = {"REGISTER"}

    def execute(self, context):
        # ищем 3D вьюпорт
        area = context.area if (context.area and context.area.type == "VIEW_3D") else None
        if area is None:
            area = next((a for a in context.screen.areas if a.type == "VIEW_3D"), None)
        if area is None:
            self.report({"ERROR"}, "Нужен 3D вьюпорт.")
            return {"CANCELLED"}

        space = area.spaces.active
        overlay = space.overlay
        rv3d = space.region_3d
        region = next((r for r in area.regions if r.type == "WINDOW"), None)

        ov_bools = [p.identifier for p in overlay.bl_rna.properties
                    if p.type == "BOOLEAN" and p.identifier.startswith("show_")
                    and not p.is_readonly]
        saved = {k: getattr(overlay, k) for k in ov_bools}
        saved_persp = rv3d.view_perspective

        # на время плейбласта прячем safe_zone_1, safe_zone_dop оставляем
        hidden_bgs = []
        for cam in bpy.data.cameras:
            for bg in cam.background_images:
                img = getattr(bg, "image", None)
                name = os.path.splitext(img.name)[0].lower() if img else ""
                if name.startswith(os.path.splitext(CAM_OVERLAYS[0][0])[0].lower()):
                    hidden_bgs.append((bg, bg.show_background_image))
                    try:
                        bg.show_background_image = False
                    except Exception:
                        pass

        try:
            # мастер оверлеев ВКЛ (иначе пропадёт фон камеры), всё остальное ВЫКЛ
            for k in ov_bools:
                setattr(overlay, k, k == "show_overlays")
            overlay.show_overlays = True
            # смотрим в камеру, чтобы её Background images попали в кадр
            if context.scene.camera is not None:
                rv3d.view_perspective = "CAMERA"

            kw = {"window": context.window, "area": area}
            if region is not None:
                kw["region"] = region
            with context.temp_override(**kw):
                bpy.ops.render.opengl(animation=True)
        finally:
            for k, v in saved.items():
                try:
                    setattr(overlay, k, v)
                except Exception:
                    pass
            try:
                rv3d.view_perspective = saved_persp
            except Exception:
                pass
            for bg, val in hidden_bgs:
                try:
                    bg.show_background_image = val
                except Exception:
                    pass

        self.report({"INFO"}, "Playblast готов (вывод — по настройкам Output).")
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
#  UI
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
#  Bake camera on 1s: всё в 25 fps, персонажи/пропсы держат 10 fps-каденс,
#  камера ретаймится и становится плавной
# --------------------------------------------------------------------------- #
BAKE_FPS_TO = 25


def _iter_anim_ids():
    seen = set()
    for name in dir(bpy.data):
        if name.startswith("_"):
            continue
        try:
            coll = getattr(bpy.data, name)
        except Exception:
            continue
        if not isinstance(coll, bpy.types.bpy_prop_collection):
            continue
        for idb in coll:
            if not isinstance(idb, bpy.types.ID):
                break
            ad = getattr(idb, "animation_data", None)
            if ad is None:
                continue
            ptr = idb.as_pointer()
            if ptr in seen:
                continue
            seen.add(ptr)
            yield idb, ad


def _camera_related_ptrs():
    """Камеры, их data, пустышки-родители (камер-риг) и дочерние пустышки (фокус)."""
    rel = set()
    for o in bpy.data.objects:
        if o.type != "CAMERA":
            continue
        rel.add(o.as_pointer())
        if o.data is not None:
            rel.add(o.data.as_pointer())
        p = o.parent
        while p is not None and p.type == "EMPTY":
            rel.add(p.as_pointer())
            p = p.parent
        for ch in o.children_recursive:
            if ch.type == "EMPTY":
                rel.add(ch.as_pointer())
    return rel


def _channelbag(action, slot):
    if action is None or slot is None:
        return None
    try:
        from bpy_extras import anim_utils
        return anim_utils.action_get_channelbag_for_slot(action, slot)
    except Exception:
        return None


def _bake_fcurve_stepped(fc, S, E, k):
    """Запекает кривую: значение каждого исходного кадра -> CONSTANT-ключ
    на кадре, где этот кадр начинается в новом fps (каденс сохраняется)."""
    kps = fc.keyframe_points
    if len(kps):
        lo = min(math.floor(min(p.co.x for p in kps)), S)
        hi = max(math.ceil(max(p.co.x for p in kps)), E)
    else:
        lo, hi = S, E
    samples = [(f, fc.evaluate(f)) for f in range(lo, hi + 1)]
    for m in list(fc.modifiers):
        fc.modifiers.remove(m)
    keys, prev = [], None
    for f, v in samples:
        if prev is None or abs(v - prev) > 1e-7:
            keys.append((S + math.ceil((f - S) * k - 1e-9), v))
            prev = v
    kps.clear()
    kps.add(len(keys))
    for kp, (nf, v) in zip(kps, keys):
        kp.co = (nf, v)
        kp.interpolation = "CONSTANT"
    fc.extrapolation = "CONSTANT"
    fc.update()


def _retime_fcurve(fc, S, k):
    """Растягивает кривую во времени (тайминг тот же, движение плавнее)."""
    rm = lambda x: S + (x - S) * k
    for kp in fc.keyframe_points:
        kp.co.x = rm(kp.co.x)
        kp.handle_left.x = rm(kp.handle_left.x)
        kp.handle_right.x = rm(kp.handle_right.x)
        if hasattr(kp, "period"):
            try:
                kp.period *= k
            except Exception:
                pass
    for m in fc.modifiers:
        try:
            if m.use_restricted_range:
                a, b = rm(m.frame_start), rm(m.frame_end)
                m.frame_end = b
                m.frame_start = a
                m.frame_end = b
                m.blend_in *= k
                m.blend_out *= k
        except Exception:
            pass
        if m.type == "NOISE":
            m.scale *= k
            m.offset = rm(m.offset)
        elif m.type == "STEPPED":
            m.frame_step *= k
            m.frame_offset = rm(m.frame_offset)
    fc.update()


def _remap_strip_range(st, S, k):
    rm = lambda x: S + (x - S) * k
    a, b = rm(st.frame_start), rm(st.frame_end)
    for _ in range(2):
        try:
            st.frame_end = b
        except Exception:
            pass
        try:
            st.frame_start = a
        except Exception:
            pass
    for attr in ("blend_in", "blend_out"):
        try:
            setattr(st, attr, getattr(st, attr) * k)
        except Exception:
            pass


class KK_OT_bake_camera_on_ones(bpy.types.Operator):
    bl_idname = "kk.bake_camera_on_ones"
    bl_label = "Bake camera on 1s"
    bl_description = ("Файл -> 25 fps: вся анимация запекается с сохранением "
                      "10 fps-каденса, камера ретаймится и становится плавной")
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene = context.scene
        r = scene.render
        src = r.fps / (r.fps_base or 1.0)
        if src >= BAKE_FPS_TO - 1e-6:
            self.report({"WARNING"}, "Файл уже %.4g fps — запекать нечего." % src)
            return {"CANCELLED"}
        k = BAKE_FPS_TO / src
        S, E = scene.frame_start, scene.frame_end

        cam_ptrs = _camera_related_ptrs()

        # 1. собираем channelbags и классифицируем (камера / остальное)
        bags = {}          # ptr -> [channelbag, is_camera]
        strips = []        # NLA-стрипы для ретайма
        actions = {}       # ptr -> action (для frame_range / pose_markers)
        skipped = 0
        for idb, ad in _iter_anim_ids():
            is_cam = idb.as_pointer() in cam_ptrs
            pairs = [(ad.action, getattr(ad, "action_slot", None))]
            for tr in ad.nla_tracks:
                for st in tr.strips:
                    pairs.append((st.action, getattr(st, "action_slot", None)))
                    strips.append(st)
            for act, slot in pairs:
                if act is None:
                    continue
                if act.library is not None:
                    skipped += 1
                    continue
                cb = _channelbag(act, slot)
                if cb is None:
                    continue
                actions[act.as_pointer()] = act
                ptr = cb.as_pointer()
                if ptr in bags:
                    bags[ptr][1] = bags[ptr][1] or is_cam
                else:
                    bags[ptr] = [cb, is_cam]

        # 2. конвертация кривых
        n_cam = n_bake = 0
        for cb, is_cam in bags.values():
            for fc in cb.fcurves:
                if is_cam:
                    _retime_fcurve(fc, S, k)
                    n_cam += 1
                else:
                    _bake_fcurve_stepped(fc, S, E, k)
                    n_bake += 1

        cm = lambda x: S + math.ceil((x - S) * k - 1e-9)
        # диапазоны и маркеры экшнов
        for act in actions.values():
            try:
                if act.use_frame_range:
                    a, b = cm(act.frame_start), cm(act.frame_end + 1) - 1
                    act.frame_end = b
                    act.frame_start = a
                    act.frame_end = b
            except Exception:
                pass
            for pm in getattr(act, "pose_markers", []):
                pm.frame = cm(pm.frame)

        # 3. NLA-стрипы
        for st in strips:
            _remap_strip_range(st, S, k)

        # 4. сцена: fps, диапазон, текущий кадр, маркеры
        new_end = S + math.ceil((E - S + 1) * k - 1e-9) - 1
        cur = scene.frame_current
        r.fps = BAKE_FPS_TO
        r.fps_base = 1.0
        scene.frame_end = new_end
        scene.frame_current = cm(cur)
        if scene.use_preview_range:
            ps, pe = scene.frame_preview_start, scene.frame_preview_end
            scene.frame_preview_end = S + math.ceil((pe - S + 1) * k - 1e-9) - 1
            scene.frame_preview_start = cm(ps)
        for mk in scene.timeline_markers:
            mk.frame = cm(mk.frame)

        # 5. звук в секвенсоре
        other = 0
        se = scene.sequence_editor
        if se is not None:
            all_strips = getattr(se, "strips_all", None) or getattr(se, "sequences_all", [])
            for sq in all_strips:
                if sq.type == "SOUND":
                    try:
                        sq.frame_start = S + (sq.frame_start - S) * k
                    except Exception:
                        pass
                else:
                    other += 1

        msg = "25 fps: камера ретайм %d кривых, запечено %d кривых." % (n_cam, n_bake)
        if skipped:
            msg += " Пропущено линкнутых экшнов: %d." % skipped
        if other:
            msg += " Не-звуковые стрипы VSE не тронуты: %d." % other
        self.report({"WARNING"} if (skipped or other) else {"INFO"}, msg)
        return {"FINISHED"}


class KK_PT_panel(bpy.types.Panel):
    bl_label = "Collegtion"
    bl_idname = "KK_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Collegtion"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("kk.setup_file", icon="NODE_COMPOSITING")
        col.separator()
        col.operator("kk.motion_blur_bg", icon="MOD_TIME")
        col.operator("kk.motion_blur_fg", icon="MOD_TIME")
        col.operator("kk.bokeh_blur_bg", icon="IMAGE_DATA")
        col.separator()
        col.operator("kk.depth_of_field", icon="CAMERA_DATA")
        col.separator()
        col.operator("kk.add_lights", icon="LIGHT_AREA")
        col.operator("kk.add_camera_overlay", icon="IMAGE_BACKGROUND")
        col.operator("kk.playblast", icon="RENDER_ANIMATION")
        col.operator("kk.bake_camera_on_ones", icon="CAMERA_DATA")
        col.separator()
        col.operator("kk.relocate_libraries", icon="FILE_REFRESH")
        col.operator("kk.make_editable", icon="UNLOCKED")
        col.operator("kk.pack_libraries", icon="PACKAGE")


class KK_PT_import_characters(bpy.types.Panel):
    bl_label = "Import characters"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Collegtion"
    bl_parent_id = "KK_PT_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.prop(context.scene, "kk_import_type", expand=True)
        col.prop(context.scene, "kk_rig_version")
        grid = col.grid_flow(row_major=True, columns=2, align=True)
        for name in CHARACTERS:
            grid.operator("kk.import_character", text=name).coll_name = name


class KK_PT_import_locations(bpy.types.Panel):
    bl_label = "Import locations"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Collegtion"
    bl_parent_id = "KK_PT_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.prop(context.scene, "kk_import_type", expand=True)
        col.prop(context.scene, "kk_location_version")
        grid = col.grid_flow(row_major=True, columns=2, align=True)
        for name in LOCATIONS:
            grid.operator("kk.import_location", text=name).coll_name = name


classes = (
    KK_OT_setup_file,
    KK_OT_motion_blur_bg,
    KK_OT_motion_blur_fg,
    KK_OT_bokeh_blur_bg,
    KK_OT_depth_of_field,
    KK_OT_add_lights,
    KK_OT_add_camera_overlay,
    KK_OT_playblast,
    KK_OT_bake_camera_on_ones,
    KK_OT_import_character,
    KK_OT_import_location,
    KK_OT_relocate_libraries,
    KK_OT_make_editable,
    KK_OT_pack_libraries,
    KK_PT_panel,
    KK_PT_import_characters,
    KK_PT_import_locations,
)


@bpy.app.handlers.persistent
def _relink_on_load(*_args):
    """При открытии файла чинит битые пути до KOLLEGI_rigs* / Office_KK_*
    по локальным библиотекам characters / Location (другой комп / ОС)."""
    try:
        _relink_libraries()
    except Exception:
        pass


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.kk_import_type = bpy.props.EnumProperty(
        name="Import",
        description="Тип импорта персонажей/локаций",
        items=[
            ("LINK", "Link", "Link + library override (внешняя библиотека)"),
            ("APPEND", "Append", "Append (локально), WGT-объекты -> скрытая WGTS"),
        ],
        default="LINK",
    )
    bpy.types.Scene.kk_rig_version = bpy.props.StringProperty(
        name="Rig version",
        description="Версия рига -> файл %s<версия>.blend" % RIGS_PREFIX,
        default=DEFAULT_RIG_VERSION,
    )
    bpy.types.Scene.kk_location_version = bpy.props.StringProperty(
        name="Location version",
        description="Версия локации -> файл %s<версия>.blend" % LOCATION_PREFIX,
        default=DEFAULT_LOCATION_VERSION,
    )
    if _relink_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_relink_on_load)


def unregister():
    if _relink_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_relink_on_load)
    del bpy.types.Scene.kk_location_version
    del bpy.types.Scene.kk_rig_version
    del bpy.types.Scene.kk_import_type
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()

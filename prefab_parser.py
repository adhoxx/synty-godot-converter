"""Derive mesh-to-material mappings from Unity .prefab files.

Fallback for packs that ship without ``MaterialList*.txt``. That file is only
included in Synty's separate SourceFiles download, never in the
``.unitypackage`` - but the package does contain every prefab, and prefabs
carry the same information in a more authoritative form.

A Synty prefab is a flat YAML document stream. Each object is introduced by an
anchor line and linked by fileID rather than nesting::

    --- !u!1 &123292
    GameObject:
      m_Name: SM_Prop_Barrel_01
    --- !u!23 &2325676
    MeshRenderer:
      m_GameObject: {fileID: 123292}
      m_Materials:
      - {fileID: 2100000, guid: 42b64fdb315e3054ea757d8d1c4bcfa7, type: 2}

So the mesh name comes from joining a renderer's ``m_GameObject`` back to the
GameObject that owns it, and the materials come from resolving each
``m_Materials`` GUID through the package's GUID map.

This module emits the same ``PrefabMaterials`` structures as
:mod:`material_list`, so every downstream consumer - ``build_shader_cache``,
``get_mesh_to_materials_map``, ``generate_mesh_material_mapping_json`` - works
against it unchanged.

Parsing uses regex rather than a YAML parser for the same reason
:mod:`unity_parser` does: Unity's ``!u!`` tags are not standard YAML 1.1 and
break PyYAML and ruamel.
"""

from __future__ import annotations

import logging
import re

from material_list import MaterialSlot, MeshMaterials, PrefabMaterials

logger = logging.getLogger(__name__)

# Unity class IDs for the components we care about.
_CLASS_GAME_OBJECT = "1"
_CLASS_MESH_RENDERER = "23"
_CLASS_SKINNED_MESH_RENDERER = "137"

_RENDERER_CLASSES = frozenset({_CLASS_MESH_RENDERER, _CLASS_SKINNED_MESH_RENDERER})

# Splits the document stream: "--- !u!<classId> &<anchor>"
_DOCUMENT_PATTERN = re.compile(
    r"^---\s+!u!(\d+)\s+&(\d+)", re.MULTILINE
)

_NAME_PATTERN = re.compile(r"^\s*m_Name:\s*(.+?)\s*$", re.MULTILINE)
_GAME_OBJECT_REF_PATTERN = re.compile(
    r"^\s*m_GameObject:\s*\{fileID:\s*(\d+)", re.MULTILINE
)

# The m_Materials block, stopped at the first line that is not a list entry.
# Unity writes entries as "  - {fileID: ..., guid: ..., type: N}".
_MATERIALS_BLOCK_PATTERN = re.compile(
    r"^\s*m_Materials:\s*$\n((?:\s*-\s*\{[^}]*\}\s*$\n?)*)",
    re.MULTILINE,
)
_MATERIAL_GUID_PATTERN = re.compile(r"guid:\s*([a-f0-9]{32})")

# Trailing _LOD<n> used to order meshes so LOD0 leads.
_LOD_SUFFIX_PATTERN = re.compile(r"_LOD(\d+)\s*$", re.IGNORECASE)


def _split_documents(text: str) -> list[tuple[str, str, str]]:
    """Split a prefab's YAML stream into (class_id, anchor, body) triples."""
    matches = list(_DOCUMENT_PATTERN.finditer(text))
    documents: list[tuple[str, str, str]] = []

    for i, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        documents.append((match.group(1), match.group(2), text[body_start:body_end]))

    return documents


def _extract_material_guids(body: str) -> list[str]:
    """Return material GUIDs from a renderer body, in slot order.

    Entries with ``{fileID: 0}`` (no material assigned) carry no GUID and are
    dropped. Reading stops at the end of the ``m_Materials`` list so unrelated
    GUID-bearing keys further down the renderer are not picked up.
    """
    block_match = _MATERIALS_BLOCK_PATTERN.search(body)
    if not block_match:
        return []

    return _MATERIAL_GUID_PATTERN.findall(block_match.group(1))


def _lod_sort_key(index_and_mesh: tuple[int, MeshMaterials]) -> tuple[int, int]:
    """Order meshes so LOD0 comes first, preserving document order otherwise.

    ``build_shader_cache()`` treats ``meshes[0]`` as LOD0 and propagates its
    per-slot shader decision to every later mesh, so a prefab whose LOD2 mesh
    happens to be serialized first would otherwise poison the whole chain.
    Meshes with no LOD suffix sort as level 0 and keep their relative order.
    """
    index, mesh = index_and_mesh
    lod_match = _LOD_SUFFIX_PATTERN.search(mesh.mesh_name)
    lod_level = int(lod_match.group(1)) if lod_match else 0
    return (lod_level, index)


def parse_prefab_bytes(
    data: bytes,
    prefab_name: str,
    guid_to_material_name: dict[str, str],
) -> PrefabMaterials | None:
    """Extract mesh-to-material assignments from one prefab's raw bytes.

    Args:
        data: Raw ``.prefab`` file content.
        prefab_name: Name for the resulting prefab (normally the filename
            without extension).
        guid_to_material_name: Material GUID to material name, as resolved
            from the package's GUID map.

    Returns:
        A ``PrefabMaterials`` with one ``MeshMaterials`` per renderer that
        resolved to both a name and at least one material, ordered LOD0-first.
        ``None`` if the prefab yielded nothing usable - no renderers, no
        resolvable materials, or unparseable content.

    Example:
        >>> prefab = parse_prefab_bytes(data, "SM_Prop_Barrel_01", guids)
        >>> prefab.meshes[0].mesh_name
        'SM_Prop_Barrel_01'
    """
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception as e:  # pragma: no cover - decode with errors= rarely raises
        logger.debug("Could not decode prefab %s: %s", prefab_name, e)
        return None

    documents = _split_documents(text)
    if not documents:
        return None

    # Pass 1: anchor -> GameObject name.
    game_object_names: dict[str, str] = {}
    for class_id, anchor, body in documents:
        if class_id != _CLASS_GAME_OBJECT:
            continue
        name_match = _NAME_PATTERN.search(body)
        if name_match:
            game_object_names[anchor] = name_match.group(1)

    # Pass 2: renderers -> (mesh name, material slots).
    meshes: list[MeshMaterials] = []
    for class_id, _anchor, body in documents:
        if class_id not in _RENDERER_CLASSES:
            continue

        ref_match = _GAME_OBJECT_REF_PATTERN.search(body)
        if not ref_match:
            continue

        mesh_name = game_object_names.get(ref_match.group(1))
        if not mesh_name:
            logger.debug(
                "Prefab %s: renderer references unknown GameObject %s",
                prefab_name,
                ref_match.group(1),
            )
            continue

        slots: list[MaterialSlot] = []
        for guid in _extract_material_guids(body):
            material_name = guid_to_material_name.get(guid)
            if not material_name:
                logger.debug(
                    "Prefab %s: unresolved material GUID %s on %s",
                    prefab_name,
                    guid,
                    mesh_name,
                )
                continue
            # Prefabs carry no "(Uses custom shader)" marker. Setting this True
            # routes the material through determine_shader() - GUID lookup,
            # then name patterns - instead of build_shader_cache()'s
            # short-circuit straight to polygon.gdshader.
            slots.append(
                MaterialSlot(
                    material_name=material_name,
                    texture_name=None,
                    uses_custom_shader=True,
                )
            )

        if slots:
            meshes.append(MeshMaterials(mesh_name=mesh_name, slots=slots))

    if not meshes:
        return None

    ordered = [mesh for _, mesh in sorted(enumerate(meshes), key=_lod_sort_key)]
    return PrefabMaterials(prefab_name=prefab_name, meshes=ordered)


def build_prefabs_from_package(guid_map) -> list[PrefabMaterials]:
    """Build prefab material data from an extracted Unity package.

    Args:
        guid_map: ``unity_package.GuidMap`` carrying ``guid_to_pathname`` and
            ``guid_to_prefab_content``.

    Returns:
        One ``PrefabMaterials`` per prefab that yielded usable meshes. Safe to
        pass anywhere ``parse_material_list()`` output is accepted.

    Example:
        >>> prefabs = build_prefabs_from_package(guid_map)
        >>> generate_mesh_material_mapping_json(prefabs, out_path)
    """
    prefab_content = getattr(guid_map, "guid_to_prefab_content", None) or {}
    if not prefab_content:
        logger.debug("Package contains no prefabs")
        return []

    # Material GUID -> material name, from the package's asset paths.
    guid_to_material_name: dict[str, str] = {}
    for guid, pathname in guid_map.guid_to_pathname.items():
        if pathname.lower().endswith(".mat"):
            guid_to_material_name[guid] = pathname.rsplit("/", 1)[-1][: -len(".mat")]

    prefabs: list[PrefabMaterials] = []
    skipped = 0

    for guid, content in prefab_content.items():
        pathname = guid_map.guid_to_pathname.get(guid, "")
        prefab_name = pathname.rsplit("/", 1)[-1]
        if prefab_name.lower().endswith(".prefab"):
            prefab_name = prefab_name[: -len(".prefab")]
        if not prefab_name:
            prefab_name = guid

        prefab = parse_prefab_bytes(content, prefab_name, guid_to_material_name)
        if prefab is None:
            skipped += 1
            continue
        prefabs.append(prefab)

    logger.debug(
        "Derived %d prefab(s) from package (%d skipped, %d material GUIDs known)",
        len(prefabs),
        skipped,
        len(guid_to_material_name),
    )
    return prefabs

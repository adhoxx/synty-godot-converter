"""Tests for prefab_parser.py - deriving mesh/material mappings from Unity prefabs.

Fixtures mirror the real structure found in Synty packs (old-style Unity
prefabs using ``m_PrefabParentObject`` / ``!u!1001 Prefab``), trimmed to the
fields the parser actually reads.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prefab_parser import (  # noqa: E402
    _is_game_object_active,
    build_prefabs_from_package,
    parse_prefab_bytes,
)

# GUID -> material name, as resolved from GuidMap.guid_to_pathname
GUIDS = {
    "42b64fdb315e3054ea757d8d1c4bcfa7": "Dungeons_Texture_01_Mat",
    "1a64cf0a23f83924f9debcb452685f6f": "Ghost_Mat",
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": "Trim_Mat",
}


def _prefab(body: str) -> bytes:
    return ("%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n" + body).encode("utf-8")


SINGLE_MESH = _prefab(
    """--- !u!1 &123292
GameObject:
  m_Name: SM_Prop_Barrel_01
  m_IsActive: 1
--- !u!23 &2325676
MeshRenderer:
  m_GameObject: {fileID: 123292}
  m_Materials:
  - {fileID: 2100000, guid: 42b64fdb315e3054ea757d8d1c4bcfa7, type: 2}
  m_StaticBatchInfo:
    firstSubMesh: 0
--- !u!33 &3366390
MeshFilter:
  m_GameObject: {fileID: 123292}
  m_Mesh: {fileID: 4300000, guid: 83695bf29d2022e4d9a5dcba65dedb60, type: 3}
"""
)


class TestSingleMesh:
    def test_extracts_mesh_name_from_linked_gameobject(self):
        prefab = parse_prefab_bytes(SINGLE_MESH, "SM_Prop_Barrel_01", GUIDS)
        assert prefab is not None
        assert prefab.prefab_name == "SM_Prop_Barrel_01"
        assert [m.mesh_name for m in prefab.meshes] == ["SM_Prop_Barrel_01"]

    def test_resolves_material_guid_to_name(self):
        prefab = parse_prefab_bytes(SINGLE_MESH, "SM_Prop_Barrel_01", GUIDS)
        assert [s.material_name for s in prefab.meshes[0].slots] == [
            "Dungeons_Texture_01_Mat"
        ]

    def test_marks_slots_as_custom_shader(self):
        """build_shader_cache() short-circuits to polygon when this is False.

        Prefabs carry no such flag, so slots must opt into real shader
        detection (GUID lookup, then name patterns) rather than defaulting
        every material in every pack to polygon.gdshader.
        """
        prefab = parse_prefab_bytes(SINGLE_MESH, "SM_Prop_Barrel_01", GUIDS)
        assert all(s.uses_custom_shader for s in prefab.meshes[0].slots)


class TestMaterialSlots:
    def test_preserves_slot_order(self):
        """Slot index maps to Godot surface index - order is load-bearing."""
        data = _prefab(
            """--- !u!1 &1
GameObject:
  m_Name: SM_Env_Rock_01
--- !u!23 &2
MeshRenderer:
  m_GameObject: {fileID: 1}
  m_Materials:
  - {fileID: 2100000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
  - {fileID: 2100000, guid: 42b64fdb315e3054ea757d8d1c4bcfa7, type: 2}
  m_StaticBatchInfo:
    firstSubMesh: 0
"""
        )
        prefab = parse_prefab_bytes(data, "SM_Env_Rock_01", GUIDS)
        assert [s.material_name for s in prefab.meshes[0].slots] == [
            "Trim_Mat",
            "Dungeons_Texture_01_Mat",
        ]

    def test_skips_null_material_reference(self):
        data = _prefab(
            """--- !u!1 &1
GameObject:
  m_Name: SM_Prop_Empty
--- !u!23 &2
MeshRenderer:
  m_GameObject: {fileID: 1}
  m_Materials:
  - {fileID: 0}
  m_StaticBatchInfo:
    firstSubMesh: 0
"""
        )
        assert parse_prefab_bytes(data, "SM_Prop_Empty", GUIDS) is None

    def test_skips_unresolvable_guid_but_keeps_siblings(self):
        data = _prefab(
            """--- !u!1 &1
GameObject:
  m_Name: SM_Prop_Mixed
--- !u!23 &2
MeshRenderer:
  m_GameObject: {fileID: 1}
  m_Materials:
  - {fileID: 2100000, guid: ffffffffffffffffffffffffffffffff, type: 2}
  - {fileID: 2100000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
  m_StaticBatchInfo:
    firstSubMesh: 0
"""
        )
        prefab = parse_prefab_bytes(data, "SM_Prop_Mixed", GUIDS)
        assert [s.material_name for s in prefab.meshes[0].slots] == ["Trim_Mat"]

    def test_does_not_read_past_materials_list(self):
        """m_Materials must stop at the next key, not swallow later GUIDs."""
        data = _prefab(
            """--- !u!1 &1
GameObject:
  m_Name: SM_Prop_Barrel_01
--- !u!23 &2
MeshRenderer:
  m_GameObject: {fileID: 1}
  m_Materials:
  - {fileID: 2100000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
  m_StaticBatchInfo:
    firstSubMesh: 0
  m_LightmapParameters: {fileID: 2100000, guid: 42b64fdb315e3054ea757d8d1c4bcfa7, type: 2}
"""
        )
        prefab = parse_prefab_bytes(data, "SM_Prop_Barrel_01", GUIDS)
        assert [s.material_name for s in prefab.meshes[0].slots] == ["Trim_Mat"]


class TestRendererTypes:
    def test_reads_skinned_mesh_renderer(self):
        data = _prefab(
            """--- !u!1 &103632
GameObject:
  m_Name: Ghost_Body
--- !u!137 &13726810
SkinnedMeshRenderer:
  m_GameObject: {fileID: 103632}
  m_Materials:
  - {fileID: 2100000, guid: 1a64cf0a23f83924f9debcb452685f6f, type: 2}
  m_Mesh: {fileID: 4300072, guid: b69174d668ba02d44b14a084b217670a, type: 3}
"""
        )
        prefab = parse_prefab_bytes(data, "Character_Ghost_01", GUIDS)
        assert prefab.meshes[0].mesh_name == "Ghost_Body"
        assert prefab.meshes[0].slots[0].material_name == "Ghost_Mat"

    def test_ignores_mesh_collider(self):
        """MeshCollider references a mesh but is not a renderer."""
        data = _prefab(
            """--- !u!1 &1
GameObject:
  m_Name: SM_Prop_Barrel_01
--- !u!64 &64295123690121964
MeshCollider:
  m_GameObject: {fileID: 1}
  m_Material: {fileID: 0}
  m_Mesh: {fileID: 43966164966285454, guid: f88585dab8d7f5f40a1210f243674231, type: 2}
"""
        )
        assert parse_prefab_bytes(data, "SM_Prop_Barrel_01", GUIDS) is None


class TestLodOrdering:
    def test_lod0_sorts_first_regardless_of_document_order(self):
        """build_shader_cache() treats meshes[0] as LOD0 and propagates its
        shader to every other LOD, so LOD0 must lead."""
        data = _prefab(
            """--- !u!1 &3
GameObject:
  m_Name: SM_Env_Tree_01_LOD2
--- !u!23 &30
MeshRenderer:
  m_GameObject: {fileID: 3}
  m_Materials:
  - {fileID: 2100000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
  m_StaticBatchInfo:
    firstSubMesh: 0
--- !u!1 &1
GameObject:
  m_Name: SM_Env_Tree_01_LOD0
--- !u!23 &10
MeshRenderer:
  m_GameObject: {fileID: 1}
  m_Materials:
  - {fileID: 2100000, guid: 42b64fdb315e3054ea757d8d1c4bcfa7, type: 2}
  m_StaticBatchInfo:
    firstSubMesh: 0
"""
        )
        prefab = parse_prefab_bytes(data, "SM_Env_Tree_01", GUIDS)
        assert [m.mesh_name for m in prefab.meshes] == [
            "SM_Env_Tree_01_LOD0",
            "SM_Env_Tree_01_LOD2",
        ]

    def test_non_lod_meshes_keep_document_order(self):
        data = _prefab(
            """--- !u!1 &1
GameObject:
  m_Name: Zebra
--- !u!23 &10
MeshRenderer:
  m_GameObject: {fileID: 1}
  m_Materials:
  - {fileID: 2100000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
  m_StaticBatchInfo:
    firstSubMesh: 0
--- !u!1 &2
GameObject:
  m_Name: Apple
--- !u!23 &20
MeshRenderer:
  m_GameObject: {fileID: 2}
  m_Materials:
  - {fileID: 2100000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
  m_StaticBatchInfo:
    firstSubMesh: 0
"""
        )
        prefab = parse_prefab_bytes(data, "Multi", GUIDS)
        assert [m.mesh_name for m in prefab.meshes] == ["Zebra", "Apple"]


class TestDegenerateInput:
    def test_prefab_with_no_renderers_returns_none(self):
        data = _prefab(
            """--- !u!1 &1
GameObject:
  m_Name: EmptyThing
--- !u!4 &2
Transform:
  m_GameObject: {fileID: 1}
"""
        )
        assert parse_prefab_bytes(data, "EmptyThing", GUIDS) is None

    def test_renderer_pointing_at_missing_gameobject_is_skipped(self):
        data = _prefab(
            """--- !u!23 &2
MeshRenderer:
  m_GameObject: {fileID: 999999}
  m_Materials:
  - {fileID: 2100000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
  m_StaticBatchInfo:
    firstSubMesh: 0
"""
        )
        assert parse_prefab_bytes(data, "Orphan", GUIDS) is None

    def test_garbage_input_does_not_raise(self):
        assert parse_prefab_bytes(b"\x00\x01\x02not yaml", "Junk", GUIDS) is None

    def test_empty_input_does_not_raise(self):
        assert parse_prefab_bytes(b"", "Empty", GUIDS) is None


class _FakeGuidMap:
    """Minimal stand-in for unity_package.GuidMap."""

    def __init__(self, pathnames, prefab_content):
        self.guid_to_pathname = pathnames
        self.guid_to_prefab_content = prefab_content
        self.guid_to_content = {}
        self.texture_guid_to_name = {}
        self.texture_guid_to_path = {}


class TestBuildFromPackage:
    def test_builds_prefabs_and_resolves_material_names(self):
        guid_map = _FakeGuidMap(
            pathnames={
                "42b64fdb315e3054ea757d8d1c4bcfa7": "Assets/PolygonDungeon/Materials/Dungeons_Texture_01_Mat.mat",
                "p1": "Assets/PolygonDungeon/Prefabs/Props/SM_Prop_Barrel_01.prefab",
            },
            prefab_content={"p1": SINGLE_MESH},
        )
        prefabs = build_prefabs_from_package(guid_map)
        assert len(prefabs) == 1
        assert prefabs[0].prefab_name == "SM_Prop_Barrel_01"
        assert prefabs[0].meshes[0].slots[0].material_name == "Dungeons_Texture_01_Mat"

    def test_skips_prefabs_with_no_renderers(self):
        guid_map = _FakeGuidMap(
            pathnames={"p1": "Assets/Pack/Prefabs/Empty.prefab"},
            prefab_content={
                "p1": _prefab("--- !u!1 &1\nGameObject:\n  m_Name: Empty\n")
            },
        )
        assert build_prefabs_from_package(guid_map) == []

    def test_returns_empty_when_package_has_no_prefabs(self):
        assert build_prefabs_from_package(_FakeGuidMap({}, {})) == []


class TestIntegrationWithMaterialList:
    """The output must satisfy every downstream consumer unchanged."""

    def test_feeds_mesh_material_mapping_json(self, tmp_path):
        from material_list import generate_mesh_material_mapping_json

        guid_map = _FakeGuidMap(
            pathnames={
                "42b64fdb315e3054ea757d8d1c4bcfa7": "Assets/P/Materials/Dungeons_Texture_01_Mat.mat",
                "p1": "Assets/P/Prefabs/SM_Prop_Barrel_01.prefab",
            },
            prefab_content={"p1": SINGLE_MESH},
        )
        prefabs = build_prefabs_from_package(guid_map)
        out = tmp_path / "mesh_material_mapping.json"
        generate_mesh_material_mapping_json(prefabs, out)

        import json

        assert json.loads(out.read_text()) == {
            "SM_Prop_Barrel_01": ["Dungeons_Texture_01_Mat"]
        }

    def test_feeds_build_shader_cache(self):
        from converter import build_shader_cache

        guid_map = _FakeGuidMap(
            pathnames={
                "42b64fdb315e3054ea757d8d1c4bcfa7": "Assets/P/Materials/Dungeons_Texture_01_Mat.mat",
                "p1": "Assets/P/Prefabs/SM_Prop_Barrel_01.prefab",
            },
            prefab_content={"p1": SINGLE_MESH},
        )
        prefabs = build_prefabs_from_package(guid_map)
        shader_cache, _unmatched = build_shader_cache(prefabs)
        assert shader_cache["Dungeons_Texture_01_Mat"].endswith(".gdshader")


class TestIsGameObjectActive:
    def test_active_flag_one_is_active(self):
        assert _is_game_object_active("  m_Name: Foo\n  m_IsActive: 1\n") is True

    def test_active_flag_zero_is_inactive(self):
        assert _is_game_object_active("  m_Name: Foo\n  m_IsActive: 0\n") is False

    def test_absent_flag_defaults_to_active(self):
        """Older prefabs omit the field; treat them as visible rather than
        silently dropping every mesh in the file."""
        assert _is_game_object_active("  m_Name: Foo\n") is True

    def test_malformed_flag_defaults_to_active(self):
        assert _is_game_object_active("  m_IsActive: yes\n") is True

    def test_reads_own_field_not_a_later_one(self):
        body = "  m_Name: Foo\n  m_IsActive: 0\n  m_SomethingElse: 1\n"
        assert _is_game_object_active(body) is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

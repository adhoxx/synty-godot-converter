"""Tests for deriving character definitions from Unity prefabs."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prefab_parser import (  # noqa: E402
    CharacterDefinition,
    build_character_definitions,
)


def _prefab(body: str) -> bytes:
    return ("%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n" + body).encode("utf-8")


# One active skinned character plus one active bone-attached item, and one
# disabled sibling character - the shape every Synty character prefab has.
WARCHIEF = _prefab(
    """--- !u!1 &100
GameObject:
  m_Name: Character_Goblin_WarChief
  m_IsActive: 1
--- !u!137 &101
SkinnedMeshRenderer:
  m_GameObject: {fileID: 100}
  m_Materials:
  - {fileID: 2100000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
  m_Mesh: {fileID: 4300072, guid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb, type: 3}
--- !u!1 &200
GameObject:
  m_Name: SM_Item_Goblin_WarBanner
  m_IsActive: 1
--- !u!23 &201
MeshRenderer:
  m_GameObject: {fileID: 200}
  m_Materials:
  - {fileID: 2100000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
  m_StaticBatchInfo:
    firstSubMesh: 0
--- !u!1 &300
GameObject:
  m_Name: Character_Skeleton_Knight
  m_IsActive: 0
--- !u!137 &301
SkinnedMeshRenderer:
  m_GameObject: {fileID: 300}
  m_Materials:
  - {fileID: 2100000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
  m_Mesh: {fileID: 4300050, guid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb, type: 3}
"""
)

# A plain prop: MeshRenderer only, no skinning.
BARREL = _prefab(
    """--- !u!1 &1
GameObject:
  m_Name: SM_Prop_Barrel_01
  m_IsActive: 1
--- !u!23 &2
MeshRenderer:
  m_GameObject: {fileID: 1}
  m_Materials:
  - {fileID: 2100000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
  m_StaticBatchInfo:
    firstSubMesh: 0
"""
)

PATHNAMES = {
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": "Assets/P/Materials/Dungeon_Material_01.mat",
    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb": "Assets/P/Models/Characters.fbx",
    "pw": "Assets/P/Prefabs/Characters/Character_Goblin_WarChief.prefab",
    "pb": "Assets/P/Prefabs/Props/SM_Prop_Barrel_01.prefab",
    "pm": "Assets/P/Prefabs/Characters/Character_Mystery.prefab",
    "cccccccccccccccccccccccccccccccc": "Assets/P/Models/FixedScale/Characters.fbx",
    "pf": "Assets/P/Prefabs/Characters/Character_Goblin_WarChief_FixedScale.prefab",
}


class _FakeGuidMap:
    def __init__(self, pathnames, prefab_content):
        self.guid_to_pathname = pathnames
        self.guid_to_prefab_content = prefab_content
        self.guid_to_content = {}
        self.texture_guid_to_name = {}
        self.texture_guid_to_path = {}


def _guid_map(prefabs):
    return _FakeGuidMap(PATHNAMES, prefabs)


class TestBuildCharacterDefinitions:
    def test_finds_character_prefab(self):
        defs = build_character_definitions(_guid_map({"pw": WARCHIEF}))
        assert list(defs) == ["Character_Goblin_WarChief"]

    def test_includes_only_active_skinned_mesh(self):
        defs = build_character_definitions(_guid_map({"pw": WARCHIEF}))
        assert defs["Character_Goblin_WarChief"].skinned == [
            "Character_Goblin_WarChief"
        ]

    def test_includes_active_attachment(self):
        defs = build_character_definitions(_guid_map({"pw": WARCHIEF}))
        assert defs["Character_Goblin_WarChief"].attachments == [
            "SM_Item_Goblin_WarBanner"
        ]

    def test_resolves_source_fbx_from_mesh_guid(self):
        defs = build_character_definitions(_guid_map({"pw": WARCHIEF}))
        assert defs["Character_Goblin_WarChief"].source_fbx == "Characters"

    def test_ignores_prefab_with_no_skinned_renderer(self):
        assert build_character_definitions(_guid_map({"pb": BARREL})) == {}

    def test_ignores_prefab_whose_only_skinned_mesh_is_disabled(self):
        data = _prefab(
            """--- !u!1 &300
GameObject:
  m_Name: Character_Skeleton_Knight
  m_IsActive: 0
--- !u!137 &301
SkinnedMeshRenderer:
  m_GameObject: {fileID: 300}
  m_Mesh: {fileID: 4300050, guid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb, type: 3}
"""
        )
        assert build_character_definitions(_guid_map({"pw": data})) == {}

    def test_returns_empty_when_no_prefabs(self):
        assert build_character_definitions(_guid_map({})) == {}

    def test_unresolvable_mesh_guid_yields_empty_source_fbx(self):
        data = _prefab(
            """--- !u!1 &1
GameObject:
  m_Name: Character_Mystery
  m_IsActive: 1
--- !u!137 &2
SkinnedMeshRenderer:
  m_GameObject: {fileID: 1}
  m_Mesh: {fileID: 1, guid: ffffffffffffffffffffffffffffffff, type: 3}
"""
        )
        defs = build_character_definitions(_guid_map({"pm": data}))
        assert defs["Character_Mystery"].source_fbx == ""

    def test_source_fbx_is_relative_to_models_root(self):
        """Basenames collide: this pack ships Models/Characters.fbx AND
        Models/FixedScale/Characters.fbx. If source_fbx were just the
        basename, every definition would match both files and characters
        would be built twice, half of them from the wrong FBX."""
        data = WARCHIEF.replace(
            b"guid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            b"guid: cccccccccccccccccccccccccccccccc",
        )
        defs = build_character_definitions(_guid_map({"pf": data}))
        got = defs["Character_Goblin_WarChief_FixedScale"].source_fbx
        assert got == "FixedScale/Characters"

    def test_source_fbx_has_no_prefix_for_top_level_fbx(self):
        defs = build_character_definitions(_guid_map({"pw": WARCHIEF}))
        assert defs["Character_Goblin_WarChief"].source_fbx == "Characters"

    def test_definition_is_a_dataclass_with_expected_fields(self):
        d = CharacterDefinition(
            name="X", source_fbx="F", skinned=["a"], attachments=["b"]
        )
        assert (d.name, d.source_fbx, d.skinned, d.attachments) == (
            "X",
            "F",
            ["a"],
            ["b"],
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

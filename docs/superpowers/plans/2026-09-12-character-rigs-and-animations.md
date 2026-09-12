# Character Rigs and Animations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert Synty skinned characters into rigged Godot scenes with equipment, and convert ANIMATION_* packs into AnimationLibrary resources that can be bound to them.

**Architecture:** Python parses Unity prefabs and emits `character_definitions.json` beside the existing `mesh_material_mapping.json`; `godot_converter.gd` reads it and builds Godot objects. This mirrors the existing Python/GDScript split exactly - Unity-format parsing stays in Python, Godot-object construction stays in GDScript, JSON is the contract.

**Tech Stack:** Python 3.10+ (stdlib only), pytest, GDScript / Godot 4.7.2.

**Spec:** `docs/superpowers/specs/2026-09-12-character-rigs-and-animations-design.md`

## Global Constraints

- Python CLI must remain **stdlib-only**. No new pip dependencies.
- Godot is invoked headless. Use `Godot_v4.7.2-stable_win64_console.exe` - the
  non-console `.exe` is GUI-subsystem on Windows and writes nothing to the
  stdout pipe `run_godot_cli()` reads.
- Static prop conversion must be unaffected. An unscaled run's prop scenes must
  match the current pipeline.
- No failure may produce a silent empty scene. Every degraded path emits a
  static mesh plus a warning.
- `--mesh-scale` must never bake into skinned-mesh vertices.
- Rig families: `Polygon` (PascalCase bones: `Root`, `Hips`, `Spine_01`) and
  `Sidekick` (camelCase bones: `root`, `pelvis`, `thigh_l`). They share zero
  bone names.
- Bone-name coverage below **0.90** warns but still binds. Family mismatch
  refuses to bind.
- Animation-pack detection threshold: fraction of FBX under `/Animations/`
  greater than **0.5**.

**Test commands:**
- Python: `python -m pytest tests/ -q`
- Full conversion: see Task 5 and Task 10 verification blocks.

---

## Phase 1 - Rig preservation (Tasks 1-5)

Ends with working software: skinned meshes convert to rigged Godot characters
with equipment. Phase 2 can be deferred indefinitely.

### Task 1: Parse `m_IsActive` from prefab GameObjects

**Files:**
- Modify: `prefab_parser.py`
- Test: `tests/test_prefab_parser.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_is_game_object_active(body: str) -> bool` - module-private helper
  used by Task 2.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_prefab_parser.py`:

```python
from prefab_parser import _is_game_object_active  # noqa: E402


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_prefab_parser.py::TestIsGameObjectActive -q`
Expected: FAIL with `ImportError: cannot import name '_is_game_object_active'`

- [ ] **Step 3: Implement**

In `prefab_parser.py`, add next to the other compiled patterns:

```python
_IS_ACTIVE_PATTERN = re.compile(r"^\s*m_IsActive:\s*(\d+)\s*$", re.MULTILINE)
```

and add the helper below `_extract_material_guids()`:

```python
def _is_game_object_active(body: str) -> bool:
    """Whether a GameObject document is enabled.

    Synty ships one prefab per character containing every character in the
    pack, with all but one disabled, so this flag is what distinguishes a
    character's own meshes from its 26 disabled siblings.

    A missing or unparseable flag counts as active: dropping meshes because a
    field was absent would silently empty the prefab.
    """
    match = _IS_ACTIVE_PATTERN.search(body)
    if match is None:
        return True
    return match.group(1) != "0"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_prefab_parser.py -q`
Expected: PASS, 25 tests

- [ ] **Step 5: Commit**

```bash
git add prefab_parser.py tests/test_prefab_parser.py
git commit -m "feat: parse m_IsActive from prefab GameObjects"
```

---

### Task 2: Build character definitions from prefabs

**Files:**
- Modify: `prefab_parser.py`
- Test: `tests/test_character_definitions.py` (create)

**Interfaces:**
- Consumes: `_is_game_object_active()` from Task 1; `_split_documents()`,
  `_CLASS_GAME_OBJECT`, `_CLASS_MESH_RENDERER`, `_CLASS_SKINNED_MESH_RENDERER`,
  `_NAME_PATTERN`, `_GAME_OBJECT_REF_PATTERN` already in the module.
- Produces:
  - `@dataclass CharacterDefinition` with fields `name: str`,
    `source_fbx: str` (path relative to the pack's `Models/` root, no
    extension - NOT a basename), `skinned: list[str]`, `attachments: list[str]`
  - `_models_relative_name(pathname: str) -> str`
  - `build_character_definitions(guid_map) -> dict[str, CharacterDefinition]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_character_definitions.py`:

```python
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
        defs = build_character_definitions(_guid_map({"pw": data}))
        assert defs["Character_Mystery"].source_fbx == ""

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_character_definitions.py -q`
Expected: FAIL with `ImportError: cannot import name 'CharacterDefinition'`

- [ ] **Step 3: Implement**

In `prefab_parser.py`, add the mesh-reference pattern next to the others:

```python
_MESH_REF_PATTERN = re.compile(
    r"^\s*m_Mesh:\s*\{fileID:\s*-?\d+,\s*guid:\s*([a-f0-9]{32})", re.MULTILINE
)
```

Add `from dataclasses import dataclass, field` to the imports, then append:

```python
@dataclass
class CharacterDefinition:
    """One character assembled from a Synty character prefab.

    Attributes:
        name: Prefab name, e.g. "Character_Goblin_WarChief".
        source_fbx: Basename of the FBX holding the rig and meshes, e.g.
            "Characters". Empty when the mesh GUID could not be resolved.
        skinned: Names of active skinned meshes (the character body).
        attachments: Names of active non-skinned meshes (equipment). Whether
            each is bone-attached is left to Godot, which has already built a
            BoneAttachment3D for it during FBX import.
    """

    name: str
    source_fbx: str = ""
    skinned: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)


def build_character_definitions(guid_map) -> dict[str, CharacterDefinition]:
    """Derive character definitions from the package's prefabs.

    A prefab is a character when it holds at least one *active*
    SkinnedMeshRenderer. Synty ships one such prefab per character, each
    containing the whole shared hierarchy with every other character disabled,
    so the active set is exactly that character's body plus its equipment.

    Args:
        guid_map: unity_package.GuidMap with guid_to_pathname and
            guid_to_prefab_content.

    Returns:
        Prefab name to CharacterDefinition, for character prefabs only.
    """
    prefab_content = getattr(guid_map, "guid_to_prefab_content", None) or {}
    definitions: dict[str, CharacterDefinition] = {}

    for guid, content in prefab_content.items():
        pathname = guid_map.guid_to_pathname.get(guid, "")
        prefab_name = pathname.rsplit("/", 1)[-1]
        if prefab_name.lower().endswith(".prefab"):
            prefab_name = prefab_name[: -len(".prefab")]
        if not prefab_name:
            continue

        try:
            text = content.decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - decode with errors= rarely raises
            continue

        documents = _split_documents(text)
        if not documents:
            continue

        active_names: dict[str, str] = {}
        for class_id, anchor, body in documents:
            if class_id != _CLASS_GAME_OBJECT:
                continue
            name_match = _NAME_PATTERN.search(body)
            if name_match and _is_game_object_active(body):
                active_names[anchor] = name_match.group(1)

        skinned: list[str] = []
        attachments: list[str] = []
        mesh_guid = ""

        for class_id, _anchor, body in documents:
            if class_id not in _RENDERER_CLASSES:
                continue
            ref = _GAME_OBJECT_REF_PATTERN.search(body)
            if not ref:
                continue
            name = active_names.get(ref.group(1))
            if not name:
                continue
            if class_id == _CLASS_SKINNED_MESH_RENDERER:
                skinned.append(name)
                if not mesh_guid:
                    mesh_match = _MESH_REF_PATTERN.search(body)
                    if mesh_match:
                        mesh_guid = mesh_match.group(1)
            else:
                attachments.append(name)

        if not skinned:
            continue

        source_path = guid_map.guid_to_pathname.get(mesh_guid, "")
        source_fbx = source_path.rsplit("/", 1)[-1]
        if source_fbx.lower().endswith(".fbx"):
            source_fbx = source_fbx[: -len(".fbx")]

        definitions[prefab_name] = CharacterDefinition(
            name=prefab_name,
            source_fbx=source_fbx,
            skinned=skinned,
            attachments=attachments,
        )

    logger.debug("Derived %d character definition(s)", len(definitions))
    return definitions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ -q`
Expected: PASS, 34 tests

- [ ] **Step 5: Verify against the real pack**

```bash
python -c "
from unity_package import extract_unitypackage
from prefab_parser import build_character_definitions
from pathlib import Path
gm = extract_unitypackage(Path(r'C:/Users/Justin/Downloads/POLYGON_Dungeon_Unity_2021_3_v1_9_5.unitypackage'))
d = build_character_definitions(gm)
print('characters:', len(d))
w = d.get('Character_Goblin_WarChief')
print(w)
" 2>&1 | grep -v "^DEBUG\|^INFO\|^WARNING"
```

Expected: **33** characters. POLYGON_Dungeon ships 16 characters plus
`_FixedScale` prefab variants of them, which resolve to a different
`source_fbx` (`Models/FixedScale/Characters.fbx`) and are therefore separate
definitions. `Character_Goblin_WarChief` has `source_fbx='Characters'`,
`skinned=['Character_Goblin_WarChief']`,
`attachments=['SM_Item_Goblin_WarBanner']`. `source_fbx` values split
16 `Characters` / 16 `FixedScale/Characters` / 1 `SM_LightRayCube`, the last
being an FX prefab that genuinely uses a SkinnedMeshRenderer.

- [ ] **Step 6: Commit**

```bash
git add prefab_parser.py tests/test_character_definitions.py
git commit -m "feat: derive character definitions from Unity prefabs"
```

---

### Task 3: Write `character_definitions.json` during conversion

**Files:**
- Modify: `converter.py` (imports; `run_conversion()` Step 10 region, near the
  `generate_mesh_material_mapping_json()` call around line 2408)
- Modify: `prefab_parser.py`
- Test: `tests/test_character_definitions.py`

**Interfaces:**
- Consumes: `build_character_definitions()` from Task 2.
- Produces: `write_character_definitions_json(defs: dict[str, CharacterDefinition], output_path: Path) -> None`, and the file
  `<pack>/character_definitions.json` consumed by Task 4.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_character_definitions.py`:

```python
class TestWriteCharacterDefinitionsJson:
    def test_writes_expected_json_shape(self, tmp_path):
        from prefab_parser import write_character_definitions_json

        defs = build_character_definitions(_guid_map({"pw": WARCHIEF}))
        out = tmp_path / "character_definitions.json"
        write_character_definitions_json(defs, out)

        import json

        assert json.loads(out.read_text(encoding="utf-8")) == {
            "Character_Goblin_WarChief": {
                "source_fbx": "Characters",
                "skinned": ["Character_Goblin_WarChief"],
                "attachments": ["SM_Item_Goblin_WarBanner"],
            }
        }

    def test_creates_parent_directory(self, tmp_path):
        from prefab_parser import write_character_definitions_json

        out = tmp_path / "nested" / "character_definitions.json"
        write_character_definitions_json({}, out)
        assert out.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_character_definitions.py::TestWriteCharacterDefinitionsJson -q`
Expected: FAIL with `ImportError: cannot import name 'write_character_definitions_json'`

- [ ] **Step 3: Implement the writer**

Add `import json` to `prefab_parser.py` imports, then append:

```python
def write_character_definitions_json(
    definitions: dict[str, CharacterDefinition],
    output_path: Path,
    *,
    indent: int = 2,
) -> None:
    """Write character_definitions.json for godot_converter.gd.

    Args:
        definitions: Output of build_character_definitions().
        output_path: Normally <pack_output_dir>/character_definitions.json.
        indent: JSON indentation level.
    """
    payload = {
        name: {
            "source_fbx": d.source_fbx,
            "skinned": d.skinned,
            "attachments": d.attachments,
        }
        for name, d in definitions.items()
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=indent, ensure_ascii=False), encoding="utf-8"
    )
    logger.debug("Wrote %d character definition(s) to %s", len(payload), output_path)
```

Add `from pathlib import Path` to `prefab_parser.py` imports if not present.

- [ ] **Step 4: Wire it into the pipeline**

In `converter.py`, extend the existing import:

```python
from prefab_parser import (
    build_prefabs_from_package,
    build_character_definitions,
    write_character_definitions_json,
)
```

In `run_conversion()`, immediately after the
`generate_mesh_material_mapping_json(prefabs, mapping_output)` call, add at the
same indentation:

```python
                    # Character definitions drive rigged-character output in
                    # godot_converter.gd. Absent file simply means no characters.
                    char_defs = build_character_definitions(guid_map)
                    if char_defs:
                        write_character_definitions_json(
                            char_defs, pack_output_dir / "character_definitions.json"
                        )
                        logger.info(
                            "Wrote %d character definition(s)", len(char_defs)
                        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/ -q`
Expected: PASS, 36 tests

- [ ] **Step 6: Verify end to end**

```bash
rm -rf "D:/GameAssets/Godot/Synty/tests/POLYGON_Dungeon"
python converter.py \
  --unity-package "C:/Users/Justin/Downloads/POLYGON_Dungeon_Unity_2021_3_v1_9_5.unitypackage" \
  --source-files "D:/Unity Projects/AEGIS/Assets/Synty/PolygonDungeon" \
  --output "D:/GameAssets/Godot/Synty/tests" \
  --godot "C:/Users/Justin/Documents/git_repos/godot-bin/Godot_v4.7.2-stable_win64_console.exe" \
  --skip-godot-cli
cat "D:/GameAssets/Godot/Synty/tests/POLYGON_Dungeon/character_definitions.json" | head -20
```

Expected: valid JSON keyed by character name.

- [ ] **Step 7: Commit**

```bash
git add converter.py prefab_parser.py tests/test_character_definitions.py
git commit -m "feat: emit character_definitions.json during conversion"
```

---

### Task 4: Build rigged character scenes in GDScript

**Files:**
- Modify: `godot_converter.gd` (state vars near line 44; `process_pack_folder()`
  around line 267; `process_fbx_file()` around line 405)

**Interfaces:**
- Consumes: `<pack>/character_definitions.json` from Task 3.
- Produces:
  - `character_definitions: Dictionary` - definition name to Dictionary
  - `load_character_definitions(pack_folder: String) -> void`
  - `_find_skeleton(node: Node) -> Skeleton3D`
  - `_find_node_named(node: Node, wanted: String) -> Node`
  - `build_character_scene(scene_instance: Node, def_name: String, def: Dictionary, relative_dir: String) -> bool`
  - `characters_saved: int` counter surfaced in `print_summary()`
  - `character_placed_meshes: Array` - meshes actually placed by the most recent
    `build_character_scene()` call

- [ ] **Step 1: Add state and loader**

Near the other `var` declarations at the top of `godot_converter.gd`:

```gdscript
## Character definitions for this pack, from character_definitions.json.
## Maps definition name -> {source_fbx, skinned, attachments}.
var character_definitions: Dictionary = {}

## Mesh names consumed by rigged character scenes, so the static path skips them.
var character_consumed_meshes: Dictionary = {}

var characters_saved: int = 0

## Mesh names placed into the character scene currently being built, so the
## static path skips exactly those and no others.
var character_placed_meshes: Array = []
```

Add the loader below `load_material_mapping()`:

```gdscript
## Loads character_definitions.json if present. Absence is normal - packs with
## no skinned meshes have no characters - so this never fails the pack.
func load_character_definitions(pack_folder: String) -> void:
	character_definitions = {}
	character_consumed_meshes = {}

	var path := pack_folder + "/character_definitions.json"
	if not FileAccess.file_exists(path):
		print("  No character_definitions.json (no rigged characters for this pack)")
		return

	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_warning("Failed to open %s" % path)
		return

	var json := JSON.new()
	var err := json.parse(file.get_as_text())
	file.close()
	if err != OK:
		printerr("Failed to parse character_definitions.json: %s" % json.get_error_message())
		return

	var data = json.get_data()
	if not data is Dictionary:
		printerr("Invalid character_definitions.json: expected Dictionary")
		return

	character_definitions = data
	for def_name in character_definitions:
		var def: Dictionary = character_definitions[def_name]
		for m in def.get("skinned", []):
			character_consumed_meshes[m] = true
		for m in def.get("attachments", []):
			character_consumed_meshes[m] = true

	print("  Loaded %d character definition(s)" % character_definitions.size())
```

Call it in `process_pack_folder()`, directly after the
`load_material_mapping(pack_folder)` success check:

```gdscript
	load_character_definitions(pack_folder)
```

- [ ] **Step 2: Add the node-search helpers**

Add below `find_mesh_instances()`:

```gdscript
func _find_skeleton(node: Node) -> Skeleton3D:
	if node is Skeleton3D:
		return node
	for child in node.get_children():
		var found := _find_skeleton(child)
		if found != null:
			return found
	return null


func _find_node_named(node: Node, wanted: String) -> Node:
	if String(node.name) == wanted:
		return node
	for child in node.get_children():
		var found := _find_node_named(child, wanted)
		if found != null:
			return found
	return null
```

- [ ] **Step 3: Implement rigged scene construction**

Add below `extract_and_save_mesh()`:

```gdscript
## Builds one rigged character scene: a cloned Skeleton3D, the character's
## skinned mesh, its bone-attached equipment, and an empty AnimationPlayer.
##
## The skeleton is produced with duplicate() then emptied of children, rather
## than rebuilt bone by bone, so bone rests and poses are reproduced exactly -
## a subtly wrong bind pose deforms the character while still passing a
## "has a skeleton" check.
##
## @returns bool True if a scene was saved.
func build_character_scene(scene_instance: Node, def_name: String, def: Dictionary, relative_dir: String) -> bool:
	var src_skel := _find_skeleton(scene_instance)
	if src_skel == null:
		printerr("    ERROR: %s has no Skeleton3D; falling back to static meshes" % def_name)
		errors += 1
		return false

	character_placed_meshes = []

	var root := Node3D.new()
	root.name = def_name

	var skel := src_skel.duplicate() as Skeleton3D
	if skel == null:
		printerr("    ERROR: could not duplicate skeleton for %s" % def_name)
		root.free()
		errors += 1
		return false
	for child in skel.get_children():
		skel.remove_child(child)
		child.queue_free()
	skel.name = "Skeleton3D"
	root.add_child(skel)

	var attached := 0

	for mesh_name in def.get("skinned", []):
		var src := _find_node_named(scene_instance, String(mesh_name)) as MeshInstance3D
		if src == null or src.mesh == null:
			printerr("    WARNING: skinned mesh %s not found in FBX" % mesh_name)
			warnings += 1
			continue
		if src.skin == null:
			# Spec: a skinned mesh with no Skin cannot be posed. Leave it to the
			# static path rather than emitting a character that cannot animate.
			printerr("    WARNING: %s has no Skin; leaving it as a static mesh" % mesh_name)
			warnings += 1
			continue
		var mi := src.duplicate() as MeshInstance3D
		skel.add_child(mi)
		mi.skin = src.skin
		mi.skeleton = NodePath("..")
		mi.transform = src.transform
		_apply_materials_to(mi, String(mesh_name))
		character_placed_meshes.append(String(mesh_name))
		attached += 1

	for item_name in def.get("attachments", []):
		var src_item := _find_node_named(scene_instance, String(item_name))
		if src_item == null:
			printerr("    WARNING: attachment %s not found in FBX" % item_name)
			warnings += 1
			continue
		# Godot's importer wraps bone-attached objects in a BoneAttachment3D.
		# Duplicating that parent preserves bone_name; if the item is not
		# bone-attached, duplicate the node itself.
		var to_copy := src_item
		if src_item.get_parent() is BoneAttachment3D:
			to_copy = src_item.get_parent()
		var copy := to_copy.duplicate()
		skel.add_child(copy)
		for mi2 in find_mesh_instances(copy):
			_apply_materials_to(mi2, String(mi2.name))
		character_placed_meshes.append(String(item_name))
		attached += 1

	if attached == 0:
		printerr("    ERROR: %s produced no meshes; falling back to static" % def_name)
		root.free()
		errors += 1
		return false

	var player := AnimationPlayer.new()
	player.name = "AnimationPlayer"
	root.add_child(player)

	# Scale belongs on the root: baking it into skinned vertices while leaving
	# bone rests untouched breaks the bind pose.
	if config_mesh_scale != 1.0:
		root.scale = Vector3.ONE * config_mesh_scale

	_set_owner_recursive(root, root)

	var meshes_dir := current_pack_folder + "/meshes/" + _get_mesh_subfolder()
	var output_path: String
	if relative_dir.is_empty():
		output_path = "%s/%s.%s" % [meshes_dir, def_name, config_mesh_format]
	else:
		output_path = "%s/%s/%s.%s" % [meshes_dir, relative_dir, def_name, config_mesh_format]
	_ensure_directory_exists(output_path.get_base_dir())

	var scene := PackedScene.new()
	if scene.pack(root) != OK:
		printerr("    ERROR: failed to pack character scene: %s" % def_name)
		root.free()
		errors += 1
		return false

	var save_result := ResourceSaver.save(scene, output_path)
	root.free()

	if save_result != OK:
		printerr("    ERROR: failed to save character scene: %s" % def_name)
		errors += 1
		return false

	print("      Saved character: %s (%d bones)" % [def_name, skel.get_bone_count()])
	characters_saved += 1
	meshes_saved += 1
	return true


## Applies the pack's material overrides to one MeshInstance3D, reusing the
## existing name-based lookup and its fallback chain.
func _apply_materials_to(mesh_instance: MeshInstance3D, mesh_name: String) -> void:
	if mesh_instance.mesh == null:
		return
	var material_names := get_material_names_for_mesh(mesh_name)
	if material_names.is_empty():
		return
	var materials_dir := current_pack_folder + "/materials"
	for i in range(mesh_instance.mesh.get_surface_count()):
		if i >= material_names.size():
			break
		var mat_path := find_material_path(material_names[i], materials_dir)
		if mat_path.is_empty():
			continue
		var mat := load(mat_path)
		if mat != null:
			mesh_instance.set_surface_override_material(i, mat)
```

- [ ] **Step 4: Hook into `process_fbx_file()`**

In `process_fbx_file()`, replace the block from `print("    Found %d mesh(es)"...)`
through the `else:` static-extraction branch with:

```gdscript
	print("    Found %d mesh(es)" % mesh_instances.size())

	# Rigged characters first; they consume their meshes so the static path
	# below does not also emit a bind-pose duplicate.
	var consumed := {}
	for def_name in character_definitions:
		var def: Dictionary = character_definitions[def_name]
		# Compare against the path relative to models/, not the basename:
		# Characters.fbx and FixedScale/Characters.fbx share a basename.
		if String(def.get("source_fbx", "")) != relative_path.get_basename():
			continue
		if not config_filter_pattern.is_empty() and not String(def_name).containsn(config_filter_pattern):
			continue
		if build_character_scene(scene_instance, String(def_name), def, relative_dir):
			# Only meshes actually placed in the character scene are consumed.
			# A skinned mesh skipped for a null Skin must still reach the static
			# path, or it would disappear from the output entirely.
			for m in character_placed_meshes:
				consumed[String(m)] = true

	if config_keep_meshes_together:
		save_fbx_as_single_scene(scene_instance, mesh_instances, relative_dir, fbx_name)
	else:
		for mesh_instance in mesh_instances:
			if consumed.has(String(mesh_instance.name)):
				continue
			extract_and_save_mesh(mesh_instance, relative_dir, fbx_name)
```

- [ ] **Step 5: Report characters in the summary**

In `print_summary()`, add after the `Meshes saved` line:

```gdscript
	print("  Characters:     %d" % characters_saved)
```

- [ ] **Step 6: Verify**

```bash
rm -rf "D:/GameAssets/Godot/Synty/tests/POLYGON_Dungeon"
python converter.py \
  --unity-package "C:/Users/Justin/Downloads/POLYGON_Dungeon_Unity_2021_3_v1_9_5.unitypackage" \
  --source-files "D:/Unity Projects/AEGIS/Assets/Synty/PolygonDungeon" \
  --output "D:/GameAssets/Godot/Synty/tests" \
  --godot "C:/Users/Justin/Documents/git_repos/godot-bin/Godot_v4.7.2-stable_win64_console.exe" \
  --godot-timeout 1800 2>&1 | grep -iE "Characters:|Meshes:|Errors"

cd "D:/GameAssets/Godot/Synty/tests/POLYGON_Dungeon/meshes/tscn_separate"
echo "scenes with Skeleton3D: $(grep -l 'type="Skeleton3D"' *.tscn | wc -l)"
echo "scenes with skin:       $(grep -l '^skin = ' *.tscn | wc -l)"
echo "scenes with AnimPlayer: $(grep -l 'AnimationPlayer' *.tscn | wc -l)"
echo "empty meshes:           $(grep -L '_surfaces' *.tscn | wc -l)"
grep -E '^\[node' Character_Goblin_WarChief.tscn
```

Expected: `Characters: 33`; scenes with `Skeleton3D`, `skin`, and
`AnimationPlayer` all match that count; **empty meshes 0**; the WarChief scene
shows `Node3D` root, `Skeleton3D`, a `MeshInstance3D`, a `BoneAttachment3D`, and
an `AnimationPlayer`.

- [ ] **Step 7: Verify visually**

Skeleton cloning is the highest-risk step in this plan and a wrong bind pose
still passes the assertions above. Render one character and look at it:

```bash
"C:/Users/Justin/Documents/git_repos/godot-bin/Godot_v4.7.2-stable_win64.exe"   --path "D:/GameAssets/Godot/Synty/tests"
```

Open `Character_Goblin_WarChief.tscn` in the editor and look at it in the 3D
view. The character must stand in a normal bind pose. Folded, stretched, or
inside-out geometry means the cloned skeleton's bone rests do not match the
skin's bind poses - stop and fix that before continuing, because every later
task builds on this scene shape.

- [ ] **Step 8: Commit**

```bash
git add godot_converter.gd
git commit -m "feat: build rigged character scenes with skeleton, skin and equipment"
```

---

### Task 5: Keep `--mesh-scale` away from skinned vertices

**Files:**
- Modify: `godot_converter.gd` (`extract_and_save_mesh()` around line 644)

**Interfaces:**
- Consumes: `scale_mesh()`, unchanged.
- Produces: no new symbols.

- [ ] **Step 1: Implement**

In `extract_and_save_mesh()`, replace:

```gdscript
	# Apply mesh scale if configured
	if config_mesh_scale != 1.0:
		original_mesh = scale_mesh(original_mesh, config_mesh_scale)
```

with:

```gdscript
	# Apply mesh scale if configured.
	# Skinned meshes must never have scale baked into their vertices: bone rest
	# transforms would keep the original scale and the bind pose would break.
	# Scale the node instead. (Rigged characters handle this on the scene root
	# in build_character_scene(); this covers skinned meshes with no character
	# definition.)
	var scale_on_node := false
	if config_mesh_scale != 1.0:
		if mesh_instance.skin != null:
			scale_on_node = true
		else:
			original_mesh = scale_mesh(original_mesh, config_mesh_scale)
```

Then, directly after `scene_mesh_instance.name = mesh_name`, add:

```gdscript
	if scale_on_node:
		scene_mesh_instance.scale = Vector3.ONE * config_mesh_scale
```

- [ ] **Step 2: Verify**

```bash
rm -rf "D:/GameAssets/Godot/Synty/tests/POLYGON_Dungeon"
python converter.py \
  --unity-package "C:/Users/Justin/Downloads/POLYGON_Dungeon_Unity_2021_3_v1_9_5.unitypackage" \
  --source-files "D:/Unity Projects/AEGIS/Assets/Synty/PolygonDungeon" \
  --output "D:/GameAssets/Godot/Synty/tests" \
  --godot "C:/Users/Justin/Documents/git_repos/godot-bin/Godot_v4.7.2-stable_win64_console.exe" \
  --mesh-scale 100 --godot-timeout 1800 2>&1 | grep -iE "Characters:|Meshes:|Errors"

cd "D:/GameAssets/Godot/Synty/tests/POLYGON_Dungeon/meshes/tscn_separate"
echo "empty: $(grep -L '_surfaces' *.tscn | wc -l)"
grep -A2 '^\[node name="Character_Goblin_WarChief"' Character_Goblin_WarChief.tscn
```

Expected: empty 0; the character root carries `transform` with a 100x basis
rather than the mesh AABB having grown.

- [ ] **Step 3: Commit**

```bash
git add godot_converter.gd
git commit -m "fix: scale skinned meshes on the node, never in vertices"
```

---

## Phase 2 - Animation packs (Tasks 6-10)

### Task 6: Detect animation packs

**Files:**
- Modify: `converter.py`
- Test: `tests/test_pack_type.py` (create)

**Interfaces:**
- Produces: `detect_pack_type(guid_map) -> str` returning `"assets"` or
  `"animations"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pack_type.py`:

```python
"""Tests for animation-pack detection."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from converter import detect_pack_type  # noqa: E402


class _FakeGuidMap:
    def __init__(self, pathnames):
        self.guid_to_pathname = pathnames


def _map(paths):
    return _FakeGuidMap({str(i): p for i, p in enumerate(paths)})


class TestDetectPackType:
    def test_animation_pack(self):
        """ANIMATION_Sword_Combat scores 242/244."""
        paths = [f"Assets/Synty/A/Animations/Polygon/Attack/c{i}.fbx" for i in range(242)]
        paths += ["Assets/Synty/A/Meshes/Rig.fbx", "Assets/Synty/A/Meshes/Rig2.fbx"]
        assert detect_pack_type(_map(paths)) == "animations"

    def test_asset_pack(self):
        """POLYGON_Dungeon scores 0/801."""
        paths = [f"Assets/P/Models/SM_Prop_{i}.fbx" for i in range(801)]
        assert detect_pack_type(_map(paths)) == "assets"

    def test_threshold_is_exclusive_above_half(self):
        paths = ["Assets/X/Animations/a.fbx", "Assets/X/Models/b.fbx"]
        assert detect_pack_type(_map(paths)) == "assets"

    def test_just_over_half_is_animations(self):
        paths = [
            "Assets/X/Animations/a.fbx",
            "Assets/X/Animations/b.fbx",
            "Assets/X/Models/c.fbx",
        ]
        assert detect_pack_type(_map(paths)) == "animations"

    def test_no_fbx_is_assets(self):
        assert detect_pack_type(_map(["Assets/X/Materials/m.mat"])) == "assets"

    def test_match_is_case_insensitive(self):
        paths = ["Assets/X/ANIMATIONS/a.fbx", "Assets/X/ANIMATIONS/b.fbx"]
        assert detect_pack_type(_map(paths)) == "animations"

    def test_ignores_non_fbx_under_animations(self):
        paths = ["Assets/X/Animations/a.controller", "Assets/X/Models/b.fbx"]
        assert detect_pack_type(_map(paths)) == "assets"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pack_type.py -q`
Expected: FAIL with `ImportError: cannot import name 'detect_pack_type'`

- [ ] **Step 3: Implement**

In `converter.py`, add above `run_conversion()`:

```python
# Fraction of FBX under an Animations/ directory above which a package is
# treated as an animation pack. Measured: ANIMATION_Sword_Combat 242/244 = 0.99,
# POLYGON_Dungeon 0/801 = 0.00, so the separation needs no tuning.
ANIMATION_PACK_FBX_RATIO = 0.5


def detect_pack_type(guid_map) -> str:
    """Classify a package as an asset pack or an animation pack.

    Args:
        guid_map: unity_package.GuidMap with guid_to_pathname populated.

    Returns:
        "animations" or "assets".
    """
    fbx_paths = [
        p for p in guid_map.guid_to_pathname.values() if p.lower().endswith(".fbx")
    ]
    if not fbx_paths:
        return "assets"

    in_animations = sum(1 for p in fbx_paths if "/animations/" in p.lower())
    ratio = in_animations / len(fbx_paths)
    logger.debug(
        "Pack type: %d/%d FBX under Animations/ (ratio %.2f)",
        in_animations,
        len(fbx_paths),
        ratio,
    )
    return "animations" if ratio > ANIMATION_PACK_FBX_RATIO else "assets"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ -q`
Expected: PASS, 43 tests

- [ ] **Step 5: Commit**

```bash
git add converter.py tests/test_pack_type.py
git commit -m "feat: detect animation packs by Animations/ FBX ratio"
```

---

### Task 7: `--pack-type` flag and animation-mode pipeline branch

**Files:**
- Modify: `converter.py` (`ConversionConfig` around line 380; `parse_args()`
  around line 460; `generate_converter_config()` around line 1268;
  `run_conversion()`)
- Modify: `godot_converter.gd` (`load_converter_config()` around line 130)

**Interfaces:**
- Consumes: `detect_pack_type()` from Task 6.
- Produces:
  - `ConversionConfig.pack_type: str = "auto"`
  - `converter_config.json` key `"mode"` with value `"assets"` or `"animations"`
  - GDScript `config_mode: String`

- [ ] **Step 1: Add the config field and CLI flag**

In `ConversionConfig`, after `flatten_output`:

```python
    pack_type: str = "auto"
```

Document it in the class docstring's Attributes section:

```
        pack_type: Package kind - 'auto' (default, detected from content),
            'assets' (materials, textures and meshes), or 'animations'
            (clip FBX converted to AnimationLibrary resources).
```

In `parse_args()`, beside the other optional flags:

```python
    parser.add_argument(
        "--pack-type",
        choices=["auto", "assets", "animations"],
        default="auto",
        help="Package kind. Default 'auto' detects from content.",
    )
```

and pass `pack_type=args.pack_type` into the `ConversionConfig(...)` construction.

- [ ] **Step 2: Resolve the mode in `run_conversion()`**

Immediately after the `guid_map` is built in Step 3 of `run_conversion()`
(after the `extract_unitypackage` try/except block), add:

```python
        pack_mode = config.pack_type
        if pack_mode == "auto":
            pack_mode = detect_pack_type(guid_map)
        logger.info("Pack type: %s", pack_mode)
```

Guard the asset-only work. Wrap the block that runs Step 4 through Step 10
(material parsing through `character_definitions.json`) in:

```python
        if pack_mode == "assets":
            ...existing steps 4-10 unchanged...
        else:
            logger.info("Animation pack: skipping materials, textures and shaders")
```

FBX copying (Step 9) must still run in animation mode so the clips reach
`models/`; leave that call outside the guard.

- [ ] **Step 3: Pass the mode to GDScript**

Add a `mode` parameter to `generate_converter_config()`:

```python
def generate_converter_config(
    project_dir: Path,
    pack_name: str,
    keep_meshes_together: bool,
    mesh_format: str,
    filter_pattern: str | None,
    mesh_scale: float,
    output_subfolder: str | None,
    flatten_output: bool,
    dry_run: bool,
    mode: str = "assets",
) -> None:
```

Document it:

```
        mode: 'assets' to convert meshes, 'animations' to build
            AnimationLibrary resources from clip FBX.
```

Add it to the dict:

```python
        "mode": mode,
```

Pass `mode=pack_mode` at the call site in `run_conversion()`.

- [ ] **Step 4: Read the mode in GDScript**

In `load_converter_config()`, beside the other reads:

```gdscript
	config_mode = data.get("mode", "assets")
```

and declare it with the other config vars:

```gdscript
var config_mode: String = "assets"
```

In `process_pack_folder()`, branch immediately after the existing
`current_pack_folder = pack_folder` assignment and before
`load_material_mapping()` - `process_animation_pack()` reads
`current_pack_folder` to name its output:

```gdscript
	if config_mode == "animations":
		process_animation_pack(pack_folder)
		return
```

Add a stub so the branch is valid until Task 8:

```gdscript
func process_animation_pack(pack_folder: String) -> void:
	print("  Animation pack mode not yet implemented: %s" % pack_folder)
```

- [ ] **Step 5: Verify**

```bash
python -m pytest tests/ -q
python converter.py \
  --unity-package "C:/Users/Justin/Downloads/ANIMATION_Sword_Combat_Unity_2021_1_v1_2_0.unitypackage" \
  --source-files "D:/Unity Projects/AEGIS/Assets/Synty/AnimationSwordCombat" \
  --output "D:/GameAssets/Godot/Synty/tests" \
  --godot "C:/Users/Justin/Documents/git_repos/godot-bin/Godot_v4.7.2-stable_win64_console.exe" \
  --skip-godot-cli 2>&1 | grep -iE "Pack type|Animation pack"
```

Expected: `Pack type: animations` and the skip message; no materials generated.

- [ ] **Step 6: Commit**

```bash
git add converter.py godot_converter.gd
git commit -m "feat: add --pack-type and animation-mode pipeline branch"
```

---

### Task 8: Convert clip FBX into AnimationLibrary resources

**Files:**
- Modify: `godot_converter.gd`

**Interfaces:**
- Consumes: `config_mode`, `find_fbx_files()`, `_find_skeleton()` from Task 4.
- Produces:
  - `_detect_rig_family(skel: Skeleton3D) -> String` returning `"Polygon"`,
    `"Sidekick"` or `"Unknown"`
  - `process_animation_pack(pack_folder: String)` replacing the Task 7 stub
  - `animations/<PackName>_<Family>.res`

- [ ] **Step 1: Add rig-family detection**

The two rigs share zero bone names and use different conventions entirely -
Polygon is PascalCase (`Root`, `Hips`, `Spine_01`, `Clavicle_L`), Sidekick is
camelCase (`root`, `pelvis`, `thigh_l`, `calf_l`). Add near the top of
`godot_converter.gd`:

```gdscript
## Bone names unique to each Synty rig family. The families share no bone
## names at all, so a couple of hits is conclusive.
const POLYGON_RIG_PROBE := ["Hips", "Spine_01", "Clavicle_L", "Ankle_L"]
const SIDEKICK_RIG_PROBE := ["pelvis", "thigh_l", "calf_l", "ball_l"]
```

and the function:

```gdscript
## Classifies a skeleton as "Polygon", "Sidekick" or "Unknown".
## Unknown must never be bound to anything - guessing would be worse than
## leaving the character unanimated.
func _detect_rig_family(skel: Skeleton3D) -> String:
	if skel == null:
		return "Unknown"

	var names := {}
	for i in skel.get_bone_count():
		names[skel.get_bone_name(i)] = true

	var polygon_hits := 0
	for probe in POLYGON_RIG_PROBE:
		if names.has(probe):
			polygon_hits += 1
	var sidekick_hits := 0
	for probe in SIDEKICK_RIG_PROBE:
		if names.has(probe):
			sidekick_hits += 1

	if polygon_hits >= 2 and polygon_hits > sidekick_hits:
		return "Polygon"
	if sidekick_hits >= 2 and sidekick_hits > polygon_hits:
		return "Sidekick"
	return "Unknown"
```

- [ ] **Step 2: Implement the library pass**

Replace the Task 7 stub with:

```gdscript
## Converts every clip FBX in the pack into AnimationLibrary resources,
## one per rig family, saved to res://animations/.
func process_animation_pack(pack_folder: String) -> void:
	var models_path := pack_folder + "/models"
	var fbx_files := find_fbx_files(models_path)
	if fbx_files.is_empty():
		print("  No clip FBX found in %s" % models_path)
		return

	print("  Building animation libraries from %d clip(s)" % fbx_files.size())

	var libraries: Dictionary = {}   # family -> AnimationLibrary
	var clip_counts: Dictionary = {} # family -> int
	var skipped := 0

	for i in range(fbx_files.size()):
		var path := fbx_files[i]
		var packed := load(path) as PackedScene
		if packed == null:
			skipped += 1
			continue
		var inst := packed.instantiate()
		if inst == null:
			skipped += 1
			continue

		var player := _find_animation_player(inst)
		if player == null:
			skipped += 1
			inst.free()
			continue

		var family := _detect_rig_family(_find_skeleton(inst))
		if not libraries.has(family):
			libraries[family] = AnimationLibrary.new()
			clip_counts[family] = 0

		var library: AnimationLibrary = libraries[family]
		for anim_name in player.get_animation_list():
			var anim := player.get_animation(anim_name)
			if anim == null:
				continue
			var key := String(anim_name)
			if key.is_empty() or key == "Take 001":
				key = path.get_file().get_basename()
			key = _unique_animation_key(library, key)
			library.add_animation(key, anim.duplicate())
			clip_counts[family] = int(clip_counts[family]) + 1

		inst.free()

		if i % 100 == 0 and i > 0:
			print("    %d/%d clips processed" % [i, fbx_files.size()])

	var pack_label := current_pack_folder.get_file()
	_ensure_directory_exists("res://animations")

	for family in libraries:
		var out_path := "res://animations/%s_%s.res" % [pack_label, family]
		var save_result := ResourceSaver.save(libraries[family], out_path)
		if save_result == OK:
			print("  Saved %s (%d clips)" % [out_path, clip_counts[family]])
			meshes_saved += 1
		else:
			printerr("  ERROR: failed to save %s" % out_path)
			errors += 1

	if skipped > 0:
		print("  Skipped %d clip(s) with no AnimationPlayer" % skipped)


func _find_animation_player(node: Node) -> AnimationPlayer:
	if node is AnimationPlayer:
		return node
	for child in node.get_children():
		var found := _find_animation_player(child)
		if found != null:
			return found
	return null


## Appends a numeric suffix if the key is taken, so two clip FBX carrying the
## same internal animation name cannot overwrite each other.
func _unique_animation_key(library: AnimationLibrary, key: String) -> String:
	if not library.has_animation(key):
		return key
	var n := 2
	while library.has_animation("%s_%d" % [key, n]):
		n += 1
	return "%s_%d" % [key, n]
```

- [ ] **Step 3: Verify**

```bash
rm -rf "D:/GameAssets/Godot/Synty/tests/ANIMATION_Sword_Combat"
python converter.py \
  --unity-package "C:/Users/Justin/Downloads/ANIMATION_Sword_Combat_Unity_2021_1_v1_2_0.unitypackage" \
  --source-files "D:/Unity Projects/AEGIS/Assets/Synty/AnimationSwordCombat" \
  --output "D:/GameAssets/Godot/Synty/tests" \
  --godot "C:/Users/Justin/Documents/git_repos/godot-bin/Godot_v4.7.2-stable_win64_console.exe" \
  --godot-timeout 1800 2>&1 | grep -iE "Pack type|Saved res|Skipped|Errors"
ls -la "D:/GameAssets/Godot/Synty/tests/animations/"
```

Expected: `Pack type: animations`; at least
`ANIMATION_Sword_Combat_Polygon.res` written with a non-zero clip count;
0 errors. Import of ~244 clips takes several minutes.

- [ ] **Step 4: Commit**

```bash
git add godot_converter.gd
git commit -m "feat: build AnimationLibrary resources from clip FBX"
```

---

### Task 9: `--animations` flag and library selection

**Files:**
- Modify: `converter.py`
- Test: `tests/test_pack_type.py`

**Interfaces:**
- Produces:
  - `ConversionConfig.animations: str | None = None`
  - `resolve_animation_libraries(project_dir: Path, selector: str | None) -> list[str]`
    returning `res://`-relative library paths
  - `converter_config.json` key `"animation_libraries"` (list of strings)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pack_type.py`:

```python
from converter import resolve_animation_libraries  # noqa: E402


def _make_libs(tmp_path, names):
    d = tmp_path / "animations"
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).write_text("stub", encoding="utf-8")
    return tmp_path


class TestResolveAnimationLibraries:
    LIBS = [
        "ANIMATION_Sword_Combat_Polygon.res",
        "ANIMATION_Sword_Combat_Sidekick.res",
        "ANIMATION_Base_Locomotion_Polygon.res",
    ]

    def test_none_selects_nothing(self, tmp_path):
        root = _make_libs(tmp_path, self.LIBS)
        assert resolve_animation_libraries(root, None) == []

    def test_all_selects_everything(self, tmp_path):
        root = _make_libs(tmp_path, self.LIBS)
        assert len(resolve_animation_libraries(root, "all")) == 3

    def test_substring_match_is_case_insensitive(self, tmp_path):
        root = _make_libs(tmp_path, self.LIBS)
        got = resolve_animation_libraries(root, "sword_combat")
        assert sorted(got) == [
            "res://animations/ANIMATION_Sword_Combat_Polygon.res",
            "res://animations/ANIMATION_Sword_Combat_Sidekick.res",
        ]

    def test_multiple_selectors(self, tmp_path):
        root = _make_libs(tmp_path, self.LIBS)
        got = resolve_animation_libraries(root, "sword_combat,base_locomotion")
        assert len(got) == 3

    def test_unmatched_selector_returns_empty(self, tmp_path):
        root = _make_libs(tmp_path, self.LIBS)
        assert resolve_animation_libraries(root, "nope") == []

    def test_missing_animations_dir_returns_empty(self, tmp_path):
        assert resolve_animation_libraries(tmp_path, "all") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pack_type.py -q`
Expected: FAIL with `ImportError: cannot import name 'resolve_animation_libraries'`

- [ ] **Step 3: Implement**

In `converter.py`:

```python
def resolve_animation_libraries(project_dir: Path, selector: str | None) -> list[str]:
    """Resolve --animations selectors to res:// library paths.

    Args:
        project_dir: Godot project root; libraries live in animations/.
        selector: None (bind nothing), "all", or a comma-separated list of
            case-insensitive substrings matched against library filenames.

    Returns:
        Sorted res:// paths. Empty when nothing matches; the caller warns.
    """
    if not selector:
        return []

    animations_dir = project_dir / "animations"
    if not animations_dir.is_dir():
        return []

    libraries = sorted(p.name for p in animations_dir.glob("*.res"))
    if selector.strip().lower() == "all":
        matched = libraries
    else:
        needles = [s.strip().lower() for s in selector.split(",") if s.strip()]
        matched = [
            name for name in libraries if any(n in name.lower() for n in needles)
        ]

    return [f"res://animations/{name}" for name in matched]
```

Add the config field after `pack_type`:

```python
    animations: str | None = None
```

with the docstring entry:

```
        animations: Animation libraries to bind to converted characters.
            None binds nothing, 'all' binds every library in animations/,
            or a comma-separated list of case-insensitive substrings.
```

Add the CLI flag in `parse_args()`:

```python
    parser.add_argument(
        "--animations",
        default=None,
        help=(
            "Bind animation libraries to converted characters. "
            "'all', or a comma-separated list of substrings "
            "(e.g. 'sword_combat,base_locomotion')."
        ),
    )
```

and pass `animations=args.animations` into `ConversionConfig(...)`.

- [ ] **Step 4: Plumb into converter_config.json**

Add a parameter to `generate_converter_config()`:

```python
    animation_libraries: list[str] | None = None,
```

documented as:

```
        animation_libraries: res:// paths of AnimationLibrary resources to bind
            to character scenes.
```

and in the dict:

```python
        "animation_libraries": animation_libraries or [],
```

At the call site in `run_conversion()`:

```python
        animation_libraries = resolve_animation_libraries(project_dir, config.animations)
        if config.animations and not animation_libraries:
            warning_msg = f"No animation libraries matched '{config.animations}'"
            logger.warning(warning_msg)
            stats.warnings.append(warning_msg)
```

then pass `animation_libraries=animation_libraries`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/ -q`
Expected: PASS, 49 tests

- [ ] **Step 6: Commit**

```bash
git add converter.py tests/test_pack_type.py
git commit -m "feat: add --animations flag and library resolution"
```

---

### Task 10: Bind libraries with family and coverage gates

**Files:**
- Modify: `godot_converter.gd`

**Interfaces:**
- Consumes: `config_mode`, `_detect_rig_family()` from Task 8,
  `build_character_scene()` from Task 4.
- Produces:
  - `config_animation_libraries: Array`
  - `_bind_animation_libraries(player: AnimationPlayer, skel: Skeleton3D) -> void`
  - `_animation_bone_coverage(skel: Skeleton3D, library: AnimationLibrary) -> Dictionary`
    with keys `coverage: float` and `missing: Array`

- [ ] **Step 1: Read the config**

Declare with the other config vars:

```gdscript
var config_animation_libraries: Array = []
```

and in `load_converter_config()`:

```gdscript
	config_animation_libraries = data.get("animation_libraries", [])
```

- [ ] **Step 2: Implement coverage measurement**

```gdscript
## Fraction of the library's animated bone names that exist in the skeleton.
##
## Bones are compared by name. Godot disambiguates duplicate FBX bone names by
## appending an index in encounter order, and that order differs between files,
## so a character and a clip can disagree on finger-bone names while sharing an
## identical skeleton. That is exactly what this measures - and why the result
## is reported rather than repaired: a guessed correspondence could bind
## left-hand tracks to the right hand.
func _animation_bone_coverage(skel: Skeleton3D, library: AnimationLibrary) -> Dictionary:
	var have := {}
	for i in skel.get_bone_count():
		have[skel.get_bone_name(i)] = true

	var wanted := {}
	for anim_name in library.get_animation_list():
		var anim := library.get_animation(anim_name)
		if anim == null:
			continue
		for t in anim.get_track_count():
			var path := anim.track_get_path(t)
			var bone := String(path.get_concatenated_subnames())
			if not bone.is_empty():
				wanted[bone] = true
		# One animation is representative; scanning all of them on a
		# 242-clip library is pure cost.
		break

	if wanted.is_empty():
		return {"coverage": 1.0, "missing": []}

	var missing := []
	for bone in wanted:
		if not have.has(bone):
			missing.append(bone)

	var coverage := float(wanted.size() - missing.size()) / float(wanted.size())
	return {"coverage": coverage, "missing": missing}
```

- [ ] **Step 3: Implement binding**

```gdscript
## Minimum bone-name coverage before a bind is reported as suspect.
const MIN_BONE_COVERAGE := 0.90


## Binds the configured animation libraries to one character's AnimationPlayer.
## Refuses libraries from a different rig family outright; binds low-coverage
## libraries but says so.
func _bind_animation_libraries(player: AnimationPlayer, skel: Skeleton3D) -> void:
	if config_animation_libraries.is_empty():
		return

	var character_family := _detect_rig_family(skel)

	for lib_path in config_animation_libraries:
		var path := String(lib_path)
		if not ResourceLoader.exists(path):
			printerr("      WARNING: animation library not found: %s" % path)
			warnings += 1
			continue

		var library := load(path) as AnimationLibrary
		if library == null:
			printerr("      WARNING: not an AnimationLibrary: %s" % path)
			warnings += 1
			continue

		# Family is encoded in the filename by process_animation_pack().
		var base := path.get_file().get_basename()
		var library_family := "Unknown"
		if base.ends_with("_Polygon"):
			library_family = "Polygon"
		elif base.ends_with("_Sidekick"):
			library_family = "Sidekick"

		if library_family != character_family:
			printerr("      Refusing %s: library rig is %s, character rig is %s" % [
				path.get_file(), library_family, character_family])
			warnings += 1
			continue

		var report := _animation_bone_coverage(skel, library)
		var coverage: float = report["coverage"]
		if coverage < MIN_BONE_COVERAGE:
			var missing: Array = report["missing"]
			printerr("      WARNING: %s covers %.0f%% of bones; missing: %s" % [
				path.get_file(), coverage * 100.0, str(missing.slice(0, 8))])
			warnings += 1

		player.add_animation_library(base, library)
		print("      Bound %s (%d clips, %.0f%% bone coverage)" % [
			base, library.get_animation_list().size(), coverage * 100.0])
```

- [ ] **Step 4: Call it from character construction**

In `build_character_scene()`, replace:

```gdscript
	var player := AnimationPlayer.new()
	player.name = "AnimationPlayer"
	root.add_child(player)
```

with:

```gdscript
	var player := AnimationPlayer.new()
	player.name = "AnimationPlayer"
	root.add_child(player)
	_bind_animation_libraries(player, skel)
```

- [ ] **Step 5: Verify**

```bash
rm -rf "D:/GameAssets/Godot/Synty/tests/POLYGON_Dungeon"
python converter.py \
  --unity-package "C:/Users/Justin/Downloads/POLYGON_Dungeon_Unity_2021_3_v1_9_5.unitypackage" \
  --source-files "D:/Unity Projects/AEGIS/Assets/Synty/PolygonDungeon" \
  --output "D:/GameAssets/Godot/Synty/tests" \
  --godot "C:/Users/Justin/Documents/git_repos/godot-bin/Godot_v4.7.2-stable_win64_console.exe" \
  --animations sword_combat --godot-timeout 1800 2>&1 \
  | grep -iE "Bound |Refusing |coverage|Characters:|Errors"

grep -c "AnimationLibrary" "D:/GameAssets/Godot/Synty/tests/POLYGON_Dungeon/meshes/tscn_separate/Character_Goblin_WarChief.tscn"
```

Expected:
- `Bound ANIMATION_Sword_Combat_Polygon (...)` for each character
- `Refusing ANIMATION_Sword_Combat_Sidekick.res: library rig is Sidekick, character rig is Polygon`
- a coverage warning naming finger bones, since Dungeon characters share 38/49 bone names with the canonical rig
- the character scene references the library

- [ ] **Step 6: Confirm the animation actually plays**

Assertions cannot tell a correct bind from a mangled one. Open the project and
play a clip on one character:

```bash
"C:/Users/Justin/Documents/git_repos/godot-bin/Godot_v4.7.2-stable_win64.exe" \
  --path "D:/GameAssets/Godot/Synty/tests"
```

Open `Character_Goblin_WarChief.tscn`, select the `AnimationPlayer`, pick a clip
from the Sword Combat library, and scrub it. The character should move without
limbs detaching or inverting. Hands may be wrong - that is the known, reported
finger-name limitation, not a regression.

- [ ] **Step 7: Commit**

```bash
git add godot_converter.gd
git commit -m "feat: bind animation libraries with rig-family and coverage gates"
```

---

### Task 11: Documentation

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `docs/architecture.md`

**Interfaces:**
- Consumes: everything above. Produces no code.

- [ ] **Step 1: Update the README CLI table**

Add to the CLI Options table:

```markdown
| `--pack-type` | No | `auto` (default), `assets`, or `animations` |
| `--animations` | No | Bind animation libraries to characters: `all` or comma-separated substrings |
```

Add a section after "Material Matching":

```markdown
## Characters and Animations

Skinned meshes convert to rigged Godot scenes - `Skeleton3D`, `skin`,
bone-attached equipment, and an `AnimationPlayer` - instead of static bind-pose
meshes. Which body mesh and which equipment belong to a character is read from
the Unity prefab, which ships with every character but one disabled.

ANIMATION_* packs are detected automatically and convert to
`animations/<Pack>_<Family>.res` AnimationLibrary resources. Bind them with
`--animations`:

```bash
python converter.py ... --animations sword_combat,base_locomotion
```

Synty uses two incompatible rig families, `Polygon` and `Sidekick`, which share
no bone names. Libraries are emitted per family and the converter refuses to
bind one family's clips to the other's characters. Where bone names partially
disagree it binds anyway and reports the coverage.
```

- [ ] **Step 2: Update CLAUDE.md**

Add to the Project Structure block:

```
├── prefab_parser.py      # Prefab-derived mesh-material mapping + character definitions
```

Add to Key Architecture:

```markdown
- **Rigged characters**: skinned meshes emit `Skeleton3D` + `skin` +
  `BoneAttachment3D` + `AnimationPlayer` scenes, driven by
  `character_definitions.json` derived from Unity prefabs
- **Animation packs**: auto-detected by `/Animations/` FBX ratio > 0.5, converted
  to `animations/<Pack>_<Family>.res`; bound via `--animations`
- **`--mesh-scale` never touches skinned vertices**: it would break the bind
  pose, so rigged characters carry scale on the scene root
```

- [ ] **Step 3: Update docs/architecture.md**

Add `character_definitions.json` to the Output Artifacts table:

```markdown
| `PACK_NAME/character_definitions.json` | Character body/equipment composition for rigged output |
| `animations/<Pack>_<Family>.res` | AnimationLibrary per pack per rig family |
```

Add `prefab_parser.py` to the Module Responsibilities table:

```markdown
| `prefab_parser.py` | `.prefab` bytes | `PrefabMaterials`, `CharacterDefinition` | Mesh-material mapping fallback and character composition |
```

- [ ] **Step 4: Verify**

Run: `python -m pytest tests/ -q`
Expected: PASS, 49 tests

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md docs/architecture.md
git commit -m "docs: document rigged characters and animation packs"
```

---

## Final verification

- [ ] `python -m pytest tests/ -q` - 49 tests pass
- [ ] Full POLYGON_Dungeon conversion, unscaled: 0 empty meshes, characters have
      `Skeleton3D` + `skin` + `AnimationPlayer`, prop scenes unchanged from the
      current pipeline
- [ ] Full POLYGON_Dungeon conversion with `--mesh-scale 100`: 0 empty meshes,
      character scale on the root node not in vertices
- [ ] ANIMATION_Sword_Combat conversion produces a Polygon library with a
      non-zero clip count
- [ ] `--animations sword_combat` binds the Polygon library, refuses the Sidekick
      one, and reports bone coverage
- [ ] One character visually inspected in Godot, animation scrubbed, no limb
      detachment or inversion

# Sidekick Character Assembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert Synty SIDEKICK packs into rigged, textured, animatable Godot character scenes by assembling each character's part meshes onto one skeleton from its `.sk` recipe.

**Architecture:** A new `sidekick.py` parses `.sk` recipes and resolves each named part to an FBX in the pack's output `models/` directory, writing `PackName/sidekick_characters.json`. A new pack-level pass in `godot_converter.gd` reads that file and assembles each character — one `MeshInstance3D` per part under a single duplicated `Skeleton3D`, plus an `AnimationPlayer`. The existing per-FBX POLYGON character path is untouched.

**Tech Stack:** Python 3.10+ stdlib only (`re`, `json`, `dataclasses`, `pathlib`), pytest for tests, GDScript for Godot 4.x.

**Spec:** `docs/superpowers/specs/2026-09-12-sidekick-character-assembly-design.md`

## Global Constraints

- Python CLI must remain **stdlib-only**. No new dependencies.
- `.sk` files use **CRLF** line endings. Every regex must tolerate `\r?\n`. A pattern anchored with a bare `\n` matches zero parts and fails silently.
- Part resolution happens against the pack's **output `models/` directory**, never against package asset paths — `copy_fbx_files()` strips `SourceFiles`/`FBX`/`Models` prefixes, so the two differ.
- Recipe resolution runs in **Step 10**, after Step 9 has copied FBX into `models/`.
- All Godot-side failures go through `_report_error` / `_report_warning` so they reach the Python summary via `GODOT_SUMMARY`.
- In `godot_converter.gd`, a `MeshInstance3D`'s `skin` must be assigned **after** `add_child()`. Assigning it first leaves the mesh in bind pose while the skeleton animates.
- Run the full suite with `python -m pytest tests/ -q` (72 tests pass before this work).
- Godot executable for manual verification: `C:\Users\Justin\Documents\git_repos\godot-bin\Godot_v4.7.2-stable_win64_console.exe` (the `_console.exe` variant — the plain `.exe` writes nothing to the pipe).

---

### Task 1: Parse `.sk` recipes

**Files:**
- Create: `sidekick.py`
- Test: `tests/test_sidekick.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `SidekickPart(slot: str, mesh: str, fbx: str = "")`, `SidekickRecipe(name: str, species: int = 0, parts: list[SidekickPart], color_map: str = "")`, `parse_sk_bytes(data: bytes) -> SidekickRecipe | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sidekick.py`:

```python
"""Tests for parsing and resolving Sidekick character recipes."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sidekick import (  # noqa: E402
    SidekickPart,
    SidekickRecipe,
    parse_sk_bytes,
)

# Shipped .sk files are CRLF. Building the fixture with explicit \r\n keeps the
# tests honest about the format the parser actually meets.
SK_BODY = (
    "Name: HumanSpecies_01\r\n"
    "Species: 1\r\n"
    "Parts:\r\n"
    "- Name: SK_HUMN_BASE_01_01HEAD_HU01\r\n"
    "  PartType: Head\r\n"
    "  PartVersion: 1\r\n"
    "- Name: SK_HUMN_BASE_01_10TORS_HU01\r\n"
    "  PartType: Torso\r\n"
    "  PartVersion: 1\r\n"
    "ColorSet:\r\n"
    "  Species: 1\r\n"
    "  Name: Custom\r\n"
    "ColorRows:\r\n"
    "- ColorProperty: 1\r\n"
    "  MainColor: FCC19C\r\n"
)


class TestParseSkBytes:
    def test_reads_name_and_species(self):
        recipe = parse_sk_bytes(SK_BODY.encode("utf-8"))
        assert recipe.name == "HumanSpecies_01"
        assert recipe.species == 1

    def test_reads_every_part_in_order(self):
        recipe = parse_sk_bytes(SK_BODY.encode("utf-8"))
        assert [(p.slot, p.mesh) for p in recipe.parts] == [
            ("Head", "SK_HUMN_BASE_01_01HEAD_HU01"),
            ("Torso", "SK_HUMN_BASE_01_10TORS_HU01"),
        ]

    def test_lf_parses_identically(self):
        """The parser must not be accidentally CRLF-only."""
        crlf = parse_sk_bytes(SK_BODY.encode("utf-8"))
        lf = parse_sk_bytes(SK_BODY.replace("\r\n", "\n").encode("utf-8"))
        assert [(p.slot, p.mesh) for p in lf.parts] == [
            (p.slot, p.mesh) for p in crlf.parts
        ]
        assert lf.name == crlf.name

    def test_colorset_name_does_not_override_character_name(self):
        """ColorSet carries an indented 'Name: Custom' that must be ignored."""
        assert parse_sk_bytes(SK_BODY.encode("utf-8")).name == "HumanSpecies_01"

    def test_no_parts_block_yields_none(self):
        data = b"Name: Empty\r\nSpecies: 1\r\nColorRows:\r\n"
        assert parse_sk_bytes(data) is None

    def test_no_name_yields_none(self):
        data = (
            "Parts:\r\n- Name: SK_X\r\n  PartType: Head\r\n"
        ).encode("utf-8")
        assert parse_sk_bytes(data) is None

    def test_missing_species_defaults_to_zero(self):
        data = (
            "Name: NoSpecies\r\nParts:\r\n- Name: SK_X\r\n  PartType: Head\r\n"
        ).encode("utf-8")
        assert parse_sk_bytes(data).species == 0

    def test_parts_start_unresolved(self):
        recipe = parse_sk_bytes(SK_BODY.encode("utf-8"))
        assert all(p.fbx == "" for p in recipe.parts)

    def test_dataclass_defaults(self):
        part = SidekickPart(slot="Head", mesh="SK_X")
        recipe = SidekickRecipe(name="R")
        assert (part.fbx, recipe.species, recipe.parts, recipe.color_map) == (
            "", 0, [], "",
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_sidekick.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sidekick'`

- [ ] **Step 3: Write the module**

Create `sidekick.py`:

```python
"""Sidekick character recipes.

Synty's SIDEKICK packs are a modular character creator rather than a set of
finished characters. A character is not one FBX: it is a recipe naming one part
mesh per body slot - head, torso, each limb, each armour attachment - with every
part skinned to the same 88-bone rig.

That recipe ships with the pack as a plain-text ``.sk`` file. The character's
prefab is no use to us: its SkinnedMeshRenderer points at a mesh Unity baked at
author time (``FantasyKnights_01.asset``), which Godot cannot import. The recipe
plus the part FBX is the only route to rebuilding the character, and both ship.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# .sk files are CRLF. A pattern anchored with a bare \n matches nothing, reports
# zero parts and raises no error - so every pattern here tolerates \r?\n.
#
# The top-level keys are unindented, which is what separates them from the
# indented "Name:" and "Species:" inside the ColorSet block and from the
# "- Name:" part entries.
_NAME_PATTERN = re.compile(r"^Name:[ \t]*(\S[^\r\n]*?)[ \t]*\r?$", re.MULTILINE)
_SPECIES_PATTERN = re.compile(r"^Species:[ \t]*(\d+)[ \t]*\r?$", re.MULTILINE)
_PART_PATTERN = re.compile(
    r"^-[ \t]*Name:[ \t]*(\S+)[ \t]*\r?\n[ \t]*PartType:[ \t]*(\S+)[ \t]*\r?$",
    re.MULTILINE,
)


@dataclass
class SidekickPart:
    """One mesh filling one body slot of a Sidekick character.

    Attributes:
        slot: The recipe's PartType, e.g. "Torso", "AttachmentShoulderLeft".
        mesh: Part name as written in the recipe, e.g.
            "SK_FANT_KNGT_17_10TORS_HU01". This is the FBX basename.
        fbx: Path to the part's FBX relative to the pack's models/ directory,
            without extension. Empty when no such FBX was found.
    """

    slot: str
    mesh: str
    fbx: str = ""


@dataclass
class SidekickRecipe:
    """One Sidekick character, as described by its .sk file.

    Attributes:
        name: Character name, e.g. "FantasyKnights_05".
        species: Species id from the recipe. Recorded, not interpreted.
        parts: One entry per body slot, in recipe order.
        color_map: Basename of the character's 32x32 palette texture, e.g.
            "T_FantasyKnights_05ColorMap". Empty when the pack ships none.
    """

    name: str
    species: int = 0
    parts: list[SidekickPart] = field(default_factory=list)
    color_map: str = ""


def parse_sk_bytes(data: bytes) -> SidekickRecipe | None:
    """Parse one .sk recipe.

    Only Name, Species and the Parts list are consumed. ColorSet and ColorRows
    describe a texture bake the pack already ships the result of.

    Args:
        data: Raw .sk file content.

    Returns:
        The recipe, or None when the file carries no name or no parts - either
        means it is not a character recipe we can build.
    """
    text = data.decode("utf-8", errors="replace")

    name_match = _NAME_PATTERN.search(text)
    if not name_match:
        return None

    parts = [
        SidekickPart(slot=slot, mesh=mesh)
        for mesh, slot in _PART_PATTERN.findall(text)
    ]
    if not parts:
        logger.debug("Recipe %s lists no parts; skipping", name_match.group(1))
        return None

    species_match = _SPECIES_PATTERN.search(text)
    return SidekickRecipe(
        name=name_match.group(1),
        species=int(species_match.group(1)) if species_match else 0,
        parts=parts,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_sidekick.py -q`
Expected: PASS (9 tests)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (81 tests)

- [ ] **Step 6: Commit**

```bash
git add sidekick.py tests/test_sidekick.py
git commit -m "feat: parse Sidekick .sk character recipes"
```

---

### Task 2: Extract `.sk` contents from the package

**Files:**
- Modify: `unity_package.py` — `GuidMap` dataclass, `extract_unitypackage()`, new `_extract_sk_contents()`

**Interfaces:**
- Consumes: existing `_extract_contents_by_extension(guid_data, guid_to_pathname, extension, *, warn_on_missing=True)`.
- Produces: `GuidMap.guid_to_sk_content: dict[str, bytes]`.

- [ ] **Step 1: Add the field to `GuidMap`**

In `unity_package.py`, find the dataclass field `guid_to_prefab_content: dict[str, bytes] = field(default_factory=dict)` and add immediately after it:

```python
    guid_to_sk_content: dict[str, bytes] = field(default_factory=dict)
```

In the `GuidMap` docstring's `Attributes:` section, after the `guid_to_prefab_content` entry, add:

```
        guid_to_sk_content: Maps GUID to raw .sk content. Sidekick packs ship
            one .sk per character, listing the part meshes it is assembled
            from. Empty for every other pack type.
```

- [ ] **Step 2: Add the extraction helper**

In `unity_package.py`, directly after `_extract_prefab_contents()`, add:

```python
def _extract_sk_contents(
    guid_data: dict[str, dict[str, bytes]], guid_to_pathname: dict[str, str]
) -> dict[str, bytes]:
    """Extract raw content for .sk files.

    Consumed by sidekick.build_sidekick_recipes(). Only SIDEKICK packs carry
    these, so a missing asset file is unremarkable and warns at debug level.

    Args:
        guid_data: Parsed tar structure from _parse_tar_structure.
        guid_to_pathname: GUID to pathname mapping for identifying .sk files.

    Returns:
        Dictionary mapping recipe GUID to raw file content (bytes).
    """
    return _extract_contents_by_extension(
        guid_data, guid_to_pathname, ".sk", warn_on_missing=False
    )
```

- [ ] **Step 3: Call it from `extract_unitypackage`**

In `extract_unitypackage()`, find:

```python
    guid_to_prefab_content = _extract_prefab_contents(guid_data, guid_to_pathname)
    logger.debug("Extracted content for %d prefab files", len(guid_to_prefab_content))
```

Add immediately after:

```python
    guid_to_sk_content = _extract_sk_contents(guid_data, guid_to_pathname)
    if guid_to_sk_content:
        logger.debug("Extracted %d Sidekick recipe(s)", len(guid_to_sk_content))
```

Then in the `GuidMap(...)` construction, find `guid_to_prefab_content=guid_to_prefab_content,` and add after it:

```python
        guid_to_sk_content=guid_to_sk_content,
```

- [ ] **Step 4: Verify against a real pack**

Run:

```bash
python -c "
from unity_package import extract_unitypackage
from pathlib import Path
gm = extract_unitypackage(Path(r'C:\Users\Justin\Downloads\SIDEKICK_Starter_Unity_2021_3_v1_0_4.unitypackage'))
print('sk recipes:', len(gm.guid_to_sk_content))
"
```

Expected: `sk recipes: 8`

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (81 tests)

- [ ] **Step 6: Commit**

```bash
git add unity_package.py
git commit -m "feat: extract .sk recipe contents from unitypackages"
```

---

### Task 3: Resolve recipes and write `sidekick_characters.json`

**Files:**
- Modify: `sidekick.py`
- Test: `tests/test_sidekick.py`

**Interfaces:**
- Consumes: `parse_sk_bytes()` from Task 1; `GuidMap.guid_to_sk_content` from Task 2.
- Produces: `build_sidekick_recipes(guid_map, source_dirs: list[Path], models_dir: Path) -> dict[str, SidekickRecipe]`, `write_sidekick_characters_json(recipes: dict[str, SidekickRecipe], output_path: Path, *, indent: int = 2) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sidekick.py`, before the `if __name__` block:

```python
from sidekick import (  # noqa: E402
    build_sidekick_recipes,
    write_sidekick_characters_json,
)


class _FakeGuidMap:
    def __init__(self, sk_content=None, textures=None):
        self.guid_to_sk_content = sk_content or {}
        self.texture_guid_to_name = textures or {}
        self.guid_to_pathname = {}


def _models(tmp_path, relative_fbx):
    """Create a models/ tree containing the named FBX files."""
    models = tmp_path / "models"
    for rel in relative_fbx:
        path = models / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fbx")
    models.mkdir(parents=True, exist_ok=True)
    return models


class TestBuildSidekickRecipes:
    def test_resolves_parts_to_models_relative_paths(self, tmp_path):
        models = _models(tmp_path, [
            "Resources/Meshes/Species/Humans/SK_HUMN_BASE_01_01HEAD_HU01.fbx",
            "Resources/Meshes/Species/Humans/SK_HUMN_BASE_01_10TORS_HU01.fbx",
        ])
        gm = _FakeGuidMap({"g": SK_BODY.encode("utf-8")})
        recipes = build_sidekick_recipes(gm, [], models)
        parts = recipes["HumanSpecies_01"].parts
        assert parts[0].fbx == "Resources/Meshes/Species/Humans/SK_HUMN_BASE_01_01HEAD_HU01"
        assert parts[1].fbx == "Resources/Meshes/Species/Humans/SK_HUMN_BASE_01_10TORS_HU01"

    def test_unresolved_part_keeps_recipe(self, tmp_path):
        """A part from another pack must not lose the whole character."""
        models = _models(tmp_path, [
            "Meshes/SK_HUMN_BASE_01_01HEAD_HU01.fbx",
        ])
        gm = _FakeGuidMap({"g": SK_BODY.encode("utf-8")})
        recipes = build_sidekick_recipes(gm, [], models)
        parts = recipes["HumanSpecies_01"].parts
        assert parts[0].fbx == "Meshes/SK_HUMN_BASE_01_01HEAD_HU01"
        assert parts[1].fbx == ""

    def test_recipe_with_no_resolved_parts_is_dropped(self, tmp_path):
        models = _models(tmp_path, [])
        gm = _FakeGuidMap({"g": SK_BODY.encode("utf-8")})
        assert build_sidekick_recipes(gm, [], models) == {}

    def test_duplicate_basename_takes_first_in_sorted_order(self, tmp_path):
        models = _models(tmp_path, [
            "B/SK_HUMN_BASE_01_01HEAD_HU01.fbx",
            "A/SK_HUMN_BASE_01_01HEAD_HU01.fbx",
        ])
        gm = _FakeGuidMap({"g": SK_BODY.encode("utf-8")})
        recipes = build_sidekick_recipes(gm, [], models)
        assert recipes["HumanSpecies_01"].parts[0].fbx == "A/SK_HUMN_BASE_01_01HEAD_HU01"

    def test_color_map_resolves_when_texture_present(self, tmp_path):
        models = _models(tmp_path, ["M/SK_HUMN_BASE_01_01HEAD_HU01.fbx"])
        gm = _FakeGuidMap(
            {"g": SK_BODY.encode("utf-8")},
            {"t": "T_HumanSpecies_01ColorMap.png"},
        )
        recipes = build_sidekick_recipes(gm, [], models)
        assert recipes["HumanSpecies_01"].color_map == "T_HumanSpecies_01ColorMap"

    def test_color_map_empty_when_absent(self, tmp_path):
        models = _models(tmp_path, ["M/SK_HUMN_BASE_01_01HEAD_HU01.fbx"])
        gm = _FakeGuidMap({"g": SK_BODY.encode("utf-8")})
        assert build_sidekick_recipes(gm, [], models)["HumanSpecies_01"].color_map == ""

    def test_source_files_recipe_overrides_package(self, tmp_path):
        """A recipe saved in the user's Unity project is the likelier edit."""
        models = _models(tmp_path, ["M/SK_OTHER.fbx"])
        src = tmp_path / "src" / "Characters"
        src.mkdir(parents=True)
        (src / "HumanSpecies_01.sk").write_bytes(
            (
                "Name: HumanSpecies_01\r\nSpecies: 2\r\nParts:\r\n"
                "- Name: SK_OTHER\r\n  PartType: Head\r\n"
            ).encode("utf-8")
        )
        gm = _FakeGuidMap({"g": SK_BODY.encode("utf-8")})
        recipes = build_sidekick_recipes(gm, [tmp_path / "src"], models)
        assert recipes["HumanSpecies_01"].species == 2
        assert [p.mesh for p in recipes["HumanSpecies_01"].parts] == ["SK_OTHER"]

    def test_missing_models_dir_yields_nothing(self, tmp_path):
        gm = _FakeGuidMap({"g": SK_BODY.encode("utf-8")})
        assert build_sidekick_recipes(gm, [], tmp_path / "nope") == {}

    def test_no_recipes_yields_empty(self, tmp_path):
        assert build_sidekick_recipes(_FakeGuidMap(), [], _models(tmp_path, [])) == {}


class TestWriteSidekickCharactersJson:
    def test_writes_expected_shape(self, tmp_path):
        models = _models(tmp_path, [
            "Resources/Meshes/Species/Humans/SK_HUMN_BASE_01_01HEAD_HU01.fbx",
            "Resources/Meshes/Species/Humans/SK_HUMN_BASE_01_10TORS_HU01.fbx",
        ])
        gm = _FakeGuidMap(
            {"g": SK_BODY.encode("utf-8")},
            {"t": "T_HumanSpecies_01ColorMap.png"},
        )
        recipes = build_sidekick_recipes(gm, [], models)
        out = tmp_path / "sidekick_characters.json"
        write_sidekick_characters_json(recipes, out)

        import json as _json

        assert _json.loads(out.read_text(encoding="utf-8")) == {
            "HumanSpecies_01": {
                "species": 1,
                "color_map": "T_HumanSpecies_01ColorMap",
                "parts": [
                    {
                        "slot": "Head",
                        "mesh": "SK_HUMN_BASE_01_01HEAD_HU01",
                        "fbx": "Resources/Meshes/Species/Humans/SK_HUMN_BASE_01_01HEAD_HU01",
                    },
                    {
                        "slot": "Torso",
                        "mesh": "SK_HUMN_BASE_01_10TORS_HU01",
                        "fbx": "Resources/Meshes/Species/Humans/SK_HUMN_BASE_01_10TORS_HU01",
                    },
                ],
            }
        }

    def test_creates_parent_directory(self, tmp_path):
        out = tmp_path / "deep" / "sidekick_characters.json"
        write_sidekick_characters_json({}, out)
        assert out.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_sidekick.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_sidekick_recipes' from 'sidekick'`

- [ ] **Step 3: Implement resolution and writing**

Append to `sidekick.py`:

```python
def _index_fbx(models_dir: Path) -> dict[str, str]:
    """Map every FBX basename under models_dir to its relative path.

    Resolution deliberately uses the pack's *output* models/ directory rather
    than the package's asset paths: copy_fbx_files() strips SourceFiles/FBX/
    Models prefixes, so the two layouts differ, and only this one is what the
    Godot side will join to models/.

    Args:
        models_dir: The pack's output models/ directory.

    Returns:
        Basename without extension to path relative to models_dir, also
        without extension, using forward slashes.
    """
    index: dict[str, str] = {}
    if not models_dir.is_dir():
        logger.debug("No models directory at %s", models_dir)
        return index

    # Sorted so a duplicate basename resolves the same way on every run.
    for path in sorted(models_dir.rglob("*.fbx")):
        stem = path.stem
        relative = path.relative_to(models_dir).with_suffix("").as_posix()
        if stem in index:
            logger.warning(
                "Duplicate part basename %s: keeping %s, ignoring %s",
                stem,
                index[stem],
                relative,
            )
            continue
        index[stem] = relative
    return index


def build_sidekick_recipes(
    guid_map, source_dirs: list[Path], models_dir: Path
) -> dict[str, SidekickRecipe]:
    """Collect and resolve every Sidekick recipe available for a pack.

    Recipes come from the .unitypackage and from --source-files. The latter
    wins on a name collision: a recipe saved into the user's Unity project is
    a character they built with the Sidekick tool, which is the likelier edit.

    Args:
        guid_map: unity_package.GuidMap with guid_to_sk_content and
            texture_guid_to_name.
        source_dirs: Directories to search recursively for .sk files.
        models_dir: The pack's output models/ directory, already populated.

    Returns:
        Character name to SidekickRecipe, for recipes with at least one part
        resolved to an FBX.
    """
    recipes: dict[str, SidekickRecipe] = {}

    sk_content = getattr(guid_map, "guid_to_sk_content", None) or {}
    for data in sk_content.values():
        recipe = parse_sk_bytes(data)
        if recipe:
            recipes[recipe.name] = recipe

    for source_dir in source_dirs:
        directory = Path(source_dir)
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.sk")):
            try:
                recipe = parse_sk_bytes(path.read_bytes())
            except OSError as exc:
                logger.warning("Could not read %s: %s", path, exc)
                continue
            if recipe:
                recipes[recipe.name] = recipe

    index = _index_fbx(models_dir)
    textures = {
        Path(name).stem
        for name in (getattr(guid_map, "texture_guid_to_name", None) or {}).values()
    }

    resolved: dict[str, SidekickRecipe] = {}
    for name, recipe in recipes.items():
        for part in recipe.parts:
            part.fbx = index.get(part.mesh, "")

        found = sum(1 for part in recipe.parts if part.fbx)
        if not found:
            logger.warning(
                "Sidekick character %s: none of its %d part(s) matched an FBX "
                "in %s; skipping",
                name,
                len(recipe.parts),
                models_dir,
            )
            continue
        if found < len(recipe.parts):
            logger.debug(
                "Sidekick character %s: %d of %d parts resolved",
                name,
                found,
                len(recipe.parts),
            )

        candidate = f"T_{name}ColorMap"
        recipe.color_map = candidate if candidate in textures else ""
        resolved[name] = recipe

    logger.debug("Resolved %d Sidekick recipe(s)", len(resolved))
    return resolved


def write_sidekick_characters_json(
    recipes: dict[str, SidekickRecipe],
    output_path: Path,
    *,
    indent: int = 2,
) -> None:
    """Write sidekick_characters.json for godot_converter.gd.

    Args:
        recipes: Output of build_sidekick_recipes().
        output_path: Normally <pack_output_dir>/sidekick_characters.json.
        indent: JSON indentation level.
    """
    payload = {
        name: {
            "species": recipe.species,
            "color_map": recipe.color_map,
            "parts": [
                {"slot": part.slot, "mesh": part.mesh, "fbx": part.fbx}
                for part in recipe.parts
            ],
        }
        for name, recipe in recipes.items()
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=indent, ensure_ascii=False), encoding="utf-8"
    )
    logger.debug("Wrote %d Sidekick recipe(s) to %s", len(payload), output_path)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_sidekick.py -q`
Expected: PASS (20 tests)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (92 tests)

- [ ] **Step 6: Commit**

```bash
git add sidekick.py tests/test_sidekick.py
git commit -m "feat: resolve Sidekick recipe parts and emit sidekick_characters.json"
```

---

### Task 4: Map Sidekick's `_ColorMap` to the shader's base texture

**Files:**
- Modify: `shader_mapping.py` — `TEXTURE_MAP_POLYGON`
- Test: `tests/test_shader_mapping.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `TEXTURE_MAP_POLYGON["_ColorMap"] == "base_texture"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_shader_mapping.py`:

```python
"""Tests for Unity-to-Godot shader property mapping."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shader_mapping import TEXTURE_MAP_POLYGON  # noqa: E402


class TestSidekickColorMap:
    def test_color_map_maps_to_base_texture(self):
        """Sidekick materials name their palette _ColorMap.

        Each Sidekick character carries a baked 32x32 palette that its part
        meshes' UVs index into. Without this entry the palette never reaches
        the generated material and the texture copy never pulls the PNG, so
        every Sidekick character converts untextured.
        """
        assert TEXTURE_MAP_POLYGON["_ColorMap"] == "base_texture"

    def test_known_albedo_aliases_still_map(self):
        """The aliases other packs rely on must not regress."""
        for unity_name in ("_MainTex", "_BaseMap", "_Base_Texture", "_Texture"):
            assert TEXTURE_MAP_POLYGON[unity_name] == "base_texture"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_shader_mapping.py -q`
Expected: FAIL — `KeyError: '_ColorMap'`

- [ ] **Step 3: Add the mapping**

In `shader_mapping.py`, inside `TEXTURE_MAP_POLYGON`, find:

```python
    "_Texture": "base_texture",  # CustomCharacters shader (FantasyHero, ModularHero, etc.)
```

Add immediately after:

```python
    "_ColorMap": "base_texture",  # Sidekick: baked 32x32 per-character palette
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_shader_mapping.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (94 tests)

- [ ] **Step 6: Commit**

```bash
git add shader_mapping.py tests/test_shader_mapping.py
git commit -m "fix: map Sidekick _ColorMap to base_texture"
```

---

### Task 5: Stop emitting character definitions that can never match

**Files:**
- Modify: `prefab_parser.py` — `build_character_definitions()`
- Test: `tests/test_character_definitions.py`

**Interfaces:**
- Consumes: existing `_MESH_REF_PATTERN`, `_models_relative_name()`.
- Produces: no signature change; `build_character_definitions()` skips prefabs whose mesh is not an FBX.

- [ ] **Step 1: Write the failing test**

In `tests/test_character_definitions.py`, add to `PATHNAMES`:

```python
    "dddddddddddddddddddddddddddddddd": "Assets/P/Characters/FantasyKnights_01/Meshes/FantasyKnights_01.asset",
    "psk": "Assets/P/Characters/FantasyKnights_01/FantasyKnights_01.prefab",
```

Then add to `TestBuildCharacterDefinitions`:

```python
    def test_ignores_prefab_whose_mesh_is_not_an_fbx(self):
        """Sidekick prefabs point at a Unity-baked .asset mesh.

        Godot cannot import .asset, so such a definition could never match a
        file and produced a silent zero-character conversion. Sidekick
        characters are built from .sk recipes instead.
        """
        data = _prefab(
            f"""--- !u!1 &1
GameObject:
  m_Name: FantasyKnights_01
  m_IsActive: 1
--- !u!137 &2
SkinnedMeshRenderer:
  m_GameObject: {{fileID: 1}}
{_bones(CHARACTER_BONES)}
  m_Mesh: {{fileID: 1, guid: dddddddddddddddddddddddddddddddd, type: 3}}
"""
        )
        assert build_character_definitions(_guid_map({"psk": data})) == {}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_character_definitions.py -q`
Expected: FAIL — the definition is created with `source_fbx == "FantasyKnights_01.asset"`

- [ ] **Step 3: Add the guard**

In `prefab_parser.py`, inside `build_character_definitions()`, find:

```python
        source_fbx = _models_relative_name(guid_map.guid_to_pathname.get(mesh_guid, ""))
```

Replace with:

```python
        mesh_path = guid_map.guid_to_pathname.get(mesh_guid, "")
        if mesh_path and not mesh_path.lower().endswith(".fbx"):
            # Sidekick prefabs point at a Unity-baked .asset mesh, which Godot
            # cannot import. A definition naming it could never match a file,
            # so it would sit in the JSON claiming a character we never build.
            # Those characters come from .sk recipes instead - see sidekick.py.
            logger.debug(
                "Skipping '%s': mesh %s is not an FBX", prefab_name, mesh_path
            )
            skipped_non_fbx_mesh += 1
            continue

        source_fbx = _models_relative_name(mesh_path)
```

Then find the counter initialisation:

```python
    skipped_low_bone_count = 0
```

Replace with:

```python
    skipped_low_bone_count = 0
    skipped_non_fbx_mesh = 0
```

And after the existing `if skipped_low_bone_count:` logging block, add:

```python
    if skipped_non_fbx_mesh:
        logger.debug(
            "Skipped %d prefab(s) whose mesh is not an FBX (Sidekick-style "
            "baked meshes; see sidekick.py)",
            skipped_non_fbx_mesh,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_character_definitions.py -q`
Expected: PASS — including the existing `test_unresolvable_mesh_guid_yields_empty_source_fbx`, which is unaffected because an empty `mesh_path` skips the guard.

- [ ] **Step 5: Verify against real packs**

Run:

```bash
python -c "
from unity_package import extract_unitypackage
from prefab_parser import build_character_definitions
from pathlib import Path
for p in ['SIDEKICK_Fantasy_Knights_Unity_2021_3_v1_0_7', 'POLYGON_Dungeon_Unity_2021_3_v1_9_5']:
    gm = extract_unitypackage(Path(rf'C:\Users\Justin\Downloads\{p}.unitypackage'))
    print(p, '->', len(build_character_definitions(gm)), 'definitions')
"
```

Expected: Sidekick `-> 0 definitions` (was 10 bogus), POLYGON_Dungeon `-> 32 definitions` (unchanged).

- [ ] **Step 6: Commit**

```bash
git add prefab_parser.py tests/test_character_definitions.py
git commit -m "fix: skip character definitions whose mesh is not an FBX"
```

---

### Task 6: Wire recipe building into the pipeline

**Files:**
- Modify: `converter.py` — imports, Step 10 block around line 2677

**Interfaces:**
- Consumes: `build_sidekick_recipes(guid_map, source_dirs, models_dir)` and `write_sidekick_characters_json(recipes, output_path)` from Task 3.
- Produces: `PackName/sidekick_characters.json` on disk.

- [ ] **Step 1: Add the import**

In `converter.py`, find the import block containing `build_character_definitions,` and `write_character_definitions_json,`. After that block, add:

```python
from sidekick import (
    build_sidekick_recipes,
    write_sidekick_characters_json,
)
```

- [ ] **Step 2: Build and write recipes in Step 10**

In `converter.py`, find:

```python
                        char_defs = build_character_definitions(guid_map)
                        if char_defs:
                            write_character_definitions_json(
                                char_defs, pack_output_dir / "character_definitions.json"
                            )
                            logger.info("Wrote %d character definition(s)", len(char_defs))
```

Add immediately after:

```python
                        # Sidekick packs ship characters as .sk recipes naming
                        # one part FBX per body slot. Resolution scans the
                        # pack's models/ directory, which Step 9 has already
                        # populated - package asset paths would not match,
                        # because copy_fbx_files() rewrites them.
                        sk_recipes = build_sidekick_recipes(
                            guid_map,
                            [config.source_files],
                            pack_output_dir / "models",
                        )
                        if sk_recipes:
                            write_sidekick_characters_json(
                                sk_recipes,
                                pack_output_dir / "sidekick_characters.json",
                            )
                            logger.info(
                                "Wrote %d Sidekick character recipe(s)",
                                len(sk_recipes),
                            )
```

- [ ] **Step 3: Verify the module imports cleanly**

Run: `python -c "import converter"`
Expected: no output, exit 0

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (95 tests)

- [ ] **Step 5: Verify end to end on a real pack**

Run:

```bash
python converter.py \
  --unity-package "C:/Users/Justin/Downloads/SIDEKICK_Fantasy_Knights_Unity_2021_3_v1_0_7.unitypackage" \
  --source-files "D:/Unity Projects/AEGIS/Assets/Synty/SidekickCharacters" \
  --output "D:/GameAssets/Godot/Synty/tests" \
  --godot "C:/Users/Justin/Documents/git_repos/godot-bin/Godot_v4.7.2-stable_win64_console.exe" \
  --skip-godot-cli
```

Expected: a log line `Wrote 10 Sidekick character recipe(s)`, and
`D:/GameAssets/Godot/Synty/tests/SIDEKICK_Fantasy_Knights/sidekick_characters.json`
exists with 10 entries, each carrying resolved `fbx` paths.

- [ ] **Step 6: Commit**

```bash
git add converter.py
git commit -m "feat: write sidekick_characters.json during conversion"
```

---

### Task 7: Assemble Sidekick characters in Godot

**Files:**
- Modify: `godot_converter.gd` — `process_pack_folder()`, plus two new functions

**Interfaces:**
- Consumes: `sidekick_characters.json` from Task 6; existing `_find_skeleton()`, `_bind_animation_libraries(player, skel)`, `_get_mesh_subfolder()`, `_ensure_directory_exists()`, `_report_error()`, `_report_warning()`, `characters_saved`, `meshes_saved`, `config_filter_pattern`, `config_mesh_format`, `config_mesh_scale`, `current_pack_folder`.
- Produces: one `.tscn` per recipe in `meshes/<format>_<mode>/`.

- [ ] **Step 1: Call the new pass from `process_pack_folder`**

In `godot_converter.gd`, find the end of `process_pack_folder()`:

```gdscript
	for i in range(fbx_files.size()):
		var fbx_path := fbx_files[i]
		print("[%d/%d] Processing: %s" % [i + 1, total_fbx, fbx_path.get_file()])
		process_fbx_file(fbx_path)
```

Add immediately after:

```gdscript

	# Sidekick characters span many FBX, so they cannot be built inside the
	# per-FBX loop above the way POLYGON characters are. They get their own
	# pack-level pass, driven by sidekick_characters.json.
	build_sidekick_characters(pack_folder)
```

- [ ] **Step 2: Add the loader**

Add at the end of `godot_converter.gd`:

```gdscript
## Builds every Sidekick character described by sidekick_characters.json.
##
## Absence of the file is normal - only SIDEKICK packs carry recipes.
##
## @param pack_folder Resource path to the pack folder.
func build_sidekick_characters(pack_folder: String) -> void:
	var path := pack_folder + "/sidekick_characters.json"
	if not FileAccess.file_exists(path):
		return

	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		_report_warning("Failed to open %s" % path)
		return

	var json := JSON.new()
	if json.parse(file.get_as_text()) != OK:
		_report_error("Failed to parse sidekick_characters.json: %s" % json.get_error_message())
		return

	var data = json.data
	if not data is Dictionary:
		_report_error("Invalid sidekick_characters.json: expected Dictionary")
		return

	print("  Loaded %d Sidekick character recipe(s)" % data.size())
	for name in data:
		if not config_filter_pattern.is_empty() and not String(name).containsn(config_filter_pattern):
			continue
		_build_sidekick_character(pack_folder, String(name), data[name])
```

- [ ] **Step 3: Add the assembler**

Add at the end of `godot_converter.gd`:

```gdscript
## Assembles one Sidekick character: every part mesh onto a single skeleton.
##
## Sidekick ships a character as one FBX per body slot, all skinned to the same
## rig, so the character is rebuilt by copying each part's mesh onto one
## skeleton taken from the first part.
##
## @param pack_folder Resource path to the pack folder.
## @param char_name Character name, used for the scene and material.
## @param recipe Dictionary with "parts" and "color_map".
## @returns bool True if a scene was saved.
func _build_sidekick_character(pack_folder: String, char_name: String, recipe: Dictionary) -> bool:
	var parts: Array = recipe.get("parts", [])
	if parts.is_empty():
		_report_error("    ERROR: Sidekick character %s has no parts" % char_name)
		return false

	if String(recipe.get("color_map", "")).is_empty():
		_report_warning("    WARNING: %s has no colour palette; it will be untextured" % char_name)

	var root := Node3D.new()
	root.name = char_name
	var skel: Skeleton3D = null
	var placed := 0

	for entry in parts:
		var part: Dictionary = entry
		var relative := String(part.get("fbx", ""))
		if relative.is_empty():
			_report_warning("    WARNING: %s part %s has no FBX; skipping" % [
				char_name, String(part.get("mesh", "?"))])
			continue

		var fbx_path := "%s/models/%s.fbx" % [pack_folder, relative]
		var packed: PackedScene = load(fbx_path)
		if packed == null:
			_report_warning("    WARNING: %s could not load part %s" % [char_name, fbx_path])
			continue
		var instance := packed.instantiate()

		if skel == null:
			# The first part donates the skeleton. duplicate() preserves bone
			# rests exactly; its children are the donor's own meshes, which the
			# loop below re-adds deliberately.
			var source_skel := _find_skeleton(instance)
			if source_skel == null:
				_report_warning("    WARNING: %s part %s has no Skeleton3D" % [char_name, relative])
				instance.free()
				continue
			skel = source_skel.duplicate() as Skeleton3D
			if skel == null:
				_report_error("    ERROR: could not duplicate skeleton for %s" % char_name)
				instance.free()
				root.free()
				return false
			for child in skel.get_children():
				skel.remove_child(child)
				child.queue_free()
			skel.name = "Skeleton3D"
			root.add_child(skel)

		for mesh_instance in find_mesh_instances(instance):
			if mesh_instance.skin == null or mesh_instance.mesh == null:
				continue
			var copy := MeshInstance3D.new()
			copy.mesh = mesh_instance.mesh
			copy.name = "%s_%s" % [String(part.get("slot", "Part")), mesh_instance.name]
			for surface in range(mesh_instance.mesh.get_surface_count()):
				copy.set_surface_override_material(surface, mesh_instance.get_active_material(surface))
			skel.add_child(copy)
			# skin binds to the skeleton only once the node is inside the tree.
			# Assigning it before add_child() leaves the part frozen in bind
			# pose while the skeleton animates - a silent, visible failure.
			copy.skeleton = copy.get_path_to(skel)
			copy.skin = mesh_instance.skin
			placed += 1

		instance.free()

	if skel == null or placed == 0:
		_report_error("    ERROR: Sidekick character %s produced no meshes" % char_name)
		root.free()
		return false

	_apply_sidekick_material(pack_folder, char_name, skel)

	var player := AnimationPlayer.new()
	player.name = "AnimationPlayer"
	root.add_child(player)
	_bind_animation_libraries(player, skel)

	# Scale belongs on the root: baking it into skinned vertices while leaving
	# bone rests untouched breaks the bind pose.
	if config_mesh_scale != 1.0:
		root.scale = Vector3.ONE * config_mesh_scale

	_set_owner_recursive(root, root)

	var meshes_dir := current_pack_folder + "/meshes/" + _get_mesh_subfolder()
	var output_path := "%s/%s.%s" % [meshes_dir, char_name, config_mesh_format]
	_ensure_directory_exists(output_path.get_base_dir())

	var bone_count := skel.get_bone_count()

	var scene := PackedScene.new()
	if scene.pack(root) != OK:
		_report_error("    ERROR: failed to pack Sidekick scene: %s" % char_name)
		root.free()
		return false

	var save_result := ResourceSaver.save(scene, output_path)
	root.free()

	if save_result != OK:
		_report_error("    ERROR: failed to save Sidekick scene: %s" % char_name)
		return false

	print("      Saved Sidekick character: %s (%d parts, %d bones)" % [
		char_name, placed, bone_count])
	characters_saved += 1
	meshes_saved += 1
	return true


## Applies the character's own material to every assembled part.
##
## Sidekick colours a whole character from one baked 32x32 palette that all its
## parts' UVs index into, so every part takes the same material.
##
## @param pack_folder Resource path to the pack folder.
## @param char_name Character name; the material shares it.
## @param skel Skeleton whose MeshInstance3D children receive the material.
func _apply_sidekick_material(pack_folder: String, char_name: String, skel: Skeleton3D) -> void:
	var material_path := "%s/materials/%s.tres" % [pack_folder, char_name]
	if not ResourceLoader.exists(material_path):
		_report_warning("    WARNING: no material for Sidekick character %s" % char_name)
		return
	var material: Material = load(material_path)
	if material == null:
		_report_warning("    WARNING: could not load material for %s" % char_name)
		return
	for child in skel.get_children():
		if not (child is MeshInstance3D):
			continue
		var mesh_instance := child as MeshInstance3D
		if mesh_instance.mesh == null:
			continue
		for surface in range(mesh_instance.mesh.get_surface_count()):
			mesh_instance.set_surface_override_material(surface, material)
```

- [ ] **Step 4: Check the script parses**

Run:

```bash
"C:/Users/Justin/Documents/git_repos/godot-bin/Godot_v4.7.2-stable_win64_console.exe" --headless --check-only --script godot_converter.gd --path .
```

Expected: exit 0, no parse errors.

- [ ] **Step 5: Convert a Sidekick pack end to end**

Run:

```bash
python converter.py \
  --unity-package "C:/Users/Justin/Downloads/SIDEKICK_Fantasy_Knights_Unity_2021_3_v1_0_7.unitypackage" \
  --source-files "D:/Unity Projects/AEGIS/Assets/Synty/SidekickCharacters" \
  --output "D:/GameAssets/Godot/Synty/tests" \
  --godot "C:/Users/Justin/Documents/git_repos/godot-bin/Godot_v4.7.2-stable_win64_console.exe"
```

Expected: the summary reports `Characters: 10 rigged` (previously absent, meaning zero). Each `meshes/tscn_separate/FantasyKnights_0*.tscn` contains a `Skeleton3D` with 88 bones and ~34 `MeshInstance3D` children.

- [ ] **Step 6: Commit**

```bash
git add godot_converter.gd
git commit -m "feat: assemble Sidekick characters from part meshes in Godot"
```

---

### Task 8: Verify visually and document

**Files:**
- Modify: `README.md` — "Characters and Animations" section
- Modify: `CLAUDE.md` — "Characters and animations" section

**Interfaces:**
- Consumes: everything above.
- Produces: no code interface.

- [ ] **Step 1: Render an assembled character**

Create `D:/GameAssets/Godot/Synty/tests/verify_sidekick.gd`:

```gdscript
extends Node3D
## Renders one converted Sidekick character mid-animation for visual checking.

const CHARACTER := "res://SIDEKICK_Fantasy_Knights/meshes/tscn_separate/FantasyKnights_05.tscn"
const CLIP := "res://ANIMATION_Sword_Combat/models/Animations/Sidekick/Attack/HeavyCombo01/A_MOD_SWD_Attack_HeavyCombo01A_Neut.fbx"
var frames := 0

func _find(n: Node, t: String) -> Node:
	if n.is_class(t): return n
	for c in n.get_children():
		var r := _find(c, t)
		if r != null: return r
	return null

func _ready() -> void:
	var e := Environment.new()
	e.background_mode = Environment.BG_SKY
	e.sky = Sky.new(); e.sky.sky_material = ProceduralSkyMaterial.new()
	e.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	var we := WorldEnvironment.new(); we.environment = e; add_child(we)
	var sun := DirectionalLight3D.new(); sun.rotation_degrees = Vector3(-45, -35, 0); add_child(sun)
	var cam := Camera3D.new(); cam.position = Vector3(0, 1.05, 2.4); cam.rotation_degrees = Vector3(-6, 0, 0); add_child(cam)

	var inst := (load(CHARACTER) as PackedScene).instantiate() as Node3D
	add_child(inst)
	var skel := _find(inst, "Skeleton3D") as Skeleton3D
	print("bones=%d parts=%d" % [skel.get_bone_count(), skel.get_child_count()])

	var ci := (load(CLIP) as PackedScene).instantiate()
	var ap := _find(ci, "AnimationPlayer") as AnimationPlayer
	var a := (ap.get_animation(ap.get_animation_list()[0]) as Animation).duplicate(true) as Animation
	ci.free()
	a.loop_mode = Animation.LOOP_LINEAR
	var sp := String(inst.get_path_to(skel))
	for tr in a.get_track_count():
		a.track_set_path(tr, NodePath("%s:%s" % [sp, String(a.track_get_path(tr).get_concatenated_subnames())]))
	var p := AnimationPlayer.new(); inst.add_child(p)
	p.root_node = p.get_path_to(inst)
	var lib := AnimationLibrary.new(); lib.add_animation("c", a)
	p.add_animation_library("", lib); p.play("c")

func _process(_d: float) -> void:
	frames += 1
	if frames == 110:
		get_viewport().get_texture().get_image().save_png("user://verify_sidekick.png")
		print("saved -> %s" % ProjectSettings.globalize_path("user://verify_sidekick.png"))
		get_tree().quit()
```

Create `D:/GameAssets/Godot/Synty/tests/verify_sidekick.tscn`:

```
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://verify_sidekick.gd" id="1"]

[node name="VerifySidekick" type="Node3D"]
script = ExtResource("1")
```

Run:

```bash
"C:/Users/Justin/Documents/git_repos/godot-bin/Godot_v4.7.2-stable_win64_console.exe" \
  --path "D:/GameAssets/Godot/Synty/tests" --resolution 800x700 res://verify_sidekick.tscn
```

Expected: `bones=88 parts=34`, a PNG is written. Open it. The character must be **textured** (not white) and posed mid-swing with no shattered or detached geometry. A white character means `_ColorMap` did not reach the material (Task 4); a T-posed one means `skin` was assigned before `add_child` (Task 7).

- [ ] **Step 2: Delete the throwaway verification files**

```bash
rm -f "D:/GameAssets/Godot/Synty/tests/verify_sidekick.gd" \
      "D:/GameAssets/Godot/Synty/tests/verify_sidekick.tscn" \
      "D:/GameAssets/Godot/Synty/tests/verify_sidekick.gd.uid"
```

- [ ] **Step 3: Document in README.md**

In `README.md`, at the end of the "Characters and Animations" section (after the rig-families table and the sentence "Characters built on the canonical rig bind and animate correctly."), add:

```markdown
### Sidekick packs

`SIDEKICK_*` packs are a modular character creator rather than a set of finished
characters. A character is a recipe - a plain-text `.sk` file naming one part
mesh per body slot, all sharing one 88-bone rig - and the converter rebuilds it
by assembling those parts onto a single skeleton:

```
FantasyKnights_05 <Node3D>
  Skeleton3D                          # 88 bones
    Head_...        <MeshInstance3D>  # one per body slot
    Torso_...       <MeshInstance3D>
    ...                               # ~34 parts
  AnimationPlayer
```

Recipes are read from the `.unitypackage` and from `--source-files`, so
characters you build with the Sidekick tool and save into your Unity project
convert too. The resolved recipe is written to `PackName/sidekick_characters.json`.

Colour comes from the 32x32 palette the pack bakes per character
(`T_<Name>ColorMap.png`), which every part's UVs index into.

Sidekick rigs need no retargeting: their bone names, order and rests already
match the Sidekick animation clips, so `--animations` binds them directly.
```

- [ ] **Step 4: Document in CLAUDE.md**

In `CLAUDE.md`, in the "Characters and animations" section, add after the
`source_fbx` bullet:

```markdown
- **Sidekick packs take a different path entirely** - `sidekick.py` parses `.sk`
  recipes and `build_sidekick_characters()` assembles one `MeshInstance3D` per
  body slot onto a shared skeleton. Their prefabs point at a Unity-baked
  `.asset` mesh Godot cannot import, so the prefab route yields nothing and is
  suppressed. Two traps: `.sk` files are CRLF, and a part's `skin` must be
  assigned *after* `add_child()` or it stays in bind pose while the skeleton
  animates
```

Also update the test count line:

```markdown
Tests: `python -m pytest tests/ -q` (95 tests, no Godot or package needed).
```

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (95 tests)

- [ ] **Step 6: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document Sidekick character assembly"
```

---

## Completion

After Task 8, use superpowers:finishing-a-development-branch to verify the suite, present integration options, and clean up.

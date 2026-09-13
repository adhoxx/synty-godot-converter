# Sidekick Character Assembly — Design

**Date:** 2026-09-12
**Status:** Approved, not yet implemented
**Related:** `docs/superpowers/research/2026-09-12-godot-retargeting-spike.md`

## Problem

Converting a `SIDEKICK_*` pack today produces **zero rigged characters**, silently.
Measured on `SIDEKICK_Fantasy_Knights`: 1,051 meshes converted, 0 characters, no
error.

The cause is structural. POLYGON packs ship each character as one FBX containing
its body mesh and rig, and `build_character_definitions()` reads that mapping out
of the character prefab. Sidekick is a **modular character creator**: the prefab's
`SkinnedMeshRenderer` points at a mesh Unity baked at author time —
`FantasyKnights_01.asset` — not at any FBX. `_models_relative_name()` only strips
`.fbx`, so `source_fbx` becomes the literal string `"FantasyKnights_01.asset"`,
which matches no FBX, so no character is ever built and nothing reports a problem.

What the pack *does* ship is everything needed to rebuild the character:

- **`.sk` recipes** — one per character, plain text, listing one mesh per body slot.
- **The part FBX themselves** — every part referenced by every recipe is present
  (verified across all 8 Starter and all 10 Fantasy Knights recipes).
- **A baked 32x32 RGB palette** per character (`T_<Name>ColorMap.png`), which the
  parts' UVs index into.
- **A character material** (`<Name>.mat`) referencing that palette as `_ColorMap`.

All parts share one 88-bone rig, and that rig already agrees with the Sidekick
animation clips — same bone names, same order, matching rest origins. No
retargeting is required, unlike the POLYGON family. A prototype assembled
`FantasyKnights_05` from its recipe (34 parts, 88-bone skeleton) and played a
Sidekick sword attack with 90 of 91 tracks resolving and clean deformation.

## Goals

1. Convert Sidekick packs into rigged, animatable Godot character scenes.
2. Use the shipped palette so characters are correctly coloured.
3. Pick up characters the user authored with the Sidekick tool and saved into
   their Unity project, not only the samples Synty ships.
4. Leave the POLYGON character path untouched.

## Non-goals

- **Baking the palette from `ColorRows`.** Each `.sk` carries ~200 `ColorRows`
  entries the Synty tool bakes into the 32x32 PNG. The baked PNG ships, so
  reproducing the bake buys only recolouring, which nobody has asked for.
- **Merging a character's parts into one mesh.** Parts stay separate: faithful to
  the source, and they can be swapped or hidden at runtime. Costs ~34 draw calls
  per character.
- **The downloaded Sidekick tool and its database.**
  `Scripts/Editor/Utility/ToolDownloader.cs` fetches `Sidekicks.unitypackage` and
  `SidekicksDatabase.unitypackage` from GitHub at editor time. We never need them:
  the `.sk` recipes are self-describing.
- **`Characters/<Set>/partsLayouts`** — an empty directory in the packs examined.

## The `.sk` format

Plain text, **CRLF line endings**, YAML-shaped but not parsed as YAML:

```
Name: HumanSpecies_01
Species: 1
Parts:
- Name: SK_HUMN_BASE_01_01HEAD_HU01
  PartType: Head
  PartVersion: 1
- Name: SK_HUMN_BASE_01_10TORS_HU01
  PartType: Torso
  PartVersion: 1
ColorSet:
  Species: 1
  Name: Custom
  SourceColorPath: Assets/Synty/Tools/.../T_ColorMap.png
ColorRows:
- ColorProperty: 1
  MainColor: FCC19C
  Metallic: FF0000
```

Only `Name`, `Species`, and the `Parts` list are consumed. `ColorSet` and
`ColorRows` are ignored — they describe the bake we are not reproducing.

Parsing uses targeted regex rather than a YAML parser, matching the choice
`prefab_parser.py` already made for Unity YAML. The CRLF endings matter: a pattern
written as `^- Name: (\S+)\n` matches **zero** parts and fails silently. Every
pattern must tolerate `\r?\n`.

Recipes observed: 23-36 parts each. Slot names are `PartType` values such as
`Head`, `Torso`, `ArmUpperLeft`, `HandRight`, `AttachmentShoulderLeft`,
`FacialHair`, `Teeth`, `Tongue`.

## Architecture

```
.unitypackage + --source-files
  |
  +-- sidekick.py
  |     find *.sk  ->  parse  ->  SidekickRecipe(name, species, parts[slot, mesh])
  |     resolve each part mesh name  ->  models-relative FBX path
  |     resolve palette              ->  T_<Name>ColorMap
  |     writes  PackName/sidekick_characters.json
  |
  +-- godot_converter.gd
        process_pack_folder()
          +-- per-FBX loop                  (unchanged)
          +-- build_sidekick_characters()   -> one .tscn per recipe
```

### Why a separate pass, not an extension of the existing one

`build_character_scene()` is called from inside `process_fbx_file()`, because a
POLYGON character is wholly contained in the FBX currently being processed. A
Sidekick character draws from ~34 different FBX, so it cannot hook there. It runs
as a pack-level pass after the per-FBX loop, reading its own file.

Keeping `sidekick_characters.json` separate from `character_definitions.json` is
deliberate. The two describe genuinely different shapes — one mesh from one FBX
versus many meshes from many FBX — and overloading one contract would put the
working POLYGON path at risk for no gain.

## Components

### `sidekick.py` (new)

```python
@dataclass
class SidekickPart:
    slot: str          # PartType, e.g. "Torso"
    mesh: str          # part name, e.g. "SK_FANT_KNGT_17_10TORS_HU01"
    fbx: str = ""      # models-relative path without extension; "" if unresolved

@dataclass
class SidekickRecipe:
    name: str
    species: int = 0
    parts: list[SidekickPart] = field(default_factory=list)
    color_map: str = ""   # texture basename, "" if the pack ships none

def parse_sk_bytes(data: bytes) -> SidekickRecipe | None
def build_sidekick_recipes(
    guid_map, source_dirs: list[Path], models_dir: Path
) -> dict[str, SidekickRecipe]
def write_sidekick_characters_json(recipes, output_path: Path) -> None
```

**Part resolution resolves against `models_dir`, not the package.** `models_dir` is
the pack's *output* `models/` directory, which Step 9 has already populated by the
time character definitions are built in Step 10. This matters: the package's own
asset paths and the output layout are not the same — `copy_fbx_files()` strips
`SourceFiles`/`FBX`/`Models` prefixes — and only the output layout is what the
Godot side will later join to `models/`. Resolving against package paths would
produce paths that do not exist on disk.

Part names are long and globally unique (`SK_FANT_KNGT_17_10TORS_HU01`), so a part
is resolved by FBX basename across a recursive scan of `models_dir`, yielding the
path relative to it without extension. This is the same `source_fbx` convention the
POLYGON path uses, for the same reason. If a basename resolves to more than one FBX
the first is taken and a warning is emitted — Sidekick names have not been observed
to collide, and a silent wrong pick is a failure this repo has already been bitten
by once.

With `--skip-fbx-copy`, `models/` may still hold FBX from an earlier run and
resolution proceeds normally. If it is empty, no part resolves, and the recipe is
reported rather than written.

**Palette resolution.** `T_<Name>ColorMap` if the pack ships a texture by that
name, else empty.

### `unity_package.py`

Extract `.sk` contents through the existing
`_extract_contents_by_extension(guid_data, guid_to_pathname, ".sk")`, exposed as
`GuidMap.guid_to_sk_content`. No new extraction machinery.

### `shader_mapping.py`

Add `"_ColorMap": "base_texture"` to the texture property map.

This is why the prototype character rendered white. The map already carries
`_MainTex`, `_BaseMap`, `_Base_Texture`, `_Texture`, `_Albedo_Map` and
`_MainTexture`, but not Sidekick's `_ColorMap`, so the palette was never attached
to the generated material and the texture-copy step never pulled the PNG. Measured
on `SIDEKICK_Fantasy_Knights`: 10 materials generated, **0 textures copied**, and
`materials/FantasyKnights_05.tres` contains no texture reference at all.

### `prefab_parser.py`

`build_character_definitions()` skips any prefab whose `m_Mesh` resolves to
something that is not an FBX, logging at debug level.

Sidekick prefabs currently yield definitions with `source_fbx` values like
`"FantasyKnights_01.asset"`. These can never match an FBX, so they do nothing
except sit in `character_definitions.json` misrepresenting what was found. This
also stops the two subsystems from both claiming the same characters.

### `converter.py`

Alongside the existing `build_character_definitions()` call, in **Step 10**. That
placement is required, not incidental: Step 9 copies the FBX into `models/`, and
part resolution scans that directory.

- Build recipes from `guid_map` **and** from `.sk` files found under
  `--source-files`, so characters authored with the Sidekick tool and saved into
  the user's Unity project convert too. A source-files recipe wins over a package
  recipe of the same name, being the more likely edit.
- Write `sidekick_characters.json` into the pack folder when any recipe resolved at
  least one part. Absence of the file means "no Sidekick characters here", the same
  convention `character_definitions.json` uses.
- Log the count at info level.

### `godot_converter.gd`

`build_sidekick_characters(pack_folder)`, called from `process_pack_folder()` after
the per-FBX loop, and only when `sidekick_characters.json` exists.

Per recipe:

1. Load the first resolvable part FBX; take its `Skeleton3D`, `duplicate()` it and
   free the copy's children. Duplicating preserves bone rests exactly — the same
   approach `build_character_scene()` uses.
2. For each part: instantiate its FBX, find the skinned `MeshInstance3D`, and add a
   fresh `MeshInstance3D` under the skeleton carrying the same mesh and materials.
   Name it `<Slot>_<MeshName>`.
3. **Assign `skeleton` and `skin` after `add_child()`.** Setting `skin` while the
   node is outside the tree leaves every part frozen in bind pose while the skeleton
   animates — a silent failure that renders as a T-posed character.
4. Apply `materials/<Name>.tres` as a surface override on every part, so all parts
   share the character's palette.
5. Add an `AnimationPlayer` and run the existing `_bind_animation_libraries()` gate
   unchanged. Sidekick rigs measure 90 of 91 tracks resolving, comfortably above the
   90% threshold, and their rests already agree with the clips.
6. Pack and save one scene per character into the configured mesh subfolder;
   increment `characters_saved`.

Scene shape:

```
FantasyKnights_05 <Node3D>
  Skeleton3D                          # 88 bones
    Head_...        <MeshInstance3D>  # skin preserved
    Torso_...       <MeshInstance3D>
    ...                               # ~34 parts
  AnimationPlayer
```

`config_filter_pattern` applies to the recipe name, matching how the POLYGON path
filters definition names.

## Error handling

| Condition | Response |
|---|---|
| Part has no resolvable FBX | `_report_warning`, skip the part, keep building. Real: 1 of ~34 parts missing in 4 of 10 Fantasy Knights recipes, the part living in another pack. |
| No part resolves at all | `_report_error`, skip the character. |
| First part has no `Skeleton3D` | `_report_error`, skip the character. |
| No `color_map` for the recipe | `_report_warning`; the character converts untextured. |
| `materials/<Name>.tres` absent | `_report_warning`; parts keep their FBX materials. |

Everything routes through `_report_error` / `_report_warning` so counts and texts
reach the Python summary through `GODOT_SUMMARY`. A pack that converts zero
Sidekick characters must say so — the current silent zero is the defect that
motivated this work.

## Testing

`tests/test_sidekick.py`, no Godot and no package required:

- `parse_sk_bytes` on a CRLF fixture returns name, species and every part in order
- an LF fixture parses identically, so the parser is not accidentally CRLF-only
- a `.sk` with no `Parts:` block yields no recipe rather than an empty one
- part resolution maps a part name to its models-relative path
- an unresolvable part leaves `fbx` empty and keeps the rest of the recipe
- duplicate basenames take the first and warn
- `color_map` resolves to `T_<Name>ColorMap` when present, empty when not
- a source-files recipe overrides a package recipe of the same name
- `write_sidekick_characters_json` emits the documented shape

`tests/test_character_definitions.py` gains a regression test: a prefab whose mesh
GUID resolves to a `.asset` produces no character definition.

The Godot side has no automated test, consistent with the rest of the repo. It is
verified by converting `SIDEKICK_Fantasy_Knights` and rendering an assembled
character mid-animation, checking that it is textured and deforms cleanly.

## Output contract

`PackName/sidekick_characters.json`:

```json
{
  "FantasyKnights_05": {
    "species": 1,
    "color_map": "T_FantasyKnights_05ColorMap",
    "parts": [
      {
        "slot": "Head",
        "mesh": "SK_HUMN_BASE_01_01HEAD_HU01",
        "fbx": "Resources/Meshes/Species/Humans/SK_HUMN_BASE_01_01HEAD_HU01"
      }
    ]
  }
}
```

`fbx` is relative to the pack's `models/` directory and carries no extension. An
empty `fbx` marks a part that could not be resolved; the Godot side skips it with a
warning rather than failing the character.

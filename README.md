# Synty Unity-to-Godot Converter

Convert Synty Studios Unity asset packs (`.unitypackage` files) to Godot 4.6 with full shader support, automatic material conversion, and FBX mesh processing.

**Version 2.4** - Output subfolder organization, retain source directory structure.

## Features

- **Full material conversion** - Parses Unity `.mat` files and generates Godot `ShaderMaterial` `.tres` files
- **3-tier shader detection** - GUID lookup (56 known shaders), name pattern matching, property-based analysis
- **7 Godot shaders** - Polygon, Foliage, Crystal, Water, Clouds, Particles, Skydome
- **FBX mesh conversion** - Imports FBX models via Godot CLI with materials pre-assigned
- **Texture handling** - Extracts textures from `.unitypackage` with fallback to SourceFiles
- **Modern GUI** - CustomTkinter interface with real-time logging, progress display, and settings persistence
- **Global shader uniforms** - Generates `project.godot` with wind, sky, and water parameters
- **Recursive folder discovery** - Finds FBX files in nested pack structures automatically
- **Project merging** - Merges `project.godot` settings for multi-pack workflows
- **LOD inheritance** - Consistent shader detection across LOD levels
- **Smart filtering** - When using `--filter`, only copies textures and materials needed by filtered FBX files
- **High quality texture compression** - Optional BPTC compression for improved texture quality
- **Per-pack isolation** - Each pack gets its own folder with `mesh_material_mapping.json` for targeted processing
- **Dynamic shader discovery** - Finds existing shaders in your project before copying duplicates
- **Clean FBX paths** - Strips `SourceFiles/FBX/Models` prefixes for cleaner output structure
- **Comprehensive fallback matching** - Name variations, prefix swaps, and fuzzy matching (Levenshtein) for materials
- **Output subfolder organization** - Organize converted packs into custom subfolders with `--output-subfolder`
- **Retain source structure** - Preserve `Source_Files/FBX/` subdirectory structure in mesh output with `--retain-subfolders`

## Convert your whole library

One command turns a folder of `.unitypackage` files into a Godot project with
meshes, materials, characters, animations, UI sprites and a runtime for swapping
Sidekick character parts:

```bash
python synty_library.py     --packages "C:/Users/me/Downloads"     --godot "C:/Godot/Godot_v4.6-stable_win64_console.exe"     --output "C:/Godot/Projects/synty"
```

| Flag | Required | What it is |
|------|----------|------------|
| `--packages` | yes | The folder holding your `.unitypackage` files |
| `--godot` | yes | Godot's **console** executable - the plain `.exe` on Windows writes nothing to a pipe, so progress and errors go blank |
| `--output` | yes | The Godot project to build. It need not exist |
| `--unity-assets` | no | A Unity project's `Assets/Synty`, if you happen to have the packs imported there |
| `--work-dir` | no | Where to stage FBX read out of packages. Defaults beside `--output` |
| `--no-retarget` | no | Skip rig retargeting. Characters still convert; clips no longer bind to them |
| `--only`, `--force`, `--dry-run` | no | Narrow the run, re-convert what exists, or print the routing and stop |

**No Unity install is needed.** Without `--unity-assets` every pack is read
straight out of its `.unitypackage`, which is all Unity's import does for a mesh.

**Supported character rigs are Polygon and Sidekick**, deliberately. Anything
else - Synty's chibi Mini Fantasy rig, for instance - converts as meshes and
binds no clips. Guessing a bone mapping for an unknown rig produces a mangled
character rather than an unanimated one, so the tool refuses instead.

**Converting a SIDEKICK pack installs `addons/synty_sidekick/`**, the runtime
that assembles modular characters and swaps their parts, gear, proportions and
colours while your game runs. Open
`addons/synty_sidekick/sidekick_viewer.tscn` to browse what your library
produced; see that folder's README to drive it from game code.

The run ends by naming what it could not do: a missing `Side_Kick_Data.db` (which
ships with Synty's Sidekick Unity tool, never inside a `.unitypackage`, and
without which attachment joints do not follow body size and recolouring is
unavailable), and any pack that declared characters and built none. Characters
still assemble, animate and mix by body region without it - point
`--unity-assets` at a Unity project with the Sidekick tool installed to pick the
database up.

## Quick Start

```bash
# CLI (no dependencies required)
# Note: --source-files supports recursive discovery, so you can point to
# the top-level SourceFiles folder even if FBX files are in subdirectories.
python converter.py \
    --unity-package "C:\SyntyComplete\POLYGON_Fantasy\Fantasy.unitypackage" \
    --source-files "C:\SyntyComplete\POLYGON_Fantasy\SourceFiles" \
    --output "C:\Godot\Projects\fantasy-assets" \
    --godot "C:\Godot\Godot_v4.6-stable_mono_win64\Godot_v4.6-stable_mono_win64.exe"

# GUI (requires additional dependencies)
pip install -r requirements-gui.txt
python gui.py
```

## Installation

**Requirements:**
- Python 3.10+
- Godot 4.6 (mono or standard)

**GUI dependencies** (optional):
```bash
pip install -r requirements-gui.txt
```

This installs CustomTkinter for the graphical interface.

## CLI Options

| Flag | Required | Description |
|------|----------|-------------|
| `--unity-package` | Yes | Path to `.unitypackage` file |
| `--source-files` | Yes | Path to SourceFiles folder containing FBX/ (recursive search, Textures/ optional) |
| `--output` | Yes | Output directory for Godot project |
| `--godot` | Yes | Path to Godot 4.6 executable |
| `--dry-run` | No | Preview without writing files |
| `--verbose` | No | Enable debug logging |
| `--skip-fbx-copy` | No | Skip copying FBX files |
| `--skip-godot-cli` | No | Skip Godot CLI (materials only) |
| `--skip-godot-import` | No | Skip Godot import phase (converter script still runs) |
| `--godot-timeout` | No | Godot CLI timeout in seconds (default: 600) |
| `--keep-meshes-together` | No | Keep all meshes from one FBX in a single scene |
| `--mesh-format` | No | Output format: `tscn` (default) or `res` |
| `--filter` | No | Filter pattern for FBX filenames (also filters textures and materials) |
| `--high-quality-textures` | No | Use BPTC compression for higher quality textures |
| `--mesh-scale` | No | Scale factor for mesh output (e.g., `100` for undersized packs) |
| `--output-subfolder` | No | Subfolder path prepended to pack folder names |
| `--retain-subfolders` | No | Preserve Source_Files/FBX/ subdirectory structure in mesh output |
| `--pack-type` | No | `auto` (default), `assets`, or `animations` |
| `--animations` | No | Bind animation libraries to characters: `all` or comma-separated substrings |

## Output Structure

```
output/
  project.godot              # Godot project with global shader uniforms
  shaders/                   # 7 community drop-in shaders
  conversion_log.txt         # Append-mode log for all pack conversions
  PackName/
    textures/                # Extracted textures
    materials/               # Generated .tres ShaderMaterials
    models/                  # Copied FBX files (clean paths, structure preserved)
    meshes/                  # Mesh output organized by configuration
      tscn_separate/         # --mesh-format tscn (default, one file per mesh)
      tscn_combined/         # --mesh-format tscn --keep-meshes-together
      res_separate/          # --mesh-format res (one file per mesh)
      res_combined/          # --mesh-format res --keep-meshes-together
    mesh_material_mapping.json  # Per-pack mesh-to-material mappings
```

**Mesh subfolder naming**: Output goes to `meshes/{format}_{mode}/` based on your options. This allows multiple output configurations to coexist without overwriting each other.

**Multi-pack workflow**: Each pack folder is self-contained with its own `mesh_material_mapping.json`. The `conversion_log.txt` at the project root appends entries from each conversion, making it easy to track multiple pack imports.

**Incremental conversion**: When re-running on a pack that already has `materials/`, `textures/`, `models/`, and `mesh_material_mapping.json`, the converter skips phases 3-10 and only regenerates meshes. This is useful for trying different mesh format/mode combinations without re-processing textures and materials.

## Pipeline Overview

The converter runs a 12-step pipeline:

| Step | Description |
|------|-------------|
| 1 | Validate inputs (package, source files, Godot exe) |
| 2 | Create output directory structure |
| 3 | Extract `.unitypackage` and build GUID maps |
| 4 | Parse Unity `.mat` files |
| 5 | Parse `MaterialList.txt` for mesh-material mappings |
| 6 | Detect shaders via 3-tier system (GUID, name patterns, property analysis) |
| 7 | Generate Godot `.tres` ShaderMaterial files |
| 8 | Copy community shader files (with dynamic path discovery) |
| 9 | Copy textures with smart filtering and fallback resolution |
| 10 | Copy FBX models (clean paths, optional scale) |
| 11 | Generate per-pack `mesh_material_mapping.json` |
| 12 | Run Godot CLI for mesh-to-scene conversion (with fallback matching) |

See [docs/steps/](docs/steps/README.md) for comprehensive step-by-step documentation.

## Supported Shaders

| Shader | Description |
|--------|-------------|
| Polygon | Standard Synty materials (characters, props, buildings) |
| Foliage | Trees, bushes, grass with wind animation |
| Crystal | Transparent/refractive materials |
| Water | Animated water surfaces |
| Clouds | Volumetric cloud rendering |
| Particles | Unlit particle effects |
| Skydome | Sky gradient and sun rendering |

These use community shaders from [GodotShaders.com](https://godotshaders.com) as drop-in replacements.

## Material Matching

The converter uses a comprehensive fallback system to match meshes to materials:

1. **Exact match** - Direct mesh name lookup in `mesh_material_mapping.json`
2. **SK_/SM_ prefix swap** - Tries both prefixes when one fails
3. **Suffix stripping** - Removes `_LOD0`, `_LOD1`, `_Low`, `_High`, etc.
4. **Prefix removal** - Strips `PolygonPack_Mat_` prefixes
5. **Name variations** - Generates all combinations of above transformations
6. **Fuzzy matching** - Levenshtein distance <= 2 as last resort

This handles naming inconsistencies between Unity prefabs and Godot mesh imports.

## Characters and Animations

Skinned meshes convert to rigged Godot scenes rather than static bind-pose
meshes:

```
Character_Goblin_WarChief <Node3D>
  Skeleton3D                                    # 49 bones
    Character_Goblin_WarChief <MeshInstance3D>  # skin preserved
    SM_Item_Goblin_WarBanner <BoneAttachment3D> # equipment on its bone
  AnimationPlayer
```

A prefab counts as a character when it has an active `SkinnedMeshRenderer`
driven by at least 16 bones. The bone threshold matters: Synty skins cloth so
it moves in the wind, so tent covers, flag lines and FX otherwise register as
characters - 33 of 52 on POLYGON_Dungeon_Realms.

Which body mesh and which equipment make up a character is read from the Unity
prefab, which ships with every character in the pack present but all except one
disabled. That mapping is written to `PACK_NAME/character_definitions.json`.

`--mesh-scale` is never baked into skinned vertices - bone rests would keep the
original scale and the bind pose would break - so rigged characters carry scale
on the scene root instead.

### Animation packs

`ANIMATION_*` packages are detected automatically (by the share of FBX under
`Animations/`) and convert to AnimationLibrary resources at
`animations/<Pack>_<Family>.res`, one per rig family. Bind them to characters
with `--animations`:

```bash
python converter.py ... --animations sword_combat,base_locomotion
python converter.py ... --animations all
```

### Rig families, and when binding is refused

Synty uses two incompatible rig families that share **no** bone names -
`Polygon` (PascalCase: `Hips`, `Spine_01`) and `Sidekick` (camelCase: `pelvis`,
`thigh_l`). Libraries are emitted per family, and binding is refused when:

| Condition | Reason |
|-----------|--------|
| Family mismatch | Sidekick clips cannot drive a Polygon character |
| Either rig unidentified | Two unknowns matching is not evidence they agree |
| Bone coverage below 90% | The character uses a rig variant the clips were not authored for |

That last case is real and common. POLYGON_Dungeon's characters use a 49-bone
variant of the canonical 52-bone rig. Binding anyway does not merely mis-pose the
hands - animation tracks apply relative to bone rests, so a variant rig collapses
the character entirely. The converter refuses and names the missing bones. An
unanimated character is recoverable; a silently mangled one is not.

Coverage is measured over the union of every clip in a library. No single clip is
representative - Base Locomotion's first clip is `A_BodyLook_Additive_Neut`, an
additive look touching 6 of the 43 bones the library uses, and sampling only that
one made two missing prop bones read as 67% when the honest figure is 74%.

**Name coverage is necessary but not sufficient, and relaxing it does not work.**
Dark Fantasy's characters differ from the libraries only in props, fingers, eyes
and eyebrows - nine of those being the same hand bones under Godot's duplicate-name
suffix, where the character has `Thumb_01` and the library wants `Thumb_01_1`. Not
one spine, limb, neck or root bone differs. Exempting the detail bones takes every
character to 100% coverage and binds all 857 clips, and the character then collapses
into a flat heap the instant one plays: the head drops from y=1.569 to y=0.852,
level with the hips, while the rest pose in the same scene is a correct A-pose.

The reason is that only four bones in a library carry position tracks. Every other
track is an absolute local *rotation*, not a delta from rest, so a clip poses only
the rig whose rest orientations it was authored against - and bone names carry no
information about rests. This character's hips rest 0.364 from where the clips
assume they are, on a rig 0.876 high.

`tools/render_bound_character.gd` renders a bound character at rest and mid-clip
for exactly this check. Run it without `--headless`; a headless process saves a
blank image.

Characters built on the canonical rig bind and animate correctly.

### Retargeting, and how Polygon characters get animated

`--retarget` rewrites a Polygon character rig *and* the clip rigs onto
`SkeletonProfileHumanoid` at import time, after which they can bind. It is opt-in;
without it nothing changes.

Both sides have to be retargeted, so an animation pack is converted with
`--retarget` before the character packs that bind it. Retargeted clips are saved
as `ANIMATION_<Pack>_Humanoid.res` beside the existing `_Polygon` and `_Sidekick`
libraries rather than replacing them, so nothing that binds today changes.
Sidekick is deliberately untouched: it binds correctly already, and its parts
library resolves, grafts and adjusts bones *by name*.

It costs a second import pass, and that is structural rather than cautious. The
converter never writes FBX `.import` files - Godot generates them - and a
`BoneMap` cannot be written before the file's real bone names are known. So: import,
report each rig, resolve the map, inject it, import again.

**Three things here fail silently, and each one looks like success:**

- `_subresources` must **replace** the empty `_subresources={}` Godot writes into
  every scene `.import`. Appending a second key leaves the empty one winning.
  Writing the options under `[params]` fails differently - Godot drops them on the
  next import.
- `retarget/bone_renamer/unique_node/make_unique` must be **false**. True rewrites
  clip tracks to `%GeneralSkeleton:<bone>` while our characters name their skeleton
  `Skeleton3D`, and Godot skips unresolvable tracks without complaint - so the
  character binds, reports success, and never moves.
- **Side is resolved by position, never by the dedup suffix.** Synty names both
  hands' finger bones identically; Godot dedups the second with an index that
  differs per file (`Thumb_01_2` in a character FBX, `Thumb_01_1` in a clip FBX).
  Each hand is decided once by majority vote of its three chain roots, then that
  suffix applies to the whole chain. Simpler rules fail on real data: the sign of
  the lateral coordinate resolved only 92 of 241 Sword Combat rigs, because death
  and knockdown poses put both hands the same side of the origin, and
  nearest-hand-per-bone reached 105, because a sword grip puts a left fingertip
  closer to the right hand. Chain-root voting resolves 123 of 123.

Once both sides carry profile names, bone-name coverage is meaningless - the names
were assigned by the retargeter and match by construction. A Humanoid pair is gated
on **rest agreement** instead: the mean dot product of corresponding bone rest
directions, measured at 0.997-1.000 for a retargeted pair and ~0 for Synty's raw
rigs. Each library carries its rests in a `.rests.json` sidecar, because an
`AnimationLibrary` holds clips and nothing else. A library without one keeps the
coverage path, so older output does not silently change meaning.

Measured on POLYGON_Dark_Fantasy: all 15 characters bind 122 Sword Combat clips,
and the rendered frame shows the character upright and articulated mid-attack -
head at y=1.435 against a rest of y=1.564, where forcing the old bind put it at
y=0.852, level with the hips. `tools/render_bound_character.gd` does that check;
run it without `--headless`, as a headless process saves a blank image.

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

Parts do not all ship an identical rig: attachments add dynamic bones of their
own (a cape's `abac_dyn_*` chain, a hip pouch's `ahpl_dyn_01`). Those bones are
grafted onto the assembled skeleton, without which the parts carrying them bind
to nothing and render detached from the body.

Recipes are read from the `.unitypackage` and from `--source-files`, so
characters you build with the Sidekick tool and save into your Unity project
convert too.

A pack never imported into Unity has no `--source-files` to point at, but its FBX
are in the `.unitypackage` regardless. `tools/extract_fbx.py` writes them out:

```bash
python tools/extract_fbx.py MyPack.unitypackage /path/outside/your/godot/project/MyPack
```

Keep that directory **outside** any Godot project - Godot imports everything under
its project root. Joint adjustments additionally need `Side_Kick_Data.db`, which
ships with the Unity tool rather than in the package; copy one alongside the
extracted files to get them. The resolved recipe is written to `PackName/sidekick_characters.json`. Joint
adjustments go to `PackName/sidekick_rig_adjustments.json`.

Colour comes from the 32x32 palette the pack bakes per character
(`T_<Name>ColorMap.png`), which every part's UVs index into.

Synty occasionally numbers a recipe with a variant suffix its assets do not carry -
`Starter_01b`'s palette and material both ship as `Starter_01`. An exact name match
is always preferred, with the trimmed name tried only when the pack has no palette
under the character's own name.

Body proportions convert too. Each recipe ends with a `BlendShapes` block -
`BodyTypeValue`, `BodySizeValue`, `MuscleValue`, each a slider value in
-100..100 - and every body part ships the matching shapes. The weights follow
Synty's own `SidekickRuntime.UpdateBlendShapes`:

| Blend shape | Weight |
|---|---|
| `masculineFeminine` | `(BodyTypeValue + 100) / 2` |
| `defaultSkinny` | `-BodySizeValue` when negative, else 0 |
| `defaultHeavy` | `BodySizeValue` when positive, else 0 |
| `*Buff` | `(MuscleValue + 100) / 2` |

Zero is not neutral: a default character sits at 50% on two of the four, so
an unset character renders fully masculine and entirely unmuscled rather than
as authored. Facial and jaw shapes on the same meshes are left alone.

Proportions also move the 11 attachment joints - `backAttach`, `hipAttach_*`,
`shoulderAttach_*`, `elbowAttach_*`, `kneeAttach_*` - so pouches, shoulder pads
and back items keep up with the body instead of floating off a heavy character
or sinking into a skinny one. The per-joint maxima come from Synty's
`Side_Kick_Data.db`, which ships in a Unity project rather than in the
`.unitypackage`, so this applies only when `--source-files` (or, for a whole
library, `--unity-assets`) points at a project with the Sidekick tool installed. Without it the characters still convert; their
gear just keeps the base rig's placement.

Sidekick rigs need no retargeting: their bone names, order and rests already
match the Sidekick animation clips, so `--animations` binds them directly.

#### Interactive viewer

`tools/sidekick_viewer.gd` and `tools/sidekick_viewer.tscn` are a character
customiser for the converted output. Copy both into the output project and run:

```bash
"<godot>" --path "<your converted project>" res://addons/synty_sidekick/sidekick_viewer.tscn
```

It scans every converted `SIDEKICK_*` pack for characters, parts, palettes and
joint adjustments, then lets you swap any of the 38 body slots, drag the three
proportion sliders and play any converted Sidekick clip. Parts can be mixed
across packs - a goblin head on a knight body works, since every Sidekick part
shares the one base rig.

**Sources** filters the parts on offer by the family encoded in each part name -
Fantasy Knights, Goblin Fighters, Zombie (base) and so on. Filtering by output
pack folder would filter nothing, because the folders share one FBX pool. The
filter drives the slot dropdowns, the `<` and `>` buttons that step through a
slot, and Randomise, which only draws from enabled sources. A slot no enabled
source supplies keeps what it is wearing rather than emptying, and the status
line says how many did. The part currently worn always stays listed even when
its family is filtered out, so a dropdown never misreports the character.

**Palette** defaults to `(each part's own)`, which renders every part with the
palette of the character it was authored against. Picking a specific palette
instead forces it onto all of them, which is the right call within one family
but will turn foreign parts bright red: Synty bakes a 32x32 palette per
character and fills the slots that character does not use with pure red, so a
part whose UVs index an unused slot has no colour defined there. The red means
the palette is silent about that part, not that a texture is missing.

The viewer's model is `SidekickCharacter` driven off the shared parts library,
so it holds no assembly logic of its own - no grafting, no blend weights, no
joint adjustment. That means it offers all 1028 parts rather than only those a
shipped recipe happens to use, and it gains two controls the library makes
possible: gear sets split by body region, and the 134 colour presets.

**Character** still loads a shipped recipe, which is now just one `set_part` per
slot. Anything you change afterwards is yours.

Animation clips need an `ANIMATION_*` pack converted into the same project;
the viewer loads every `animations/*_Sidekick.res` it finds.

### The parts library, and equipping gear at runtime

Sidekick models gear as **body-mesh replacement, not attachment**. A knight's
breastplate *is* the torso mesh: `FantasyKnights_01` wears a bare human head
over a knight torso, arms, hands, hips, legs and feet. Measured across the
converted packs, 80 of 109 sets span more than one slot and the largest span 27.
Nothing can be equipped by parenting a prop to a bone, and a wardrobe of
combinations cannot be pre-baked, so equipping means assembling at runtime.

Converting a Sidekick pack therefore writes a shared library at the **output
root**, not inside the pack:

```
<output root>/
  sidekick_parts/
    <PartName>.res               skinned scene: Skeleton3D > MeshInstance3D + skin
    T_SidekickMaster_ColorMap.png
  sidekick_parts.json            slot, family, set, species, bones, blend shapes
  sidekick_gear_sets.json        Synty's 532 curated sets
  sidekick_colors.json           209 colour slots, 134 palette presets
```

It is shared because Sidekick packs ship a common part pool - 5455 part scenes
across the packs, 1339 of them distinct. The pack's own `SK_*.tscn` are no
longer written: they were bare `MeshInstance3D` with no skin and no skeleton, so
nothing could be assembled from them.

`tools/sidekick_character.gd` consumes that library:

```gdscript
var character := SidekickCharacter.new()
add_child(character)
character.load_library("res://")
character.set_base_skeleton(my_skeleton)

character.equip_set("492")                        # head region
character.equip_set("490")                        # upper body
character.equip_set("679")                        # lower body
character.set_base_loadout()                      # this is "unequipped"

character.equip_set("637")                        # Viking upper over a goblin
character.set_part("AttachmentBack", "SK_FANT_KNGT_09_24ABAC_HU01")
character.clear_slot("Torso")                     # back to the base loadout
character.set_proportions(50.0, 40.0, 60.0)       # gear follows the body
character.recolour("Metal 01", Color("c0a068"))   # a rarity tint
```

```gdscript
character.load_animations()                       # every animations/*_Sidekick.res
character.play("A_Base_Locomotion_Idle_Standing_Fem")
character.stop()
```

Clip tracks are addressed `Skeleton3D:<bone>` relative to the player's
`root_node`, so the player is rooted at the character and the skeleton must be
named `Skeleton3D` - which is what the converter writes and what
`create_base_skeleton()` returns.

`set_proportions` drives two layers. Blend shapes reshape the body meshes, and
the 11 attachment joints move with them, so a back banner or hip pouch stays on
a heavy character instead of floating off it. Offsets come from the tool
database, so they need a `--source-files` that carries it; without one the blend
shapes still work and the joints simply stay put. Adjustments go onto bone **poses**, not rests, and are
re-applied every frame after the AnimationPlayer advances. A clip rewrites these
bones every frame, so an offset folded into the rest would simply be discarded
the moment an animation played and the gear would snap back mid-swing.

Use `create_base_skeleton()` rather than seeding from an arbitrary part: 45 of
the parts are small attachments carrying as few as 14 bones, and a character
built on one of those is on a stub rig most skins cannot bind to.

Gear sets come from Synty's own `sk_part_preset`. Its three groups are **body
regions, not layers**: measured across all 532 sets they partition the 38 slots
exactly, 14 + 13 + 11 with no overlap.

| Group | Sets | Slots | Covers |
|-------|------|-------|--------|
| `head` | 250 | 14 | head, eyes, ears, teeth, nose, brows, hair, head and face attachments |
| `upper` | 143 | 13 | torso, arms, hands, back/shoulder/elbow attachments, wrap |
| `lower` | 139 | 11 | hips, legs, feet, hip and knee attachments |

A complete character is one set from each. Because an armoured torso replaces
the bare one outright rather than covering it, there is no naked body to fall
back to - so `set_base_loadout()` nominates the current loadout as "unequipped"
and `clear_slot()` reverts to that.

Colour is a pixel write. Every colour slot has an explicit `(u,v)` in the 32x32
palette, and the groups keep skin (41 slots) separate from outfits (53) and
attachments (65), so recolouring armour never disturbs skin. The master
`T_ColorMap.png` defines all 209, which is what guarantees that an arbitrary mix
of parts has no undefined - that is, bright red - colour slot.

Without a Sidekick tool database, the library still emits gear sets: they are
derived from the family and number in part names and split across the same three
body regions, so the wardrobe mixes normally. They are coarser - tens of sets
rather than the database's 532, and blind to two families sharing a bare torso -
and recolouring is unavailable, because the colour tables and the master palette
both come from the database.

### Re-running a converted pack

A pack that already has `materials/`, `textures/`, `models/` and
`mesh_material_mapping.json` skips straight to mesh generation, which is what
keeps re-runs cheap. `PackName/pack_metadata.json` records which metadata schema
it was converted against: when that is older than the current converter, the
pack regenerates its metadata instead, re-running everything except the FBX copy.
So upgrading the converter and re-running picks up new metadata without a manual
cache clear, and without recopying thousands of FBX.

`--prune-models` deletes a pack's staging FBX once mesh generation succeeds. They
are input, not output: the generated scenes embed their mesh data. On a shared
source pool they are also the same bytes in every pack - pruning the seven Sidekick
packs here reclaimed 2.3 GB of 4.3 GB.

Only the FBX go. Godot's importer extracts a mesh's embedded textures as PNGs
beside it and the scenes reference those by path, so they stay; on a Sidekick pack
that is 15 MB kept against 352 MB reclaimed. A failed or timed-out conversion is
never pruned, since that would delete the inputs needed to retry. The next run sees
no FBX and re-copies them, so pruning costs a full re-run rather than breaking one.

### Converting a whole library at once

`converter.py` takes one pack per run and has to be told where that pack's meshes
live. `synty_library.py` makes that decision per pack across a folder of
packages - see [Convert your whole library](#convert-your-whole-library) for the
command.

Add `--dry-run` to print each pack and the route it would take without converting
anything. `--only` narrows the run to packages matching a comma-separated list of
substrings.

A pack imported into Unity is pointed at directly; one that never was has its FBX
written out of the `.unitypackage` first, into `--work-dir` (which must sit
outside the Godot project, or Godot imports everything twice - the tool refuses a
work directory inside the output). A pack whose output folder already exists is
skipped, so an interrupted run resumes where it stopped; `--force` re-converts
regardless. Animation packs convert first, because `--animations all` cannot bind
a library that does not exist yet.

Per-pack output goes to `conversion_logs/PackName.log` under the output root,
with a machine-readable roll-up in `conversion_logs/convert_all_results.json`
written after every pack rather than at the end.

**The INTERFACE packs are sprites, not meshes.** Dark Fantasy HUD carries 2205
PNGs and six demo-scene FBX, so the mesh pipeline reports an empty conversion
rather than an error. Those packs take a second route that writes their sprites
to `PackName/ui/`, where Godot imports them as textures without help. The routes
compose, so a UI pack's handful of meshes still convert. The signal is dominance,
not absence: a prop pack's textures are outnumbered by its meshes, a sprite set
outnumbers them tenfold.

## GUI Features

The GUI (`gui.py`) provides:
- Real-time conversion progress with percentage and ETA
- Detailed logging with warning/error highlighting
- **Settings persistence** - Paths and options are saved between sessions
- Dry-run mode for previewing conversions
- **Convert Library** - the whole-library conversion above, without the
  command line. Fill in Packages Folder, Output Directory and Godot
  Executable and press it; Filter by Name narrows the run to matching
  packages and Dry Run prints the routing without converting. The other
  fields are for single-pack conversion and are ignored.

## Documentation

| Document | Description |
|----------|-------------|
| [Pipeline Steps](docs/steps/README.md) | Comprehensive 12-step pipeline documentation |
| [GUI Documentation](docs/steps/gui.md) | CustomTkinter GUI wrapper |
| [Architecture](docs/architecture.md) | Technical architecture |
| [Shader Reference](docs/shader-reference.md) | Godot shader parameters |
| [Troubleshooting](docs/troubleshooting.md) | Common issues and solutions |
| [API Reference](docs/api/index.md) | Module API documentation |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## License

This converter tool is provided for use with legally purchased Synty Studios assets. The shaders are licensed under their respective GodotShaders.com licenses.

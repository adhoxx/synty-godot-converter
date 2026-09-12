# Character Rigs and Animations

**Status:** Approved design, not yet implemented
**Date:** 2026-09-12
**Scope:** Two components in one spec - rig preservation, and animation pack support

## Problem

The converter discards every character rig.

`extract_and_save_mesh()` in `godot_converter.gd` creates a fresh, bare
`MeshInstance3D`, copies only `.mesh` and `.name` onto it, and packs that as the
output scene. The `Skeleton3D`, the `skin` binding, the `BoneAttachment3D` nodes
holding weapons, and the node transform are all dropped. Characters arrive in
Godot as static meshes frozen in bind pose.

This is a design limitation, not a bug. Extracting flat meshes is correct for the
~850 props and walls that make up the bulk of every pack. It is wrong for the
small minority of assets that are characters, and those are the assets whose
value depends most on the rig.

## Evidence

Measured on POLYGON_Dungeon and the four ANIMATION_* packs.

`Models/Characters.fbx` imports into Godot 4.7.2 with the rig fully intact:

```
Characters <Node3D>
  Skeleton3D  [49 bones]
    Character_Skeleton_Knight  <MeshInstance3D> [skin=YES skeleton_path=..]
    Character_Goblin_Shaman    <MeshInstance3D> [skin=YES skeleton_path=..]
    ... 16 skinned meshes total ...
    SM_Item_Sword <BoneAttachment3D>
      SM_Item_Sword <MeshInstance3D>
    ... 12 bone attachments total ...
```

The data the converter needs is present on import and thrown away afterwards.

### Rig families

| Rig | Bones | Bone names shared with Polygon rig |
|---|---|---|
| `PolygonSyntyCharacter` (canonical) | 52 | - |
| Animation clip (Base Locomotion) | 52 | **52 / 52** |
| POLYGON_Dungeon characters | 49 | 38 / 49 |
| `SidekickSyntyCharacter` | 88 | **0 / 88** |

Two findings drive the whole design:

1. **Animation clips need no retargeting.** Clips use the identical 52-bone
   Polygon skeleton, so they can be loaded and bound directly.
2. **Sidekick is a disjoint rig family.** Zero shared bone names means family
   detection is trivial and cross-binding must be refused.

The Dungeon characters' 11-bone gap is almost entirely an artifact:

```
In Polygon rig, not in Dungeon (14):
  Jaw, Prop_L, Prop_R,
  Thumb_01_1, Thumb_02_1, Thumb_03_1,
  IndexFinger_01_1 .. IndexFinger_04_1, Finger_01_1 .. Finger_04_1

In Dungeon, not in Polygon rig (11):
  Thumb_01_2, Thumb_02_2, Thumb_03_2,
  IndexFinger_01_2 .. IndexFinger_04_2, Finger_01_2 .. Finger_04_2
```

Both hands' finger bones share names inside the FBX. Godot disambiguates
duplicates by appending an index in encounter order, and that order differs
between files. So the real difference is three genuinely absent bones (`Jaw`,
`Prop_L`, `Prop_R`) plus a naming-order artifact covering the fingers.

### Character composition

Synty encodes each character as a Unity prefab holding the entire shared
hierarchy with all but one character disabled. `Character_Goblin_WarChief.prefab`
has exactly two active GameObjects:

```
ACTIVE   (2): Character_Goblin_WarChief, SM_Item_Goblin_WarBanner
INACTIVE(26): every other character mesh and item
```

The prefab is therefore a complete character definition: which body mesh, and
which equipment. `prefab_parser.py` already parses these files and already
distinguishes `SkinnedMeshRenderer` (`!u!137`); it only needs to read
`m_IsActive`.

### Animation packs

| Measure | Value |
|---|---|
| Clip FBX across the four ANIMATION_* packs | 2,432 |
| Polygon family | 1,160 |
| Sidekick family | 1,157 |
| RootMotion variants | 209 |
| FBX under `/Animations/` in ANIMATION_Sword_Combat | 242 / 244 |
| FBX under `/Animations/` in POLYGON_Dungeon | 0 / 801 |

Clips ship as one FBX per animation, carrying real names
(`A_Idle_Crouching_Femn`), organised by category (`Attack/`, `Block/`, `Death/`,
`Dodge/`, `Hit/`, `Idle/`).

## Goals

- Skinned meshes convert to usable rigged Godot characters, with equipment.
- Animation packs convert to `AnimationLibrary` resources.
- Characters can be bound to those libraries on request.
- Mis-binding across rig families is impossible; partial binding is reported.
- Static prop conversion is completely unaffected.

## Non-goals

- **Structural bone retargeting.** Matching bones by parent chain rather than
  name, to repair the finger-suffix artifact. Reported, not fixed. See Risks.
- **Animation state machines.** Unity `.controller` and `.playable` assets are
  ignored; Godot `AnimationTree` authoring stays manual.
- **Avatar masks.** `.mask` files are ignored.
- **Blend shapes.** Still not carried through `scale_mesh()`; no pack under test
  has any.

## Architecture

Two components. Each adds one interface file and neither depends on the other at
runtime, so they can be built and verified independently despite sharing a spec.

```
ANIMATION PACK                          CHARACTER PACK
  converter.py (auto-detect)              prefab_parser.py
       | animation mode                        | + m_IsActive
       v                                       v
  models/ <- clip FBX                   character_definitions.json
       |                                       |
       v                                       v
  godot_converter.gd                     godot_converter.gd
   AnimationPlayer -> AnimationLibrary    clone Skeleton3D per character,
       |                                  reattach skin, copy BoneAttachment3D
       v                                       v
  animations/<Pack>_<Family>.res --bind-> meshes/.../Character_X.tscn
                                (--animations)
```

The division follows the existing codebase: Unity-format parsing in Python,
Godot-object construction in GDScript, a JSON file as the contract between them.
This mirrors `mesh_material_mapping.json` exactly.

Rejected alternatives:

- **All in GDScript.** Character composition lives in Unity prefabs, so GDScript
  would need a second prefab parser in a second language.
- **Python emits `.tscn` text directly**, as `tres_generator.py` does for
  materials. A rigged scene embeds `ArrayMesh` surfaces, a `Skin` with bind
  poses, and a bone hierarchy; hand-authoring that would reimplement Godot's
  serializer. Materials are a flat property list, so the analogy does not hold.

## Component 1: Rig preservation

### Python

`prefab_parser.py` gains `m_IsActive` parsing and a second entry point:

```python
def build_character_definitions(guid_map) -> dict[str, CharacterDefinition]
```

A prefab qualifies as a character when it contains at least one **active**
`SkinnedMeshRenderer`. `source_fbx` is resolved by looking the skinned mesh's
GUID up in `guid_to_pathname`.

`character_definitions.json`, written beside `mesh_material_mapping.json`:

```json
{
  "Character_Goblin_WarChief": {
    "source_fbx": "Characters",
    "skinned": ["Character_Goblin_WarChief"],
    "attachments": ["SM_Item_Goblin_WarBanner"]
  }
}
```

Python deliberately does **not** determine that the banner is bone-attached. The
prefab encodes that as a Transform parent chain, but Godot's FBX importer has
already built a `BoneAttachment3D` carrying the correct `bone_name`. Python
reports only which objects are active; GDScript reads the structure Godot built.
This avoids a second parser that could disagree with Godot's interpretation.

### GDScript

For each definition whose `source_fbx` matches the file being processed:

1. Instantiate the FBX scene and locate its `Skeleton3D`.
2. Clone the skeleton - bones and rest transforms only, no children.
3. Reparent the character's skinned `MeshInstance3D` under the clone, preserving
   `skin` and repointing `skeleton`.
4. Copy each active attachment's `BoneAttachment3D` subtree, preserving
   `bone_name`.
5. Apply material overrides through the existing `get_material_names_for_mesh()`
   lookup and its fallback chain.
6. Add an empty `AnimationPlayer`.
7. Save to the standard mesh output path.

Output replaces the flat static scene for that mesh. File count and layout are
unchanged; only skinned meshes take this path.

### Scale

**`--mesh-scale` must never reach a skinned mesh.** Baking a factor into vertex
positions while leaving bone rest transforms untouched breaks the bind pose and
deforms the character. The `scale_mesh()` fix in `1716f8a` stops surfaces being
dropped; it does not make vertex-baked scaling correct for skinned geometry.

Rigged characters carry scale on the scene root instead, which scales mesh,
skeleton, and attachments coherently. This also gives the pack's inconsistent
unit scales a clean home - POLYGON_Dungeon props measure ~0.0077 units while its
characters measure ~204.

## Component 2: Animation packs

### Detection

Animation mode triggers when the fraction of FBX whose path contains
`/Animations/` exceeds 0.5.

| Pack | Ratio | Mode |
|---|---|---|
| ANIMATION_Sword_Combat | 242 / 244 = 0.99 | animations |
| POLYGON_Dungeon | 0 / 801 = 0.00 | assets |

The separation is wide enough to need no tuning. `--pack-type {auto,assets,animations}`
forces either mode when detection is wrong.

In animation mode the converter skips material parsing, texture copying, shader
resolution, and mesh-material mapping. It copies clip FBX and runs the library
pass.

### Clips to libraries

A GDScript pass instantiates each imported clip FBX, reads its
`AnimationPlayer`, and appends every animation to an `AnimationLibrary`. Clip
names come from the FBX's own animation name, falling back to the filename stem,
with a numeric suffix on collision. Rig family is read from the clip's own
skeleton.

Output: `animations/<PackName>_<Family>.res` at project root, shared across packs
in the same way as `shaders/`. `<PackName>` is the existing
`extract_pack_name_from_package()` result, so
`ANIMATION_Sword_Combat_Unity_2021_1_v1_2_0.unitypackage` yields
`animations/ANIMATION_Sword_Combat_Polygon.res` and
`animations/ANIMATION_Sword_Combat_Sidekick.res`.

### Binding

`--animations <name>[,<name>...]` on a character-pack run. Each name is matched
case-insensitively as a substring of the `<PackName>` component of the library
filenames, so `--animations sword_combat` selects
`ANIMATION_Sword_Combat_Polygon.res` and its Sidekick sibling; the family gate
then decides which one actually binds. `--animations all` binds every library
present. The resolved list is recorded in `converter_config.json`; GDScript loads
each library and calls `add_animation_library()` on the character's
`AnimationPlayer`, keyed by `<PackName>` so clip references read
`ANIMATION_Sword_Combat/A_Attack_HeavyCombo01A_Sword`.

Binding is opt-in so character scenes stay light by default, one library serves
every character of that family, and adding a pack later needs no character
re-conversion.

### Rig safety

| Condition | Action |
|---|---|
| Family mismatch (Sidekick library, Polygon character) | Refuse to bind; warn naming both families |
| Bone-name coverage below 90% | Bind, and warn listing the missing bones |

The coverage gate is what surfaces the `Thumb_01_1` / `Thumb_01_2` artifact.
Auto-remapping is deliberately excluded: the suffixes come from encounter-order
disambiguation, so a guessed correspondence can bind left-hand tracks to the
right hand. A wrong hand is a worse outcome than a still hand. `Jaw`, `Prop_L`
and `Prop_R` simply have no target and are harmless.

## Error handling

Every failure degrades to a working static asset or an explicit warning. None
produces a silent empty scene - that was the failure mode of the `scale_mesh`
bug and is the specific outcome to avoid.

| Condition | Behaviour |
|---|---|
| Source FBX has no `Skeleton3D` | Static mesh output, warn |
| Skinned mesh has null `skin` | Static mesh output, warn |
| `character_definitions.json` absent | Static output for all meshes, as today |
| Requested animation library missing | Warn, leave `AnimationPlayer` unbound |
| Clip FBX has no `AnimationPlayer` | Skip, count in summary |
| Rig family mismatch | Refuse bind, warn |
| Bone coverage below 90% | Bind, warn with missing names |

## Testing

**Python (pytest, matching the existing 20-test suite and fixture style):**

- `m_IsActive` parsing, including absent and malformed values
- Character definition assembly: active mesh and attachment selection, prefabs
  with no active skinned renderer, `source_fbx` GUID resolution
- Animation-pack detection ratio at and around the threshold

**GDScript (no framework available - empirical and scripted):**

- Convert POLYGON_Dungeon; assert every character scene contains a `Skeleton3D`
  with a bone count above zero and a non-null `skin`
- Assert attachment nodes are present and carry a `bone_name`
- Convert ANIMATION_Base_Locomotion; assert library clip count matches the FBX
  count and the family is `Polygon`
- Bind the library to a Dungeon character; assert the coverage report warns and
  names the expected finger bones
- Assert a Sidekick library is refused against a Polygon character
- Regression: on an unscaled run, assert static prop scenes are unchanged against
  the current pipeline (same file set, same node names, same material overrides);
  scaled runs already differ because of the `scale_mesh` fix in `1716f8a`

Full 2,432-clip import costs roughly 20 minutes, one-time per pack.

## Risks

**Finger-bone mis-binding.** Coverage below 100% is expected for POLYGON_Dungeon
characters against Polygon clips. Reported, not repaired. If hand poses prove
visibly wrong in practice, structural parent-chain retargeting becomes its own
piece of work.

**Skeleton cloning fidelity.** Cloning bones and rest transforms must reproduce
the bind pose exactly, or characters deform. This is the highest-risk step and
the first thing to verify visually rather than by assertion alone.

**Rig variation across packs.** Only POLYGON_Dungeon characters and the two
canonical rigs have been measured. Other POLYGON_* packs may differ; detection
is by bone-name signature, so an unrecognised family should report as unknown
and refuse binding rather than guess.

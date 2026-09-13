# Spike: can Godot's built-in retargeting animate POLYGON pack characters?

**Date:** 2026-09-12
**Status:** Answered - yes. Nothing implemented; the probe code was throwaway.
**Relates to:** `docs/superpowers/specs/2026-09-12-character-rigs-and-animations-design.md`,
which records real retargeting as a non-goal.

## The question

`--animations` refuses to bind clips to POLYGON pack characters. The spec
records two reasons:

1. **Bone name coverage.** POLYGON_Dungeon's character rig shares only 75% of
   its bone names with the rig the clips were authored against, so the binding
   gate refuses it.
2. **Bone orientation.** The clip rig's bones run along **Y**; POLYGON pack
   character bones run along **X**, in centimetres rather than metres. Pose
   tracks apply relative to bone rests, so binding anyway does not merely
   mis-pose the hands - it collapses the character.

Item 2 was the blocker, and the spec calls fixing it "real retargeting",
explicitly out of scope. The question was whether Godot 4.7 already ships that.

## Answer

It does, and it resolves both problems at once.

Godot's scene importer has a `retarget/` option group driven by a `BoneMap`
that maps the rig's bone names onto a `SkeletonProfile`
(`SkeletonProfileHumanoid`, 56 bones). With a bone map set, the **bone
renamer** rewrites bones - and the animation tracks addressing them - to the
profile's names, and the **rest fixer** rewrites bone rests to the profile's
convention.

Measured on `POLYGON_Dungeon/models/Characters.fbx` against the rig inside
`ANIMATION_Sword_Combat`:

| | before | after |
|---|---|---|
| Character `Spine` rest origin | `(10.393, 0, 0)` - X axis, centimetres | `(0.0, 0.1028, -0.0155)` |
| Clip rig `Spine` rest origin | `(0.0005, 0.1039, 0.0030)` - Y axis, metres | `(-0.0017, 0.1014, -0.0228)` |
| Rest axis agreement (dot) | ~0 | **0.997 - 1.000** |
| Bone name coverage | 75% | 40 of 42 bone tracks resolve |

The two unresolved tracks are `Prop_L` and `Prop_R`, weapon-holder bones the
clip rig has and the Dungeon character does not. They stay under their
original names, as do other unmapped leftovers (`Jaw`, `Toes_L/R`, `Eyes`,
`Eyebrows`, `IndexFinger_04`).

Driving the character with `A_Attack_HeavyCombo01A_Sword` and comparing joint
positions against the same clip on its own rig:

| t (s) | reference rig RightHand | retargeted character RightHand | worst joint delta |
|-------|-------------------------|--------------------------------|-------------------|
| 0.00 | `(-0.368, 1.021, -0.306)` | `(-0.381, 1.014, -0.323)` | 0.057 m |
| 0.50 | `(-0.255, 1.660, 0.428)` | `(-0.267, 1.645, 0.388)` | 0.050 m |
| 1.00 | `(0.216, 1.709, 0.379)` | `(0.199, 1.710, 0.348)` | 0.053 m |
| 1.50 | `(-0.322, 1.269, -0.451)` | `(-0.278, 1.269, -0.469)` | 0.062 m |
| 2.00 | `(-0.226, 1.480, -0.538)` | `(-0.175, 1.483, -0.542)` | 0.063 m |

The hand travels the full attack arc, staying within ~6 cm of the reference.
That residual is the proportion difference between two differently-built
characters, which is what retargeting is meant to absorb - not the collapse
seen when binding across mismatched rests.

## The part that cost the most time

**The retarget options are per-node subresource settings, not top-level import
params.** Writing them under `[params]` in the `.import` file looks like it
works and then silently does nothing: Godot rewrites the file on the next
import and drops every key. They belong in `_subresources`, keyed by the
skeleton's node path:

```ini
_subresources={
"nodes": {
"PATH:Skeleton3D": {
"retarget/bone_map": Resource("res://bonemap_polygon.tres"),
"retarget/bone_renamer/rename_bones": true,
"retarget/bone_renamer/unique_node/make_unique": true,
"retarget/bone_renamer/unique_node/skeleton_name": "GeneralSkeleton",
"retarget/rest_fixer/apply_node_transforms": true,
"retarget/rest_fixer/fix_silhouette/enable": true,
"retarget/rest_fixer/fix_silhouette/filter": [],
"retarget/rest_fixer/fix_silhouette/threshold": 15.0,
"retarget/rest_fixer/keep_global_rest_on_leftovers": true,
"retarget/rest_fixer/normalize_position_tracks": true,
"retarget/rest_fixer/reset_all_bone_poses_after_import": true
}
}
}
```

The valid option names in 4.7.2, confirmed against the binary, are:
`retarget/bone_map`, `retarget/bone_renamer/rename_bones`,
`retarget/bone_renamer/unique_node/{make_unique,skeleton_name}`,
`retarget/remove_tracks/{except_bone_transform,unimportant_positions,unmapped_bones}`,
`retarget/rest_fixer/{apply_node_transforms,keep_global_rest_on_leftovers,
normalize_position_tracks,original_skeleton_name,
reset_all_bone_poses_after_import,retarget_method,use_global_pose}`,
`retarget/rest_fixer/fix_silhouette/{enable,threshold,filter,base_height_adjustment}`.
There is no `overwrite_axis` - that name is from an older release.

Note also that renamed tracks address the skeleton as `%GeneralSkeleton:Bone`,
a scene-unique-name path. It resolves only when the skeleton is reachable by
unique name from the `AnimationPlayer`'s `root_node`, which any implementation
has to arrange deliberately.

## What implementing this would take

1. Generate one `BoneMap` `.tres` per rig family (Polygon, Sidekick). The
   mapping is static per family and is the only hand-authored part. Godot's
   FBX importer appends dedup suffixes (`_1`, `_2`) to duplicate bone names,
   and the suffix differs between files, so right-hand finger bones need the
   suffix substituted per file rather than hard-coded.
2. Write the `_subresources` block into each character and clip `.import`
   before the import phase, which means knowing the skeleton's node path -
   `PATH:Skeleton3D` for every Synty FBX measured so far.
3. Replace the bone-coverage gate. Once both sides are renamed to the profile,
   coverage is no longer a proxy for compatibility: the honest check becomes
   whether both FBX were imported with a bone map, plus the rest-orientation
   check already proposed.
4. Decide what happens to characters with no humanoid mapping. Not every
   skinned thing is a humanoid, so the bone map has to be opt-in per rig
   family with a clean fallback to today's static behaviour.

Step 3 matters: the current 90% coverage gate would still refuse these
characters after retargeting, because it measures the wrong thing.

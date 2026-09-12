# Synty Converter

A Python tool for converting Synty Unity asset packs to Godot 4.

## Environment

- **Python**: `python` on PATH (3.14.3). CLI needs stdlib only; GUI needs `pip install -r requirements-gui.txt`.
- **Godot**: `C:\Users\Justin\Documents\git_repos\godot-bin\Godot_v4.7.2-stable_win64_console.exe`
  - Use the **`_console.exe`** variant. `run_godot_cli()` pipes stdout via `subprocess.Popen`; the
    plain `.exe` is a Windows GUI-subsystem binary and writes nothing to the pipe, so progress
    parsing and error reporting go blank.
  - 4.7.2 is ahead of the 4.6 this repo targets. The engine APIs `godot_converter.gd` uses are
    stable across 4.x. `PROJECT_GODOT_TEMPLATE` still writes
    `config/features=PackedStringArray("4.6")`; Godot 4.7 loads and upgrades that without complaint.
- **Unity packages**: `C:\Users\Justin\Downloads\*.unitypackage` (43 packs: POLYGON_*, SIDEKICK_*,
  ANIMATION_*, INTERFACE_*)
- **Imported Unity assets**: `D:\Unity Projects\AEGIS\Assets\Synty\` - packs already imported into
  the AEGIS Unity project (`Models/`, `Materials/`, `Textures/`, `Prefabs/`). Usable as
  `--source-files` because `has_source_assets_recursive()` accepts a `Models/` dir in place of `FBX/`.
- **Output root**: `D:\GameAssets\Godot\Synty\` (test runs go in `D:\GameAssets\Godot\Synty\tests\`)

### No MaterialList.txt on this machine - handled by prefab fallback

Synty ships `MaterialList*.txt` only in the separate **SourceFiles** download (the raw FBX/texture
zip from the Synty store), never in the `.unitypackage`. Neither Downloads nor the AEGIS project
has one, so without a fallback step 10 would skip `mesh_material_mapping.json`, and
`process_pack_folder()` in `godot_converter.gd` hard-returns when that file is absent - yielding
zero meshes.

`prefab_parser.py` closes that gap. When step 4.5 finds no MaterialList data, it derives the same
`list[PrefabMaterials]` from the `.prefab` files inside the package (`GuidMap.guid_to_prefab_content`),
joining each `MeshRenderer`/`SkinnedMeshRenderer`'s `m_GameObject` back to its GameObject name and
resolving `m_Materials` GUIDs through the package's GUID map. Everything downstream
(`build_shader_cache`, `get_mesh_to_materials_map`, `generate_mesh_material_mapping_json`) consumes
it unchanged.

MaterialList.txt stays authoritative when present - the prefab path is only a fallback.

Two things to know when working on this:

- **`uses_custom_shader` is forced to `True`** on prefab-derived slots. Prefabs carry no such flag,
  and `build_shader_cache()` short-circuits straight to `polygon.gdshader` when it is `False` -
  which would silently flatten every foliage/water/crystal material in every pack. `True` routes
  through `determine_shader()` (GUID lookup first), which is the more authoritative signal anyway.
- **Coverage is ~95%, not 100%.** On POLYGON_Dungeon, 801 of 825 prefabs parse and 762 of 801 FBX
  filenames match a mapping key. The misses are FX prefabs with no renderer and a handful of FBX
  whose mesh nodes have no correspondingly-named prefab. Those meshes get no surface override and
  fall back to whatever `_detect_default_material()` finds. MaterialList.txt is itself generated
  from prefabs, so it would have much the same gap.

Tests: `python -m pytest tests/ -q` (20 tests, no Godot or package needed).

## Quick Commands

```bash
# Run converter (this machine)
python converter.py \
  --unity-package "C:/Users/Justin/Downloads/POLYGON_Dungeon_Unity_2021_3_v1_9_5.unitypackage" \
  --source-files "D:/Unity Projects/AEGIS/Assets/Synty/PolygonDungeon" \
  --output "D:/GameAssets/Godot/Synty/tests" \
  --godot "C:/Users/Justin/Documents/git_repos/godot-bin/Godot_v4.7.2-stable_win64_console.exe" \
  --filter "SM_Prop_Barrel" --verbose

# Build exe
python -m PyInstaller synty_converter.spec --noconfirm

# Create release
git tag v2.X && git push origin v2.X
gh release create v2.X dist/SyntyConverter.exe --title "v2.X - Title" --notes "Release notes"
```

## Project Structure

```
synty-converter/
├── converter.py          # Main CLI pipeline (Steps 1-12)
├── gui.py                # Tkinter GUI wrapper
├── godot_converter.gd    # GDScript for Godot-side mesh processing
├── material_list.py      # MaterialList.txt parsing, mesh-material mapping
├── prefab_parser.py      # Prefab-derived mesh-material mapping + character definitions
├── shader_mapping.py     # Unity shader GUID → Godot shader mapping
├── tres_generator.py     # .tres material file generation
├── unity_parser.py       # Unity .mat file parsing
├── shaders/              # Godot shader files (polygon, foliage, water, etc.)
├── tests/                # pytest suite (51 tests, no Godot needed)
├── dist/                 # Built exe output
└── synty_converter.spec  # PyInstaller spec file
```

## Key Architecture

- **Per-pack isolation**: Each pack gets its own folder with materials/, textures/, models/, meshes/
- **Mesh subfolders by config**: Mesh output goes to `meshes/{format}_{mode}/` subfolders (e.g., `meshes/tscn_separate/`, `meshes/res_combined/`)
- **Per-pack mapping**: `mesh_material_mapping.json` is in each pack folder (not shared)
- **Existing pack detection**: Re-running on a pack with materials/, textures/, models/, and mesh_material_mapping.json skips phases 3-10, only regenerates meshes
- **Dynamic shader discovery**: Searches project for existing shaders before copying
- **FBX path cleaning**: Strips SourceFiles/FBX/Models prefixes from paths
- **Output subfolder**: Optional subfolder within output directory for organizing multiple packs (e.g., `output/synty/PackName/`)
- **Retain subfolders**: Preserves original directory structure from source files when enabled

### Characters and animations

- **Rigged characters**: skinned meshes emit `Skeleton3D` + `skin` +
  `BoneAttachment3D` equipment + `AnimationPlayer`, driven by
  `character_definitions.json` derived from Unity prefabs (`m_IsActive` picks the
  one enabled character out of the ~28 in each prefab)
- **`source_fbx` is a Models-relative path, never a basename** - packs ship both
  `Models/Characters.fbx` and `Models/FixedScale/Characters.fbx`, and matching on
  basename builds every character twice from the wrong source
- **`--mesh-scale` must never reach skinned vertices** - it would break the bind
  pose; rigged characters carry scale on the scene root
- **Animation packs**: auto-detected by `/Animations/` FBX ratio > 0.5, converted
  to `animations/<Pack>_<Family>.res`, bound via `--animations`
- **Binding is refused** on rig-family mismatch, unidentified rigs, or bone
  coverage below 90%. POLYGON_Dungeon's 49-bone variant measures 75% and is
  refused: below-threshold binding collapses the character, because pose tracks
  apply relative to bone rests. The canonical 52-bone rig binds correctly.

### Measured unit scales (POLYGON_Dungeon)

| Source | Size | Units |
|--------|------|-------|
| `Models/Characters.fbx` | 204 x 188 | centimetres |
| `Models/FixedScale/Characters.fbx` | 2.05 x 1.89 | **metres (correct)** |
| props | 0.0077 | ~1/100 metric |

No single `--mesh-scale` fits all three; `_FixedScale` character scenes are the
ones usable as-is.

## Testing

Test output location: `D:\GameAssets\Godot\Synty\tests\`

Packs available locally, smallest first. PolygonDungeon alone has 801 FBX, so **always pass
`--filter`** while iterating - a full pack run is a long Godot import.

| Pack | Size | Notes |
|------|------|-------|
| `POLYGON_Dungeon_Unity_2021_3_v1_9_5` | 51 MB | 42 mats, 801 FBX, 50 textures; also imported in AEGIS |
| `POLYGON_Dark_Fantasy_Unity_2021_3_v1_3_3` | 142 MB | Also imported in AEGIS |
| `POLYGON_NatureBiomes_EnchantedForest_Unity_2022_3_v1_6_2` | 238 MB | Good foliage/water shader coverage |

Useful flags while iterating: `--skip-godot-cli` (materials only, no Godot), `--filter <substr>`
(also filters textures and materials), `--dry-run`.

---

Last Updated: 2026-09-12
Version: 2.4

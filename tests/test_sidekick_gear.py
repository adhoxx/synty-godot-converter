"""Gear sets from the Sidekick tool database."""

import json
import sqlite3
from pathlib import Path

from sidekick import (
    SIDEKICK_PARTS_DIRNAME,
    SIDEKICK_SLOT_CODES,
    derive_gear_sets_from_names,
    load_part_presets,
    slot_for_part_name,
    write_sidekick_colors_json,
    write_sidekick_gear_sets_json,
)


def _make_db(path: Path) -> None:
    """Build a database with the two tables load_part_presets reads."""
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE sk_part_preset (
            id INTEGER PRIMARY KEY, ptr_species INTEGER,
            part_group INTEGER, name TEXT, outfit TEXT
        );
        CREATE TABLE sk_part_preset_row (
            id INTEGER PRIMARY KEY, ptr_part_preset INTEGER,
            part_name TEXT, part_type TEXT, ptr_part INTEGER
        );
        INSERT INTO sk_part_preset VALUES (429, 2, 1, 'Species Goblins 01', NULL);
        INSERT INTO sk_part_preset VALUES (600, 1, 2, 'Fantasy Knights 01', '');
        INSERT INTO sk_part_preset VALUES (700, 1, 3, 'Fantasy Knights 01', '');
        INSERT INTO sk_part_preset_row VALUES
            (1, 429, 'SK_GOBL_BASE_01_01HEAD_GO01', '01HEAD', NULL),
            (2, 429, 'SK_GOBL_BASE_01_10TORS_GO01', '10TORS', NULL),
            (3, 600, 'SK_FANT_KNGT_01_10TORS_HU01', '10TORS', NULL),
            (4, 700, 'SK_FANT_KNGT_01_24ABAC_HU01', '24ABAC', NULL),
            (5, 600, 'SK_HUMN_BASE_01_01HEAD_HU01', 'Head', NULL),
            (6, 600, NULL, '22AHED', NULL);
        """
    )
    connection.commit()
    connection.close()


def test_slot_codes_cover_every_body_slot():
    assert len(SIDEKICK_SLOT_CODES) == 38
    assert SIDEKICK_SLOT_CODES["10TORS"] == "Torso"
    assert SIDEKICK_SLOT_CODES["24ABAC"] == "AttachmentBack"


def test_slot_for_part_name_reads_the_embedded_code():
    assert slot_for_part_name("SK_FANT_KNGT_01_10TORS_HU01") == "Torso"


def test_slot_for_part_name_returns_empty_for_unparseable_names():
    assert slot_for_part_name("SK_FacialDemoCharacter") == ""
    assert slot_for_part_name("SK_FANT_KNGT_01_99XXXX_HU01") == ""


def test_load_part_presets_groups_by_part_group(tmp_path):
    db = tmp_path / "Side_Kick_Data.db"
    _make_db(db)

    presets = load_part_presets(db)

    assert presets["429"]["group"] == "head"
    assert presets["600"]["group"] == "upper"
    assert presets["700"]["group"] == "lower"


def test_load_part_presets_maps_slot_codes_to_slot_names(tmp_path):
    db = tmp_path / "Side_Kick_Data.db"
    _make_db(db)

    presets = load_part_presets(db)

    assert presets["429"]["parts"] == {
        "Head": "SK_GOBL_BASE_01_01HEAD_GO01",
        "Torso": "SK_GOBL_BASE_01_10TORS_GO01",
    }
    assert presets["429"]["name"] == "Species Goblins 01"
    assert presets["429"]["species"] == 2


def test_load_part_presets_returns_empty_for_a_missing_database(tmp_path):
    assert load_part_presets(tmp_path / "absent.db") == {}


def test_derive_gear_sets_groups_by_family_and_set_number():
    sets = derive_gear_sets_from_names(
        [
            "SK_FANT_KNGT_01_10TORS_HU01",
            "SK_FANT_KNGT_01_11AUPL_HU01",
            "SK_FANT_KNGT_02_10TORS_HU01",
        ]
    )

    assert sets["FANT_KNGT_01"]["parts"] == {
        "Torso": "SK_FANT_KNGT_01_10TORS_HU01",
        "ArmUpperLeft": "SK_FANT_KNGT_01_11AUPL_HU01",
    }
    assert sets["FANT_KNGT_01"]["group"] == "unknown"
    assert "FANT_KNGT_02" in sets


def test_derive_gear_sets_ignores_unparseable_names():
    assert derive_gear_sets_from_names(["SK_FacialDemoCharacter"]) == {}


def test_gear_sets_are_written_as_json(tmp_path):
    out = tmp_path / "sidekick_gear_sets.json"

    write_sidekick_gear_sets_json(
        {
            "429": {
                "name": "Species Goblins 01",
                "group": "head",
                "species": 2,
                "parts": {"Torso": "SK_GOBL_BASE_01_10TORS_GO01"},
            }
        },
        out,
    )

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["429"]["parts"]["Torso"] == "SK_GOBL_BASE_01_10TORS_GO01"


def test_colors_are_written_as_json(tmp_path):
    out = tmp_path / "sidekick_colors.json"

    write_sidekick_colors_json(
        {"properties": {"Skin 01": {"id": 1, "group": 1, "u": 0, "v": 5}}, "presets": {}},
        out,
    )

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["properties"]["Skin 01"]["u"] == 0


def test_writers_create_missing_parent_directories(tmp_path):
    out = tmp_path / "nested" / "sidekick_gear_sets.json"

    write_sidekick_gear_sets_json({}, out)

    assert out.is_file()


def test_parts_dirname_is_stable():
    assert SIDEKICK_PARTS_DIRNAME == "sidekick_parts"


def test_part_type_is_read_as_a_slot_name_too(tmp_path):
    """sk_part_preset_row.part_type holds a code on some rows, a name on others.

    Reading only codes drops 352 of the real database's 532 presets and every
    face slot of the rest, without reporting anything.
    """
    db = tmp_path / "Side_Kick_Data.db"
    _make_db(db)

    presets = load_part_presets(db)

    assert presets["600"]["parts"]["Head"] == "SK_HUMN_BASE_01_01HEAD_HU01"
    assert presets["600"]["parts"]["Torso"] == "SK_FANT_KNGT_01_10TORS_HU01"


def test_part_names_with_an_extra_prefix_and_no_species_still_parse():
    """Not every part name is SK_<FAMILY>_<NN>_<CODE>_<SPECIES>.

    SK_SPEC_HUMN_BASE_01_10TORS and SK_FUTR_APOC_OUTL_06_28AHPR carry an extra
    prefix and no species suffix. Reading fixed positions dropped 25 real parts
    from the library without reporting anything.
    """
    assert slot_for_part_name("SK_SPEC_HUMN_BASE_01_10TORS") == "Torso"
    assert slot_for_part_name("SK_FUTR_APOC_OUTL_06_28AHPR") == "AttachmentHipsRight"

    sets = derive_gear_sets_from_names(["SK_SPEC_HUMN_BASE_01_10TORS"])
    assert sets["SPEC_HUMN_BASE_01"]["parts"] == {
        "Torso": "SK_SPEC_HUMN_BASE_01_10TORS"
    }


def test_a_name_with_no_slot_code_is_not_a_part():
    assert slot_for_part_name("SK_FacialDemoCharacter") == ""
    assert slot_for_part_name("SK_FANT_KNGT_01_99XXXX_HU01") == ""


def test_a_null_part_name_leaves_the_slot_empty(tmp_path):
    """418 of the database's 5547 rows have a NULL part_name.

    It means the set fills nothing in that slot. str() would turn it into a
    part named literally "None", which no library can ever resolve.
    """
    db = tmp_path / "Side_Kick_Data.db"
    _make_db(db)

    presets = load_part_presets(db)

    assert "AttachmentHead" not in presets["600"]["parts"]
    assert "None" not in presets["600"]["parts"].values()

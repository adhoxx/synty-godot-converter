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
        paths = [
            f"Assets/Synty/A/Animations/Polygon/Attack/c{i}.fbx" for i in range(242)
        ]
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

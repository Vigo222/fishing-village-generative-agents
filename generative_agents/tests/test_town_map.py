"""小镇场景自检:地图、居民文件互相对得上,所有地点都走得到。"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from modules.maze import Maze  # noqa: E402

ASSETS = BASE / "frontend/static/assets/village"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def all_agents():
    return {p.parent.name: load(p) for p in ASSETS.glob("agents/*/agent.json")}


def test_rosters_match_agent_files():
    agents = all_agents()
    core = load(BASE / "data/town.json")["personas"]
    full = load(BASE / "data/town_20.json")["personas"]
    assert len(core) == 10 and len(full) == 20
    assert full[:10] == core
    assert set(full) == set(agents)
    for name in full:
        assert (ASSETS / "agents" / name / "texture.png").exists()
        assert (ASSETS / "agents" / name / "portrait.png").exists()


def test_every_known_place_is_reachable_from_home():
    maze = Maze(load(ASSETS / "maze.json"), None)
    for name, agent in all_agents().items():
        coord = tuple(agent["coord"])
        assert not maze.tile_at(coord).collision
        living = agent["spatial"]["address"]["living_area"]
        assert ":".join(living + ["床"]) in maze.address_tiles
        for sector, arenas in agent["spatial"]["tree"]["the Ville"].items():
            for arena, objects in arenas.items():
                for obj in objects:
                    addr = ":".join(["the Ville", sector, arena, obj])
                    assert addr in maze.address_tiles, (name, addr)
                    tiles = [t for t in maze.address_tiles[addr] if not maze.tile_at(t).collision]
                    assert tiles, (name, addr)
                    assert any(t == coord or maze.find_path(coord, t) for t in tiles), (name, addr)


def test_core_personas_do_not_mention_extra_residents():
    # 10 人实验里另外 10 人不存在,核心居民的人设不能提到他们
    agents = all_agents()
    full = load(BASE / "data/town_20.json")["personas"]
    for name in full[:10]:
        text = json.dumps(agents[name]["scratch"], ensure_ascii=False) + agents[name]["currently"]
        for other in full[10:]:
            assert other not in text, (name, other)


def test_tilemap_matches_maze_size():
    maze = load(ASSETS / "maze.json")
    tilemap = load(ASSETS / "tilemap/tilemap.json")
    height, width = maze["size"]
    assert (tilemap["height"], tilemap["width"]) == (height, width)
    for layer in tilemap["layers"]:
        assert len(layer["data"]) == height * width

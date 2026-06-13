"""Build the fisher-village scenario assets.

This script is intentionally data-only: it renames existing maze addresses within
their original sector scope, copies reused character art, writes the new persona
JSON files, and updates the resident roster.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from modules.maze import Maze


BASE = Path(__file__).resolve().parent
MAZE_PATH = BASE / "frontend/static/assets/village/maze.json"
AGENTS_DIR = BASE / "frontend/static/assets/village/agents"
TOWN_PATH = BASE / "data/town.json"

PUBLIC_SECTORS = [
    {
        "old_sector": "约翰逊公园",
        "new_sector": "码头",
        "old_arena": "公园",
        "new_arena": "码头",
        "objects": {"公园花园": "渔船泊位"},
    },
    {
        "old_sector": "霍布斯咖啡馆",
        "new_sector": "渔家小店",
        "old_arena": "咖啡馆",
        "new_arena": "渔家小店",
        "objects": {
            "咖啡馆顾客座位": "小店桌椅",
            "咖啡馆柜台后面": "小店柜台后面",
            "钢琴": "渔获摊架",
            "烹饪区": "灶台",
        },
    },
    {
        "old_sector": "玫瑰酒吧",
        "new_sector": "茶摊",
        "old_arena": "酒吧",
        "new_arena": "茶摊",
        "objects": {
            "酒吧顾客座位": "茶座",
            "吧台后面": "茶台后面",
            "麦克风": "说书台",
            "烹饪区": "烧水炉",
        },
    },
]

HOME_SECTORS = {
    "亚当的家": "老陈的家",
    "伊莎贝拉的公寓": "阿香的家",
    "亚瑟的公寓": "符大爷的家",
    "乔治的公寓": "小林的家",
    "卡洛斯的公寓": "吴婆婆的家",
}

PUBLIC_TREE = {
    "码头": {"码头": ["渔船泊位"]},
    "渔家小店": {
        "渔家小店": [
            "小店桌椅",
            "小店柜台后面",
            "渔获摊架",
            "灶台",
            "冰箱",
            "厨房水槽",
        ]
    },
    "茶摊": {
        "茶摊": [
            "茶座",
            "茶台后面",
            "说书台",
            "烧水炉",
            "架子",
            "冰箱",
            "厨房水槽",
        ]
    },
}

RESIDENTS = [
    {
        "name": "老陈",
        "source": "亚当",
        "old_home": "亚当的家",
        "home": "老陈的家",
        "coord_address": ["the Ville", "码头", "码头"],
        "coord_offset": 0,
        "age": 58,
        "innate": "消息灵通、大嗓门、热心肠",
        "learned": "老陈是渔村里打了一辈子鱼的老渔民,村里大小事他往往最先知道,爱在码头扯着嗓门和人聊天,谁家来了生人他立马就晓得。",
        "lifestyle": "老陈早上4点多就起床出海,上午在码头收拾渔获,傍晚收工。",
        "currently": "老陈今天一早出了趟海,正在码头边一边收拾渔网一边和过往的人搭话。",
    },
    {
        "name": "阿香",
        "source": "伊莎贝拉",
        "old_home": "伊莎贝拉的公寓",
        "home": "阿香的家",
        "coord_address": ["the Ville", "渔家小店", "渔家小店"],
        "coord_offset": 0,
        "age": 42,
        "innate": "精明、热情、爱打听",
        "learned": "阿香在码头边开着一家渔家小店,卖些海货和热汤热饭,嘴甜爱聊,是村里消息的二传手,客人说的事她转头就传开了。",
        "lifestyle": "阿香早上6点开店备货,白天守店,晚上9点打烊。",
        "currently": "阿香正在渔家小店里招呼客人,顺便打听今天码头有什么新鲜事。",
    },
    {
        "name": "符大爷",
        "source": "亚瑟",
        "old_home": "亚瑟的公寓",
        "home": "符大爷的家",
        "coord_address": ["the Ville", "茶摊", "茶摊"],
        "coord_offset": 0,
        "age": 67,
        "innate": "慢性子、嘴碎、爱点评",
        "learned": "符大爷在村口摆了个茶摊,村里人闲了都爱来喝碗茶歇歇脚,他是村里的'信息交易所',谁路过他都要评点两句,记性好,陈年旧事张口就来。",
        "lifestyle": "符大爷上午9点支起茶摊,坐一整天,傍晚6点收摊。",
        "currently": "符大爷正守着茶摊,慢悠悠地给茶客续水,听他们闲谈村里的事。",
    },
    {
        "name": "小林",
        "source": "乔治",
        "old_home": "乔治的公寓",
        "home": "小林的家",
        "coord_address": ["the Ville", "码头", "码头"],
        "coord_offset": 6,
        "age": 26,
        "innate": "理想主义、热情、健谈",
        "learned": "小林是从城里返乡的年轻人,想把渔村做成有故事的地方,懂村史也爱主动跟人搭话,尤其爱招呼外来的生面孔,给人讲村子的来历。",
        "lifestyle": "小林早上8点起,白天在村里各处转悠、和人攀谈,晚上11点睡。",
        "currently": "小林正在村里四处走动,看看有没有需要帮忙的外来客,顺便琢磨怎么讲好渔村的故事。",
    },
    {
        "name": "吴婆婆",
        "source": "卡洛斯",
        "old_home": "卡洛斯的公寓",
        "home": "吴婆婆的家",
        "coord_address": ["the Ville", "码头", "码头"],
        "coord_offset": 12,
        "age": 79,
        "innate": "记性极好、独来独往、说话带传说色彩",
        "learned": "吴婆婆独自住在村子边上守了大半辈子灯塔,见过来来往往无数人,记性好得惊人,说起话来总带着海上的老传说和谶语般的口吻。",
        "lifestyle": "吴婆婆起得早睡得早,白天偶尔到码头或茶摊坐坐,话不多但句句有分量。",
        "currently": "吴婆婆慢慢走到码头边,望着海,像在回想什么很久以前的事。",
    },
]

USER_AVATAR = {
    "name": "用户分身",
    "source": "用户分身",
    "coord_address": ["the Ville", "码头", "码头"],
    "coord_offset": 18,
    "age": 31,
    "innate": "客气、健谈、眼神里藏着心事",
    "learned": "他风尘仆仆来到渔村,对外自称是来收购海货的客商,以免唐突;实则是回乡寻找三十年前因变故失散的妹妹。只有和人聊得投机、信得过了,他才会吐露真正的来意。",
    "lifestyle": "他白天在码头、渔家小店、茶摊一带转悠,逢人便先攀谈收鱼的行情,熟了才打听旧人旧事。",
    "currently": "用户分身刚到渔村,背着行囊在码头边打量,逢人先问'这儿收不收海货',心里却惦记着三十年前失散的妹妹。",
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def rename_maze() -> dict:
    data = load_json(MAZE_PATH)
    public_by_sector = {item["old_sector"]: item for item in PUBLIC_SECTORS}

    for tile in data["tiles"]:
        address = tile.get("address")
        if not address:
            continue

        original_sector = address[0]
        if original_sector in public_by_sector:
            spec = public_by_sector[original_sector]
            address[0] = spec["new_sector"]
            if len(address) > 1 and address[1] == spec["old_arena"]:
                address[1] = spec["new_arena"]
            if len(address) > 2 and address[2] in spec["objects"]:
                address[2] = spec["objects"][address[2]]
        elif original_sector in HOME_SECTORS:
            address[0] = HOME_SECTORS[original_sector]

    dump_json(MAZE_PATH, data)
    return data


def make_maze(config: dict) -> Maze:
    return Maze(copy.deepcopy(config), None)


def exact_tiles(maze: Maze, address: list[str]) -> list[tuple[int, int]]:
    return sorted(maze.address_tiles.get(":".join(address), []))


def pick_coord(maze: Maze, address: list[str], offset: int = 0) -> list[int]:
    coords = [coord for coord in exact_tiles(maze, address) if not maze.tile_at(coord).collision]
    if not coords:
        raise RuntimeError(f"No non-collision tile for {address}")
    coord = coords[offset % len(coords)]
    return [coord[0], coord[1]]


def copied_home_tree(source: str, old_home: str, new_home: str) -> dict:
    source_data = load_json(AGENTS_DIR / source / "agent.json")
    source_tree = source_data["spatial"]["tree"]["the Ville"][old_home]
    return {new_home: copy.deepcopy(source_tree)}


def spatial_tree_with_home(home_tree: dict) -> dict:
    tree = copy.deepcopy(PUBLIC_TREE)
    tree.update(home_tree)
    return {"the Ville": tree}


def copy_art(source: str, target: str) -> None:
    target_dir = AGENTS_DIR / target
    target_dir.mkdir(parents=True, exist_ok=True)
    for file_name in ("texture.png", "portrait.png"):
        shutil.copy2(AGENTS_DIR / source / file_name, target_dir / file_name)


def write_resident(maze: Maze, spec: dict) -> None:
    copy_art(spec["source"], spec["name"])
    home_tree = copied_home_tree(spec["source"], spec["old_home"], spec["home"])
    data = {
        "name": spec["name"],
        "portrait": f"assets/village/agents/{spec['name']}/portrait.png",
        "coord": pick_coord(maze, spec["coord_address"], spec["coord_offset"]),
        "currently": spec["currently"],
        "scratch": {
            "age": spec["age"],
            "innate": spec["innate"],
            "learned": spec["learned"],
            "lifestyle": spec["lifestyle"],
            "daily_plan": "",
        },
        "spatial": {
            "address": {"living_area": ["the Ville", spec["home"], "主人房"]},
            "tree": spatial_tree_with_home(home_tree),
        },
    }
    dump_json(AGENTS_DIR / spec["name"] / "agent.json", data)


def write_user_avatar(maze: Maze) -> None:
    home_tree = copied_home_tree("亚当", "亚当的家", "老陈的家")
    data = {
        "name": USER_AVATAR["name"],
        "portrait": "assets/village/agents/用户分身/portrait.png",
        "coord": pick_coord(
            maze, USER_AVATAR["coord_address"], USER_AVATAR["coord_offset"]
        ),
        "currently": USER_AVATAR["currently"],
        "scratch": {
            "age": USER_AVATAR["age"],
            "innate": USER_AVATAR["innate"],
            "learned": USER_AVATAR["learned"],
            "lifestyle": USER_AVATAR["lifestyle"],
            "daily_plan": "",
        },
        "spatial": {
            "address": {"living_area": ["the Ville", "老陈的家", "主人房"]},
            "tree": spatial_tree_with_home(home_tree),
        },
    }
    dump_json(AGENTS_DIR / "用户分身" / "agent.json", data)


def write_town() -> None:
    dump_json(TOWN_PATH, {"personas": [item["name"] for item in RESIDENTS]})


def validate(maze: Maze) -> None:
    required_addresses = [
        ["the Ville", "码头", "码头"],
        ["the Ville", "码头", "码头", "渔船泊位"],
        ["the Ville", "渔家小店", "渔家小店"],
        ["the Ville", "渔家小店", "渔家小店", "小店桌椅"],
        ["the Ville", "茶摊", "茶摊"],
        ["the Ville", "茶摊", "茶摊", "茶座"],
        ["the Ville", "老陈的家", "主人房"],
        ["the Ville", "阿香的家", "主人房"],
        ["the Ville", "符大爷的家", "主人房"],
        ["the Ville", "小林的家", "主人房"],
        ["the Ville", "吴婆婆的家", "主人房"],
    ]
    old_addresses = [
        ["the Ville", "约翰逊公园", "公园"],
        ["the Ville", "霍布斯咖啡馆", "咖啡馆"],
        ["the Ville", "玫瑰酒吧", "酒吧"],
        ["the Ville", "亚当的家", "主人房"],
        ["the Ville", "伊莎贝拉的公寓", "主人房"],
        ["the Ville", "亚瑟的公寓", "主人房"],
        ["the Ville", "乔治的公寓", "主人房"],
        ["the Ville", "卡洛斯的公寓", "主人房"],
    ]

    print("Address availability:")
    for address in required_addresses:
        coords = exact_tiles(maze, address)
        non_collision = [c for c in coords if not maze.tile_at(c).collision]
        print(f"  {address}: tiles={len(coords)}, non_collision={len(non_collision)}")
        if not coords:
            raise RuntimeError(f"Missing required address: {address}")

    print("Old address residue:")
    for address in old_addresses:
        count = len(exact_tiles(maze, address))
        print(f"  {address}: tiles={count}")
        if count:
            raise RuntimeError(f"Old address still present: {address}")

    print("Persona coords:")
    for name in [item["name"] for item in RESIDENTS] + ["用户分身"]:
        data = load_json(AGENTS_DIR / name / "agent.json")
        coord = tuple(data["coord"])
        if maze.tile_at(coord).collision:
            raise RuntimeError(f"{name} is placed on a collision tile: {coord}")
        living_area = data["spatial"]["address"]["living_area"]
        if not exact_tiles(maze, living_area):
            raise RuntimeError(f"{name} has invalid living_area: {living_area}")
        print(f"  {name}: coord={list(coord)}, living_area={living_area}")


def main() -> None:
    maze_config = rename_maze()
    maze = make_maze(maze_config)
    for spec in RESIDENTS:
        write_resident(maze, spec)
    write_user_avatar(maze)
    write_town()
    validate(maze)
    print("Village build complete.")


if __name__ == "__main__":
    main()

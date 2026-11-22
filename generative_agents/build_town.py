"""从零生成小镇场景:地图(tilemap.json / maze.json)、20 位居民人设、居民名单。

用法(在 generative_agents/ 目录下):
    python build_town.py            # 重新生成全部场景文件并自检
    python build_town.py --render   # 另外输出一张带地名标注的地图图片 docs/resources/town_map.png

地图布局、家具摆放、地址(sector/arena/object)都写在本文件里,改这里再重跑即可。
居民文字设定在 data/town_residents.json。
"""

from __future__ import annotations

import argparse
import json
import random
from collections import deque
from pathlib import Path

BASE = Path(__file__).resolve().parent
ASSETS = BASE / "frontend/static/assets/village"
TILEMAP_PATH = ASSETS / "tilemap/tilemap.json"
MAZE_PATH = ASSETS / "maze.json"
AGENTS_DIR = ASSETS / "agents"
RESIDENTS_PATH = BASE / "data/town_residents.json"
TOWN_PATH = BASE / "data/town.json"
TOWN20_PATH = BASE / "data/town_20.json"
RENDER_PATH = BASE.parent / "docs/resources/town_map.png"

WORLD = "the Ville"
W, H = 54, 64
TILE = 32

# 图块集(素材图片不变,只登记编号起点)
TILESETS = [
    ("CuteRPG_Field_B", 1, 16, 256),
    ("CuteRPG_Field_C", 257, 16, 256),
    ("CuteRPG_Harbor_C", 513, 16, 256),
    ("Room_Builder_32x32", 769, 76, 8284),
    ("CuteRPG_Village_B", 9053, 16, 256),
    ("CuteRPG_Forest_B", 9309, 16, 256),
    ("CuteRPG_Desert_C", 9565, 16, 256),
    ("CuteRPG_Mountains_B", 9821, 16, 256),
    ("CuteRPG_Desert_B", 10077, 16, 256),
    ("CuteRPG_Forest_C", 10333, 16, 256),
    ("interiors_pt1", 10589, 16, 5008),
    ("interiors_pt2", 15597, 16, 5008),
    ("interiors_pt3", 20605, 16, 5008),
    ("interiors_pt4", 25613, 16, 2000),
    ("interiors_pt5", 27613, 16, 4512),
    ("blocks", 32125, 10, 80),
]
TILESET_FILES = {"blocks": "blocks_1"}

BG, EG, ED1, ED2, IG, WALL, F1, F2, FG1, FG2, COL = (
    "Bottom Ground",
    "Exterior Ground",
    "Exterior Decoration L1",
    "Exterior Decoration L2",
    "Interior Ground",
    "Wall",
    "Interior Furniture L1",
    "Interior Furniture L2 ",
    "Foreground L1",
    "Foreground L2",
    "Collisions",
)
LAYERS = [BG, EG, ED1, ED2, IG, WALL, F1, F2, FG1, FG2, COL]

GRASS = 2
COLLIDE = 32125
WOOD = 490
HOME_FLOOR = [4874, 4875, 4876, 4950, 4951, 4952, 4953, 5026, 5028, 5029, 5102,
              5103, 5104, 5105, 5178, 5179, 5180, 5181, 5254, 5255, 5256, 5257]
PAVING = [9246, 9247, 9262, 9263, 9278, 9279, 9294, 9295]
GRASS_DECO = [7, 8, 9, 10, 11, 15, 16, 22, 38, 54, 73, 89, 105]

WALL_STYLES = {
    "home": dict(TL=(5983, 6059), TM=(6136, 6212), TR=(5986, 6062), L=6135, R=6138,
                 BL=6363, BM=6364, BR=6366),
    "shop": dict(TL=(6515, 6591), TM=(6668, 6744), TR=(6518, 6594), L=6667, R=6670,
                 BL=6895, BM=6896, BR=6898),
}

# 家具"图章":layers 里每层一个二维编号表(0 = 空);collide 为挡路的格子;
# use 为"使用这件家具时站的格子"(可走,会写上物件地址)。坐标都相对图章左上角。
STAMPS = {
    "bed": dict(layers={F2: [[13289, 13290], [13305, 13306], [13321, 13322]]},
                collide=[(0, 0), (1, 0), (0, 1), (1, 1)], use=[(0, 2), (1, 2)]),
    "dresser": dict(layers={F1: [[13453, 13454], [13469, 13470]]},
                    collide=[(0, 0), (1, 0), (0, 1), (1, 1)], use=[(1, 2)]),
    "desk": dict(layers={F1: [[15912, 0], [15928, 15952], [15944, 15968]], FG1: [[15912, 0]]},
                 collide=[(0, 0), (0, 1), (0, 2)], use=[(1, 1), (1, 2)]),
    "stove": dict(layers={F1: [[19131], [19163], [19179]], F2: [[14821], [14822]]},
                  collide=[(0, 0), (0, 1), (0, 2)], use=[(-1, 0), (-1, 1)]),
    "table": dict(layers={F1: [[15986, 15987, 15952], [16002, 16003, 15968]]},
                  collide=[(1, 0), (1, 1)], use=[(0, 0), (0, 1), (2, 0), (2, 1)]),
    "fridge": dict(layers={F1: [[17673, 17674], [17689, 17690], [17705, 17706]],
                           FG2: [[17673, 17674]]},
                   collide=[(0, 0), (1, 0), (0, 1), (1, 1), (0, 2), (1, 2)], use=[]),
    "utensils": dict(layers={F2: [[14973, 14974], [14989, 14990]]}, collide=[], use=[]),
    "cooktop": dict(layers={F1: [[0, 0, 0], [0, 0, 0], [18569, 18570, 18570]],
                            F2: [[0, 0, 0], [14821, 14822, 0]],
                            FG1: [[0, 0, 0], [0, 0, 0], [18569, 18570, 18570]]},
                    collide=[(0, 2), (1, 2), (2, 2)], use=[(0, 3), (1, 3), (2, 3)]),
    "shelf": dict(layers={F1: [[20149, 20148], [20165, 20164]], FG1: [[20149, 20148]]},
                  collide=[(0, 0), (1, 0), (0, 1), (1, 1)], use=[(0, 2), (1, 2)]),
    "case": dict(layers={F1: [[22359, 22358], [22375, 22374], [22391, 22390]],
                         FG1: [[22359, 22358]]},
                 collide=[(0, 0), (1, 0), (0, 1), (1, 1)], use=[(0, 2), (1, 2)]),
    "cooler": dict(layers={F1: [[10881, 10882], [10897, 10898], [10913, 10914]],
                           FG1: [[10881, 10882]]},
                   collide=[(0, 0), (1, 0), (0, 1), (1, 1)], use=[(0, 2), (1, 2)]),
    "produce": dict(layers={F1: [[17405], [17421], [17437]]},
                    collide=[(0, 0), (0, 1), (0, 2)], use=[(1, 0), (1, 1), (1, 2)]),
    "bookshelf": dict(layers={F1: [[15609, 15610, 15611, 15612], [15625, 15626, 15627, 15628],
                                   [15641, 15642, 15643, 15644]],
                              FG1: [[15609, 15610, 15611, 15612]]},
                      collide=[(x, y) for x in range(4) for y in range(3)],
                      use=[(1, 3), (2, 3)]),
    "hanging": dict(layers={F1: [[21193, 21194, 21195, 20835, 20836],
                                 [21209, 21210, 21211, 20851, 20852]]}, collide=[], use=[]),
    "bigtree": dict(layers={ED2: [[10397, 10398, 10399, 10400], [10413, 10414, 10415, 10416],
                                  [10429, 10430, 10431, 10432], [10445, 10446, 10447, 10448],
                                  [10461, 10462, 10463, 10464], [10477, 10478, 10479, 10480]],
                            FG1: [[10397, 10398, 10399, 10400], [10413, 10414, 10415, 10416],
                                  [10429, 10430, 10431, 10432], [10445, 10446, 10447, 10448],
                                  [10461, 10462, 10463, 10464]]},
                    collide=[(x, y) for x in range(4) for y in (1, 2, 3)]
                    + [(1, 4), (2, 4)] + [(x, 5) for x in range(4)],
                    use=[(x, 6) for x in range(-1, 5)] + [(-1, 5), (4, 5), (-1, 4), (4, 4)]),
    "tree": dict(layers={ED2: [[134, 135], [150, 151]]},
                 collide=[(0, 0), (1, 0), (0, 1), (1, 1)], use=[]),
    "bench": dict(layers={ED2: [[9160, 9161], [9176, 9177]]},
                  collide=[(0, 0), (1, 0), (0, 1), (1, 1)], use=[(0, 2), (1, 2)]),
    "well": dict(layers={ED2: [[9099, 9100], [9115, 9116], [9131, 9132]], FG1: [[9099, 9100]]},
                 collide=[(0, 1), (1, 1), (0, 2), (1, 2)], use=[]),
    "flowerbed": dict(layers={ED1: [[55, 87, 71, 103], [87, 71, 103, 55]]},
                      collide=[(x, y) for x in range(4) for y in range(2)],
                      use=[(x, 2) for x in range(4)] + [(x, -1) for x in range(4)]),
    "crates": dict(layers={ED2: [[9186, 9189, 9190], [9202, 9205, 9206]]},
                   collide=[(x, y) for x in range(3) for y in range(2)], use=[]),
}


class TownMap:
    def __init__(self):
        self.rng = random.Random(20261122)
        self.layers = {n: [[0] * W for _ in range(H)] for n in LAYERS}
        self.address = {}  # (x, y) -> [sector, arena, object]
        self.road = set()
        self.reserved = set()  # 不放树的格子
        self.buildings = {}  # sector -> info
        for y in range(H):
            for x in range(W):
                self.layers[BG][y][x] = GRASS

    # ---- 基础绘制 ----
    def put(self, layer, x, y, gid):
        self.layers[layer][y][x] = gid

    def block(self, x, y):
        self.layers[COL][y][x] = COLLIDE

    def blocked(self, x, y):
        return self.layers[COL][y][x] != 0

    def set_addr(self, x, y, addr):
        cur = self.address.get((x, y), [])
        if len(addr) >= len(cur):
            self.address[(x, y)] = list(addr)

    def add_road(self, x0, y0, x1, y1):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.road.add((x, y))
                self.reserved.add((x, y))

    def paint_roads(self):
        # 沙土路按相邻关系选边角图块(81-83 / 97-99 / 113-115)
        for (x, y) in self.road:
            n, s = (x, y - 1) in self.road, (x, y + 1) in self.road
            w, e = (x - 1, y) in self.road, (x + 1, y) in self.road
            row = 0 if not n and s else 2 if n and not s else 1
            col = 0 if not w and e else 2 if w and not e else 1
            self.put(EG, x, y, 81 + row * 16 + col)

    def stamp(self, name, x, y, addr=None):
        """把一件家具盖到地图上;addr 给出时,在它的 use 格写上物件地址。"""
        spec = STAMPS[name]
        for layer, rows in spec["layers"].items():
            for dy, row in enumerate(rows):
                for dx, gid in enumerate(row):
                    if gid:
                        self.put(layer, x + dx, y + dy, gid)
                        self.reserved.add((x + dx, y + dy))
        for dx, dy in spec["collide"]:
            self.block(x + dx, y + dy)
        if addr:
            for dx, dy in spec["use"]:
                if not self.blocked(x + dx, y + dy):
                    self.set_addr(x + dx, y + dy, addr)
                    self.reserved.add((x + dx, y + dy))

    def counter(self, x, y, length, addr):
        """柜台:上排是柜台后面站人的位置(可走),下排挡路。"""
        for i in range(length):
            top, bottom = (22095, 22111) if i == length - 1 else (22094, 22110)
            self.put(F1, x + i, y, top)
            self.put(FG1, x + i, y, top)
            self.put(F1, x + i, y + 1, bottom)
            self.block(x + i, y + 1)
            self.set_addr(x + i, y, addr)

    def building(self, x0, y0, w, h, sector, arena, style, floor, door_dx):
        """画一栋房子:上墙占两行,下墙一行,门开在下墙(两格宽)。返回室内左上角坐标。"""
        st = WALL_STYLES[style]
        x1, y1 = x0 + w - 1, y0 + h - 1
        door = (x0 + door_dx, x0 + door_dx + 1)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                self.reserved.add((x, y))
                self.set_addr(x, y, [sector])
        for x in range(x0, x1 + 1):
            key = "TL" if x == x0 else "TR" if x == x1 else "TM"
            self.put(WALL, x, y0, st[key][0])
            self.put(FG1, x, y0, st[key][0])
            self.put(WALL, x, y0 + 1, st[key][1])
            self.block(x, y0)
            self.block(x, y0 + 1)
            if x in door:
                continue
            gid = st["BL"] if x in (x0, door[1] + 1) else st["BR"] if x in (x1, door[0] - 1) else st["BM"]
            self.put(WALL, x, y1, gid)
            self.put(FG1, x, y1, gid)
            self.block(x, y1)
        for y in range(y0 + 2, y1):
            self.put(WALL, x0, y, st["L"])
            self.put(WALL, x1, y, st["R"])
            self.block(x0, y)
            self.block(x1, y)
        cells = [(x, y) for y in range(y0 + 2, y1) for x in range(x0 + 1, x1)]
        cells += [(x, y1) for x in door]
        for x, y in cells:
            gid = floor if isinstance(floor, int) else self.rng.choice(floor)
            self.put(IG, x, y, gid)
            self.set_addr(x, y, [sector, arena])
        for x in door:  # 门口外一格留空
            self.reserved.add((x, y1 + 1))
        self.buildings[sector] = dict(box=(x0, y0, x1, y1), door=(door[0], y1), arena=arena)
        return x0 + 1, y0 + 2

    # ---- 导出 ----
    def tree_of(self):
        tree = {}
        for addr in self.address.values():
            if len(addr) >= 2:
                objs = tree.setdefault(addr[0], {}).setdefault(addr[1], [])
                if len(addr) == 3 and addr[2] not in objs:
                    objs.append(addr[2])
        return tree

    def maze_config(self):
        tiles = []
        for y in range(H):
            for x in range(W):
                tile = {"coord": [x, y]}
                if (x, y) in self.address:
                    tile["address"] = self.address[(x, y)]
                if self.blocked(x, y):
                    tile["collision"] = True
                if len(tile) > 1:
                    tiles.append(tile)
        group = [n for n, *_ in TILESETS if n not in ("blocks", "Room_Builder_32x32")]
        group.append("Room_Builder_32x32")

        def layer(name, **kw):
            return dict(name=name, tileset_group="group_1", **kw)

        return {
            "world": WORLD,
            "tile_size": TILE,
            "size": [H, W],
            "map": {
                "asset": "map",
                "tileset_groups": {"group_1": group},
                "layers": [layer(BG), layer(EG), layer(ED2), layer(IG),
                           {"name": WALL, "tileset_group": ["CuteRPG_Field_C", "Room_Builder_32x32"]},
                           layer(F1), layer(F2), layer(FG1, depth=2), layer(FG2, depth=2),
                           {"name": COL, "tileset_group": ["blocks"], "depth": -1,
                            "collision": {"exclusion": [-1]}}],
            },
            "camera": {"zoom_factor": 1, "zoom_range": [0.5, 10, 0.01]},
            "tile_address_keys": ["world", "sector", "arena", "game_object"],
            "tiles": tiles,
        }

    def tilemap(self):
        layers = []
        for i, name in enumerate(LAYERS):
            layers.append({
                "data": [g for row in self.layers[name] for g in row],
                "height": H, "width": W, "id": i + 1, "name": name, "opacity": 1,
                "type": "tilelayer", "visible": True, "x": 0, "y": 0,
            })
        tilesets = []
        for name, firstgid, columns, count in TILESETS:
            rows = -(-count // columns)
            tilesets.append({
                "columns": columns, "firstgid": firstgid,
                "image": TILESET_FILES.get(name, name) + ".png",
                "imageheight": rows * TILE, "imagewidth": columns * TILE,
                "margin": 0, "name": name, "spacing": 0, "tilecount": count,
                "tileheight": TILE, "tilewidth": TILE,
            })
        return {
            "compressionlevel": -1, "height": H, "width": W, "infinite": False,
            "layers": layers, "nextlayerid": len(LAYERS) + 1, "nextobjectid": 1,
            "orientation": "orthogonal", "renderorder": "right-down",
            "tiledversion": "1.8.6", "tileheight": TILE, "tilewidth": TILE,
            "tilesets": tilesets, "type": "map", "version": "1.8",
        }


# ---------------------------------------------------------------------------
# 小镇布局
# ---------------------------------------------------------------------------
HOME_ROWS_Y = [2, 11, 44, 53]  # 四排民居的上沿
HOME_X = [5, 14, 23, 32, 41]  # 每排五户
HOME_W, HOME_H = 8, 7
PLAZA = (17, 32, 36, 43)

PUBLIC_TREE_ORDER = ["小广场", "早点铺", "菜市场", "杂货店", "茶馆", "卫生所"]


def home_slots():
    """20 个宅基地,按"核心 10 户先占、均匀分散"的顺序排列。"""
    core, extra = [], []
    for r, y in enumerate(HOME_ROWS_Y):
        for c, x in enumerate(HOME_X):
            (core if (r + c) % 2 == 0 else extra).append((x, y))
    return core + extra


def build_map(residents):
    m = TownMap()

    # 道路:两条竖街 + 五条横巷 + 中央大街,小广场与大街连成一片
    m.add_road(2, 9, 3, 61)
    m.add_road(50, 9, 51, 61)
    for y in (9, 18, 42, 51, 60):
        m.add_road(2, y, 51, y + 1)
    m.add_road(2, 29, 51, 31)
    m.add_road(*PLAZA)

    # 民居
    for person, (x, y) in zip(residents, home_slots()):
        sector = person["name"] + "家"
        ix, iy = m.building(x, y, HOME_W, HOME_H, sector, "屋里", "home", HOME_FLOOR, 3)
        m.stamp("dresser", ix, iy - 1, [sector, "屋里", "衣柜"])
        m.stamp("desk", ix, iy + 1, [sector, "屋里", "书桌"])
        m.stamp("bed", ix + 2, iy, [sector, "屋里", "床"])
        m.stamp("stove", ix + 5, iy, [sector, "屋里", "灶台"])
        person["home"] = sector
        person["coord"] = [ix + 4, iy + 3]

    # 早点铺
    ix, iy = m.building(5, 20, 12, 9, "早点铺", "店堂", "shop", WOOD, 5)
    m.stamp("fridge", ix, iy - 2)
    m.stamp("utensils", ix + 2, iy - 2)
    m.stamp("cooktop", ix + 4, iy - 2, ["早点铺", "店堂", "蒸笼灶台"])
    m.counter(ix, iy + 1, 7, ["早点铺", "店堂", "早点铺柜台"])
    for dx in (0, 4):
        m.stamp("table", ix + dx, iy + 3, ["早点铺", "店堂", "早点铺桌椅"])
    m.stamp("table", ix + 7, iy + 4, ["早点铺", "店堂", "早点铺桌椅"])

    # 菜市场
    ix, iy = m.building(19, 20, 16, 9, "菜市场", "摊位区", "shop", WOOD, 7)
    m.stamp("hanging", ix + 4, iy - 2)
    m.stamp("produce", ix, iy, ["菜市场", "摊位区", "蔬菜摊"])
    m.stamp("produce", ix + 2, iy, ["菜市场", "摊位区", "蔬菜摊"])
    m.stamp("case", ix + 5, iy, ["菜市场", "摊位区", "熟食摊"])
    m.stamp("case", ix + 7, iy, ["菜市场", "摊位区", "熟食摊"])
    m.stamp("cooler", ix + 10, iy, ["菜市场", "摊位区", "鲜肉摊"])
    m.stamp("shelf", ix + 12, iy, ["菜市场", "摊位区", "干货摊"])
    m.stamp("produce", ix, iy + 3, ["菜市场", "摊位区", "水果摊"])
    m.stamp("shelf", ix + 11, iy + 3, ["菜市场", "摊位区", "豆腐摊"])

    # 杂货店
    ix, iy = m.building(37, 20, 12, 9, "杂货店", "店堂", "shop", WOOD, 5)
    m.counter(ix, iy + 1, 4, ["杂货店", "店堂", "杂货店柜台"])
    for dx in (5, 7):
        m.stamp("shelf", ix + dx, iy, ["杂货店", "店堂", "杂货店货架"])
        m.stamp("shelf", ix + dx, iy + 3, ["杂货店", "店堂", "杂货店货架"])
    m.stamp("cooler", ix, iy + 3, ["杂货店", "店堂", "冷饮柜"])

    # 茶馆
    ix, iy = m.building(5, 33, 10, 9, "茶馆", "茶室", "shop", WOOD, 3)
    m.stamp("fridge", ix + 6, iy - 2)
    m.stamp("utensils", ix + 4, iy - 2)
    m.counter(ix, iy, 4, ["茶馆", "茶室", "茶馆柜台"])
    for dx in (0, 4):
        m.stamp("table", ix + dx, iy + 3, ["茶馆", "茶室", "茶桌"])

    # 卫生所
    ix, iy = m.building(39, 33, 10, 9, "卫生所", "诊室", "shop", HOME_FLOOR, 3)
    m.stamp("dresser", ix + 2, iy - 1, ["卫生所", "诊室", "药柜"])
    m.stamp("desk", ix, iy + 1, ["卫生所", "诊室", "诊桌"])
    m.stamp("bed", ix + 5, iy, ["卫生所", "诊室", "病床"])
    m.stamp("table", ix + 4, iy + 4, ["卫生所", "诊室", "候诊椅"])

    # 小广场:露天,整片都算"小广场"
    px0, py0, px1, py1 = PLAZA
    for y in range(py0, py1 + 1):
        for x in range(px0, px1 + 1):
            m.set_addr(x, y, ["小广场", "广场"])
            if m.rng.random() < 0.5:
                m.put(ED1, x, y, m.rng.choice(PAVING))
    m.stamp("bigtree", 25, 33, ["小广场", "广场", "大榕树下"])
    for x, y in ((19, 34), (33, 34), (19, 39), (33, 39)):
        m.stamp("bench", x, y, ["小广场", "广场", "长凳"])
    m.stamp("flowerbed", 20, 37, ["小广场", "广场", "花坛"])
    m.stamp("flowerbed", 30, 37, ["小广场", "广场", "花坛"])
    m.stamp("well", 35, 32)
    m.stamp("crates", 17, 32)

    m.paint_roads()
    decorate(m)
    return m


def decorate(m):
    """在空草地上种树、撒草花(只做装饰,不占道路和门口)。"""
    def free(x, y):
        return (0 <= x < W and 0 <= y < H and (x, y) not in m.reserved
                and not m.blocked(x, y))

    # 树种在地图四边(本来就走不到的一圈)和零星空地上,民居之间的窄缝留着走人
    for _ in range(3000):
        x, y = m.rng.randrange(0, W - 1), m.rng.randrange(0, H - 1)
        cells = [(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)]
        on_edge = x == 0 or x == W - 2 or y == 0 or y == H - 2
        if all(free(*c) for c in cells) and (on_edge or m.rng.random() < 0.02):
            m.stamp("tree", x, y)
    for y in range(H):
        for x in range(W):
            if free(x, y) and m.rng.random() < 0.12:
                m.put(ED1, x, y, m.rng.choice(GRASS_DECO))


# ---------------------------------------------------------------------------
# 居民
# ---------------------------------------------------------------------------
def write_agents(m, residents):
    tree = m.tree_of()
    for person in residents:
        name, home = person["name"], person["home"]
        known = {k: tree[k] for k in PUBLIC_TREE_ORDER}
        known[home] = tree[home]
        data = {
            "name": name,
            "portrait": f"assets/village/agents/{name}/portrait.png",
            "coord": person["coord"],
            "currently": person["currently"],
            "scratch": {
                "age": person["age"],
                "innate": person["innate"],
                "learned": person["learned"],
                "lifestyle": person["lifestyle"],
                "daily_plan": "",
            },
            "spatial": {
                "address": {"living_area": [WORLD, home, "屋里"]},
                "tree": {WORLD: known},
            },
        }
        dump_json(AGENTS_DIR / name / "agent.json", data)


def dump_json(path, data, compact=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        if compact:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# 自检:每个地址都有可走的格子,且从每户家里都走得到
# ---------------------------------------------------------------------------
def validate(m, residents):
    def walkable(x, y):
        return 0 < x < W - 1 and 0 < y < H - 1 and not m.blocked(x, y)

    start = tuple(residents[0]["coord"])
    assert walkable(*start), start
    seen, queue = {start}, deque([start])
    while queue:
        x, y = queue.popleft()
        for c in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if c not in seen and walkable(*c):
                seen.add(c)
                queue.append(c)

    by_addr = {}
    for coord, addr in m.address.items():
        for i in range(1, len(addr) + 1):
            by_addr.setdefault(tuple(addr[:i]), []).append(coord)
    problems = []
    for addr, coords in by_addr.items():
        if len(addr) >= 2 and not any(c in seen for c in coords):
            problems.append("走不到: " + ":".join(addr))
    for person in residents:
        if tuple(person["coord"]) not in seen:
            problems.append("出生点走不到: " + person["name"])
        if (person["home"], "屋里", "床") not in by_addr:
            problems.append("没有床: " + person["name"])
        if not (AGENTS_DIR / person["name"] / "texture.png").exists():
            problems.append("缺少人物贴图: " + person["name"])
    if problems:
        raise RuntimeError("\n".join(problems))
    print(f"自检通过: 地图 {W}x{H}, 地址 {len(by_addr)} 个, 居民 {len(residents)} 人")


# ---------------------------------------------------------------------------
# 渲染成图片(给人看的,模拟本身不需要)
# ---------------------------------------------------------------------------
FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]


def render(m, residents, path, core_count):
    from PIL import Image, ImageDraw, ImageFont

    sheets = []
    for name, firstgid, columns, count in TILESETS:
        if name == "blocks":
            continue
        img = Image.open(TILEMAP_PATH.parent / (name + ".png")).convert("RGBA")
        sheets.append((firstgid, columns, count, img))

    def tile(gid):
        for firstgid, columns, count, img in sheets:
            if firstgid <= gid < firstgid + count:
                i = gid - firstgid
                x, y = i % columns * TILE, i // columns * TILE
                return img.crop((x, y, x + TILE, y + TILE))

    out = Image.new("RGBA", (W * TILE, H * TILE), (0, 0, 0, 255))
    for name in LAYERS:
        if name == COL:
            continue
        for y in range(H):
            for x in range(W):
                gid = m.layers[name][y][x]
                if gid:
                    out.alpha_composite(tile(gid), (x * TILE, y * TILE))

    font_path = next((p for p in FONT_CANDIDATES if Path(p).exists()), None)
    if font_path:
        draw = ImageDraw.Draw(out)
        big, small = ImageFont.truetype(font_path, 34), ImageFont.truetype(font_path, 22)

        def label(text, cx, cy, font, fill):
            box = draw.textbbox((0, 0), text, font=font)
            w, h = box[2] - box[0], box[3] - box[1]
            x, y = cx - w / 2, cy - h / 2
            draw.rounded_rectangle((x - 8, y - 4, x + w + 8, y + h + 10), 8, fill=fill)
            draw.text((x, y), text, font=font, fill=(20, 20, 20, 255))

        core = {p["home"] for p in residents[:core_count]}
        for sector, info in m.buildings.items():
            x0, y0, x1, y1 = info["box"]
            cx = (x0 + x1 + 1) * TILE / 2
            if sector.endswith("家"):
                fill = (255, 236, 150, 235) if sector in core else (215, 225, 240, 235)
                label(sector, cx, (y0 + 0.7) * TILE, small, fill)
            else:
                label(sector, cx, (y0 + 0.8) * TILE, big, (255, 170, 120, 240))
        px0, py0, px1, py1 = PLAZA
        label("小广场", (px0 + px1 + 1) * TILE / 2, (py1 - 0.3) * TILE, big, (255, 170, 120, 240))
    else:
        print("未找到中文字体,图片不带地名标注")
    path.parent.mkdir(parents=True, exist_ok=True)
    out.convert("RGB").save(path)
    print("地图图片:", path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true", help="同时输出带标注的地图图片")
    args = parser.parse_args()

    spec = json.loads(RESIDENTS_PATH.read_text(encoding="utf-8"))
    residents, core_count = spec["residents"], spec["core_count"]
    m = build_map(residents)
    dump_json(TILEMAP_PATH, m.tilemap(), compact=True)
    dump_json(MAZE_PATH, m.maze_config(), compact=True)
    write_agents(m, residents)
    names = [p["name"] for p in residents]
    dump_json(TOWN_PATH, {"personas": names[:core_count]})
    dump_json(TOWN20_PATH, {"personas": names})
    validate(m, residents)
    if args.render:
        render(m, residents, RENDER_PATH, core_count)


if __name__ == "__main__":
    main()

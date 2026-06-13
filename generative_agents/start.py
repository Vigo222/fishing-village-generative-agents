import os
import copy
import json
import argparse
import datetime

from dotenv import load_dotenv, find_dotenv

from modules.game import create_game, get_game
from modules import memory, utils


# 居民名单从 data/town.json 读取(裁剪小镇规模只改配置);文件缺失时回退到原版 25 人
def load_personas():
    town_file = "data/town.json"
    if os.path.exists(town_file):
        with open(town_file, "r", encoding="utf-8") as f:
            return json.load(f)["personas"]
    return [
        "阿伊莎", "克劳斯", "玛丽亚", "沃尔夫冈",  # 学生
        "梅", "约翰", "埃迪",  # 家庭：教授、药店主人、学生
        "简", "汤姆",  # 家庭：家庭主妇、市场主人
        "卡门", "塔玛拉",  # 室友：供应店主人、儿童读物作家
        "亚瑟", "伊莎贝拉",  # 酒吧老板、咖啡馆老板
        "山姆", "詹妮弗",  # 家庭：退役军官、水彩画家
        "弗朗西斯科", "海莉", "拉吉夫", "拉托亚",  # 共居空间：喜剧演员、作家、画家、摄影师
        "阿比盖尔", "卡洛斯", "乔治", "瑞恩", "山本百合子", "亚当",  # 动画师、诗人、数学家、软件工程师、税务律师、哲学家
    ]


personas = load_personas()

# 热注入"到场事件"文本:主实验控制变量,两组逐字一致;
# 居民反应过冷时只允许改这里的文本(两组同步),严禁改动 percept/_reaction 机制
ARRIVAL_OBJECT = "刚抵达村子，正在打量四周"
ARRIVAL_DESCRIBE = "{name}是刚来到村子的陌生面孔，正站在路边打量四周"


class SimulateServer:
    def __init__(self, name, static_root, checkpoints_folder, config, start_step=0, verbose="info", log_file="", inject_plan=None):
        self.name = name
        self.static_root = static_root
        self.checkpoints_folder = checkpoints_folder
        # 热注入计划(触发器A):{step: [agent_name, ...]}
        self.inject_plan = inject_plan or {}

        # 历史存档数据（用于断点恢复）
        self.config = config

        os.makedirs(checkpoints_folder, exist_ok=True)

        # 载入历史对话数据（用于断点恢复）
        self.conversation_log = f"{checkpoints_folder}/conversation.json"
        if os.path.exists(self.conversation_log):
            with open(self.conversation_log, "r", encoding="utf-8") as f:
                conversation = json.load(f)
        else:
            conversation = {}

        if len(log_file) > 0:
            self.logger = utils.create_file_logger(f"{checkpoints_folder}/{log_file}", verbose)
        else:
            self.logger = utils.create_io_logger(verbose)

        # 创建游戏
        game = create_game(name, static_root, config, conversation, logger=self.logger)
        game.reset_game()

        self.game = get_game()
        self.tile_size = self.game.maze.tile_size
        self.agent_status = {}
        if "agent_base" in config:
            agent_base = config["agent_base"]
        else:
            agent_base = {}
        for agent_name, agent in config["agents"].items():
            agent_config = copy.deepcopy(agent_base)
            agent_config.update(self.load_static(agent["config_path"]))
            # 叠加存档条目:resume 时 config["agents"][name] 含已保存 coord,
            # 必须覆盖 agent.json 的初始 coord,否则全员被传送回出生点(位置漂移)。
            # fresh 跑时该条目仅含 config_path,coord 保持初始,无影响。
            agent_config.update(agent)
            self.agent_status[agent_name] = {
                "coord": agent_config["coord"],
                "path": [],
            }
        self.think_interval = max(
            a.think_config["interval"] for a in self.game.agents.values()
        )
        self.start_step = start_step

    def simulate(self, step, stride=0):
        timer = utils.get_timer()
        for i in range(self.start_step, self.start_step + step):
            # 热注入检查:固定在每步开头、agent 循环之外(避免迭代中修改 dict)
            self._check_injection(i + 1)
            title = "Simulate Step[{}/{}, time: {}]".format(i+1, self.start_step + step, timer.get_date())
            self.logger.info("\n" + utils.split_line(title, "="))
            for name, status in self.agent_status.items():
                plan = self.game.agent_think(name, status)["plan"]
                agent = self.game.get_agent(name)
                if name not in self.config["agents"]:
                    self.config["agents"][name] = {}
                self.config["agents"][name].update(agent.to_dict())
                if plan.get("path"):
                    status["coord"], status["path"] = plan["path"][-1], []
                self.config["agents"][name].update(
                    # {"coord": status["coord"], "path": plan["path"]}
                    {"coord": status["coord"]}
                )

            sim_time = timer.get_date("%Y%m%d-%H:%M")
            self.config.update(
                {
                    "time": sim_time,
                    "step": i + 1,
                }
            )
            # 保存Agent活动数据
            with open(f"{self.checkpoints_folder}/simulate-{sim_time.replace(':', '')}.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(self.config, indent=2, ensure_ascii=False))
            # 保存对话数据
            with open(f"{self.checkpoints_folder}/conversation.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(self.game.conversation, indent=2, ensure_ascii=False))

            if stride > 0:
                timer.forward(stride)

    # ------------------------------------------------------------------
    # 运行时热注入(自研功能 1)
    # ------------------------------------------------------------------

    def _check_injection(self, step):
        # 触发器A:命令行注入计划(--inject 名字@step,确定性,实验/录播用)
        for name in self.inject_plan.pop(step, []):
            config_path = os.path.join(
                "assets", "village", "agents", name.replace(" ", "_"), "agent.json"
            )
            self.inject_agent(name, config_path, step)

        # 触发器B:监听 checkpoints/<name>/inject/ 目录(真热注入,现场演示用)
        inject_dir = os.path.join(self.checkpoints_folder, "inject")
        if not os.path.isdir(inject_dir):
            return
        for file_name in sorted(os.listdir(inject_dir)):
            if not file_name.endswith(".json"):
                continue
            file_path = os.path.join(inject_dir, file_name)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    persona = json.load(f)
                name = persona["name"]
                config_path = os.path.join(
                    "assets", "village", "agents", name.replace(" ", "_"), "agent.json"
                )
                # 若文件携带完整人设(含 scratch),安装进静态资源目录(素材目录须已存在)
                if "scratch" in persona:
                    config_abs = os.path.join(self.static_root, config_path)
                    os.makedirs(os.path.dirname(config_abs), exist_ok=True)
                    with open(config_abs, "w", encoding="utf-8") as f:
                        f.write(json.dumps(persona, indent=2, ensure_ascii=False))
                self.inject_agent(name, config_path, step)
                os.replace(file_path, file_path + ".done")
            except Exception as e:
                self.logger.error("[INJECT] {} 注入失败: {}".format(file_name, e))
                os.replace(file_path, file_path + ".error")

    def inject_agent(self, name, config_path, step=None):
        if name in self.game.agents:
            self.logger.warning("[INJECT] {} 已在小镇中,跳过".format(name))
            return
        self._validate_persona(os.path.join(self.static_root, config_path))
        agent = self.game.add_agent(name, {"config_path": config_path})
        agent.reset()  # 创建 LLM 实例(原 reset_game 只在启动时执行一次)
        self._mount_arrival(agent)
        self.agent_status[name] = {"coord": list(agent.coord), "path": []}
        self.config["agents"][name] = {"config_path": config_path}
        self.think_interval = max(
            a.think_config["interval"] for a in self.game.agents.values()
        )
        self.logger.info(
            "[INJECT] {} 加入小镇 @ step {} ({})".format(
                name, step, utils.get_timer().get_date("%Y%m%d-%H:%M")
            )
        )

    def _mount_arrival(self, agent):
        """挂"到场事件"(绕开 percept 的空闲过滤)+ 写入种子记忆(来意)"""
        address = agent.get_tile().get_address("game_object", as_list=True)
        arrival = memory.Event(
            agent.name,
            "此时",
            ARRIVAL_OBJECT,
            describe=ARRIVAL_DESCRIBE.format(name=agent.name),
            address=address,
            emoji="🧳",
        )
        agent.action = memory.Action(
            arrival,
            memory.Event(address[-1], address=address),
            duration=self.config.get("stride", 10),
            start=utils.get_timer().get_date(),
        )
        agent.move(agent.coord)  # 重新把到场事件挂上 tile,供周围居民 percept
        # 种子记忆:人设的 currently(来意)写成 thought 节点,注入初期对话有内容可说
        # 注意:这意味着反思关闭组中"无 thought 节点"的断言仅对居民成立(批准条件4)
        if agent.scratch.currently:
            event = agent.make_event(
                agent.name, agent.scratch.currently, agent.get_tile().get_address()
            )
            agent._add_concept("thought", event)

    @staticmethod
    def _validate_persona(path):
        """注入前校验人设文件,缺字段立即报错(而非深夜才暴露)"""
        data = utils.load_dict(path)
        missing = [k for k in ("name", "coord", "currently", "scratch", "spatial") if k not in data]
        for k in ("age", "innate", "learned", "lifestyle"):
            if k not in data.get("scratch", {}):
                missing.append("scratch." + k)
        if "living_area" not in data.get("spatial", {}).get("address", {}):
            missing.append("spatial.address.living_area")
        if "tree" not in data.get("spatial", {}):
            missing.append("spatial.tree")
        if missing:
            raise ValueError("人设文件 {} 缺少字段: {}".format(path, ", ".join(missing)))
        return data

    def load_static(self, path):
        return utils.load_dict(os.path.join(self.static_root, path))


# 解析 --inject 参数:"用户分身@12" 或 "A@3,B@5" → {step: [names]}
def parse_inject_plan(spec):
    plan = {}
    for item in [s.strip() for s in spec.split(",") if s.strip()]:
        name, sep, step_str = item.partition("@")
        if not sep or not step_str.strip().isdigit():
            raise ValueError("--inject 格式错误: '{}' (应为 名字@step)".format(item))
        plan.setdefault(int(step_str.strip()), []).append(name.strip())
    return plan


# 从存档数据中载入配置，用于断点恢复
def get_config_from_log(checkpoints_folder):
    files = sorted(os.listdir(checkpoints_folder))

    json_files = list()
    for file_name in files:
        if file_name.endswith(".json") and file_name != "conversation.json":
            json_files.append(os.path.join(checkpoints_folder, file_name))

    if len(json_files) < 1:
        return None

    with open(json_files[-1], "r", encoding="utf-8") as f:
        config = json.load(f)

    assets_root = os.path.join("assets", "village")

    start_time = datetime.datetime.strptime(config["time"], "%Y%m%d-%H:%M")
    start_time += datetime.timedelta(minutes=config["stride"])
    config["time"] = {"start": start_time.strftime("%Y%m%d-%H:%M")}
    agents = config["agents"]
    for a in agents:
        config["agents"][a]["config_path"] = os.path.join(assets_root, "agents", a.replace(" ", "_"), "agent.json")

    return config


# 为新游戏创建配置
def get_config(start_time="20240213-09:30", stride=15, agents=None):
    with open("data/config.json", "r", encoding="utf-8") as f:
        json_data = json.load(f)
        agent_config = json_data["agent"]

    assets_root = os.path.join("assets", "village")
    config = {
        "stride": stride,
        "time": {"start": start_time},
        "maze": {"path": os.path.join(assets_root, "maze.json")},
        "agent_base": agent_config,
        "agents": {},
    }
    for a in agents:
        config["agents"][a] = {
            "config_path": os.path.join(
                assets_root, "agents", a.replace(" ", "_"), "agent.json"
            ),
        }
    return config


load_dotenv(find_dotenv())

parser = argparse.ArgumentParser(description="console for village")
parser.add_argument("--name", type=str, default="", help="The simulation name")
parser.add_argument("--start", type=str, default="20240213-09:30", help="The starting time of the simulated ville")
parser.add_argument("--resume", action="store_true", help="Resume running the simulation")
parser.add_argument("--step", type=int, default=10, help="The simulate step")
parser.add_argument("--stride", type=int, default=10, help="The step stride in minute")
parser.add_argument("--verbose", type=str, default="debug", help="The verbose level")
parser.add_argument("--log", type=str, default="", help="Name of the log file")
parser.add_argument("--agents", type=str, default="", help="Override personas, e.g. '伊莎贝拉,克劳斯' (test only)")
parser.add_argument("--inject", type=str, default="", help="Hot-injection plan, e.g. '用户分身@12' or 'A@3,B@5'")
parser.add_argument("--reflect", type=str, default="", choices=["", "on", "off"], help="Override reflection switch (main experiment variable); empty=use config")
args = parser.parse_args()


if __name__ == "__main__":
    checkpoints_path = "results/checkpoints"

    name = args.name
    if len(name) < 1:
        name = input("Please enter a simulation name (e.g. sim-test): ")

    resume = args.resume
    if resume:
        while not os.path.exists(f"{checkpoints_path}/{name}"):
            name = input(f"'{name}' doesn't exists, please re-enter the simulation name: ")
    else:
        while os.path.exists(f"{checkpoints_path}/{name}"):
            name = input(f"The name '{name}' already exists, please enter a new name: ")

    checkpoints_folder = f"{checkpoints_path}/{name}"

    start_time = args.start
    if resume:
        sim_config = get_config_from_log(checkpoints_folder)
        if sim_config is None:
            print("No checkpoint file found to resume running.")
            exit(0)
        start_step = sim_config["step"]
    else:
        if args.agents:
            personas = [a.strip() for a in args.agents.split(",") if a.strip()]
        sim_config = get_config(start_time, args.stride, personas)
        start_step = 0

    inject_plan = parse_inject_plan(args.inject) if args.inject else {}

    # 主实验变量:--reflect on/off 覆盖 config 的 think.reflect(对照组屏蔽反思)
    if args.reflect:
        sim_config.setdefault("agent_base", {}).setdefault("think", {})["reflect"] = (args.reflect == "on")

    static_root = "frontend/static"

    server = SimulateServer(name, static_root, checkpoints_folder, sim_config, start_step, args.verbose, args.log, inject_plan)
    server.simulate(args.step, args.stride)

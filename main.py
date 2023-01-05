import re
import sys
import threading
import time
import traceback
from copy import deepcopy
from math import atan, sqrt, pi
from typing import Dict, Set, Optional

import pymem
from pynput import mouse, keyboard
from pynput.keyboard import Key

from classes import WindowsInfo, Player, Signature, Bone, Team
from config import Config
from utils import draw_rect, draw_ellipse, draw_line, exit_

sys.path.append('hazedumper')

ERROR = None


def try_except(func):
    def wrapper(*args, **kwargs):
        global ERROR
        try:
            res = func(*args, **kwargs)
            return res
        except Exception as e:
            print(e)  # , traceback.format_exc())
            ERROR = True
            return None

    return wrapper


class Cheat:
    LOCK_AIM = False  # 是否自瞄
    LOCK_ALL = False  # 仅敌人还是全部锁定
    DRAW_LINE = False  # 是否绘制射线
    THREAD_DICT = {}  # 线程字典

    def __init__(self, process_name: str = "csgo.exe"):
        self.__current_angle = None
        self.client_state = None
        self.mem = pymem.Pymem(process_name)
        # 游戏进程名称
        self.__process_name = process_name

        # 挂载 hazedumper 的 csgo 配置
        self.__config = Config()

        # 挂载默认模块
        self.__client = self.__get_module("client.dll")
        self.__engine = self.__get_module("engine.dll")

        # 初始化屏幕信息
        self.__windows_x = WindowsInfo.x
        self.__windows_y = WindowsInfo.y
        self.__windows_w = WindowsInfo.w
        self.__windows_h = WindowsInfo.h

        # 初始化用户字典 {team_id: {Player1, ...}}
        self.__player_dict: Dict[int, Set[Player]] = dict()

        # 游戏特征初始化
        self.signature: Signature = Signature()
        self.signature.dwClientState = self._signature("dwClientState")  # 客户端偏移
        self.signature.dwEntityList = self._signature("dwEntityList")  # 玩家数组偏移
        self.signature.dwLocalPlayer = self._signature("dwLocalPlayer")  # 本地玩家偏移
        self.signature.dwViewMatrix = self._signature("dwViewMatrix")  # 视图矩阵偏移
        self.signature.m_iTeamNum = self._signature("m_iTeamNum")  # 玩家阵营id 偏移， 2为t, 3为ct
        self.signature.m_iHealth = self._signature("m_iHealth")  # 玩家血量偏移
        self.signature.m_iGlowIndex = self._signature("m_iGlowIndex")  # 玩家光学阴影偏移
        self.signature.m_vecOrigin = self._signature("m_vecOrigin")  # 玩家坐标偏移，此处默认为最低点坐标
        self.signature.m_ArmorValue = self._signature("m_ArmorValue")  # 玩家护甲值偏移
        self.signature.m_dwBoneMatrix = self._signature("m_dwBoneMatrix")  # 骨骼节点矩阵偏移
        self.signature.m_aimPunchAngle = self._signature("m_aimPunchAngle")  # 瞄准冲压角度偏移
        self.signature.m_iShotsFired = self._signature("m_iShotsFired")  # 是否开枪
        self.signature.m_vecViewOffset = self._signature("m_vecViewOffset")  # 视图偏移
        self.signature.dwGlowObjectManager = self._signature("dwGlowObjectManager")  # 光学跟踪
        self.signature.dwClientState_ViewAngles = self._signature("dwClientState_ViewAngles")  # 玩家视角偏移

        # 光学跟踪
        self.__glow_manager = self.mem.read_uint(self.__client.lpBaseOfDll + self.signature.dwGlowObjectManager)

        # 矩阵初始化
        self.matrix = [[.0, .0, .0, .0],
                       [.0, .0, .0, .0],
                       [.0, .0, .0, .0],
                       [.0, .0, .0, .0]]
        self.__temp_matrix = range(0, 64, 4)

        # 初始化离我最近的敌人
        self.__nearest_enemy: Optional[Player, None] = None

        # 初始化自瞄范围
        self.__aim_range = 60

    def __get_module(self, dll):
        """获取对应模块的信息"""
        return pymem.process.module_from_name(self.mem.process_handle, dll)

    def __get_module_base_addr(self, dll: str):
        """获取模块基址"""
        # modules = {module.name: module.lpBaseOfDll for module in self.mem.list_modules()}
        return self.__get_module(dll).lpBaseOfDll

    @staticmethod
    def __search_data(data_l, key):
        """查询指定索引值的特征"""
        data_l = deepcopy(data_l)
        for data in data_l:
            if key == data["name"]:
                data.pop("name")
                pattern = data.get("pattern")
                if pattern:
                    new = pattern.replace("?", ".").split(" ")
                    newone = ""
                    for element in new:
                        if element != ".":
                            element = r'\x' + element
                        newone += element
                    data["pattern"] = bytes(newone, encoding="raw_unicode_escape")

                return data

    def __get_sig(self, extra=0, relative=True, module=None, offsets=None, pattern=None):
        """获取特征"""
        module = self.__get_module(module)
        raw_text = self.mem.read_bytes(module.lpBaseOfDll, module.SizeOfImage)

        match = re.search(pattern, raw_text).start()

        if not offsets:
            res = match + extra
            return res
        if not offsets[0]:
            res = match + extra
            return res
        offset = offsets[0]

        non_relative = self.mem.read_int(module.lpBaseOfDll + match + offset) + extra
        yes_relative = self.mem.read_int(module.lpBaseOfDll + match + offset) + extra - module.lpBaseOfDll
        return yes_relative if relative else non_relative

    def __get_config_signature_data(self, name):
        """获取指定索引的特征信息"""
        return self.__search_data(self.__config.config_info.signatures, name)

    def __get_config_net_vars_data(self, name):
        """获取网络数据 net_vars 中的偏移"""
        return self.__search_data(self.__config.config_info.netvars, name)

    def _signature(self, name):
        """获取指定索引的特征偏移"""
        # return self.__get_sig(**self.__get_config_signature_data(name))
        signature = self.__config.csgo_info.signatures.get(name)
        if signature:
            return self.__config.csgo_info.signatures[name]
        else:
            prop = self.__get_config_net_vars_data(name)["prop"]
            if '[' in prop:
                prop_list = re.split(r'[\[\]]', prop)
                prop = prop_list[0]
                if prop[1].isdigit():
                    offsets = int(prop[1])
                else:
                    offsets = 0
                offset = self.__get_config_net_vars_data(name).get("offset", 0)
                offset += offsets
            else:
                offset = self.__get_config_net_vars_data(name).get("offset", 0)

            return self.__config.csgo_info.netvars[prop] + offset

    def __get_self_info(self):
        """获取自身数据"""
        entity = self.mem.read_uint(self.__client.lpBaseOfDll + self.signature.dwLocalPlayer)
        team_id = self.mem.read_uint(entity + self.signature.m_iTeamNum)

        healthy_blood = self.mem.read_uint(entity + self.signature.m_iHealth)

        location_x = self.mem.read_float(entity + self.signature.m_vecOrigin)
        location_y = self.mem.read_float(entity + self.signature.m_vecOrigin + 4)
        location_z = self.mem.read_float(entity + self.signature.m_vecOrigin + 8)

        armor = self.mem.read_uint(entity + self.signature.m_ArmorValue)
        squat = self.mem.read_float(entity + 0x110)

        self.__myself = Player(
            entity,
            team_id=team_id,
            is_self=True,
            location=(location_x, location_y, location_z),
            healthy_blood=healthy_blood,
            armor=armor,
            squat=squat,
        )
        self.__get_body_bone(self.__myself)
        self.__player_dict[team_id] = {
            self.__myself
        }

    def __init_player_entities(self):
        """初始化该局游戏内的人物信息"""

        for i in range(0, 64):  # Looping through all entities

            entity = self.mem.read_uint(self.__client.lpBaseOfDll + self.signature.dwEntityList + i * 0x10)
            if entity and entity != self.__myself.entity:

                entity_team_id = self.mem.read_uint(entity + self.signature.m_iTeamNum)
                team = self.__player_dict.get(entity_team_id)
                if team:
                    team.add(Player(
                        entity,
                        team_id=entity_team_id,
                    ))
                else:
                    self.__player_dict[entity_team_id] = {
                        Player(
                            entity,
                            team_id=entity_team_id,
                        )
                    }

    def __get_player_list(self):
        """获取对局中的玩家信息"""
        self.__get_self_matrix()
        best_xy = None

        for team, players in self.__player_dict.items():
            players_list = list(players)

            for player in players_list:
                entity = player.entity
                # 血量
                player.healthy_blood = self.mem.read_uint(entity + self.signature.m_iHealth)
                # 护甲
                player.armor = self.mem.read_uint(entity + self.signature.m_ArmorValue)
                location_x = self.mem.read_float(entity + self.signature.m_vecOrigin)
                location_y = self.mem.read_float(entity + self.signature.m_vecOrigin + 4)
                location_z = self.mem.read_float(entity + self.signature.m_vecOrigin + 8)
                player.location = (location_x, location_y, location_z)

                player.squat = self.mem.read_float(entity + 0x110)

                # 骨骼
                if self.__get_body_bone(player):
                    continue

                player = self.__draw(player)
                # 仅可绘制的玩家才会计入自瞄
                if player:
                    x_min, y_min = (
                        (self.__windows_w - self.__aim_range) / 2,
                        (self.__windows_h - self.__aim_range) / 2,
                    )
                    x_max, y_max = x_min + self.__aim_range, y_min + self.__aim_range
                    if not (x_max > player.screen[0] > x_min and y_max > player.screen[1] > y_min):
                        continue
                    # 全局瞄准时才会锁定队友
                    if not self.LOCK_ALL:
                        if player.team_id == self.__myself.team_id:
                            continue
                    p_x, p_y = player.screen
                    m_x, m_y = x_max - self.__aim_range / 2, y_max - self.__aim_range / 2

                    # p_x, p_y, _ = player.location
                    # m_x, m_y, _ = self.__myself.location
                    dist = (p_x - m_x) ** 2 + (p_y - m_y) ** 2

                    if not best_xy:
                        best_xy = (player, dist)
                    else:
                        _, old_dist = best_xy
                        if dist < old_dist:
                            best_xy = (player, dist)

        if best_xy:
            self.__nearest_enemy, _ = best_xy

    def __get_self_matrix(self):
        """获取自身的矩阵信息"""
        index = 0
        for i in range(0, 16, 4):
            temp_list = []
            for v in self.__temp_matrix[i:i + 4]:
                # temp_list.append(self.mem.read_float(self.__client.lpBaseOfDll + 0x4DF0E54 + v))
                temp_list.append(self.mem.read_float(self.__client.lpBaseOfDll + self.signature.dwViewMatrix + v))
            self.matrix[index] = temp_list
            index += 1

    def __get_body_bone(self, player):
        """获取身体骨骼节点"""
        bone_base_addr = self.mem.read_uint(player.entity + self.signature.m_dwBoneMatrix)
        body = [self.mem.read_float(bone_base_addr + i) for i in range(12, 45, 16)]
        # 最高点
        highest = [self.mem.read_float(bone_base_addr + i + (2 * 0x30)) for i in range(12, 45, 16)]
        # 头
        head = [self.mem.read_float(bone_base_addr + i + (8 * 0x30)) for i in range(12, 45, 16)]
        # 最低点
        lowest = [self.mem.read_float(bone_base_addr + i + (1 * 0x30)) for i in range(12, 45, 16)]
        player.bone = Bone(
            body=body, head=head,
            highest=highest, lowest=lowest
        )

    def __start_thread(self, target, args=None, kwargs=None):
        if isinstance(target, str):
            target = getattr(self, "_Cheat" + target)

        glow_thread = self.THREAD_DICT.get(str(target))
        if not glow_thread:
            if args is None:
                args = tuple()
            if kwargs is None:
                kwargs = dict()
            glow_thread = threading.Thread(target=target, args=args, kwargs=kwargs)
        glow_thread.start()

    def __world2screen(self, location, win_w, win_h):
        """世界坐标转屏幕坐标"""
        p_X = (self.matrix[0][0] * location[0] + self.matrix[0][1] * location[1] + self.matrix[0][2] * location[2]
               + self.matrix[0][3])
        p_Y = (self.matrix[1][0] * location[0] + self.matrix[1][1] * location[1] + self.matrix[1][2] * location[2]
               + self.matrix[1][3])
        # p_Z = (self.matrix[2][0] * location[0] + self.matrix[2][1] * location[1] + self.matrix[2][2] * location[2]
        #        + self.matrix[2][3])
        p_W = (self.matrix[3][0] * location[0] + self.matrix[3][1] * location[1] + self.matrix[3][2] * location[2]
               + self.matrix[3][3])
        if p_W < 0.1:
            return False, (0, 0)

        ndc_X = p_X / p_W
        ndc_Y = p_Y / p_W

        screen_X = (win_w / 2 * ndc_X) + (ndc_X + win_w / 2)
        screen_Y = -(win_h / 2 * ndc_Y) + (ndc_Y + win_h / 2)

        if self.__windows_x <= screen_X <= self.__windows_x + win_w and self.__windows_y <= screen_Y <= self.__windows_y + win_h:
            return True, (
                screen_X,
                screen_Y,
            )
        else:
            return False, (0, 0)

    def __draw(self, player: Player):
        """绘制"""

        if player.is_self:  # 绘制除自身之外的人
            return
        # 光学阴影设置
        self.__start_thread(target="__set_glow", args=(player,))
        effective, draw_location = self.__world2screen(player.bone.head, self.__windows_w, self.__windows_h)
        # effective, draw_location = self.__world2screen(player.location, self.__windows_w, self.__windows_h)
        if effective:

            if player.healthy_blood > 0:
                lowest = self.__world2screen(player.bone.lowest, self.__windows_w, self.__windows_h)
                distance = sqrt(
                    (self.__myself.location[0] - player.location[0]) ** 2
                    + (self.__myself.location[1] - player.location[1]) ** 2
                )
                distance /= self.__windows_w / 3
                x, y = draw_location
                screen_xy = [x, y]
                h = abs(y - lowest[1][1]) * 1.06
                # diff_h / h
                w = h / 2
                x -= w / 2
                y += distance
                # y -= diff_h
                screen_xy[1] = y
                player.screen = tuple(screen_xy)
                player.aim_len = self.__get_aim_distance(x + (w / 2), y + (h / 2))

                # 方框
                self.__start_thread(target='__draw_head_rect',
                                    args=(player, (x, y - w / 4, w, h)))

                # 跟踪射线
                self.__start_thread(target='__draw_radial', args=(player,))

                return player

    @try_except
    def __draw_radial(self, player):
        if self.DRAW_LINE:
            if self.LOCK_ALL:
                draw_line(player.screen, (self.__windows_w / 2, self.__windows_h))
            else:
                if self.__myself.team_id != player.team_id:
                    draw_line(player.screen, (self.__windows_w / 2, self.__windows_h))

    @try_except
    def __draw_head_rect(self, player, rect_loc):
        x, y, w, h = rect_loc
        if player.team_id == self.__myself.team_id:
            color = (0, 255, 0)
            head_color = (0, 255, 55)
        else:
            color = (255, 0, 0)
            head_color = (255, 0, 55)
        # # 身体方框
        # draw_rect((x, y, w, h), color)
        # 头部方框
        draw_rect((x + w * 5 / 12, y, w / 4, w / 4), head_color, 2)

    @try_except
    def __set_glow(self, player):
        if not self.LOCK_ALL:
            if player.team_id == self.__myself.team_id:
                return

        player_hp = player.healthy_blood
        player_tem_id = player.team_id
        if player_hp == 100:
            if player_tem_id == Team.t:
                r, g, b = 0, 255, 0
            else:
                r, g, b = 0, 255, 0
        elif 50 <= player_hp < 100:
            r, g, b = 255, 165, 0
        else:
            r, g, b = 255, 0, 0
        glow_manager = self.__glow_manager
        entity_glow = self.mem.read_uint(player.entity + self.signature.m_iGlowIndex)
        self.mem.write_float(glow_manager + entity_glow * 0x38 + 0x8, float(r))  # R
        self.mem.write_float(glow_manager + entity_glow * 0x38 + 0xC, float(g))  # G
        self.mem.write_float(glow_manager + entity_glow * 0x38 + 0x10, float(b))  # B
        self.mem.write_float(glow_manager + entity_glow * 0x38 + 0x14, float(255))  # A
        self.mem.write_int(glow_manager + entity_glow * 0x38 + 0x28, 1)  # Enable

    def __get_aim_distance(self, x, y):
        """获取自瞄距离"""
        temp_x = abs(self.__windows_w - x)
        temp_y = abs(self.__windows_h - y)

        aim_len = int(sqrt((temp_x * temp_x) + (temp_y * temp_y)))

        return aim_len

    def __get_aim_angle(self, current_angle, player):
        """获取自瞄视角"""

        aim_location = player.bone.head
        # aim_location = player.bone.body

        x = self.__myself.bone.head[0] - aim_location[0]
        y = self.__myself.bone.head[1] - aim_location[1]
        z = self.__myself.bone.head[2] - aim_location[2] - 2

        # x = self.__myself.location[0] - aim_location[0]
        # y = self.__myself.location[1] - aim_location[1]
        # z = self.__myself.location[2] - aim_location[2] + self.__current_angle[2]

        # 连发时，枪口偏移角度
        y_recoil = self.mem.read_float(self.__myself.entity + self.signature.m_aimPunchAngle)
        x_recoil = self.mem.read_float(self.__myself.entity + self.signature.m_aimPunchAngle + 4)
        shots_fire_num = self.mem.read_int(self.__myself.entity + self.signature.m_iShotsFired)
        if shots_fire_num > 1:
            x -= x_recoil / 2
            z -= y_recoil * ((sqrt(x ** 2 + y ** 2) + 135) * 15 / 653)

        aim_angle = [
            atan(z / sqrt(x ** 2 + y ** 2)) / pi * 180.0,
            atan(y / x)
        ]
        if x >= 0.0 and y >= 0.0:
            aim_angle[1] = aim_angle[1] / pi * 180.0 - 180.0
        elif x < 0.0 and y >= 0.0:
            aim_angle[1] = aim_angle[1] / pi * 180.0
        elif x < 0.0 and y < 0.0:
            aim_angle[1] = aim_angle[1] / pi * 180.0
        elif x >= 0.0 and y < 0.0:
            aim_angle[1] = aim_angle[1] / pi * 180.0 + 180.0

        return aim_angle

    def __get_current_angle(self):
        """获取当前玩家视角"""
        self.__current_angle = [
            self.mem.read_float(self.client_state + self.signature.dwClientState_ViewAngles),
            self.mem.read_float(self.client_state + self.signature.dwClientState_ViewAngles + 0x4),
            self.mem.read_float(self.__myself.entity + self.signature.m_vecViewOffset + 0x8)
        ]

    def __set_current_angle(self, angle):
        """设置当前视角"""
        self.mem.write_float(self.client_state + self.signature.dwClientState_ViewAngles, angle[0])
        self.mem.write_float(self.client_state + self.signature.dwClientState_ViewAngles + 0x4, angle[1])

    @try_except
    def __start_aim(self):
        """开始自瞄"""
        self.__get_current_angle()
        current_angle = self.__current_angle
        player = self.__nearest_enemy
        if player:
            aim_angle = self.__get_aim_angle(current_angle, player)
            if not aim_angle:
                return
            max_fov = 20.0
            if abs(int(aim_angle[0]) - int(current_angle[0])) > max_fov or abs(
                    int(aim_angle[1]) - int(current_angle[1])) > max_fov:
                return
            self.__set_current_angle(aim_angle)

    def __init_cheat(self):
        """"""
        try:
            self.client_state = self.mem.read_uint(
                self.__engine.lpBaseOfDll + self.signature.dwClientState
            )
            if self.client_state:
                self.__get_self_info()
                self.__init_player_entities()
                return True
        except pymem.exception.MemoryReadError:
            return False

    @try_except
    def __init_players(self):
        self.__init_player_entities()
        # milli_sleep(.5)
        self.__get_player_list()

    def start(self, num=1):
        global ERROR
        """入口"""
        __c = num
        if self.__init_cheat():
            __c = 0
            x, y, w, h, = (
                (self.__windows_w - self.__aim_range) / 2,
                (self.__windows_h - self.__aim_range) / 2,
                self.__aim_range,
                self.__aim_range
            )
            flag = True
            while flag:
                try:
                    if ERROR:
                        time.sleep(3)
                        print("=====================重启服务中=====================")
                        flag = False
                        break

                    draw_ellipse((x, y), (x + w, y + h), color=(0, 0, 255))
                    self.__nearest_enemy = None
                    self.__init_players()

                    if self.LOCK_AIM:
                        self.__start_thread(target="__start_aim")
                        # self.__start_aim()
                except KeyboardInterrupt:
                    exit_("感谢使用")
                except OverflowError:
                    print("对局已结束!!!")
                except Exception as e:
                    time.sleep(3)
                    print("重启服务中")
                    self.__init_cheat()
                    print(e, traceback.format_exc())
            if flag is False:
                ERROR = None
                __c += 1
                self.__init__()
                self.start(__c)
        else:
            __c += 1
            if __c < 100:
                time.sleep(3)
                print("重启服务中")
                self.__init__()
                self.start(__c)
            else:
                print("重启过多，启动失败")

    def on_click(self, x, y, button, pressed):
        """鼠标监听"""
        if button == button.x1:  # 左侧键1
            if pressed:
                self.DRAW_LINE = not self.DRAW_LINE
                print('射线状态: ', f"[{self.DRAW_LINE and '开' or '关'}]")
        elif button == button.x2:  # 左侧键2
            if pressed:
                self.LOCK_ALL = not self.LOCK_ALL
                print('自瞄模式: ', f"[{self.LOCK_ALL and '全部' or '仅敌人'}]")

    def on_keyboard_release(self, key):
        if key == Key.ctrl_l:
            self.LOCK_AIM = False
            print('自瞄状态: ', f"[{self.LOCK_AIM and '开' or '关'}]")

    def on_keyboard_press(self, key):
        if key == Key.ctrl_l:
            self.LOCK_AIM = True
            # print('自瞄状态: ', f"[{self.LOCK_AIM and '开' or '关'}]")


if __name__ == '__main__':
    cheat = Cheat()
    mouse_listener = mouse.Listener(on_click=cheat.on_click)
    keyboard_listener = keyboard.Listener(on_press=cheat.on_keyboard_press, on_release=cheat.on_keyboard_release)

    mouse_listener.start()
    keyboard_listener.start()
    cheat.start()

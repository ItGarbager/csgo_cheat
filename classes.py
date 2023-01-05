import threading
from typing import List, Tuple

from utils import get_windows_location


class Bone:
    """骨骼节点"""

    def __init__(
            self, body: List[float], head: List[float],
            highest: List[float] = None, lowest: List[float] = None,
            l_feed: List[float] = None, r_feed: List[float] = None,
    ):
        self.body = body  # 腰部身体节点
        self.head = head  # 头节点
        self.highest = highest  # 最高处节点
        self.lowest = lowest  # 最低处节点
        self.l_feed = l_feed  # 左脚节点
        self.r_feed = r_feed  # 右脚节点


class Player:
    """玩家"""
    _single_lock = threading.Lock()
    _instance = {}

    def __new__(cls, *args, **kwargs):
        if args:
            _entity = args[0]
        else:
            _entity = kwargs.get('entity')
        cls_ = cls._instance.get(_entity)
        if not cls_:
            with cls._single_lock:
                if not cls_:
                    cls_ = super(Player, cls).__new__(cls)
                    cls._instance[_entity] = cls_

        return cls_

    def __init__(
            self,
            entity: int,
            team_id: int,
            effective: bool = True,
            is_self: bool = False,
            location: tuple = None,
            healthy_blood: int = 100,
            armor: int = 100,
            bone: Bone = None,
            aim_len: int = 9999,
            squat: float = 0.0,
            screen: Tuple[float, float] = None,
    ):
        self.entity = entity  # 人物矩阵地址
        self.team_id = team_id  # 队伍id
        self.effective = effective
        self.is_self = is_self  # 是否为自己
        self.location = location  # 位置
        self.healthy_blood = healthy_blood  # 血量
        self.armor = armor  # 盔甲
        self.bone: Bone = bone  # 骨骼
        self.aim_len = aim_len  # 自瞄距离
        self.squat = squat  # squat
        self.screen = screen  # 屏幕坐标

    def __str__(self):
        return "Player(0X%x->{team:%s, self:%s, location:%s, blood:%s, armor:%s})" % (
            self.entity, self.team_id, self.is_self, self.location, self.healthy_blood, self.armor
        )

    __repr__ = __str__


class WindowsInfo:
    """监听屏幕"""
    x, y, w, h = get_windows_location()


class Signature:
    """特征值"""
    dwClientState: int
    dwEntityList: int
    dwViewMatrix: int
    dwLocalPlayer: int
    m_iTeamNum: int
    m_iHealth: int
    m_iGlowIndex: int
    m_vecOrigin: int
    m_ArmorValue: int
    m_iShotsFired: int
    m_dwBoneMatrix: int
    m_aimPunchAngle: int
    m_vecViewOffset: int
    dwGlowObjectManager: int
    dwClientState_ViewAngles: int


class Team:
    """队伍阵营"""
    ct: int = 3
    t: int = 2

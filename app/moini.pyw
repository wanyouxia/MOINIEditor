# -*- coding: utf-8 -*-
"""MO 数值编辑器 — 只改副本，不动原文件。

原理：
  1. 从游戏的 .mix 中提取 rulesmo.ini（只读，绝不改动 mix）。
  2. 把原版 rulesmo.ini 原样复制到游戏根目录（这叫“添加文件”），然后在副本里
     把要改的键就地改掉（其他行一个字节都不动）。
     注意：不能像以前那样在末尾追加 [单位ID] 只写改动的键 —— 引擎对重复节的
     处理是整节替换，那样会把 Owner/Prerequisite 之类全丢掉，单位就造不出来了。
  3. “全部还原”＝删掉根目录那个 rulesmo.ini，游戏回到原版数值。
"""

import os
import re
import sys
import json
import time
import struct
import glob
import random
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    # 打包成 exe：只读资源在解包目录，可写数据放在 exe 旁边（不行就放到用户目录）
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)
    _DATA_CAND = os.path.join(APP_DIR, "MOINIEditor_data")
    try:
        os.makedirs(_DATA_CAND, exist_ok=True)
        _probe = os.path.join(_DATA_CAND, ".w")
        with open(_probe, "w") as _f:
            _f.write("1")
        os.remove(_probe)
        DATA_DIR = _DATA_CAND
    except Exception:
        DATA_DIR = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "MOINIEditor")
        os.makedirs(DATA_DIR, exist_ok=True)
else:
    APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
    RES_DIR = None
    DATA_DIR = os.path.join(APP_DIR, "data")
BASE_FILE = os.path.join(DATA_DIR, "rulesmo.base.ini")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
SETTINGS = os.path.join(DATA_DIR, "settings.txt")
PROFILE_DIR = os.path.join(DATA_DIR, "profiles")
GEO_FILE = os.path.join(DATA_DIR, "geometry.txt")
NOTICE_FILE = os.path.join(DATA_DIR, "notice_ok.txt")

NOTICE_TITLE = "免费声明 / 使用须知"
NOTICE_TEXT = """这个工具是免费软件。

· 免费提供，不收费、不带任何广告，也不要用它卖钱。
· 与 Mental Omega 的制作组（Mentalmeisters）、Ares、CnCNet 都没有官方关系，
  只是玩家自己写的小工具。
· 它只读取游戏里的 .mix，然后在你游戏目录生成一个松散的 rulesmo.ini；
  .mix 本身一个字节都不改，点「全部还原」就删掉生成的那个文件，游戏立刻回原版。
· 改数值只影响你自己这台机器。联机时请保证所有人的 rulesmo.ini 完全一致，
  否则会不同步；版本不同的话，先点「重新提取」再保存。
· 数据出错、游戏崩溃、存档损坏之类的风险需要你自己承担——
  改之前心里有个数，重要存档先备份。

祝玩得开心。"""
CN_FILE = os.path.join(DATA_DIR, "cn_names.json")
FAC_FILE = os.path.join(DATA_DIR, "cn_faction.json")
# 可建造的科技等级范围：1~10。
# 注意：原版 RA2/YR 里 11 是“需要实验室”可造，但**心灵终结把 11 拿去当“不可建造”**了
# （11 级单位正常玩造不出来，只能靠支援技能/渗透/剧情给你），所以上限是 10。
TL_MIN, TL_MAX = 1, 10
C_GRAY = "#6f6585"
C_WARN_ICON = "#ffcc55"
# 纯数字字段的判定（允许正负号与小数，不允许空格/单位/百分号）
NUM_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")
# 步兵移速的合理上限：超过这个数，引擎里会出现抽搐/瞬移
INF_SPEED_MAX = 15
# 渗透（偷科技）单位：原版没写 Owner=/Prerequisite=，靠间谍渗透敌方实验室解锁，
# 正常玩是造得出来的，不能因为“没有 Owner”就灰掉。
STOLEN_TECH = {
    "QUICK", "LIONH", "CHRP", "AHVYBOT2",
    "GRUMBLE", "MAMM", "SYCKLE", "IDRAG",
    "SCAV", "WORMQ", "SEIZER", "SALA",
    "PHNT", "SEITAAD", "ARCH", "RAMW",
}
MYSTERY_FACS = ("盟军", "苏军", "厄普西隆", "焚风")
ART_DIR = os.path.join(RES_DIR, "art") if FROZEN else os.path.join(DATA_DIR, "art")

# 界面配色（MO 客户端那套：深紫底 + 金属板 + 琥珀色高亮）
C_PANEL = "#140f1c"
C_PANEL2 = "#1b1526"
C_EDGE = "#3a2b4e"
C_TEXT = "#e6dff2"
C_DIM = "#a396b8"
C_GOLD = "#ffd28a"
C_WARN = "#ff9d5c"
C_BAD = "#ff6b6b"
C_OK = "#8fe08a"
C_LIST_SEL = "#6b2f8c"
# 全角标点 → 半角（改数值时统一用英文标点，ini 里也只认这个）
_PUNCT_MAP = {
    "，": ",", "。": ".", "、": ",", "；": ",", "：": ":",
    "（": "(", "）": ")", "！": "!", "？": "?",
    "“": '"', "”": '"', "‘": "'", "’": "'",
    "【": "[", "】": "]", "《": "<", "》": ">",
    "－": "-", "—": "-", "～": "~", "　": " ",
    "％": "%", "＃": "#", "＆": "&", "＊": "*",
    "＋": "+", "＝": "=", "｜": "|", "／": "/", "＼": "\\",
    "＠": "@", "＄": "$", "＾": "^", "！": "!", "．": ".",
}
_PUNCT_TABLE = str.maketrans(_PUNCT_MAP)


# 相邻重复的标点只保留一个（E1,,GGI → E1,GGI）
_PUNCT_RUN_RE = re.compile(r"([,.:;!?|/\\\-=_+*&%#$@~])\1+")


def fix_punct(txt):
    """全角标点换半角 + 相邻重复标点合并（中文正文不受影响）。"""
    if not txt:
        return txt
    txt = txt.translate(_PUNCT_TABLE)
    return _PUNCT_RUN_RE.sub(r"\1", txt)


SENTINEL = ";;; ====== MO INI TOOL OVERRIDES (AUTO-GENERATED, DO NOT EDIT) ======"
RULE_FILE_NAME = "rulesmo.ini"
APP_VERSION = "1.2.1"
DEFAULT_GAME_DIR = r"D:\Mental Omega"

KINDS = [
    ("InfantryTypes", "步兵"),
    ("VehicleTypes", "车辆"),
    ("BuildingTypes", "建筑"),
    ("AircraftTypes", "空军"),
]

# 其它节一律归到“其他”

SW_FIELDS = [
    ("RechargeTime", "冷却"),
    ("Money.Amount", "花费"),
    ("Range", "施法距离"),
    ("SW.RangeMaximum", "最大距离"),
    ("SW.Damage", "技能伤害"),
    ("SW.Warhead", "技能弹头"),
    ("SW.Animation", "释放动画"),
    ("SW.AITargeting", "AI 使用"),
    ("SW.Group", "侧边栏分组"),
    ("SW.ShowCameo", "显示图标"),
    ("SW.FireIntoShroud", "可穿烟"),
    ("SW.Inhibitors", "被禁用建筑"),
    ("SW.AuxBuildings", "辅助建筑"),
]
SW_KIND = "支援技能"
DROP_KEY_RE = re.compile(r"^(PARADROP(\.[A-Z0-9_]+)?|DELIVER|DROPPOD)\.TYPES$", re.I)
DROP_KEY_CN = {"PARADROP": "空投单位", "DELIVER": "传送单位", "DROPPOD": "空降舱单位"}
_UNIT_PRI = {"建筑": 0, "步兵": 1, "车辆": 2, "空军": 3, SW_KIND: 4, "其他": 9}
KIND_ORDER = ["建筑", "步兵", "车辆", "空军", SW_KIND, "其他"]
FAC_ORDER = ["盟军", "苏军", "厄普西隆", "焚风", "中立&其他"]
FAC_PRI = {f: i for i, f in enumerate(FAC_ORDER)}
# 官网正式名称（按钮上显示）
FAC_DISPLAY = {
    "盟军": "同盟国联军",
    "苏军": "苏维埃联盟",
    "厄普西隆": "厄普西隆军",
    "焚风": "焚风反抗军",
    "中立&其他": "中立&其他",
}
# 阵营主题（代表色取自官网阵营徽章；背景图不参与换色）
FAC_THEME = {
    "全部": dict(accent="#ffd28a", edge="#3a2b4e", panel="#140f1c",
                 bar="#0b0810", list="#0f0b16", sel="#6b2f8c", img="def"),
    "盟军": dict(accent="#7fb6ff", edge="#25425f", panel="#0f151d",
                 bar="#080d13", list="#0c1218", sel="#2b5c96", img="allied"),
    "苏军": dict(accent="#ff8a6a", edge="#5c2a22", panel="#1a1012",
                 bar="#120a0c", list="#160d0f", sel="#8d2b1e", img="soviet"),
    "厄普西隆": dict(accent="#c99bff", edge="#452a5c", panel="#150f20",
                     bar="#0c0812", list="#110c1a", sel="#5c2a8a", img="epsilon"),
    "焚风": dict(accent="#79e8dd", edge="#1e4a48", panel="#0e1a1b",
                 bar="#070f10", list="#0b1516", sel="#1f7f7a", img="foehn"),
    "中立&其他": dict(accent="#d2d2dc", edge="#3c3c46", panel="#121216",
                      bar="#0a0a0c", list="#0e0e12", sel="#565660", img="neutral"),
}

# 常用数值字段（按这个顺序优先展示）
COMMON_KEYS = [
    "Cost", "Strength", "Armor", "Speed", "Sight", "TechLevel", "Points",
    "Weight", "ROT", "TurretROT", "Power", "Upkeep", "Ammo", "Reload",
    "ROF", "Range", "Damage", "Burst", "GuardRange", "MinimumRange",
    "ProjectileSpeed", "SpeedLimit", "BuildTime", "Growth", "Spread",
    "ParaDrop.Count", "ParaDrop.Num",
]

# 武器槽位（单位节里指向武器节的那几个键）
WEAPON_SLOTS = ["Primary", "Secondary", "ElitePrimary", "EliteSecondary"]
SLOT_CN = {"Primary": "主武器", "Secondary": "副武器",
           "ElitePrimary": "精英主武器", "EliteSecondary": "精英副武器"}


def slot_cn(slot):
    """槽位的中文名；加特林单位的 Weapon1..N 在这里临时翻译。"""
    if slot in SLOT_CN:
        return SLOT_CN[slot]
    m = re.match(r"^(Elite)?Weapon(\d+)$", slot)
    if m:
        return ("精英加特林第%s段" if m.group(1) else "加特林第%s段") % m.group(2)
    return slot

# 武器节里值得改的数值
WEAPON_FIELDS = ["Damage", "ROF", "Range", "Burst", "ProjectileSpeed",
                 "MinimumRange", "GuardRange", "Warhead", "Report", "Speed"]
# 派生出来的导弹/子弹自身的数值（Ares、Phobos 的 Spawner 体系）
MISSILE_KEYS = ["Missile.Damage", "Missile.Warhead", "Missile.EliteWarhead",
                "Missile.Speed", "Missile.BodyLength", "Missile.ROT"]
# Verses= 的 11 个位置对应的基础装甲（顺序是引擎写死的）
ARMOR_ORDER = ["none", "flak", "plate", "light", "medium",
               "heavy", "wood", "steel", "concrete", "special_1", "special_2"]
ARMOR_CN = ["无甲", "防弹衣", "护板", "轻甲", "中甲",
            "重甲", "木", "钢", "混凝土", "特殊1", "特殊2"]
# 没有 Missile.Damage 的派生导弹，伤害弹头由 [General] 指定
SPAWN_WARHEAD = {"V3ROCKET": ("V3Warhead", "V3EliteWarhead"),
                 "DMISL": ("DMislWarhead", "DMislEliteWarhead"),
                 "CMISL": ("CMislWarhead", "CMislEliteWarhead")}

# 字段中文名（没收录的就显示原始键名）
FIELD_CN = {
    "Cost": "价格", "Strength": "生命", "Armor": "装甲", "Speed": "速度",
    "Sight": "视野", "TechLevel": "科技等级", "Points": "点数", "Weight": "重量",
    "ROT": "转向速率", "TurretROT": "炮塔转速", "Power": "电力", "Upkeep": "维护费",
    "Ammo": "弹药量", "Reload": "装填时间", "ROF": "射速(ROF)", "Range": "射程",
    "Damage": "伤害", "Burst": "连发数", "GuardRange": "警戒范围",    "MinimumRange": "最小射程", "ProjectileSpeed": "弹道速度", "SpeedLimit": "限速",
    "BuildTime": "建造时间", "Growth": "生长速率", "Spread": "散布",
    "Name": "名称", "UIName": "界面名", "Image": "图像", "Cameo": "图标",
    "Crushable": "可碾压", "Crewed": "乘员", "Occupier": "可驻军",
    "Pip": "状态点", "Voice": "语音", "DieSound": "死亡音效",
    "Warhead": "弹头", "Report": "开火音效", "Primary": "主武器",
    "Secondary": "副武器", "ElitePrimary": "精英主武器",
    "EliteSecondary": "精英副武器", "Projectile": "弹道", "Verses": "伤害比例",
    "Spawns": "载具数", "Storage": "储量", "Refinery": "矿厂收益",
    "Dock": "停靠位", "NumberImpassableRows": "不可通行行数",
    "Foundation": "占地", "Height": "高度", "PhysicalHeight": "实际高度",
    "Adjacent": "须相邻", "BaseNormal": "可作为基地节点", "PowerBonus": "电力产出",
    "Owner": "所属方", "RequiredHouses": "需要阵营", "ForbiddenHouses": "禁止阵营",
    "Prerequisite": "前置建筑", "BuildLimit": "建造上限", "AIBasePlanningSide": "AI规划",
    "ThreatPosed": "威胁值", "SpecialThreatValue": "特殊威胁", "VeteranAbilities": "老兵能力",
    "EliteAbilities": "精英能力", "ImmuneToPsionics": "免疫心灵", "MindControl": "心灵控制",
    "DeployTime": "部署时间", "DeploysInto": "部署为", "UndeploysInto": "回收为",
    "Turret": "有炮塔", "OpportunityFire": "机会射击", "DeployFire": "部署开火",
    "Primary": "主武器", "Secondary": "副武器", "ElitePrimary": "精英主武器",
    "EliteSecondary": "精英副武器", "Occupant": "驻军武器",
    "AmbientSound": "音效", "MoveSound": "移动音效", "Report": "开火音效",
    "Spawns": "生成单位", "SpawnsNumber": "生成数量", "SpawnReloadRate": "生成冷却",
    "Missile.Damage": "导弹伤害", "Missile.Warhead": "导弹弹头",
    "Missile.EliteWarhead": "精英导弹弹头", "Missile.Speed": "导弹速度",
    "Missile.BodyLength": "导弹拖尾", "Missile.ROT": "导弹转向",
    # ---- 支援技能 ----
    "RechargeTime": "冷却", "Money.Amount": "花费", "Range": "施法距离",
    "SW.RangeMaximum": "最大距离", "SW.Damage": "技能伤害", "SW.Warhead": "技能弹头",
    "SW.Animation": "释放动画", "SW.AnimationHeight": "动画高度",
    "SW.AITargeting": "AI 使用", "SW.Group": "侧边栏分组",
    "SW.ShowCameo": "显示图标", "SW.FireIntoShroud": "可穿烟释放",
    "SW.Inhibitors": "被这些建筑禁用", "SW.AuxBuildings": "辅助建筑",
    "SW.RequiresTarget": "必须选目标", "SW.AutoFire": "自动释放",
    "SW.ManualFire": "手动释放", "SW.Sound": "释放音效",
    "SW.CreateRadarEvent": "雷达事件", "SW.AffectsHouse": "影响对象",
    "Type": "行为类型", "Action": "动作", "SidebarPCX": "侧边栏图标",
    "UIName": "界面名", "ShowTimer": "显示读秒", "IsPowered": "需要电力",
    "PreClick": "先选目标", "PostClick": "点后生效", "PreDependent": "前置技能",
    "Cursor": "可用指针", "NoCursor": "不可用指针", "LineMultiplier": "连线数",
    "Deliver.Types": "空投内容", "ParaDrop.Count": "空投数量",
    "DisableableFromShell": "可被壳禁用", "FlashSidebarTabFrames": "侧边栏闪烁",
    "SuperWeapon": "技能1", "SuperWeapon2": "技能2", "SuperWeapons": "技能列表",
}

# 大小写不敏感查表（INI 里 ParaDrop.Count / PARADROP.COUNT 混着写）
# —— 数值汉化补充（v1.3，逐步扩充）——
FIELD_CN.update({
    "MaxDebris": "最大碎片数",
    "MinDebris": "最小碎片数",
    "DebrisAnims": "碎片动画",
    "DebrisMaximums": "碎片数量上限",
    "Explosion": "爆炸动画",
    "Explodes": "死亡时爆炸",
    "Insignificant": "不显示选中框",
    "Nominal": "标准高度",
    "ClickRepairable": "可点击维修",
    "VoiceSelect": "选中语音",
    "VoiceMove": "移动语音",
    "VoiceAttack": "攻击语音",
    "VoiceSpecialAttack": "特殊攻击语音",
    "VoiceFeedback": "受击语音",
    "VoiceDie": "死亡语音",
    "VoiceEnter": "进入语音",
    "VoiceCapture": "占领语音",
    "VoiceDeploy": "部署语音",
    "MoveSound": "移动音效",
    "CrushSound": "碾压音效",
    "DamageSound": "受损音效",
    "DieSound": "死亡音效",
    "DeploySound": "部署音效",
    "UndeploySound": "收起音效",
    "Bounty": "赏金",
    "Bounty.Value": "赏金金额",
    "Bounty.Display": "显示赏金",
    "Soylent": "回收价值",
    "Locomotor": "运动类型",
    "MovementZone": "移动区域",
    "SpeedType": "速度类型",
    "Category": "分类",
    "AllowedToStartInMultiplayer": "联机开局自带",
    "CanBeReversed": "可以倒车",
    "Size": "尺寸",
    "PhysicalSize": "物理尺寸",
    "CanBeOccupied": "可以驻军",
    "MaxNumberOccupants": "最大驻军数",
    "CanOccupyFire": "驻军可开火",
    "Bunkerable": "可进驻碉堡",
    "DamageSmokeOffset": "受损冒烟位置",
    "DamageParticleSystems": "受损粒子效果",
    "Trainable": "可升级",
    "IsSelectableCombatant": "可选中的战斗单位",
    "Insignia.Veteran": "老兵徽章",
    "Insignia.Elite": "精英徽章",
    "Capturable": "可被占领",
    "CaptureSound": "占领音效",
    "LeaveRubble": "摧毁后留废墟",
    "ProtectedDriver": "驾驶员受保护",
    "ImmuneToEMP": "免疫 EMP",
    "EMP.Threshold": "EMP 瘫痪阈值",
    "EMP.Modifier": "EMP 持续时间倍率",
    "Crusher": "碾压等级",
    "CrateGoodie": "会掉木箱道具",
    "DeathWeapon": "死亡武器",
    "Selectable": "可被选中",
    "VehicleThief.Allowed": "可被偷车",
    "ZFudgeColumn": "纵向偏移",
    "ZFudgeTunnel": "隧道高度偏移",
    "IFVMode": "多功能车武器模式",
    "Powered": "需要电力",
    "Accelerates": "会加速",
    "BuildCat": "建造栏分类",
    "BuildTime.MultipleFactory": "多工厂建造时间",
    "BuildTimeMultiplier": "建造时间倍率",
    "SlowdownDistance": "减速距离",
    "PixelSelectionBracketDelta": "选中框像素偏移",
    "TooBigToFitUnderBridge": "过大不能钻桥",
    "AccelerationFactor": "加速度系数",
    "DeaccelerationFactor": "减速度系数",
    "UC.PassThrough": "可被单位穿过",
    "UC.DamageMultiplier": "碾压伤害倍率",
    "AIBuildThis": "AI 会建造",
    "ImmuneToAbduction": "免疫绑架",
    "ImmuneToVeins": "免疫藤蔓",
    "ImmuneToRadiation": "免疫辐射",
    "SelfHealing": "自我修复",
    "RadarInvisible": "雷达隐身",
    "RadarVisible": "雷达可见",
    "PipScale": "状态图标样式",
    "CanPassiveAquire": "自动索敌",
    "CanRetaliate": "会还击",
    "IsTilter": "可倾斜",
    "Unsellable": "不可出售",
    "IronCurtain.Modifier": "铁幕修正",
    "PreventAttackMove": "禁止攻击移动",
    "Spyable": "可被间谍渗透",
    "Drainable": "可被吸取",
    "Chronoshift.Allow": "可被超时空传送",
    "Chronoshift.Crushable": "可被超时空碾压",
    "Warpable": "可被超时空移动",
    "DamageReducesReadiness": "受损降低效率",
    "ReadinessReductionMultiplier": "效率下降倍率",
    "UnitRepair": "可维修",
    "Repairable": "可维修",
    "RepairStep": "每次维修量",
    "Repair Percent": "维修量百分比",
    "Reload": "装填时间",
    "EmptyReload": "空弹装填时间",
    "OccupyWeapon": "驻军武器",
    "EliteOccupyWeapon": "精英驻军武器",
    "OpenTransportWeapon": "运输单位开火武器",
    "Assaulter": "可突击(清驻军)",
    "AssaultAnim": "突击动画",
    "DeployTime": "部署时间",
    "DeploysInto": "部署为",
    "UndeploysInto": "回收为",
    "Deployer": "可部署",
    "UndeployDelay": "收起延迟",
    "Spawns": "生成的单位",
    "SpawnsNumber": "生成数量",
    "SpawnReloadRate": "生成冷却",
    "SpawnRegenRate": "生成恢复速率",
    "Spawned": "是生成物",
    "Missile.Damage": "导弹伤害",
    "Missile.Warhead": "导弹弹头",
    "Missile.EliteWarhead": "精英导弹弹头",
    "Missile.Speed": "导弹速度",
    "Missile.BodyLength": "导弹拖尾长度",
    "Missile.ROT": "导弹转向速率",
    "SpawnDelay": "生成延迟",
    "Damage": "伤害",
    "ROF": "射速(ROF)",
    "Range": "射程",
    "MinimumRange": "最小射程",
    "Burst": "连发数",
    "Projectile": "弹道",
    "ProjectileSpeed": "弹道速度",
    "SpeedLimit": "限速",
    "Spread": "散布",
    "Warhead": "弹头",
    "Report": "开火音效",
    "OccupantAnim": "驻军开火动画",
    "Anim": "动画",
    "Spawner": "发射器(生成单位)",
    "FireOnce": "只开一次",
    "CellRangefinding": "按格计算射程",
    "Lobber": "抛射",
    "Bright": "开火闪光",
    "Floating": "浮空",
    "IsRadBeam": "辐射光束",
    "IsLaser": "激光",
    "IsSonic": "声波",
    "IsElectricBolt": "电弧",
    "LaserInnerColor": "激光内色",
    "LaserOuterColor": "激光外色",
    "LaserDuration": "激光持续",
    "IonSensitive": "离子敏感",
    "Ion effect": "离子效果",
    "AmbientDamage": "范围伤害",
    "CausesDelayKill": "延迟致死",
    "DelayKillFrames": "延迟帧数",
    "Suicide": "自爆",
    "ShakeX": "屏幕震动 X",
    "ShakeY": "屏幕震动 Y",
    "LimboLaunch": "自毁式发射",
    "Bullets": "子弹数",
    "AttachToBone": "挂接位置",
    "Verses": "伤害百分比",
    "CellSpread": "爆炸范围(格)",
    "PercentAtMax": "边缘伤害比例",
    "InfDeath": "步兵死亡方式",
    "Wood": "对木伤害",
    "Wall": "对墙伤害",
    "ProneDamage": "趴下伤害倍率",
    "Tiberium": "对矿伤害",
    "Conventional": "常规伤害",
    "Rock": "对岩石",
    "CombatLightSize": "战斗灯光范围",
    "WallAbsoluteDestroyer": "直接摧毁墙",
    "PenetratesBunker": "穿透碉堡",
    "RadLevel": "辐射强度",
    "Paralyzes": "瘫痪",
    "Paralyze": "瘫痪",
    "EMPulse.Cannons": "EMP 炮数量",
    "PreImpactAnim": "命中前动画",
    "AnimList": "命中动画",
    "SonarPulse": "声纳脉冲",
    "NukeMaker": "核弹特效",
    "MiniNuke": "小型核弹",
    "Height": "高度",
    "Foundation": "地基",
    "Adjacent": "可紧贴建造",
    "EligibileForAllyBuilding": "可被盟友借建",
    "UnitReload": "可补给弹药",
    "NumberOfDocks": "停机位数量",
    "NumberOfUnitRepo": "回收位数量",
    "FreeUnit": "赠送单位",
    "GivesBounty": "提供赏金",
    "FactoryPlant": "工厂加成",
    "CloakGenerator": "隐形发生器",
    "SensorArray": "雷达(感应)",
    "SuperWeapon": "支援技能",
    "SuperWeapon2": "支援技能 2",
    "SuperWeapons": "支援技能(多个)",
    "DrainWeapon": "吸取武器",
    "RefinerySmokeParticleSystems": "精炼厂烟雾",
    "Bib": "可建造地基",
    "CanBeHidden": "可被隐形",
    "WaterBound": "只能建在水上",
    "AdjacentToWater": "必须临水",
    "NeedsEngineer": "需要工程师占领",
    "PoweredUnit": "需要电力工作",
    "BaseNormal": "属于基地建筑",
    "Storage": "储量容量",
    "PowersUpBuilding": "升级目标建筑",
    "RechargeTime": "冷却",
    "Money.Amount": "花费",
    "SW.RangeMaximum": "最大距离",
    "SW.Damage": "技能伤害",
    "SW.Warhead": "技能弹头",
    "SW.Animation": "释放动画",
    "SW.AITargeting": "AI 使用方式",
    "SW.Group": "侧边栏分组",
    "SW.ShowCameo": "显示图标",
    "SW.FireIntoShroud": "可穿烟释放",
    "SW.Inhibitors": "被这些建筑禁用",
    "SW.AuxBuildings": "辅助建筑",
    "SW.AlwaysGranted": "一直可用",
    "SW.AllowAI": "AI 可用",
    "SW.AllowPlayer": "玩家可用",
    "SW.RequiresTarget": "需要选目标",
    "SW.RequiresHouse": "需要所属国家",
    "SW.NegCharge": "需要电力",
    "SW.Sound": "释放音效",
    "SW.CreateRadarEvent": "雷达提示",
    "SW.ManualFire": "手动发射",
    "Type": "行为类型",
    "Action": "动作",
    "SidebarPCX": "侧边栏图标",
    "UIName": "界面名",
    "Name": "名称",
    "ShowTimer": "显示读秒",
    "DisableableFromShell": "可被关闭",
    "AIDefendAgainst": "AI 会防御",
    "IsPowered": "需要电力",
    "ParaDrop.Aircraft": "空投运输机",
    "ParaDrop.Count": "空投数量",
    "ParaDrop.Num": "空投数量",
    "ParaDrop.Types": "空投单位",
    "ParaDropInf": "空投步兵",
    "ParaDropNum": "空投数量",
})

# —— 数值汉化补充（第二批）——
FIELD_CN.update({
    "EVA.Ready": "语音提示(就绪)",
    "DebrisTypes": "碎片类型",
    "Fearless": "无所畏惧",
    "OmniCrushResistant": "免疫碾压",
    "HasRadialIndicator": "显示圆形指示器",
    "MoveToShroud": "会自动探雾",
    "HasStupidGuardMode": "原地警戒不追击",
    "NavalTargeting": "对海目标类型",
    "AttachEffect.Duration": "附带效果时长",
    "AttachEffect.Animation": "附带效果动画",
    "AttachEffect.PenetratesIronCurtain": "效果穿透铁幕",
    "CrashingSound": "坠毁音效",
    "DistributedFire": "分散开火",
    "ForceShield.Modifier": "力场护盾修正",
    "GroupAs": "分组(同类)",
    "AntiInfantryValue": "AI 反步兵价值",
    "AntiArmorValue": "AI 反装甲价值",
    "AntiAirValue": "AI 防空价值",
    "LeadershipRating": "指挥加成",
    "Cursor.Spy": "间谍光标",
    "SpyEffect.Custom": "自定义渗透效果",
    "PipWrap": "状态图标换行数",
    "KeepAlive": "不会自然消失",
    "ImpactLandSound": "落地音效",
    "AirRangeBonus": "对空射程加成",
    "DetectDisguise": "可识破伪装",
    "ProtectWithWall": "用墙保护",
    "ConsideredAircraft": "按飞行器处理",
    "Crashable": "可坠毁",
    "SensorsSight": "感应视野",
    "Sensors": "感应器",
    "IsBaseDefense": "属于防御建筑",
    "PitchSpeed": "俯仰速度",
    "PitchAngle": "俯仰角",
    "UseOwnName": "使用自身名字",
    "FireAngle": "开火角度",
    "Insignia.Rookie": "新兵徽章",
    "Promote.VeteranSound": "晋升老兵音效",
    "Promote.EliteSound": "晋升精英音效",
    "SizeLimit": "运载尺寸上限",
    "PsychicDetectionRadius": "心灵探测范围",
    "Cloakable": "可隐形",
    "CloakingSpeed": "隐形时速度",
    "CloakStop": "停下才隐形",
    "DecloakToFire": "开火现形",
    "SensorSight": "感应视野",
    "Detectable": "可被探测",
    "IonCannon.ConditionRed": "离子炮条件(红)",
    "CanHideThings": "可藏匿单位",
    "HideHealthBar": "隐藏血条",
    "DisableVeterancy": "不能升级",
    "VeteranSpeed": "老兵速度",
    "VeteranSight": "老兵视野",
    "VeteranArmor": "老兵装甲",
    "EliteSpeed": "精英速度",
    "EliteSight": "精英视野",
    "EliteArmor": "精英装甲",
    "EliteROF": "精英射速",
    "WeaponStages": "阶段数",
    "Stage1": "第1段击破数",
    "Stage2": "第2段击破数",
    "Stage3": "第3段击破数",
    "EliteStage1": "精英第1段击破数",
    "EliteStage2": "精英第2段击破数",
    "EliteStage3": "精英第3段击破数",
    "RateUp": "射速提升",
    "RateDown": "射速恢复",
    "NormalTurret": "正常炮塔",
    "TurretCount": "炮塔数量",
    "IsTurret": "是炮塔",
    "HasTurretTooltips": "炮塔提示",
    "DeployFireWeapon": "部署开火武器",
    "DeployedCrushable": "部署后可被碾压",
    "DeployedSound": "部署音效",
    "CreateSound": "建造音效",
    "UnderConstruction": "建造中动画",
    "BuildupTime": "建造动画时长",
    "BuildingFace": "建筑朝向",
    "IsAnimDelayedFire": "延迟开火动画",
    "Natural": "自然生成",
    "NaturalParticleSystem": "自然粒子",
    "Helipad": "停机坪",
    "ManualReload": "手动装填",
    "EmptyCell": "空格子",
    "PipCount": "状态图标数量",
    "NumberOfOccupants": "驻军槽数量",
    "NumberOfSpawns": "生成数量",
})

# —— 数值汉化补充（第三批）——
FIELD_CN.update({
    "JumpjetSpeed": "悬浮飞行速度",
    "JumpjetClimb": "悬浮爬升速度",
    "JumpjetCrash": "悬浮坠毁速度",
    "JumpjetAccel": "悬浮加速度",
    "JumpjetTurnRate": "悬浮转向率",
    "JumpjetHeight": "悬浮高度",
    "JumpjetWobbles": "悬浮摆动幅度",
    "JumpjetDeviation": "悬浮偏移",
    "JumpjetNoWobbles": "悬浮不摆动",
    "JumpjetPrecision": "悬浮精度",
    "Passengers": "可载人数",
    "DeathWeaponDamageModifier": "死亡武器伤害修正",
    "SW.Deferment": "延迟启动",
    "SW.UsesAmmo": "消耗弹药",
    "SW.Range": "施法距离",
    "Naval": "是海军单位",
    "Landable": "可着陆",
    "LandTargeting": "对地目标类型",
    "HoverAttack": "悬停攻击",
    "BalloonHover": "气球式悬停",
    "TogglePower": "可切换电力",
    "Civilian": "平民单位",
    "FraidyCat": "胆小(会逃跑)",
    "Cursor.Deploy": "部署光标",
    "Cursor.Attack": "攻击光标",
    "Cursor.Move": "移动光标",
    "Cursor.NoMove": "禁止移动光标",
    "Cursor.Select": "选择光标",
    "WorkingSound": "工作音效",
    "AIBaseNormal": "AI 基地建筑",
    "Smoke.Anim": "烟雾动画",
    "Smoke.ChanceRed": "受损冒烟概率",
    "Smoke.ChanceDead": "死亡冒烟概率",
    "Smoke.ChanceGray": "低血冒烟概率",
    "BurstDelay0": "第1发间隔",
    "BurstDelay1": "第2发间隔",
    "BurstDelay2": "第3发间隔",
    "BurstDelay3": "第4发间隔",
    "AttachEffect.SpeedMultiplier": "附带速度倍率",
    "AttachEffect.ArmorMultiplier": "附带装甲倍率",
    "AttachEffect.FirepowerMultiplier": "附带火力倍率",
    "AttachEffect.ROFMultiplier": "附带射速倍率",
    "AttachEffect.TemporalHidesAnim": "时空隐藏动画",
    "AttachEffect.AffectsSelf": "影响自身",
    "ForceShield.Armor": "力场护盾装甲",
    "ForceShield.Duration": "力场护盾时长",
    "LEAD": "铅量(投射物)",
    "LeptonMindControl": "心灵控制(轻子)",
    "MindControl": "心灵控制",
    "MindControl.Range": "心灵控制距离",
    "CanBeMindControlled": "可被心灵控制",
    "NumberOfDocks": "停机位数量",
    "DockUnload": "卸载点",
    "Weeder": "可收割",
    "Bombable": "可被炸弹摧毁",
    "WantsWeapon": "需要武器",
    "Harvester": "是采矿车",
    "Enslaves": "可奴役",
    "MakesShroud": "产生黑幕",
    "ImmuneToVeins": "免疫藤蔓",
    "Subterranean": "地下移动",
    "Locomotor.Land": "陆地运动类型",
    "Locomotor.Water": "水上运动类型",
    "WheelCount": "轮子数量",
    "TurretAnim": "炮塔动画",
    "BarrelAnim": "炮管动画",
    "BarrelLength": "炮管长度",
    "BarrelOffset": "炮管偏移",
    "TurretOffset": "炮塔偏移",
    "RotatesTurret": "炮塔会转动",
    "AmmoPerBarrel": "每根炮管弹药",
    "RecoilAmount": "后坐距离",
    "MuzzleFlash": "枪口火光",
    "Report.Damage": "受损音效",
    "CloakSound": "隐形音效",
    "DecloakSound": "现形音效",
    "AmbientSound": "环境音效",
    "DieSound2": "死亡音效 2",
    "UndeploySound": "收起音效",
    "CaptureAnim": "占领动画",
    "SellAnim": "出售动画",
    "ExitCoord": "出口坐标",
    "DockOffset": "停靠偏移",
    "NumberOfOccupants": "驻军数量",
    "PipScale": "图标缩放",
    "PipWrap": "图标换行",
    "AIBuildThis": "AI 会建造",
    "AIBuildCount": "AI 建造数量",
    "AITargeting": "AI 目标选择",
    "AIFriendlyFire": "AI 友伤",
    "GuardRange": "警戒范围",
    "GuardRangeBonus": "警戒范围加成",
    "PostClickDelay": "点击后延迟",
    "ThreatAvoidance": "威胁规避",
    "ThreatPosed": "威胁值",
    "NotWorkingSound": "缺电音效",
    "PowerDownSound": "断电音效",
    "InfantryGainSelfHeal": "步兵自愈",
    "SelfHealInfantryFrames": "自愈间隔(帧)",
    "SelfHealInfantryAmount": "自愈量",
    "SelfHealUnitFrames": "载具自愈间隔",
    "SelfHealUnitAmount": "载具自愈量",
    "CanSelfHeal": "可自愈",
    "ImmuneToPoison": "免疫毒素",
    "Parasiteable": "可被寄生",
    "Parasite": "寄生",
    "Storage": "可储存",
    "NumberOfBuildings": "建筑数量",
    "RefinerySmokeParticleSystems": "精炼厂烟雾效果",
    "UnitsGarrisoned": "已驻军单位",
    "BaseUnit": "基地单位",
    "VoiceIFVRepair": "多功能车维修语音",
    "RepairSell": "维修/出售值",
    "SellSound": "出售音效",
    "ExitDelay": "出舱延迟",
    "EjectDir": "弹出方向",
    "DrainBrain": "吸取大脑",
    "BrainAIMode": "AI 模式",
})

# —— 数值汉化补充（第四批：武器段/灯光/提示）——
FIELD_CN.update({
    "Gattling.Cycle": "加特林循环切换",
    "ConstructionYard": "建造场",
    "Factory": "工厂",
    "SellTime": "出售时间",
    "SpyEffect.StolenTechIndex": "渗透科技索引",
    "WeaponType": "武器类型",
    "SW.ActivationSound": "启动音效",
    "Light.Ambient": "环境光亮度",
    "Light.Red": "红光强度",
    "Light.Green": "绿光强度",
    "Light.Blue": "蓝光强度",
    "Message.Detected": "被发现提示",
    "Message.FirerColor": "发射方配色提示",
    "Message.Launch": "发射提示",
    "OccupyPip": "驻军图标",
    "EnterTransportSound": "进入运输音效",
    "LeaveTransportSound": "离开运输音效",
    "SlamSound": "关门音效",
    "VoiceSecondaryWeaponAttack": "副武器攻击语音",
    "LightVisibility": "灯光可见度",
    "LightIntensity": "灯光强度",
    "LightRedTint": "红色光晕",
    "LightGreenTint": "绿色光晕",
    "LightBlueTint": "蓝色光晕",
    "DontScore": "不计分",
    "InvisibleInGame": "游戏内隐形",
    "NotHuman": "非人类单位",
    "Cloneable": "可被克隆",
    "EVA.VeteranPromoted": "晋升老兵提示音",
    "EVA.ElitePromoted": "晋升精英提示音",
    "Weapon1": "武器 1",
    "Weapon2": "武器 2",
    "Weapon3": "武器 3",
    "Weapon4": "武器 4",
    "Weapon5": "武器 5",
    "Weapon6": "武器 6",
    "Weapon7": "武器 7",
    "Weapon8": "武器 8",
    "Weapon9": "武器 9",
    "Weapon10": "武器 10",
    "Weapon11": "武器 11",
    "Weapon12": "武器 12",
    "EliteWeapon2": "精英武器 2",
    "EliteWeapon3": "精英武器 3",
    "EliteWeapon4": "精英武器 4",
    "EliteWeapon5": "精英武器 5",
    "EliteWeapon6": "精英武器 6",
    "EliteWeapon7": "精英武器 7",
    "EliteWeapon8": "精英武器 8",
    "EliteWeapon9": "精英武器 9",
    "EliteWeapon10": "精英武器 10",
    "EliteWeapon11": "精英武器 11",
    "EliteWeapon12": "精英武器 12",
    "Stage0": "第1段击破数",
    "EliteStage0": "精英第1段击破数",
    "Stage1": "第2段击破数",
    "EliteStage1": "精英第2段击破数",
    "Stage2": "第3段击破数",
    "EliteStage2": "精英第3段击破数",
    "Stage3": "第4段击破数",
    "EliteStage3": "精英第4段击破数",
    "Stage4": "第5段击破数",
    "EliteStage4": "精英第5段击破数",
    "Stage5": "第6段击破数",
    "EliteStage5": "精英第6段击破数",
    "Stage6": "第7段击破数",
    "EliteStage6": "精英第7段击破数",
    "Stage7": "第8段击破数",
    "EliteStage7": "精英第8段击破数",
    "Stage8": "第9段击破数",
    "EliteStage8": "精英第9段击破数",
    "Stage9": "第10段击破数",
    "EliteStage9": "精英第10段击破数",
    "Stage10": "第11段击破数",
    "EliteStage10": "精英第11段击破数",
    "Stage11": "第12段击破数",
    "EliteStage11": "精英第12段击破数",
})

# —— 数值汉化补充（补漏：被代码引用误判成已存在的键）——
FIELD_CN.update({
    "IsGattling": "加特林逻辑",
    "WeaponCount": "武器段数",
    "Immune": "免疫伤害",
    "Radar": "雷达",
})

# —— 数值汉化补充（第五批）——
FIELD_CN.update({
    "EliteWeapon1": "精英武器 1",
    "AuxSound1": "辅助音效 1",
    "AuxSound2": "辅助音效 2",
    "AuxSound3": "辅助音效 3",
    "Parachute.Anim": "伞降动画",
    "IsSimpleDeployer": "简单部署逻辑",
    "HealthBar.Hide": "隐藏血条",
    "Convert.Deploy": "部署转换",
    "Fighter": "是战斗机",
    "Survivor.RookiePassengerChance": "新兵乘员存活率",
    "Survivor.VeteranPassengerChance": "老兵乘员存活率",
    "Survivor.ElitePassengerChance": "精英乘员存活率",
    "Survivor.RookiePilotChance": "新兵驾驶员存活率",
    "Survivor.VeteranPilotChance": "老兵驾驶员存活率",
    "Survivor.ElitePilotChance": "精英驾驶员存活率",
    "Survivor.RookiePassengerChance.Ally": "新兵乘员存活率(友军)",
    "Pilot": "有驾驶员",
    "Crash": "坠毁",
    "CrashAnim": "坠毁动画",
    "SpawnReload": "生成装填",
    "SpawnFlightLevel": "生成飞行高度",
    "SpawnsTiberium": "生成矿",
    "PipScale": "图标缩放",
    "DeployingAnim": "部署动画",
    "UnderDeployAnim": "部署过程中动画",
    "DeployToLand": "只能部署在陆地",
    "DeployToWater": "只能部署在水上",
})

FIELD_CN_UP = {k.upper(): v for k, v in FIELD_CN.items()}

SEC_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(?:;.*)?$")
KEY_RE = re.compile(r"^([^=:;\s][^=;]*?)\s*=\s*(.*?)\s*$")


# --------------------------------------------------------------------------- #
# MIX 读取（只读）
# --------------------------------------------------------------------------- #
def iter_mix_entries(path):
    """逐个产出 (offset, size)，offset 已换算成文件绝对位置。"""
    try:
        fsize = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(10)
            if len(head) < 10:
                return
            b0, b1 = head[0], head[1]
            if b0 or b1:            # 没有 flags 段的老格式，本工具不处理
                return
            flags = struct.unpack_from("<I", head, 0)[0]
            if flags & 0x00020000:  # 头部加密，跳过
                return
            cnt = struct.unpack_from("<H", head, 4)[0]
            if cnt == 0 or cnt > 60000:
                return
            data_start = 10 + 12 * cnt
            if data_start > fsize:
                return
            f.seek(10)
            table = f.read(12 * cnt)
            if len(table) < 12 * cnt:
                return
            for k in range(cnt):
                _fid, off, size = struct.unpack_from("<III", table, 12 * k)
                if off == 0xFFFFFFFF or size == 0xFFFFFFFF:
                    continue
                if size == 0 or size > fsize:
                    continue
                pos = data_start + off
                if pos + size > fsize:
                    continue
                yield pos, size
    except Exception:
        return


def extract_rules_from_mixes(game_dir, log=None):
    """在所有 *.mix 里找 rulesmo.ini（按内容识别），返回文本。"""
    best = None
    files = glob.glob(os.path.join(game_dir, "*.mix"))
    files.sort(key=lambda p: os.path.getsize(p), reverse=True)
    for path in files:
        try:
            with open(path, "rb") as f:
                for pos, size in iter_mix_entries(path):
                    if size < 200000 or size > 20_000_000:
                        continue
                    f.seek(pos)
                    probe = f.read(220)
                    if b"RULES CONTROL FILE" not in probe and b"[General]" not in probe:
                        continue
                    f.seek(pos)
                    blob = f.read(size)
                    if b"[General]" not in blob[:4000]:
                        continue
                    text = blob.decode("latin1")
                    heads = text.count("[")
                    if heads < 100:
                        continue
                    if best is None or len(text) > len(best[1]):
                        best = (os.path.basename(path), text)
                        if log:
                            log("找到 rulesmo.ini: %s (%d 字节)" % (best[0], len(text)))
        except Exception:
            continue
    return best


# --------------------------------------------------------------------------- #
# INI 解析
# --------------------------------------------------------------------------- #
def parse_ini(text):
    """-> (sections: {name: [(key,val), ...]}, order: [name, ...])"""
    sections, order = {}, []
    cur = None
    for line in text.splitlines():
        m = SEC_RE.match(line)
        if m:
            cur = m.group(1).strip()
            if cur not in sections:
                sections[cur] = []
                order.append(cur)
            continue
        if cur is None:
            continue
        m = KEY_RE.match(line)
        if m:
            key, val = m.group(1).strip(), m.group(2).strip()
            sections[cur].append((key, val))
    return sections, order


def _section_spans(lines):
    """-> {节名大写: (起始行, 结束行)}，同名节只取第一处。"""
    spans, cur, start = {}, None, 0
    for i, ln in enumerate(lines):
        m = SEC_RE.match(ln.rstrip("\r"))
        if m:
            if cur is not None:
                spans.setdefault(cur.upper(), (start, i))
            cur, start = m.group(1).strip(), i
    if cur is not None:
        spans.setdefault(cur.upper(), (start, len(lines)))
    return spans


def patch_ini_text(text, edits):
    """把 edits={节: {键: 新值}} 就地写进 text，其余行原样保留。"""
    lines = text.split("\n")
    cr = "\r" if "\r\n" in text else ""
    for sec, d in edits.items():
        spans = _section_spans(lines)
        span = spans.get(sec.upper())
        if not span:
            lines += ["", "[%s]" % sec + cr]
            lines += ["%s=%s" % (k, v) + cr for k, v in d.items()]
            continue
        for k, v in d.items():
            st, en = spans.get(sec.upper())
            hit = -1
            for i in range(st + 1, en):
                m = KEY_RE.match(lines[i].rstrip("\r"))
                if m and m.group(1).strip().lower() == k.lower():
                    hit = i
                    break
            if hit >= 0:
                m = KEY_RE.match(lines[hit].rstrip("\r"))
                cm = re.search(r";.*$", lines[hit])
                tail = (" " + cm.group(0).strip()) if cm else ""
                lines[hit] = "%s=%s%s" % (m.group(1).strip(), v, tail)
            else:
                ins = en
                while ins - 1 > st and not lines[ins - 1].strip():
                    ins -= 1
                lines.insert(ins, "%s=%s" % (k, v) + cr)
    return "\n".join(lines)


def type_list_ids(sections, name):
    out = []
    for key, val in sections.get(name, []):
        if not key.isdigit():
            continue
        uid = val.split(";")[0].strip()
        if uid:
            out.append(uid)
    return out


# --------------------------------------------------------------------------- #
# 主界面
# --------------------------------------------------------------------------- #
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MO 数值编辑器 v%s — Mental Omega" % APP_VERSION)
        self._want_zoom = False
        geo = self._load_geometry()
        self.geometry(geo if geo else "1080x680")
        self.minsize(900, 560)
        try:
            self.tk.call("tk", "scaling", 1.25)
        except Exception:
            pass

        os.makedirs(DATA_DIR, exist_ok=True)
        self._auto_found = None
        self._auto_timeout = False
        self.game_dir = self._load_game_dir()
        self.base_text = ""
        self.sections = {}
        self.order = []
        self.units = []            # [(sec, kind, name)]
        self.edits = {}
        self.undo_stack = []   # [(说明, edits 快照)]
        self.redo_stack = []            # {sec: {key: newval}}
        self.current = None
        self.entries = {}          # {(sec,key): (Entry, original)}
        self.dirty = set()
        self._field_map = {}       # {Entry控件: (sec, key)}，给中文搜索用
        self._ref_seen = {}        # {id(Entry): 上次看到的文本}，配合 IME 轮询
        self._ref_popup = None
        self._top_jobs = []        # 待执行的“回顶部”after 任务，用户滚动时取消
        self.cn = self._load_cn()  # {节ID大写: 中文名}
        self.factions = self._load_json(FAC_FILE)  # {节ID大写: 阵营}

        self._build_ui()
        if getattr(self, "_want_zoom", False):
            self.after(80, lambda: self.state("zoomed"))
        self.after(120, self._startup)
        self.after(400, self._ref_poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 日志 ----------
    def _log(self, msg):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(os.path.join(DATA_DIR, "save.log"), "a", encoding="utf-8") as f:
                f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
        except Exception:
            pass

    # ---------- 中文名 ----------
    def _load_json(self, path, upper=True):
        cands = [path]
        if FROZEN and RES_DIR:
            cands.append(os.path.join(RES_DIR, os.path.basename(path)))
        for p in cands:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if upper:
                    return {str(k).upper(): str(v) for k, v in data.items()}
                return data
            except Exception:
                continue
        return {}

    def _load_cn(self):
        return self._load_json(CN_FILE)

    # ---------- 设置 ----------
    def _load_game_dir(self):
        try:
            with open(SETTINGS, "r", encoding="utf-8") as f:
                p = f.read().strip()
                if p and os.path.isdir(p):
                    return p
        except Exception:
            pass
        # 没记录或记录失效：自动找一下
        found = self._auto_detect_game_dir()
        if found:
            self._auto_found = found
            try:
                os.makedirs(DATA_DIR, exist_ok=True)
                with open(SETTINGS, "w", encoding="utf-8") as f:
                    f.write(found)
            except Exception:
                pass
            return found
        return DEFAULT_GAME_DIR

    @staticmethod
    def _looks_like_game_dir(p):
        try:
            if not p or not os.path.isdir(p):
                return False
            if not os.path.isfile(os.path.join(p, "gamemd.exe")):
                return False
            if glob.glob(os.path.join(p, "*.mix")):
                return True
            return os.path.isdir(os.path.join(p, "Resources"))
        except Exception:
            return False

    def _auto_detect_game_dir(self, limit=5.0):
        """在常见位置找 Mental Omega 安装目录；最多花 limit 秒，超时就返回 None。"""
        t0 = time.time()
        names = ["Mental Omega", "MentalOmega"]
        cands = []
        for d in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            if time.time() - t0 > limit:
                self._auto_timeout = True
                return None
            root = d + ":\\"
            if not os.path.isdir(root):
                continue
            for n in names:
                cands.append(os.path.join(root, n))
                cands.append(os.path.join(root, "Games", n))
                cands.append(os.path.join(root, "Program Files", n))
                cands.append(os.path.join(root, "Program Files (x86)", n))
        cands.append(DEFAULT_GAME_DIR)
        seen = set()
        for p in cands:
            if time.time() - t0 > limit:
                self._auto_timeout = True
                return None
            try:
                key = p.lower()
            except Exception:
                continue
            if key in seen:
                continue
            seen.add(key)
            if self._looks_like_game_dir(p):
                return os.path.normpath(p)
        # 再扫一层子目录（D:\MOMOD\Mental Omega 这种）
        for d in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            if time.time() - t0 > limit:
                self._auto_timeout = True
                return None
            root = d + ":\\"
            if not os.path.isdir(root):
                continue
            try:
                for sub in os.listdir(root)[:400]:
                    if time.time() - t0 > limit:
                        self._auto_timeout = True
                        return None
                    for n in names:
                        p = os.path.join(root, sub, n)
                        if self._looks_like_game_dir(p):
                            return os.path.normpath(p)
            except Exception:
                continue
        return None

    # ---------- 副本（另存 / 载入）----------
    def _profile_files(self):
        try:
            os.makedirs(PROFILE_DIR, exist_ok=True)
            items = [f for f in os.listdir(PROFILE_DIR) if f.lower().endswith(".json")]
        except Exception:
            return []
        out = []
        for f in items:
            p = os.path.join(PROFILE_DIR, f)
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    d = json.load(fh)
            except Exception:
                continue
            n = sum(len(v) for v in d.get("edits", {}).values())
            out.append((p, d.get("name") or os.path.splitext(f)[0], n, d.get("time", "")))
        out.sort(key=lambda x: x[3], reverse=True)
        return out

    # ---------- 神秘选项 ----------
    MYSTERY_ATTRS = [("Strength", "血量"), ("Speed", "移速"), ("Cost", "价格"), ("ROF", "攻击间隔")]

    def _attr_units(self, secs, attr):
        """返回要改的 (节, 键) 列表；攻击间隔落在武器节上。"""
        out = []
        if attr == "ROF":
            wsecs = []
            for sec in secs:
                for slot in WEAPON_SLOTS:
                    w = self._first_val(sec, slot).strip()
                    ws = self.sec_by_up.get(w.upper()) if w else None
                    if ws and ws not in wsecs:
                        wsecs.append(ws)
            out = [(ws, "ROF") for ws in wsecs]
        else:
            out = [(sec, attr) for sec in secs]
        return out

    def _apply_attr(self, secs, attr, factor):
        n = 0
        for sec, key in self._attr_units(secs, attr):
            base = self._first_val(sec, key).strip()
            if not base:
                continue
            try:
                v = float(base)
            except Exception:
                continue
            nv = v * factor
            # 神秘选项不把步兵移速顶过 15（引擎里超过会抽搐/瞬移）；
            # 只夹“往上加”的情况，原本就 >15 的不往下拉，手动改也不受这个限制
            if key.upper() == "SPEED" and self._kind_of_sec(sec) == "步兵":
                nv = min(nv, max(float(INF_SPEED_MAX), v))
            txt = str(int(nv // 1))   # 向下取整（负数也朝 -∞）
            if txt == base:
                continue
            self.edits.setdefault(sec, {})[key] = txt
            n += 1
        return n

    def mystery(self):
        self._push_undo("神秘选项")
        fac = getattr(self, "fac", "全部")
        if fac not in MYSTERY_FACS:
            messagebox.showinfo("先选阵营",
                                "先在「阵营」里点一个具体阵营（「全部」和「中立&其他」不行）。")
            return
        inf = [sec for sec, kind, _n in self.index if kind == "步兵" and self._fac_of(sec) == fac]
        veh = [sec for sec, kind, _n in self.index if kind == "车辆" and self._fac_of(sec) == fac]
        if not inf and not veh:
            messagebox.showinfo("这个阵营没有可用单位", "「%s」下没找到步兵或车辆。" % fac)
            return

        def pick():
            attr, cn = random.choice(self.MYSTERY_ATTRS)
            up = random.random() < 0.5
            factor = 1.5 if up else 0.75
            good = (attr in ("Strength", "Speed")) == up
            return attr, cn, up, factor, good

        a1, c1, up1, f1, good1 = pick()
        n1 = self._apply_attr(inf, a1, f1) if inf else 0

        # 步兵改动若有利，就反过来给车辆一个有害的；反之给有利的
        want_good = not good1
        a2, c2, up2, f2, good2 = pick()
        tries = 0
        while good2 != want_good and tries < 12:
            a2, c2, up2, f2, good2 = pick()
            tries += 1
        if good2 != want_good:
            a2, c2 = random.choice(self.MYSTERY_ATTRS)
            up2 = (a2 not in ("Strength", "Speed")) == want_good
            f2 = 1.5 if up2 else 0.75
            good2 = want_good
        n2 = self._apply_attr(veh, a2, f2) if veh else 0

        self._fill_fields()
        self._refresh_list()
        self._update_status_quick()

        def line(name, cn, up, good, n):
            pct = "+50%" if up else "-25%"
            return "%s：%s %s（%s），改了 %d 处" % (
                name, cn, pct, "有利" if good else "有害", n)

        txt = "阵营：%s\n\n%s\n%s\n\n改动已放进待保存列表，点「保存到游戏」才生效。" % (
            FAC_DISPLAY.get(fac, fac), line("步兵", c1, up1, good1, n1),
            line("车辆", c2, up2, good2, n2))
        messagebox.showinfo("神秘选项", txt)
        self._msg("神秘选项已生效：%s" % ("步兵有利" if good1 else "步兵有害"), warn=not good1)

    def _about_window(self, w, h, title):
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=C_PANEL)
        win.transient(self)
        win.resizable(False, False)
        self._center_on_parent(win, w, h)
        return win

    @staticmethod
    def _win_text(parent, text, size=10, wrap=560, fg=None, pady=(0, 8)):
        lb = tk.Label(parent, text=text, bg=C_PANEL, fg=fg or C_TEXT,
                      font=("Microsoft YaHei UI", size), justify="left",
                      anchor="nw", wraplength=wrap)
        lb.pack(fill="x", pady=pady)
        return lb

    # ---------- 撤销 / 还原 / 内容 ----------
    UNDO_MAX = 300

    def _edits_copy(self):
        return {sec: dict(d) for sec, d in self.edits.items()}

    def _push_undo(self, label=""):
        """在真正改动 edits 之前调用：把当前状态压栈，并清空重做栈。"""
        self.undo_stack.append((label, self._edits_copy()))
        if len(self.undo_stack) > self.UNDO_MAX:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self._refresh_undo_links()

    def _after_state_change(self):
        """撤销/还原之后刷新面板、列表和状态。"""
        try:
            self._fill_fields()
        except Exception:
            pass
        self._refresh_list()
        self._update_status_quick()
        self._refresh_undo_links()

    def _refresh_undo_links(self):
        for lnk, ok, name in ((getattr(self, "lnk_undo", None), bool(getattr(self, "undo_stack", [])), "撤销"),
                              (getattr(self, "lnk_redo", None), bool(getattr(self, "redo_stack", [])), "还原")):
            if lnk is None:
                continue
            try:
                lnk.configure(fg=self.theme["accent"] if ok else C_GRAY)
            except Exception:
                pass

    def undo(self):
        if not getattr(self, "undo_stack", None):
            self._msg("没有可以撤销的修改了", warn=True)
            return
        label, snap = self.undo_stack.pop()
        self.redo_stack.append((label, self._edits_copy()))
        self.edits = snap
        self._after_state_change()
        self._msg("已撤销：%s" % (label or "上一步"))

    def redo(self):
        if not getattr(self, "redo_stack", None):
            self._msg("没有可以恢复的修改了", warn=True)
            return
        label, snap = self.redo_stack.pop()
        self.undo_stack.append((label, self._edits_copy()))
        self.edits = snap
        self._after_state_change()
        self._msg("已恢复：%s" % (label or "上一步"))

    def open_changes(self):
        """列出所有改动，可跳转或逐条还原。"""
        win = getattr(self, "_chg_win", None)
        if win is not None and win.winfo_exists():
            self._refresh_changes()
            win.deiconify()
            win.lift()
            return
        win = self._about_window(660, 560, "内容 · 当前修改")
        self._chg_win = win
        body = tk.Frame(win, bg=C_PANEL)
        body.pack(fill="both", expand=True, padx=16, pady=(12, 6))
        self._chg_title = ttk.Label(body, text="", style="Small.TLabel")
        self._chg_title.pack(anchor="w", pady=(0, 6))
        box = tk.Frame(body, bg=C_PANEL)
        box.pack(fill="both", expand=True)
        self._chg_lst = tk.Listbox(
            box, bg=self.theme["list"], fg=C_TEXT, selectbackground=self.theme["sel"],
            selectforeground="#ffffff", activestyle="none", font=("Microsoft YaHei UI", 10),
            borderwidth=0, highlightthickness=1, highlightbackground=self.theme["edge"])
        sb = ttk.Scrollbar(box, orient="vertical", command=self._chg_lst.yview)
        self._chg_lst.configure(yscrollcommand=sb.set)
        self._chg_lst.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._chg_lst.bind("<Double-Button-1>", lambda e: self._changes_goto())
        btns = tk.Frame(body, bg=C_PANEL)
        btns.pack(fill="x", pady=(8, 0))
        self._imgbtn(btns, "跳转", self._changes_goto, "btn").pack(side="left")
        self._imgbtn(btns, "还原这条", self._changes_revert_one, "btnf").pack(side="left", padx=(8, 0))
        self._imgbtn(btns, "还原这个单位", self._changes_revert_unit, "btnf").pack(side="left", padx=(8, 0))
        self._imgbtn(btns, "关闭", win.destroy, "btn").pack(side="right")
        self._refresh_changes()

    def _changes_rows(self):
        rows = []
        for sec, d in self.edits.items():
            real = self.sec_by_up.get(sec.upper(), sec)
            for key, val in d.items():
                if key.upper() == "VERSES":
                    continue
                orig = self._first_val(real, key)
                rows.append((real, key, orig, val))
        rows.sort(key=lambda t: ((self._disp(t[0], self._first_val(t[0], "Name")) or t[0]).lower(),
                                 t[1].lower()))
        return rows

    def _refresh_changes(self):
        if not getattr(self, "_chg_lst", None) or not self._chg_lst.winfo_exists():
            return
        rows = self._changes_rows()
        self._chg_rows = rows
        self._chg_lst.delete(0, "end")
        for sec, key, orig, val in rows:
            nm = self._disp(sec, self._first_val(sec, "Name")) or sec
            self._chg_lst.insert("end", "  %s  [%s]\u3000%s：%s → %s" % (
                nm, sec, self._field_label(key, sec), orig or "（空）", val))
        n_units = len({r[0] for r in rows})
        if hasattr(self, "_chg_title"):
            self._chg_title.configure(
                text="共 %d 个单位、%d 处改动（双击一行可跳转）" % (n_units, len(rows))
                if rows else "还没有任何改动")

    def _changes_selected(self):
        if not getattr(self, "_chg_lst", None) or not self._chg_lst.winfo_exists():
            return None
        sel = self._chg_lst.curselection()
        if not sel:
            return None
        idx = int(sel[0])
        if idx >= len(getattr(self, "_chg_rows", [])):
            return None
        return self._chg_rows[idx]

    def _changes_goto(self):
        row = self._changes_selected()
        if not row:
            self._msg("先在列表里选一条", warn=True)
            return
        win = getattr(self, "_chg_win", None)
        if win is not None and win.winfo_exists():
            win.destroy()
        self._goto(row[0])

    def _changes_revert_one(self):
        row = self._changes_selected()
        if not row:
            self._msg("先在列表里选一条", warn=True)
            return
        sec, key = row[0], row[1]
        self._push_undo("还原 %s 的 %s" % (self._disp(sec, self._first_val(sec, "Name")), key))
        d = self.edits.get(sec, {})
        d.pop(key, None)
        if not d:
            self.edits.pop(sec, None)
        self._after_state_change()
        self._refresh_changes()

    def _changes_revert_unit(self):
        row = self._changes_selected()
        if not row:
            self._msg("先在列表里选一条", warn=True)
            return
        sec = row[0]
        self._push_undo("还原 %s" % self._disp(sec, self._first_val(sec, "Name")))
        self.edits.pop(sec, None)
        self.dirty = {d for d in self.dirty if d[0] != sec}
        self._after_state_change()
        self._refresh_changes()

    def open_about(self):
        win = self._about_window(676, 700, "关于")
        body = tk.Frame(win, bg=C_PANEL)
        body.pack(fill="both", expand=True, padx=22, pady=(18, 6))

        ttk.Label(body, text="MO 数值编辑器  v%s" % APP_VERSION,
                  style="HTitle.TLabel").pack(anchor="w")
        self._win_text(body, "Mental Omega 3.3.6 的数值编辑器，给不想碰 INI 文件的人用。",
                       fg=C_DIM, pady=(4, 12))

        ttk.Label(body, text="— 谁做的 —", style="HSmall.TLabel").pack(anchor="w")
        self._win_text(
            body,
            "· MadNod（MadNod_）\n"
            "  需求、玩法设计、每一项功能在游戏里的实测验收，以及所有“这里不对”的反馈。\n"
            "  没有他一条条试，这工具做不出来。\n\n"
            "· DeepSeek Harness（AI 助手）\n"
            "  代码实现、MIX 容器解析、rulesmo.ini 结构分析、\n"
            "  Wiki 中文名的抓取与节 ID 映射、界面美术与打包。",
            pady=(2, 12))

        ttk.Label(body, text="— 免费声明 —", style="HSmall.TLabel").pack(anchor="w")
        self._win_text(body, NOTICE_TEXT, pady=(2, 4))

        linkrow = tk.Frame(body, bg=C_PANEL)
        linkrow.pack(fill="x", pady=(2, 0))
        self._win_text(linkrow, "觉得有用？", fg=C_DIM, pady=(0, 0))
        self._link(linkrow, "打赏作者", self.open_donate).pack(anchor="w")

        self._imgbtn(win, "关闭", win.destroy, "btnf").pack(side="bottom", pady=(4, 16))
        try:
            win.grab_set()
        except Exception:
            pass

    def open_donate(self):
        img_path = os.path.join(ART_DIR, "donate.png")
        has_img = os.path.isfile(img_path)
        win = self._about_window(600 if has_img else 560, 520 if has_img else 300, "打赏作者")
        body = tk.Frame(win, bg=C_PANEL)
        body.pack(fill="both", expand=True, padx=22, pady=(18, 6))
        self._win_text(
            body,
            "这工具一直是免费的，也不打算收费。\n"
            "觉得它省了事，就随手打赏一杯咖啡——完全自愿，\n"
            "不打赏也一样能用全部功能，没有任何功能锁。",
            pady=(2, 8))
        if has_img:
            try:
                ph = tk.PhotoImage(file=img_path)
                holder = tk.Frame(body, bg=C_PANEL)
                holder.pack(anchor="center", pady=(4, 0))
                lbl = tk.Label(holder, image=ph, bg="#ffffff", bd=0)
                lbl.image = ph
                lbl.pack()
                tk.Label(body, text="微信扫码打赏（MadNod）", bg=C_PANEL, fg=C_DIM,
                         font=("Microsoft YaHei UI", 9)).pack(anchor="center", pady=(8, 0))
            except Exception:
                pass
        else:
            self._win_text(body, "收款方式：由 MadNod_ 在群里公布。", fg=C_DIM, pady=(6, 0))
        self._imgbtn(win, "关闭", win.destroy, "btnf").pack(side="bottom", pady=(4, 16))
        try:
            win.grab_set()
        except Exception:
            pass

    def _show_notice(self):
        """启动时的免费声明；点「之后不再弹出」会记一个标记文件。"""
        if getattr(self, "_notice_shown", False):
            return
        self._notice_shown = True
        if os.path.isfile(NOTICE_FILE):
            return
        win = tk.Toplevel(self)
        win.title(NOTICE_TITLE)
        win.configure(bg=C_PANEL)
        win.transient(self)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        win.resizable(False, False)

        head = tk.Frame(win, bg=C_PANEL)
        head.pack(fill="x", padx=18, pady=(14, 0))

        body = tk.Frame(win, bg=C_PANEL)
        body.pack(fill="both", expand=True, padx=18, pady=(8, 4))
        tk.Label(body, text=NOTICE_TEXT, bg=C_PANEL, fg=C_TEXT,
                 font=("Microsoft YaHei UI", 10), justify="left",
                 anchor="nw", wraplength=548).pack(fill="both", expand=True)

        bar = tk.Frame(win, bg=C_PANEL)
        bar.pack(fill="x", padx=18, pady=(4, 16))

        def close(save):
            if save:
                try:
                    os.makedirs(DATA_DIR, exist_ok=True)
                    with open(NOTICE_FILE, "w", encoding="utf-8") as f:
                        f.write(APP_VERSION)
                except Exception as e:
                    messagebox.showwarning("记不下来", "写标记文件失败：%s\n下次还会弹。" % e)
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()

        self._imgbtn(bar, "之后不再弹出", lambda: close(True), "btnf").pack(side="right")
        self._imgbtn(bar, "我知道了", lambda: close(False), "btnf").pack(side="right", padx=(0, 8))

        self._center_on_parent(win, 600, 400)
        try:
            win.grab_set()
        except Exception:
            pass

    def _center_on_parent(self, win, w, h):
        """把子窗口摆在主窗口中间（并保证不出屏）。"""
        try:
            self.update_idletasks()
            px, py = self.winfo_rootx(), self.winfo_rooty()
            pw, ph = self.winfo_width(), self.winfo_height()
            if pw <= 1 or ph <= 1:
                pw, ph = 1080, 680
                px = py = 100
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            x = max(0, min(x, sw - w - 10))
            y = max(0, min(y, sh - h - 40))
            win.geometry("%dx%d+%d+%d" % (w, h, x, y))
        except Exception:
            win.geometry("%dx%d" % (w, h))

    def _sw_label(self, sid):
        cn = self.cn.get(sid.upper(), "")
        nm = self._first_val(sid, "Name").strip()
        if cn and nm:
            return "%s  %s  [%s]" % (cn, nm, sid)
        return "%s  [%s]" % (cn or nm or "?", sid)

    def _pick_sw(self, sec, key):
        """挑一个支援技能 ID，写进建筑的 SuperWeapon 键。"""
        ids = [s for s in getattr(self, "sw_set_order", []) if s in self.sections]
        ids.sort(key=lambda s: (self.cn.get(s.upper(), "") or self._first_val(s, "Name") or s).lower())
        win = tk.Toplevel(self)
        win.title("换成哪个支援技能")
        win.configure(bg=C_PANEL)
        win.transient(self)
        info = ttk.Label(win, text="双击一项即可换上（只改这一格，点「保存到游戏」才生效）",
                         style="Small.TLabel")
        info.pack(anchor="w", padx=10, pady=(8, 2))
        vq = tk.StringVar()
        ent = ttk.Entry(win, textvariable=vq)
        ent.pack(fill="x", padx=10, pady=(0, 6))
        body = tk.Frame(win, bg=C_PANEL)
        body.pack(fill="both", expand=True, padx=10)
        lb = tk.Listbox(body, bg=C_PANEL2, fg=C_TEXT, selectbackground=self.theme["sel"],
                        selectforeground="#ffffff", relief="flat", highlightthickness=0,
                        font=("Microsoft YaHei UI", 10), activestyle="none")
        sb = ttk.Scrollbar(body, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        shown = []

        def refill(*_a):
            q = vq.get().strip().lower()
            lb.delete(0, "end")
            del shown[:]
            for sid in ids:
                txt = self._sw_label(sid)
                if q and q not in txt.lower():
                    continue
                shown.append(sid)
                lb.insert("end", txt)
            if shown:
                lb.selection_set(0)

        def take(_e=None):
            sel = lb.curselection()
            if not sel:
                return
            sid = shown[sel[0]]
            self.edits.setdefault(sec, {})[key] = sid
            win.destroy()
            self._fill_fields()
            self._refresh_list()
            self._update_status_quick()

        vq.trace_add("write", refill)
        lb.bind("<Double-Button-1>", take)
        lb.bind("<Return>", take)
        refill()
        btns = tk.Frame(win, bg=C_PANEL)
        btns.pack(fill="x", padx=10, pady=8)
        self._imgbtn(btns, "换上", take, "btnf").pack(side="right", padx=4)
        self._imgbtn(btns, "取消", win.destroy, "btnf").pack(side="right", padx=4)
        win.minsize(460, 380)
        self._center_on_parent(win, 560, 460)
        ent.focus_set()

    def open_profiles(self):
        if getattr(self, "_prof_win", None) is not None:
            try:
                self._prof_win.deiconify()
                self._prof_win.lift()
                return
            except Exception:
                self._prof_win = None
        win = tk.Toplevel(self)
        self._prof_win = win
        win.title("副本")
        win.transient(self)
        win.configure(bg=C_PANEL)
        win.minsize(440, 300)
        self._center_on_parent(win, 540, 380)

        def close():
            self._prof_win = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", close)

        ttk.Label(win, text="把当前这一套改动存成副本，以后可以一键载回来。",
                  style="Head.TLabel").pack(anchor="w", padx=12, pady=(12, 4))

        row = tk.Frame(win, bg=C_PANEL)
        row.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Label(row, text="名字").pack(side="left")
        var_name = tk.StringVar(value=time.strftime("%m-%d %H-%M"))
        ent = ttk.Entry(row, textvariable=var_name)
        ent.pack(side="left", fill="x", expand=True, padx=(6, 6))
        self._imgbtn(row, "另存当前副本", lambda: self._profile_save(var_name, lb),
                     "btnw").pack(side="left")

        lb = tk.Listbox(win, bg=C_PANEL2, fg=C_TEXT, bd=0, highlightthickness=0,
                        selectbackground=self.theme["sel"], selectforeground="#ffffff",
                        font=("Microsoft YaHei UI", 10))
        lb.pack(fill="both", expand=True, padx=12)
        self._prof_lb = lb

        ios = tk.Frame(win, bg=C_PANEL)
        ios.pack(fill="x", padx=12, pady=(8, 0))
        self._imgbtn(ios, "导出改动到文件…", self._export_profile, "btnf").pack(side="left")
        self._imgbtn(ios, "从文件读取…", self._import_profile, "btnf").pack(side="left", padx=6)

        btns = tk.Frame(win, bg=C_PANEL)
        btns.pack(fill="x", padx=12, pady=10)
        self._imgbtn(btns, "载入选中副本", lambda: self._profile_load(lb, close),
                     "btnf").pack(side="left")
        self._imgbtn(btns, "删除", lambda: self._profile_delete(lb), "btnf").pack(side="left", padx=6)
        self._imgbtn(btns, "关闭", close, "btnf").pack(side="right")

        def fill():
            lb.delete(0, "end")
            self._prof_items = self._profile_files()
            for _p, name, n, tm in self._prof_items:
                lb.insert("end", "%s    (%d 项改动, %s)" % (name, n, tm[:16]))
            if not self._prof_items:
                lb.insert("end", "（还没有副本）")
        self._fill_profiles = fill
        fill()

    # ---------- 副本的导出 / 读取（跨机器传配置） ----------
    def _validate_edits(self, edits):
        """返回 (不认识的节, 不认识的键)，用于导入时提醒。"""
        up2 = {k.upper(): k for k in self.sections}
        bad_sec, bad_key = [], []
        for sec, kv in edits.items():
            real = up2.get(sec.upper())
            if real is None:
                bad_sec.append(sec)
                continue
            keys = {k.upper() for k, _v in self.sections[real]}
            for k in kv:
                if k.upper() not in keys:
                    bad_key.append("%s.%s" % (sec, k))
        return bad_sec, bad_key

    def _export_profile(self):
        n = sum(len(d) for d in self.edits.values())
        if not n:
            messagebox.showinfo("没有改动", "现在一个改动都没有，没什么可导出的。",
                                parent=self._prof_win)
            return
        path = filedialog.asksaveasfilename(
            parent=self._prof_win, title="导出当前改动",
            defaultextension=".json",
            initialfile="MO副本_%s.json" % time.strftime("%m%d_%H%M"),
            filetypes=[("MO 数值副本", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        data = {"app": "MOINIEditor", "version": APP_VERSION,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "edits": {k: dict(v) for k, v in self.edits.items()}}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except Exception as e:
            messagebox.showerror("写不了", "导出时出错：\n%s" % e, parent=self._prof_win)
            return
        self._msg("已导出 %d 项改动到 %s" % (n, os.path.basename(path)))

    def _import_profile(self):
        path = filedialog.askopenfilename(
            parent=self._prof_win, title="读取副本文件",
            filetypes=[("MO 数值副本", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            messagebox.showerror("读不了", "读取文件时出错：\n%s" % e, parent=self._prof_win)
            return
        edits = d.get("edits") if isinstance(d, dict) else None
        if not isinstance(edits, dict):
            messagebox.showerror("不是副本文件",
                                 "这个文件里没有改动数据，是不是选错文件了？",
                                 parent=self._prof_win)
            return
        clean = {}
        for sec, kv in edits.items():
            if isinstance(kv, dict) and kv:
                clean[str(sec)] = {str(k): str(v) for k, v in kv.items()}
        total = sum(len(v) for v in clean.values())
        if not total:
            messagebox.showinfo("文件是空的", "这个副本文件里没有任何改动。",
                               parent=self._prof_win)
            return

        bad_sec, bad_key = self._validate_edits(clean)
        head = ("文件：%s\n版本：%s\n改动：%d 项，涉及 %d 个节"
                % (os.path.basename(path), d.get("version") or "未知", total, len(clean)))
        if bad_sec or bad_key:
            warn = "\n\n⚠ 有 %d 个节、%d 个键在你这版 rulesmo.ini 里找不到" % (
                len(bad_sec), len(bad_key))
            if bad_sec:
                warn += "\n不认识的节：" + "、".join(bad_sec[:5]) + ("…" if len(bad_sec) > 5 else "")
            if bad_key:
                warn += "\n不认识的键：" + "、".join(bad_key[:5]) + ("…" if len(bad_key) > 5 else "")
            warn += "\n\n（多半是 MO 版本不一样，建议先点「重新提取」再导入；强行导入的话这些项可能不生效）"
            if not messagebox.askyesno("版本可能不一致", head + warn + "\n\n仍然载入吗？",
                                       parent=self._prof_win):
                return
        elif not messagebox.askyesno(
                "载入这份副本？", head + "\n\n会覆盖你当前这 %d 项改动（不会动已经写进游戏的规则）。"
                % self._unsaved_count(), parent=self._prof_win):
            return

        self._push_undo("载入副本")
        self.edits = clean
        self._fill_fields()
        self._refresh_list()
        self._update_status_quick()
        self._msg("已读入副本：%d 项改动（记得点「保存到游戏」）" % total)

    def _profile_save(self, var_name, lb):
        name = (var_name.get() or "").strip()
        if not name:
            messagebox.showwarning("名字空着", "给副本起个名字吧。", parent=self._prof_win)
            return
        n = sum(len(d) for d in self.edits.values())
        if n == 0 and not messagebox.askyesno(
                "当前没有改动", "现在一个改动都没有，也要存成空副本吗？", parent=self._prof_win):
            return
        safe = "".join(ch for ch in name if ch not in '\\/:*?"<>|').strip() or "profile"
        path = os.path.join(PROFILE_DIR, safe + ".json")
        if os.path.isfile(path) and not messagebox.askyesno(
                "同名副本已存在", "已经有一个叫「%s」的副本，覆盖它吗？" % safe,
                parent=self._prof_win):
            return
        data = {"name": name, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "edits": {k: dict(v) for k, v in self.edits.items()}}
        try:
            os.makedirs(PROFILE_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except Exception as e:
            messagebox.showerror("存不了", "写入副本时出错：\n%s" % e, parent=self._prof_win)
            return
        if getattr(self, "_fill_profiles", None):
            self._fill_profiles()
        self._msg("副本已保存：%s（%d 项改动）" % (name, n))

    def _profile_load(self, lb, close=None):
        sel = lb.curselection()
        if not sel or not getattr(self, "_prof_items", None):
            messagebox.showinfo("先选一个", "在列表里点一个副本。", parent=self._prof_win)
            return
        idx = sel[0]
        if idx >= len(self._prof_items):
            return
        path, name, n, _tm = self._prof_items[idx]
        if self._unsaved_count() and not messagebox.askyesno(
                "当前有没保存的改动",
                "载入副本会覆盖当前这 %d 项改动（不会动已经写进游戏的规则）。继续吗？"
                % self._unsaved_count(), parent=self._prof_win):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            messagebox.showerror("读不了", "读取副本时出错：\n%s" % e, parent=self._prof_win)
            return
        self.edits = {k: dict(v) for k, v in (d.get("edits") or {}).items()}
        self._fill_fields()
        self._refresh_list()
        self._update_status_quick()
        self._msg("已载入副本「%s」：%d 项改动（记得点「保存到游戏」）" % (name, n))
        if close:
            close()

    def _profile_delete(self, lb):
        sel = lb.curselection()
        if not sel or not getattr(self, "_prof_items", None):
            return
        idx = sel[0]
        if idx >= len(self._prof_items):
            return
        path, name, _n, _tm = self._prof_items[idx]
        if not messagebox.askyesno("删除副本", "删掉「%s」？" % name, parent=self._prof_win):
            return
        try:
            os.remove(path)
        except Exception:
            pass
        if getattr(self, "_fill_profiles", None):
            self._fill_profiles()

    def launch_game(self):
        """用 Syringe（Ares 注入器）启动游戏；没有就退回直接跑 gamemd.exe。"""
        if not self._path_ok():
            messagebox.showwarning("还没设置游戏目录",
                                   "请先指定 Mental Omega 安装目录（含 gamemd.exe）。")
            return
        n = self._unsaved_count()
        if n:
            ans = messagebox.askyesnocancel(
                "还有改动没保存",
                "有 %d 项改动还没写进游戏目录。\n\n"
                "是 = 先保存再启动\n"
                "否 = 不保存，直接启动（这次的改动不会生效）\n"
                "取消 = 什么都不做" % n)
            if ans is None:
                return
            if ans:
                self.save()
                if self._unsaved_count():
                    return
        gem = os.path.join(self.game_dir, "gamemd.exe")
        syr = os.path.join(self.game_dir, "Syringe.exe")
        cli = os.path.join(self.game_dir, "MentalOmegaClient.exe")
        params = self._launch_params()
        try:
            if os.path.isfile(cli):
                # 优先启动客户端（和平时双击那个一样：有菜单/战役/遭遇战，
                # 它自己会用正确的参数去调 Syringe + gamemd）。
                subprocess.Popen('"%s"' % cli, cwd=self.game_dir)
            elif os.path.isfile(syr):
                # Syringe 用法是 `Syringe.exe "<exe name>" <参数>`，exe 名必须带引号；
                # 不带引号它会认为参数无效，直接退出（实测日志 "No or invalid command line arguments"）。
                subprocess.Popen('"%s" "gamemd.exe" %s' % (syr, params), cwd=self.game_dir)
            elif os.path.isfile(gem):
                subprocess.Popen('"%s" %s' % (gem, params), cwd=self.game_dir)
            else:
                messagebox.showerror("找不到游戏程序",
                                     "这个目录里没有 MentalOmegaClient.exe / gamemd.exe：\n%s" % self.game_dir)
                return
            self._msg("已启动游戏（改动需重启游戏才生效）。")
        except Exception as e:
            messagebox.showerror("启动失败", "启动游戏时出错：\n%s" % e)

    def _launch_params(self):
        """启动参数：照客户端 ClientDefinitions.ini 里的 ExtraCommandLineParams，前面补 -SPAWN。

        没有 -SPAWN 时 MO 的 gamemd.exe 起不到几秒就自己退出（实测 exit code 1），
        所以这里跟客户端保持一致。
        """
        params = "-SPAWN -CD -SPEEDCONTROL -LOG -AFFINITY:1048575"
        cd = os.path.join(self.game_dir, "Resources", "ClientDefinitions.ini")
        try:
            with open(cd, "r", encoding="latin1") as f:
                for line in f:
                    if line.strip().lower().startswith("extracommandlineparams="):
                        extra = line.split("=", 1)[1].strip()
                        if extra:
                            params = "-SPAWN " + extra
                        break
        except Exception:
            pass
        return params

    def _save_game_dir(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(SETTINGS, "w", encoding="utf-8") as f:
                f.write(self.game_dir)
        except Exception:
            pass

    # ---------- 窗口位置记忆 ----------
    def _load_geometry(self):
        try:
            with open(GEO_FILE, "r", encoding="utf-8") as f:
                raw = f.read().strip()
        except Exception:
            return None
        if not raw:
            return None
        parts = raw.split()
        zoomed = parts[0] == "zoomed" if parts else False
        geo = parts[-1]
        m = re.match(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$", geo)
        if not m:
            return None
        w, h, x, y = (int(m.group(i)) for i in range(1, 5))
        # 屏幕换了 / 显示器没了：位置不合法就别用
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
        except Exception:
            sw, sh = 1920, 1080
        if w < 600 or h < 400 or w > sw + 200 or h > sh + 200:
            return None
        if x < -50 or y < -50 or x > sw - 200 or y > sh - 100:
            return None
        self._want_zoom = zoomed
        return "%dx%d+%d+%d" % (w, h, x, y)

    def _save_geometry(self):
        try:
            st = "zoomed" if self.state() == "zoomed" else "normal"
            geo = self.geometry()
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(GEO_FILE, "w", encoding="utf-8") as f:
                f.write("%s %s" % (st, geo))
        except Exception:
            pass

    # ---------- 界面 ----------
    # ---------- 美术资源 / 控件工厂 ----------
    def _load_art(self):
        self._imgs = {}
        for name in ("btn", "btnf", "btnw", "btnbig"):
            for st in ("idle", "hover", "active"):
                p = os.path.join(ART_DIR, "%s_%s.png" % (name, st))
                try:
                    self._imgs[(name, st)] = tk.PhotoImage(file=p)
                except Exception:
                    self._imgs[(name, st)] = None
        self._theme_imgs = {}
        for key in ("def", "allied", "soviet", "epsilon", "foehn", "neutral"):
            for size in ("btn", "btnf"):
                p = os.path.join(ART_DIR, "%s_active_%s.png" % (size, key))
                try:
                    self._theme_imgs[(size, key)] = tk.PhotoImage(file=p)
                except Exception:
                    self._theme_imgs[(size, key)] = None
        try:
            self._bgimg = tk.PhotoImage(file=os.path.join(ART_DIR, "bg.png"))
        except Exception:
            self._bgimg = None

    def _imgbtn(self, parent, text, cmd, size="btn", font=None, fg="#1b1424"):
        b = tk.Button(parent, text=text, command=cmd, bd=0, highlightthickness=0,
                      relief="flat", takefocus=0, cursor="hand2",
                      font=font or ("Microsoft YaHei UI", 9, "bold"),
                      padx=0, pady=0, bg=C_PANEL, activebackground=C_PANEL)
        b._imgs = {st: self._imgs.get((size, st)) for st in ("idle", "hover", "active")}
        b._fg = fg
        img = b._imgs["idle"]
        if img is not None:
            b.configure(image=img, compound="center", width=img.width(), height=img.height())
            b._size = (img.width(), img.height())
        else:
            b._size = None
        b._selected = False
        b.configure(fg=fg, activeforeground=fg)
        b.bind("<Enter>", lambda e, b=b: self._btn_hover(b, True))
        b.bind("<Leave>", lambda e, b=b: self._btn_hover(b, False))
        return b

    @staticmethod
    def _enabled(b):
        try:
            return str(b.cget("state")) != "disabled"
        except Exception:
            return True

    @staticmethod
    def _pin_size(b):
        sz = getattr(b, "_size", None)
        if sz:
            try:
                b.configure(width=sz[0], height=sz[1])
            except Exception:
                pass

    def _link(self, parent, text, cmd):
        """超链接样式的文字按钮（无底板，融入背景）"""
        lb = tk.Label(parent, text=text, bg=C_PANEL, fg=self.theme["accent"],
                      font=("Microsoft YaHei UI", 10, "underline"),
                      cursor="hand2", padx=2, pady=0)
        lb.bind("<Button-1>", lambda e: cmd())
        lb.bind("<Enter>", lambda e: lb.configure(fg="#ffffff"))
        lb.bind("<Leave>", lambda e: lb.configure(fg=self.theme["accent"]))
        self._links.append(lb)
        return lb

    def _btn_hover(self, b, on):
        if not self._enabled(b):
            return
        st = "active" if getattr(b, "_selected", False) else ("hover" if on else "idle")
        img = getattr(b, "_imgs", {}).get(st)
        if img is not None:
            b.configure(image=img)
        b.configure(fg=self.theme["accent"] if st == "active" else getattr(b, "_fg", "#1b1424"))
        self._pin_size(b)

    def _btn_select(self, b, on):
        b._selected = on
        img = getattr(b, "_imgs", {}).get("active" if on else "idle")
        if img is not None:
            b.configure(image=img)
        b.configure(fg=self.theme["accent"] if on else getattr(b, "_fg", "#1b1424"))
        self._pin_size(b)

    def _set_enabled(self, b, on):
        b.configure(state="normal" if on else "disabled",
                    cursor="hand2" if on else "",
                    fg=getattr(b, "_fg", "#1b1424") if on else "#7d7688")
        if not on:
            img = getattr(b, "_imgs", {}).get("idle")
            if img is not None:
                b.configure(image=img)
        self._pin_size(b)

    # ---------- 界面 ----------
    def _place_banner(self, ev=None):
        try:
            w = self.banner.winfo_width()
            x = (w - self._banner_img.width()) // 2
            self.banner.coords(self._banner_item, x if x < 0 else 0, 0)
        except Exception:
            pass

    def _init_styles(self):
        t = self.theme
        st = self.style
        st.configure(".", background=t["panel"], foreground=C_TEXT,
                     fieldbackground=C_PANEL2, bordercolor=t["edge"],
                     lightcolor=t["edge"], darkcolor=t["edge"],
                     troughcolor="#0d0a13", focuscolor=t["accent"])
        st.configure("TFrame", background=t["panel"])
        st.configure("TLabel", background=t["panel"], foreground=C_DIM,
                     font=("Microsoft YaHei UI", 10))
        st.configure("Head.TLabel", background=t["panel"], foreground=t["accent"],
                     font=("Microsoft YaHei UI", 11, "bold"))
        st.configure("Small.TLabel", background=t["panel"], foreground=C_DIM)
        st.configure("Ok.TLabel", background=t["panel"], foreground=C_OK)
        st.configure("Warn.TLabel", background=t["panel"], foreground=C_WARN)
        st.configure("Bad.TLabel", background=t["panel"], foreground=C_BAD,
                     font=("Microsoft YaHei UI", 10, "bold"))
        st.configure("HTitle.TLabel", background=t["bar"], foreground=t["accent"],
                     font=("Microsoft YaHei UI", 13, "bold"))
        st.configure("HSmall.TLabel", background=t["bar"], foreground=C_DIM)
        st.configure("HOk.TLabel", background=t["bar"], foreground=C_OK)
        st.configure("HWarn.TLabel", background=t["bar"], foreground=C_WARN)
        st.configure("HBad.TLabel", background=t["bar"], foreground=C_BAD,
                     font=("Microsoft YaHei UI", 10, "bold"))
        st.configure("TEntry", fieldbackground=C_PANEL2, foreground="#f4eefc",
                     insertcolor=t["accent"], bordercolor=t["edge"],
                     lightcolor=t["edge"], darkcolor=t["edge"], padding=4,
                     font=("Microsoft YaHei UI", 10))
        st.map("TEntry", fieldbackground=[("focus", "#241b31")],
               bordercolor=[("focus", t["accent"])])
        st.configure("TCheckbutton", background=t["panel"], foreground=C_DIM,
                     focuscolor=t["panel"])
        st.map("TCheckbutton", background=[("active", t["panel"])],
               foreground=[("active", t["accent"])])
        st.configure("TScrollbar", background="#2b2338", troughcolor="#0d0a13",
                     bordercolor="#0d0a13", arrowcolor=t["accent"])
        st.map("TScrollbar", background=[("active", "#463257")])

    def _apply_theme(self, key):
        """按阵营换配色（不含背景图）"""
        t = FAC_THEME.get(key) or FAC_THEME["全部"]
        self.theme = dict(t)
        self.theme_key = key
        if not hasattr(self, "_panels"):
            return
        self._init_styles()
        for w in self._panels:
            try:
                w.configure(bg=t["panel"])
            except Exception:
                pass
        for w in self._bars:
            try:
                w.configure(bg=t["bar"])
            except Exception:
                pass
        for w in self._edges:
            try:
                w.configure(bg=t["edge"], highlightbackground=t["edge"])
            except Exception:
                pass
        try:
            self.canvas.configure(bg=t["panel"])
            self.inner.configure(bg=t["panel"])
            self.lst.configure(bg=t["list"], selectbackground=t["sel"],
                               selectforeground="#ffffff")
        except Exception:
            pass
        for lb in getattr(self, "_links", []):
            try:
                lb.configure(fg=t["accent"])
            except Exception:
                pass
        self._fill_fields() if getattr(self, "cur_sec", None) else None
        self.configure(bg=t["bar"])
        img = self._theme_imgs.get(t["img"])
        for size, btns in (("btnf", getattr(self, "_fac_buttons", {})),
                           ("btn", getattr(self, "_kind_buttons", {}))):
            im = self._theme_imgs.get((size, t["img"]))
            if im is not None:
                for b in btns.values():
                    b._imgs["active"] = im
        if hasattr(self, "_fac_buttons"):
            self._paint_buttons(self._fac_buttons, self.fac)
        if hasattr(self, "_kind_buttons"):
            self._paint_buttons(self._kind_buttons, self.kind)
        if self._banner_img is not None:
            pass
        self._fill_fields() if getattr(self, "cur_sec", None) else None

    def _build_ui(self):
        self.option_add("*Font", ("Microsoft YaHei UI", 10))
        self._load_art()
        self.theme = dict(FAC_THEME["全部"])
        self.theme_key = "全部"
        self._panels, self._bars, self._edges = [], [], []
        self._links = []
        self.configure(bg=FAC_THEME["全部"]["bar"])

        if self._bgimg is not None:
            self.bg = tk.Label(self, image=self._bgimg, bd=0, bg="#07050b")
            self.bg.place(x=0, y=0, relwidth=1, relheight=1)

        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self._init_styles()

        # ---- 顶部横幅：MO 载入画面 + 标题 ----
        self.banner = tk.Canvas(self, height=96, highlightthickness=0, bd=0, bg="#07050b")
        self.banner.pack(fill="x")
        try:
            self._banner_img = tk.PhotoImage(file=os.path.join(ART_DIR, "banner.png"))
        except Exception:
            self._banner_img = None
        self.banner.create_text(17, 57, text="MENTAL OMEGA", anchor="w",
                                font=("Microsoft YaHei UI", 22, "bold"), fill="#1a0618")
        self.banner.create_text(15, 55, text="MENTAL OMEGA", anchor="w",
                                font=("Microsoft YaHei UI", 22, "bold"), fill=C_GOLD)
        self.banner.create_text(18, 80, text="数值编辑器 v%s   ·   rulesmo.ini" % APP_VERSION, anchor="w",
                                font=("Microsoft YaHei UI", 9), fill="#2a1030")
        self.banner.create_text(17, 79, text="数值编辑器 v%s   ·   rulesmo.ini" % APP_VERSION, anchor="w",
                                font=("Microsoft YaHei UI", 9), fill="#d9bfe8")
        if self._banner_img is not None:
            self._banner_item = self.banner.create_image(0, 0, anchor="nw", image=self._banner_img)
            self.banner.tag_lower(self._banner_item)
            self.banner.bind("<Configure>", self._place_banner)

        # ---- 目录 / 状态条 ----
        top = tk.Frame(self, bg=self.theme["bar"])
        top.pack(fill="x")
        self._bars.append(top)
        # 最左上角：关于（单独一行，不和「副本 / 神秘」并排）
        corner = tk.Frame(top, bg=self.theme["bar"])
        corner.pack(fill="x", padx=10, pady=(2, 0))
        self._bars.append(corner)
        self.lnk_undo = self._link(corner, "撤销", self.undo)
        self.lnk_undo.pack(side="left")
        self.lnk_redo = self._link(corner, "还原", self.redo)
        self.lnk_redo.pack(side="left", padx=(14, 0))
        self.lnk_changes = self._link(corner, "内容", self.open_changes)
        self.lnk_changes.pack(side="left", padx=(14, 0))
        self._link(corner, "关于", self.open_about).pack(side="left", padx=(14, 0))
        inner_top = tk.Frame(top, bg=self.theme["bar"])
        inner_top.pack(fill="x", padx=12, pady=(4, 4))
        self._bars.append(inner_top)
        self._imgbtn(inner_top, "副本", self.open_profiles, "btn").pack(side="left", padx=(0, 6))
        self.btn_mystery = self._imgbtn(inner_top, "神秘", self.mystery, "btn")
        self.btn_mystery.pack(side="left", padx=(0, 10))
        self._set_enabled(self.btn_mystery, False)
        ttk.Label(inner_top, text="游戏目录：", style="HSmall.TLabel").pack(side="left")
        self.lbl_dir = ttk.Label(inner_top, text=self.game_dir, style="HSmall.TLabel")
        self.lbl_dir.pack(side="left")
        self._imgbtn(inner_top, "选择目录", self.choose_dir, "btnw").pack(side="left", padx=(8, 4))
        self._imgbtn(inner_top, "重新提取", self.reextract, "btnw").pack(side="left")
        self.lbl_state = ttk.Label(inner_top, text="", style="HSmall.TLabel")
        self.lbl_state.pack(side="right")
        sep = tk.Frame(top, bg=self.theme["edge"], height=1)
        sep.pack(fill="x")
        self._edges.append(sep)

        # ---- 路径警告条 ----
        self.warn_bar = tk.Frame(self, bg=self.theme["bar"])
        self._bars.append(self.warn_bar)
        self.lbl_warn = ttk.Label(self.warn_bar, text="", style="HBad.TLabel")
        self.lbl_warn.pack(side="left", padx=12, pady=(3, 1))
        self.warn_bar.pack(fill="x")

        # ---- 控制面板：第一行 搜索 + 分类，第二行 阵营 ----
        ctrl = tk.Frame(self, bg=self.theme["panel"], highlightbackground=self.theme["edge"],
                        highlightthickness=1)
        ctrl.pack(fill="x", padx=10, pady=(6, 0))
        self._panels.append(ctrl)

        sf = tk.Frame(ctrl, bg=self.theme["panel"])
        sf.pack(fill="x", padx=10, pady=(6, 2))
        self._panels.append(sf)
        ttk.Label(sf, text="搜索").pack(side="left")
        self.var_q = tk.StringVar()
        self.ent_q = ttk.Entry(sf, textvariable=self.var_q, width=22)
        self.ent_q.pack(side="left", padx=8)
        self.ent_q.bind("<KeyRelease>", self._on_type)
        # 搜索框内靠右的小叉：只在有内容时显示，点一下清空（其它输入框没有）
        self.lnk_clear_q = tk.Label(sf, text="\u2715", bg=C_PANEL2, fg=C_DIM,
                                    font=("Microsoft YaHei UI", 9), cursor="hand2",
                                    bd=0, padx=2)
        self.lnk_clear_q.bind("<Button-1>", lambda e: self.clear_search())
        self.lnk_clear_q.bind("<Enter>", lambda e: self.lnk_clear_q.configure(fg=C_TEXT))
        self.lnk_clear_q.bind("<Leave>", lambda e: self.lnk_clear_q.configure(fg=C_DIM))
        self.var_q.trace_add("write", lambda *a: self._sync_clear_q())
        self.after(300, self._sync_clear_q)
        self.lbl_count = ttk.Label(sf, text="", style="Small.TLabel")
        self.lbl_count.pack(side="left", padx=(2, 8))

        self._kind_buttons = {}
        for k in reversed(["全部"] + KIND_ORDER):
            b = self._imgbtn(sf, k, lambda kk=k: self._set_kind(kk), "btn")
            b.pack(side="right", padx=2)
            self._kind_buttons[k] = b
        ttk.Label(sf, text="分类").pack(side="right", padx=(8, 2))
        self.kind = "全部"
        self._paint_kind_buttons()

        ff = tk.Frame(ctrl, bg=self.theme["panel"])
        ff.pack(fill="x", padx=10, pady=(2, 7))
        self._panels.append(ff)
        ttk.Label(ff, text="阵营").pack(side="left", padx=(0, 8))
        self._fac_buttons = {}
        for f in ["全部"] + FAC_ORDER:
            disp = "全部" if f == "全部" else FAC_DISPLAY.get(f, f)
            b = self._imgbtn(ff, disp, lambda kk=f: self._set_fac(kk), "btnf")
            b.pack(side="left", padx=3)
            self._fac_buttons[f] = b
        self.fac = "全部"
        self._paint_buttons(self._fac_buttons, self.fac)

        # ---- 主区：左列表 + 右字段 ----
        main = tk.Frame(self, bg=self.theme["panel"], highlightbackground=self.theme["edge"],
                        highlightthickness=1)
        main.pack(fill="both", expand=True, padx=10, pady=(6, 0))
        self._panels.append(main)

        left = tk.Frame(main, bg=self.theme["panel"])
        left.pack(side="left", fill="both", expand=False, padx=(6, 0), pady=6)
        self._panels.append(left)
        self.lst = tk.Listbox(left, exportselection=False, activestyle="none", width=40,
                              font=("Microsoft YaHei UI", 11), selectmode="browse",
                              bg=self.theme["list"], fg="#f2ecfa", bd=0, highlightthickness=0,
                              selectbackground=self.theme["sel"], selectforeground="#ffffff",
                              relief="flat")
        sb = ttk.Scrollbar(left, orient="vertical", command=self.lst.yview)
        self.lst.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.lst.pack(side="left", fill="both", expand=True)
        self.lst.bind("<<ListboxSelect>>", self._on_select)

        vsep = tk.Frame(main, bg=self.theme["edge"], width=1)
        vsep.pack(side="left", fill="y", pady=6)
        self._edges.append(vsep)

        right = tk.Frame(main, bg=self.theme["panel"])
        right.pack(side="left", fill="both", expand=True, padx=6, pady=(6, 0))
        self._panels.append(right)

        hdr = tk.Frame(right, bg=self.theme["panel"])
        hdr.pack(fill="x")
        self._panels.append(hdr)
        self.lbl_title = ttk.Label(hdr, text="（在左边搜索并选择一个单位）", style="Head.TLabel",
                                  wraplength=640, justify="left")
        self.lbl_title.pack(side="left")
        self.var_common = tk.BooleanVar(value=True)
        ttk.Checkbutton(hdr, text="只看常用数值", variable=self.var_common,
                        command=self._fill_fields).pack(side="right", padx=(6, 2))
        self._imgbtn(hdr, "还原此单位", self.reset_unit, "btnw").pack(side="right", padx=4)

        # 可滚动字段区
        wrap = tk.Frame(right, bg=self.theme["panel"])
        wrap.pack(fill="both", expand=True, pady=(4, 6))
        self._panels.append(wrap)
        self.canvas = tk.Canvas(wrap, highlightthickness=0, bg=self.theme["panel"], bd=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.inner = tk.Frame(self.canvas, bg=self.theme["panel"])
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        # 第 1 列留给「⚠ 警告图标」，第 2 列才是输入框（这样图标永远在框左边）
        self.inner.columnconfigure(1, weight=0, minsize=18)
        self.inner.columnconfigure(2, weight=1)

        # ---- 底栏 ----
        bottom = tk.Frame(self, bg=self.theme["bar"])
        bottom.pack(fill="x")
        self._bars.append(bottom)
        self.lbl_msg = ttk.Label(bottom, text="", style="HSmall.TLabel")
        self.lbl_msg.pack(side="left", padx=12, pady=6)
        self.btn_play = self._imgbtn(bottom, "启动游戏", self.launch_game, "btnbig")
        self.btn_play.pack(side="right", padx=(6, 10), pady=5)
        self.btn_restore = self._imgbtn(bottom, "全部还原", self.restore_all, "btnbig")
        self.btn_restore.pack(side="right", padx=(6, 0), pady=5)
        self.btn_save = self._imgbtn(bottom, "保存到游戏", self.save, "btnbig")
        self.btn_save.pack(side="right", pady=5)

    @staticmethod
    def _is_descendant(w, parent):
        while w is not None:
            if w is parent:
                return True
            w = getattr(w, "master", None)
        return False

    def _on_wheel(self, ev):
        # 只滚动光标底下那个列表/面板
        step = int(-1 * (ev.delta / 120))
        if step == 0:
            step = -1 if ev.delta > 0 else 1
        w = ev.widget
        if self._is_descendant(w, self.lst):
            self._cancel_top_jobs()
            self.lst.yview_scroll(step, "units")
            return "break"
        if w is self.canvas or self._is_descendant(w, self.inner):
            self._cancel_top_jobs()
            if self.canvas.bbox("all") and \
                    self.canvas.bbox("all")[3] > self.canvas.winfo_height():
                self.canvas.yview_scroll(step, "units")
            return "break"
        return None

    # ---------- 目录有效性 ----------
    def _path_ok(self):
        d = self.game_dir
        if not d or not os.path.isdir(d):
            return False
        if os.path.isfile(os.path.join(d, "gamemd.exe")):
            return True
        return any(f.lower().endswith(".mix") for f in os.listdir(d))

    def _update_path_state(self):
        ok = self._path_ok()
        if ok:
            self.lbl_dir.configure(text=self.game_dir, style="HSmall.TLabel")
            self.lbl_warn.configure(text="")
            self._set_enabled(self.btn_save, True)
            self._set_enabled(self.btn_restore, True)
        else:
            self.lbl_dir.configure(text=self.game_dir or "（未设置）", style="HBad.TLabel")
            self.lbl_warn.configure(
                text="⚠ 游戏目录无效：请点上面的「选择目录」，选中 Mental Omega 安装目录"
                     "（里面有 gamemd.exe 的那个）。设好之前不能保存。")
            self._set_enabled(self.btn_save, False)
            self._set_enabled(self.btn_restore, False)
        return ok

    # ---------- 启动加载 ----------
    def _startup(self):
        self.after(160, self._show_notice)
        auto = getattr(self, "_auto_found", None)
        if auto:
            self._auto_found = None
            self._update_path_state()
            self._msg("已自动识别游戏目录：%s" % auto)
        else:
            self._update_path_state()
            if getattr(self, "_auto_timeout", False):
                self._auto_timeout = False
                self._msg("自动查找游戏目录超过 5 秒，已停下：请点「选择目录」手动指定。", warn=True)
        if not self._path_ok():
            self._msg("请先指定游戏目录（含 gamemd.exe）。", warn=True)
            return
        if not self._ensure_base():
            return
        self._load_base()
        self._refresh_state()

    def _ensure_base(self):
        if os.path.isfile(BASE_FILE) and os.path.getsize(BASE_FILE) > 100000:
            return True
        self._msg("首次运行：正在从游戏 .mix 里提取 rulesmo.ini（只读，约几秒）…")
        self.update_idletasks()
        found = extract_rules_from_mixes(self.game_dir, log=lambda s: (self._msg(s), self.update_idletasks()))
        if found:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(BASE_FILE, "wb") as f:
                f.write(found[1].encode("latin1", "ignore"))
            return True
        # 兜底：游戏根目录已有 rulesmo.ini
        loose = os.path.join(self.game_dir, RULE_FILE_NAME)
        if os.path.isfile(loose):
            import shutil
            os.makedirs(DATA_DIR, exist_ok=True)
            shutil.copyfile(loose, BASE_FILE)
            return True
        self._msg("提取失败：游戏目录里没有可读的 rulesmo.ini。", warn=True)
        messagebox.showerror(
            "无法获取 rulesmo.ini",
            "没能在 %s 的 .mix 里找到 rulesmo.ini，\n"
            "也没找到根目录下的 rulesmo.ini。\n\n"
            "请确认游戏目录选择正确。" % self.game_dir)
        return False

    def _load_base(self):
        with open(BASE_FILE, "rb") as f:
            self.base_text = f.read().decode("latin1")
        self._reindex()
        self._load_edits_from_loose()
        self._refresh_list()
        self._update_title_state()

    def _reindex(self):
        self.sections, self.order = parse_ini(self.base_text)
        kind_of = {}
        for listname, kind in KINDS:
            for uid in type_list_ids(self.sections, listname):
                if uid in self.sections and uid not in kind_of:
                    kind_of[uid] = kind
        # ---- 部署形态：车 ↔ 建筑互指（AMCV↔GACNST、BOID↔FABOID…）----
        # 建筑形态在 ini 里通常没有 Owner=，阵营/名字都从载具那边继承。
        self.deploy_pair = {}
        up2sec = {o.upper(): o for o in self.order}
        for sec in self.order:
            for key in ("DeploysInto", "UndeploysInto"):
                val = self._first_val(sec, key).strip()
                if not val or val.lower() in ("no", "none", "yes"):
                    continue
                other = up2sec.get(val.upper())
                if other:
                    self.deploy_pair[sec.upper()] = other
                    self.deploy_pair.setdefault(other.upper(), sec)
        for s_up, other in self.deploy_pair.items():
            if s_up not in self.factions and other.upper() in self.factions:
                self.factions[s_up] = self.factions[other.upper()]
        # ---- 支援技能（[SuperWeaponTypes] 注册表）----
        self.sw_set = set()
        self.sw_set_order = []
        for uid in type_list_ids(self.sections, "SuperWeaponTypes"):
            if uid in self.sections:
                kind_of[uid] = SW_KIND
                self.sw_set.add(uid.upper())
                self.sw_set_order.append(uid)
        # 建筑 → 挂载的技能；技能 → 提供它的建筑
        self.building_sw = {}
        self.sw_owners = {}
        for sec in self.order:
            if kind_of.get(sec) != "建筑":
                continue
            for k, v in self.sections.get(sec, []):
                if k.lower() in ("superweapon", "superweapon2", "superweapons"):
                    ids = [x.strip() for x in v.split(",") if x.strip()]
                    if not ids:
                        continue
                    self.building_sw.setdefault(sec, []).append((k, v))
                    for sid in ids:
                        if self.sections.get(sid) is not None:
                            self.sw_owners.setdefault(sid.upper(), []).append((sec, k))
        index = []
        for sec in self.order:
            kind = kind_of.get(sec, "其他")
            nm = self._first_val(sec, "Name")
            if not nm:
                uin = self._first_val(sec, "UIName")
                nm = uin.split(":", 1)[-1] if uin else ""
            index.append((sec, kind, nm or ""))
        self.index = index
        self.units = [e for e in index if e[1] in _UNIT_PRI]
        # 节 ID 大写表 + 武器被哪些单位使用（用于“同种武器”注释）
        self.sec_by_up = {}
        for sec, _k, _n in index:
            self.sec_by_up.setdefault(sec.upper(), sec)
        self._mark_unbuildable(index)
        self.wpn_users = {}
        for sec, kind, _nm in index:
            if kind not in _UNIT_PRI:
                continue
            for slot in WEAPON_SLOTS:
                wid = self._first_val(sec, slot).strip()
                if not wid:
                    continue
                ws = self.sec_by_up.get(wid.upper())
                if not ws or ws.upper() == sec.upper():
                    continue
                self.wpn_users.setdefault(ws.upper(), []).append(sec)

    def _tl_of(self, sec):
        """科技等级；缺失返回 None。"""
        t = self._first_val(sec, "TechLevel").strip()
        if not t:
            return None
        try:
            return int(float(t))
        except ValueError:
            return None

    def _mark_unbuildable(self, index):
        """标出玩家造不出来的条目（列表里灰显）：
        ① 科技等级不在 TL_MIN..TL_MAX；② 步兵/车辆/空军没有 Owner=（诱饵、导弹、生成物）；
        ③ Prerequisite 里写了不存在的节，或那个建筑的科技等级超出范围。"""
        self.gray = set()
        # 建造场这类“由基地车展开出来”的建筑，科技等级都是 -1，但它们是能造出来的
        deploy_forms = set(getattr(self, "deploy_pair", {}).keys()) | \
            {v.upper() for v in getattr(self, "deploy_pair", {}).values()}
        for sec, kind, _nm in index:
            if kind not in ("建筑", "步兵", "车辆", "空军"):
                continue
            if self._fac_of(sec) == "中立&其他":
                # 中立&其他 里的东西本来就不是“玩家造”的（科技建筑靠占、平民是装饰、渗透单位靠偷），
                # 一律不灰，否则整栏全灰反而看不出区别
                continue
            tl = self._tl_of(sec)
            bad = tl is None or tl < TL_MIN or tl > TL_MAX
            if bad and sec.upper() in deploy_forms:
                bad = False
            if not bad and kind in ("步兵", "车辆", "空军"):
                if not self._first_val(sec, "Owner").strip() and sec.upper() not in STOLEN_TECH:
                    bad = True
            if not bad:
                pre = self._first_val(sec, "Prerequisite")
                for p in [x.strip() for x in pre.split(",") if x.strip()]:
                    real = self.sec_by_up.get(p.upper())
                    if real is None:
                        # ALLWEAP / SOVTECH / POWER 这类是“任意某类建筑”的占位词，不是节
                        continue
                    ptl = self._tl_of(real)
                    # -1 是“不靠建造获得”的建筑（建造场之类），算正常
                    if ptl is None or ptl < -1 or ptl > TL_MAX:
                        bad = True
                        break
            if bad:
                self.gray.add(sec.upper())

    def _is_gray(self, sec):
        return sec.upper() in getattr(self, "gray", ())

    def _first_val(self, sec, key):
        for k, v in self.sections.get(sec, []):
            if k.lower() == key.lower():
                return v
        return ""

    # ---------- 副本文件 ----------
    def _loose_path(self):
        return os.path.join(self.game_dir, RULE_FILE_NAME)

    def _loose_text(self):
        p = self._loose_path()
        if not os.path.isfile(p):
            return None
        try:
            with open(p, "rb") as f:
                return f.read().decode("latin1")
        except Exception:
            return None

    def _is_ours(self, text):
        return bool(text) and SENTINEL in text

    def _load_edits_from_loose(self):
        """把副本和原版对比，反推出改过哪些键。"""
        self.edits = {}
        self.saved_edits = {}
        self.dirty = set()
        text = self._loose_text()
        if not text:
            return
        loose, _ = parse_ini(text)
        upper = {s.upper(): s for s in self.sections}
        for sec, items in loose.items():
            if sec.upper().startswith(";"):
                continue
            base = {k.upper(): v for k, v in self.sections.get(upper.get(sec.upper(), ""), [])}
            d = {}
            for k, v in items:
                if k.startswith(";"):
                    continue
                ku = k.upper()
                if ku not in base or base[ku] != v:
                    d[k] = v
            if d:
                self.edits[sec] = d
        self.dirty = {(s, k) for s, d in self.edits.items() for k in d}

    # ---------- 状态显示 ----------
    def _refresh_state(self):
        text = self._loose_text()
        n = sum(len(d) for d in self.edits.values())
        if text is None:
            self.lbl_state.configure(text="状态：原版数值（无规则副本）", style="HSmall.TLabel")
        elif self._is_ours(text):
            self.lbl_state.configure(text="● 已启用（改 %d 项）" % n, style="HOk.TLabel")
        else:
            self.lbl_state.configure(text="状态：检测到已有自制 rulesmo.ini", style="HWarn.TLabel")
        self._msg("")

    def _update_title_state(self):
        if self.current:
            sec, kind, name = self.current
            cn = self.cn.get(sec.upper(), "")
            if cn and name and name != sec:
                t = "%s    %s    [%s]" % (cn, name, sec)
            else:
                t = "%s    [%s]" % (self._disp(sec, name), sec)
            self.lbl_title.configure(text=t)
        else:
            self.lbl_title.configure(text="（在左边搜索并选择一个单位）")

    def _msg(self, text, warn=False):
        self.lbl_msg.configure(text=text, style="HWarn.TLabel" if warn else "HSmall.TLabel")

    def _disp(self, sec, name):
        """列表/标题里显示的名字：中文名优先，其次英文 Name=，最后节ID。"""
        cn = self.cn.get(sec.upper(), "")
        if cn:
            return cn
        # 部署形态的建筑/车辆没有独立中文名时，借载体的名字
        up = getattr(self, "deploy_pair", {}).get(sec.upper())
        if up:
            cn2 = self.cn.get(up.upper(), "")
            if cn2:
                return "%s（展开形态）" % cn2
        return name if name and name != sec else sec

    # ---------- 搜索 ----------
    def _sync_clear_q(self):
        """搜索框有内容就在框内右侧显示小叉。"""
        w = getattr(self, "lnk_clear_q", None)
        if w is None or not w.winfo_exists():
            return
        if self.var_q.get().strip():
            try:
                w.place(in_=self.ent_q, relx=1.0, rely=0.5, anchor="e", x=-6)
                w.lift()
            except Exception:
                pass
        else:
            try:
                w.place_forget()
            except Exception:
                pass

    def clear_search(self):
        self.var_q.set("")
        self._sync_clear_q()
        self._refresh_list()
        try:
            self.ent_q.focus_set()
        except Exception:
            pass

    def _on_type(self, _ev=None):
        if getattr(self, "_pending", None):
            self.after_cancel(self._pending)
        self._pending = self.after(150, self._refresh_list)

    def _set_kind(self, k):
        self.kind = k
        self._paint_kind_buttons()
        self._refresh_list()

    def _sync_mystery(self):
        try:
            self._set_enabled(self.btn_mystery, getattr(self, "fac", "全部") in MYSTERY_FACS)
        except Exception:
            pass

    def _set_fac(self, f):
        self.fac = f
        self._apply_theme(f)
        self._sync_mystery()
        self._paint_buttons(self._fac_buttons, self.fac)
        self._refresh_list()

    def _paint_buttons(self, buttons, active):
        for k, b in buttons.items():
            self._btn_select(b, k == active)

    def _paint_kind_buttons(self):
        self._paint_buttons(self._kind_buttons, self.kind)

    def _fac_of(self, sec):
        return self.factions.get(sec.upper(), "中立&其他")

    def _fac_set(self, sec):
        """一个节可能属于多个阵营（支援技能被多个建筑提供时）。"""
        f = self.factions.get(sec.upper())
        if f:
            return {f}
        out = set()
        for bsec, _k in getattr(self, "sw_owners", {}).get(sec.upper(), []):
            fb = self.factions.get(bsec.upper())
            if fb:
                out.add(fb)
        return out or {"中立&其他"}

    def _fac_rank(self, sec):
        s = self._fac_set(sec)
        return min(FAC_PRI.get(f, 9) for f in s)

    def _refresh_list(self):
        self._pending = None
        q = self.var_q.get().strip().lower()
        self.lst.delete(0, "end")
        self._rows = []
        want = getattr(self, "kind", "全部")
        wantf = getattr(self, "fac", "全部")
        for sec, kind, name in getattr(self, "index", []):
            if want != "全部" and kind != want:
                continue
            if wantf != "全部" and wantf not in self._fac_set(sec):
                continue
            cn = self.cn.get(sec.upper(), "")
            hay = (sec + " " + name + " " + cn).lower()
            if q and q not in hay:
                continue
            self._rows.append((sec, kind, name))
        if q:
            def _grp(sec):
                # 0 = 正常且有中文名，1 = 灰显（造不出来），2 = 正常但没中文名
                if self._is_gray(sec):
                    return 1
                return 0 if self.cn.get(sec.upper(), "") else 2

            def rank(row):
                sec, kind, name = row
                cn = self.cn.get(sec.upper(), "")
                pri = _UNIT_PRI.get(kind, 9)
                g = _grp(sec)
                if sec.lower() == q:
                    return (-1, 0, 0, "")
                for s in (cn, name):
                    s = s.lower()
                    if s.startswith(q):
                        return (0, g, pri, s)
                for s in (cn, name):
                    if q in s.lower():
                        return (1, g, pri, s.lower())
                if sec.lower().startswith(q):
                    return (2, g, pri, sec.lower())
                return (3, g, pri, (name or sec).lower())
            self._rows.sort(key=rank)
        else:
            # 没搜索时：先按阵营（盟军→苏军→厄普西隆→焚风→中立&其他），
            # 再按 建筑→步兵→车辆→空军→其他；
            # 同类里有中文名的排前面（按中文名），没中文名的排后面（按英文名）
            def key0(r):
                sec, kind, name = r
                cn = self.cn.get(sec.upper(), "")
                if self._is_gray(sec):
                    grp = 1           # 灰显的夹在中间
                elif cn:
                    grp = 0           # 有中文名的正常项
                else:
                    grp = 2           # 没中文名的正常项（英文）
                return (self._fac_rank(sec),
                        _UNIT_PRI.get(kind, 9), grp,
                        (cn or (name or sec)).lower())
            self._rows.sort(key=key0)
        for i, (sec, kind, name) in enumerate(self._rows):
            self.lst.insert("end", "  %s  [%s]" % (self._disp(sec, name), sec))
            if self._is_gray(sec):
                self.lst.itemconfig(i, foreground=C_GRAY)
            if i >= 5000:
                break
        self.lbl_count.configure(text="%d 个结果" % len(self._rows))
        self.lst.yview_moveto(0)
        if self._rows:
            self.lst.selection_clear(0, "end")
            self.lst.selection_set(0)
            self.lst.activate(0)
            self._on_select()

    def _sel_index(self, idx):
        if 0 <= idx < self.lst.size():
            self.lst.selection_clear(0, "end")
            self.lst.selection_set(idx)
            self.lst.activate(idx)
            self._on_select()

    def _on_select(self, _ev=None):
        sel = self.lst.curselection()
        if not sel:
            return
        i = sel[0]
        if i >= len(getattr(self, "_rows", [])):
            return
        self.current = self._rows[i]
        self._update_title_state()
        self._fill_fields()
        self.inner.update_idletasks()
        # 用 reqheight 立刻把滚动区设成新内容的真实高度，再回到顶部，
        # 否则 canvas 会沿用上一页的 yview（上一页内容不足一屏时会贴到底部）。
        self.canvas.configure(
            scrollregion=(0, 0, max(1, self.inner.winfo_reqwidth()),
                          max(1, self.inner.winfo_reqheight())))
        self._schedule_top()

    # ---------- 字段 ----------
    def _slots_for(self, sec):
        """该单位的武器槽位列表：常规四槽 + 加特林单位的多段武器。"""
        slots = list(WEAPON_SLOTS)
        if self._first_val(sec, "IsGattling").strip().lower() in ("yes", "true"):
            try:
                cnt = int(self._first_val(sec, "WeaponCount").strip() or 6)
            except ValueError:
                cnt = 6
            cnt = max(1, min(cnt, 12))
            # Weapon1 通常就是 Primary，从第 2 段开始补，避免同一把枪显示两遍
            for i in range(2, cnt + 1):
                slots.append("Weapon%d" % i)
                slots.append("EliteWeapon%d" % i)
        return slots

    def _gattling_stage(self, sec, slot):
        """加特林单位第 N 段武器在第几“击破数”后出现；常规槽位返回空串。"""
        m = re.match(r"^(Elite)?Weapon(\d+)$", slot or "")
        if not m:
            return ""
        n = int(m.group(2))
        if n < 2:
            return ""
        key = ("EliteStage%d" if m.group(1) else "Stage%d") % (n - 1)
        return self._first_val(sec, key).strip()

    def _weapons_of(self, sec):
        """返回 [([槽位…], 武器节ID, [(键,值)...]), ...]
        同一个武器节被多个槽位引用时（主武器 == 精英主武器）合并成一段。"""
        out = []
        seen = {}
        for slot in self._slots_for(sec):
            wid = self._first_val(sec, slot).strip()
            if not wid:
                continue
            ws = self.sec_by_up.get(wid.upper())
            if not ws or ws.upper() == sec.upper():
                continue
            hit = seen.get(ws.upper())
            if hit is not None:
                hit.append(slot)
                continue
            kv = [(k, v) for k, v in self.sections.get(ws, []) if k in WEAPON_FIELDS]
            if kv:
                slots = [slot]
                seen[ws.upper()] = slots
                out.append((slots, ws, kv))
        return out

    def _users_text(self, weapon_sec, me=None):
        us = [u for u in self.wpn_users.get(weapon_sec.upper(), []) if u != me]
        if not us:
            return ""
        names = []
        for u in us[:6]:
            nm = self._first_val(u, "Name")
            names.append(self._disp(u, nm))
        more = "" if len(us) <= 6 else " 等 %d 个" % len(us)
        return "另有 %d 个单位使用同种武器：%s%s" % (len(us), "、".join(names), more)

    def _fill_fields(self):
        self._close_ref_popup()
        for w in self.inner.winfo_children():
            w.destroy()
        self.entries = {}
        self._vars = []
        self._field_map = {}
        if not self.current:
            return
        sec = self.current[0]
        items = self.sections.get(sec, [])
        if self.var_common.get():
            shown = [(k, v) for k, v in items if k in COMMON_KEYS]
            order = {k: i for i, k in enumerate(COMMON_KEYS)}
            shown.sort(key=lambda kv: order.get(kv[0], 999))
            if not shown:
                shown = [(k, v) for k, v in items if self._is_number(v)][:14]
        else:
            shown = items

        # 手动新增的键（原版这一节里没有）也要显示出来，否则加完看不见
        have = {k.lower() for k, _v in shown}
        for k, v in self.edits.get(sec, {}).items():
            if k.lower() not in have:
                shown.append((k, ""))

        if sec.upper() in getattr(self, "sw_set", set()):
            sw_keys = {k.lower() for k, _c in SW_FIELDS}
            shown = [(k, v) for k, v in shown if k.lower() not in sw_keys]
            # 空投数量在下面的「空投 / 传送内容」段里单独出，避免重复两行
            if any(k.upper() == "PARADROP.COUNT" for k, _v in items):
                shown = [(k, v) for k, v in shown if k.upper() != "PARADROP.COUNT"]

        weapons = self._weapons_of(sec)

        r = 0
        # ---- 支援技能：先它（冷却/花费/距离/伤害 + 谁提供它），再看通用字段 ----
        r = self._render_superweapon(r, sec)
        if shown:
            ttk.Label(self.inner, text="字段", style="Small.TLabel").grid(
                row=r, column=0, sticky="w", padx=(2, 10), pady=(0, 4))
            ttk.Label(self.inner, text="数值（直接改，回车生效）", style="Small.TLabel").grid(
                row=r, column=2, sticky="w", pady=(0, 4))
            r += 1
            edits = self.edits.get(sec, {})
            for k, v in shown:
                r = self._row_field(r, sec, k, v, edits.get(k, v), k in edits)
        elif not weapons and not (sec.upper() in getattr(self, "sw_set", set())):
            ttk.Label(self.inner, text="该节没有数值字段。").grid(
                row=r, column=0, sticky="w")
            return

        # ---- 该单位的武器（直接在这里改，改的是武器节本身）----
        r = self._render_weapons(r, sec, me=sec)
        # ---- 派生单位：Spawns= 指向的导弹/子单位（飞毛腿、无畏导弹、航母大黄蜂…）----
        r = self._render_spawns(r, sec)
        # ---- 部署/展开形态：基地车 ↔ 建造场、机动声波侦测仪 ↔ 建筑形态… ----
        r = self._render_deploy(r, sec)
        # ---- 支援技能：空投/传送出来的单位 ----
        r = self._render_drops(r, sec)
        # ---- 弹头：Verses 拆成逐种装甲的百分比 ----
        r = self._render_verses(r, sec)
        # ---- 建筑：它挂载了哪些支援技能（可改/可换）----
        r = self._render_sw_hooks(r, sec)

        # 让整块面板从顶部开始显示（否则换单选时可能停在上一次的滚动位置）
        self.inner.update_idletasks()
        try:
            self.canvas.configure(scrollregion=(0, 0, max(1, self.inner.winfo_reqwidth()),
                                                max(1, self.inner.winfo_reqheight())))
        except Exception:
            pass
        self._schedule_top()

    def _schedule_top(self):
        """选中新条目后把面板拉回顶部；用户自己滚动时会被取消。"""
        self._cancel_top_jobs()
        for _ms in (0, 60, 200, 450, 900, 1600):
            try:
                self._top_jobs.append(self.after(_ms, self._to_top))
            except Exception:
                pass

    def _cancel_top_jobs(self):
        for j in getattr(self, "_top_jobs", []):
            try:
                self.after_cancel(j)
            except Exception:
                pass
        self._top_jobs = []

    def _to_top(self):
        try:
            self.canvas.yview_moveto(0)
        except Exception:
            pass
        if getattr(self, "_dbg_scroll", False):
            try:
                with open(os.path.join(DATA_DIR, "dbg.txt"), "a", encoding="utf-8") as f:
                    f.write("to_top yview=%r focus=%r\n" % (
                        self.canvas.yview(), self.focus_get()))
            except Exception:
                pass

    def _render_verses(self, r, sec):
        """弹头节：把 Verses=100%,90%,… 拆成 11 行单独改。"""
        raw = self._first_val(sec, "Verses").strip()
        if not raw:
            return r
        parts = [p.strip() for p in raw.split(",")]
        if "%" not in raw:
            parts = [p + "%" for p in parts]
        parts = (parts + ["100%"] * len(ARMOR_ORDER))[:len(ARMOR_ORDER)]
        cur = self.edits.get(sec, {}).get("Verses")
        if cur:
            parts = ([p.strip() for p in cur.split(",")] + ["100%"] * len(ARMOR_ORDER))[:len(ARMOR_ORDER)]

        r += 1
        head = tk.Frame(self.inner, bg=C_PANEL)
        head.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(8, 2))
        ttk.Label(head, text="── 伤害百分比（Verses：对各类装甲的伤害系数，填百分数，100 = 全额伤害）",
                  style="Small.TLabel").pack(side="left")
        r += 1
        vs = {}
        for i, (key, cn) in enumerate(zip(ARMOR_ORDER, ARMOR_CN)):
            ttk.Label(self.inner, text="    %s  %s" % (cn, key)).grid(
                row=r, column=0, sticky="w", padx=(2, 10), pady=1)
            v = tk.StringVar(value=parts[i].rstrip("%"))
            self._vars.append(v)
            ico, ent = self._entry_cell(r, v)
            self._watch_warn(ico, sec, "Verses", v, parts[i].rstrip("%"))
            ent.bind("<KeyRelease>", lambda e, i=i: self._commit_verses(sec))
            ent.bind("<FocusOut>", lambda e, i=i: self._commit_verses(sec))
            vs[i] = (v, ent)
            r += 1
        self._verses = (sec, vs)
        return r

    def _commit_verses(self, sec):
        if not getattr(self, "_verses", None) or self._verses[0] != sec:
            return
        _s, vs = self._verses
        vals = []
        for i in range(len(ARMOR_ORDER)):
            v = vs[i][0].get().strip().rstrip("%") or "100"
            vals.append(v + "%")
        new = ",".join(vals)
        orig = self._first_val(sec, "Verses").strip()
        d = self.edits.setdefault(sec, {})
        if new == orig:
            d.pop("Verses", None)
            if not d:
                self.edits.pop(sec, None)
        else:
            d["Verses"] = new
        self._update_status_quick()

    def _spawns_of(self, sec):
        raw = self._first_val(sec, "Spawns").strip()
        if not raw or raw.lower() in ("no", "yes", "none"):
            return []
        out = []
        for part in raw.split(","):
            ws = self.sec_by_up.get(part.strip().upper())
            if ws and ws.upper() != sec.upper():
                out.append(ws)
        return out

    def _render_superweapon(self, r, sec):
        """支援技能节：冷却/花费/距离/伤害 + 谁提供它。"""
        if sec.upper() not in getattr(self, "sw_set", set()):
            return r
        editors = self.sw_owners.get(sec.upper(), [])
        r += 1
        head = tk.Frame(self.inner, bg=C_PANEL)
        head.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(8, 2))
        ttype = self._first_val(sec, "Type").strip() or "?"
        taction = self._first_val(sec, "Action").strip() or "?"
        ttk.Label(head, text="── 支援技能 · 行为 %s / %s" % (ttype, taction),
                  style="Small.TLabel").pack(side="left")
        r += 1

        # 提供这个技能的建筑（B 档：这一层在建筑面板里可改）
        if editors:
            row = tk.Frame(self.inner, bg=C_PANEL)
            row.grid(row=r, column=0, columnspan=4, sticky="ew", pady=1)
            ttk.Label(row, text="    由 %d 个建筑提供：" % len(editors),
                      style="Small.TLabel").pack(side="left")
            seen = set()
            for bsec, _k in editors:
                if bsec.upper() in seen:
                    continue
                seen.add(bsec.upper())
                nm = self._disp(bsec, self._first_val(bsec, "Name") or bsec)
                self._link(row, "%s [%s]" % (nm, bsec),
                           lambda s=bsec: self._goto(s)).pack(side="left", padx=(0, 8))
            r += 1
        else:
            row = tk.Frame(self.inner, bg=C_PANEL)
            row.grid(row=r, column=0, columnspan=4, sticky="ew", pady=1)
            ttk.Label(row, text="    （没有建筑挂载它：内部辅助技能，或由其它技能触发）",
                      style="Small.TLabel").pack(side="left")
            r += 1

        # 技能自己的参数（不依赖“常用数值”开关，固定顺序）
        eds = self.edits.get(sec, {})
        for key, _cn in SW_FIELDS:
            v = self._first_val(sec, key).strip()
            if not v and key not in eds:
                continue
            r = self._row_field(r, sec, key, v, eds.get(key, v), key in eds, indent=True)
        wh = eds.get("SW.Warhead", self._first_val(sec, "SW.Warhead")).strip()
        wsec = self.sec_by_up.get(wh.upper()) if wh else None
        if wsec:
            row = tk.Frame(self.inner, bg=C_PANEL)
            row.grid(row=r, column=0, columnspan=4, sticky="ew", pady=1)
            ttk.Label(row, text="    弹头效果（伤害百分比）", style="Small.TLabel").pack(side="left")
            self._link(row, "打开这个弹头", lambda s=wsec: self._goto(s)).pack(
                side="left", padx=(6, 2))
            r += 1
        return r

    def _render_drops(self, r, sec):
        """支援技能：它会送出来 / 传过来的单位（PARADROP.*.TYPES / DELIVER.TYPES / DROPPOD.TYPES）。"""
        items = self.sections.get(sec, [])
        drops = [(k, v) for k, v in items if DROP_KEY_RE.match(k)]
        has_count = any(k.upper() == "PARADROP.COUNT" for k, _v in items)
        if not drops and not has_count:
            return r
        names = []
        for _k, v in drops:
            for sid in [x.strip() for x in str(v).split(",") if x.strip()]:
                real = self.sec_by_up.get(sid.upper())
                if real:
                    names.append(real)
        if not names and not has_count:
            return r
        r += 1
        head = tk.Frame(self.inner, bg=C_PANEL)
        head.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(8, 2))
        ttk.Label(head, text="── 空投 / 传送内容（这个技能会送出下面这些单位）",
                  style="Small.TLabel").pack(side="left")
        r += 1
        if has_count:
            _orig = self._first_val(sec, "PARADROP.COUNT")
            _ed = self.edits.get(sec, {})
            r = self._row_field(r, sec, "PARADROP.COUNT", _orig,
                                _ed.get("PARADROP.COUNT", _orig),
                                "PARADROP.COUNT" in _ed)
        if not drops:
            r += 1
            hint = tk.Frame(self.inner, bg=C_PANEL)
            hint.grid(row=r, column=0, columnspan=4, sticky="w", pady=(0, 2))
            ttk.Label(hint, text="    具体兵种见 [General] 的 AmerParaDropInf / AllyParaDropInf / "
                                 "SovParaDropInf / YuriParaDropInf　",
                      style="Small.TLabel").pack(side="left")
            g = self.sec_by_up.get("GENERAL")
            if g:
                self._link(hint, "打开 General", lambda s=g: self._goto(s)).pack(side="left")
            r += 1
        for key, val in drops:
            r += 1
            row = tk.Frame(self.inner, bg=C_PANEL)
            row.grid(row=r, column=0, columnspan=4, sticky="ew", pady=1)
            label = DROP_KEY_CN.get(key.split(".")[0].upper(), key)
            if key.count(".") >= 2:
                label += "（%s）" % key.split(".")[1].capitalize()
            ttk.Label(row, text="    " + label, style="Small.TLabel",
                      width=20, anchor="w").pack(side="left")
            cur = self.edits.get(sec, {}).get(key, val)
            var = tk.StringVar(value=cur)
            self._vars.append(var)
            ent = ttk.Entry(row, textvariable=var, width=24)
            ent.pack(side="left", padx=(6, 6))
            self.entries[(sec, key)] = (var, val)
            self._bind_field(ent, sec, key)
            units = [x.strip() for x in str(cur).split(",") if x.strip()]
            shown = 0
            for sid in units:
                real = self.sec_by_up.get(sid.upper())
                if not real:
                    continue
                if shown >= 4:
                    ttk.Label(row, text="…等 %d 个" % (len(units) - shown),
                              style="Small.TLabel").pack(side="left", padx=(4, 0))
                    break
                self._link(row, self._disp(real, self._first_val(real, "Name")),
                           lambda s=real: self._goto(s)).pack(side="left", padx=(4, 0))
                shown += 1
        return r

    def _render_sw_hooks(self, r, sec):
        """建筑节：它挂载的支援技能（SuperWeapon / SuperWeapon2 / SuperWeapons），可改可换。"""
        hooks = getattr(self, "building_sw", {}).get(sec, [])
        if not hooks:
            return r
        r += 1
        head = tk.Frame(self.inner, bg=C_PANEL)
        head.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(8, 2))
        ttk.Label(head, text="── 提供的支援技能（填技能 ID，多个用逗号）",
                  style="Small.TLabel").pack(side="left")
        for key, val in hooks:
            r += 1
            row = tk.Frame(self.inner, bg=C_PANEL)
            row.grid(row=r, column=0, columnspan=4, sticky="ew", pady=1)
            ttk.Label(row, text="    " + key, style="Small.TLabel").pack(side="left")
            cur = self.edits.get(sec, {}).get(key, val)
            var = tk.StringVar(value=cur)
            self._vars.append(var)
            ent = ttk.Entry(row, textvariable=var, width=34)
            ent.pack(side="left", padx=(6, 6))
            self.entries[(sec, key)] = (var, val)
            self._bind_field(ent, sec, key)
            # 换成别的技能：弹窗挑
            self._link(row, "换成…", lambda s=sec, k=key: self._pick_sw(s, k)).pack(
                side="left", padx=(0, 8))
            for sid in [x.strip() for x in str(cur).split(",") if x.strip()]:
                ws = self.sec_by_up.get(sid.upper())
                if ws and ws.upper() in getattr(self, "sw_set", set()):
                    self._link(row, "打开", lambda s=ws: self._goto(s)).pack(side="left", padx=(0, 4))
        return r

    def _render_weapons(self, r, sec, me=None, depth=0):
        for slots, ws, kv in self._weapons_of(sec):
            r += 1
            head = tk.Frame(self.inner, bg=C_PANEL)
            head.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(8, 2))
            parts = []
            gm = [re.match(r"^(Elite)?Weapon(\d+)$", s or "") for s in slots]
            nums = [int(x.group(2)) for x in gm if x]
            if len(nums) == len(slots) > 1 and max(nums) - min(nums) + 1 == len(nums):
                # 连续的多段加特林武器合成一句：加特林第2–4段（210/280 击破后）
                elite = bool(gm[0].group(1))
                t = ("精英加特林" if elite else "加特林") + "第%d–%d段" % (min(nums), max(nums))
                sts = [self._gattling_stage(sec, s) for s in slots]
                sts = [x for x in sts if x]
                if sts:
                    t += "（%s 击破后）" % "/".join(sts)
                parts.append(t)
            else:
                for s in slots:
                    t = slot_cn(s)
                    st = self._gattling_stage(sec, s)
                    if st:
                        t += "（%s 击破后）" % st
                    parts.append(t)
            slot_txt = " / ".join(parts)
            ttk.Label(head, text="── 武器 · %s：%s" % (slot_txt, ws),
                      style="Small.TLabel").pack(side="left")
            self._link(head, "单独打开", lambda s=ws: self._goto(s)).pack(side="left", padx=(6, 2))
            whv = self._first_val(ws, "Warhead").strip()
            wsec = self.sec_by_up.get(whv.upper()) if whv else None
            if wsec:
                self._link(head, "弹头 %s" % whv, lambda s=wsec: self._goto(s)).pack(
                    side="left", padx=(0, 8))
            r += 1
            we = self.edits.get(ws, {})
            order = {k: i for i, k in enumerate(WEAPON_FIELDS)}
            for k, v in sorted(kv, key=lambda kv_: order.get(kv_[0], 99)):
                r = self._row_field(r, ws, k, v, we.get(k, v), k in we, indent=True)
        return r

    def _render_spawns(self, r, sec):
        for sp in self._spawns_of(sec):
            num = self._first_val(sec, "SpawnsNumber").strip()
            r += 1
            head = tk.Frame(self.inner, bg=C_PANEL)
            head.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(10, 2))
            ttk.Label(head,
                      text="── 派生 · 发射/生成：%s  [%s]%s" % (
                          self._disp(sp, self._first_val(sp, "Name")), sp,
                          ("   ×%s" % num) if num else ""),
                      style="Small.TLabel").pack(side="left")
            self._link(head, "单独打开", lambda s=sp: self._goto(s)).pack(side="left", padx=(6, 2))
            r += 1
            ed = self.edits.get(sp, {})
            for k in ("Cost", "Strength", "Armor", "Speed", "Sight", "Points"):
                v = self._first_val(sp, k)
                if v:
                    r = self._row_field(r, sp, k, v, ed.get(k, v), k in ed, indent=True)
            # Ares/Phobos 的“子导弹”数值：Missile.Damage / Missile.Warhead …
            for k in MISSILE_KEYS:
                v = self._first_val(sp, k)
                if v or k in ed:
                    r = self._row_field(r, sp, k, v, ed.get(k, v), k in ed, indent=True)
            # 没有 Missile.Damage 的导弹：伤害由引擎按 [General] 指定的弹头结算
            if not self._first_val(sp, "Missile.Warhead") and sp.upper() in SPAWN_WARHEAD:
                gen = SPAWN_WARHEAD[sp.upper()][0]
                wh = (self._first_val("CombatDamage", gen).strip()
                      or self._first_val("General", gen).strip())
                wsec = self.sec_by_up.get(wh.upper()) if wh else None
                if wsec:
                    row = tk.Frame(self.inner, bg=C_PANEL)
                    row.grid(row=r, column=0, columnspan=4, sticky="ew", pady=1)
                    ttk.Label(row, text="    伤害弹头（引擎指定 %s）：%s" % (gen, wh),
                              style="Small.TLabel").pack(side="left")
                    self._link(row, "打开这个弹头", lambda s=wsec: self._goto(s)).pack(
                        side="left", padx=(6, 2))
                    r += 1
            r = self._render_weapons(r, sp, me=sec, depth=1)
        return r

    def _render_deploy(self, r, sec):
        """部署/展开形态：车 → 建筑（DeploysInto）、建筑 → 车（UndeploysInto）。"""
        pairs = []
        for key, rev in (("DeploysInto", False), ("UndeploysInto", True)):
            val = self._first_val(sec, key).strip()
            if val and val.lower() not in ("none", "no"):
                pairs.append((key, val, rev))
        for key, val, rev in pairs:
            other = self.sec_by_up.get(val.upper())
            head = tk.Frame(self.inner, bg=C_PANEL)
            head.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(10, 2))
            ttk.Label(head, text="── 部署形态 · %s：%s  [%s]" % (
                "展开成建筑" if not rev else "展开回车辆",
                self._disp(other, self._first_val(other, "Name")) if other else val,
                other or val), style="Small.TLabel").pack(side="left")
            if other:
                self._link(head, "打开", lambda s=other: self._goto(s)).pack(side="left", padx=(6, 2))
            r += 1
            # 形态关联键本身可改（改了就等于换成另一个建筑/车辆）
            r = self._row_field(r, sec, key, val, self.edits.get(sec, {}).get(key, val),
                                key in self.edits.get(sec, {}), indent=True)
            if other and other.upper() != sec.upper():
                ed = self.edits.get(other, {})
                for k in ("Cost", "Strength", "Armor", "Power", "Sight"):
                    v = self._first_val(other, k)
                    if v:
                        r = self._row_field(r, other, k, v, ed.get(k, v), k in ed, indent=True)
        return r

    # ---------- 中文搜索：数值框里打中文 = 搜节 ID ----------
    _CJK_RE = re.compile(r"[\u4e00-\u9fff]")

    def _close_ref_popup(self, revert=True):
        win = getattr(self, "_ref_popup", None)
        self._ref_popup = None
        if revert:
            self._revert_ref_entry()
        if win is not None:
            try:
                win.grab_release()
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass

    def _revert_ref_entry(self):
        """把“正在检索”的输入框恢复原值（中文只是查询串，不能留在框里）。"""
        ent = getattr(self, "_ref_entry", None)
        self._ref_entry = None
        if ent is None:
            return
        info = self._field_map.get(str(ent))
        if not info:
            return
        item = self.entries.get(info)
        if not item:
            return
        var, orig = item
        try:
            if self._CJK_RE.search(ent.get()):
                var.set(orig)
        except Exception:
            pass

    def _popup_alive(self):
        return getattr(self, "_ref_popup", None) is not None

    def _ref_allowed(self, key):
        """按字段类型限定候选：支援技能槽只给技能，单位列表只给单位，弹头只给弹头。"""
        k = (key or "").upper()
        if k.startswith("SUPERWEAPON"):
            return set(x.upper() for x in getattr(self, "sw_set", set()))
        if k.endswith(".TYPES") or k.endswith("TYPES"):
            kinds = ("建筑", "步兵", "车辆", "空军")
            return set(sec.upper() for sec, kind, _nm in getattr(self, "index", [])
                       if kind in kinds)
        if "WARHEAD" in k:
            if getattr(self, "_wh_set", None) is None:
                wh = set()
                for sec in getattr(self, "order", []):
                    for kk, _v in self.sections.get(sec, []):
                        if kk.upper() == "VERSES":
                            wh.add(sec.upper())
                            break
                self._wh_set = wh
            return self._wh_set
        return None

    def _ref_candidates(self, q, limit=80, allowed=None):
        """只在已汉化的注册名里找：把中文名里的「前缀：核心名」按核心名比对。

        规则极简：q 是连起来的一段中文，中文名里包含它就算命中，
        越短越靠前（更容易一眼看到想要的）。"""
        q = q.strip()
        if not q:
            return []
        rows = []
        for s in getattr(self, "order", []):
            if allowed is not None and s.upper() not in allowed:
                continue
            cn = self.cn.get(s.upper(), "")
            if not cn or q not in cn:
                continue
            core = cn
            for sep in ("：", ":"):
                if sep in core:
                    core = core.split(sep)[-1]
            core = core.strip()
            rank = 0 if core == q else (1 if core.startswith(q) else 2)
            rows.append((rank, len(cn), cn, s))
        rows.sort(key=lambda t: (t[0], t[1], t[2]))
        return [("%s  [%s]" % (t[2], t[3]), t[3]) for t in rows[:limit]]

    def _pointer_in_popup(self):
        pop = getattr(self, "_ref_popup", None)
        if pop is None:
            return False
        try:
            px, py = self.winfo_pointerxy()
            x0 = pop.winfo_rootx()
            y0 = pop.winfo_rooty()
            return (x0 <= px <= x0 + pop.winfo_width() and
                    y0 <= py <= y0 + pop.winfo_height())
        except Exception:
            return False

    def _ref_poll(self):
        """轮询当前输入框：中文输入法下 KeyRelease 不一定触发，这里兜底。"""
        try:
            w = self.focus_get()
        except Exception:
            w = None
        try:
            key = str(w) if w is not None else ""
            if key and key in self._field_map:
                txt = w.get()
                if self._ref_seen.get(key) != txt:
                    self._ref_seen[key] = txt
                    if self._cjk_run(txt):
                        self._ref_search(w, *self._field_map[key])
                    else:
                        self._ref_last_q = None
                        self._close_ref_popup()
            elif self._ref_popup is not None:
                inside = False
                if w is not None:
                    try:
                        inside = self._is_descendant(w, self._ref_popup)
                    except Exception:
                        inside = False
                if not inside:
                    inside = self._pointer_in_popup()
                if not inside:
                    self._close_ref_popup()
        except Exception:
            pass
        self.after(280, self._ref_poll)

    _CJK_RUN_RE = re.compile(r"[一-鿿]+")

    @classmethod
    def _cjk_run(cls, txt):
        """取出最后一个连续中文段；没有中文就返回空串。"""
        runs = cls._CJK_RUN_RE.findall(txt or "")
        return runs[-1] if runs else ""

    def _ref_search(self, ent, sec, key):
        """数值框里出现连续中文时，只在已汉化的注册名里找（点一下填注册名）。"""
        q = self._cjk_run(ent.get())
        if not q:
            self._close_ref_popup()
            return
        if q == getattr(self, "_ref_last_q", None) and self._ref_popup is not None:
            return
        self._ref_last_q = q
        self._ref_entry = ent
        allowed = self._ref_allowed(key)
        cands = self._ref_candidates(q, allowed=allowed)
        self._close_ref_popup(revert=False)
        if not cands:
            if allowed is not None:
                self._msg("这一格只接受特定类型（支援技能 / 单位 / 弹头），其中多数没有中文名——直接填 ID 更稳：%s" % q, warn=True)
            else:
                self._msg("未搜索到相应注册名：%s（换个说法，或直接填注册名如 RHINAPE）" % q, warn=True)
            return
        win = tk.Toplevel(self)
        self._ref_popup = win
        win.overrideredirect(True)
        win.configure(bg=self.theme["accent"])
        inner = tk.Frame(win, bg=C_PANEL2)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        lb = tk.Listbox(inner, bg=C_PANEL2, fg=C_TEXT, selectbackground=self.theme["sel"],
                        selectforeground="#ffffff", relief="flat", highlightthickness=0,
                        font=("Microsoft YaHei UI", 10), activestyle="none",
                        width=40, height=min(10, max(3, len(cands))))
        lb.pack(side="left", fill="both", expand=True)
        for _label, _sid in cands:
            lb.insert("end", _label)
        lb.selection_set(0)

        def take(_e=None):
            idx = 0
            if _e is not None and hasattr(_e, "y"):
                try:
                    idx = lb.nearest(_e.y)
                except Exception:
                    idx = 0
            else:
                sel = lb.curselection()
                idx = sel[0] if sel else 0
            if not (0 <= idx < len(cands)):
                return
            sid = cands[idx][1]
            self._ref_entry = None
            self._close_ref_popup(revert=False)
            newval = sid
            ku = (key or "").upper()
            cur = ent.get()
            q = self._cjk_run(cur)
            is_list = (ku.endswith("TYPES") or ku in ("SUPERWEAPONS", "SW.INHIBITORS",
                                                      "SW.AUXBUILDINGS", "VERSES")
                       or "," in cur)
            if is_list and cur.strip():
                # 列表型字段：保留前面已有的条目，只把中文查询串换成新 ID 追加进去
                base = cur.replace(q, "") if q else cur
                parts = [x.strip() for x in base.split(",") if x.strip()]
                if sid.upper() not in [x.upper() for x in parts]:
                    parts.append(sid)
                newval = ",".join(parts)
            ent.delete(0, "end")
            ent.insert(0, newval)
            self._commit(sec, key, ent)

        lb.bind("<ButtonPress-1>", take)
        lb.bind("<ButtonRelease-1>", take)
        lb.bind("<Return>", take)
        lb.bind("<Escape>", lambda e: self._close_ref_popup())

        try:
            rows = int(lb.cget("height"))
            pop_h = rows * 20 + 8
            pop_w = 360
            x = ent.winfo_rootx()
            y = ent.winfo_rooty() + ent.winfo_height()
            # 保证整块候选列表落在右侧面板的可视范围内（输入框可能被滚动到屏幕外）
            try:
                top = self.canvas.winfo_rooty() + 6
                bottom = self.canvas.winfo_rooty() + self.canvas.winfo_height() - 6
            except Exception:
                top, bottom = 0, self.winfo_screenheight() - 40
            if y + pop_h > bottom:
                y = bottom - pop_h
            if y < top:
                y = top
            sw = self.winfo_screenwidth()
            if x + pop_w > sw - 10:
                x = max(0, sw - pop_w - 10)
            y = max(0, y)
            win.geometry("+%d+%d" % (x, y))
        except Exception:
            pass

    def _bind_field(self, ent, sec, key):
        """数值框通用绑定：回车/失焦提交、按键与轮询双通道中文检索。"""
        ent.bind("<Return>", lambda e, s=sec, k=key, w=ent: self._commit(s, k, w))
        ent.bind("<FocusOut>", lambda e, s=sec, k=key, w=ent: self._commit(s, k, w))
        ent.bind("<KeyRelease>", lambda e, s=sec, k=key, w=ent: self._ref_search(w, s, k))
        ent.bind("<Escape>", lambda e: self._close_ref_popup())
        self._field_map[str(ent)] = (sec, key)
        return ent

    # ---------- 输入框：黄色警告（非数字 / 步兵移速过大）----------
    def _entry_cell(self, r, var):
        """一行输入框：第 1 列是警告图标位，第 2 列才是输入框。"""
        ico = tk.Label(self.inner, text="", width=2, anchor="center",
                       bg=C_PANEL, fg=C_WARN_ICON,
                       font=("Microsoft YaHei UI", 10))
        ico.grid(row=r, column=1, sticky="e", padx=(0, 2), pady=1)
        ent = ttk.Entry(self.inner, textvariable=var)
        ent.grid(row=r, column=2, sticky="ew", pady=1)
        return ico, ent

    def _kind_of_sec(self, sec):
        if not hasattr(self, "_kind_map") or len(getattr(self, "_kind_map", {})) == 0:
            self._kind_map = {s: k for s, k, _n in getattr(self, "index", [])}
        return self._kind_map.get(sec, "")

    def _num_problem(self, sec, key, val, orig):
        """返回警告文字；没问题返回 None。"""
        v = (val or "").strip()
        if not v:
            return None
        o = (orig or "").strip()
        ku = key.upper()
        # ① 原本就是纯数字的格子：这次填的东西也必须能当数字用
        if o and NUM_RE.match(o) and not NUM_RE.match(v):
            return "这一格只能是数字，现在填的是「%s」" % v
        # ② 步兵移速：超过 %d 会在游戏里抽搐/瞬移
        if ku == "SPEED" and self._kind_of_sec(sec) == "步兵" and NUM_RE.match(v):
            try:
                if float(v) > INF_SPEED_MAX:
                    return "步兵移速 %s 超过 %d，游戏里可能出现抽搐或瞬移" % (
                        v.rstrip("0").rstrip(".") if "." in v else v, INF_SPEED_MAX)
            except ValueError:
                pass
        return None

    def _check_warn(self, ico, sec, key, val, orig):
        msg = self._num_problem(sec, key, val, orig)
        ico._tip = msg
        ico.configure(text="⚠" if msg else "")
        if not hasattr(ico, "_tip_bound"):
            ico._tip_bound = True
            ico.bind("<Enter>", lambda e, w=ico: self._tip_show(w))
            ico.bind("<Leave>", lambda e: self._tip_hide())

    def _watch_warn(self, ico, sec, key, var, orig):
        """输入变化时实时刷新警告（var 的 trace 能接住输入法上屏／粘贴）。"""
        def _upd(*_a):
            try:
                self._check_warn(ico, sec, key, var.get(), orig)
            except Exception:
                pass
        try:
            var.trace_add("write", _upd)
        except Exception:
            pass
        _upd()

    def _tip_show(self, widget):
        msg = getattr(widget, "_tip", None)
        if not msg:
            return
        self._tip_hide()
        try:
            x = widget.winfo_rootx() - 6
            y = widget.winfo_rooty() - 2
            tip = tk.Toplevel(self)
            tip.overrideredirect(True)
            tip.attributes("-topmost", True)
            frame = tk.Frame(tip, bg="#2b2136", highlightthickness=1,
                             highlightbackground=C_WARN_ICON)
            frame.pack()
            tk.Label(frame, text=msg, bg="#2b2136", fg="#ffe9b0",
                     font=("Microsoft YaHei UI", 9), justify="left",
                     wraplength=320).pack(padx=8, pady=5)
            tip.update_idletasks()
            sw, sh = tip.winfo_screenwidth(), tip.winfo_screenheight()
            # 默认放在图标的左上方，贴屏幕边就翻到下面／里面
            y = widget.winfo_rooty() - tip.winfo_height() - 6
            if y < 8:
                y = widget.winfo_rooty() + widget.winfo_height() + 6
            if x + tip.winfo_width() > sw - 8:
                x = max(0, sw - tip.winfo_width() - 8)
            if y + tip.winfo_height() > sh - 8:
                y = max(8, sh - tip.winfo_height() - 8)
            tip.geometry("+%d+%d" % (x, y))
            self._tip_win = tip
        except Exception:
            self._tip_win = None

    def _tip_hide(self):
        w = getattr(self, "_tip_win", None)
        if w is not None:
            try:
                w.destroy()
            except Exception:
                pass
        self._tip_win = None

    def _row_field(self, r, sec, k, orig, cur, changed, indent=False):
        ttk.Label(self.inner, text=("    " if indent else "") + self._field_label(k, sec)).grid(
            row=r, column=0, sticky="w", padx=(2, 10), pady=1)
        var = tk.StringVar(value=cur)
        # 同一个武器节可能同时出现在“主武器/精英主武器”两段里，
        # entries 的键会重复；这里额外攥住所有 StringVar，避免被 GC 掉导致输入框空白
        self._vars.append(var)
        ico, ent = self._entry_cell(r, var)
        # 提交时直接读控件里的文本（不读 var），避免同键多行时写错变量
        self._bind_field(ent, sec, k)
        ent.bind("<KeyRelease>", lambda e, s=sec, key=k: self._mark(s, key), add="+")
        self.entries[(sec, k)] = (var, orig)
        self._watch_warn(ico, sec, k, var, orig)
        if changed:
            ttk.Label(self.inner, text="● 已改", style="Warn.TLabel").grid(
                row=r, column=3, sticky="w", padx=4)
        return r + 1

    def _goto(self, sec):
        """跳到指定节（清空搜索和过滤后选中）。"""
        self.kind = "全部"
        self.fac = "全部"
        self.bind_all("<Control-z>", lambda e: (self.undo(), "break")[1])
        self.bind_all("<Control-Z>", lambda e: (self.undo(), "break")[1])
        self.bind_all("<Control-y>", lambda e: (self.redo(), "break")[1])
        self.bind_all("<Control-Y>", lambda e: (self.redo(), "break")[1])
        self._apply_theme("全部")
        self._paint_kind_buttons()
        self._paint_buttons(self._fac_buttons, self.fac)
        self.var_q.set(sec)
        self._refresh_list()
        for i, row in enumerate(self._rows):
            if row[0].upper() == sec.upper():
                self.lst.selection_clear(0, "end")
                self.lst.selection_set(i)
                self.lst.see(i)
                self._on_select()
                break

    def _field_label(self, k, sec=None):
        cn = FIELD_CN.get(k) or FIELD_CN_UP.get(k.upper())
        # 支援技能的 Range 是“效果能扔多远”，不是武器射程
        if sec and sec.upper() in getattr(self, "sw_set", ()) and k.upper() == "RANGE":
            cn = "效果范围"
        if not cn:
            return k
        # 带点的键（ParaDrop.Count / Missile.Damage…）中文名已经够清楚，不再缀英文
        if "." in k:
            return cn
        return cn if k.lower() in cn.lower() else "%s  %s" % (cn, k)

    def _is_number(self, v):
        try:
            float(v)
            return True
        except Exception:
            return False

    def _mark(self, sec, key):
        if self.current and self.current[0] == sec:
            self.dirty.add((sec, key))

    def _commit(self, sec, key, widget=None, value=None):
        pair = self.entries.get((sec, key))
        if not pair:
            return
        var, orig = pair
        if value is not None:
            val = str(value).strip()
        else:
            val = (widget.get() if widget is not None else var.get()).strip()
        val = fix_punct(val)
        if val == "":
            val = orig
        if self._CJK_RE.search(val):
            # 中文是搜索用的输入，不写进 ini；正在从候选里挑时先别动
            if self._popup_alive():
                return
            self._close_ref_popup()
            var.set(orig)
            return
        var.set(val)
        before = self.edits.get(sec, {}).get(key)
        if val != before:
            self._push_undo("%s 的 %s" % (self._disp(sec, self._first_val(sec, "Name")), key))
        if val != orig:
            self.edits.setdefault(sec, {})[key] = val
        else:
            d = self.edits.get(sec, {})
            d.pop(key, None)
            if not d:
                self.edits.pop(sec, None)
        self._update_status_quick()

    def reset_unit(self):
        if not self.current:
            return
        sec = self.current[0]
        if sec not in self.edits:
            self._msg("这个单位没有修改。")
            return
        self._push_undo("还原 %s" % self._disp(sec, self._first_val(sec, "Name")))
        self.edits.pop(sec, None)
        self.dirty = {d for d in self.dirty if d[0] != sec}
        self._fill_fields()
        self._update_status_quick()
        self._refresh_undo_links()

    def _save_snapshot(self):
        """记下“已经写进游戏目录”的那一份改动。"""
        self.saved_edits = {s: dict(d) for s, d in self.edits.items()}

    def _unsaved_count(self):
        n = 0
        for sec, d in self.edits.items():
            base = self.saved_edits.get(sec, {})
            for k, v in d.items():
                if base.get(k) != v:
                    n += 1
        return n

    def _update_status_quick(self):
        n = self._unsaved_count()
        if n:
            self._msg("已修改 %d 项（尚未保存）" % n, warn=True)
        # 没有未保存改动时不动左下角，留着“已保存…”那行提示

    def add_key(self, sec=None, preset=""):
        """给当前节手动加一个键（比如给 V3ROCKET 加 Missile.Damage）。"""
        if not self.current and not sec:
            self._msg("先选一个单位或武器。", warn=True)
            return
        sec = sec or self.current[0]
        win = tk.Toplevel(self)
        win.title("给 [%s] 新增数值" % sec)
        win.transient(self)
        win.resizable(False, False)
        tk.Label(win, text="键名（英文，如 Missile.Damage）").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        vk = tk.StringVar(value=preset)
        tk.Entry(win, textvariable=vk, width=32).grid(row=1, column=0, padx=8)
        tk.Label(win, text="数值").grid(row=2, column=0, sticky="w", padx=8, pady=(8, 2))
        vv = tk.StringVar()
        tk.Entry(win, textvariable=vv, width=32).grid(row=3, column=0, padx=8)

        def ok(event=None):
            k = vk.get().strip()
            v = vv.get().strip()
            if not k:
                return
            self.edits.setdefault(sec, {})[k] = v
            win.destroy()
            if self.current and self.current[0] == sec:
                self._fill_fields()
            self._update_status_quick()
            self._msg("[%s] 已新增 %s=%s（记得保存）" % (sec, k, v), warn=True)

        bf = tk.Frame(win, bg=C_PANEL)
        bf.grid(row=4, column=0, pady=8)
        tk.Button(bf, text="确定", width=8, command=ok).pack(side="left", padx=4)
        tk.Button(bf, text="取消", width=8, command=win.destroy).pack(side="left", padx=4)
        win.bind("<Return>", ok)
        vk.set(preset)
        (vv if preset else vk).focus_set()

    # ---------- 保存 ----------
    def save(self):
        if not self._update_path_state():
            messagebox.showwarning(
                "还没设置游戏目录",
                "请先点上面的「选择目录」，选中 Mental Omega 安装目录\n"
                "（里面有 gamemd.exe 的那个文件夹）。")
            return
        # 先把界面上没提交的改动收进来
        for (sec, key), (var, orig) in list(self.entries.items()):
            self._commit(sec, key)
        if not self.edits:
            self._msg("没有要保存的修改。", warn=True)
            return
        if not self.base_text:
            messagebox.showwarning(
                "还没读到原版数据",
                "原版 rulesmo.ini 还没提取成功，先点「重新提取」再保存，\n"
                "否则保存出来的文件是空的、游戏会打不开。")
            return
        loose = self._loose_path()
        n = sum(len(d) for d in self.edits.values())
        if os.path.isfile(loose):
            old = self._loose_text()
            if not self._is_ours(old):
                if not messagebox.askyesno(
                        "检测到已有 rulesmo.ini",
                        "游戏目录里已经有一个不是本工具生成的 rulesmo.ini：\n%s\n\n"
                        "继续保存会覆盖它（会先自动备份到工具目录）。继续吗？"
                        % loose):
                    return
            os.makedirs(BACKUP_DIR, exist_ok=True)
            bak = os.path.join(BACKUP_DIR, "rulesmo_%s.ini" % time.strftime("%Y%m%d_%H%M%S"))
            import shutil
            shutil.copyfile(loose, bak)

        # 就地改写：原版全文照抄，只替换/插入改过的键
        text = patch_ini_text(self.base_text, self.edits)
        txt_lines = [SENTINEL, "; 本工具只改下面这几项，其余与原版完全一致："]
        for sec, d in self.edits.items():
            txt_lines.append("; [%s] %s" % (sec, " ".join("%s=%s" % (k, v) for k, v in d.items())))
        text = text.rstrip("\r\n") + "\r\n" + "\r\n".join(txt_lines) + "\r\n"
        try:
            with open(loose, "wb") as f:
                f.write(text.encode("latin1", "replace"))
        except PermissionError:
            self._log("save PermissionError %s" % loose)
            messagebox.showerror("写入失败", "没有写入权限：\n%s\n\n试试用管理员身份运行。" % loose)
            return
        except Exception as e:
            self._log("save error %r" % (e,))
            messagebox.showerror("写入失败", str(e))
            return
        self._log("save ok %d keys -> %s (%d bytes)"
                  % (n, loose, os.path.getsize(loose)))
        self._save_snapshot()
        self._refresh_state()
        self._msg("已保存：%d 项改动写入 %s（重启游戏生效）" % (n, RULE_FILE_NAME))
        messagebox.showinfo(
            "已保存",
            "已把 %d 项数值写入：\n%s\n\n"
            "· 只改动了这一份副本，游戏原本的 mix 文件没动\n"
            "· 重新启动游戏后生效\n"
            "· 联机 / 更新游戏前先点“全部还原”" % (n, loose))

    def restore_all(self):
        if not self._update_path_state():
            messagebox.showwarning(
                "还没设置游戏目录",
                "请先点上面的「选择目录」，选中 Mental Omega 安装目录。")
            return
        loose = self._loose_path()
        text = self._loose_text()
        if text is None:
            self.edits = {}
            self.dirty = set()
            self._fill_fields()
            self._refresh_state()
            self._msg("已经是原版状态，无需还原。")
            return
        if not self._is_ours(text):
            messagebox.showwarning(
                "这不是本工具生成的文件",
                "游戏目录里的 rulesmo.ini 不是本工具生成的，\n"
                "为了安全不会自动删除：\n\n%s\n\n请手动处理或先备份。" % loose)
            return
        if not messagebox.askyesno(
                "全部还原",
                "将删除：\n%s\n\n游戏会恢复原版数值。继续吗？" % loose):
            return
        try:
            os.remove(loose)
        except Exception as e:
            messagebox.showerror("删除失败", str(e))
            return
        self.edits = {}
        self.dirty = set()
        self._fill_fields()
        self._refresh_state()
        self._msg("已全部还原：覆盖文件已删除，游戏回到原版数值。")

    def choose_dir(self):
        p = filedialog.askdirectory(title="选择 Mental Omega 游戏目录", initialdir=self.game_dir)
        if not p:
            return
        self.game_dir = os.path.normpath(p)
        if not self._path_ok():
            self._update_path_state()
            messagebox.showwarning(
                "目录不对",
                "这个文件夹里既没有 gamemd.exe，也没有 .mix 文件：\n%s\n\n"
                "请选中 Mental Omega 的安装目录（就是里面能看见 gamemd.exe 的那个）。" % p)
            return
        self._save_game_dir()
        self.edits = {}
        self.current = None
        self._update_path_state()
        self._startup()

    def reextract(self):
        if not messagebox.askyesno(
                "重新提取",
                "将重新从游戏 .mix 中提取 rulesmo.ini 作为“原版数值”基准。\n"
                "（游戏更新后可以用这个）已保存的覆盖修改不受影响。继续吗？"):
            return
        try:
            if os.path.isfile(BASE_FILE):
                os.remove(BASE_FILE)
        except Exception:
            pass
        self._startup()
        self._msg("已重新提取 rulesmo.ini 基准。")

    def _on_close(self):
        self._save_geometry()
        self.destroy()


def main():
    args = sys.argv[1:]
    app = App()
    if "--dir" in args:
        p = args[args.index("--dir") + 1]
        if os.path.isdir(p):
            app.game_dir = os.path.normpath(p)
    if "--selftest" in args:
        messagebox.askyesno = lambda *a, **k: True
        messagebox.showinfo = lambda *a, **k: None
        messagebox.showwarning = lambda *a, **k: print("WARN:", a)
        messagebox.showerror = lambda *a, **k: print("ERR:", a)

        def run():
            ok = True
            sec = "MTNK"
            app.edits = {sec: {"Strength": "1234", "Cost": "1"}}
            app.save()
            p = app._loose_path()
            ok = ok and os.path.isfile(p)
            txt = open(p, "rb").read().decode("latin1")
            ok = ok and SENTINEL in txt and "\r\nStrength=1234" in txt and "\r\nCost=1" in txt
            ok = ok and txt.startswith(";;;;;;;;;;Mental Omega 3.3.6 RULES CONTROL FILE")
            # 除改动项外必须与原版逐字一致
            print("save ok:", ok, "size", len(txt), "base", len(app.base_text))
            print("unsaved after save:", app._unsaved_count(), " msg:", app.lbl_msg.cget("text"))
            app.edits = {}
            app._load_edits_from_loose()
            print("reload edits:", app.edits.get(sec))
            # 结构完整性：所有节都还在
            secs2, _ = parse_ini(txt)
            print("sections:", len(secs2), "E1 keys:", len(secs2.get("E1", [])),
                  "E1 Owner:", dict(secs2.get("E1", [])).get("Owner"))
            print("MTNK keys:", len(secs2.get("MTNK", [])))
            app.restore_all()
            print("restored (file gone):", not os.path.exists(p))
            app.destroy()

        app.after(800, run)
        app.mainloop()
        return
    if "--query" in args:
        q = args[args.index("--query") + 1]
        app.var_q.set(q)
        app.after(400, app._refresh_list)
    if "--profiles" in args:
        app.after(700, app.open_profiles)
    if "--about" in args:
        app.after(700, app.open_about)
    if "--donate" in args:
        app.after(700, app.open_donate)
    if "--dbg" in args:
        def _dump():
            lines = ["theme=%s fac=%r kind=%r" % (app.theme_key, app.fac, app.kind)]
            for k, b in app._fac_buttons.items():
                lines.append("fac %s sel=%s img=%s w=%d" % (
                    k, b._selected, bool(b.cget("image")), b.winfo_width()))
            for k, b in app._kind_buttons.items():
                lines.append("kind %s sel=%s img=%s w=%d" % (
                    k, b._selected, bool(b.cget("image")), b.winfo_width()))
            with open(os.path.join(DATA_DIR, "dbg.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
                f.write("\nfinal yview=%r focus=%r\n" % (
                    app.canvas.yview(), app.focus_get()))
        app._dbg_scroll = True
        app.after(8000, _dump)
    if "--fac" in args:
        f = args[args.index("--fac") + 1]
        app.after(500, lambda: app._set_fac(f))
    if "--go" in args:
        g = args[args.index("--go") + 1]
        app.after(1200, lambda: app._goto(g))
    if "--sel" in args:
        try:
            sel_idx = int(args[args.index("--sel") + 1])
        except (ValueError, IndexError):
            sel_idx = 0
        app.after(1800, lambda: app._sel_index(sel_idx))
    if "--scroll" in args:
        where = args[args.index("--scroll") + 1] if args[-1] != "--scroll" else "end"
        def _scroll():
            try:
                app.canvas.update_idletasks()
                app.canvas.yview_moveto(1.0 if where != "top" else 0.0)
            except Exception:
                pass
        app.after(2500, _scroll)
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        msg = traceback.format_exc()
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(os.path.join(DATA_DIR, "error.log"), "w", encoding="utf-8") as f:
                f.write(msg)
        except Exception:
            pass
        try:
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror("程序出错", msg[-1500:])
            r.destroy()
        except Exception:
            pass

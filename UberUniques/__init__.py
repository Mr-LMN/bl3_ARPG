from typing import Any, Dict
import random
from mods_base import hook, build_mod, SliderOption, keybind
from unrealsdk.hooks import Type
from unrealsdk.unreal import UObject, WrappedStruct
import unrealsdk


def _hud(title: str, msg: str) -> None:
    try:
        from ui_utils import show_hud_message
        show_hud_message(title, msg)
    except Exception:
        pass

DropChance: SliderOption = SliderOption("Uber Unique Drop Chance (1/n)", 1000, 100, 5000, 100, True)

_attr_bases: Dict[str, float] = {}
_active: Dict[str, Any] | None = None

ATTR_DMG_REDUCTION = "/Game/GameData/Attributes/Character/Att_Character_DamageReduction"
ATTR_PROJ_PER_SHOT = "/Game/GameData/Attributes/Weapon/Att_Weapon_ProjectilesPerShot"
ATTR_AS_CDR       = "/Game/GameData/Attributes/ActionSkill/Att_ActionSkill_CooldownRate"
ATTR_SPLASH_D     = "/Game/GameData/Attributes/Weapon/Att_Weapon_SplashDamageScale"
ATTR_SPLASH_R     = "/Game/GameData/Attributes/Weapon/Att_Weapon_SplashRadiusScale"

_attr_defs: Dict[str, Any] = {}

def _find_attr(path: str):
    if path in _attr_defs:
        return _attr_defs[path]
    obj = unrealsdk.FindObject("AttributeDefinition", path)
    _attr_defs[path] = obj
    return obj

def _cache_base(target, path: str) -> None:
    if path in _attr_bases:
        return
    attr = _find_attr(path)
    if attr and target:
        try:
            _attr_bases[path] = float(target.GetAttributeBaseValue(attr))
        except Exception:
            _attr_bases[path] = 1.0

def _apply_attr_scaled(target, path: str, mult: float) -> None:
    attr = _find_attr(path)
    if not attr or not target:
        return
    _cache_base(target, path)
    base = _attr_bases.get(path, 1.0)
    try:
        target.SetAttributeBaseValue(attr, base * mult)
    except Exception:
        pass

def _restore_attrs() -> None:
    try:
        pc = unrealsdk.GetEngine().GamePlayers[0].Actor
        tgt = pc if pc else None
        for path, base in _attr_bases.items():
            attr = _find_attr(path)
            if attr and tgt:
                try:
                    tgt.SetAttributeBaseValue(attr, base)
                except Exception:
                    pass
    except Exception:
        pass


def _apply_aegis() -> None:
    pc = unrealsdk.GetEngine().GamePlayers[0].Actor
    tgt = pc if pc else None
    _apply_attr_scaled(tgt, ATTR_DMG_REDUCTION, 0.5)

def _apply_multishot() -> None:
    pc = unrealsdk.GetEngine().GamePlayers[0].Actor
    tgt = pc if pc else None
    _apply_attr_scaled(tgt, ATTR_PROJ_PER_SHOT, 3.0)

def _apply_splash() -> None:
    pc = unrealsdk.GetEngine().GamePlayers[0].Actor
    tgt = pc if pc else None
    _apply_attr_scaled(tgt, ATTR_SPLASH_D, 4.0)
    _apply_attr_scaled(tgt, ATTR_SPLASH_R, 2.0)

def _apply_skillpoints() -> None:
    pc = unrealsdk.GetEngine().GamePlayers[0].Actor
    try:
        pc.AddSkillPoints(10)
    except Exception:
        try:
            pc.SkillPoints += 10
        except Exception:
            pass

UBERS = [
    {"name": "Aegis of the Ancients", "desc": "50% damage taken", "apply": _apply_aegis},
    {"name": "Echoing Volumes", "desc": "+200% projectiles per shot", "apply": _apply_multishot},
    {"name": "Nova Catalyst", "desc": "+300% splash dmg", "apply": _apply_splash},
    {"name": "Paragon Talisman", "desc": "+10 skill points", "apply": _apply_skillpoints},
]


def _grant_uber(item: Dict[str, Any]) -> None:
    global _active
    _restore_attrs()
    _active = item
    item["apply"]()
    _hud("Uber Unique", f"{item['name']} acquired — {item['desc']}")

def _roll_drop() -> None:
    if int(DropChance.value) <= 0:
        return
    if random.randint(1, int(DropChance.value)) == 1:
        item = random.choice(UBERS)
        _grant_uber(item)

@hook("/Script/OakGame.OakCharacter:Died", Type.POST)
def _on_died(obj: UObject, args: WrappedStruct, *_: Any) -> None:
    try:
        pc = unrealsdk.GetEngine().GamePlayers[0].Actor
        is_hostile = pc.GetTeamComponent().IsHostile if pc else None
        if is_hostile is None or is_hostile(obj):
            _roll_drop()
    except Exception:
        pass
    return

@keybind("Clear Uber Unique")
def _kb_clear() -> None:
    global _active
    _active = None
    _restore_attrs()
    _hud("Uber Unique", "Cleared")

build_mod()

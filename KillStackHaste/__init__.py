from typing import Any, Dict
from mods_base import hook, build_mod, SliderOption, BoolOption, keybind
from unrealsdk.hooks import Type
from unrealsdk.unreal import UObject, WrappedStruct
import unrealsdk

def _hud(title: str, msg: str) -> None:
    try:
        from ui_utils import show_hud_message
        show_hud_message(title, msg)
    except Exception:
        pass

PerKillPct: SliderOption = SliderOption("Per‑Kill %  (1=2.5, 2=5, 3=7.5, 4=10, 5=20)", 5, 1, 5, 1, True)
MaxStacks: SliderOption = SliderOption("Max Stacks (1–10)", 10, 1, 10, 1, True)
DecaySeconds: SliderOption = SliderOption("Seconds per Stack Decay (5–20)", 10, 5, 20, 1, True)

AffectReload:   BoolOption = BoolOption("Affect Reload Speed",   True,  "On", "Off")
AffectFireRate: BoolOption = BoolOption("Affect Fire Rate",      True,  "On", "Off")
AffectSplashD:  BoolOption = BoolOption("Affect Splash Damage",  True,  "On", "Off")
AffectSplashR:  BoolOption = BoolOption("Affect Splash Radius",  True,  "On", "Off")
AffectAS_CDR:   BoolOption = BoolOption("Affect Action Skill Cooldown Rate", True, "On", "Off")
UseTimeDilate:  BoolOption = BoolOption("Use Time Dilation for Movement", True, "On", "Off")
UseFOVBump:     BoolOption = BoolOption("Also bump FOV for visibility", True, "On", "Off")

_stacks: int = 0
_last_kill_time: float = 0.0
_base_walk: float | None = None
_base_sprint: float | None = None
_base_td: float | None = None
_base_fov: float | None = None

_attr_bases: Dict[str, float] = {}
_attr_defs: Dict[str, object] = {}

ATTR_RELOAD   = "/Game/GameData/Attributes/Weapon/Att_Weapon_ReloadSpeedScale"
ATTR_FIRERATE = "/Game/GameData/Attributes/Weapon/Att_Weapon_FireRateScale"
ATTR_SPLASH_D = "/Game/GameData/Attributes/Weapon/Att_Weapon_SplashDamageScale"
ATTR_SPLASH_R = "/Game/GameData/Attributes/Weapon/Att_Weapon_SplashRadiusScale"
ATTR_AS_CDR   = "/Game/GameData/Attributes/ActionSkill/Att_ActionSkill_CooldownRate"
ATTR_MOVE_CANDIDATES = [
    "/Game/GameData/Attributes/Movement/Att_CharacterMovementSpeed",
    "/Game/GameData/Attributes/Movement/Att_Character_Movement_Speed",
    "/Game/GameData/Attributes/Player/Att_CharacterMovementSpeed",
]

def _per_stack() -> float:
    return {1: 0.025, 2: 0.05, 3: 0.075, 4: 0.10, 5: 0.20}.get(int(PerKillPct.value), 0.05)

def _max_stacks() -> int:
    return int(MaxStacks.value)

def _decay_seconds() -> float:
    return float(DecaySeconds.value)

def _world_time() -> float:
    try:
        pc = unrealsdk.GetEngine().GamePlayers[0].Actor
        return pc.GetWorldInfo().TimeSeconds if pc else 0.0
    except Exception:
        return 0.0

def _find_attr(path: str):
    if path in _attr_defs:
        return _attr_defs[path]
    obj = unrealsdk.FindObject("AttributeDefinition", path)
    _attr_defs[path] = obj
    return obj

def _cache_attr_base(target, path: str):
    if path in _attr_bases:
        return
    attr = _find_attr(path)
    if attr and target:
        try:
            _attr_bases[path] = float(target.GetAttributeBaseValue(attr))
        except Exception:
            _attr_bases[path] = 1.0

def _apply_attr_scaled(target, path: str, mult: float):
    attr = _find_attr(path)
    if not attr or not target:
        return
    _cache_attr_base(target, path)
    base = _attr_bases.get(path, 1.0)
    try:
        target.SetAttributeBaseValue(attr, base * mult)
    except Exception:
        pass

def _apply_movement(pawn, mult: float) -> None:
    global _base_walk, _base_sprint, _base_td
    try:
        if not pawn or not pawn.CharacterMovement:
            return
        cm = pawn.CharacterMovement
        if _base_walk is None:
            _base_walk = float(getattr(cm, "MaxWalkSpeed", 600.0))
        if _base_sprint is None and hasattr(cm, "MaxSprintSpeed"):
            _base_sprint = float(getattr(cm, "MaxSprintSpeed"))
        if _base_td is None:
            _base_td = float(getattr(pawn, "CustomTimeDilation", 1.0))

        try: cm.MaxWalkSpeed = _base_walk * mult
        except Exception: pass
        try:
            if _base_sprint is not None and hasattr(cm, "MaxSprintSpeed"):
                cm.MaxSprintSpeed = _base_sprint * mult
        except Exception: pass

        for path in ATTR_MOVE_CANDIDATES:
            _apply_attr_scaled(pawn, path, mult)

        if UseTimeDilate.value:
            try: pawn.CustomTimeDilation = _base_td * mult
            except Exception: pass
        else:
            try: pawn.CustomTimeDilation = _base_td if _base_td is not None else 1.0
            except Exception: pass

    except Exception:
        pass

def _apply_fov(pc, mult: float) -> None:
    global _base_fov
    try:
        cam = pc.PlayerCameraManager if pc else None
        if not cam:
            return
        current_fov = 90.0
        try:
            current_fov = float(cam.GetFOVAngle())
        except Exception:
            try:
                current_fov = float(getattr(cam, "DefaultFOV", 90.0))
            except Exception:
                pass
        if _base_fov is None:
            _base_fov = current_fov
        target_fov = float(_base_fov) * (1.0 + 0.10*(mult-1.0))  # mild bump
        try:
            cam.SetFOV(target_fov)
        except Exception:
            try:
                cam.DefaultFOV = target_fov
            except Exception:
                pass
    except Exception:
        pass

def _apply_all() -> None:
    try:
        pc = unrealsdk.GetEngine().GamePlayers[0].Actor
        pawn = pc.Pawn if pc else None
        if not pawn:
            return
        mult = (1.0 + _per_stack()) ** _stacks
        _apply_movement(pawn, mult)
        if UseFOVBump.value:
            _apply_fov(pc, mult)
        tgt = pc if pc else pawn
        if AffectReload.value:   _apply_attr_scaled(tgt, ATTR_RELOAD,   mult)
        if AffectFireRate.value: _apply_attr_scaled(tgt, ATTR_FIRERATE, mult)
        if AffectSplashD.value:  _apply_attr_scaled(tgt, ATTR_SPLASH_D, mult)
        if AffectSplashR.value:  _apply_attr_scaled(tgt, ATTR_SPLASH_R, mult)
        if AffectAS_CDR.value:   _apply_attr_scaled(pc if pc else pawn, ATTR_AS_CDR, mult)
    except Exception:
        pass

def _restore_all() -> None:
    try:
        pc = unrealsdk.GetEngine().GamePlayers[0].Actor
        pawn = pc.Pawn if pc else None
        if pawn and pawn.CharacterMovement and _base_walk is not None:
            cm = pawn.CharacterMovement
            try: cm.MaxWalkSpeed = _base_walk
            except Exception: pass
            if _base_sprint is not None and hasattr(cm, "MaxSprintSpeed"):
                try: cm.MaxSprintSpeed = _base_sprint
                except Exception: pass
        if _base_td is not None and pawn and hasattr(pawn, "CustomTimeDilation"):
            try: pawn.CustomTimeDilation = _base_td
            except Exception: pass
        if _base_fov is not None and pc and getattr(pc, "PlayerCameraManager", None):
            try:
                pc.PlayerCameraManager.SetFOV(_base_fov)
            except Exception:
                try:
                    pc.PlayerCameraManager.DefaultFOV = _base_fov
                except Exception:
                    pass
    except Exception:
        pass
    try:
        pc = unrealsdk.GetEngine().GamePlayers[0].Actor
        pawn = pc.Pawn if pc else None
        tgt = pc if pc else pawn
        for path, base in _attr_bases.items():
            attr = _find_attr(path)
            if attr and tgt:
                try: tgt.SetAttributeBaseValue(attr, base)
                except Exception: pass
    except Exception:
        pass

def _gain_stack() -> None:
    global _stacks, _last_kill_time
    new_val = min(_stacks + 1, _max_stacks())
    if new_val != _stacks:
        _stacks = new_val
        _last_kill_time = _world_time()
        _hud("KillStackHaste", f"Stacks: {_stacks}  (+{int(_per_stack()*100)}% per)")
        _apply_all()

def _clear_stacks() -> None:
    global _stacks
    _stacks = 0
    _hud("KillStackHaste", "Stacks cleared")
    _restore_all()

def _decay(now: float) -> None:
    global _stacks, _last_kill_time
    while _stacks > 0 and now - _last_kill_time >= _decay_seconds():
        _stacks -= 1
        _last_kill_time += _decay_seconds()

@hook("/Script/OakGame.OakCharacter:Died", Type.POST)
def _on_died_char(obj: UObject, args: WrappedStruct, *_: Any) -> None:
    try:
        pc = unrealsdk.GetEngine().GamePlayers[0].Actor
        is_hostile = pc.GetTeamComponent().IsHostile if pc else None
        if is_hostile is None or is_hostile(obj):
            _gain_stack()
    except Exception:
        pass
    return

@hook("/Script/OakGame.OakDamageComponent:OnDeath", Type.POST)
def _on_death_dc(obj: UObject, args: WrappedStruct, *_: Any) -> None:
    try:
        owner = getattr(obj, "Owner", None) or getattr(obj, "GetOwner", lambda: None)()
        pc = unrealsdk.GetEngine().GamePlayers[0].Actor
        is_hostile = pc.GetTeamComponent().IsHostile if pc else None
        if owner and (is_hostile is None or is_hostile(owner)):
            _gain_stack()
    except Exception:
        pass
    return

@hook("/Script/OakGame.OakPlayerController:PlayerTick", Type.POST)
def _on_tick(obj: UObject, args: WrappedStruct, *_: Any) -> None:
    try:
        now = _world_time()
        _decay(now)
        _apply_all()
        if _stacks == 0:
            _restore_all()
    except Exception:
        pass
    return

@keybind("KSH: Add Stack")
def _kb_add() -> None:
    _gain_stack()
    _apply_all()

@keybind("KSH: Clear Stacks")
def _kb_clear() -> None:
    _clear_stacks()
    _apply_all()

build_mod()

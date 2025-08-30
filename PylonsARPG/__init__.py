from typing import Any, Dict, List, Tuple, Optional
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

Duration: SliderOption = SliderOption("Pylon Duration (sec)", 35, 20, 60, 5, True)
Cooldown: SliderOption = SliderOption("Anchor Cooldown (sec)", 180, 60, 600, 30, True)
MaxSimultaneous: SliderOption = SliderOption("Max Concurrent Pylon Buffs", 2, 1, 3, 1, True)
AnchorsPerMap: SliderOption = SliderOption("Anchors Per Map (1–3)", 3, 1, 3, 1, True)

EnableFrenzy:   BoolOption = BoolOption("Enable Frenzy (MS/Reload/FireRate)", True, "On", "Off")
EnableConquest: BoolOption = BoolOption("Enable Conquest (Splash Dmg/Radius)", True, "On", "Off")
ShowHUDHints:   BoolOption = BoolOption("Show HUD Hints Near Anchors", True, "On", "Off")

ATTR_RELOAD   = "/Game/GameData/Attributes/Weapon/Att_Weapon_ReloadSpeedScale"
ATTR_FIRERATE = "/Game/GameData/Attributes/Weapon/Att_Weapon_FireRateScale"
ATTR_SPLASH_D = "/Game/GameData/Attributes/Weapon/Att_Weapon_SplashDamageScale"
ATTR_SPLASH_R = "/Game/GameData/Attributes/Weapon/Att_Weapon_SplashRadiusScale"

FRENZY_MS   = 1.25
FRENZY_RE   = 1.25
FRENZY_FR   = 1.20
CONQ_SD     = 1.35
CONQ_SR     = 1.30

_anchors: List[Dict[str, Any]] = []
_active: List[Dict[str, Any]] = []
_built_for_map: Optional[str] = None
_last_hint_time: float = 0.0

def _world_time() -> float:
    try:
        pc = unrealsdk.GetEngine().GamePlayers[0].Actor
        return pc.GetWorldInfo().TimeSeconds if pc else 0.0
    except Exception:
        return 0.0

def _map_name() -> str:
    try:
        pc = unrealsdk.GetEngine().GamePlayers[0].Actor
        wi = pc.GetWorldInfo() if pc else None
        return wi.GetMapName() if wi else "Unknown"
    except Exception:
        return "Unknown"

def _pawn_loc() -> Optional[Tuple[float,float,float]]:
    try:
        pc = unrealsdk.GetEngine().GamePlayers[0].Actor
        pawn = pc.Pawn if pc else None
        if not pawn:
            return None
        loc = pawn.K2_GetActorLocation()
        return (float(loc.X), float(loc.Y), float(loc.Z))
    except Exception:
        return None

def _apply_attr_scaled(target, path: str, mult: float):
    attr = unrealsdk.FindObject("AttributeDefinition", path)
    if not attr or not target:
        return
    try:
        base = float(target.GetAttributeBaseValue(attr))
    except Exception:
        base = 1.0
    try:
        target.SetAttributeBaseValue(attr, base * mult)
    except Exception:
        pass

def _apply_frenzy() -> None:
    pc = unrealsdk.GetEngine().GamePlayers[0].Actor
    pawn = pc.Pawn if pc else None
    if not pc or not pawn:
        return
    try:
        base_td = float(getattr(pawn, "CustomTimeDilation", 1.0))
        pawn.CustomTimeDilation = base_td * FRENZY_MS
    except Exception:
        pass
    tgt = pc if pc else pawn
    _apply_attr_scaled(tgt, ATTR_RELOAD, FRENZY_RE)
    _apply_attr_scaled(tgt, ATTR_FIRERATE, FRENZY_FR)

def _apply_conquest() -> None:
    pc = unrealsdk.GetEngine().GamePlayers[0].Actor
    pawn = pc.Pawn if pc else None
    if not pc or not pawn:
        return
    tgt = pc if pc else pawn
    _apply_attr_scaled(tgt, ATTR_SPLASH_D, CONQ_SD)
    _apply_attr_scaled(tgt, ATTR_SPLASH_R, CONQ_SR)

def _restore_all() -> None:
    try:
        pc = unrealsdk.GetEngine().GamePlayers[0].Actor
        pawn = pc.Pawn if pc else None
        if pawn and hasattr(pawn, "CustomTimeDilation"):
            try: pawn.CustomTimeDilation = 1.0
            except Exception: pass
        tgt = pc if pc else pawn
        for path in [ATTR_RELOAD, ATTR_FIRERATE, ATTR_SPLASH_D, ATTR_SPLASH_R]:
            try:
                attr = unrealsdk.FindObject("AttributeDefinition", path)
                if attr and tgt:
                    base = float(tgt.GetAttributeBaseValue(attr))
                    tgt.SetAttributeBaseValue(attr, base)
            except Exception:
                pass
    except Exception:
        pass

def _assign_types(count: int) -> List[str]:
    pool = []
    if EnableFrenzy.value: pool.append("Frenzy")
    if EnableConquest.value: pool.append("Conquest")
    if not pool: pool = ["Frenzy"]
    return [pool[i % len(pool)] for i in range(count)]

def _build_anchors_if_needed() -> None:
    global _built_for_map, _anchors
    mapname = _map_name()
    if _built_for_map == mapname and _anchors:
        return
    _anchors = []
    _built_for_map = mapname
    me = _pawn_loc()
    if not me:
        return
    ax = int(AnchorsPerMap.value)
    offsets = [(0.0,0.0,0.0), (1200.0,0.0,0.0), (0.0,1200.0,0.0)][:ax]
    types = _assign_types(len(offsets))
    now = _world_time()
    for i, off in enumerate(offsets):
        pos = (me[0]+off[0], me[1]+off[1], me[2]+off[2])
        _anchors.append({"map": mapname, "pos": pos, "type": types[i], "cooldown_until": now})
    _hud("Pylons", f"{len(_anchors)} pylons ready in {mapname}")

def _dist(a: Tuple[float,float,float], b: Tuple[float,float,float]) -> float:
    dx, dy, dz = a[0]-b[0], a[1]-b[1], a[2]-b[2]
    return (dx*dx+dy*dy+dz*dz) ** 0.5

def _draw_anchors() -> None:
    try:
        for a in _anchors:
            pos = a["pos"]
            unrealsdk.DrawDebugSphere(pos, 50.0, 12, (0, 255, 255, 255), False, 0.1)
    except Exception:
        pass

def _nearest_anchor(within: float=1200.0):
    me = _pawn_loc()
    if not me or not _anchors:
        return None, None
    best = None
    bestd = 9e9
    curmap = _map_name()
    for i,a in enumerate(_anchors):
        if a["map"] != curmap:
            continue
        d = _dist(a["pos"], me)
        if d < bestd and d <= within:
            bestd = d
            best = i
    return best, bestd if best is not None else (None, None)

def _activate_anchor(i: int) -> None:
    if i is None or i < 0 or i >= len(_anchors):
        return
    now = _world_time()
    a = _anchors[i]
    if now < a["cooldown_until"]:
        secs = int(a["cooldown_until"] - now)
        _hud("Pylons", f"{a['type']} on cooldown ({secs}s)")
        return
    _active[:] = [b for b in _active if b["expires"] > now]
    if len(_active) >= int(MaxSimultaneous.value):
        _hud("Pylons", "Pylon limit reached")
        return
    dur = int(Duration.value)
    if a["type"] == "Frenzy":
        _apply_frenzy()
    else:
        _apply_conquest()
    _active.append({"type": a["type"], "expires": now + dur})
    a["cooldown_until"] = now + max(int(Cooldown.value), dur + 10)
    _hud("Pylons", f"{a['type']} activated — {dur}s")

def _tick_expiry() -> None:
    now = _world_time()
    before = len(_active)
    _active[:] = [b for b in _active if b["expires"] > now]
    if before > 0 and len(_active) == 0:
        _restore_all()

@hook("/Script/OakGame.OakPlayerController:PlayerTick", Type.POST)
def _on_tick(obj: UObject, args: WrappedStruct, *_: Any) -> None:
    global _last_hint_time
    try:
        _build_anchors_if_needed()
        _draw_anchors()
        _tick_expiry()
        now = _world_time()
        if ShowHUDHints.value and (now - _last_hint_time) > 1.0:
            idx, d = _nearest_anchor(1200.0)
            if idx is not None:
                _hud("Pylons", f"Near {_anchors[idx]['type']} — press bound key")
            _last_hint_time = now
    except Exception:
        pass
    return

@keybind("Pylon: Use Nearest")
def _kb_use() -> None:
    i, d = _nearest_anchor(1200.0)
    if i is None:
        _hud("Pylons", "No pylon nearby")
        return
    _activate_anchor(i)

@keybind("Pylon: Drop Anchor Here")
def _kb_drop_here() -> None:
    me = _pawn_loc()
    if not me:
        return
    now = _world_time()
    _anchors.append({"map": _map_name(), "pos": me, "type": "Frenzy", "cooldown_until": now})
    _hud("Pylons", "Temporary Frenzy pylon dropped at your feet")

build_mod()

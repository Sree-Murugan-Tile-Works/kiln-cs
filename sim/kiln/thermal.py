"""
Heat in the ring: gas, tiles and brickwork for one time step.

Each room unit holds two lumps that store heat:
  * the **tiles** (dry mass times specific heat), with the water still in them;
  * the **brick**: an effective share of the arch, walls and floor near the hot face.
The two interconnecting flues have brick only.

The gas is quasi-steady: it passes through the whole kiln in seconds, while the solids change over
hours. Each step the gas is followed unit by unit in the direction it flows (from the open doors,
through the cooling and firing zones, to the lifted dampers). In each unit:

  1. **Mix.** Gas arriving along the tunnel, air entering from the room (at ambient) and the
     products of the fuel burning in that unit are mixed. The fuel adds its heat and its mass.
  2. **Exchange.** The mixed gas meets the tiles and brick. Seen from the gas, the two lumps act as
     one wall at their h*A-weighted temperature ``T_wall``, so the gas leaves at

         T_out = T_wall + (T_mix - T_wall) * exp(-NTU),     NTU = (hA_tile + hA_brick) / (m * cp)

     This is exact for a gas passing a wall of fixed temperature and cannot overshoot, whatever the
     flow or the step.
  3. **Solids.** The heat the gas gives up is shared between tiles and brick. The brick also loses
     ``UA * (T_brick - T_ambient)`` to the outside. Both are integrated with backward (implicit)
     Euler: heat flows are evaluated at the END-of-step temperatures, which is stable and does not
     overshoot for any step length. The gas temperatures are then computed from those same
     end-of-step temperatures, so the heat the gas loses is exactly the heat the solids gain.
  4. **Drying.** While tiles hold water they cannot rise above ``boiling_c``: heat that would lift
     them higher evaporates water instead. The vapour joins the gas leaving the unit at
     ``boiling_c``. The tiles pay the latent heat plus the vapour's sensible heat (from the
     reference temperature to boiling), which the vapour then carries in the gas stream.
  5. **Split.** The gas leaving the unit is shared between its outlets (damper, next unit, door)
     in the proportions the flow network found. Fuel and vapour mass therefore add to the gas
     downstream, so mass is conserved by construction.

Energy is booked as enthalpy above a fixed reference temperature ``t_ref_c`` with one specific heat
for all gas. Fuel enters at the reference temperature and brings only its heating value.

Simplifications (deliberate):
  * tiles dry only at boiling (real tiles lose some water earlier, "sweating"); the water's own
    heat capacity is left out of the tile lump;
  * no radiation or conduction along the ring between units; heat moves only with the gas;
  * there is always enough air for the fuel to burn (excess air is not checked per unit);
  * the gas specific heat does not depend on temperature or on water vapour content.
"""
import math
from dataclasses import dataclass

from sim.kiln.params import KilnParams

FLOW_EPS_KG_S = 1e-12      # flows smaller than this count as no flow
MIN_GAS_KG_S = 1e-9        # below this a unit has no gas to exchange heat with


@dataclass(frozen=True)
class GasFlows:
    """Network flows for one step, indexed by firebox number - 1 (see ``sim.kiln.network``)."""
    along_kg_s: tuple[float, ...]    # unit n -> unit n+1 (clockwise positive)
    inlet_kg_s: tuple[float, ...]    # room -> unit n (negative: gas escaping to the room)
    damper_kg_s: tuple[float, ...]   # unit n -> main flue


@dataclass
class Solids:
    """State that is carried from step to step, indexed by firebox number - 1."""
    tile_c: list[float]
    brick_c: list[float]
    water_kg: list[float]
    has_tiles: list[bool]


@dataclass(frozen=True)
class StepResult:
    """Everything one thermal step produced. Rates are averages over the step (W, kg/s)."""
    gas_c: tuple[float, ...]             # gas leaving each unit
    through_kg_s: tuple[float, ...]      # gas leaving each unit (all outlets together)
    damper_kg_s: tuple[float, ...]       # gas each unit sends to the main flue (incl. fuel and vapour mass)
    tile_heat_w: tuple[float, ...]       # heat the gas gave each unit's tiles
    brick_heat_w: tuple[float, ...]      # heat the gas gave each unit's brick
    evaporated_kg: tuple[float, ...]     # water driven off each unit this step
    wall_loss_w: float                   # brick to outside, whole kiln
    air_in_kg_s: float                   # air entering from the room
    air_in_w: float                      # enthalpy it brings above the reference (0 when ambient = reference)
    fuel_kg_s: float                     # fuel mass burnt
    fuel_w: float                        # heat released by the fuel
    vapour_kg_s: float
    latent_w: float                      # latent heat of the water evaporated
    exhaust_kg_s: float                  # gas reaching the main flue
    exhaust_c: float                     # its mixed temperature
    exhaust_w: float                     # enthalpy it carries above the reference
    vented_kg_s: float                   # gas leaving through a door or leak instead of a damper
    vented_w: float


def flow_order(along: tuple[float, ...]) -> list[int]:
    """
    Units in the order the gas reaches them (a topological order of the chain).

    Unit i feeds i+1 when the flow along is positive and i-1 when the flow from i-1 to i is
    negative. The paper seal guarantees one zero link, so there is no loop.
    """
    n = len(along)
    waiting = [0] * n
    for i in range(n):
        if along[i] > FLOW_EPS_KG_S:
            waiting[(i + 1) % n] += 1
        elif along[i] < -FLOW_EPS_KG_S:
            waiting[i] += 1
    ready = [i for i in range(n) if waiting[i] == 0]
    order = []
    while ready:
        i = ready.pop()
        order.append(i)
        for j in _downstream(along, i):
            waiting[j] -= 1
            if waiting[j] == 0:
                ready.append(j)
    if len(order) != n:
        raise ValueError("the gas flows round a closed loop; the ring must be cut by a paper seal")
    return order


def _downstream(along: tuple[float, ...], i: int) -> list[int]:
    n = len(along)
    out = []
    if along[i] > FLOW_EPS_KG_S:
        out.append((i + 1) % n)
    if along[i - 1] < -FLOW_EPS_KG_S:
        out.append((i - 1) % n)
    return out


def _solve2(a11: float, a12: float, a21: float, a22: float, b1: float, b2: float) -> tuple[float, float]:
    det = a11 * a22 - a12 * a21
    return (b1 * a22 - a12 * b2) / det, (a11 * b2 - a21 * b1) / det


def _exchange(kp: KilnParams, m: float, t_mix: float, tile_old: float, brick_old: float, has_tiles: bool,
              t_amb: float, dt: float, fixed_tile: float | None) -> tuple[float, float, float, float]:
    """
    Backward-Euler update of the two lumps of one unit against gas at ``t_mix``.

    Returns (tile end, brick end, heat to tile W, heat to brick W). With ``fixed_tile`` the tile
    end temperature is held there (drying) and its energy balance is settled by the caller.
    """
    ha_t = kp.tile_ha_w_k if has_tiles else 0.0
    ha_b = kp.brick_ha_w_k
    ha = ha_t + ha_b
    w_t, w_b = ha_t / ha, ha_b / ha
    cp = kp.gas_cp_j_kg_k
    g = m * cp * (1.0 - math.exp(-ha / (m * cp))) if m > MIN_GAS_KG_S else 0.0   # effective gas conductance
    alpha = ha_t * ha_b / ha                       # tile-brick exchange through the gas films
    c_t = kp.tile_dry_kg * kp.tile_cp_j_kg_k / dt
    c_b = kp.brick_kg * kp.brick_cp_j_kg_k / dt
    ua = kp.wall_ua_w_k

    # heat to tile  = alpha*(Tb - Tt) + w_t*G*(Tmix - w_t*Tt - w_b*Tb)
    # heat to brick = alpha*(Tt - Tb) + w_b*G*(Tmix - w_t*Tt - w_b*Tb) ; brick also loses UA*(Tb - Tamb)
    b11, b12 = alpha + w_b * w_b * g + ua + c_b, -alpha + w_b * w_t * g
    if not has_tiles:
        brick = (c_b * brick_old + w_b * g * t_mix + ua * t_amb) / (c_b + w_b * g + ua)
        return tile_old, brick, 0.0, w_b * g * (t_mix - brick)
    if fixed_tile is None:
        tile, brick = _solve2(c_t + alpha + w_t * w_t * g, -alpha + w_t * w_b * g,
                              -alpha + w_b * w_t * g, b11,
                              c_t * tile_old + w_t * g * t_mix, c_b * brick_old + w_b * g * t_mix + ua * t_amb)
    else:
        tile = fixed_tile
        brick = (c_b * brick_old + w_b * g * t_mix + ua * t_amb - (-alpha + w_b * w_t * g) * tile) / b11
    wall = w_t * tile + w_b * brick
    to_gas_wall = g * (t_mix - wall)
    heat_t = alpha * (brick - tile) + w_t * to_gas_wall
    heat_b = alpha * (tile - brick) + w_b * to_gas_wall
    return tile, brick, heat_t, heat_b


def thermal_step(kp: KilnParams, flows: GasFlows, solids: Solids, fuel_w: list[float], fuel_kg_s: list[float],
                 t_amb_c: float, t_ref_c: float, dt_s: float) -> StepResult:
    """
    Advance gas and solids by ``dt_s`` seconds. ``solids`` is updated in place.

    ``fuel_w`` and ``fuel_kg_s`` are the heat released and the fuel mass burnt in each unit,
    averaged over the step.
    """
    if dt_s <= 0.0:
        raise ValueError("time step must be positive")
    n = len(flows.along_kg_s)
    if not (len(flows.inlet_kg_s) == len(flows.damper_kg_s) == len(fuel_w) == len(fuel_kg_s)
            == len(solids.tile_c) == n):
        raise ValueError("every per-unit list must have one entry per firebox")
    cp = kp.gas_cp_j_kg_k
    along, inlet, damper = flows.along_kg_s, flows.inlet_kg_s, flows.damper_kg_s
    vapour_h = kp.latent_heat_j_kg + cp * (kp.boiling_c - t_ref_c)   # what the tiles pay per kg evaporated

    gas_c = [t_amb_c] * n
    through = [0.0] * n
    sent_forward = [0.0] * n          # actual gas from unit i to unit i+1
    sent_back = [0.0] * n             # actual gas from unit i to unit i-1
    to_damper = [0.0] * n
    tile_heat = [0.0] * n
    brick_heat = [0.0] * n
    evaporated = [0.0] * n
    totals = dict(wall=0.0, air=0.0, air_w=0.0, vented=0.0, vented_w=0.0, ex=0.0, ex_w=0.0)

    for i in flow_order(along):
        # ---- 1. mix
        m, h = fuel_kg_s[i], fuel_w[i]                          # fuel: mass at the reference, plus its heat
        if along[i - 1] > FLOW_EPS_KG_S:
            m += sent_forward[i - 1]
            h += sent_forward[i - 1] * cp * (gas_c[i - 1] - t_ref_c)
        if along[i] < -FLOW_EPS_KG_S:
            j = (i + 1) % n
            m += sent_back[j]
            h += sent_back[j] * cp * (gas_c[j] - t_ref_c)
        if inlet[i] > 0.0:
            m += inlet[i]
            h += inlet[i] * cp * (t_amb_c - t_ref_c)
            totals["air"] += inlet[i]
            totals["air_w"] += inlet[i] * cp * (t_amb_c - t_ref_c)
        if m > MIN_GAS_KG_S:
            t_mix = t_ref_c + h / (m * cp)
        else:                                                    # no gas: any fuel heat goes straight to the solids
            t_mix, m = t_amb_c, 0.0

        # ---- 2-4. exchange with the solids, drying
        has_tiles = solids.has_tiles[i]
        tile_old, brick_old = solids.tile_c[i], solids.brick_c[i]
        tile, brick, q_t, q_b = _exchange(kp, m, t_mix, tile_old, brick_old, has_tiles, t_amb_c, dt_s, None)
        steam = 0.0
        if has_tiles and solids.water_kg[i] > 0.0 and tile > kp.boiling_c:
            tile, brick, q_t, q_b = _exchange(kp, m, t_mix, tile_old, brick_old, True, t_amb_c, dt_s, kp.boiling_c)
            c_t = kp.tile_dry_kg * kp.tile_cp_j_kg_k
            spare_j = q_t * dt_s - c_t * (kp.boiling_c - tile_old)       # energy left after reaching boiling
            steam = min(solids.water_kg[i], max(0.0, spare_j / vapour_h))
            tile = kp.boiling_c + (spare_j - steam * vapour_h) / c_t      # all water gone: the rest heats the tiles
            solids.water_kg[i] -= steam
        totals["wall"] += kp.wall_ua_w_k * (brick - t_amb_c)     # at the end-of-step temperature (implicit)
        if m == 0.0 and h > 0.0:                                 # (rare) fuel burning with no gas through:
            q_b += h                                             # its heat goes into the brick directly
            brick += h * dt_s / (kp.brick_kg * kp.brick_cp_j_kg_k)
        solids.tile_c[i], solids.brick_c[i] = tile, brick
        tile_heat[i], brick_heat[i] = q_t, q_b
        evaporated[i] = steam

        # ---- gas leaving the unit, then the vapour joins it
        h_out = h - q_t - q_b if m > 0.0 else 0.0
        v = steam / dt_s
        m_out = m + v
        h_out += v * cp * (kp.boiling_c - t_ref_c)
        gas_c[i] = t_ref_c + h_out / (m_out * cp) if m_out > MIN_GAS_KG_S else tile if has_tiles else brick
        through[i] = m_out

        # ---- 5. split between the outlets in the network's proportions
        forward = along[i] if along[i] > FLOW_EPS_KG_S else 0.0
        back = -along[i - 1] if along[i - 1] < -FLOW_EPS_KG_S else 0.0
        out_room = -inlet[i] if inlet[i] < 0.0 else 0.0
        outlets = damper[i] + forward + back + out_room
        if outlets <= FLOW_EPS_KG_S:                             # nowhere to go in the network: it escapes to the room
            totals["vented"] += m_out
            totals["vented_w"] += m_out * cp * (gas_c[i] - t_ref_c)
            continue
        share = m_out / outlets
        sent_forward[i], sent_back[i], to_damper[i] = forward * share, back * share, damper[i] * share
        totals["vented"] += out_room * share
        totals["vented_w"] += out_room * share * cp * (gas_c[i] - t_ref_c)
        totals["ex"] += to_damper[i]
        totals["ex_w"] += to_damper[i] * cp * (gas_c[i] - t_ref_c)

    exhaust_c = t_ref_c + totals["ex_w"] / (totals["ex"] * cp) if totals["ex"] > MIN_GAS_KG_S else t_amb_c
    vapour = sum(evaporated) / dt_s
    return StepResult(
        gas_c=tuple(gas_c), through_kg_s=tuple(through), damper_kg_s=tuple(to_damper),
        tile_heat_w=tuple(tile_heat), brick_heat_w=tuple(brick_heat), evaporated_kg=tuple(evaporated),
        wall_loss_w=totals["wall"], air_in_kg_s=totals["air"], air_in_w=totals["air_w"],
        fuel_kg_s=sum(fuel_kg_s), fuel_w=sum(fuel_w), vapour_kg_s=vapour, latent_w=vapour * kp.latent_heat_j_kg,
        exhaust_kg_s=totals["ex"], exhaust_c=exhaust_c, exhaust_w=totals["ex_w"],
        vented_kg_s=totals["vented"], vented_w=totals["vented_w"])


def stored_heat_j(kp: KilnParams, solids: Solids, t_ref_c: float) -> float:
    """Heat held by all tiles and brick above the reference temperature."""
    c_t = kp.tile_dry_kg * kp.tile_cp_j_kg_k
    c_b = kp.brick_kg * kp.brick_cp_j_kg_k
    total = 0.0
    for tile, brick, has_tiles in zip(solids.tile_c, solids.brick_c, solids.has_tiles):
        total += c_b * (brick - t_ref_c)
        if has_tiles:
            total += c_t * (tile - t_ref_c)
    return total

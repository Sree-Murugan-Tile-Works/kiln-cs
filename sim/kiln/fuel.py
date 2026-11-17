"""
Fuel: the firing plan recipe, the charge rules and how a charge burns.

What the plant does (VelKilnMaster ``docs/Kiln-Domain.md``, "Firing Plan"): every 15 minutes each
firing firebox gets a weighed charge, split over its 4 portholes. The plan ramps the charge up,
holds it and tapers it off; Fp1(170) is about 724 kg over 160 charges (40 h). Some boxes carry a
condition on the point temperature: "< 630 = +1 kg" (feed more when cool) or "> 830 = 0 kg"
(skip when hot). Wetter firewood is fed heavier so the heat delivered stays the same.

What the model does:
  * firewood only (the real plan starts with some coal; not modelled);
  * a ramp-hold-taper shape scaled so the plan total matches 724 kg per 160 charges. The exact
    weights per box are in the plant workbook, which has not been read; the shape is a placeholder;
  * the conditions apply to every charge (the "add" condition only after the ramp), with
    thresholds as parameters;
  * the net heating value is moved to another moisture with the usual wet-basis rule
    ``LHV(w) = LHV_dry * (1 - w) - 2.44 MJ/kg * w``;
  * a charge on the grate burns out exponentially: ``burnt = grate * (1 - exp(-dt / tau))``,
    which is exact for any time step.
"""
import math

from sim.kiln.params import KilnParams

MJ = 1.0e6
MAX_MOISTURE = 0.6            # wood wetter than this hardly burns; reject it as an input error


def _check_moisture(moisture: float) -> None:
    if not 0.0 <= moisture <= MAX_MOISTURE:
        raise ValueError(f"fuel moisture must be between 0 and {MAX_MOISTURE} (fraction, wet basis)")


def dry_lhv_mj_kg(kp: KilnParams) -> float:
    """Heating value of bone-dry wood implied by the reference value at the reference moisture."""
    w = kp.fuel_moisture_ref
    return (kp.fuel_lhv_ref_mj_kg + kp.water_latent_25c_mj_kg * w) / (1.0 - w)


def lhv_j_kg(kp: KilnParams, moisture: float) -> float:
    """Net heating value of wood at a moisture (wet basis), in J/kg. Wetter wood gives less heat per kg."""
    _check_moisture(moisture)
    value = dry_lhv_mj_kg(kp) * (1.0 - moisture) - kp.water_latent_25c_mj_kg * moisture
    return max(0.0, value) * MJ


def moisture_factor(kp: KilnParams, moisture: float) -> float:
    """
    How much heavier a charge is fed for wood at ``moisture`` than for wood at the reference moisture.

    With ``moisture_compensation = 1`` the extra weight exactly restores the heat of the charge; with
    0 the weight is not changed (so wetter wood gives less heat).
    """
    wet = lhv_j_kg(kp, moisture)
    if wet <= 0.0:
        raise ValueError("wood this wet gives no net heat")
    full = lhv_j_kg(kp, kp.fuel_moisture_ref) / wet
    return 1.0 + kp.moisture_compensation * (full - 1.0)


def charge_plan(kp: KilnParams, charge_count: int) -> tuple[float, ...]:
    """
    Standard charge weights (kg, at the reference moisture) for charges 1..charge_count.

    Ramp from ``ramp_start_fraction`` of a full charge to a full charge, hold, taper to
    ``taper_end_fraction``. The weights are scaled so the average charge is the plan average
    (724 kg / 160 charges = 4.5 kg).
    """
    if charge_count <= 0:
        raise ValueError("charge count must be positive")
    ramp = max(1, round(kp.ramp_share * charge_count))
    taper = max(1, round(kp.taper_share * charge_count))
    shape = []
    for i in range(charge_count):
        if i < ramp:
            shape.append(kp.ramp_start_fraction + (1.0 - kp.ramp_start_fraction) * i / ramp)
        elif i >= charge_count - taper:
            into_taper = (i - (charge_count - taper) + 1) / taper
            shape.append(1.0 + (kp.taper_end_fraction - 1.0) * into_taper)
        else:
            shape.append(1.0)
    mean_kg = kp.fuel_per_firebox_kg / kp.plan_charge_count
    scale = mean_kg * charge_count / sum(shape)
    return tuple(s * scale for s in shape)


def charge_mass_kg(kp: KilnParams, plan: tuple[float, ...], number: int, point_c: float,
                   moisture: float, size_factor: float = 1.0) -> tuple[float, str]:
    """
    Weight fed for charge ``number`` (1-based) and the reason: "plan", "skip" or "add".

    ``point_c`` is the point (thermocouple) reading of the firebox when the charge is due;
    ``size_factor`` scales every charge (an operator feeding heavier or lighter than the plan).
    """
    if not 1 <= number <= len(plan):
        raise ValueError(f"charge number must be 1..{len(plan)}")
    if size_factor < 0.0:
        raise ValueError("charge size factor must not be negative")
    if point_c > kp.skip_above_c:
        return 0.0, "skip"
    weight = plan[number - 1]
    reason = "plan"
    if number >= kp.conditional_from_charge and point_c < kp.add_below_c:
        weight += kp.add_kg
        reason = "add"
    return weight * size_factor * moisture_factor(kp, moisture), reason


def burn(grate_kg: float, grate_j: float, dt_s: float, tau_s: float) -> tuple[float, float, float, float]:
    """
    Burn fuel lying on the grate for ``dt_s`` seconds.

    Returns (mass burnt kg, heat released J, mass left kg, heat left J). Mass and heat burn in the
    same proportion, so fuel fed at different moistures keeps its own heating value.
    """
    if dt_s <= 0.0 or tau_s <= 0.0:
        raise ValueError("time step and burn time constant must be positive")
    fraction = 1.0 - math.exp(-dt_s / tau_s)
    burnt_kg, released_j = grate_kg * fraction, grate_j * fraction
    return burnt_kg, released_j, grate_kg - burnt_kg, grate_j - released_j

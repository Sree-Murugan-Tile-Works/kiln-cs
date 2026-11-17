"""
The exhaust path at one instant, station by station, plus the derived calculations.

``build_profile`` turns an ``OperatingPoint`` into plain data for the GUI picture and the
calculations panel: where each station is, how big the tube is there, and the temperature,
pressure, density and velocity of the gas, with the outside air at matching heights.

All arithmetic is done here so the browser only draws.

Particle counts
---------------
The picture draws particles to show how many gas molecules there are per unit volume. For an
ideal gas that is proportional to ``pressure / temperature``. ``density_true`` is that number
relative to the outside air at ground level (1.0 = the same as the air around the kiln).

Pressure differences in this system are far below 1 % of atmospheric, so at true scale only the
temperature shows. ``density_exaggerated`` multiplies every pressure difference from ground level
by ``PRESSURE_EXAGGERATION`` so the thinning of the sky with height and the suction and pressure
zones along the tube become visible. It is for the picture only; no number shown uses it.
"""
from sim.gas import density, air_viscosity, barometric_pressure, AIR_MOLAR_MASS_G_MOL, KELVIN, G
from sim.plant import OperatingPoint, chimney_state, _circle_area

PRESSURE_EXAGGERATION = 100.0      # picture only: pressure differences are drawn this many times bigger
MIN_DRAWN_DENSITY = 0.05           # never draw fewer particles than this fraction of ground-level air


def _relative_density(p_abs_pa: float, t_c: float, p_ground_pa: float, t_amb_c: float,
                      exaggeration: float = 1.0) -> float:
    """Molecules per unit volume relative to the outside air at ground level (p / T, ideal gas)."""
    pressure_ratio = 1.0 + exaggeration * (p_abs_pa / p_ground_pa - 1.0)
    temperature_ratio = (t_amb_c + KELVIN) / (t_c + KELVIN)
    return max(MIN_DRAWN_DENSITY, pressure_ratio * temperature_ratio)


def _densities(p_abs_pa: float, t_c: float, p_ground_pa: float, t_amb_c: float) -> dict:
    return {"density_true": _relative_density(p_abs_pa, t_c, p_ground_pa, t_amb_c),
            "density_exaggerated": _relative_density(p_abs_pa, t_c, p_ground_pa, t_amb_c, PRESSURE_EXAGGERATION)}


def _reynolds(rho: float, velocity: float, size_m: float, t_c: float) -> float:
    return rho * velocity * size_m / air_viscosity(t_c)


def build_profile(p, op: OperatingPoint, t_amb_c: float) -> dict:
    """Stations, chimney slices, outside air and calculations for one operating point."""
    m = op.mass_flow_kg_s
    rho = op.rho_plate
    a_duct = _circle_area(p.duct_diameter_m)
    a_bore = _circle_area(p.plate_beta * p.duct_diameter_m)
    v_duct = m / (rho * a_duct)
    rho_ground_air = density(p.p_atm_pa, t_amb_c, AIR_MOLAR_MASS_G_MOL)

    def station(key: str, label: str, gauge_pa: float, velocity: float | None) -> dict:
        p_abs = p.p_atm_pa + gauge_pa
        return {"key": key, "label": label, "z_m": 0.0, "width_m": p.duct_diameter_m, "t_c": op.t_gas_c,
                "p_gauge_pa": gauge_pa, "p_abs_pa": p_abs, "rho": rho, "v_m_s": velocity,
                **_densities(p_abs, op.t_gas_c, p.p_atm_pa, t_amb_c)}

    stations = [
        station("kiln", "Kiln", p.kiln_gauge_pa, None),
        station("fan_in", "Fan inlet", op.p_fan_in_pa, v_duct),
        station("fan_out", "Fan outlet", op.p_fan_out_pa, v_duct),
        station("p1", "P1 (before plate)", op.p1_pa, v_duct),
        station("p2", "P2 (after plate)", op.p2_pa, v_duct),
        station("chimney_base", "Chimney base", op.p_chimney_base_pa, v_duct),
    ]

    # Up the chimney: pressure is reported relative to the outside air at the same height.
    state = chimney_state(p, m, op.t_gas_c, t_amb_c)
    slices = []
    gauge_local = op.p_chimney_base_pa
    for z, side, t_slice, rho_g, rho_o, p_out in zip(state.z_mid, state.side, state.t_gas_c, state.rho_gas,
                                                     state.rho_outside, state.p_outside_abs):
        friction = p.chimney_friction * state.dz / (2.0 * side ** 5 * rho_g) * m ** 2
        draft = G * (rho_o - rho_g) * state.dz
        mid_gauge = gauge_local + (draft - friction) / 2.0       # value at the middle of the slice
        gauge_local += draft - friction
        p_abs = p_out + mid_gauge
        slices.append({"z_m": z, "side_m": side, "t_c": t_slice, "rho": rho_g, "v_m_s": m / (rho_g * side ** 2),
                       "p_gauge_local_pa": mid_gauge, "p_abs_pa": p_abs,
                       **_densities(p_abs, t_slice, p.p_atm_pa, t_amb_c),
                       "outside": {"p_abs_pa": p_out, "rho": rho_o,
                                   **_densities(p_out, t_amb_c, p.p_atm_pa, t_amb_c)}})

    top_side = p.chimney_top_side_m
    v_exit = m / (state.rho_top * top_side ** 2)
    p_top_outside = barometric_pressure(p.p_atm_pa, p.chimney_height_m, t_amb_c)
    rho_top_outside = density(p_top_outside, t_amb_c, AIR_MOLAR_MASS_G_MOL)
    top = {"z_m": p.chimney_height_m, "side_m": top_side, "t_c": state.t_top_c, "rho": state.rho_top,
           "v_m_s": v_exit, "p_gauge_local_pa": gauge_local,     # = exit loss at steady state
           "outside": {"p_abs_pa": p_top_outside, "rho": rho_top_outside,
                       **_densities(p_top_outside, t_amb_c, p.p_atm_pa, t_amb_c)}}

    base_side = p.chimney_bottom_side_m
    rho_base = state.rho_gas[0]
    v_chimney_base = m / (rho_base * base_side ** 2)
    sources = {"kiln_gauge_pa": p.kiln_gauge_pa, "draft_pa": op.draft_pa, "fan_pa": op.fan_dp_pa}
    losses = {"kiln_pa": op.loss_kiln_pa, "fan_to_plate_pa": op.loss_fan_to_plate_pa,
              "plate_pa": op.loss_plate_permanent_pa, "restriction_pa": op.loss_restriction_pa,
              "chimney_friction_pa": op.loss_chimney_friction_pa, "exit_pa": op.loss_exit_pa}
    driving = op.draft_pa + max(op.fan_dp_pa, 0.0)
    q_fan = m / rho
    fan_air_power = q_fan * op.fan_dp_pa
    heat_carried = m * p.gas_cp_j_kg_k * (op.t_gas_c - t_amb_c)
    heat_lost = m * p.gas_cp_j_kg_k * (op.t_gas_c - state.t_top_c)

    calcs = {
        "mass_flow_kg_s": m,
        "mass_flow_t_h": m * 3.6,
        "q_plate_m3_s": op.q_m3_s,
        "velocity": {"duct_m_s": v_duct, "plate_bore_m_s": m / (rho * a_bore),
                     "kiln_opening_m_s": m / (rho * p.kiln_free_area_m2),
                     "chimney_base_m_s": v_chimney_base, "chimney_exit_m_s": v_exit},
        "reynolds": {"duct": _reynolds(rho, v_duct, p.duct_diameter_m, op.t_gas_c),
                     "chimney_base": _reynolds(rho_base, v_chimney_base, base_side, state.t_gas_c[0]),
                     "chimney_top": _reynolds(state.rho_top, v_exit, top_side, state.t_top_c)},
        "budget": {"sources": sources, "losses": losses,
                   "imbalance_pa": sum(sources.values()) - sum(losses.values())},
        "draft_share": op.draft_pa / driving if driving > 0.0 else None,
        "fan_air_power_w": fan_air_power,
        "fan_shaft_power_w": fan_air_power / p.fan_efficiency if fan_air_power > 0.0 else 0.0,
        "heat_carried_w": heat_carried,
        "heat_lost_chimney_w": heat_lost,
        "residence_time_chimney_s": sum(state.dz / s["v_m_s"] for s in slices) if m > 0.0 else None,
        "viscosity_note": "Reynolds numbers use the viscosity of air (Sutherland's formula) as an approximation.",
    }

    return {
        "stations": stations,
        "chimney": slices,
        "top": top,
        "ground": {"t_amb_c": t_amb_c, "p_abs_pa": p.p_atm_pa, "rho": rho_ground_air,
                   "density_true": 1.0, "density_exaggerated": 1.0},
        "geometry": {"height_m": p.chimney_height_m, "bottom_side_m": base_side, "top_side_m": top_side,
                     "duct_diameter_m": p.duct_diameter_m, "plate_beta": p.plate_beta},
        "pressure_exaggeration": PRESSURE_EXAGGERATION,
        "calcs": calcs,
    }

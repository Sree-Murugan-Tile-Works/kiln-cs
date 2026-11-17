"""
Parameters of the whole-kiln model. Like ``sim.params`` these are placeholders unless the comment
names a source; they give the right behaviour, not calibrated numbers.

Sources named below:
  * "Kiln-Domain"  -- VelKilnMaster ``docs/Kiln-Domain.md`` (Room Unit Geometry and Load, Firing Plan,
                      Process Measures), read 2026-11-16;
  * "Coldstart"    -- VelKilnMaster ``docs/Kiln-Coldstart-Firing.md`` (calibration and inputs).

Every value marked "TUNED PLACEHOLDER" was adjusted on 2026-11-17 (build stage H) until a run from
a plausible start settles into a travelling wave with a peak of roughly 850-950 degC and an exhaust
of roughly 100-180 degC at 380 rpm. They are not measurements and must be replaced by calibration
(build stage J).
"""
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class KilnParams:
    # ---------------------------------------------------------------- gas path (stage G)
    # Resistance of one room unit to gas flowing along the tunnel, written as an equivalent opening.
    # 1.6 m2 per loaded unit makes the whole kiln look like about 0.18 m2 to the fan, the value
    # stage 1 needed to reproduce the site reading.
    setting_free_area_m2: float = 1.6      # unit loaded with tiles
    empty_free_area_m2: float = 5.0        # unit in the handling zone (treated as empty)
    flue_free_area_m2: float = 3.0         # interconnecting flue unit (no tiles)
    door_open_area_m2: float = 1.5         # fully open door
    door_part_area_m2: float = 0.3         # part-open door
    leak_area_m2: float = 0.0005           # air leaking into each closed unit (brickwork, porthole covers)
    damper_bore_m: float = 0.45            # ring bore of the damper (VelKilnMaster: 450 mm, approximate)
    damper_curtain_factor: float = 0.7     # how much of the ring-times-lift curtain is open with a cone in it
    porthole_area_m2: float = 0.02         # extra opening on a firing unit while its portholes are open for a charge

    # ---------------------------------------------------------------- tiles (stage H)
    tile_dry_kg: float = 7000.0            # Kiln-Domain: 7600 kg wet, 6900-7100 kg fired, per room unit
    tile_water_kg: float = 600.0           # Kiln-Domain: 500-690 kg of water driven off per room unit
    tile_cp_j_kg_k: float = 900.0          # placeholder: a usual value for fired clay
    latent_heat_j_kg: float = 2.26e6       # latent heat of evaporation of water at 100 degC (physics)
    boiling_c: float = 100.0               # tiles hold here while their water evaporates (simplification)

    # ---------------------------------------------------------------- brickwork and heat transfer (stage H)
    # Coldstart quotes about 25 t of brick per room unit. The fire takes about a week to come round, which
    # is long enough for heat to soak deep into the brick, so the lump uses all of it. With much less
    # (9 t was tried) the cooling air strips the ware bare and the hottest point sits at the fire front.
    brick_kg: float = 25000.0              # TUNED PLACEHOLDER (order of magnitude from Coldstart): brick per room unit
    brick_cp_j_kg_k: float = 1000.0        # placeholder: a usual value for fireclay brick
    tile_ha_w_k: float = 1500.0            # TUNED PLACEHOLDER: gas-to-tile h*A (about 420 m2 of tile face)
    brick_ha_w_k: float = 1500.0           # TUNED PLACEHOLDER: gas-to-brick h*A (17.8 m2 enclosure, with radiation)
    wall_ua_w_k: float = 22.0              # TUNED PLACEHOLDER: brick-to-ambient loss through arch, walls and floor
    gas_cp_j_kg_k: float = 1100.0          # same as the stage 1 default for flue gas

    # ---------------------------------------------------------------- fuel (stage H)
    fuel_per_firebox_kg: float = 724.0     # Kiln-Domain / Coldstart: firing plan Fp1(170), 724 kg over 160 charges
    plan_charge_count: int = 160           # the charge count the 724 kg belongs to
    fuel_lhv_ref_mj_kg: float = 14.3       # Coldstart: firewood net heating value at the reference moisture
    fuel_moisture_ref: float = 0.22        # Coldstart: about 22 % moisture (wet basis)
    water_latent_25c_mj_kg: float = 2.44   # physics: used to move the heating value to another moisture
    moisture_compensation: float = 1.0     # 1 = charge weight raised so wetter wood gives the same heat; 0 = no adjustment
    ramp_share: float = 0.20               # placeholder recipe shape: first 20 % of charges ramp up
    taper_share: float = 0.25              # placeholder recipe shape: last 25 % of charges taper down
    ramp_start_fraction: float = 0.45      # placeholder: first charge is this share of the full charge
    taper_end_fraction: float = 0.40       # placeholder: last charge is this share of the full charge
    burn_tau_s: float = 240.0              # placeholder: a charge burns out exponentially with this time constant
    skip_above_c: float = 1000.0           # placeholder: a charge is skipped if the point reads above this
    add_below_c: float = 630.0             # Kiln-Domain example "< 630 = +1 kg"
    add_kg: float = 1.0                    # Kiln-Domain example "< 630 = +1 kg"
    conditional_from_charge: int = 40      # placeholder: the "add" condition applies from this charge on (after the ramp)
    porthole_open_s: float = 60.0          # placeholder: portholes stay open this long for each charge

    # ---------------------------------------------------------------- operations and reading (stage H)
    reload_delay_ru: float = 2.0           # placeholder: tiles are replaced this far into the handling zone
    thermocouple_tau_s: float = 600.0      # placeholder: the "point" reading lags the gas like a sheathed thermocouple

    def __post_init__(self):
        for f in fields(self):
            if getattr(self, f.name) < 0:
                raise ValueError(f"{f.name} must not be negative")
        if self.plan_charge_count <= 0 or self.burn_tau_s <= 0 or self.thermocouple_tau_s <= 0:
            raise ValueError("charge count, burn time constant and thermocouple lag must be positive")
        if self.tile_dry_kg <= 0 or self.brick_kg <= 0 or self.gas_cp_j_kg_k <= 0:
            raise ValueError("tile mass, brick mass and gas specific heat must be positive")
        if not 0.0 <= self.fuel_moisture_ref < 1.0:
            raise ValueError("reference fuel moisture must be a fraction below 1")
        if self.ramp_share + self.taper_share > 1.0:
            raise ValueError("ramp and taper together cannot be more than the whole plan")


INCH_M = 0.0254

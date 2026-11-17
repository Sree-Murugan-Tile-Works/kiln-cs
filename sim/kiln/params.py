"""
Parameters of the whole-kiln model. Like ``sim.params`` these are placeholders unless the comment
names a source; they give the right behaviour, not calibrated numbers.
"""
from dataclasses import dataclass


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


INCH_M = 0.0254

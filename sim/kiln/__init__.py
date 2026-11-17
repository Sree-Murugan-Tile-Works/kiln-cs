"""
Whole-kiln simulation (stage 2): the ring of 60 fireboxes behind the fan.

Stage 1 (``sim.plant``) treats the kiln as one opening and one gas temperature. This package
replaces that box step by step:

  * ``layout``   -- the 60 fireboxes: which have a door, a damper, a platform of tiles;
  * ``schedule`` -- the "train" of zones moving round the ring: fire, dampers, doors;
  * ``network``  -- gas flow through the ring and the dampers, joined to the stage 1 fan;
  * ``fuel``     -- the firing plan recipe, conditional charges, moisture, burn-out;
  * ``thermal``  -- gas, tile and brick temperatures and tile drying for one step;
  * ``kilnsim``  -- ``KilnSim``, the driver that steps all of the above in time.

Kiln facts come from the VelKilnMaster repository (``docs/Kiln-Domain.md``), read 2026-11-16.
Dev-machine only; nothing here touches hardware.
"""

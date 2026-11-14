"""Gas property helpers (ideal gas). SI units; temperatures in degC at the interface."""

R_UNIVERSAL = 8.314462618       # J/mol/K
G = 9.80665                     # m/s2
KELVIN = 273.15
AIR_MOLAR_MASS_G_MOL = 28.96    # dry air, used for the ambient air outside the chimney
FAN_REF_DENSITY = 1.2           # kg/m3, density the fan curve is quoted at (standard air)


def density(p_abs_pa: float, t_c: float, molar_mass_g_mol: float) -> float:
    """Ideal-gas density in kg/m3."""
    return p_abs_pa * (molar_mass_g_mol / 1000.0) / (R_UNIVERSAL * (t_c + KELVIN))

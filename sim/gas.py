"""Gas property helpers (ideal gas). SI units; temperatures in degC at the interface."""
import math

R_UNIVERSAL = 8.314462618       # J/mol/K
G = 9.80665                     # m/s2
KELVIN = 273.15
AIR_MOLAR_MASS_G_MOL = 28.96    # dry air, used for the ambient air outside the chimney
FAN_REF_DENSITY = 1.2           # kg/m3, density the fan curve is quoted at (standard air)

# Sutherland's formula for the viscosity of AIR. Flue gas is mostly nitrogen, so this is used as an
# approximation for the gas too (only the Reynolds numbers shown in the GUI depend on it).
SUTHERLAND_MU_REF = 1.716e-5    # Pa.s at SUTHERLAND_T_REF
SUTHERLAND_T_REF = 273.15       # K
SUTHERLAND_S = 110.4            # K


def density(p_abs_pa: float, t_c: float, molar_mass_g_mol: float) -> float:
    """Ideal-gas density in kg/m3."""
    return p_abs_pa * (molar_mass_g_mol / 1000.0) / (R_UNIVERSAL * (t_c + KELVIN))


def barometric_pressure(p_ground_pa: float, height_m: float, t_c: float) -> float:
    """
    Outside air pressure at a height above the ground (isothermal barometric formula).

    About 440 Pa below ground pressure at 38 m and 25 degC. This small fall is what the chimney
    gas has to be lighter than for natural draft to exist.
    """
    molar_mass = AIR_MOLAR_MASS_G_MOL / 1000.0
    return p_ground_pa * math.exp(-molar_mass * G * height_m / (R_UNIVERSAL * (t_c + KELVIN)))


def air_viscosity(t_c: float) -> float:
    """Dynamic viscosity of air in Pa.s (Sutherland's formula)."""
    t_k = t_c + KELVIN
    return (SUTHERLAND_MU_REF * (t_k / SUTHERLAND_T_REF) ** 1.5
            * (SUTHERLAND_T_REF + SUTHERLAND_S) / (t_k + SUTHERLAND_S))

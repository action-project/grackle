########################################################################
#
# Python wrapper convenience functions
#
#
# Copyright (c) 2013, Enzo/Grackle Development Team.
#
# Distributed under the terms of the Enzo Public Licence.
#
# The full license is in the file LICENSE, distributed with this
# software.
########################################################################

import numpy as np
import sys

from pygrackle.fluid_container import \
    FluidContainer

from pygrackle.utilities.physical_constants import \
    mass_hydrogen_cgs, \
    sec_per_Myr

def check_convergence(fc1, fc2, fields=None, tol=0.01):
    "Check for fields to be different by less than tol."

    if fields is None:
        fields = fc1.density_fields
    max_field = None
    max_val = 0.0
    for field in fields:
        if field not in fc2:
            continue
        convergence = np.max(np.abs(fc1[field] - fc2[field]) / fc1[field])
        if convergence > max_val:
            max_val = convergence
            max_field = field
    if np.any(max_val > tol):
        sys.stderr.write("max change - %5s: %.10e." % (max_field, max_val))
        return False
    return True

def setup_fluid_container(my_chemistry,
                          density=mass_hydrogen_cgs,
                          temperature=None,
                          state="ionized",
                          metal_mass_fraction=None,
                          dust_to_gas_ratio=None,
                          converge=False,
                          tolerance=0.01,
                          max_iterations=10000):
    """
    Initialize a fluid container using settings from a chemistry_data object.

    By default, initialize with a constant density and smoothly increasing
    temperature from 1e4 K to 1e9 K. Optionally, iterate the chemistry solver
    until the species fractions converge.

    The state of the gas can be set to "neutral" or "ionized" initialize the
    gas as fully neutral or fully ionized. Molecular fractions are always
    initialized to effectively zero.

    Parameters
    ---------
    my_chemistry : chemistry_data
        Struct of Grackle runtime parameters.
    density : optional, float
        The density in CGS for all elements in the fluid container.
        Default: 1 hydrogen mass per cm^3 (i.e., ~1.67e-24 g/cm^3)
    temperature : optional, array of floats
        Array of temperature values in K.
    state : optional, string
        The initial ionization state of the gas. Either "neutral" to set
        all ionized species to effectively zero or "ionized" to set all
        neutral species to effectively zero.
    metal_mass_fraction : optional, float
        The mass fraction of gas in gas-phase metals.
        Default: 1e-20.
    dust_to_gas_ratio : optional, float
        The ratio of dust mass density to total gas density.
        Default: 1e-20.
    converge : optional, bool
        If True, iterate the solver until the chemical species reach
        equilibrium for the given temperatures.
        Default: False.
    tolerance : optional, float
        The maximum fractional change in a species density allowed to
        be considered converged.
        Default: 0.01.
    max_iterations : optional, int
        The maximum iterations to try for reaching convergence.
        Default: 10000.

    Returns
    -------
    fc : FluidContainer
        A fully initialized FluidContainer object.
    """

    rval = my_chemistry.initialize()
    if rval == 0:
        raise RuntimeError("Failed to initialize chemistry_data.")

    tiny_number = 1e-20
    if metal_mass_fraction is None:
        metal_mass_fraction = tiny_number
    if dust_to_gas_ratio is None:
        dust_to_gas_ratio = tiny_number
    if temperature is None:
        n_points = 200
        temperature = np.logspace(4, 9, n_points)
    else:
        n_points = temperature.size

    fc = FluidContainer(my_chemistry, n_points)
    fh = my_chemistry.HydrogenFractionByMass
    d2h = my_chemistry.DeuteriumToHydrogenRatio

    metal_free = 1 - metal_mass_fraction
    H_total = fh * metal_free
    He_total = (1 - fh) * metal_free
    # someday, maybe we'll include D in the total
    D_total = H_total * d2h

    fc_density = density / my_chemistry.density_units
    tiny_density = tiny_number * fc_density

    state_vals = {
        "density": fc_density,
        "metal": metal_mass_fraction * fc_density,
        "dust": dust_to_gas_ratio * fc_density
    }

    if state == "neutral":
        state_vals["HI"] = H_total * fc_density
        state_vals["HeI"] = He_total * fc_density
        state_vals["DI"] = D_total * fc_density
    elif state == "ionized":
        state_vals["HII"] = H_total * fc_density
        state_vals["HeIII"] = He_total * fc_density
        state_vals["DII"] = D_total * fc_density
        # ignore HeII since we'll set it to tiny
        state_vals["de"] = state_vals["HII"] + state_vals["HeIII"] / 2
    else:
        raise ValueError("State must be either neutral or ionized.")

    for field in fc.density_fields:
        fc[field][:] = state_vals.get(field, tiny_density)

    fc.calculate_mean_molecular_weight()
    fc["energy"] = temperature / \
        fc.chemistry_data.temperature_units / \
        fc["mu"] / (my_chemistry.Gamma - 1.0)
    fc["x-velocity"][:] = 0.0
    fc["y-velocity"][:] = 0.0
    fc["z-velocity"][:] = 0.0

    fc_last = fc.copy()

    my_time = 0.0
    i = 0
    while converge and i < max_iterations:
        fc.calculate_cooling_time()
        dt = 0.1 * np.abs(fc["cooling_time"]).min()
        sys.stderr.write("t: %.3f Myr, dt: %.3e Myr, " % \
                         ((my_time * my_chemistry.time_units / sec_per_Myr),
                          (dt * my_chemistry.time_units / sec_per_Myr)))
        for field in fc.density_fields:
            fc_last[field] = np.copy(fc[field])
        fc.solve_chemistry(dt)
        fc.calculate_mean_molecular_weight()
        fc["energy"] = temperature / \
            fc.chemistry_data.temperature_units / fc["mu"] / \
            (my_chemistry.Gamma - 1.0)
        converged = check_convergence(fc, fc_last, tol=tolerance)
        if converged:
            sys.stderr.write("\n")
            break
        sys.stderr.write("\r")
        my_time += dt
        i += 1

    if i >= max_iterations:
        sys.stderr.write("ERROR: solver did not converge in %d iterations.\n" %
                         max_iterations)
        return None

    return fc

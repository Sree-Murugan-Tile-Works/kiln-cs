import pytest

from sim.params import (PARAM_SPECS, SPEC_BY_NAME, Params, make_params, params_to_dict,
                        specs_as_dicts)


def test_names_are_unique():
    names = [s.name for s in PARAM_SPECS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("spec", PARAM_SPECS, ids=lambda s: s.name)
def test_default_is_inside_range_and_step_is_positive(spec):
    assert spec.min <= spec.default <= spec.max
    assert spec.step > 0
    assert spec.help and spec.unit is not None


def test_defaults_match_registry():
    p = make_params()
    for name, spec in SPEC_BY_NAME.items():
        assert getattr(p, name) == pytest.approx(spec.default)


def test_override_is_applied():
    assert make_params({"chimney_height_m": 40}).chimney_height_m == 40


def test_unknown_parameter_rejected():
    with pytest.raises(ValueError, match="Unknown"):
        make_params({"not_a_param": 1})


def test_out_of_range_rejected():
    with pytest.raises(ValueError, match="outside"):
        make_params({"chimney_height_m": 1000})


def test_round_trip_and_gui_specs():
    p = make_params({"kp": 2.0})
    assert params_to_dict(p)["kp"] == 2.0
    assert len(specs_as_dicts()) == len(PARAM_SPECS)
    assert isinstance(p, Params)

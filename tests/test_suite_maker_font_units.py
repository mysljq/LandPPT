"""Forward/inverse font sizes, slide fit and exporter quantization."""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def units(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'skills/clawpartner-suite-maker/scripts'))
    return importlib.import_module('font_units')


@pytest.mark.parametrize('px,pt', [(16,9),(24,13.5),(32,18),(48,27),(64,36),(96,54),(14,7.9)])
def test_project_export_and_rounded_inverse(units,px,pt):
    assert units.exporter_px_to_points(px)==pt
    inverse=units.exporter_points_to_px(pt)
    lower,upper=inverse['possible_original_px_interval']
    assert lower-1e-12<=px<upper
    assert abs(inverse['font_px']-px)<=.05/.5625+1e-12
    assert units.pptx_points_to_px(pt,9144000,5143500)==pytest.approx(inverse['font_px'])


def test_native_960pt_width_is_a_different_scale(units):
    assert units.pptx_points_to_px(48,12192000,6858000)==pytest.approx(64)
    assert units.pptx_points_to_px(48,9144000,5143500)==pytest.approx(85+1/3)


def test_other_root_and_square_canvas_fit(units):
    assert units.exporter_px_to_points(48,960,540)==36
    assert units.exporter_points_to_px(36,960,540)['font_px']==48
    # Square HTML fits by height; imported PPTX is rectangular and letterboxed.
    assert units.exporter_px_to_points(48,720,720)==27


def test_half_point_rounding_matches_javascript(units):
    assert units.exporter_px_to_points(7.85/.5625)==7.9

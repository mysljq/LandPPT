"""Physical font conversion and inverse of the audited HTML exporter.

The exporter uses 96 CSS px/in, 72 pt/in, a 10 x 5.625 in slide,
uniform fit scaling and JS Math.round to one decimal point.
No repository runtime dependency; arbitrary PPTX uses its actual EMU dimensions.
"""
from __future__ import annotations

import argparse
import json
import math

EMU_PER_POINT = 12700
EMU_PER_INCH = 914400
CSS_PPI = 96
POINTS_PER_INCH = 72
EXPORT_SLIDE_INCHES = (10, 5.625)


def pptx_px_per_point(slide_width_emu, slide_height_emu, width_px=1280, height_px=720):
    if min(slide_width_emu, slide_height_emu, width_px, height_px) <= 0:
        raise ValueError('Slide and target dimensions must be positive')
    return EMU_PER_POINT * min(width_px / slide_width_emu, height_px / slide_height_emu)


def pptx_points_to_px(points, slide_width_emu, slide_height_emu, width_px=1280, height_px=720):
    if points <= 0:
        raise ValueError('Font size must be positive')
    return points * pptx_px_per_point(slide_width_emu, slide_height_emu, width_px, height_px)


def exporter_point_factor(root_width_px=1280, root_height_px=720):
    if min(root_width_px, root_height_px) <= 0:
        raise ValueError('HTML root dimensions must be positive')
    # Match the exporter's multiplication order, including IEEE-754 rounding.
    scale = min(EXPORT_SLIDE_INCHES[0] / (root_width_px * (1 / CSS_PPI)),
                EXPORT_SLIDE_INCHES[1] / (root_height_px * (1 / CSS_PPI)))
    return POINTS_PER_INCH / CSS_PPI * scale


def exporter_px_to_points(font_px, root_width_px=1280, root_height_px=720):
    if font_px <= 0:
        raise ValueError('Font size must be positive')
    # JS Math.round for positive values, not Python's ties-to-even round().
    return math.floor(font_px * exporter_point_factor(root_width_px, root_height_px) * 10 + .5) / 10


def exporter_points_to_px(points, root_width_px=1280, root_height_px=720):
    if points <= 0:
        raise ValueError('Font size must be positive')
    factor = exporter_point_factor(root_width_px, root_height_px)
    return {'font_px': points / factor,
            'possible_original_px_interval': [(points - .05) / factor, (points + .05) / factor],
            'interval_bounds': '[lower, upper); exporter rounding loses the exact original CSS size',
            'point_factor': factor}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    size = parser.add_mutually_exclusive_group(required=True)
    size.add_argument('--font-pt', type=float)
    size.add_argument('--font-px', type=float)
    parser.add_argument('--root-width', type=float, default=1280)
    parser.add_argument('--root-height', type=float, default=720)
    parser.add_argument('--slide-width-emu', type=float)
    parser.add_argument('--slide-height-emu', type=float)
    args = parser.parse_args()
    if args.slide_width_emu is not None or args.slide_height_emu is not None:
        if args.font_pt is None or args.slide_width_emu is None or args.slide_height_emu is None:
            parser.error('Physical PPTX conversion requires --font-pt and both EMU dimensions')
        result = {'font_px': pptx_points_to_px(args.font_pt, args.slide_width_emu, args.slide_height_emu, args.root_width, args.root_height), 'profile': 'physical-pptx'}
    elif args.font_px is not None:
        result = {'font_pt': exporter_px_to_points(args.font_px, args.root_width, args.root_height), 'profile': 'project-export'}
    else:
        result = exporter_points_to_px(args.font_pt, args.root_width, args.root_height) | {'profile': 'project-export-inverse'}
    print(json.dumps(result))

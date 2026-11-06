"""Deterministic, pre-generation slide capacity planning. No browser or model calls.

CSS bounds are best-effort: literal px/%/simple calc() values are supported;
dynamic layouts fall back to conservative space instead of the full canvas.
The existing rendered DOM check remains the final authority.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from html import escape
from typing import Any

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class ContentArea:
    width: float = 1060
    height: float = 480
    source: str = "conservative_default"


@dataclass(frozen=True)
class TypographyProfile:
    name: str
    label: str
    sizes: tuple[int, ...]
    line_height: float
    gap: int
    padding: int
    heading_size: int


PROFILES = (
    TypographyProfile("sparse", "稀疏", (26, 24), 1.45, 24, 16, 30),
    TypographyProfile("balanced", "适中", (24, 22), 1.4, 16, 12, 28),
    TypographyProfile("dense", "密集", (22, 20, 18), 1.3, 10, 8, 26),
)
SPARSE_MAX_RATIO = .4
BALANCED_MAX_RATIO = .75


@dataclass(frozen=True)
class DensityPlan:
    area: ContentArea
    profile: TypographyProfile
    font_size: int
    columns: int
    column_width: float
    text_height: float
    required_height: float
    reference_ratio: float
    media_height: float
    point_count: int
    weighted_units: float
    longest_point_units: float
    over_capacity: bool

    def to_prompt(self) -> str:
        source = "模板 CSS 可解析尺寸" if self.area.source == "template_css" else "保守估算；需以实际骨架校核"
        status = "预估超容量" if self.over_capacity else "预计可容纳，仍需最终换行校核"
        media = f"\n- 为已提供的图片/图表/表格暂预留 {self.media_height:.0f}px 高的横向区域。" if self.media_height else ""
        warning = (
            "\n- **预估超容量**：当前最紧凑建议仍不足以容纳；优先重排或合并重复表达，必要时拆页。"
            "不要继续缩小文字硬塞、删掉关键事实或隐藏裁切；最终以 DOM 检查为准。"
            if self.over_capacity else ""
        )
        return (
            "**本页正文容量提示（本地密度计算，不是强制字号下限）**\n"
            f"- 正文内空间 {self.area.width:.0f}×{self.area.height:.0f}px，依据：{source}；"
            f"{self.point_count} 个文本单元，约 {self.weighted_units:.0f} 个全角等效字符，"
            f"最长单元约 {self.longest_point_units:.0f}；参考占用率 {self.reference_ratio:.0%}。\n"
            f"- 密度档：{self.profile.label}。正文建议 {self.font_size}px，行高 {self.profile.line_height:g}，"
            f"模块 gap {self.profile.gap}px，内边距参考 {self.profile.padding}px，"
            f"正文内小标题参考 {min(self.profile.heading_size, self.font_size + 4)}px。\n"
            f"- 候选布局：{self.columns} 列，每列外宽约 {self.column_width:.0f}px；"
            f"按最长单元换行及逐行最大高度预算约 {self.required_height:.0f}px，"
            f"文字可用高度约 {self.text_height:.0f}px，{status}。"
            f"{media}\n"
            "- 字号、行高、间距是一组起始参数，只有沿用上述列宽/媒体预留时此预算才成立；"
            "改换布局后必须重新核算。保留模板页头页脚，不把正文区扩成整个画布。\n"
            "- 本页分档优先于通用正文建议，只作用于主内容区，页头与页码锁定令牌保持不变。"
            "候选列数可用于无外框文字分区，不要求等大卡片；卡片随内容定高，网格按需 align-items:start。\n"
            "- 编号与小标题同行，正文不额外缩进；图文采用上下预留时才可直接使用本次文字高度预算。\n"
            "- 少量长段落按成段内容排版，不能当作短标签；不要额外扩写导语、标签、分组组头或复述侧栏。"
            "短内容页扩大信息体量并调整整页重心，不拉伸空卡片，不统一大字号。"
            f"{warning}"
        )


def _declarations(css: str) -> list[tuple[str, str, bool]]:
    result = []
    for item in css.split(';'):
        if ':' not in item:
            continue
        key, value = item.split(':', 1)
        important = bool(re.search(r'!\s*important\s*$', value, re.I))
        key = key.strip().lower()
        value = re.sub(r'!\s*important\s*$', '', value, flags=re.I).strip()
        if key in ('padding', 'inset', 'border-width'):
            values = _css_words(value)
            if len(values) == 1:
                values *= 4
            elif len(values) == 2:
                values *= 2
            elif len(values) == 3:
                values.append(values[1])
            if len(values) == 4:
                for side, v in zip(('top', 'right', 'bottom', 'left'), values):
                    prop = side if key == 'inset' else f'border-{side}-width' if key == 'border-width' else f'padding-{side}'
                    result.append((prop, v, important))
                continue
        if key == 'border' or key in ('border-top', 'border-right', 'border-bottom', 'border-left'):
            size = next((v for v in _css_words(value) if re.fullmatch(r'\d+(?:\.\d+)?px', v)), '0')
            for side in ('top', 'right', 'bottom', 'left') if key == 'border' else (key[7:],):
                result.append((f'border-{side}-width', size, important))
            continue
        result.append((key, value, important))
    return result


def _css_words(value: str) -> list[str]:
    words, current, depth = [], '', 0
    for char in value:
        depth += int(char == '(') - int(char == ')')
        if char.isspace() and depth == 0:
            if current:
                words.append(current)
                current = ''
        else:
            current += char
    if current:
        words.append(current)
    return words


def _length(value: str | None, base: float, variables: dict[str, str]) -> float | None:
    if not value:
        return None
    value = value.strip().lower()
    for _ in range(4):
        resolved = re.sub(r'var\((--[\w-]+)(?:,\s*([^()]+))?\)',
                          lambda m: variables.get(m[1], m[2] or 'unknown'), value)
        if resolved == value:
            break
        value = resolved
    match = re.fullmatch(r'(-?\d+(?:\.\d+)?)(px|%|vw|vh|rem|em)?', value)
    if match:
        number = float(match[1])
        factors = {'%': base / 100, 'px': 1, 'vw': 12.8, 'vh': 7.2,
                   'rem': float(variables.get('__root_font_px', 16)), 'em': float(variables.get('__font_px', 16))}
        return number * factors[match[2]] if match[2] in factors else 0 if number == 0 else None
    function = re.fullmatch(r'(min|max|clamp)\((.*)\)', value)
    if function:
        args = re.split(r',\s*(?![^()]*\))', function[2])
        values = [_length(v, base, variables) for v in args]
        if not values or any(v is None for v in values):
            return None
        if function[1] == 'clamp':
            return max(values[0], min(values[1], values[2])) if len(values) == 3 else None
        return min(values) if function[1] == 'min' else max(values)
    if value.startswith('calc(') and value.endswith(')'):
        expression = value[5:-1]
        tokens = re.findall(r'[+-]?\s*\d+(?:\.\d+)?(?:px|%|vw|vh|rem|em)', expression)
        if not tokens or re.sub(r'\s+', '', ''.join(tokens)) != re.sub(r'\s+', '', expression):
            return None
        values = [_length(re.sub(r'\s+', '', token).lstrip('+'), base, variables) for token in tokens]
        return sum(values) if all(v is not None for v in values) else None
    return None


def _edges(style: dict[str, str], key: str, base: float, variables: dict[str, str]) -> tuple[float, ...]:
    values = _css_words(style.get(key, '0'))
    numbers = [_length(v, base, variables) for v in values]
    numbers = [max(0, n or 0) for n in numbers]
    if len(numbers) == 1:
        numbers *= 4
    elif len(numbers) == 2:
        numbers *= 2
    elif len(numbers) == 3:
        numbers.append(numbers[1])
    if len(numbers) != 4:
        numbers = [0.0] * 4
    for i, side in enumerate(('top', 'right', 'bottom', 'left')):
        if f'{key}-{side}' in style:
            numbers[i] = max(0, _length(style[f'{key}-{side}'], base, variables) or 0)
    return tuple(numbers)


@lru_cache(maxsize=128)
def _area_from_html(html: str) -> ContentArea:
    # Suite skeletons are often fragments. Browsers supply an implicit html/body;
    # html.parser does not, which would otherwise lose :root variables and rules.
    if not re.search(r'<html\b', html, re.I):
        html = '<html><body>' + html + '</body></html>'
    soup = BeautifulSoup(html, 'html.parser')
    stage = None
    for selector in ('.suite-stage', '[data-content-layer]', 'main', '[role="main"]',
                     '.main-content', '.slide-content', '.content-layer', '.page-body'):
        stage = soup.select_one(selector)
        if stage is not None:
            break
    if stage is None:
        return ContentArea()
    ancestors = [node for node in reversed(list(stage.parents)) if getattr(node, 'name', '') != '[document]'] + [stage]
    styles: dict[int, dict[str, tuple]] = {id(node): {} for node in soup.find_all(True)}
    variables: dict[str, str] = {'__root_font_px': '16', '__font_px': '16'}
    order = 0
    for block in soup.find_all('style'):
        css = re.sub(r'/\*.*?\*/', '', block.get_text(), flags=re.S)
        # Ignore conditional/nested rules. Their actual applicability requires a browser.
        for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', css):
            selectors = match[1].strip()
            if '@' in selectors:
                continue
            # Nested at-rules are deliberately not interpreted as unconditional CSS.
            prefix = css[:match.start()]
            if prefix.count('{') != prefix.count('}'):
                continue
            declarations = _declarations(match[2])
            for selector in selectors.split(','):
                selector = selector.strip()
                specificity = (len(re.findall(r'#[\w-]+', selector)) * 100,
                               len(re.findall(r'\.[\w-]+|\[[^]]+\]|:[\w-]+', selector)),
                               len(re.findall(r'(?:^|[ >+~])([a-zA-Z][\w-]*)', selector)))
                try:
                    matched = soup.select(selector)
                except Exception:
                    continue
                for node in matched:
                    if id(node) not in styles:
                        continue
                    for key, value, important in declarations:
                        rank = (important, specificity, order)
                        old = styles[id(node)].get(key)
                        if old is None or rank >= old[0]:
                            styles[id(node)][key] = (rank, value)
                order += 1
    width, height = 1280.0, 720.0
    containing_width, containing_height = width, height
    known_w = known_h = False

    def style_for(node):
        styled = dict(styles.get(id(node), {}))
        for key, value, important in _declarations(node.get('style', '')):
            rank = (important, (1000, 0, 0), order)
            if key not in styled or rank >= styled[key][0]:
                styled[key] = (rank, value)
        return {k: v[1] for k, v in styled.items()}

    def flow_height(node, parent_w, parent_h, vars_, depth=0):
        style = style_for(node)
        if style.get('display') == 'none':
            return 0
        padding = _edges(style, 'padding', parent_w, vars_)
        margin = _edges(style, 'margin', parent_w, vars_)
        explicit = _length(style.get('height'), parent_h, vars_)
        if explicit is not None:
            return explicit + (0 if style.get('box-sizing') == 'border-box' else padding[0] + padding[2]) + margin[0] + margin[2]
        font = _length(style.get('font-size'), float(vars_['__font_px']), vars_)
        if font is None:
            font = float(vars_['__font_px']) * {'h1': 2, 'h2': 1.5, 'h3': 1.17}.get(node.name, 1)
        local_vars = {**vars_, '__font_px': str(max(1, font))}
        children = [c for c in node.find_all(recursive=False) if c.name not in ('style', 'script', 'link', 'meta')
                    and style_for(c).get('position') not in ('absolute', 'fixed')]
        inline = {'span', 'b', 'strong', 'em', 'i', 'a', 'small', 'br'}
        if children and depth < 4 and not all(c.name in inline for c in children):
            sizes = [flow_height(c, max(1, parent_w - padding[1] - padding[3]), parent_h, local_vars, depth + 1) for c in children]
            rows = max(sizes, default=0) if style.get('display') == 'flex' and style.get('flex-direction', 'row') == 'row' else sum(sizes)
        else:
            text = node.get_text(' ', strip=True)
            line = style.get('line-height', '1.2')
            line_px = float(line) * font if re.fullmatch(r'\d+(?:\.\d+)?', line) else _length(line, font, local_vars) or 1.2 * font
            rows = _lines(text, max(1, parent_w - padding[1] - padding[3]), font) * line_px if text else 0
        return rows + padding[0] + padding[2] + margin[0] + margin[2]

    for node in ancestors:
        style = style_for(node)
        parent_variables = dict(variables)
        variables.update({k: v for k, v in style.items() if k.startswith('--')})
        font = _length(style.get('font-size'), float(variables['__font_px']), variables)
        if font is not None and font > 0:
            variables['__font_px'] = str(font)
            if node.name == 'html':
                variables['__root_font_px'] = str(font)
        absolute = style.get('position') in ('absolute', 'fixed')
        if absolute:
            width, height = (1280.0, 720.0) if style.get('position') == 'fixed' else (containing_width, containing_height)
        w, h = _length(style.get('width'), width, variables), _length(style.get('height'), height, variables)
        auto_w, auto_h = w is None, h is None
        left, right = (_length(style.get(side), width, variables) for side in ('left', 'right'))
        top, bottom = (_length(style.get(side), height, variables) for side in ('top', 'bottom'))
        if absolute and left is not None and right is not None:
            w = width - left - right if w is None else min(w, width - left - right)
        if absolute and top is not None and bottom is not None:
            h = height - top - bottom if h is None else min(h, height - top - bottom)
        max_w = _length(style.get('max-width'), width, variables)
        max_h = _length(style.get('max-height'), height, variables)
        padding = _edges(style, 'padding', width, variables)
        borders = [_length(style.get(f'border-{side}-width'), width, variables) or 0
                   for side in ('top', 'right', 'bottom', 'left')]
        inner_w = min(width, w if w is not None else width, max_w if max_w is not None else width)
        inner_h = min(height, h if h is not None else height, max_h if max_h is not None else height)
        if absolute:
            inner_w = min(inner_w, width - (left or 0) - (right or 0))
            inner_h = min(inner_h, height - (top or 0) - (bottom or 0))
        if style.get('box-sizing') == 'border-box' or auto_w:
            inner_w -= padding[1] + padding[3] + borders[1] + borders[3]
        else:
            inner_w = min(inner_w, width - (left or 0) - (right or 0) - padding[1] - padding[3] - borders[1] - borders[3])
        if style.get('box-sizing') == 'border-box' or auto_h:
            inner_h -= padding[0] + padding[2] + borders[0] + borders[2]
        else:
            inner_h = min(inner_h, height - (top or 0) - (bottom or 0) - padding[0] - padding[2] - borders[0] - borders[2])
        if node is stage:
            known_w = w is not None or absolute and left is not None and right is not None
            known_h = h is not None
            if not known_w:
                inner_w = min(inner_w, 1060)
            if not known_h:
                # Flex/flow templates do not declare a body height. Reserve the
                # actual sibling header/footer and body padding before fallback.
                siblings = [s for s in node.parent.find_all(recursive=False) if s is not node
                            and s.name not in ('style', 'script', 'link', 'meta')]
                reserved = sum(flow_height(s, width, height, parent_variables) for s in siblings
                               if style_for(s).get('position') not in ('absolute', 'fixed'))
                overlay_top = overlay_bottom = 0
                for sibling in siblings:
                    ss = style_for(sibling)
                    if ss.get('position') not in ('absolute', 'fixed'):
                        continue
                    hints = ' '.join(sibling.get('class', [])) + ' ' + sibling.name
                    outer = flow_height(sibling, width, height, parent_variables)
                    if re.search(r'footer|page-number|page-num|^page\b', hints):
                        overlay_bottom = max(overlay_bottom, (_length(ss.get('bottom'), height, variables) or 0) + outer)
                    elif re.search(r'header|\bh1\b', hints):
                        overlay_top = max(overlay_top, (_length(ss.get('top'), height, variables) or 0) + outer)
                margin = _edges(style, 'margin', width, variables)
                available_flow = (height - reserved - overlay_top - overlay_bottom
                                  - padding[0] - padding[2] - borders[0] - borders[2]
                                  - margin[0] - margin[2])
                inner_h = min(inner_h, available_flow, 480)
        width, height = max(0, inner_w), max(0, inner_h)
        if style.get('position') in ('relative', 'absolute', 'fixed'):
            containing_width = width + padding[1] + padding[3]
            containing_height = height + padding[0] + padding[2]
    return ContentArea(round(width, 2), round(height, 2),
                       'template_css' if known_w and known_h else 'conservative_default')


def resolve_content_area(template_html: str = '', suite_context: str = '', *, page_title: str = '') -> ContentArea:
    """Suite skeleton takes priority over a separate, potentially unrelated template."""
    source = suite_context or template_html or ''
    blocks = re.findall(r'```html\s*(.*?)```', source, flags=re.I | re.S)
    if blocks:
        source = next((b for b in blocks if 'suite-stage' in b), blocks[0])
    if page_title:
        source = re.sub(r'\{\{\s*(?:page_title|main_heading)\s*\}\}',
                        lambda _: escape(str(page_title)), source)
    return _area_from_html(source)


def _plain(value: str) -> str:
    if re.search(r'<[a-zA-Z][^>]*>', value):
        value = BeautifulSoup(value, 'html.parser').get_text('\n')
    return re.sub(r'[^\S\n]+', ' ', value).strip()


def content_blocks(slide: dict[str, Any]) -> list[str]:
    def parts(value):
        if isinstance(value, str):
            text = _plain(value)
            return [text] if text else []
        if isinstance(value, (list, tuple)):
            return [p for item in value for p in parts(item)]
        if isinstance(value, dict):
            # Only content-bearing fields; URLs, notes and metadata are not rendered text.
            title = '\n'.join(parts(value.get('title')))
            values = [value[k] for k in ('text', 'content', 'description', 'body', 'items') if k in value]
            body = '\n'.join(p for v in values for p in parts(v))
            text = title + '：' + body if title and body else title or body
            return [text] if text else []
        return []
    blocks = parts(slide.get('content_points')) or parts(slide.get('bullet_points'))
    body = parts(slide.get('content'))
    if body:
        joined = ''.join(body)
        if blocks and all(b in joined for b in blocks):
            blocks = body
        else:
            blocks += [b for b in body if b not in blocks]
    if not blocks:
        blocks = parts(slide.get('description'))
    return blocks


def text_units(text: str) -> float:
    def unit(char):
        if char == '\n' or unicodedata.combining(char) or char in ('\u200d', '\ufe0f'):
            return 0
        if char.isspace():
            return .33
        if unicodedata.east_asian_width(char) in ('W', 'F'):
            return 1
        if char in 'MW@':
            return .95
        if char in 'mw':
            return .85
        return .68 if char.isupper() else .55
    return sum(unit(c) for c in text)


def _lines(text: str, width: float, font: float) -> int:
    # 8% reserve covers word boundaries and font metric differences.
    capacity = max(.1, width / font * .92)
    return sum(max(1, math.ceil(text_units(line) / capacity)) for line in text.split('\n'))


def _estimate(blocks: list[str], area_width: float, columns: int,
              profile: TypographyProfile, font: int) -> tuple[float, float]:
    column = (area_width - (columns - 1) * profile.gap) / columns
    width = max(1, column - profile.padding * 2)
    heights = []
    for block in blocks:
        match = re.match(r'^([^：:\n]{1,30})[：:]\s*(.+)$', block, re.S)
        if match and text_units(match[1]) <= 24:
            heading, body = match.groups()
            heading_font = min(profile.heading_size, font + 4)
            height = _lines(heading, max(1, width - font - 8), heading_font) * heading_font * 1.2 + 6
        else:
            body, height = block, 0
        heights.append(height + _lines(body, width, font) * font * profile.line_height + profile.padding * 2)
    rows = [max(heights[i:i + columns]) for i in range(0, len(heights), columns)]
    return sum(rows) + profile.gap * max(0, len(rows) - 1), column


def _media_height(slide: dict[str, Any], area: ContentArea) -> float:
    images_info = slide.get('images_info') or {}
    images = slide.get('images') or (images_info.get('images') if isinstance(images_info, dict) else None)
    collection = slide.get('images_collection')
    slide_type = str(slide.get('slide_type') or slide.get('type') or '').lower()
    has_images = bool(images or slide.get('images_summary') or getattr(collection, 'total_count', 0)) or slide_type == 'image'
    has_chart = bool(slide.get('chart_data')) or slide_type == 'chart'
    table = slide.get('table_data') or slide.get('table')
    if not (has_images or has_chart or table or slide_type == 'table'):
        return 0
    # Source image dimensions are NOT display dimensions. Never reserve intrinsic 4K height.
    explicit = slide.get('media_display_height')
    if isinstance(explicit, (int, float)) and math.isfinite(explicit) and explicit >= 0:
        return float(explicit)
    if table:
        rows = table.get('rows') if isinstance(table, dict) else table
        if isinstance(rows, list):
            return (len(rows) + 1) * 30 + 16
    return area.height * (.4 if has_chart or table or slide_type == 'table' else .35)


def plan_content_density(slide: dict[str, Any], template_html: str = '', suite_context: str = '') -> DensityPlan | None:
    blocks = content_blocks(slide)
    if not blocks:
        return None
    area = resolve_content_area(template_html, suite_context, page_title=slide.get('title') or '')
    media = _media_height(slide, area)
    height = max(0, area.height - media - (16 if media else 0))
    choices = [1]
    for columns in (2, 3):
        if len(blocks) >= columns and (area.width - 16 * (columns - 1)) / columns >= 300:
            choices.append(columns)
    reference = min(_estimate(blocks, area.width, c, PROFILES[1], 24)[0] for c in choices)
    ratio = reference / max(1, height)
    start = 0 if ratio <= SPARSE_MAX_RATIO else 1 if ratio <= BALANCED_MAX_RATIO else 2
    selected = None
    for profile in PROFILES[start:]:
        for font in profile.sizes:
            estimates = [(c, *_estimate(blocks, area.width, c, profile, font)) for c in choices]
            fitting = [item for item in estimates if item[1] <= height * .95]
            if fitting:
                selected = (profile, font, min(fitting, key=lambda item: item[0]))
                break
        if selected:
            break
    if selected is None:
        profile, font = PROFILES[-1], PROFILES[-1].sizes[-1]
        estimates = [(c, *_estimate(blocks, area.width, c, profile, font)) for c in choices]
        selected = profile, font, min(estimates, key=lambda item: item[1])
    profile, font, (columns, needed, column) = selected
    units = [text_units(b) for b in blocks]
    return DensityPlan(area, profile, font, columns, round(column, 2), round(height, 2), round(needed, 2),
                       round(ratio, 4), round(media, 2), len(blocks), round(sum(units), 2), round(max(units), 2),
                       needed > height or area.width <= 0 or height <= 0)

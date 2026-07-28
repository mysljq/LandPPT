"""Aesthetic Pre-Flight Checker.

机械化的 HTML 审美预检，借鉴 taste-skill 的 Pre-Flight Check 方法论。
全部为确定性检测（正则/简单解析），不调用 LLM、不启动浏览器，
用于在结构校验通过后给到重试链路一个审美维度的失败信号。

设计原则：
- 健壮：HTML 为空、无 style、解析异常 → 返回空列表，绝不抛错阻塞主流程。
- 软硬分级：em-dash / 纯黑纯白 / 多 accent 视为 hard fail（触发重试）；
  圆角不一致、三等分卡片视为 warning（记日志、不强制重试，避免误杀）。
- 尽力而为：单页 HTML 无法做严格宪法比对，仅统计页内"独特色是否唯一"。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


class AestheticPreFlightChecker:
    """对单页幻灯片 HTML 做审美维度的机械化预检。

    返回 (hard_fails, warnings) 两个列表。空列表表示通过。
    """

    # 纯黑纯白（不区分大小写、带词边界避免误伤 #0000000 这种）
    _PURE_BW_RE = re.compile(r"#(?:000000|FFFFFF)\b", re.IGNORECASE)
    # em-dash / en-dash 作为设计元素出现的指纹
    _DASH_RE = re.compile(r"[—–]")
    # 6 位 hex 颜色
    _HEX_RE = re.compile(r"#([0-9A-Fa-f]{6})\b")
    # border-radius 数值
    _RADIUS_RE = re.compile(r"border-radius\s*:\s*([0-9]+(?:\.\d+)?)(px|rem|%)", re.IGNORECASE)
    # 三列网格 + card/item 等份排布
    _GRID3_RE = re.compile(r"(grid-cols-3|grid-template-columns\s*:\s*repeat\(\s*3)", re.IGNORECASE)
    # 中性灰族阈值：饱和度低于该值视为灰族，不参与 accent 比对
    _NEUTRAL_SAT_THRESHOLD = 0.08

    @staticmethod
    def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    @staticmethod
    def _is_neutral(rgb: Tuple[int, int, int]) -> bool:
        """近似判定灰族：三通道差异极小。"""
        r, g, b = rgb
        sat = (max(r, g, b) - min(r, g, b)) / 255.0
        return sat <= AestheticPreFlightChecker._NEUTRAL_SAT_THRESHOLD

    # 页头/页脚令牌守恒相关正则
    _HEADER_LOCK_RE = re.compile(
        r"===HEADER_LOCK===" r"(.*?)(?:===\w+===|\Z)", re.IGNORECASE | re.DOTALL
    )
    _FOOTER_LOCK_RE = re.compile(
        r"===FOOTER_LOCK===" r"(.*?)(?:===\w+===|\Z)", re.IGNORECASE | re.DOTALL
    )
    _HEADER_LINE_RE = re.compile(
        r"(?P<key>font_family|font_size|font_weight|color|background|padding|icon)\s*:\s*(?P<val>.+)"
    )
    _FOOTER_LINE_RE = re.compile(
        r"(?P<key>font_family|font_size|font_weight|color)\s*:\s*(?P<val>.+)"
    )
    # 捕获内联样式里的属性值（容忍值末尾无分号、引号边界、行尾）
    # 注意 style 属性正文里不会有 "，但末尾属性往往无分号；用 ;|"行尾 兜底
    _STYLE_DECL_RE = re.compile(
        r"font-family\s*:\s*(?P<ff>[^;\"]+?)(?=;|\"|$)|"
        r"font-size\s*:\s*(?P<fs>[^;\"]+?)(?=;|\"|$)|"
        r"font-weight\s*:\s*(?P<fw>[^;\"]+?)(?=;|\"|$)|"
        r"color\s*:\s*(?P<col>#[0-9A-Fa-f]{3,8}\b|hsl\([^)]+\)|rgb\([^)]+\))(?=;|\"|$)|"
        r"background(?:-color)?\s*:\s*(?P<bg>linear-gradient\([^)]+\)|radial-gradient\([^)]+\)|#[0-9A-Fa-f]{3,8}\b)(?=;|\"|$)",
        re.IGNORECASE,
    )

    @classmethod
    def parse_header_lock(cls, constitution: str) -> Dict[str, str]:
        """从宪法字符串解析 ===HEADER_LOCK=== 令牌块。未给出则返回空字典。"""
        if not constitution:
            return {}
        m = cls._HEADER_LOCK_RE.search(constitution)
        if not m:
            return {}
        block = m.group(1)
        out: Dict[str, str] = {}
        for lm in cls._HEADER_LINE_RE.finditer(block):
            key = lm.group("key").strip().lower()
            val = lm.group("val").strip().rstrip(";").strip()
            if val:
                out[key] = val
        return out

    @classmethod
    def parse_footer_lock(cls, constitution: str) -> Dict[str, str]:
        """从宪法字符串解析 ===FOOTER_LOCK=== 令牌块。未给出则返回空字典。"""
        if not constitution:
            return {}
        m = cls._FOOTER_LOCK_RE.search(constitution)
        if not m:
            return {}
        block = m.group(1)
        out: Dict[str, str] = {}
        for lm in cls._FOOTER_LINE_RE.finditer(block):
            key = lm.group("key").strip().lower()
            val = lm.group("val").strip().rstrip(";").strip()
            if val:
                out[key] = val
        return out

    @classmethod
    def _normalize_color(cls, s: str) -> Optional[str]:
        """把常见颜色串归一为便于比对的字符串：6 位 hex 小写，否则原样小写去空格。"""
        if not s:
            return None
        s = s.strip().lower()
        m = re.fullmatch(r"#([0-9a-f]{6})", s)
        if m:
            return s
        # #abc → #aabbcc
        m3 = re.fullmatch(r"#([0-9a-f]{3})\b", s)
        if m3:
            a, b, c = m3.group(1)
            return f"#{a}{a}{b}{b}{c}{c}"
        return s  # gradient / rgb(...) 原样

    @classmethod
    def _find_header_style_decls(cls, html: str) -> List[Dict[str, str]]:
        """从 HTML 中收集"疑似页头标题区"内联样式的声明集合。

        启发式：扫描所有 style="..." 的内联块，挑出含 font-family 与
        (color 或 background) 至少两项的，视为页头标题候选；同时扫描
        `header`/`h1`/`h2` 等语义标签上的内联 style。这只做尽力而为的
        一致性比对，宁可漏报也不误判主内容区。
        """
        decls: List[Dict[str, str]] = []
        for style_m in re.finditer(r'style\s*=\s*"([^"]*)"', html, re.IGNORECASE):
            body = style_m.group(1)
            d: Dict[str, str] = {}
            for dm in cls._STYLE_DECL_RE.finditer(body):
                for k in ("ff", "fs", "fw", "col", "bg"):
                    v = dm.group(k)
                    if v is not None and v.strip():
                        key = {"ff": "font_family", "fs": "font_size", "fw": "font_weight",
                               "col": "color", "bg": "background"}[k]
                        d[key] = v.strip()
            # 页头候选：至少有 font-family，且同时出现 color 或 background 之一
            if d.get("font_family") and (d.get("color") or d.get("background")):
                decls.append(d)
        return decls

    @classmethod
    def is_header_locked_page(cls, slide_data: Optional[Dict[str, Any]],
                              page_number: Optional[int] = None,
                              total_pages: Optional[int] = None) -> bool:
        """判定本页是否应遵循全册页头令牌。

        非内容页（封面/尾页/目录/过渡/分割页）可自由设计页头，不参与 HEADER_LOCK 守恒校验，
        与 prompt 侧 _build_locked_zones_context 的豁免逻辑保持一致。
        """
        if not slide_data:
            # 没拿到 slide 元信息时不动现状（保守地参与校验），避免老路退化
            return True
        slide_data = slide_data or {}
        slide_type = str(slide_data.get("slide_type") or slide_data.get("type") or "").strip().lower()
        title = str(slide_data.get("title") or "").strip()

        if page_number is not None and page_number == 1:
            return False
        if total_pages is not None and page_number is not None and page_number == total_pages:
            return False
        # 目录/大纲类（与 prompt 侧 keyword 对齐）
        catalog_types = ("outline", "catalog", "directory", "agenda", "toc")
        if slide_type in catalog_types:
            return False
        # 过渡/分割/章节扉页等
        divider_types = ("transition", "divider", "section", "chapter", "separator", "interlude")
        if slide_type in divider_types:
            return False
        # title 里含目录/大纲关键词也豁免
        if any(kw in title for kw in ["目录", "大纲", "Contents", "Agenda", "过渡", "过渡页"]):
            return False
        return True

    @classmethod
    def _check_header_lock(cls, html: str, lock: Dict[str, str],
                          slide_data: Optional[Dict[str, Any]] = None,
                          page_number: Optional[int] = None,
                          total_pages: Optional[int] = None) -> Tuple[List[str], List[str]]:
        """比对页面内页头候选样式与 HEADER_LOCK 令牌。返回 (hard_fails, warnings)。

        非内容页（封面/尾页/目录/过渡）自动豁免：返回空，不做页头守恒比对。
        """
        hard: List[str] = []
        warns: List[str] = []
        if not lock:
            return hard, warns
        if not cls.is_header_locked_page(slide_data, page_number, total_pages):
            return hard, warns  # 非内容页豁免
        decls = cls._find_header_style_decls(html)
        if not decls:
            return hard, warns  # 没有可识别的内联页头样式，不强判

        # 令牌归一化
        lock_ff = lock.get("font_family")
        lock_fs = (lock.get("font_size") or "").strip()
        lock_fw = (lock.get("font_weight") or "").strip()
        lock_col = cls._normalize_color(lock.get("color", ""))
        lock_bg = (lock.get("background") or "").strip().lower()

        ff_divergent = fs_divergent = fw_divergent = col_divergent = bg_divergent = 0
        for d in decls:
            if lock_ff and d.get("font_family") and not cls._font_family_matches(d["font_family"], lock_ff):
                ff_divergent += 1
            if lock_fs and d.get("font_size") and not cls._size_matches(d["font_size"], lock_fs):
                fs_divergent += 1
            if lock_fw and d.get("font_weight") and d["font_weight"].strip() != lock_fw:
                fw_divergent += 1
            if lock_col and d.get("color") and cls._normalize_color(d["color"]) != lock_col:
                col_divergent += 1
            if lock_bg and d.get("background") and not cls._bg_matches(d["background"], lock_bg):
                bg_divergent += 1

        # 字体/背景是跨页一致性的核心载体 → hard fail；字号/字重为相对软指标 → warning
        if ff_divergent:
            hard.append(
                f"页头标题字体栈与 HEADER_LOCK 不一致（{ff_divergent} 处偏离「{lock_ff}」），必须沿用全册唯一页头字体"
            )
        if bg_divergent:
            hard.append(
                f"页头标题区背景与 HEADER_LOCK 不一致（{bg_divergent} 处偏离「{lock_bg}」），页头背景全册必须一致"
            )
        if fs_divergent:
            warns.append(f"页头字号有 {fs_divergent} 处与令牌「{lock_fs}」不符，建议统一")
        if fw_divergent:
            warns.append(f"页头字重有 {fw_divergent} 处与令牌「{lock_fw}」不符，建议统一")

        # 页头组成一致性：是否带图标、图标规格是否落在令牌内（二值一致）
        # 令牌取值示例：`icon: none`（全册纯文字）/ `icon: svg-inline, 28px`（统一带图标）
        lock_icon = (lock.get("icon") or "").strip()
        if lock_icon:
            want_icon = not lock_icon.lower().startswith("none")
            # 全页 svg 计数
            svg_count = len(re.findall(r"<svg\b", html, re.IGNORECASE))
            # 在页头候选附近找 inline svg（启发式：style 块紧邻的 header/容器文本）
            header_block_multi = re.search(
                r"<(header|h1|h2|div[^>]*)\b[^>]*style=\"[^\"]*font-family[^\"]*\"[^>]*>(.*?)</\1>",
                html, re.IGNORECASE | re.DOTALL,
            )
            header_has_svg = False
            if header_block_multi:
                header_has_svg = "<svg" in header_block_multi.group(0).lower()
            # 额外检测：页面上半部小尺寸 SVG（≤48px 宽高，可能是页头外独立图标），
            # 用于避免 SVG 放在 header 容器外时漏判
            top_half_html = html[:len(html) // 4] if len(html) > 200 else html
            tiny_svg_count = len(re.findall(
                r"<svg\b[^>]*(?:width\s*=\s*[\"']?(?:\d{1,2})\b|height\s*=\s*[\"']?(?:\d{1,2})\b)[^>]*>",
                top_half_html, re.IGNORECASE))
            # 如果宽度/高度不大于 48，也视为候选小图标
            if not tiny_svg_count:
                tiny_svg_count = len(re.findall(
                    r"<svg\b[^>]*(?:width\s*=\s*[\"']?(?:3[0-9]|4[0-8])\b|height\s*=\s*[\"']?(?:3[0-9]|4[0-8])\b)[^>]*>",
                    top_half_html, re.IGNORECASE))
            any_header_icon = header_has_svg or (svg_count > 0 and tiny_svg_count > 0)

            if want_icon and not any_header_icon and svg_count == 0:
                hard.append(
                    f"页头缺少图标：令牌要求页头带图标（{lock_icon}），本页为纯文字标题，全册页头组成需一致"
                )
            if not want_icon and any_header_icon:
                hard.append(
                    f"页头不应带图标：令牌要求页头为纯文字标题（icon: none），本页出现了图标，全册页头组成需一致"
                )
        return hard, warns

    _PAGE_NUM_RE = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")
    _FOOTER_TAG_RE = re.compile(r"<(div|span|p|footer|label)\b[^>]*class\s*=\s*\"[^\"]*(?:page-num|pagination|footer|slide-num)[^\"]*\"[^>]*>", re.IGNORECASE)

    @classmethod
    def _check_footer_lock(cls, html: str, lock: Dict[str, str],
                          slide_data: Optional[Dict[str, Any]] = None,
                          page_number: Optional[int] = None,
                          total_pages: Optional[int] = None) -> Tuple[List[str], List[str]]:
        """比对页面内页脚页码样式与 FOOTER_LOCK 令牌。返回 (hard_fails, warnings)。

        普通内容页必须显示页码，且其字体栈/字号/字重/颜色需沿用令牌。
        非内容页（封面/尾页/目录/过渡）可无页码，自动豁免。
        """
        hard: List[str] = []
        warns: List[str] = []
        if not lock:
            return hard, warns
        if not cls.is_header_locked_page(slide_data, page_number, total_pages):
            return hard, warns  # 非内容页可无页码，豁免

        # 搜索页面中的页码模式 "N / M" 以及 footer/page-num 类元素
        # 去掉 HTML 标签后搜索文本以兜底
        text_only = re.sub(r"<[^>]+>", " ", html)
        num_matches = list(cls._PAGE_NUM_RE.finditer(text_only))
        if not num_matches:
            # 没有 "N/M" 格式的页码 → 两种可能：页码使用了其他格式（如纯数字），或确实没有页码
            # 再搜 footer/page-num 类元素
            has_footer_el = bool(cls._FOOTER_TAG_RE.search(html))
            if has_footer_el:
                return hard, warns  # 有页脚容器但格式非 N/M，不强制判违
            warns.append("未检测到页码（N/M 格式），普通内容页通常应有页码；若使用了其他数字格式，可忽略此提示")
            return hard, warns

        # 找到匹配的页码，定位其周围的元素取内联样式
        # 启发式：取匹配前的最近 style="..." 块，或匹配附近的 <span>/<div> 样式
        match_pos = num_matches[0].start()
        # 在 HTML 原文中匹配位置附近的 style 属性
        nearby = html[max(0, match_pos - 500):match_pos + 200]
        style_m = re.search(r'style\s*=\s*"([^"]*(?:font-family|color)[^"]*)"', nearby, re.IGNORECASE)
        if not style_m:
            warns.append("页码附近未找到内联字体/颜色样式，无法校验页脚令牌一致性")
            return hard, warns

        style_decl = style_m.group(1)
        d: Dict[str, str] = {}
        for dm in cls._STYLE_DECL_RE.finditer(style_decl):
            for k in ("ff", "fs", "fw", "col"):
                v = dm.group(k)
                if v is not None and v.strip():
                    key = {"ff": "font_family", "fs": "font_size",
                           "fw": "font_weight", "col": "color"}[k]
                    d[key] = v.strip()

        lock_ff = lock.get("font_family")
        lock_col = cls._normalize_color(lock.get("color", ""))
        lock_fs = (lock.get("font_size") or "").strip()
        lock_fw = (lock.get("font_weight") or "").strip()

        if lock_ff and d.get("font_family") and not cls._font_family_matches(d["font_family"], lock_ff):
            hard.append(f"页码字体栈与 FOOTER_LOCK 不一致（「{d['font_family']}」≠ 令牌「{lock_ff}」），全册页码字体须沿用令牌")
        if lock_col and d.get("color") and cls._normalize_color(d["color"]) != lock_col:
            hard.append(f"页码颜色与 FOOTER_LOCK 不一致（「{d.get('color')}」≠ 令牌「{lock.get('color')}」），全册页码颜色须统一")
        if lock_fs and d.get("font_size") and not cls._size_matches(d["font_size"], lock_fs):
            warns.append(f"页码字号「{d.get('font_size')}」与令牌「{lock_fs}」不符，建议统一")
        if lock_fw and d.get("font_weight") and d["font_weight"].strip() != lock_fw:
            warns.append(f"页码字重「{d.get('font_weight')}」与令牌「{lock_fw}」不符，建议统一")
        return hard, warns

    @staticmethod
    def _font_family_matches(actual: str, lock_ff: str) -> bool:
        """字体族匹配：按各自的第一个 family（去引号）比较，忽略空白。"""
        def first_family(s: str) -> str:
            s = (s or "").split(",")[0].strip().strip("'\"").lower()
            return s
        return first_family(actual) and first_family(actual) == first_family(lock_ff)

    @staticmethod
    def _size_matches(actual: str, lock_fs: str) -> bool:
        """字号匹配：比较数值（忽略单位差异 36px vs 36）。"""
        def num(s: str) -> Optional[float]:
            m = re.search(r"([0-9]+(?:\.\d+)?)", s or "")
            return float(m.group(1)) if m else None
        a, b = num(actual), num(lock_fs)
        return a is not None and b is not None and a == b

    @staticmethod
    def _bg_matches(actual: str, lock_bg: str) -> bool:
        """背景匹配：相同 gradient/同色即一致；都归一小写比较。"""
        a = actual.strip().lower()
        b = lock_bg.strip().lower()
        return a == b

    @classmethod
    def check(cls, html: str, header_lock: Optional[Dict[str, str]] = None,
             footer_lock: Optional[Dict[str, str]] = None,
             slide_data: Optional[Dict[str, Any]] = None,
             page_number: Optional[int] = None,
             total_pages: Optional[int] = None) -> Tuple[List[str], List[str]]:
        """返回 (hard_fails, warnings)。

        header_lock：可选，从宪法 ===HEADER_LOCK=== 解析出的令牌字典。
        footer_lock：可选，从宪法 ===FOOTER_LOCK=== 解析出的令牌字典。
        传入时对页头标题区/页脚页码区做跨页一致性守恒校验；非内容页自动豁免，不传则跳过。
        """
        hard_fails: List[str] = []
        warnings: List[str] = []
        if not html or not html.strip():
            return hard_fails, warnings

        try:
            # 1. em-dash / en-dash
            dash_count = len(cls._DASH_RE.findall(html))
            if dash_count:
                hard_fails.append(
                    f"出现 {dash_count} 处 em-dash/en-dash（—/–），属于最强 AI 套路指纹，请用普通连字符或换行/分栏替代"
                )

            # 2. 纯黑纯白
            pure_bw = cls._PURE_BW_RE.findall(html)
            if pure_bw:
                warns = sorted({c.upper() for c in pure_bw})
                hard_fails.append(
                    f"出现纯黑/纯白 {warns}，请改用近黑（如 #1A1A1A）和近白保留层次"
                )

            # 3. 多 accent 色撞色（页内侧重色是否唯一）
            distinct: dict = {}
            for m in cls._HEX_RE.finditer(html):
                hexv = m.group(1).upper()
                rgb = cls._hex_to_rgb(hexv)
                if cls._is_neutral(rgb):
                    continue
                distinct[hexv] = distinct.get(hexv, 0) + 1
            # 去掉极低频的噪点色（仅出现一次且非主色），剩余即为"页内活跃强调色"
            active = {c: n for c, n in distinct.items() if n >= 2}
            if len(active) > 1:
                top = sorted(active.items(), key=lambda kv: kv[1], reverse=True)
                hard_fails.append(
                    f"页内出现多种活跃 accent 色 {sorted(c for c, _ in top)}，全册应锁定唯一 accent，请只保留一种"
                )
        except Exception:
            # 任何异常都不阻塞主流程
            return hard_fails, warnings

        try:
            # 4. 圆角一致性（warning）
            radius_values = [float(m.group(1)) for m in cls._RADIUS_RE.finditer(html)]
            # 过滤胶囊（9999px、百分比 50 等）
            rounded = [v for v in radius_values if v not in (9999,)]
            distinct_radius = set(rounded)
            if len(distinct_radius) > 3:
                warnings.append(
                    f"圆角刻度繁杂（{sorted(distinct_radius)}），建议统一为 sharp/soft/pill 之一"
                )

            # 5. 三等分卡片（启发式，warning）
            if cls._GRID3_RE.search(html):
                warnings.append(
                    "检测到三列等份网格，请确认不是'三张等宽卡片横排'的套路；对等内容可改 2+1 或非对称网格"
                )
        except Exception:
            pass

        # 6. 页头令牌守恒：跨页标题字体/背景一致性（非内容页自动豁免）
        try:
            h_lock, w_lock = cls._check_header_lock(
                html, header_lock or {}, slide_data, page_number, total_pages)
            hard_fails.extend(h_lock)
            warnings.extend(w_lock)
        except Exception:
            pass

        # 7. 页脚令牌守恒：页码字体/颜色一致性（非内容页自动豁免）
        try:
            h_lock, w_lock = cls._check_footer_lock(
                html, footer_lock or {}, slide_data, page_number, total_pages)
            hard_fails.extend(h_lock)
            warnings.extend(w_lock)
        except Exception:
            pass

        return hard_fails, warnings
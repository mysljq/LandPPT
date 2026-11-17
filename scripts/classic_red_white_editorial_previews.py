"""Real-content layout references for the suite; no generated slide mutations."""
from html import escape as e


def editorial_previews(slides: list) -> list:
    # Preserve each page's complete outline text; only split labels from bodies.
    examples = []
    slide = slides[10]
    points = slide["content_points"]
    rows = []
    for n, point in enumerate(points[1:], 1):
        label, _, body = point.partition("：")
        rows.append(f'<div class="module-row"><span class="suite-index">{n:02}</span><strong>{e(label)}</strong><p>{e(body)}</p></div>')
    css = """<style>
.module-layout{display:grid;grid-template-columns:220px minmax(0,1fr);gap:32px;height:100%}
.module-core{padding-top:32px;border-right:1px solid var(--suite-line);padding-right:24px}
.module-core .suite-display{font-size:44px;margin:16px 0 24px}
.module-core p{font-size:20px;line-height:1.5}
.module-rows{display:flex;flex-direction:column;justify-content:space-between;padding:8px 0}
.module-row{display:grid;grid-template-columns:32px 80px minmax(0,1fr);gap:12px;align-items:start;border-top:1px solid var(--suite-line);padding-top:12px}
.module-row strong{font-size:20px;line-height:1.5}.module-row p{font-size:20px;line-height:1.5}
</style>"""
    # The equation is the full first content point, broken into typographic parts.
    equation = e(points[0]).replace('LLM', '<span class="suite-display" style="display:block">LLM</span>')
    body = css + '<div class="module-layout"><div class="module-core"><p>'+equation+'</p></div><div class="module-rows">'+''.join(rows)+'</div></div>'
    examples.append((10, "architecture", body))

    slide = slides[15]
    points = slide['content_points']
    steps = []
    for n, point in enumerate(points[1:4], 1):
        label, _, description = point.partition('：')
        steps.append('<div class="suite-path-step"><div class="suite-display">'+f'{n:02}'+'</div><div class="suite-path-title">'+e(label).replace(' Engineering','<br><span style="font-size:20px;font-weight:400">Engineering</span>')+'</div><p>'+e(description)+'</p></div>')
    css = '<style>.progress-intro{font-size:20px;margin:0 0 20px}.progress-layout{height:100%;display:flex;flex-direction:column;gap:16px}.progress-layout .suite-path{flex:1}.progress-layout .suite-path-step p{font-size:20px;line-height:1.5}.progress-layout .suite-takeaway{font-size:20px;line-height:1.5}.progress-layout .suite-path-step:last-child{background:var(--suite-brand);color:var(--suite-paper);padding:20px;min-height:236px}.progress-layout .suite-path-step:last-child .suite-display{color:var(--suite-paper);font-size:40px}.progress-layout .suite-path-step:last-child .suite-path-title{font-size:28px}</style>'
    body = css+'<div class="progress-layout"><p class="progress-intro">'+e(points[0])+'</p><div class="suite-path">'+''.join(steps)+'</div><p class="suite-takeaway">'+e(points[4])+'</p></div>'
    examples.append((15, 'progression', body))

    slide = slides[23]
    points = slide['content_points']
    columns = []
    for point in points[:2]:
        label, _, text = point.partition('：')
        columns.append('<div><div class="suite-display">'+e(label)+'</div><p>'+e(text)+'</p></div>')
    support = []
    for point in points[2:]:
        label, _, text = point.partition('：')
        support.append('<div class="contrast-note"><strong>'+e(label)+'</strong><p>'+e(text)+'</p></div>')
    css = '<style>.contrast-layout{display:flex;flex-direction:column;gap:24px;height:100%}.contrast-layout .suite-contrast{padding:8px 0 16px}.contrast-layout .suite-contrast p{font-size:22px;line-height:1.5;margin-top:16px}.contrast-layout .suite-contrast>div+div .suite-display{color:var(--suite-ink)}.contrast-notes{display:flex;flex-direction:column;gap:20px}.contrast-note{display:grid;grid-template-columns:140px minmax(0,1fr);gap:24px;font-size:20px;line-height:1.5}.contrast-note strong{color:var(--suite-brand)}.contrast-notes{border-top:2px solid var(--suite-brand);padding-top:20px}</style>'
    body = css+'<div class="contrast-layout"><div class="suite-contrast">'+''.join(columns)+'</div><div class="contrast-notes">'+''.join(support)+'</div></div>'
    examples.append((23, 'comparison', body))
    return examples

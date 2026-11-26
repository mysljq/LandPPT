"""Measured PPTX evidence and deterministic HTML; coordinates are never re-designed."""
from __future__ import annotations

import hashlib
import html
import json
import math
from pathlib import Path
from lxml import etree
from font_units import pptx_px_per_point, pptx_points_to_px

A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS = {'a': A, 'p': P, 'r': R}


def find(node, path):
    return node.find(path, NS) if node is not None else None


def val(node, key, default=None):
    return node.get(key, default) if node is not None else default


def number(value):
    return f'{float(value):.6f}'.rstrip('0').rstrip('.') or '0'


def css(properties):
    return ';'.join(f'{key}:{value}' for key, value in properties.items())


def multiply(m, n):
    a,b,c,d,e,f = m; g,h,i,j,k,l = n
    return (a*g+c*h,b*g+d*h,a*i+c*j,b*i+d*j,a*k+c*l+e,b*k+d*l+f)


def translated(x, y):
    return (1,0,0,1,x,y)


def rotation(angle, cx, cy, flip_h=False, flip_v=False):
    r = math.radians(angle); x = -1 if flip_h else 1; y = -1 if flip_v else 1
    return multiply(multiply(translated(cx,cy),(math.cos(r)*x,math.sin(r)*x,-math.sin(r)*y,math.cos(r)*y,0,0)),translated(-cx,-cy))


def bounds(m, w, h):
    points = [(m[0]*x+m[2]*y+m[4],m[1]*x+m[3]*y+m[5]) for x,y in [(0,0),(w,0),(0,h),(w,h)]]
    xs,ys=zip(*points)
    return [min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys)]


class Reader:
    def __init__(self, presentation, store, native=None):
        self.p = presentation
        self.store = store
        self.scale = min(1280/presentation.slide_width,720/presentation.slide_height)
        self.font_factor = pptx_px_per_point(presentation.slide_width, presentation.slide_height)
        self.root_matrix = translated((1280-presentation.slide_width*self.scale)/2,(720-presentation.slide_height*self.scale)/2)
        self.warnings = []
        self.native = {(s['slide'],sh['id']):sh for s in (native or []) for sh in s['shapes']}
        self.theme = {}
        self.fonts = {}
        for rel in presentation.slide_masters[0].part.rels.values():
            if rel.reltype.endswith('/theme'):
                theme = etree.fromstring(rel.target_part.blob)
                for n in theme.findall('.//a:clrScheme/*', NS):
                    child = n[0]
                    self.theme[etree.QName(n).localname] = child.get('val') if child.tag.endswith('srgbClr') else child.get('lastClr')
                for family in ('major','minor'):
                    for script in ('latin','ea','cs'):
                        self.fonts[(family,script)] = val(find(theme,f'.//a:{family}Font/a:{script}'),'typeface','')
        self.theme.update({'bg1':self.theme.get('lt1','FFFFFF'),'tx1':self.theme.get('dk1','000000'),'bg2':self.theme.get('lt2','FFFFFF'),'tx2':self.theme.get('dk2','000000')})

    def color(self, node):
        if node is None: return '#000000'
        rgb = find(node,'a:srgbClr'); scheme=find(node,'a:schemeClr'); system=find(node,'a:sysClr')
        color = val(rgb,'val') or self.theme.get(val(scheme,'val')) or val(system,'lastClr') or '000000'
        rgb_values = [int(color[i:i+2],16) for i in (0,2,4)]
        target = rgb if rgb is not None else scheme
        for child in target if target is not None else []:
            tag=etree.QName(child).localname; v=float(child.get('val','100000'))/100000
            if tag in ('lumMod','shade'): rgb_values=[c*v for c in rgb_values]
            elif tag=='lumOff':rgb_values=[c+255*v for c in rgb_values]
            elif tag=='tint':rgb_values=[c+(255-c)*v for c in rgb_values]
        return '#' + ''.join(f'{round(max(0,min(255,c))):02X}' for c in rgb_values)

    def fill(self, props):
        if props is None or find(props,'a:noFill') is not None:return None
        solid=find(props,'a:solidFill')
        if solid is not None:return self.color(solid)
        grad=find(props,'a:gradFill')
        if grad is not None:
            stops=sorted([(float(gs.get('pos'))/1000,self.color(gs)) for gs in grad.findall('a:gsLst/a:gs',NS)])
            angle=float(val(find(grad,'a:lin'),'ang','0'))/60000+90
            return 'linear-gradient('+number(angle)+'deg,'+','.join(f'{c} {number(p)}%' for p,c in stops)+')'
        return None

    def inherited(self, shape, slide):
        chain=[shape._element]
        if shape.is_placeholder:
            idx=shape.placeholder_format.idx
            for owner in (slide.slide_layout,slide.slide_layout.slide_master):
                matches=[s._element for s in owner.placeholders if s.placeholder_format.idx==idx]
                chain.extend(matches[:1])
        return chain

    def text(self, shape, slide, slide_no):
        chain=self.inherited(shape,slide)
        body_nodes=[find(e,'p:txBody/a:bodyPr') for e in chain]
        def body_attr(name,default):
            return next((n.get(name) for n in body_nodes if n is not None and n.get(name) is not None),default)
        margins={k:float(body_attr(a,d))*self.scale for k,a,d in [('left','lIns','91440'),('top','tIns','45720'),('right','rIns','91440'),('bottom','bIns','45720')]}
        paragraphs=[]
        for paragraph in shape.text_frame.paragraphs:
            ppr=find(paragraph._p,'a:pPr'); lvl=int(val(ppr,'lvl','0'))+1
            lists=[find(e,f'p:txBody/a:lstStyle/a:lvl{lvl}pPr') for e in chain]
            master=slide.slide_layout.slide_master._element
            style='titleStyle' if shape.is_placeholder and str(shape.placeholder_format.type).startswith(('TITLE','CENTER_TITLE')) else ('bodyStyle' if shape.is_placeholder else 'otherStyle')
            lists.extend([find(master,f'p:txStyles/p:{style}/a:lvl{lvl}pPr'),find(self.p._element,f'p:defaultTextStyle/a:lvl{lvl}pPr')])
            pchain=[n for n in [ppr,*lists] if n is not None]
            def pattr(name,default):return next((n.get(name) for n in pchain if n.get(name) is not None),default)
            defs=[find(n,'a:defRPr') for n in pchain]
            run_entries=[]
            raw_runs=paragraph._p.findall('a:r',NS)
            if not raw_runs:raw_runs=[paragraph._p]
            for raw in raw_runs:
                rpr=find(raw,'a:rPr')
                rchain=[n for n in [rpr,*defs,find(paragraph._p,'a:endParaRPr')] if n is not None]
                def attr(key,default):return next((n.get(key) for n in rchain if n.get(key) is not None),default)
                font = next((val(find(n,'a:ea'),'typeface') or val(find(n,'a:latin'),'typeface') for n in rchain if val(find(n,'a:ea'),'typeface') or val(find(n,'a:latin'),'typeface')), 'Arial')
                if font.startswith('+'):
                    font=self.fonts.get(('major' if font[1:3]=='mj' else 'minor','ea' if font.endswith('ea') else 'latin')) or 'Arial'
                point_size=float(attr('sz','1800'))/100
                size=pptx_points_to_px(point_size,self.p.slide_width,self.p.slide_height)
                fill=next((self.fill(n) for n in rchain if self.fill(n)), '#000000')
                styles={'font-family':f'"{font}",sans-serif','font-size':number(size)+'px','font-weight':'700' if attr('b','0')=='1' else '400','font-style':'italic' if attr('i','0')=='1' else 'normal','letter-spacing':number(float(attr('spc','0'))/100*12700*self.scale)+'px','color':fill if not fill.startswith('linear') else '#000000'}
                if fill.startswith('linear'):styles.update({'background-image':fill,'background-clip':'text','-webkit-background-clip':'text','color':'transparent'})
                if attr('u','none')!='none':styles['text-decoration']='underline'
                text=''.join(raw.itertext()) if raw is paragraph._p else (find(raw,'a:t').text or '')
                if raw is paragraph._p:text=''
                run_entries.append({'text':text,'font':font,'font_size_pt':point_size,'font_size_px':size,'style':styles})
            line_node=next((find(n,'a:lnSpc') for n in pchain if find(n,'a:lnSpc') is not None),None)
            pct=find(line_node,'a:spcPct'); pts=find(line_node,'a:spcPts')
            line_px=(float(pts.get('val'))/100*12700*self.scale if pts is not None else max(r['font_size_px'] for r in run_entries)*(float(val(pct,'val','100000'))/100000)*1.2)
            before=next((find(n,'a:spcBef/a:spcPts') for n in pchain if find(n,'a:spcBef/a:spcPts') is not None),None)
            after=next((find(n,'a:spcAft/a:spcPts') for n in pchain if find(n,'a:spcAft/a:spcPts') is not None),None)
            pstyle={'margin':'0','padding':'0','text-align':{'l':'left','ctr':'center','r':'right','just':'justify'}.get(pattr('algn','l'),'left'),'line-height':number(line_px)+'px','margin-top':number(float(val(before,'val','0'))/100*12700*self.scale)+'px','margin-bottom':number(float(val(after,'val','0'))/100*12700*self.scale)+'px'}
            paragraphs.append({'runs':run_entries,'style':pstyle})
        native=self.native.get((slide_no,shape.shape_id))
        return {'text':shape.text,'margins':margins,'anchor':body_attr('anchor','t'),'wrap':body_attr('wrap','square'), 'paragraphs':paragraphs,'native':native}

    def items(self, shapes, slide, slide_no, layer, part, parent=None):
        parent=parent or self.root_matrix
        result=[]
        for shape in shapes:
            x,y,w,h=[float(v)*self.scale for v in (shape.left,shape.top,shape.width,shape.height)]
            xf=find(shape._element,'p:spPr/a:xfrm')
            if int(shape.shape_type)==6:xf=find(shape._element,'p:grpSpPr/a:xfrm')
            transform=multiply(multiply(parent,translated(x,y)),rotation(shape.rotation,w/2,h/2,val(xf,'flipH')=='1',val(xf,'flipV')=='1'))
            uid=f's{slide_no}-{layer}-{shape.shape_id}'
            if int(shape.shape_type)==6:
                child_off=find(xf,'a:chOff');child_ext=find(xf,'a:chExt')
                cw=float(val(child_ext,'cx',str(shape.width)))*self.scale;ch=float(val(child_ext,'cy',str(shape.height)))*self.scale
                group=multiply(multiply(transform,(w/cw if cw else 1,0,0,h/ch if ch else 1,0,0)),translated(-float(val(child_off,'x','0'))*self.scale,-float(val(child_off,'y','0'))*self.scale))
                result.extend(self.items(shape.shapes,slide,slide_no,layer+'g'+str(shape.shape_id),part,group));continue
            if shape.is_placeholder and layer!='slide':continue
            item={'id':uid,'shape_id':shape.shape_id,'layer':layer,'kind':'shape','width':w,'height':h,'transform':list(transform),'bounds':bounds(transform,w,h),'name':shape.name}
            props=find(shape._element,'p:spPr');item['fill']=self.fill(props)
            if int(shape.shape_type)==13:
                item.update(kind='image',asset=self.store.save(shape.image.blob,'.'+shape.image.ext,str(part.partname)+'/'+str(shape.shape_id)),crop=[float(shape.crop_left),float(shape.crop_top),float(shape.crop_right),float(shape.crop_bottom)])
            elif int(shape.shape_type)==9:
                ln=find(props,'a:ln');item.update(kind='line',line={'width':float(val(ln,'w','12700'))*self.scale,'color':self.color(find(ln,'a:solidFill')),'dash':val(find(ln,'a:prstDash'),'val','solid'),'cap':val(ln,'cap','flat')})
            elif shape.has_text_frame:
                # Group child coordinates may use arbitrary chExt units (e.g. 1/635 EMU).
                # Normalize the frame to canvas px; font sizes and margins stay in points.
                scale_x=math.hypot(transform[0],transform[1]);scale_y=math.hypot(transform[2],transform[3])
                if scale_x and scale_y:
                    w*=scale_x;h*=scale_y
                    transform=(transform[0]/scale_x,transform[1]/scale_x,transform[2]/scale_y,transform[3]/scale_y,transform[4],transform[5])
                    item.update(width=w,height=h,transform=list(transform),bounds=bounds(transform,w,h))
                item.update(kind='text',text=self.text(shape,slide,slide_no))
                reflection=find(shape._element,'.//a:reflection')
                if reflection is not None:
                    item['reflection']={'distance_px':float(val(reflection,'dist','0'))*self.scale,'start_alpha':float(val(reflection,'stA','100000'))/100000,'end_alpha':float(val(reflection,'endA','0'))/100000,'end_position':float(val(reflection,'endPos','100000'))/1000}
                    self.warnings.append(f'{uid}: reflection uses CSS approximation; compare against native reference')
                geom=find(props,'a:prstGeom')
                if val(geom,'prst','rect')!='rect':self.warnings.append(f'{uid}: text shape geometry {geom.get("prst")} not reproduced')
            else:
                self.warnings.append(f'{uid}: unsupported {shape.shape_type}; requires native reference and review')
            if item['kind']=='image':
                item['opacity']=float(val(find(shape._element,'p:blipFill/a:blip/a:alphaModFix'),'amt','100000'))/100000
            result.append(item)
        return result


def element(item, asset_prefix=''):
    w,h=item['width'],item['height']
    styles={'position':'absolute','left':'0px','top':'0px','width':number(w)+'px','height':number(h)+'px','transform-origin':'0 0','transform':'matrix('+','.join(number(v) for v in item['transform'])+')','box-sizing':'border-box','margin':'0'}
    if item.get('fill'):styles['background']=item['fill']
    if 'opacity' in item:styles['opacity']=number(item['opacity'])
    uid=html.escape(item['id'],quote=True)
    content=''
    if item['kind']=='image':
        l,t,r,b=item['crop'];styles['overflow']='hidden'
        content='<img data-pptx-image="true" src="'+asset_prefix+item['asset']+'" alt="" style="position:absolute;max-width:none;max-height:none;left:'+number(-l/(1-l-r)*100)+'%;top:'+number(-t/(1-t-b)*100)+'%;width:'+number(100/(1-l-r))+'%;height:'+number(100/(1-t-b))+'%;object-fit:fill">'
    elif item['kind']=='line':
        ln=item['line'];unit=ln['width']
        dash={'dash':[4,3],'sysDash':[3,1],'dot':[1,3],'sysDot':[1,1],'lgDash':[8,3],'dashDot':[4,3,1,3],'lgDashDot':[8,3,1,3],'lgDashDotDot':[8,3,1,3,1,3]}.get(ln['dash'])
        dash_attr=' stroke-dasharray="'+' '.join(number(v*unit)for v in dash)+'"' if dash else ''
        styles['overflow']='visible'
        content=f'<svg width="{number(max(w,1))}" height="{number(max(h,1))}" style="position:absolute;left:0;top:0;overflow:visible"><line x1="0" y1="0" x2="{number(w)}" y2="{number(h)}" stroke="{ln["color"]}" stroke-width="{number(unit)}" stroke-linecap="{"round" if ln["cap"]=="rnd" else "butt"}"{dash_attr}/></svg>'
    elif item['kind']=='text':
        text=item['text'];m=text['margins'];native=text.get('native')
        inner={'position':'absolute','left':number(m['left'])+'px','right':number(m['right'])+'px','top':number(m['top'])+'px','bottom':number(m['bottom'])+'px','display':'flex','flex-direction':'column','justify-content':{'t':'flex-start','ctr':'center','b':'flex-end'}.get(text['anchor'],'flex-start'),'overflow':'visible'}
        if native and text['anchor']=='t':
            inner['top']=number(native['bound'][1]-item['bounds'][1])+'px'
            # Native top paragraph spacing is collapsed for first paragraph in PowerPoint.
        ps=[]
        for index,p in enumerate(text['paragraphs']):
            pstyle=dict(p['style'])
            # Match the paragraph strut to its run font; a browser default 16px serif
            # strut can enlarge an inline line box and shift vertically centered text.
            pstyle['font-size']=number(p['runs'][0]['font_size_px'])+'px'
            pstyle['font-family']=p['runs'][0]['style']['font-family']
            if index==0:pstyle['margin-top']='0'
            if native and len(text['paragraphs'])==1 and native.get('line_count',1)==1:
                pstyle['line-height']=number(native['bound'][3])+'px'
            if item.get('reflection'):
                effect=item['reflection']
                pstyle['-webkit-box-reflect']='below '+number(effect['distance_px'])+'px linear-gradient(to bottom,rgba(0,0,0,'+number(effect['start_alpha'])+'),rgba(0,0,0,'+number(effect['end_alpha'])+') '+number(effect['end_position'])+'%,transparent)'
            spans=''.join('<span data-pptx-run="true" style="'+html.escape(css(r['style']),quote=True)+'">'+html.escape(r['text'])+'</span>' for r in p['runs'])
            ps.append('<p data-pptx-paragraph="true" style="'+html.escape(css(pstyle),quote=True)+'">'+spans+'</p>')
        content='<div data-pptx-text="true" style="'+html.escape(css(inner),quote=True)+'">'+''.join(ps)+'</div>'
    return '<div data-pptx-id="'+uid+'" data-pptx-kind="'+item['kind']+'" style="'+html.escape(css(styles),quote=True)+'">'+content+'</div>'


def document(items, prefix=''):
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>*{box-sizing:border-box}html,body{width:1280px;height:720px;margin:0;overflow:hidden}body{background:#fff}.pptx-slide{position:relative;width:1280px;height:720px;overflow:hidden}</style></head><body><main class="pptx-slide">'+''.join(element(i,prefix)for i in items)+'</main></body></html>'


def extract(presentation, out, store, native=None):
    reader=Reader(presentation,store,native)
    slides=[]
    (out/'slides').mkdir(exist_ok=True)
    for no,slide in enumerate(presentation.slides,1):
        items=[]
        if slide._element.get('showMasterSp','1')!='0':
            master=slide.slide_layout.slide_master
            items+=reader.items(master.shapes,slide,no,'master',master.part)
            items+=reader.items(slide.slide_layout.shapes,slide,no,'layout',slide.slide_layout.part)
        items+=reader.items(slide.shapes,slide,no,'slide',slide.part)
        slides.append({'number':no,'layout_name':slide.slide_layout.name,'shapes':items})
        (out/'slides'/f'{no:03}.html').write_text(document(items,'../'),encoding='utf-8')
    return {'kind':'pptx','evidence_version':2,'original_size_emu':[presentation.slide_width,presentation.slide_height], 'canvas':[1280,720], 'scale_px_per_emu':reader.scale,'font_px_per_pt':reader.font_factor,'normalization':'uniform scale, centered letterbox; font_pt * 12700 * scale', 'slides':slides,'warnings':reader.warnings, 'native_reference':bool(native)}

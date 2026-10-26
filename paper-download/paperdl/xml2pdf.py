"""Render publisher full-text XML to PDF."""
import base64
import copy
import html
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
L = lambda t: t.rsplit('}', 1)[-1]
PARA = {'para', 'simple-para', 'ce:para'}
SKIP = {'ref', 'ce:reference', 'ce:bibliography', 'bibliography', 'further-reading', 'floats', 'item-info'}
FLOAT = {'figure', 'table'}
MIN_BODY = 500
MIN_PDF_BYTES = 20000
CHROME_CANDIDATES = ('google-chrome', 'chromium', 'chromium-browser')
CHROME_FALLBACK = ('/usr/bin/google-chrome', '~/.local/bin/google-chrome')
VERSION = 2
MARK = 'XML2PDF-v2'

class RenderError(RuntimeError):
    pass

class PdfBytes(bytes):
    completeness = None

def text_of(el):
    return re.sub('\\s+', ' ', ''.join(el.itertext())).strip()

def text_skip(el, skip=FLOAT):
    out = []

    def rec(e):
        if e.text:
            out.append(e.text)
        for c in e:
            if L(c.tag) not in skip:
                rec(c)
            if c.tail:
                out.append(c.tail)
    rec(el)
    return re.sub('\\s+', ' ', ''.join(out)).strip()

def label_caption(el):
    label = next((text_of(c) for c in el if L(c.tag) == 'label'), '')
    cap = next((c for c in el if L(c.tag) == 'caption'), None)
    caption = ' '.join((text_of(p) for p in cap.iter() if L(p.tag) in ('simple-para', 'para'))) if cap is not None else ''
    if cap is not None and (not caption):
        caption = text_of(cap)
    return (label, caption)
MATHML_NS = 'http://www.w3.org/1998/Math/MathML'
INLINE = {'italic': 'i', 'bold': 'b', 'sup': 'sup', 'inf': 'sub', 'underline': 'u', 'monospace': 'code', 'small-caps': 'span', 'sans-serif': 'span'}
MATH_ATTRS = {'mathvariant', 'stretchy', 'fence', 'separator', 'lspace', 'rspace', 'width', 'height', 'depth', 'linethickness', 'displaystyle', 'scriptlevel', 'accent', 'accentunder', 'movablelimits', 'largeop', 'symmetric', 'columnalign', 'rowalign', 'columnspacing', 'rowspacing', 'form', 'minsize', 'maxsize', 'voffset', 'notation'}
SYMBOL_FIX = {'Î': '∈', 'Ï': '∉', 'Ì': '⊂', 'Í': '⊆', 'Ç': '∩', 'È': '∪', 'Ñ': '∇', '¥': '∞', '£': '≤', '³': '≥', '¹': '≠', '»': '≈', '®': '→', 'Û': '⇔', 'Þ': '⇒'}
TOKENS = {'mi', 'mo', 'mn', 'mtext', 'ms'}
PLACEHOLDER = re.compile('^\\s*mm[A-Z][A-Za-z]*')

def _strip_placeholders(m):
    n = 0
    for parent in list(m.iter()):
        kids = list(parent)
        i = 0
        while i < len(kids):
            k = kids[i]
            if L(k.tag) in ('mi', 'mtext') and PLACEHOLDER.match(k.text or ''):
                a = i
                while a > 0 and (not (L(kids[a].tag) == 'mo' and (kids[a].text or '').strip() == '<')):
                    a -= 1
                b = i
                while b < len(kids) - 1 and (not (L(kids[b].tag) == 'mo' and (kids[b].text or '').strip() == '>')):
                    b += 1
                for x in kids[a:b + 1]:
                    parent.remove(x)
                kids = list(parent)
                i = a
                n += 1
                continue
            i += 1
    return n

def _mser(e):
    n = L(e.tag)
    if n in ('annotation', 'annotation-xml'):
        return ''
    if n == 'semantics':
        first = next((c for c in e if L(c.tag) not in ('annotation', 'annotation-xml')), None)
        return _mser(first) if first is not None else ''
    if n == 'mfenced':
        op, cl = (e.get('open', '('), e.get('close', ')'))
        seps = list((e.get('separators', ',') or '').replace(' ', '')) or ['']
        kids = list(e)
        out = ['<mo>%s</mo>' % html.escape(op)] if op else []
        for i, c in enumerate(kids):
            if i:
                out.append('<mo>%s</mo>' % html.escape(seps[min(i - 1, len(seps) - 1)]))
            out.append(_mser(c))
        if cl:
            out.append('<mo>%s</mo>' % html.escape(cl))
        return '<mrow>%s</mrow>' % ''.join(out)
    attrs = ''.join((' %s="%s"' % (k, html.escape(v)) for k, v in e.attrib.items() if k in MATH_ATTRS))
    if n in TOKENS:
        t = e.text or ''
        t = SYMBOL_FIX.get(t.strip(), t)
        inner = html.escape(t.strip() if n != 'mtext' else t)
    else:
        inner = html.escape((e.text or '').strip())
    inner += ''.join((_mser(c) for c in e))
    return '<%s%s>%s</%s>' % (n, attrs, inner, n)

def _math_text(m):
    return ''.join((x.text or '' for x in m.iter() if L(x.tag) in TOKENS)).strip()

def math_html(m, block=False, stats=None):
    m = copy.deepcopy(m)
    junk = _strip_placeholders(m)
    if stats is not None:
        stats['math'] = stats.get('math', 0) + 1
        stats['junk'] = stats.get('junk', 0) + junk
    if not _math_text(m):
        if stats is not None:
            stats['dropped'] = stats.get('dropped', 0) + 1
        return ''
    disp = 'block' if block or m.get('display') == 'block' else 'inline'
    return '<math xmlns="%s" display="%s">%s</math>' % (MATHML_NS, disp, ''.join((_mser(c) for c in m)))

def eq_html(f, stats=None):
    lab = next((text_of(c) for c in f if L(c.tag) == 'label'), '')
    body = ''.join((math_html(c, True, stats) for c in f.iter() if L(c.tag) == 'math'))
    if not body:
        return ''
    return '<div class="eq"><span class="eqm">%s</span><span class="eqn">%s</span></div>' % (body, html.escape(lab))
_EQ_ONLY = re.compile('^[\\s,;.]*(\\(\\s*[0-9]+[a-z]?\\s*\\)[\\s,;.]*(and)?[\\s,;.]*)*$')

def eq_para(el, stats=None):
    rest = [el.text or ''] + [c.tail or '' for c in el]
    if any((L(c.tag) not in ('math', 'display', 'formula') for c in el)) or not any((L(c.tag) == 'math' for c in el)):
        return None
    if not _EQ_ONLY.match(''.join(rest)):
        return None
    out = []
    for c in el:
        n = L(c.tag)
        if n == 'math':
            body = math_html(c, True, stats)
            m = re.search('\\(\\s*[0-9]+[a-z]?\\s*\\)', c.tail or '')
            if body:
                out.append('<div class="eq"><span class="eqm">%s</span><span class="eqn">%s</span></div>' % (body, html.escape(re.sub('\\s+', '', m.group(0))) if m else ''))
        elif n == 'formula':
            out.append(eq_html(c, stats))
        else:
            out.append(''.join((eq_html(f, stats) for f in c.iter() if L(f.tag) == 'formula')))
    return ''.join(out)

def inline(el, stats=None, skip=FLOAT):
    out = [html.escape(el.text or '')]
    for c in el:
        n = L(c.tag)
        if n in skip or (n in ('link', 'label') and L(el.tag) not in ('cross-ref', 'cross-refs')):
            if n == 'label' and L(el.tag) not in ('list-item', 'formula', 'caption'):
                out.append(html.escape(text_of(c)) + ' ')
        elif n == 'math':
            out.append(math_html(c, False, stats))
        elif n == 'formula':
            out.append(eq_html(c, stats))
        elif n == 'display':
            out.append(''.join((eq_html(f, stats) for f in c.iter() if L(f.tag) == 'formula')))
        elif n == 'list':
            for it in c:
                if L(it.tag) != 'list-item':
                    continue
                lab = next((text_of(x) for x in it if L(x.tag) == 'label'), '')
                out.append('<div class="li"><span class="lab">%s</span> %s</div>' % (html.escape(lab), inline(it, stats, skip)))
        elif n in ('para', 'simple-para'):
            out.append('<div class="p2">%s</div>' % inline(c, stats, skip))
        elif n == 'br':
            out.append('<br>')
        elif n == 'hsp':
            out.append(' ')
        elif n in INLINE:
            out.append('<%s>%s</%s>' % (INLINE[n], inline(c, stats, skip), INLINE[n]))
        else:
            out.append(inline(c, stats, skip))
        out.append(html.escape(c.tail or ''))
    return re.sub('\\s+', ' ', ''.join(out)).strip()

def sniff(b):
    if not b or len(b) < 16:
        return None
    if b[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if b[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if b[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    if b[:4] == b'RIFF' and b[8:12] == b'WEBP':
        return 'image/webp'
    head = b[:1024].lstrip().lower()
    if head.startswith(b'<svg') or (head.startswith(b'<?xml') and b'<svg' in head):
        return 'image/svg+xml'
    return None

def asset_of(assets, loc):
    if not assets or not loc:
        return None
    b = assets.get(loc)
    if b is None:
        want = loc.lower()
        for k, v in assets.items():
            k2 = str(k).lower()
            if k2 == want or k2.rsplit('.', 1)[0] == want or k2.rsplit('/', 1)[-1].rsplit('.', 1)[0] == want:
                b = v
                break
    if isinstance(b, str):
        try:
            b = base64.b64decode(b)
        except Exception:
            b = None
    mime = sniff(b) if isinstance(b, (bytes, bytearray)) else None
    return (mime, bytes(b)) if mime else None

def locators(el):
    return [c.get('locator') for c in el.iter() if L(c.tag) == 'link' and c.get('locator')]

def images_html(el, assets):
    locs = locators(el)
    got = [asset_of(assets, x) for x in locs]
    if not locs or not all(got):
        miss = [x for x, g in zip(locs, got) if not g]
        return ('<div class="nofig">缺图：图像未取得%s</div>' % ('（' + html.escape(', '.join(miss)) + '）' if miss else '（XML 未给图像定位）'), False)
    return (''.join(('<img src="data:%s;base64,%s">' % (m, base64.b64encode(b).decode()) for m, b in got)), True)

def tgroup_html(tg, stats=None):
    cols = {}
    n = 0
    for cs in tg:
        if L(cs.tag) == 'colspec':
            n += 1
            num = cs.get('colnum')
            idx = int(num) if num and num.isdigit() else n
            if cs.get('colname'):
                cols[cs.get('colname')] = idx
    rows_html, rows = ([], 0)
    for part in tg:
        pn = L(part.tag)
        if pn not in ('thead', 'tbody', 'tfoot'):
            continue
        cell = 'th' if pn == 'thead' else 'td'
        for row in part:
            if L(row.tag) != 'row':
                continue
            rows += 1
            tds = []
            for en in row:
                if L(en.tag) != 'entry':
                    continue
                attrs = ''
                a, b = (cols.get(en.get('namest') or ''), cols.get(en.get('nameend') or ''))
                if a and b and (b > a):
                    attrs += ' colspan="%d"' % (b - a + 1)
                mr = en.get('morerows')
                if mr and mr.isdigit() and (int(mr) > 0):
                    attrs += ' rowspan="%d"' % (int(mr) + 1)
                al = en.get('align')
                if al in ('left', 'right', 'center'):
                    attrs += ' style="text-align:%s"' % al
                tds.append('<%s%s>%s</%s>' % (cell, attrs, inline(en, stats), cell))
            rows_html.append('<tr>%s</tr>' % ''.join(tds))
    return ('<table>%s</table>' % ''.join(rows_html), rows)

def float_html(el, assets, stats=None):
    kind = L(el.tag)
    label, caption = label_caption(el)
    name = label or el.get('id') or kind
    capel = next((c for c in el if L(c.tag) == 'caption'), None)
    cap_html = ' '.join((inline(p, stats) for p in capel if L(p.tag) in ('simple-para', 'para'))) if capel is not None else ''
    cap = '<div class="cap"><b>%s</b> %s</div>' % (html.escape(label), cap_html or html.escape(caption))
    if kind == 'table':
        tgs = [c for c in el if L(c.tag) == 'tgroup']
        if tgs:
            parts = [tgroup_html(t, stats) for t in tgs]
            body, ok = (''.join((h for h, _ in parts)), any((r for _, r in parts)))
        else:
            body, ok = images_html(el, assets)
        foot = [text_of(c) for c in el.iter() if L(c.tag) in ('table-footnote', 'legend')]
        foot_html = ''.join(('<div class="tfoot">%s</div>' % html.escape(t) for t in foot if t))
        return ('<div class="tbl">%s%s%s</div>' % (cap, body, foot_html), ok, name)
    body, ok = images_html(el, assets)
    return ('<div class="fig">%s%s</div>' % (body, cap), ok, name)

def _names(el):
    out = []
    for a in el:
        n = L(a.tag)
        if n in ('author', 'editor'):
            g = next((text_of(c) for c in a if L(c.tag) == 'given-name'), '')
            s = next((text_of(c) for c in a if L(c.tag) == 'surname'), '')
            out.append((g + ' ' + s).strip() or text_of(a))
        elif n == 'collaboration':
            out.append(text_of(a))
        elif n == 'et-al':
            out.append('et al.')
    return ', '.join((x for x in out if x))

def _first(el, name):
    return next((c for c in el.iter() if L(c.tag) == name), None)

def _t(el, name):
    c = _first(el, name) if el is not None else None
    return text_of(c) if c is not None else ''

def sb_text(ref):
    bits = []
    con = next((c for c in ref if L(c.tag) == 'contribution'), None)
    if con is not None:
        au = next((c for c in con if L(c.tag) == 'authors'), None)
        if au is not None and _names(au):
            bits.append(_names(au))
        tt = next((c for c in con if L(c.tag) == 'title'), None)
        if tt is not None and _t(tt, 'maintitle'):
            bits.append(_t(tt, 'maintitle'))
    for host in (c for c in ref if L(c.tag) == 'host'):
        h = []
        for kind in host:
            k = L(kind.tag)
            if k in ('issue', 'edited-book', 'book', 'e-host'):
                eds = next((c for c in kind if L(c.tag) == 'editors'), None)
                if eds is not None and _names(eds):
                    h.append('in: ' + _names(eds) + ' (Eds.)')
                tt = _first(kind, 'maintitle')
                if tt is not None:
                    h.append(text_of(tt))
                for nm in ('volume-nr', 'issue-nr', 'conference', 'edition', 'date'):
                    v = _t(kind, nm)
                    if v:
                        h.append({'issue-nr': '(%s)', 'date': '(%s)'}.get(nm, '%s') % v)
                pub = _first(kind, 'publisher')
                if pub is not None and text_of(pub):
                    h.append(text_of(pub))
                url = _first(kind, 'inter-ref')
                if url is not None and text_of(url):
                    h.append(text_of(url))
        fp, lp, an = (_t(host, 'first-page'), _t(host, 'last-page'), _t(host, 'article-number'))
        if fp:
            h.append(fp + ('–' + lp if lp else ''))
        elif an:
            h.append(an)
        d = _t(host, 'doi')
        if d:
            h.append('doi:' + d)
        if h:
            bits.append(' '.join(h))
    cm = _t(ref, 'comment')
    if cm:
        bits.append(cm)
    return ', '.join(bits) or text_of(ref)

def ref_text(bib):
    st = [c for c in bib.iter() if L(c.tag) == 'source-text']
    if st and text_of(st[0]):
        return text_of(st[0])
    parts = []
    for c in bib:
        n = L(c.tag)
        if n == 'other-ref':
            parts.append(text_of(c))
        elif n == 'reference':
            parts.append(sb_text(c))
    t = '; '.join((p for p in parts if p))
    return t or text_skip(bib, {'label'})

class Doc:

    def __init__(self, root, assets=None):
        self.assets = assets or {}
        self.title, self.authors, self.doi = ('', [], '')
        cd = next((el for el in root if L(el.tag) == 'coredata'), None)
        if cd is not None:
            for el in cd:
                n = L(el.tag)
                if n == 'title' and (not self.title):
                    self.title = text_of(el)
                elif n == 'doi' and (not self.doi):
                    self.doi = text_of(el)
                elif n == 'creator':
                    t = text_of(el)
                    if t and ',' in t:
                        sur, _, giv = t.partition(',')
                        self.authors.append((giv.strip() + ' ' + sur.strip()).strip())
                    elif t:
                        self.authors.append(t)
        ot = next((el for el in root if L(el.tag) == 'originalText'), None)
        self.ot = ot
        if not self.authors and ot is not None:
            for el in ot.iter():
                if L(el.tag) == 'author':
                    g = next((text_of(c) for c in el if L(c.tag) == 'given-name'), '')
                    s_ = next((text_of(c) for c in el if L(c.tag) == 'surname'), '')
                    if s_:
                        self.authors.append((g + ' ' + s_).strip())
        if not self.title:
            for el in root.iter():
                if L(el.tag) == 'normalized-article-title' and text_of(el):
                    self.title = text_of(el)
                    break
        self.corr, self.corr_note = self._correspondence(ot)
        self.stats = {}
        self.plain = []
        scope = list(ot.iter()) if ot is not None else []
        self.floats = [el for el in scope if L(el.tag) in FLOAT]
        self.by_id = {el.get('id'): el for el in self.floats if el.get('id')}
        self.bibs = [el for el in scope if L(el.tag) == 'bib-reference']
        self.placed = set()
        self.parts = []
        self.done = {'figure': [], 'table': []}
        self.miss = {'figure': [], 'table': []}
        if ot is not None:
            self.walk(ot)
        for el in self.floats:
            self.put(el)
        self.refs = [(next((text_of(c) for c in b if L(c.tag) == 'label'), '') or '[%d]' % (i + 1), ref_text(b)) for i, b in enumerate(self.bibs)]

    @staticmethod
    def _correspondence(ot):
        if ot is None:
            return ({}, '')
        cors = {el.get('id'): el for el in ot.iter() if L(el.tag) == 'correspondence' and el.get('id')}
        found, mails = ({}, [])
        for au in ot.iter():
            if L(au.tag) != 'author':
                continue
            g = next((text_of(c) for c in au if L(c.tag) == 'given-name'), '')
            s_ = next((text_of(c) for c in au if L(c.tag) == 'surname'), '')
            name = (g + ' ' + s_).strip()
            em = [text_of(c) for c in au if L(c.tag) == 'e-address' and text_of(c)]
            refs = {r for c in au if L(c.tag) in ('cross-ref', 'cross-refs') for r in (c.get('refid') or '').split()}
            if name and refs & set(cors):
                found[name] = em
            mails += ['%s (%s)' % (m, name) for m in em]
        if not found:
            return ({}, '')
        txt = [text_of(c) for el in cors.values() for c in el if L(c.tag) == 'text' and text_of(c)]
        note = '* Corresponding author%s: %s.' % ('s' if len(found) > 1 else '', ', '.join(found))
        if txt:
            note += ' ' + ' '.join(dict.fromkeys(txt))
        cm = ['%s (%s)' % (m, n) for n, ems in found.items() for m in ems]
        if cm or mails:
            note += ' E-mail: ' + '; '.join(cm or mails) + '.'
        return (found, note)

    def author_line(self):
        keys = {re.sub('\\W+', '', n).lower() for n in self.corr}
        sur = {(n.split()[-1].lower(), n[:1].lower()) for n in self.corr if n.split()}
        out = []
        for a in self.authors[:30]:
            k = re.sub('\\W+', '', a).lower()
            hit = k in keys or (a.split() and (a.split()[-1].lower(), a[:1].lower()) in sur)
            out.append(a + ('*' if hit else ''))
        return ', '.join(out)

    def put(self, el):
        if id(el) in self.placed:
            return
        self.placed.add(id(el))
        h, ok, name = float_html(el, self.assets, self.stats)
        k = L(el.tag)
        (self.done if ok else self.miss)[k].append(name)
        self.parts.append(('float', 0, h))

    def walk(self, el):
        for ch in el:
            n = L(ch.tag)
            if n in SKIP:
                continue
            if n in FLOAT:
                self.put(ch)
                continue
            if n == 'section-title':
                lvl = ch.get('ce:level') or ch.get('{http://www.elsevier.com/xml/common/dtd}level') or '2'
                lvl = int(lvl) if str(lvl).isdigit() else 2
                t = inline(ch, self.stats)
                if t:
                    self.parts.append(('h', min(max(lvl, 1), 4) + 1, t))
                continue
            if n == 'label' and L(el.tag) == 'section':
                t = text_of(ch)
                if t:
                    self.parts.append(('hl', 0, html.escape(t)))
                continue
            if n in PARA:
                t = eq_para(ch, self.stats) or inline(ch, self.stats)
                if t:
                    self.parts.append(('p', 0, t))
                    self.plain.append(text_skip(ch))
                for sub in ch.iter():
                    if sub is not ch and L(sub.tag) in FLOAT:
                        self.put(sub)
                for x in ch.iter():
                    if L(x.tag) in ('cross-ref', 'cross-refs'):
                        for rid in (x.get('refid') or '').split():
                            if rid in self.by_id:
                                self.put(self.by_id[rid])
                continue
            if n == 'keywords':
                kws = [text_of(k) for k in ch if L(k.tag) == 'keyword' and text_of(k)]
                if kws:
                    st = next((text_of(c) for c in ch if L(c.tag) == 'section-title'), '') or 'Keywords'
                    self.parts += [('h', 3, html.escape(st)), ('p', 0, html.escape('; '.join(kws)))]
                continue
            if n == 'abstract' and (not any((L(c.tag) == 'section-title' for c in ch))):
                self.parts.append(('h', 3, 'Abstract'))
            self.walk(ch)

    def completeness(self):
        refs_ok = [(lab, t) for lab, t in self.refs if t]
        missing = ['fig:' + x for x in self.miss['figure']] + ['table:' + x for x in self.miss['table']] + ['ref:' + lab for lab, t in self.refs if not t]
        F = len(self.done['figure']) + len(self.miss['figure'])
        T = len(self.done['table']) + len(self.miss['table'])
        m = self.stats.get('math', 0)
        return {'refs': [len(refs_ok), len(self.bibs)], 'figs': [len(self.done['figure']), F], 'tables': [len(self.done['table']), T], 'missing': missing, 'v': VERSION, 'math': [m - self.stats.get('dropped', 0), m], 'math_junk': self.stats.get('junk', 0)}

def build(root):
    d = Doc(root)
    return (d.title, d.authors, [p for p in d.parts if p[0] in ('h', 'p')])
STYLE = 'body{font-family:"DejaVu Serif","Noto Serif CJK SC","Noto Sans CJK SC","AR PL UMing CN","WenQuanYi Zen Hei",serif;\nfont-size:10.5pt;line-height:1.45;margin:0}\n.x2p{font-family:"DejaVu Sans","Noto Sans CJK SC","Noto Serif CJK SC","AR PL UMing CN","WenQuanYi Zen Hei",sans-serif;\nfont-size:8.5pt;line-height:1.4;border:1px solid #999;background:#f3f3f3;padding:4pt 6pt;margin:0 0 10pt}\n.x2p .miss{color:#a00;font-weight:bold}\nh1{font-size:16pt;line-height:1.3;margin:0 0 6pt}\nh2{font-size:12.5pt;margin:14pt 0 4pt}\nh3{font-size:11pt;margin:10pt 0 3pt}\nh4{font-size:10.5pt;margin:8pt 0 3pt;font-style:italic}\n.au{font-size:10pt;color:#333;margin:0 0 14pt}\np,.p{margin:0 0 6pt;text-align:justify}\n.p2{margin:2pt 0}\n.li{margin:3pt 0 3pt 1.2em}\n.li .lab{font-weight:bold}\n.eq{display:flex;align-items:center;margin:6pt 0;break-inside:avoid}\n.eqm{flex:1;text-align:center}\n.eqn{margin-left:8pt;white-space:nowrap}\nmath{font-family:"STIX Two Math","Latin Modern Math","DejaVu Math TeX Gyre","Noto Sans Math",math}\n.corr{font-size:8.5pt;color:#333;margin:-10pt 0 14pt}\n.fig,.tbl{margin:8pt 0 10pt;break-inside:avoid}\n.fig img,.tbl img{display:block;max-width:100%;max-height:21cm;margin:0 auto 4pt}\n.cap{font-size:9pt;line-height:1.35}\n.nofig{border:1px dashed #a00;color:#a00;padding:18pt 6pt;text-align:center;font-size:9pt;margin:0 0 4pt}\ntable{border-collapse:collapse;width:100%;font-size:7.5pt;line-height:1.3;margin:3pt 0}\nth,td{border-top:0.5pt solid #888;border-bottom:0.5pt solid #888;padding:1.5pt 3pt;vertical-align:top;text-align:left}\nth{font-weight:bold}\n.tfoot{font-size:8pt;color:#333}\nol.refs{list-style:none;padding:0;margin:0;font-size:9pt;line-height:1.35}\nol.refs li{margin:0 0 3pt;padding-left:2.6em;text-indent:-2.6em}'

def banner(c, doi):
    e = html.escape
    line = '转换版 · 出版社 XML 排版，非出版社 PDF · 参考文献 %d/%d · 图 %d/%d · 表 %d/%d' % tuple(c['refs'] + c['figs'] + c['tables'])
    miss = []
    if c['refs'][0] < c['refs'][1]:
        miss.append('缺参考文献 %d 条' % (c['refs'][1] - c['refs'][0]))
    if c['figs'][0] < c['figs'][1]:
        names = [m[4:] for m in c['missing'] if m.startswith('fig:')]
        miss.append('缺图 %d 张（%s）' % (len(names), '、'.join(names[:8]) + ('…' if len(names) > 8 else '')))
    if c['tables'][0] < c['tables'][1]:
        names = [m[6:] for m in c['missing'] if m.startswith('table:')]
        miss.append('缺表 %d 张（%s）' % (len(names), '、'.join(names[:8])))
    tail = MARK + (' · DOI ' + doi if doi else '')
    return '<div class="x2p">%s<br>%s%s</div>' % (e(line), e(tail), '<br><span class="miss">%s</span>' % e('；'.join(miss)) if miss else '')

def to_html(title, authors, parts, refs=None, comp=None, doi='', author_line=None, corr_note=''):
    e = html.escape
    h = ['<!doctype html><html><head><meta charset="utf-8"><title>%s</title><style>%s</style></head><body>' % (e(title), STYLE)]
    if comp is not None:
        h.append(banner(comp, doi))
    h.append('<h1>%s</h1>' % e(title))
    if authors:
        h.append('<div class="au">%s</div>' % e(author_line or ', '.join(authors[:30])))
    if corr_note:
        h.append('<div class="corr">%s</div>' % e(corr_note))
    pend = ''
    for kind, lvl, t in parts:
        if kind == 'hl':
            pend = t + ' '
            continue
        if kind == 'h':
            h.append('<h%d>%s%s</h%d>' % (lvl, pend, t, lvl))
        elif kind == 'float':
            h.append(t)
        else:
            if pend:
                h.append('<div class="p"><b>%s</b></div>' % pend)
            h.append('<div class="p">%s</div>' % t)
        pend = ''
    if refs:
        h.append('<h2>References</h2><ol class="refs">')
        h += ['<li>%s %s</li>' % (e(lab), e(t)) for lab, t in refs if t]
        h.append('</ol>')
    h.append('</body></html>')
    return '\n'.join(h)

def _drop(path):
    if os.path.exists(path):
        os.unlink(path)

def find_chrome():
    env = os.environ.get('X2P_CHROME')
    if env:
        p = os.path.expanduser(env)
        if not (os.path.isfile(p) and os.access(p, os.X_OK)):
            raise RenderError('X2P_CHROME 不可执行: %s' % env)
        return p
    for name in CHROME_CANDIDATES:
        p = shutil.which(name)
        if p:
            return p
    for p in CHROME_FALLBACK:
        p = os.path.expanduser(p)
        if os.access(p, os.X_OK):
            return p
    raise RenderError('找不到 chrome（设 X2P_CHROME 或装 google-chrome）')

def convert_file(xml_path, pdf_path, assets=None):
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as e:
        raise ValueError('XML 解析失败: %s' % e)
    d = Doc(root, assets)
    body = d.plain
    if not d.title or len(' '.join(body)) < MIN_BODY:
        raise ValueError('XML 里没有可用正文（题名=%r 正文段=%d）' % (d.title[:40], len(body)))
    comp = d.completeness()
    chrome = find_chrome()
    with tempfile.TemporaryDirectory(prefix='x2p-') as td:
        hp = os.path.join(td, 'a.html')
        with open(hp, 'w', encoding='utf-8') as f:
            f.write(to_html(d.title, d.authors, d.parts, d.refs, comp, d.doi, d.author_line(), d.corr_note))
        try:
            r = subprocess.run([chrome, '--headless=new', '--disable-gpu', '--no-sandbox', '--no-pdf-header-footer', '--virtual-time-budget=5000', '--user-data-dir=' + os.path.join(td, 'prof'), '--print-to-pdf=' + pdf_path, 'file://' + hp], capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            _drop(pdf_path)
            raise RenderError('chrome 打印超时(180s)')
        if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) < MIN_PDF_BYTES:
            _drop(pdf_path)
            raise RenderError('chrome 打印失败: %s' % ((r.stderr or '')[-200:] or '产物缺失或过小'))
        return {'title': d.title, 'authors': d.authors, 'paras': len(body), 'bytes': os.path.getsize(pdf_path), 'completeness': comp}

def to_pdf(xml_bytes, assets=None):
    with tempfile.TemporaryDirectory(prefix='x2p-') as td:
        src, dst = (os.path.join(td, 'in.xml'), os.path.join(td, 'out.pdf'))
        with open(src, 'wb') as f:
            f.write(xml_bytes)
        info = convert_file(src, dst, assets)
        with open(dst, 'rb') as f:
            out = PdfBytes(f.read())
        out.completeness = info['completeness']
        return out

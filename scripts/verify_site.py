#!/usr/bin/env python3
"""Check generated Hugo output, including base-path links."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote
import sys
root=Path(sys.argv[1]); mode=sys.argv[2]
class Doc(HTMLParser):
    def __init__(self,s):
        super().__init__(); self.links=[]; self.ids=set(); self.feed(s)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.ids.add(a['id'])
        if tag=='a' and a.get('href'):self.links.append(a['href'])
home=(root/'index.html').read_text()
article=(root/'posts/deep-to-deep-series-01/index.html').read_text()
if mode=='baseline':
    assert '首页' in home and 'header-menu' in home
    assert 'class="toc"' in article and 'reading-toc' not in article
    print('BASELINE PASS: original navigation=7; inline TOC')
    sys.exit(0)
count=0
for f in root.rglob('*.html'):
    s=f.read_text()
    if 'http-equiv="refresh"' in s:continue
    count+=1
    assert 'class="top-nav"' in s, str(f)
    nav=s.split('class="top-nav"',1)[1].split('</nav>',1)[0]
    assert nav.count('<a ')==3 and all(t in nav for t in ['博客','简介','关于']),str(f)
    for link in Doc(s).links:
        u=urlsplit(link)
        if u.scheme in ('mailto','tel'):continue
        if u.netloc and u.netloc not in ('jlenoch1.github.io','localhost:1313'):continue
        if u.path and not u.path.startswith('/snowblog/'):raise AssertionError((f,link))
        target=root/unquote(u.path.removeprefix('/snowblog/')) if u.path else f
        if target.is_dir():target=target/'index.html'
        assert target.exists(),(f,link,target)
        if u.fragment:assert unquote(u.fragment) in Doc(target.read_text()).ids,(f,link)
assert 'reading-toc' in article and 'class="toc"' not in article
assert all('#'+t in article for t in ['认知','思考','成长'])
assert '项目整理中' in (root/'projects/index.html').read_text()
assert '这里还没有文章' in (root/'thoughts/index.html').read_text() if mode=='modified' else True
assert all(t in (root/'about/index.html').read_text() for t in ['社会现象','个体成长','个体行为','AI 实践','客户端安全','Links'])
if mode=='fixture':
    thoughts=(root/'thoughts/index.html').read_text()
    assert '独立测试文章' in thoughts and '系列测试文章' not in thoughts
    assert '独立测试文章' in (root/'tags/测试/index.html').read_text()
print(f'{mode.upper()} PASS: {count} pages; navigation=3; links/anchors valid; tags; right TOC; about/projects')

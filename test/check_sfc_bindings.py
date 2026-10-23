#!/usr/bin/env python
"""核对 Vue SFC 模板引用是否都在 script setup 中声明（防 importVisible 类静默失效）。"""
import re, sys, pathlib

BLACKLIST = set('''template div span el el-icon button select option input form form-item card empty tag
pagination dialog drawer checkbox radio radio-group input-number badge alert progress skeleton message
message-box upload if else for of key class style type size label round effect plain light dark disabled
loading visible closable show text inside indeterminate align center width popper header footer title never
shadow container active banner close info msg change click circle clearable confirm copy create creation
current danger description difficulty draft file group heading icon id image item large layout left length
link main meta model module muted name next origin pager placeholder position prev primary published px
score small source status stroke subtitle success tip toolbar top value action actions animate animated
batch body btn catalog catalogs course drafts imported item submitted saved question qt ai_gen model
required max min step precision controls auto limit drag on remove exceed accept multiple'''.split())

def check(path):
    src = pathlib.Path(path).read_text(encoding='utf-8')
    head = src.split('<script setup>', 1)[0]
    if '<template>' not in head or '</template>' not in head:
        return []
    tpl = head[head.index('<template>') + len('<template>'):head.rindex('</template>')]
    script = src.split('<script setup>', 1)[1].split('</script>', 1)[0]
    ids = set(re.findall(r'[A-Za-z_$][A-Za-z0-9_$]*', tpl))
    declared = set(re.findall(r'(?:const|let|var|function)\s+([A-Za-z_$][\w$]*)', script))
    for m in re.findall(r'(?:const|let|var)\s*\{([^}]+)\}', script):
        declared |= {p.split(':')[-1].strip() for p in m.split(',') if p.strip()}
    for m in re.findall(r'import\s+\{([^}]+)\}', script):
        declared |= {p.split(' as ')[-1].strip() for p in m.split(',') if p.strip()}
    declared |= set(re.findall(r'import\s+([A-Za-z_$][\w$]*)\s+from', script))
    for m in re.findall(r'v-for="([^"]+)"', tpl):
        parts = m.split(' in ')
        if len(parts) == 2:
            declared |= {v.strip() for v in parts[0].replace('(', '').replace(')', '').split(',')}
    declared |= set(re.findall(r'defineProps\(\s*\{([^}]+)\}', script)[0].split(':')[0].split(',') if 'defineProps' in script else [])
    for m in re.findall(r'props\.(\w+)', script):
        declared.add(m)
    missing = sorted(
        i for i in ids - declared - BLACKLIST
        if not i[0].isupper() and i not in ('true', 'false', 'null', 'undefined', 'of', 'in', 'on', 'to', 'new', 'await', 'return')
    )
    return missing

bad = 0
for p in sys.argv[1:]:
    m = check(p)
    if m:
        bad = 1
        print(f"{p}: MISSING {m}")
    else:
        print(f"{p}: OK")
sys.exit(bad)

import sys, os, re, json, collections
ROOTS = {
 "kfp/v6.0.0(k5)": "/private/tmp/claude-501/-Users-juli-Desktop-Claude/ec137c75-6d2e-4a41-bb2c-d385126baef6/scratchpad/kfp/v6.0.0",
 "kfp/v7.0.0(k6)": "/private/tmp/claude-501/-Users-juli-Desktop-Claude/ec137c75-6d2e-4a41-bb2c-d385126baef6/scratchpad/kfp/v7.0.0",
 "kfp/v8.0.0(k8)": "/private/tmp/claude-501/-Users-juli-Desktop-Claude/ec137c75-6d2e-4a41-bb2c-d385126baef6/scratchpad/kfp/v8.0.0",
 "kfp/v9.0.0(k9)": "/private/tmp/claude-501/-Users-juli-Desktop-Claude/ec137c75-6d2e-4a41-bb2c-d385126baef6/scratchpad/kfp/v9.0.0",
 "kfp/master(k10)": "/private/tmp/claude-501/-Users-juli-Desktop-Claude/ec137c75-6d2e-4a41-bb2c-d385126baef6/scratchpad/kfp/master",
 "repo/kicad5": "/Users/juli/Desktop/Claude/kicadfp/tests/fixtures/kicad5",
 "repo/kicad6": "/Users/juli/Desktop/Claude/kicadfp/tests/fixtures/kicad6",
 "repo/kicad8": "/Users/juli/Desktop/Claude/kicadfp/tests/fixtures/kicad8",
 "repo/kicad9": "/Users/juli/Desktop/Claude/kicadfp/tests/fixtures/kicad9",
 "repo/kicad10dev": "/Users/juli/Desktop/Claude/kicadfp/tests/fixtures/kicad10dev",
}
TOK = re.compile(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()"]+')
def tokens(s):
    for m in TOK.finditer(s):
        yield m.group(0)
def parse(s):
    stack=[[]]
    for t in tokens(s):
        if t=='(': stack.append([])
        elif t==')':
            l=stack.pop(); stack[-1].append(l)
        else: stack[-1].append(t)
    return stack[0]
def walk(node, parent=None):
    if isinstance(node, list):
        yield node, parent
        for c in node:
            yield from walk(c, node)
res = {}
for name, root in ROOTS.items():
    st = dict(files=0, layer_tokens=collections.Counter(), layers_tokens=collections.Counter(),
              layer_quoted=collections.Counter(), layers_quoted=collections.Counter(),
              layers_combo=collections.Counter(), pad_type_layers=collections.Counter(),
              version=collections.Counter(), knockout=0, layer_parent=collections.Counter(),
              layers_parent=collections.Counter(), unusual=collections.Counter())
    for dp, dn, fn in os.walk(root):
        for f in fn:
            if not f.endswith('.kicad_mod'): continue
            p=os.path.join(dp,f)
            try: s=open(p,encoding='utf-8',errors='replace').read()
            except Exception as e: continue
            st['files']+=1
            try: tree=parse(s)
            except Exception as e: st['unusual']['parse_error']+=1; continue
            top = tree[0] if tree and isinstance(tree[0], list) else None
            if top:
                for i,x in enumerate(top):
                    if isinstance(x,list) and x and x[0]=='version': st['version'][x[1]]+=1
            for node,parent in walk(tree):
                if not node: continue
                h=node[0]
                if h=='layer' and len(node)>=2 and isinstance(node[1],str):
                    raw=node[1]; q=raw.startswith('"'); v=raw.strip('"')
                    st['layer_tokens'][v]+=1; st['layer_quoted'][q]+=1
                    st['layer_parent'][parent[0] if parent and isinstance(parent[0],str) else '?']+=1
                    if len(node)>2: 
                        for extra in node[2:]:
                            if extra=='knockout': st['knockout']+=1
                            else: st['unusual']['layer_extra:'+str(extra)]+=1
                elif h=='layers':
                    vals=[]
                    for raw in node[1:]:
                        if not isinstance(raw,str): st['unusual']['layers_nonstr']+=1; continue
                        q=raw.startswith('"'); v=raw.strip('"')
                        st['layers_tokens'][v]+=1; st['layers_quoted'][q]+=1; vals.append(v)
                    combo=' '.join(vals); st['layers_combo'][combo]+=1
                    ph = parent[0] if parent and isinstance(parent[0],str) else '?'
                    st['layers_parent'][ph]+=1
                    if ph=='pad':
                        ptype = parent[2] if len(parent)>2 else '?'
                        st['pad_type_layers'][ptype+' | '+combo]+=1
    res[name]={k:(dict(v.most_common()) if isinstance(v,collections.Counter) else v) for k,v in st.items()}
json.dump(res, open('/private/tmp/claude-501/-Users-juli-Desktop-Claude/ec137c75-6d2e-4a41-bb2c-d385126baef6/scratchpad/research/scan_layers.json','w'), indent=1, ensure_ascii=False)
for name,st in res.items():
    print('=====',name,'files',st['files'],'versions',st['version'])
    print(' layer quoted:',st['layer_quoted'],' layers quoted:',st['layers_quoted'],' knockout:',st['knockout'])
    print(' layer tokens:',st['layer_tokens'])
    print(' layers tokens:',st['layers_tokens'])
    print(' layer parents:',st['layer_parent'])
    print(' layers parents:',st['layers_parent'])
    print(' top combos:',dict(list(st['layers_combo'].items())[:25]))
    print(' pad type|layers:',dict(list(st['pad_type_layers'].items())[:40]))
    print(' unusual:',st['unusual'])

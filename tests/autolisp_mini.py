"""Interpretor minimal AutoLISP (subset) folosit doar pentru testarea offline a TopoKit.lsp.

Emuleaza impartirea intreaga, scoparea dinamica si functiile de liste/geometrie
folosite de TopoKit; functiile AutoCAD (entget, entmake...) sunt simulate in teste.
"""
# Mini interpretor AutoLISP (subset) pentru testarea TopoKit.lsp
import math, re, sys
class Sym(str): pass
class DP:
    def __init__(s,a,d): s.car=a; s.cdr=d
    def __eq__(s,o): return isinstance(o,DP) and s.car==o.car and s.cdr==o.cdr
    def __repr__(s): return f"({s.car!r} . {s.cdr!r})"
T=Sym('T'); NIL=None
def tokenize(src):
    toks=[];i=0;n=len(src)
    while i<n:
        c=src[i]
        if c.isspace(): i+=1
        elif c==';':
            if src.startswith(';|',i): i=src.index('|;',i)+2
            else:
                j=src.find('\n',i); i=n if j<0 else j
        elif c in "()'": toks.append(c); i+=1
        elif c=='"':
            j=i+1; s=''
            while src[j]!='"':
                if src[j]=='\\':
                    e=src[j+1]; s+={'n':'\n','t':'\t','\\':'\\','"':'"','r':'\r','e':'\x1b'}.get(e,e); j+=2
                else: s+=src[j]; j+=1
            toks.append(('str',s)); i=j+1
        else:
            j=i
            while j<n and not src[j].isspace() and src[j] not in "()';\"": j+=1
            toks.append(src[i:j]); i=j
    return toks
def atom(t):
    if isinstance(t,tuple): return t[1]
    if re.fullmatch(r'[-+]?\d+',t): return int(t)
    try:
        if re.fullmatch(r'[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?',t): return float(t)
    except: pass
    return Sym(t.upper())
def parse(toks):
    pos=[0]
    def rd():
        t=toks[pos[0]]; pos[0]+=1
        if t=='(':
            l=[]
            while toks[pos[0]]!=')':
                if toks[pos[0]]=='.' :
                    pos[0]+=1; d=rd(); assert toks[pos[0]]==')'; pos[0]+=1
                    assert l; r=DP(l[-1],d)
                    for x in reversed(l[:-1]): r=DP(x,r)   # lista improprie (a b . c)
                    return r
                l.append(rd())
            pos[0]+=1; return l if l else None
        if t==')': raise SyntaxError('unexpected )')
        if t=="'": return [Sym('QUOTE'),rd()]
        return atom(t)
    out=[]
    while pos[0]<len(toks): out.append(rd())
    return out
env={}; funcs={}
class UFun:
    def __init__(s,params,locs,body,name='lambda'): s.params=params;s.locs=locs;s.body=body;s.name=name
def splitargs(a):
    a=a or []
    if Sym('/') in a: k=a.index(Sym('/')); return a[:k],a[k+1:]
    return a,[]
def truthy(v): return not (v is None or v==[] )
def lst(v): return [] if v is None else v
def call(f,args):
    if isinstance(f,Sym): f=lookupf(f)
    if isinstance(f,list) and f and f[0]==Sym('LAMBDA'): f=mkl(f)
    if callable(f): return f(*args)
    if isinstance(f,UFun):
        if len(args)!=len(f.params): raise TypeError(f"{f.name}: args {len(args)} vs {len(f.params)}")
        syms=f.params+f.locs; old={s:env.get(s) for s in syms}
        for s in f.locs: env[s]=None
        for s,v in zip(f.params,args): env[s]=v
        # local function defs (e.g. *error*) : store in env too
        try:
            r=None
            for x in f.body: r=ev(x)
            return r
        except Exception as ex:
            if not hasattr(ex,'lisp_trace'): ex.lisp_trace=[]
            ex.lisp_trace.append(str(f.name))
            raise
        finally:
            for s in syms: env[s]=old[s]
    raise TypeError(f"not callable {f!r}")
def mkl(x): p,l=splitargs(x[1]); return UFun(p,l,x[2:])
def lookupf(s):
    v=env.get(s)
    if isinstance(v,(UFun,)) or callable(v): return v
    if s in funcs: return funcs[s]
    raise NameError(f"no function {s}")
def ev(x):
    if isinstance(x,Sym):
        if x=='T': return T
        if x=='NIL': return None
        if x=='PI': return math.pi
        return env.get(x)
    if not isinstance(x,list): return x
    h=x[0]
    if h=='QUOTE': return x[1]
    if h=='FUNCTION': return x[1]
    if h=='SETQ':
        r=None
        for i in range(1,len(x),2): r=ev(x[i+1]); env[x[i]]=r
        return r
    if h=='DEFUN':
        p,l=splitargs(x[2]); env[x[1]]=UFun(p,l,x[3:],x[1]); return x[1]
    if h=='LAMBDA': return mkl(x)
    if h=='IF':
        if truthy(ev(x[1])): return ev(x[2])
        return ev(x[3]) if len(x)>3 else None
    if h=='COND':
        for cl in x[1:]:
            v=ev(cl[0])
            if truthy(v):
                for e in cl[1:]: v=ev(e)
                return v
        return None
    if h=='PROGN':
        r=None
        for e in x[1:]: r=ev(e)
        return r
    if h=='AND':
        for e in x[1:]:
            if not truthy(ev(e)): return None
        return T
    if h=='OR':
        for e in x[1:]:
            if truthy(ev(e)): return T
        return None
    if h=='WHILE':
        r=None
        while truthy(ev(x[1])):
            for e in x[2:]: r=ev(e)
        return r
    if h=='REPEAT':
        r=None
        for _ in range(ev(x[1])):
            for e in x[2:]: r=ev(e)
        return r
    if h=='FOREACH':
        s=x[1]; old=env.get(s); r=None
        for v in lst(ev(x[2])):
            env[s]=v
            for e in x[3:]: r=ev(e)
        env[s]=old; return r
    f=lookupf(h) if isinstance(h,Sym) else ev(h)
    return call(f,[ev(a) for a in x[1:]])
def B(name):
    def d(fn): funcs[Sym(name.upper())]=fn; return fn
    return d
def num_div(*a):
    r=a[0]
    for b in a[1:]:
        if isinstance(r,int) and isinstance(b,int): r=int(r/b) if b else (_ for _ in ()).throw(ZeroDivisionError('divide by zero'))
        else: r=r/b
    return r
funcs.update({Sym(k):v for k,v in {
 '+':lambda *a: sum(a) if a else 0,'-':lambda *a: -a[0] if len(a)==1 else a[0]-sum(a[1:]),
 '*':lambda *a: math.prod(a),'/':num_div,'1+':lambda a:a+1,'1-':lambda a:a-1,
 'ABS':abs,'SQRT':lambda a: math.sqrt(a),'SIN':math.sin,'COS':math.cos,'EXP':math.exp,'LOG':math.log,
 'ATAN':lambda a,b=None: math.atan(a) if b is None else math.atan2(a,b),
 'EXPT':lambda a,b: a**b,'FIX':lambda a:int(a),'FLOAT':float,'REM':lambda a,b: math.fmod(a,b) if isinstance(a,float) or isinstance(b,float) else int(math.fmod(a,b)),
 'MIN':lambda *a: min(a),'MAX':lambda *a: max(a),'MINUSP':lambda a: T if a<0 else None,'ZEROP':lambda a: T if a==0 else None,
 'LOGAND':lambda *a: __import__('functools').reduce(lambda x,y:x&y,a),
 '=':lambda *a: T if all(a[i]==a[i+1] for i in range(len(a)-1)) else None,
 '/=':lambda a,b: T if a!=b else None,
 '<':lambda *a: T if all(a[i]<a[i+1] for i in range(len(a)-1)) else None,
 '>':lambda *a: T if all(a[i]>a[i+1] for i in range(len(a)-1)) else None,
 '<=':lambda *a: T if all(a[i]<=a[i+1] for i in range(len(a)-1)) else None,
 '>=':lambda *a: T if all(a[i]>=a[i+1] for i in range(len(a)-1)) else None,
 'NULL':lambda a: T if not truthy(a) else None,'NOT':lambda a: T if not truthy(a) else None,
 'LIST':lambda *a: list(a) if a else None,'PRINC':lambda *a: (print(a[0],end='') if a and isinstance(a[0],str) else None) or (a[0] if a else None),
 'LENGTH':lambda a: len(lst(a)),'REVERSE':lambda a: list(reversed(lst(a))) or None,
 'APPEND':lambda *a: sum((lst(x) for x in a),[]) or None,
 'NTH':lambda n,l: lst(l)[n] if n<len(lst(l)) else None,
 'LAST':lambda l: l[-1],'STRCAT':lambda *a:''.join(a),'ITOA':lambda a:str(a),'STRLEN':len,
 'SUBSTR':lambda s,i,n=None: s[i-1:] if n is None else s[i-1:i-1+n],
 'VL-STRING-SEARCH':lambda p,s,st=0: (lambda r: None if r<0 else r)(s.find(p,st)),
 'VL-STRING-TRIM':lambda c,s: s.strip(c),'VL-STRING-RIGHT-TRIM':lambda c,s: s.rstrip(c),
 'STRCASE':lambda s,lo=None: s.lower() if truthy(lo) else s.upper(),
 'SET':lambda s,v: env.__setitem__(s,v) or v,'EVAL':lambda x: ev(x),
 'VL-LOAD-COM':lambda:None,'NUMBERP':lambda a: T if isinstance(a,(int,float)) else None,
}.items()})
def car(x): return x.car if isinstance(x,DP) else (x[0] if x else None)
def cdr(x):
    if isinstance(x,DP): return x.cdr
    return (x[1:] or None) if x else None
funcs[Sym('CAR')]=car; funcs[Sym('CDR')]=cdr
for nm in ['CADR','CADDR','CADDDR','CAAR','CADAR','CDDR','CDAR']:
    ops=nm[1:-1][::-1]
    def mk(ops):
        def f(x):
            for o in ops: x=car(x) if o=='A' else cdr(x)
            return x
        return f
    funcs[Sym(nm)]=mk(ops)
@B('cons')
def _cons(a,b):
    if b is None: return [a]
    if isinstance(b,list): return [a]+b
    return DP(a,b)
@B('assoc')
def _assoc(k,l):
    for e in lst(l):
        if car(e)==k: return e
    return None
@B('member')
def _member(k,l):
    l=lst(l)
    for i,e in enumerate(l):
        if e==k: return l[i:]
    return None
@B('subst')
def _subst(new,old,l): return [new if e==old else e for e in lst(l)]
@B('eq')
def _eq(a,b): return T if a==b else None
@B('equal')
def _equal(a,b,f=0.0):
    def eqf(a,b):
        if isinstance(a,(int,float)) and isinstance(b,(int,float)): return abs(a-b)<=f
        if isinstance(a,list) and isinstance(b,list): return len(a)==len(b) and all(eqf(x,y) for x,y in zip(a,b))
        return a==b
    return T if eqf(a,b) else None
@B('mapcar')
def _mapcar(f,*ls):
    ls=[lst(l) for l in ls]; n=min(len(l) for l in ls)
    return [call(f,[l[i] for l in ls]) for i in range(n)] or None
@B('apply')
def _apply(f,a): return call(f,lst(a))
@B('vl-remove-if')
def _rif(f,l): return [e for e in lst(l) if not truthy(call(f,[e]))] or None
@B('vl-remove-if-not')
def _rifn(f,l): return [e for e in lst(l) if truthy(call(f,[e]))] or None
@B('vl-every')
def _every(f,l): return T if all(truthy(call(f,[e])) for e in lst(l)) else None
@B('vl-some')
def _some(f,l):
    for e in lst(l):
        r=call(f,[e])
        if truthy(r): return r
    return None
@B('vl-sort')
def _sort(l,f):
    import functools
    return sorted(lst(l),key=functools.cmp_to_key(lambda a,b: -1 if truthy(call(f,[a,b])) else (1 if truthy(call(f,[b,a])) else 0))) or None
@B('distance')
def _dist(a,b):
    if len(a)>2 and len(b)>2: return math.dist(a[:3],b[:3])
    return math.dist(a[:2],b[:2])
@B('angle')
def _angle(a,b): r=math.atan2(b[1]-a[1],b[0]-a[0]); return r+2*math.pi if r<0 else r
@B('polar')
def _polar(p,a,d): return [p[0]+d*math.cos(a),p[1]+d*math.sin(a)]+list(p[2:])
@B('trans')
def _trans(p,frm,to):
    # doar normale (0 0 1) in teste
    return list(map(float,p))
@B('rtos')
def _rtos(v,m=2,pr=4): return f"{v:.{pr}f}"
@B('type')
def _type(x): return Sym('STR') if isinstance(x,str) else None
def load(path):
    for form in parse(tokenize(open(path,encoding='utf-8').read())): ev(form)
class CErr:
    def __init__(s,m): s.m=m
def _cap(f,args):
    try: return call(f,lst(args))
    except Exception as e: return CErr(str(e))
funcs[Sym('VL-CATCH-ALL-APPLY')]=_cap
funcs[Sym('VL-CATCH-ALL-ERROR-P')]=lambda x: T if isinstance(x,CErr) else None
funcs[Sym('GETVAR')]=lambda v: None
import fnmatch as _fn
funcs[Sym('VL-LIST->STRING')]=lambda l: ''.join(chr(c) for c in lst(l))
funcs[Sym('WCMATCH')]=lambda s,p: T if any(_fn.fnmatchcase(s,x) for x in p.split(',')) else None
funcs[Sym('ATOI')]=lambda s: int(float(s or 0))

# ---------------------------------------------------------------- extensii (TopoKitAnexe.lsp)
funcs[Sym('CDDDR')] = lambda x: cdr(cdr(cdr(x)))
def _itoa(a):
    if not isinstance(a, int): raise TypeError(f"itoa: bad argument type: fixnump: {a!r}")
    return str(a)
funcs[Sym('ITOA')] = _itoa
def _nth(n, l):
    if not isinstance(n, int) or n < 0: raise TypeError(f"nth: bad argument {n!r}")
    l = lst(l); return l[n] if n < len(l) else None
funcs[Sym('NTH')] = _nth
def _atof(s):
    m = re.match(r'\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?', s or '')
    return float(m.group(0)) if m else 0.0
funcs[Sym('ATOF')] = _atof
def _atoi(s):
    m = re.match(r'\s*[-+]?\d+', s or '')
    return int(m.group(0)) if m else 0
funcs[Sym('ATOI')] = _atoi
funcs[Sym('READ')] = lambda s: parse(tokenize(s))[0] if s and s.strip() else None
funcs[Sym('VL-REMOVE')] = lambda x, l: [e for e in lst(l) if e != x] or None
funcs[Sym('VL-STRING->LIST')] = lambda s: [ord(c) for c in s] or None
funcs[Sym('BOUNDP')] = lambda s: T if env.get(s) is not None else None
def prin1(x):
    if x is None: return 'nil'
    if isinstance(x, Sym): return str(x)
    if isinstance(x, str): return '"' + x.replace('\\', '\\\\').replace('"', '\\"') + '"'
    if isinstance(x, bool): return 'T'
    if isinstance(x, int): return str(x)
    if isinstance(x, float): return repr(x)
    if isinstance(x, DP): return '(' + prin1(x.car) + ' . ' + prin1(x.cdr) + ')'
    if isinstance(x, list): return '(' + ' '.join(prin1(e) for e in x) + ')'
    return str(x)
funcs[Sym('VL-PRIN1-TO-STRING')] = prin1
funcs[Sym('CHR')] = lambda n: chr(n)
funcs[Sym('VL-POSITION')] = lambda x, l: next((i for i, e in enumerate(lst(l)) if e == x), None)
def _distof(s, mode=2):
    try: return float(s.strip())
    except (ValueError, AttributeError): return None
funcs[Sym('DISTOF')] = _distof

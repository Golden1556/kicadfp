import re, json, collections
SRC='/private/tmp/claude-501/-Users-juli-Desktop-Claude/ec137c75-6d2e-4a41-bb2c-d385126baef6/scratchpad/kicad-src/'
# ---- enum ids (9.0 layer_ids.h) and names (LSET::Name 9.0)
def name9(i):
    fixed={0:"F.Cu",2:"B.Cu",1:"F.Mask",3:"B.Mask",5:"F.SilkS",7:"B.SilkS",9:"F.Adhes",11:"B.Adhes",13:"F.Paste",15:"B.Paste",
           17:"Dwgs.User",19:"Cmts.User",21:"Eco1.User",23:"Eco2.User",25:"Edge.Cuts",27:"Margin",29:"B.CrtYd",31:"F.CrtYd",33:"B.Fab",35:"F.Fab",37:"Rescue"}
    if i in fixed: return fixed[i]
    if i%2==1: return "User.%d"%((i-37)//2)      # lset.cpp 9.0:232-233
    return "In%d.Cu"%((i-2)//2)                   # lset.cpp 9.0:237-238
ids9={name9(i):i for i in range(128)}
# 6.0/7.0/8.0 enum (layer_ids.h 8.0:59-139)
names8=["F.Cu"]+["In%d.Cu"%i for i in range(1,31)]+["B.Cu","B.Adhes","F.Adhes","B.Paste","F.Paste","B.SilkS","F.SilkS","B.Mask","F.Mask",
        "Dwgs.User","Cmts.User","Eco1.User","Eco2.User","Edge.Cuts","Margin","B.CrtYd","F.CrtYd","B.Fab","F.Fab"]+["User.%d"%i for i in range(1,10)]+["Rescue"]
ids8={n:i for i,n in enumerate(names8)}
assert len(names8)==60
# canonical lists in enum id order (== order in which the writer enumerates individual layers)
canon9=[name9(i) for i in range(128)]
canon9_real=[n for n in canon9 if not (n.startswith("In") and int(n[2:-3])>30)]  # exclude In31..In62 quirk names
copper9=["F.Cu"]+["In%d.Cu"%i for i in range(1,31)]+["B.Cu"]
wild={"*.Cu":copper9,"*In.Cu":copper9[1:-1],"F&B.Cu":["F.Cu","B.Cu"],"*.Adhes":["B.Adhes","F.Adhes"],"*.Paste":["B.Paste","F.Paste"],
      "*.Mask":["B.Mask","F.Mask"],"*.SilkS":["B.SilkS","F.SilkS"],"*.Fab":["B.Fab","F.Fab"],"*.CrtYd":["B.CrtYd","F.CrtYd"]}
inner_old={"Inner%d.Cu"%i:"In%d.Cu"%(15-i) for i in range(1,15)}  # parser init: In15_Cu - 2*i (9.0) / In15_Cu - i (8.0)
# ---- legacy
LEG={0:"LAYER_N_BACK",15:"LAYER_N_FRONT",16:"ADHESIVE_N_BACK",17:"ADHESIVE_N_FRONT",18:"SOLDERPASTE_N_BACK",19:"SOLDERPASTE_N_FRONT",
     20:"SILKSCREEN_N_BACK",21:"SILKSCREEN_N_FRONT",22:"SOLDERMASK_N_BACK",23:"SOLDERMASK_N_FRONT",24:"DRAW_N",25:"COMMENT_N",26:"ECO1_N",27:"ECO2_N",28:"EDGE_N"}
def BoardLayerFromLegacyId(x):  # layer_id.cpp 9.0:215-262 (only the <31 branch is needed here)
    if x==0: return "F.Cu"
    if x==31: return "B.Cu"
    if 0<x<31: return "In%d.Cu"%x
    raise ValueError
def leg_layer2new(cu_count,old):  # pcb_io_kicad_legacy.cpp 9.0:311-364
    if 0<=old<=15:
        if old==15: return "F.Cu"
        if old==0: return "B.Cu"
        return BoardLayerFromLegacyId(cu_count-1-old)
    m={16:"B.Adhes",17:"F.Adhes",18:"B.Paste",19:"F.Paste",20:"B.SilkS",21:"F.SilkS",22:"B.Mask",23:"F.Mask",24:"Dwgs.User",25:"Cmts.User",26:"Eco1.User",27:"Eco2.User",28:"Edge.Cuts"}
    return m.get(old,"Cmts.User")
def leg_mask2new(cu_count,mask):  # pcb_io_kicad_legacy.cpp 9.0:367-385
    ret=[]
    if mask&0xFFFF==0xFFFF:
        ret+=copper9; mask&=~0xFFFF
    i=0
    while mask:
        if mask&1:
            n=leg_layer2new(cu_count,i)
            if n not in ret: ret.append(n)
        i+=1; mask>>=1
    return ret
legacy_index_lib={str(i):leg_layer2new(16,i) for i in range(32)}   # m_cu_count = 16 for .mod libraries (init(), :2923)
legacy_index_2cu={str(i):leg_layer2new(2,i) if not (1<=i<=14) else None for i in range(32)}
legacy_bits={("0x%08X"%(1<<i)):{"bit":i,"macro":LEG.get(i,("LAYER_N_%d"%(i+1)) if i<15 else "UNUSED_LAYER_%d"%i),"layer_lib16":leg_layer2new(16,i)} for i in range(32)}
examples={m:leg_mask2new(16,int(m,16)) for m in ["00E0FFFF","00E00001","00808000","00888000","0000FFFF","00C0FFFF","00008000","00000001","1FFFFFFF"]}
# ---- pad presets (pad.cpp 9.0:334-366)
pad_presets={"thru_hole":copper9+["F.Mask","B.Mask"],"smd":["F.Cu","F.Paste","F.Mask"],"smd_back":["B.Cu","B.Paste","B.Mask"],
             "connect":["F.Cu","F.Mask"],"connect_back":["B.Cu","B.Mask"],"np_thru_hole":["F.Cu","B.Cu","F.Mask","B.Mask"],"aperture":["F.Paste"]}
# ---- colors: parse builtin_color_themes.h + color4d.cpp
h=open(SRC+'9.0/common_settings_builtin_color_themes.h').read()
c4=open(SRC+'9.0/common_gal_color4d.cpp').read()
named={}
for m in re.finditer(r'\{\s*(\d+),\s*(\d+),\s*(\d+),\s*([A-Z]+),\s*TS\(',c4):
    b,g,r,nm=m.groups(); named[nm]=(int(r),int(g),int(b))   # StructColors = {m_Blue, m_Green, m_Red,...} color4d.h:84-92
def section(name):
    s=h.index(name); e=h.index('};',s); return h[s:e]
def parse_theme(txt):
    out={}
    for m in re.finditer(r'\{\s*([A-Za-z0-9_]+),\s*(CSS_COLOR\([^)]*\)|COLOR4D\([^)]*\)(?:\.WithAlpha\(\s*[\d.]+\s*\))?)\s*\}',txt):
        key,val=m.groups()
        if val.startswith('CSS_COLOR'):
            r,g,b,a=[x.strip() for x in val[len('CSS_COLOR('):-1].split(',')]
            out[key]=(int(r),int(g),int(b),float(a))
        else:
            mm=re.match(r'COLOR4D\(\s*([^)]*)\)(?:\.WithAlpha\(\s*([\d.]+)\s*\))?',val)
            args=[x.strip() for x in mm.group(1).split(',')]; alpha=mm.group(2)
            if len(args)==1:
                if args[0] not in named: continue
                r,g,b=named[args[0]]; a=1.0
            else:
                r,g,b=[round(float(x)*255) for x in args[:3]]; a=float(args[3])
            if alpha: a=float(alpha)
            out[key]=(r,g,b,a)
    return out
default=parse_theme(section('s_defaultTheme')); classic=parse_theme(section('s_classicTheme'))
enum2name={"F_Cu":"F.Cu","B_Cu":"B.Cu","B_Adhes":"B.Adhes","F_Adhes":"F.Adhes","B_Paste":"B.Paste","F_Paste":"F.Paste","B_SilkS":"B.SilkS","F_SilkS":"F.SilkS",
           "B_Mask":"B.Mask","F_Mask":"F.Mask","Dwgs_User":"Dwgs.User","Cmts_User":"Cmts.User","Eco1_User":"Eco1.User","Eco2_User":"Eco2.User","Edge_Cuts":"Edge.Cuts",
           "Margin":"Margin","B_CrtYd":"B.CrtYd","F_CrtYd":"F.CrtYd","B_Fab":"B.Fab","F_Fab":"F.Fab"}
for i in range(1,31): enum2name["In%d_Cu"%i]="In%d.Cu"%i
for i in range(1,46): enum2name["User_%d"%i]="User.%d"%i
def hexc(r,g,b,a): return "#%02X%02X%02X"%(r,g,b) if a==1.0 else "#%02X%02X%02X%02X"%(r,g,b,round(a*255))
def to_map(theme):
    m=collections.OrderedDict()
    for k,v in theme.items():
        if k in enum2name: m[enum2name[k]]={"hex":hexc(*v),"rgba":list(v)}
    gal=collections.OrderedDict()
    for k,v in theme.items():
        if k.startswith('LAYER_') and not k.startswith('LAYER_3D') and not k.startswith('LAYER_SCHEMATIC') or k=='NETNAMES_LAYER_ID_START':
            gal[k]={"hex":hexc(*v),"rgba":list(v)}
    return m,gal
dcol,dgal=to_map(default); ccol,cgal=to_map(classic)
# keep only pcbnew GAL layers of interest
keep=["LAYER_ANCHOR","LAYER_LOCKED_ITEM_SHADOW","LAYER_CONFLICTS_SHADOW","LAYER_AUX_ITEMS","LAYER_PCB_BACKGROUND","LAYER_CURSOR","LAYER_DRC_ERROR","LAYER_DRC_WARNING",
      "LAYER_DRC_EXCLUSION","LAYER_GRID","LAYER_GRID_AXES","LAYER_PAD_PLATEDHOLES","LAYER_NON_PLATEDHOLES","LAYER_RATSNEST","LAYER_SELECT_OVERLAY","LAYER_VIA_HOLES",
      "LAYER_VIA_HOLEWALLS","LAYER_DRAWINGSHEET","LAYER_PAGE_LIMITS","NETNAMES_LAYER_ID_START","LAYER_PAD_NETNAMES","LAYER_VIA_NETNAMES"]
dgal={k:dgal[k] for k in keep if k in dgal}; cgal={k:cgal[k] for k in keep if k in cgal}
assert all(n in dcol for n in canon9_real if n!="Rescue"), [n for n in canon9_real if n not in dcol]
# ---- draw order (pcb_draw_panel_gal.cpp 9.0 GAL_LAYER_ORDER; index 0 = closest to viewer)
g=open(SRC+'9.0/pcbnew_pcb_draw_panel_gal.cpp').read()
s=g.index('const int GAL_LAYER_ORDER[]'); e=g.index('};',s)
toks=[t.strip() for t in re.sub(r'//.*','',g[s:e]).split('{',1)[1].replace('\n',' ').split(',')]
draw=[]
for t in toks:
    t=t.strip()
    if t in enum2name: draw.append(enum2name[t])
    elif t in ("LAYER_FP_TEXT","LAYER_FP_REFERENCES","LAYER_FP_VALUES","LAYER_ANCHOR","LAYER_PAD_PLATEDHOLES","LAYER_NON_PLATEDHOLES","LAYER_PAD_HOLEWALLS","LAYER_VIA_HOLES","LAYER_SELECT_OVERLAY","LAYER_GP_OVERLAY","LAYER_RATSNEST","LAYER_DRC_ERROR"):
        draw.append("<%s>"%t)
out=collections.OrderedDict()
out["_source"]={"note":"generated by scratchpad/research/gen_layers_json.py from KiCad sources; see docs/dev/layers.md",
  "enum_ids":"9.0: include/layer_ids.h:59-172; 6.0/7.0/8.0: include/layer_ids.h:59-139",
  "names":"common/lset.cpp LSET::Name (9.0:188-243; 8.0:89-175)",
  "wildcards":"pcb_io_kicad_sexpr_parser.cpp 9.0:115-136 (init); writer formatLayers 9.0:1366-1445",
  "pad_presets":"pcbnew/pad.cpp 9.0:334-366",
  "legacy":"pcbnew/pcb_io/kicad_legacy/pcb_io_kicad_legacy.cpp 9.0:102-174,311-385,2923",
  "colors":"common/settings/builtin_color_themes.h 9.0 (s_defaultTheme 28-284, s_classicTheme 307-557); named colors common/gal/color4d.cpp 9.0:40-80 (B,G,R order)",
  "draw_order":"pcbnew/pcb_draw_panel_gal.cpp 9.0:59-260 GAL_LAYER_ORDER (index 0 = closest to viewer, include/gal/graphics_abstraction_layer.h:418)"}
out["canonical"]={"6.0":names8,"7.0":names8,"8.0":names8,"9.0":canon9_real,"master":canon9_real}
out["ids"]={"6.0":ids8,"7.0":ids8,"8.0":ids8,"9.0":{n:ids9[n] for n in canon9_real}}
out["parser_known_names_9.0_extra"]=["In%d.Cu"%i for i in range(31,63)]
out["copper"]=copper9
out["copper_layers_iteration_order_9.0"]=copper9
out["wildcards"]=wild
out["old_inner_names"]=inner_old
out["writer_wildcards_order"]=["*.Cu|F&B.Cu","*.Adhes","*.Paste","*.SilkS","*.Mask","*.CrtYd","*.Fab"]
out["writer_individual_order"]={"6.0-8.0":names8,"9.0+":canon9_real}
out["pad_presets"]=pad_presets
out["pad_presets_as_written"]={"thru_hole":["*.Cu","*.Mask"],"smd":["F.Cu","F.Paste","F.Mask"],"smd_9.0+":["F.Cu","F.Mask","F.Paste"],"connect":["F.Cu","F.Mask"],
   "np_thru_hole_6.0-8.0_and_9.0.0-9.0.5":["F&B.Cu","*.Mask"],"np_thru_hole_9.0.6+":["*.Cu","*.Mask"],"aperture":["F.Paste"]}
out["pad_dialog_selectable_tech_layers_9.0"]=["F.Adhes","B.Adhes","F.Paste","B.Paste","F.SilkS","B.SilkS","F.Mask","B.Mask","Eco1.User","Eco2.User","Dwgs.User"]
out["legacy_names_2011"]={"0":"Back","1-14":"Inner2..Inner15","15":"Front","16":"Adhes_Back","17":"Adhes_Front","18":"SoldP_Back","19":"SoldP_Front","20":"SilkS_Back","21":"SilkS_Front","22":"Mask_Back","23":"Mask_Front","24":"Drawings","25":"Comments","26":"Eco1","27":"Eco2","28":"PCB_Edges"}
out["legacy_index"]=legacy_index_lib
out["legacy_index_note"]="legacy number -> modern name with cu_count=16 (value used for .mod libraries, pcb_io_kicad_legacy.cpp 9.0:2923). Inner layers 1..14 depend on cu_count: In(cu_count-1-n).Cu; 29..31 -> Cmts.User (default branch :358-360)"
out["legacy_mask_bits"]=legacy_bits
out["legacy_mask_examples"]=examples
out["legacy_pad_default_masks_2011"]={"STD":"00E0FFFF","SMD":"00808000","CONN":"00888000","HOLE":"00E00001"}
out["colors"]={n:dcol[n]["hex"] for n in dcol}
out["colors_rgba"]=dcol
out["colors_gal"]={k:v["hex"] for k,v in dgal.items()}
out["colors_classic"]={n:ccol[n]["hex"] for n in ccol}
out["colors_classic_gal"]={k:v["hex"] for k,v in cgal.items()}
out["color_json_keys"]={"F.Cu":"board.copper.f","B.Cu":"board.copper.b","In1.Cu":"board.copper.in1","F.SilkS":"board.f_silks","B.SilkS":"board.b_silks","F.Mask":"board.f_mask","B.Mask":"board.b_mask","F.Paste":"board.f_paste","B.Paste":"board.b_paste","F.Adhes":"board.f_adhes","B.Adhes":"board.b_adhes","Dwgs.User":"board.dwgs_user","Cmts.User":"board.cmts_user","Eco1.User":"board.eco1_user","Eco2.User":"board.eco2_user","Edge.Cuts":"board.edge_cuts","Margin":"board.margin","F.CrtYd":"board.f_crtyd","B.CrtYd":"board.b_crtyd","F.Fab":"board.f_fab","B.Fab":"board.b_fab","User.1":"board.user_1","LAYER_PCB_BACKGROUND":"board.background","LAYER_GRID":"board.grid","LAYER_PAD_PLATEDHOLES":"board.pad_plated_hole","LAYER_NON_PLATEDHOLES":"board.plated_hole","LAYER_ANCHOR":"board.anchor","LAYER_SELECT_OVERLAY":"<no CLR in 9.0 color_settings.cpp:123-143; not verified>"}
out["draw_order"]=draw
json.dump(out,open('/Users/juli/Desktop/Claude/kicadfp/docs/dev/layers.json','w'),indent=1,ensure_ascii=False)
print("named colors:",len(named), "RED=",named["RED"],"BLUE=",named["BLUE"],"YELLOW=",named["YELLOW"])
print("default pcb colors:",len(dcol),"classic:",len(ccol),"gal:",len(dgal))
print("examples:",json.dumps(examples))
print("legacy_index:",legacy_index_lib)
print("draw:",draw)
print({k:dcol[k]["hex"] for k in ["F.Cu","B.Cu","In1.Cu","F.SilkS","B.SilkS","F.Mask","B.Mask","F.Paste","B.Paste","F.Fab","B.Fab","F.CrtYd","B.CrtYd","Edge.Cuts","Margin","Dwgs.User","Cmts.User","Eco1.User","Eco2.User","User.1","User.9","F.Adhes","B.Adhes"]})
print(dgal)
print({k:ccol[k]["hex"] for k in ["F.Cu","B.Cu","F.SilkS","B.SilkS","F.Mask","B.Mask","F.Paste","B.Paste","Edge.Cuts","F.Fab","F.CrtYd"]})
print(cgal)

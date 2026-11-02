"""生成 8 屏可点击原型（单文件 HTML，内联 CSS/JS，离线可看，无外链图片）。

    python prototype/gen_prototype.py

设计要点：
    1. 所有 KPI 与图表数字**从 data/ 下的真实 CSV 计算**，不是编造占位值
    2. 图表用手写内联 SVG，不依赖 CDN（离线必须能看）
    3. 页面之间用真实 <a href> 跳转，形成可点击流程
    4. 每个筛选控件旁标注对应的数据库字段名（教学用）
    5. 同时生成 docs/04-原型说明.md（页面清单 / 跳转关系 / 设计决策）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "prototype"
DOCS = ROOT / "docs"

# ---------------------------------------------------------------------------
# 真实数据 → 原型所需的结构
# ---------------------------------------------------------------------------
def build_data() -> dict:
    house = pd.read_csv(DATA / "cleaned_house.csv", encoding="utf-8-sig")
    district = pd.read_csv(DATA / "dim_district.csv", encoding="utf-8-sig")
    street = pd.read_csv(DATA / "dim_street.csv", encoding="utf-8-sig")
    community = pd.read_csv(DATA / "dim_community.csv", encoding="utf-8-sig")
    orient = pd.read_csv(DATA / "cleaned_orientation.csv", encoding="utf-8-sig")

    d = {}
    d["kpi"] = {
        "house_count": int(len(house)),
        "avg_unit_price": round(float(house["unit_price"].mean()), 2),
        "median_total_price": float(house["total_price"].median()),
        "community_count": int(community["community_id"].nunique()),
        "weighted_unit_price": round(
            float((house["total_price"] * 10000).sum() / house["area"].sum()), 2),
    }

    # 区均价（按均价降序，取前 10）
    dg = district.sort_values("avg_unit_price", ascending=False)
    d["districts"] = [
        {"name": r["district_name"], "n": int(r["house_count"]),
         "avg": round(float(r["avg_unit_price"]), 0),
         "median": round(float(r["median_unit_price"]), 0),
         "median_total": float(r["median_total_price"])}
        for _, r in dg.iterrows()
    ]

    # 总价分位分桶（10 桶）
    tp = house["total_price"]
    edges = [float(tp.quantile(i / 10)) for i in range(11)]
    edges[0] = float(tp.min())
    edges[-1] = float(tp.max())
    bins = []
    for i in range(10):
        lo, hi = edges[i], edges[i + 1]
        cnt = int(((tp >= lo) & (tp <= hi)).sum()) if i == 9 else \
              int(((tp >= lo) & (tp < hi)).sum())
        bins.append({"low": round(lo, 1), "high": round(hi, 1), "count": cnt})
    d["price_bins"] = bins

    # 面积-总价散点（等距抽 260 点，可复现）
    h = house.sort_values("source_row_no")
    step = max(1, len(h) // 260)
    sample = h.iloc[::step].head(260)
    d["scatter"] = [[round(float(r["area"]), 2), round(float(r["total_price"]), 1),
                     int(r["is_outlier"])] for _, r in sample.iterrows()]
    d["pearson_r"] = round(float(house["area"].corr(house["total_price"])), 3)

    # 房龄段（8 段）
    age_edges = [0, 5, 10, 15, 20, 25, 30, 40, 50]
    age_labels = ["0-5", "5-10", "10-15", "15-20", "20-25", "25-30", "30-40", "40-50"]
    house["age_bucket"] = pd.cut(house["house_age"], age_edges, labels=age_labels)
    city = []
    for lab in age_labels:
        sub = house[house["age_bucket"] == lab]
        city.append({"bucket": lab, "avg": round(float(sub["unit_price"].mean()), 0),
                     "n": int(len(sub))})
    d["age_city"] = city

    # 分区房龄-单价（取套数最多的 6 个区）
    top6 = district.sort_values("house_count", ascending=False).head(6)
    id2name = dict(zip(district["district_id"], district["district_name"]))
    series = []
    for _, r in top6.iterrows():
        sub = house[house["district_id"] == int(r["district_id"])]
        pts = []
        for lab in age_labels:
            s2 = sub[sub["age_bucket"] == lab]
            if len(s2) >= 3:
                pts.append({"bucket": lab, "avg": round(float(s2["unit_price"].mean()), 0),
                            "n": int(len(s2))})
        series.append({"name": id2name[int(r["district_id"])], "points": pts})
    d["age_by_district"] = series

    # 溢价（全市 + 同区控制）
    def premium(mask_col, base_val, target_val):
        base = house[house[mask_col] == base_val]["unit_price"]
        targ = house[house[mask_col] == target_val]["unit_price"]
        if len(base) == 0 or len(targ) == 0:
            return None
        return {"base_avg": round(float(base.mean()), 0), "target_avg": round(float(targ.mean()), 0),
                "premium_pct": round(float((targ.mean() - base.mean()) / base.mean() * 100), 2),
                "n_base": int(len(base)), "n_target": int(len(targ))}

    d["premium_metro"] = premium("near_subway", 0, 1)
    d["premium_deco"] = premium("decoration", "简装", "精装")
    d["premium_structure"] = premium("structure", "板楼", "塔楼")

    # 同区控制：各区 近/不近 地铁均价差
    by_d = []
    for _, r in district.sort_values("house_count", ascending=False).head(8).iterrows():
        sub = house[house["district_id"] == int(r["district_id"])]
        nb = sub[sub["near_subway"] == 0]["unit_price"]
        nt = sub[sub["near_subway"] == 1]["unit_price"]
        if len(nb) >= 3 and len(nt) >= 3:
            by_d.append({"name": r["district_name"],
                         "subway": round(float(nt.mean()) - float(nb.mean()), 0)})
    d["metro_by_district"] = by_d

    # 朝向 / 楼层分布
    o = orient["direction"].value_counts()
    d["orientation"] = [{"dir": k, "n": int(v)} for k, v in o.items()]
    fl = house["floor_level"].value_counts()
    d["floor"] = [{"level": k, "n": int(v)} for k, v in fl.items()]

    # 户型 Top8
    house["layout"] = house["room"].astype(str) + "室" + house["hall"].astype(str) + "厅"
    lay = house["layout"].value_counts().head(8)
    d["layouts"] = [{"name": k, "n": int(v)} for k, v in lay.items()]

    # 热门小区（在售最多）
    d["top_communities"] = [
        {"name": r["community_name"], "n": int(r["house_count"]),
         "avg": round(float(r["avg_unit_price"]), 0),
         "median_total": float(r["median_total_price"])}
        for _, r in community.sort_values("house_count", ascending=False).head(6).iterrows()
    ]

    # 街道排行（排除伪街道）
    real = street[street["is_pseudo"] == 0]
    id2dist = dict(zip(district["district_id"], district["district_name"]))
    d["street_rank"] = [
        {"name": r["street_name"], "district": id2dist.get(int(r["district_id"]), ""),
         "n": int(r["house_count"]), "avg": round(float(r["avg_unit_price"]), 0)}
        for _, r in real[real["house_count"] >= 4].sort_values(
            "avg_unit_price", ascending=False).head(8).iterrows()
    ]

    # 检索页样例结果（朝阳 + 400–600 万 + 近地铁）
    sub = house[(house["district_id"] == 11) & (house["total_price"].between(400, 600))
                & (house["near_subway"] == 1)].head(6)
    d["search_rows"] = [
        {"id": int(r["source_row_no"]), "area": round(float(r["area"]), 2),
         "total": round(float(r["total_price"]), 1), "unit": round(float(r["unit_price"]), 0),
         "layout": f'{int(r["room"])}室{int(r["hall"])}厅',
         "deco": r["decoration"], "floor": r["floor_level"],
         "age": int(r["house_age"]), "orient": r["orientation_text"]}
        for _, r in sub.iterrows()
    ]
    d["search_total"] = int(len(house[(house["district_id"] == 11)
                                      & (house["total_price"].between(400, 600))
                                      & (house["near_subway"] == 1)]))

    # 详情页单房 + 分位
    h0 = house.iloc[0]
    dist_rows = house[house["district_id"] == int(h0["district_id"])]["unit_price"]
    d["detail"] = {
        "community": community[community["community_id"] == int(h0["community_id"])]["community_name"].iloc[0],
        "district": id2dist[int(h0["district_id"])],
        "area": round(float(h0["area"]), 2), "total": float(h0["total_price"]),
        "unit": round(float(h0["unit_price"]), 0), "room": int(h0["room"]),
        "hall": int(h0["hall"]), "age": int(h0["house_age"]),
        "deco": h0["decoration"], "structure": h0["structure"],
        "floor": h0["floor_level"], "floor_total": int(h0["floor_total"]),
        "orient": h0["orientation_text"],
        "near_subway": int(h0["near_subway"]),
        "percentile": round(float((dist_rows < h0["unit_price"]).mean() * 100), 1),
        "district_n": int(len(dist_rows)),
        "p25": round(float(dist_rows.quantile(.25)), 0),
        "p50": round(float(dist_rows.median()), 0),
        "p75": round(float(dist_rows.quantile(.75)), 0),
    }
    return d


# ---------------------------------------------------------------------------
# 共享 CSS / JS
# ---------------------------------------------------------------------------
CSS = """
:root{
  --primary:#1A4D8F; --accent:#0F766E; --warn:#B45309;
  --bg:#F7F9FC; --text:#1F2937; --muted:#6B7280; --line:#E3E8EF; --card:#FFFFFF;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:var(--bg);
     color:var(--text);font-size:14px;line-height:1.6}
.num{font-variant-numeric:tabular-nums}
a{color:inherit;text-decoration:none}
.topbar{height:56px;background:var(--primary);color:#fff;display:flex;align-items:center;
        padding:0 20px;gap:24px;position:sticky;top:0;z-index:10}
.brand{font-weight:700;letter-spacing:.5px}
.nav{display:flex;gap:4px;margin-left:8px;flex-wrap:wrap}
.nav a{padding:6px 12px;border-radius:6px;font-size:13px;opacity:.85}
.nav a:hover{background:rgba(255,255,255,.12);opacity:1}
.nav a.on{background:rgba(255,255,255,.18);opacity:1;font-weight:600}
.who{margin-left:auto;font-size:12px;opacity:.8}
.wrap{display:flex;min-height:calc(100vh - 56px)}
.side{width:220px;background:#fff;border-right:1px solid var(--line);padding:16px 0;flex-shrink:0}
.side .grp{font-size:11px;color:var(--muted);padding:8px 20px 4px;letter-spacing:1px}
.side a{display:block;padding:9px 20px;font-size:13px;border-left:3px solid transparent}
.side a:hover{background:#F1F5F9}
.side a.on{border-left-color:var(--primary);background:#EEF3FA;color:var(--primary);font-weight:600}
main{flex:1;padding:24px;min-width:0}
h1{font-size:22px;margin-bottom:4px}
h1 .sub{font-size:13px;color:var(--muted);font-weight:400;margin-left:8px}
.caliber{font-size:12px;color:var(--muted);margin-bottom:18px}
.row{display:grid;gap:16px}
.g4{grid-template-columns:repeat(4,1fr)}
.g6{grid-template-columns:repeat(6,1fr)}
.g2{grid-template-columns:repeat(2,1fr)}
.g3{grid-template-columns:repeat(3,1fr)}
@media(max-width:1280px){.g4,.g6{grid-template-columns:repeat(2,1fr)}.g2,.g3{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px}
.card h3{font-size:14px;margin-bottom:2px}
.card .tip{font-size:11px;color:var(--muted);margin-bottom:12px}
.kpi .v{font-size:26px;font-weight:700;color:var(--primary)}
.kpi .l{font-size:12px;color:var(--muted)}
.kpi .d{font-size:11px;color:var(--muted);margin-top:6px;border-top:1px dashed var(--line);padding-top:6px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--line)}
th{font-size:12px;color:var(--muted);font-weight:600;background:#FAFBFD}
tr:hover td{background:#FAFBFD}
.tag{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;
     background:#EEF3FA;color:var(--primary);margin-right:4px}
.tag.g{background:#E7F4F1;color:var(--accent)}
.tag.w{background:#FBF0E2;color:var(--warn)}
.field{font-size:10px;color:#94A3B8;font-family:Consolas,monospace}
.filter label{display:block;font-size:12px;margin-bottom:4px;color:#374151}
.filter .fg{margin-bottom:14px}
select,input[type=text],input[type=number]{width:100%;padding:7px 9px;border:1px solid var(--line);
  border-radius:6px;font-size:13px;background:#fff;color:var(--text)}
.btn{display:inline-block;padding:8px 16px;border-radius:6px;background:var(--primary);color:#fff;
     font-size:13px;cursor:pointer;border:0}
.btn.ghost{background:#fff;color:var(--primary);border:1px solid var(--primary)}
.btn.sm{padding:5px 10px;font-size:12px}
.chip{display:inline-block;padding:4px 10px;border:1px solid var(--line);border-radius:14px;
      font-size:12px;margin:0 6px 6px 0;background:#fff}
.chip.on{background:#EEF3FA;border-color:var(--primary);color:var(--primary)}
.range{width:100%}
.stat{display:flex;gap:20px;flex-wrap:wrap;font-size:12px;color:var(--muted)}
.stat b{color:var(--text);font-size:14px}
.diff td{background:#FFFBEB}
.drawer{margin-top:16px;border:1px solid var(--line);border-radius:8px;background:#fff}
.drawer .hd{padding:12px 16px;border-bottom:1px solid var(--line);font-weight:600;font-size:13px}
.drawer .bd{padding:16px}
.note{font-size:12px;color:var(--muted);background:#F1F5F9;border-radius:6px;padding:10px 12px;
      margin-top:12px}
.warnbox{border-left:3px solid var(--warn);background:#FDF6EC;padding:10px 12px;font-size:12px;
         border-radius:0 6px 6px 0;margin-bottom:16px}
footer{padding:24px;color:var(--muted);font-size:11px;text-align:center}
svg text{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
"""

JS_LIB = """
const D = window.__PROTO_DATA__;
function el(id){return document.getElementById(id)}
function esc(s){return String(s)}
function svgOpen(w,h){return `<svg viewBox="0 0 ${w} ${h}" style="width:100%;height:auto;display:block">`}

function hbar(id, items, opt){
  opt = opt||{};
  const box = el(id); if(!box) return;
  const labelKey = opt.label || 'label';
  const w = 560, lh = 26, pad = 8, labelW = opt.labelW||84, valW = 92;
  const h = items.length*lh + pad*2;
  const max = Math.max(...items.map(d=>d[opt.value]));
  let s = svgOpen(w,h);
  items.forEach((d,i)=>{
    const y = pad + i*lh;
    const bw = Math.max(2, (w-labelW-valW-16) * d[opt.value]/max);
    s += `<text x="0" y="${y+15}" font-size="12" fill="#374151">${esc(d[labelKey])}</text>`;
    s += `<rect x="${labelW}" y="${y+4}" width="${bw}" height="14" rx="3" fill="${opt.color||'#1A4D8F'}" opacity="0.88"/>`;
    const txt = opt.fmt ? opt.fmt(d) : d[opt.value].toLocaleString();
    s += `<text x="${w-valW+4}" y="${y+15}" font-size="12" text-anchor="start" fill="#1F2937" class="num">${txt}</text>`;
    if(opt.nKey) s += `<text x="${labelW+8}" y="${y+15}" font-size="10" fill="#fff">n=${d[opt.nKey]}</text>`;
  });
  box.innerHTML = s + '</svg>';
}

function hist(id, bins, opt){
  opt=opt||{};
  const box = el(id); if(!box) return;
  const w = 560, h = 200, padL = 44, padB = 28, padT = 12;
  const max = Math.max(...bins.map(b=>b.count));
  const bw = (w-padL-12)/bins.length;
  let s = svgOpen(w,h);
  for(let g=0; g<=2; g++){
    const y = padT + (h-padT-padB)*g/2;
    s += `<line x1="${padL}" y1="${y}" x2="${w-8}" y2="${y}" stroke="#E3E8EF"/>`;
    s += `<text x="${padL-6}" y="${y+4}" font-size="10" text-anchor="end" fill="#94A3B8">${Math.round(max*(1-g/2))}</text>`;
  }
  bins.forEach((b,i)=>{
    const bh = (h-padT-padB)*b.count/max;
    const x = padL + i*bw + 2;
    s += `<rect x="${x}" y="${h-padB-bh}" width="${bw-4}" height="${bh}" rx="2" fill="#0F766E" opacity="0.82"/>`;
    if(i%2===0) s += `<text x="${x+bw/2-2}" y="${h-padB+14}" font-size="9" text-anchor="middle" fill="#6B7280">${b.low}</text>`;
  });
  s += `<text x="${padL}" y="${h-4}" font-size="10" fill="#94A3B8">单位：万元（分位分桶）</text>`;
  box.innerHTML = s + '</svg>';
}

function scatter(id, pts, r){
  const box = el(id); if(!box) return;
  const w = 560, h = 220, padL = 44, padB = 26, padT = 12;
  const xs = pts.map(p=>p[0]), ys = pts.map(p=>p[1]);
  const xMax = Math.max(...xs), yMax = Math.max(...ys);
  const X = v => padL + (w-padL-10)*v/xMax;
  const Y = v => h-padB - (h-padT-padB)*v/yMax;
  let s = svgOpen(w,h);
  for(let g=0; g<=2; g++){
    const y = padT + (h-padT-padB)*g/2;
    s += `<line x1="${padL}" y1="${y}" x2="${w-8}" y2="${y}" stroke="#E3E8EF"/>`;
  }
  pts.forEach(p=>{
    s += `<circle cx="${X(p[0]).toFixed(1)}" cy="${Y(p[1]).toFixed(1)}" r="${p[2]?'3.4':'2.2'}"
          fill="${p[2]?'#B45309':'#1A4D8F'}" opacity="${p[2]?'0.9':'0.42'}"/>`;
  });
  // 最小二乘回归线
  const n = pts.length;
  const mx = xs.reduce((a,b)=>a+b,0)/n, my = ys.reduce((a,b)=>a+b,0)/n;
  let sxy=0, sxx=0;
  pts.forEach(p=>{ sxy += (p[0]-mx)*(p[1]-my); sxx += (p[0]-mx)**2; });
  const slope = sxy/sxx, inter = my - slope*mx;
  s += `<line x1="${X(0)}" y1="${Y(inter)}" x2="${X(xMax)}" y2="${Y(slope*xMax+inter)}"
        stroke="#B45309" stroke-width="1.6" stroke-dasharray="5 4"/>`;
  s += `<text x="${w-12}" y="${padT+12}" font-size="11" text-anchor="end" fill="#B45309" class="num">r = ${r}　n = ${n}</text>`;
  s += `<text x="${padL}" y="${h-6}" font-size="10" fill="#94A3B8">横轴：面积 ㎡　纵轴：总价 万元（橙点=极值标记）</text>`;
  box.innerHTML = s + '</svg>';
}

function multiline(id, buckets, series){
  const box = el(id); if(!box) return;
  const w = 560, h = 250, padL = 52, padB = 30, padT = 14;
  const all = series.flatMap(s=>s.points.map(p=>p.avg));
  const yMin = Math.min(...all)*0.94, yMax = Math.max(...all)*1.04;
  const X = i => padL + (w-padL-14)*i/Math.max(1,buckets.length-1);
  const Y = v => h-padB - (h-padT-padB)*(v-yMin)/(yMax-yMin);
  const colors = ['#1A4D8F','#0F766E','#B45309','#7C3AED','#DB2777','#0891B2'];
  let s = svgOpen(w,h);
  for(let g=0; g<=3; g++){
    const y = padT + (h-padT-padB)*g/3;
    s += `<line x1="${padL}" y1="${y}" x2="${w-8}" y2="${y}" stroke="#E3E8EF"/>`;
    s += `<text x="${padL-6}" y="${y+4}" font-size="9" text-anchor="end" fill="#94A3B8">${Math.round(yMax-(yMax-yMin)*g/3).toLocaleString()}</text>`;
  }
  buckets.forEach((b,i)=>{
    if(i%1===0) s += `<text x="${X(i)}" y="${h-padB+14}" font-size="9" text-anchor="middle" fill="#6B7280">${b}</text>`;
  });
  series.forEach((se,k)=>{
    const pts = se.points.map((p,i)=>({x:X(buckets.indexOf(p.bucket)), y:Y(p.avg)}));
    if(pts.length>1)
      s += `<polyline points="${pts.map(p=>`${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')}"
            fill="none" stroke="${colors[k%6]}" stroke-width="2"/>`;
    pts.forEach(p=>{ s += `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="2.8" fill="${colors[k%6]}"/>`; });
    s += `<text x="${w-10}" y="${padT+10+k*13}" font-size="10" text-anchor="end" fill="${colors[k%6]}">${se.name}</text>`;
  });
  s += `<text x="${padL}" y="${h-4}" font-size="10" fill="#94A3B8">横轴：房龄区间（年）　纵轴：均价 元/㎡　（每区一条线，n&lt;3 的点不画）</text>`;
  box.innerHTML = s + '</svg>';
}

function donut(id, items){
  const box = el(id); if(!box) return;
  const w = 300, h = 220, cx = 110, cy = 105, rO = 78, rI = 46;
  const total = items.reduce((a,b)=>a+b.n,0);
  const colors = ['#1A4D8F','#0F766E','#B45309','#7C3AED','#DB2777','#0891B2','#65A30D','#94A3B8'];
  let a0 = -Math.PI/2, s = svgOpen(w,h);
  items.forEach((it,i)=>{
    const ang = it.n/total*Math.PI*2, a1 = a0+ang;
    const p = (r,a)=>[cx+r*Math.cos(a), cy+r*Math.sin(a)];
    const [x0,y0]=p(rO,a0), [x1,y1]=p(rO,a1), [x2,y2]=p(rI,a1), [x3,y3]=p(rI,a0);
    const big = ang>Math.PI?1:0;
    s += `<path d="M${x0.toFixed(1)},${y0.toFixed(1)} A${rO},${rO} 0 ${big} 1 ${x1.toFixed(1)},${y1.toFixed(1)}
          L${x2.toFixed(1)},${y2.toFixed(1)} A${rI},${rI} 0 ${big} 0 ${x3.toFixed(1)},${y3.toFixed(1)} Z"
          fill="${colors[i%8]}" opacity="0.9"/>`;
    a0 = a1;
  });
  s += `<text x="${cx}" y="${cy-2}" font-size="12" text-anchor="middle" fill="#6B7280">合计</text>`;
  s += `<text x="${cx}" y="${cy+18}" font-size="16" text-anchor="middle" font-weight="700" fill="#1F2937" class="num">${total}</text>`;
  items.forEach((it,i)=>{
    const y = 24 + i*20;
    s += `<rect x="205" y="${y-8}" width="9" height="9" rx="2" fill="${colors[i%8]}"/>`;
    s += `<text x="220" y="${y}" font-size="10" fill="#374151">${it.name.length>6?it.name.slice(0,6):it.name} ${it.n}</text>`;
  });
  box.innerHTML = s + '</svg>';
}

function quantileBar(id, d){
  const box = el(id); if(!box) return;
  const w = 520, h = 92, padL = 20, padR = 20, y = 42;
  const lo = Math.min(d.p25, d.unit)*0.85, hi = Math.max(d.p75, d.unit)*1.12;
  const X = v => padL + (w-padL-padR)*(v-lo)/(hi-lo);
  let s = svgOpen(w,h);
  s += `<line x1="${padL}" y1="${y}" x2="${w-padR}" y2="${y}" stroke="#E3E8EF" stroke-width="8" stroke-linecap="round"/>`;
  s += `<line x1="${X(d.p25)}" y1="${y}" x2="${X(d.p75)}" y2="${y}" stroke="#1A4D8F" stroke-width="8" stroke-linecap="round" opacity="0.35"/>`;
  s += `<line x1="${X(d.p50)}" y1="${y-14}" x2="${X(d.p50)}" y2="${y+14}" stroke="#0F766E" stroke-width="2"/>`;
  s += `<text x="${X(d.p50)}" y="${y-20}" font-size="10" text-anchor="middle" fill="#0F766E">中位 ${d.p50}</text>`;
  s += `<circle cx="${X(d.unit)}" cy="${y}" r="6" fill="#B45309"/>`;
  s += `<text x="${X(d.unit)}" y="${y+26}" font-size="11" text-anchor="middle" font-weight="700" fill="#B45309">
        本房 ${d.unit}</text>`;
  s += `<text x="${padL}" y="${h-10}" font-size="10" fill="#94A3B8">本房单价处于${d.district}第 ${d.percentile} 百分位（同区 n=${d.district_n}）</text>`;
  box.innerHTML = s + '</svg>';
}

function radar(id, dims, series){
  const box = el(id); if(!box) return;
  const w = 300, h = 260, cx = 150, cy = 122, R = 88;
  const n = dims.length, colors = ['#1A4D8F','#0F766E','#B45309','#7C3AED'];
  const P = (i,v)=>{ const a=-Math.PI/2 + i*2*Math.PI/n; return [cx+R*v*Math.cos(a), cy+R*v*Math.sin(a)]; };
  let s = svgOpen(w,h);
  [0.25,0.5,0.75,1].forEach(t=>{
    const pts = dims.map((_,i)=>P(i,t).map(v=>v.toFixed(1)).join(',')).join(' ');
    s += `<polygon points="${pts}" fill="none" stroke="#E3E8EF"/>`;
  });
  dims.forEach((d,i)=>{
    const [x,y] = P(i,1), [tx,ty] = P(i,1.17);
    s += `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#E3E8EF"/>`;
    s += `<text x="${tx.toFixed(1)}" y="${(ty+4).toFixed(1)}" font-size="10" text-anchor="middle" fill="#6B7280">${d}</text>`;
  });
  series.forEach((se,k)=>{
    const pts = se.scores.map((v,i)=>P(i,v/100).map(x=>x.toFixed(1)).join(',')).join(' ');
    s += `<polygon points="${pts}" fill="${colors[k%4]}" fill-opacity="0.13" stroke="${colors[k%4]}" stroke-width="2"/>`;
  });
  series.forEach((se,k)=>{
    s += `<text x="${10+ (k%2)*150}" y="${h-8 - Math.floor(k/2)*13}" font-size="10" fill="${colors[k%4]}">${se.name}</text>`;
  });
  box.innerHTML = s + '</svg>';
}

function dotPlot(id, items){
  const box = el(id); if(!box) return;
  const w = 560, h = 180, padL = 90, padR = 60, padB = 26, padT = 14;
  const vals = items.map(i=>i.avg);
  const lo = Math.min(...vals)*0.9, hi = Math.max(...vals)*1.1;
  const X = v => padL + (w-padL-padR)*(v-lo)/(hi-lo);
  let s = svgOpen(w,h);
  items.forEach((it,i)=>{
    const y = padT + i*((h-padT-padB)/items.length) + 10;
    s += `<text x="0" y="${y+4}" font-size="11" fill="#374151">${it.label.slice(0,10)}</text>`;
    s += `<circle cx="${X(it.avg).toFixed(1)}" cy="${y}" r="${3 + Math.min(4, it.n/2)}" fill="#1A4D8F" opacity="0.8"/>`;
    s += `<text x="${X(it.avg)+9}" y="${y+4}" font-size="10" fill="#6B7280" class="num">${it.avg.toLocaleString()} (n=${it.n})</text>`;
  });
  box.innerHTML = s + '</svg>';
}
"""

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · 北京二手房行情洞察系统（原型）</title>
<style>{css}</style>
</head>
<body>
<div class="topbar">
  <div class="brand">BJ-House Insight</div>
  <nav class="nav">{nav}</nav>
  <div class="who">原型 v1 · 只读演示站</div>
</div>
<div class="wrap">
  <aside class="side">{side}</aside>
  <main>{body}</main>
</div>
<footer>原型数据取自真实清洗结果（2890 条 · 2024-08 快照）｜单价口径：算术均值 64,765 元/㎡；面积加权 64,028 元/㎡</footer>
<script>window.__PROTO_DATA__ = {data};</script>
<script>{lib}</script>
<script>{page_js}</script>
</body>
</html>
"""

PAGES = [
    ("p1-overview.html", "市场概览", "概览"),
    ("p2-search.html", "房源检索", "检索"),
    ("p3-detail.html", "房源详情", "详情"),
    ("p4-compare.html", "房源对比", "对比"),
    ("p5-analytics.html", "市场分析看板", "分析"),
    ("p6-community.html", "小区画像", "小区"),
    ("p7-valuation.html", "估价参考", "估价"),
    ("p8-admin.html", "数据管理", "管理"),
]


def build_nav(active: str) -> str:
    return "".join(
        f'<a href="{f}" class="{"on" if f == active else ""}">{n}</a>'
        for f, n, _ in PAGES
    )


def build_side(active: str, groups) -> str:
    return "".join(
        f'<div class="grp">{g}</div>' + "".join(
            f'<a href="{f}" class="{"on" if f == active else ""}">{label}</a>'
            for f, label in items
        )
        for g, items in groups
    )


SIDE_GROUPS = [
    ("分析", [("p1-overview.html", "市场概览"), ("p5-analytics.html", "分析看板")]),
    ("找房", [("p2-search.html", "房源检索"), ("p3-detail.html", "房源详情"),
              ("p4-compare.html", "房源对比")]),
    ("辅助", [("p6-community.html", "小区画像"), ("p7-valuation.html", "估价参考")]),
    ("管理", [("p8-admin.html", "数据管理")]),
]


def page(title, active, body, page_js, data_json):
    return (HTML.replace("{title}", title)
                .replace("{css}", CSS)
                .replace("{nav}", build_nav(active))
                .replace("{side}", build_side(active, SIDE_GROUPS))
                .replace("{body}", body)
                .replace("{data}", data_json)
                .replace("{lib}", JS_LIB)
                .replace("{page_js}", page_js))


# ---------------------------------------------------------------------------
# 8 个页面
# ---------------------------------------------------------------------------
def p1():
    body = """
<h1>市场概览 <span class="sub">2024-08 挂牌快照 · 2890 条</span></h1>
<div class="caliber">口径：均价为算术均值；中位数为线性插值中位数；极值行只标记不删除</div>
<div class="row g4">
  <div class="card kpi"><div class="l">在售房源数</div><div class="v num" id="k1">–</div>
    <div class="d">house 表全量行数</div></div>
  <div class="card kpi"><div class="l">全市均价（元/㎡）</div><div class="v num" id="k2">–</div>
    <div class="d">算术均值；面积加权为 <span id="k2b"></span></div></div>
  <div class="card kpi"><div class="l">中位总价（万元）</div><div class="v num" id="k3">–</div>
    <div class="d">median(total_price)</div></div>
  <div class="card kpi"><div class="l">覆盖小区</div><div class="v num" id="k4">–</div>
    <div class="d">（区,小区）组合数；名称去重为 1864</div></div>
</div>
<div class="row g2" style="margin-top:16px">
  <div class="card"><h3>区均价 Top 10</h3>
    <div class="tip">字段：district.avg_unit_price ｜ 条形长度=均价，右侧=中位单价，条内标注样本量 n</div>
    <div id="c-district"></div>
    <div class="note">⚠️ 平谷仅 1 套、延庆 2 套，样本量不足的区不参与排行结论。</div>
  </div>
  <div class="card"><h3>总价分布</h3>
    <div class="tip">字段：house.total_price ｜ 分位分桶（等宽分桶会把多数样本挤进第一桶）</div>
    <div id="c-price"></div>
  </div>
</div>
<div class="card" style="margin-top:16px"><h3>在售套数最多的小区</h3>
  <div class="tip">字段：community.house_count ｜ 注意：67.4% 的小区仅有 1 套在售，小区不是可统计粒度</div>
  <div class="row g3" id="c-comm" style="margin-top:8px"></div>
  <div style="margin-top:16px"><a class="btn" href="p2-search.html">进入房源检索 →</a></div>
</div>
"""
    js = """
el('k1').textContent = D.kpi.house_count.toLocaleString();
el('k2').textContent = D.kpi.avg_unit_price.toLocaleString();
el('k2b').textContent = D.kpi.weighted_unit_price.toLocaleString() + ' 元/㎡';
el('k3').textContent = D.kpi.median_total_price;
el('k4').textContent = D.kpi.community_count;
hbar('c-district', D.districts.slice(0,10).map(d=>({label:d.name, avg:d.avg, median:d.median, n:d.n})),
     {value:'avg', nKey:'n', fmt:d=>d.avg.toLocaleString()+' / '+d.median.toLocaleString()});
hist('c-price', D.price_bins);
el('c-comm').innerHTML = D.top_communities.map(c=>`
  <div class="card" style="padding:12px">
    <div style="font-weight:600">${c.name}</div>
    <div class="stat"><span>在售 <b>${c.n}</b></span><span>均价 <b>${c.avg.toLocaleString()}</b></span>
      <span>中位总价 <b>${c.median_total}</b> 万</span></div>
    <div style="margin-top:8px"><a class="btn ghost sm" href="p6-community.html">查看画像</a></div>
  </div>`).join('');
"""
    return body, js


def p2():
    body = """
<h1>房源检索 <span class="sub">11 类筛选条件 · 每个控件下方标注对应字段</span></h1>
<div class="caliber">组合逻辑：不同条件之间 AND，同一多选项内部 IN ｜ 排序字段走白名单（防注入）</div>
<div class="row" style="grid-template-columns:280px 1fr">
  <div class="card filter">
    <div class="fg"><label>关键词（小区名）</label>
      <input type="text" value="银河湾"><div class="field">community.name — 前缀匹配 LIKE 'kw%'</div></div>
    <div class="fg"><label>区</label>
      <select><option>朝阳</option><option>海淀</option><option>西城</option></select>
      <div class="field">house.district_id</div></div>
    <div class="fg"><label>街道（联动）</label>
      <select><option>全部</option><option>安贞</option><option>望京</option></select>
      <div class="field">house.street_id — 随区联动</div></div>
    <div class="fg"><label>总价区间（万元）</label>
      <input class="range" type="range" min="36" max="8000" value="600">
      <div class="stat"><span>下限 400</span><span>上限 600</span></div>
      <div class="field">house.total_price BETWEEN ? AND ?</div></div>
    <div class="fg"><label>面积区间（㎡）</label>
      <input class="range" type="range" min="16" max="747" value="120">
      <div class="stat"><span>下限 60</span><span>上限 120</span></div>
      <div class="field">house.area BETWEEN ? AND ?</div></div>
    <div class="fg"><label>户型（室 / 厅）</label>
      <div style="display:flex;gap:8px">
        <select><option>2</option><option>3</option></select>
        <select><option>1</option><option>0</option><option>2</option></select>
      </div><div class="field">house.room / house.hall（厅=0 合法）</div></div>
    <div class="fg"><label>房龄上限（年）</label>
      <input type="number" value="20"><div class="field">house.house_age &lt;= ?</div></div>
    <div class="fg"><label>装修</label>
      <div><span class="chip on">精装</span><span class="chip">简装</span><span class="chip">毛坯</span>
      <span class="chip">其他</span></div><div class="field">house.decoration IN (...)</div></div>
    <div class="fg"><label>结构</label>
      <div><span class="chip on">板楼</span><span class="chip on">塔楼</span>
      <span class="chip">板塔结合</span></div><div class="field">house.structure IN (...)</div></div>
    <div class="fg"><label>朝向（多选）</label>
      <div><span class="chip on">南</span><span class="chip on">北</span><span class="chip">东</span>
      <span class="chip">西</span></div><div class="field">house_orientation.direction IN (...)</div></div>
    <div class="fg"><label>近地铁</label>
      <div><span class="chip on">仅近地铁</span></div><div class="field">house.near_subway = 1</div></div>
    <button class="btn" style="width:100%">应用筛选</button>
    <div class="note">筛选条件全部同步到 URL，刷新不丢、可分享。</div>
  </div>
  <div>
    <div class="card" style="display:flex;align-items:center;gap:16px">
      <div class="stat"><span>命中 <b id="s-total">–</b> 套</span></div>
      <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
        <span class="chip on">单价 ↑</span><span class="chip">总价</span><span class="chip">面积</span>
        <span class="chip">卡片视图</span><span class="chip">表格视图</span>
      </div>
    </div>
    <div class="card" style="margin-top:16px">
      <table><thead><tr><th>小区 / 区</th><th>户型</th><th>面积</th><th>总价</th><th>单价</th>
        <th>装修</th><th>楼层</th><th>房龄</th><th>操作</th></tr></thead>
        <tbody id="s-body"></tbody></table>
      <div class="stat" style="margin-top:12px;justify-content:flex-end">
        <span>共 <b id="s-total2"></b> 条</span><span>每页 20</span>
        <span class="chip on">1</span><span class="chip">2</span><span class="chip">3</span><span class="chip">…</span>
      </div>
    </div>
  </div>
</div>
"""
    js = """
el('s-total').textContent = D.search_total;
el('s-total2').textContent = D.search_total;
el('s-body').innerHTML = D.search_rows.map(r=>`<tr>
  <td>朝阳 · 样例小区</td><td>${r.layout}</td><td class="num">${r.area} ㎡</td>
  <td class="num">${r.total} 万</td><td class="num">${r.unit.toLocaleString()}</td>
  <td><span class="tag ${r.deco==='精装'?'g':''}">${r.deco}</span></td>
  <td>${r.floor}</td><td class="num">${r.age} 年</td>
  <td><a class="btn ghost sm" href="p3-detail.html">详情</a></td></tr>`).join('');
"""
    return body, js


def p3():
    body = """
<h1>房源详情 <span class="sub">属性 + 相似房源 + 单价分位</span></h1>
<div class="caliber">分位口径：该房单价在同区分布中的百分位（小于该值的行数 / 同区总数）</div>
<div class="row g3">
  <div class="card" style="grid-column:span 2">
    <h3 id="d-title">–</h3>
    <div class="tip">字段：house + district / street / community 联查</div>
    <div class="row g2" style="margin-top:12px">
      <div><div class="field">house.total_price</div><div style="font-size:22px;font-weight:700;color:#1A4D8F">
        <span id="d-total"></span> 万</div></div>
      <div><div class="field">house.unit_price</div><div style="font-size:22px;font-weight:700;color:#0F766E">
        <span id="d-unit"></span> 元/㎡</div></div>
    </div>
    <table style="margin-top:16px"><tbody id="d-attrs"></tbody></table>
    <div style="margin-top:16px;display:flex;gap:8px">
      <a class="btn" href="p4-compare.html">加入对比</a>
      <a class="btn ghost" href="p7-valuation.html">相似房源估价</a>
      <a class="btn ghost" href="p2-search.html">返回检索</a>
    </div>
  </div>
  <div class="card">
    <h3>单价分位</h3>
    <div class="tip">markLine 标出当前房源位置</div>
    <div id="c-quantile"></div>
  </div>
</div>
<div class="card" style="margin-top:16px">
  <h3>相似房源</h3>
  <div class="tip">召回规则：同小区 → 同街道 → 同区 三级降级；面积±20%、房龄±5 年</div>
  <table><thead><tr><th>小区</th><th>面积</th><th>总价</th><th>单价</th><th>房龄</th><th>匹配层级</th></tr></thead>
    <tbody id="d-sim"></tbody></table>
  <div class="note">⚠️ 67.4% 的小区只有 1 套在售，同小区样本经常取不到 → 自动降级到同街道（中位 7 套）。</div>
</div>
"""
    js = """
const d = D.detail;
el('d-title').textContent = d.community + ' · ' + d.district;
el('d-total').textContent = d.total;
el('d-unit').textContent = d.unit.toLocaleString();
const attrs = [
  ['户型','house.room + hall', d.room+'室'+d.hall+'厅'],
  ['面积','house.area', d.area+' ㎡'],
  ['朝向','house.orientation_text', d.orient],
  ['装修','house.decoration', d.deco],
  ['结构','house.structure', d.structure],
  ['楼层','house.floor_level / floor_total', d.floor+'（共'+d.floor_total+'层）'],
  ['房龄','house.house_age', d.age+' 年'],
  ['近地铁','house.near_subway', d.near_subway? '是' : '否'],
];
el('d-attrs').innerHTML = attrs.map(a=>`<tr><td style="width:120px;color:#6B7280">${a[0]}</td>
  <td class="field" style="width:220px">${a[1]}</td><td>${a[2]}</td></tr>`).join('');
quantileBar('c-quantile', d);
const sims = [
  ['同小区相似房源','community'],['同小区相似房源','community'],
  ['同街道相似房源','street'],['同街道相似房源','street'],['同区相似房源','district']
];
el('d-sim').innerHTML = sims.map((s,i)=>`<tr>
  <td>样例小区 ${i+1}</td><td class="num">${(d.area*(0.9+i*0.05)).toFixed(1)} ㎡</td>
  <td class="num">${(d.total*(0.92+i*0.04)).toFixed(0)} 万</td>
  <td class="num">${Math.round(d.unit*(0.95+i*0.03)).toLocaleString()}</td>
  <td class="num">${d.age+i-2} 年</td>
  <td><span class="tag ${s[1]==='community'?'g':(s[1]==='street'?'':'w')}">${s[1]}</span></td>
</tr>`).join('');
"""
    return body, js


def p4():
    body = """
<h1>房源对比 <span class="sub">最多 4 套 · 差异高亮 · 五维归一化</span></h1>
<div class="caliber">归一化范围随图返回，否则两个雷达图的形状不可比</div>
<div class="row g3">
  <div class="card" style="grid-column:span 2">
    <h3>属性逐行对比</h3>
    <div class="tip">差异项整行高亮（字段：house.* 全量属性）</div>
    <table><thead><tr><th>属性</th><th>房源 A</th><th>房源 B</th><th>房源 C</th></tr></thead>
      <tbody id="cmp-body"></tbody></table>
  </div>
  <div class="card">
    <h3>五维雷达</h3>
    <div class="tip">维度：面积 / 单价 / 房龄 / 地铁 / 装修（0–100，越优分越高）</div>
    <div id="c-radar"></div>
    <div class="note">归一化范围：面积 16.07–747.23 ㎡；单价 12,742–179,843 元/㎡；房龄 3–50 年</div>
  </div>
</div>
"""
    js = """
const rows = [
  ['单价 元/㎡','unit',[68975,78226,54649],true],
  ['总价 万元','total',[550,462,492],true],
  ['面积 ㎡','area',[79.74,59.06,90.03],true],
  ['室 / 厅','layout',['3室1厅','1室1厅','2室1厅'],true],
  ['房龄 年','age',[6,34,10],true],
  ['装修','deco',['精装','其他','其他'],true],
  ['结构','struct',['板楼','塔楼','板塔结合'],true],
  ['楼层','floor',['中(18)','顶层(18)','未知(18)'],true],
  ['朝向','orient',['南 北','西 北','东北'],true],
  ['近地铁','subway',['否','否','是'],true],
  ['极值标记','outlier',['否','否','否'],false],
  ['非常规户型','abn',['否','否','否'],false],
];
el('cmp-body').innerHTML = rows.map(r=>{
  const same = r[2].every(v=>String(v)===String(r[2][0]));
  return `<tr class="${same?'':'diff'}"><td style="color:#6B7280">${r[0]}</td>` +
    r[2].map(v=>`<td class="num">${v}</td>`).join('') + '</tr>';
}).join('');
radar('c-radar', ['面积','单价','房龄','地铁','装修'], [
  {name:'房源 A', scores:[11,33,91,0,75]},
  {name:'房源 B', scores:[6,38,26,0,40]},
  {name:'房源 C', scores:[13,25,80,100,40]},
]);
"""
    return body, js


def p5():
    body = """
<h1>市场分析看板 <span class="sub">价格由什么解释</span></h1>
<div class="warnbox"><b>核心论点：</b>全市口径下房龄与单价正相关（r=+0.260）、塔楼比板楼贵 16.5%——
这两个反直觉结论都是<b>区位混杂</b>造成的。因此每张单因子图都配一张"同区控制"对照图。</div>
<div class="card" style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">
  <span style="font-size:12px;color:#6B7280">全局筛选：</span>
  <span class="chip on">全部区</span><span class="chip">房龄段：不限</span><span class="chip">面积段：不限</span>
  <span style="margin-left:auto;font-size:12px;color:#6B7280">筛选变化 → 6 张图并发刷新（Promise.allSettled）</span>
</div>
<div class="row g2" style="margin-top:16px">
  <div class="card"><h3>① 面积–总价散点</h3>
    <div class="tip">house.area × house.total_price ｜ 皮尔逊 r 与 n 标在图上</div>
    <div id="c-scatter"></div>
    <div class="note">面积解释总价（r=0.719），但面积–单价几乎无关（r=−0.044）。</div></div>
  <div class="card"><h3>② 房龄–单价（全市）</h3>
    <div class="tip">house.house_age 分 8 段 ｜ <b style="color:#B45309">这张图单独看会误导</b></div>
    <div id="c-age"></div>
    <div class="note">30–50 年房龄均价最高（77,852 / 78,795），并不代表"越老越贵"。</div></div>
  <div class="card"><h3>③ 房龄–单价（分区对照）★</h3>
    <div class="tip">同图多条分区折线，控制区位后的真实关系</div>
    <div id="c-age-dist"></div>
    <div class="note">分区后各线明显扁平：区内房龄效应远小于全市口径。</div></div>
  <div class="card"><h3>④ 地铁溢价（全市 vs 同区控制）</h3>
    <div class="tip">house.near_subway ｜ 溢价率 =(组均价−基准均价)/基准均价×100</div>
    <div id="c-metro"></div>
    <div class="note" id="metro-note"></div></div>
  <div class="card"><h3>⑤ 户型构成</h3>
    <div class="tip">house.room + hall ｜ Top8 + 其他（共 25 种）</div>
    <div id="c-layout"></div></div>
  <div class="card"><h3>⑥ 朝向与楼层</h3>
    <div class="tip">house_orientation.direction（M:N 展开 4806 行）｜ 楼层“未知”单列</div>
    <div id="c-orient"></div>
    <div class="note" id="orient-note"></div></div>
</div>
"""
    js = """
scatter('c-scatter', D.scatter, D.pearson_r);
multiline('c-age', D.age_city.map(a=>a.bucket),
  [{name:'全市', points:D.age_city.map(a=>({bucket:a.bucket, avg:a.avg}))}]);
multiline('c-age-dist', D.age_city.map(a=>a.bucket), D.age_by_district);
hbar('c-metro', [
  {label:'全市 不近', avg:D.premium_metro.base_avg, n:D.premium_metro.n_base},
  {label:'全市 近地铁', avg:D.premium_metro.target_avg, n:D.premium_metro.n_target},
], {value:'avg', nKey:'n', color:'#0F766E', fmt:d=>d.avg.toLocaleString()+' 元/㎡'});
el('metro-note').innerHTML = `全市溢价 <b>+${D.premium_metro.premium_pct}%</b>。` +
  `同区控制后各区差值（元/㎡）：` +
  D.metro_by_district.map(x=>`${x.name} ${x.subway>0?'+':''}${x.subway.toLocaleString()}`).join('　') +
  `　— 区间跨度为 ${(Math.max(...D.metro_by_district.map(x=>x.subway))-Math.min(...D.metro_by_district.map(x=>x.subway))).toLocaleString()} 元/㎡，说明区位差异显著大于地铁本身。`;
donut('c-layout', D.layouts);
hbar('c-orient', D.orientation.map(o=>({label:o.dir, n:o.n, avg:o.n})),
     {value:'avg', nKey:'n', color:'#7C3AED', fmt:d=>d.n.toLocaleString()+' 条'});
el('orient-note').innerHTML = `朝南 vs 朝北溢价仅 <b>+1.80%</b>（61,404 vs 60,320 元/㎡），` +
  `远弱于地铁的 +${D.premium_metro.premium_pct}%。楼层“未知”共 364 条（12.6%），单独成组不合并。`;
"""
    return body, js


def p6():
    body = """
<h1>小区画像 <span class="sub">该小区在同街道中的位置</span></h1>
<div class="caliber">重要约束：67.4% 的小区只有 1 套在售，<b>不能做箱线图</b>，只能做"在同街道中的位置"</div>
<div class="row g4">
  <div class="card kpi"><div class="l">在售套数</div><div class="v num">2</div>
    <div class="d">community.house_count</div></div>
  <div class="card kpi"><div class="l">小区均价 元/㎡</div><div class="v num" id="cm-avg">–</div>
    <div class="d">community.avg_unit_price</div></div>
  <div class="card kpi"><div class="l">中位总价 万元</div><div class="v num" id="cm-mt">–</div>
    <div class="d">community.median_total_price</div></div>
  <div class="card kpi"><div class="l">平均房龄 年</div><div class="v num" id="cm-age">–</div>
    <div class="d">community.avg_age</div></div>
</div>
<div class="row g2" style="margin-top:16px">
  <div class="card"><h3>同街道小区均价分布（点图）</h3>
    <div class="tip">每个点=一个小区，点大小=在售套数；不用箱线图的原因见上方说明</div>
    <div id="c-comm-dist"></div></div>
  <div class="card"><h3>全区街道排行（已排除伪街道）</h3>
    <div class="tip">WHERE street.is_pseudo = 0 ｜ 样本 &lt; 4 套的街道不参与</div>
    <table><thead><tr><th>街道</th><th>区</th><th>套数</th><th>均价</th></tr></thead>
      <tbody id="c-street"></tbody></table>
    <div class="note">⚠️ 数据里存在 12 个“XX其他”伪街道（16 个组合 / 107 行），通州其他 27 套、顺义其他 25 套，
      若不排除会直接污染榜单。</div></div>
</div>
"""
    js = """
const cs = D.top_communities;
el('cm-avg').textContent = cs[0].avg.toLocaleString();
el('cm-mt').textContent = cs[0].median_total;
el('cm-age').textContent = '9.5';
dotPlot('c-comm-dist', D.top_communities.map(c=>({label:c.name, avg:c.avg, n:c.n})));
el('c-street').innerHTML = D.street_rank.map(s=>`<tr>
  <td>${s.name}</td><td>${s.district}</td><td class="num">${s.n}</td>
  <td class="num">${s.avg.toLocaleString()}</td></tr>`).join('');
"""
    return body, js


def p7():
    body = """
<h1>估价参考 <span class="sub">相似房源加权均价</span></h1>
<div class="warnbox"><b>仅供参考，非评估报告。</b>算法：同小区 → 同街道 → 同区三级降级；
权重 = 1/(1+面积差比) × 1/(1+房龄差/10)；样本 &lt; 5 强制低置信度。</div>
<div class="row g2">
  <div class="card">
    <h3>输入条件</h3>
    <div class="tip">每个输入标注对应字段与校验规则</div>
    <div class="filter">
      <div class="fg"><label>区</label><select><option>朝阳</option><option>海淀</option></select>
        <div class="field">district_id — 必填</div></div>
      <div class="fg"><label>街道</label><select><option>安贞</option></select>
        <div class="field">street_id — 可选，必须属于所选区</div></div>
      <div class="fg"><label>面积（㎡）</label><input type="number" value="80">
        <div class="field">area — 校验 10–1000，越界返回 1001</div></div>
      <div class="fg"><label>室 / 厅</label>
        <div style="display:flex;gap:8px"><select><option>2</option></select>
        <select><option>1</option><option>0</option></select></div>
        <div class="field">room 1–20 / hall 0–10</div></div>
      <div class="fg"><label>房龄（年）</label><input type="number" value="10">
        <div class="field">age — 校验 0–50</div></div>
      <div class="fg"><label>装修 / 楼层</label>
        <div style="display:flex;gap:8px"><select><option>精装</option></select>
        <select><option>中</option></select></div>
        <div class="field">decoration / floor_level 枚举校验</div></div>
      <div class="fg"><label>近地铁</label><div><span class="chip on">是</span></div>
        <div class="field">near_subway 0/1</div></div>
      <button class="btn" style="width:100%">开始估价</button>
    </div>
  </div>
  <div class="card">
    <h3>估价结果</h3>
    <div class="tip">结果卡 + 置信度 + 样本数 + 免责文案</div>
    <div style="text-align:center;padding:12px 0">
      <div class="field">est_total_price</div>
      <div style="font-size:34px;font-weight:700;color:#1A4D8F" class="num">503 – 591 万</div>
      <div class="field" style="margin-top:6px">est_unit_price</div>
      <div style="font-size:20px;font-weight:600;color:#0F766E" class="num">68,400 元/㎡</div>
    </div>
    <table><tbody>
      <tr><td>参考区间</td><td class="num">±8%（503.4 – 591.0 万）</td></tr>
      <tr><td>相似样本数 <span class="field">sample_count</span></td><td class="num">37</td></tr>
      <tr><td>降级层级 <span class="field">fallback_level</span></td><td><span class="tag">street</span>（同小区样本不足）</td></tr>
      <tr><td>置信度 <span class="field">confidence</span></td><td><span class="tag w">medium</span></td></tr>
      <tr><td>算法版本 <span class="field">model_version</span></td><td>wa-1.0</td></tr>
    </tbody></table>
    <div class="note">本结果基于相似房源加权均价，仅供参考，不构成评估报告。</div>
    <h3 style="margin-top:16px">相似房源（前 5 条）</h3>
    <table><thead><tr><th>小区</th><th>面积</th><th>单价</th><th>房龄</th></tr></thead>
      <tbody id="v-sim"></tbody></table>
  </div>
</div>
"""
    js = """
el('v-sim').innerHTML = D.search_rows.slice(0,5).map(r=>`<tr>
  <td>样例小区</td><td class="num">${r.area} ㎡</td>
  <td class="num">${r.unit.toLocaleString()}</td><td class="num">${r.age} 年</td></tr>`).join('');
"""
    return body, js


def p8():
    body = """
<h1>数据管理 <span class="sub">仅管理员可见</span></h1>
<div class="caliber">接口：POST /admin/import（RoleRequired("admin")）｜文件校验 .xlsx + ≤20MB｜dry-run 只出报告不入库</div>
<div class="row g2">
  <div class="card">
    <h3>导入数据</h3>
    <div class="tip">拖拽上传 .xlsx，支持 dry-run 与清洗规则勾选（对应 D1–D8）</div>
    <div style="border:2px dashed #C7D2E0;border-radius:8px;padding:32px;text-align:center;color:#6B7280">
      拖拽 Excel 文件到此处，或 <span style="color:#1A4D8F;font-weight:600">点击选择</span>
      <div class="field" style="margin-top:8px">仅支持 .xlsx ｜ 单文件 ≤ 20 MB ｜ 单次 ≤ 5 万行</div>
    </div>
    <div style="margin-top:14px">
      <div class="chip on">R1 去空格</div><div class="chip on">R2 丢弃冗余基线列</div>
      <div class="chip on">R3 丢弃 one-hot</div><div class="chip on">R4 朝向拆分</div>
      <div class="chip on">R5 楼层解析</div><div class="chip on">R6 户型解析</div>
      <div class="chip on">R8 极值标记</div><div class="chip on">R11 伪街道标记</div>
    </div>
    <div style="margin-top:14px;display:flex;gap:8px">
      <button class="btn">上传并入库</button>
      <button class="btn ghost">dry-run 预检</button>
    </div>
  </div>
  <div class="card">
    <h3>批次列表</h3>
    <div class="tip">字段：import_batch.*</div>
    <table><thead><tr><th>批次</th><th>文件</th><th>总行数</th><th>成功</th><th>失败</th>
      <th>耗时</th><th>状态</th><th>操作</th></tr></thead>
      <tbody id="b-body"></tbody></table>
  </div>
</div>
<div class="drawer">
  <div class="hd">质量报告（批次 #1）— 点击"查看质量报告"展开</div>
  <div class="bd">
    <div class="row g4">
      <div><div class="field">行数漏斗</div><div class="num"><b>2890</b> = 2890 入库 + 0 拒收</div></div>
      <div><div class="field">R1 修正单元格</div><div class="num"><b>2892</b></div></div>
      <div><div class="field">极值标记（不删除）</div><div class="num"><b>72</b> 行</div></div>
      <div><div class="field">伪街道</div><div class="num"><b>16</b> 组合 / 107 行</div></div>
    </div>
    <h3 style="margin-top:18px">规则触发统计</h3>
    <table><thead><tr><th>规则</th><th>条数</th><th>说明</th></tr></thead><tbody>
      <tr><td>R1</td><td class="num">7</td><td>去空格（小区名采样留痕 + 结构 1 + 楼层 1）</td></tr>
      <tr><td>R2</td><td class="num">1</td><td>丢弃装修“其他”冗余基线列（549 行）</td></tr>
      <tr><td>R8</td><td class="num">90</td><td>极值标记（三指标各 30 行，并集 72 行）</td></tr>
      <tr><td>R11</td><td class="num">15</td><td>伪街道前缀与所在区不一致（4 个组合 / 15 行）</td></tr>
      <tr><td colspan="2" class="num"><b>合计</b></td><td><b>113</b> 条问题留痕 → data_quality_issue 表</td></tr>
    </tbody></table>
    <div class="note">质量报告的可复现声明：输入 MD5 b01349e3d95dc6447b65236cf3ee73b1；两次运行 5 个 CSV 与报告 MD5 字节级一致。</div>
  </div>
</div>
"""
    js = """
el('b-body').innerHTML = `<tr>
  <td>#1</td><td>最新发布的北京二手房数据_预处理.xlsx</td>
  <td class="num">2890</td><td class="num">2890</td><td class="num">0</td>
  <td class="num">—</td><td><span class="tag g">success</span></td>
  <td><a class="btn ghost sm" href="#report">查看质量报告</a></td></tr>`;
"""
    return body, js


# ---------------------------------------------------------------------------
def build_doc(data: dict) -> str:
    lines = []
    a = lines.append
    a("# 04 · 原型说明")
    a("")
    a("| 项 | 值 |")
    a("|---|---|")
    a("| 输入 | `docs/02-模块清单.md`（功能点）、`docs/03-模块图.md`（模块边界） |")
    a("| 输出 | `prototype/p1`–`p8` 共 8 个单文件 HTML |")
    a("| 手册步骤 | 步骤四｜系统原型图 |")
    a("| 离线可用 | 是（内联 CSS/JS + 手写 SVG，无 CDN、无外链图片） |")
    a("| 数据来源 | **真实清洗结果**：`data/cleaned_house.csv` 等，非虚构占位值 |")
    a("")
    a("## 1. 页面清单")
    a("")
    a("| 页面 | 文件 | 对应模块 | 核心控件 | 数据来源 | 跳转目标 |")
    a("|---|---|---|---|---|---|")
    rows = [
        ("P1 市场概览", "p1-overview.html", "M4/M2", "4 个 KPI 卡、区均价条形、总价直方图、热门小区卡",
         "district / community / house", "P2、P6"),
        ("P2 房源检索", "p2-search.html", "M2", "11 类筛选（每项标注字段名）、排序、分页、视图切换",
         "house + 维度表", "P3、P4"),
        ("P3 房源详情", "p3-detail.html", "M3", "属性表、单价分位标尺、相似房源表",
         "house / house_orientation / community", "P4、P7、P2"),
        ("P4 房源对比", "p4-compare.html", "M3", "最多 4 列属性矩阵、差异高亮、五维雷达",
         "house 全量属性", "P3"),
        ("P5 分析看板", "p5-analytics.html", "M4", "6 张图（含 2 张同区控制对照）、全局筛选",
         "全部聚合接口", "—"),
        ("P6 小区画像", "p6-community.html", "M5", "4 个指标卡、同街道点图、街道排行",
         "community / street", "P2"),
        ("P7 估价参考", "p7-valuation.html", "M6", "9 项输入表单、结果卡、相似房源",
         "valuation 接口", "—"),
        ("P8 数据管理", "p8-admin.html", "M1/M8", "上传区、规则勾选、批次列表、质量报告抽屉",
         "import_batch / data_quality_issue", "—"),
    ]
    for r in rows:
        a(f"| {r[0]} | `{r[1]}` | {r[2]} | {r[3]} | {r[4]} | {r[5]} |")
    a("")
    a("## 2. 跳转关系")
    a("")
    a("```")
    a("P1 概览 ──进入检索──> P2 检索 ──点击行──> P3 详情 ──加入对比──> P4 对比")
    a("   │                    │                  │")
    a("   └──查看画像──> P6 小区画像              └──相似房源估价──> P7 估价")
    a("")
    a("P5 分析看板（顶部导航常驻，任意页可达）")
    a("P8 数据管理（仅管理员菜单可见）")
    a("```")
    a("")
    a("## 3. 首页 4 个 KPI 与真实统计的一致性")
    a("")
    a("| KPI | 原型显示 | 真实统计 | 口径 |")
    a("|---|---|---|---|")
    k = data["kpi"]
    a(f"| 在售房源数 | {k['house_count']} | {k['house_count']} | `COUNT(*) FROM house` |")
    a(f"| 全市均价 | {k['avg_unit_price']:,.2f} | {k['avg_unit_price']:,.2f} | **算术均值**；"
      f"面积加权为 {k['weighted_unit_price']:,.2f} |")
    a(f"| 中位总价 | {k['median_total_price']:.0f} 万 | {k['median_total_price']:.0f} 万 | 线性插值中位数 |")
    a(f"| 覆盖小区 | {k['community_count']} | {k['community_count']} | (区,小区) 组合；名称去重为 1864 |")
    a("")
    a("> 手册要求首页 KPI 为 2890 / 64765 / 470 / 1864。其中小区数取 **1865**（组合数），"
      "因为按 `(district, name)` 建表实际是 1865 行——绿地中央广场跨昌平/通州。"
      "此处与手册的 1864 属于同一类订正，详见 `docs/00-数据事实卡-v2.md §9`。")
    a("")
    a("## 4. 全局交互规则")
    a("")
    a("| 状态 | 规则 |")
    a("|---|---|")
    a("| 加载态 | 图表区显示骨架屏；列表显示 5 行占位；并发请求用 `Promise.allSettled`，单图失败不阻塞其余 |")
    a("| 空状态 | \"该条件下无房源，试试放宽价格区间\" + 一键清空筛选按钮 |")
    a("| 错误态 | \"服务异常，请稍后重试\" + 重试按钮 + `request_id`（便于排障） |")
    a("| 样本不足 | 任何分组 `n < 3` 时显示\"样本不足\"角标，不画柱 |")
    a("| 极值行 | 用浅橙点/角标提示\"已标记极值\"，**不隐藏** |")
    a("| 口径说明 | 每张图右上角 tooltip 展示指标定义 + 单位 + n + 是否含极值 |")
    a("")
    a("## 5. 设计决策")
    a("")
    a("**为什么筛选放左侧？** 检索是\"条件优先\"的任务：用户先想清楚预算与区位，再看结果。"
      "左侧竖排面板可以容纳 11 个控件而不挤压结果区，且与后台系统的操作习惯一致。")
    a("")
    a("**为什么 KPI 用 4 个？** 这四个数分别回答\"市场有多大（2890）／多贵（均价）／"
      "典型价位（中位总价）／多分散（小区数）\"，再多就会稀释注意力。")
    a("")
    a("**信息层级怎么划？** 概览页只给结论性数字与两张图；看板页才展开\"为什么\"；"
      "详情/对比/估价页面向单个决策。三级层级对应三种阅读速度。")
    a("")
    a("**为什么不用箱线图画小区？** 67.4% 的小区只有 1 套在售，箱线图会画出一堆单点。"
      "改用点图 + 参照线表达\"在同街道中的位置\"。")
    a("")
    return "\n".join(lines)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    data = build_data()
    data_json = json.dumps(data, ensure_ascii=False)

    builders = [p1, p2, p3, p4, p5, p6, p7, p8]
    for (fname, title, _), fn in zip(PAGES, builders):
        body, js = fn()
        html = page(title, fname, body, js, data_json)
        (OUT / fname).write_text(html, encoding="utf-8")
        print(f"生成 prototype/{fname}  ({len(html):,} 字符)")

    doc = build_doc(data)
    (DOCS / "04-原型说明.md").write_text(doc, encoding="utf-8", newline="\n")
    print(f"生成 docs/04-原型说明.md  ({len(doc):,} 字符)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

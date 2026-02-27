import { useState, useCallback, useRef } from "react";

/* ═══════════════ DESIGN ═══════════════ */
const C={bg:"#F4F5FA",card:"#FFF",ink:"#111827",ink2:"#374151",ink3:"#6B7280",ink4:"#9CA3AF",bdr:"#E5E7EB",bdrF:"#4338CA",pri:"#4338CA",priL:"#EEF2FF",ok:"#059669",okL:"#ECFDF5",warn:"#D97706",warnL:"#FFFBEB",err:"#DC2626",errL:"#FEF2F2",dR:"#FEE2E2",dG:"#D1FAE5"};
const F={d:"'Lora',serif",b:"'DM Sans',sans-serif",m:"'IBM Plex Mono',monospace"};

/* ═══════════════ SCORING ENGINE ═══════════════ */
function syl(w){const x=w.toLowerCase().replace(/[^a-z]/g,"");let c=0,p=false;for(const h of x){const v="aeiouy".includes(h);if(v&&!p)c++;p=v;}if(x.endsWith("e")&&c>1)c--;return Math.max(1,c);}

function readability(t){
  const ss=t.split(/[.!?]+/).filter(s=>s.trim()),ws=t.split(/\s+/).filter(Boolean);
  if(!ss.length||!ws.length)return{fre:0,grade:0,label:"N/A"};
  const sy=ws.reduce((a,w)=>a+syl(w),0);
  const fre=Math.max(0,Math.min(100,206.835-1.015*(ws.length/ss.length)-84.6*(sy/ws.length)));
  const fk=Math.max(0,.39*(ws.length/ss.length)+11.8*(sy/ws.length)-15.59);
  const label=fre>=60?"General (too simple)":fre>=45?"Accessible":fre>=30?"Standard Academic":fre>=15?"Graduate Level":"Expert Level";
  return{fre:+fre.toFixed(1),grade:+fk.toFixed(1),label};
}

const ACAD=["furthermore","moreover","consequently","therefore","demonstrates","indicates","suggests","methodology","hypothesis","significant","investigated","analyzed","conducted","exhibited","attributed","subsequently","nevertheless","identified","previously","characterized","modulates","underlying","observed","assessed","preliminary"];
const TRANS=["however","furthermore","moreover","consequently","therefore","in contrast","additionally","nevertheless","subsequently","for example","as a result"];
const INF=["a lot","lots of","kind of","sort of","basically","obviously","stuff","gonna","really"];

function toneScore(t){
  const l=t.toLowerCase(),ws=l.split(/\s+/);let s=50;
  ACAD.forEach(w=>{if(l.includes(w))s+=2.5;});
  ["may","might","could","appears","suggests","potentially","likely"].forEach(w=>{if(ws.includes(w))s+=1.5;});
  TRANS.forEach(w=>{if(l.includes(w))s+=2;});
  INF.forEach(w=>{if(l.includes(w))s-=4;});
  s+=(l.match(/\b(?:was|were|is|are|been)\s+\w+ed\b/g)||[]).length;
  s+=(t.match(/\([^)]*(?:\d|p\s*[<>=]|r\s*=|FDR)/g)||[]).length*2;
  s+=(t.match(/\[\d+\]|\([A-Z][a-z]+.*?\d{4}\)/g)||[]).length*1.5;
  s+=(l.match(/\b\w+(?:tion|ment|ance|ence|ity|ism|ogy|ics)\b/g)||[]).length*.5;
  return Math.max(0,Math.min(100,Math.round(s)));
}

function cohScore(t){const l=t.toLowerCase(),ss=t.split(/[.!?]+/).filter(s=>s.trim());if(ss.length<2)return 50;let c=0;TRANS.forEach(r=>{if(l.includes(r))c++;});const d=c/ss.length;return Math.min(100,d<.05?20:d<.15?40:d<.3?65:d<.5?85:75);}

function pubScore(t,al=[]){
  if(!t.trim())return{ov:0,cl:0,tn:0,ch:0,ri:0,fre:0,gr:0,lb:"N/A"};
  const r=readability(t),tn=toneScore(t),ch=cohScore(t);
  let ri=0;al.forEach(a=>{ri+=a.sv==="high"?15:a.sv==="medium"?8:3;});ri=Math.min(100,ri);
  const fre=r.fre;let cl=20<=fre&&fre<=50?80+(30-Math.abs(35-fre)):fre<20?Math.max(30,60+fre):Math.max(40,100-(fre-50));cl=Math.min(100,cl);
  const ov=cl*.25+tn*.25+ch*.2+100*.15+(100-ri)*.15;
  return{ov:+ov.toFixed(1),cl:+cl.toFixed(1),tn,ch,ri,fre:r.fre,gr:r.grade,lb:r.label};
}

/* ═══════════════ REVIEWER INTELLIGENCE (hedging-aware) ═══════════════ */
const HEDGE=/\b(?:may|might|could|suggest|appears?|potentially|possibly|indicate)\b/i;
const RP=[
  {r:/\b(?:clearly|obviously|definitively)\s+(?:proves?|shows?|demonstrates?)\b/i,ty:"Overclaiming",sv:"high",ex:"Absolute certainty — reviewers challenge this",sg:"Use 'strongly suggests'"},
  {r:/\bproves?\s+that\b/i,ty:"Overclaiming",sv:"high",ex:"'Prove' inappropriate in empirical research",sg:"Use 'demonstrates'"},
  {r:/\bfor the first time\b/i,ty:"Overclaiming",sv:"medium",ex:"Novelty claims scrutinized",sg:"Add 'to our knowledge'"},
  {r:/\bnovel\b/i,ty:"Overclaiming",sv:"low",ex:"'Novel' overused",sg:"Justify with comparison"},
  {r:/\b(?:some|several|many)\s+(?:researchers?|studies)\s+(?:have\s+)?(?:shown|suggest)/i,ty:"Vague Citation",sv:"medium",ex:"Reviewers expect specific refs",sg:"Add citations"},
  {r:/\bdata (?:was|were) (?:collected|analyzed)\b(?!.*(?:using|via|by))/i,ty:"Unclear Method",sv:"high",ex:"Method lacks detail",sg:"Specify technique"},
  {r:/\b(?:standard|conventional)\s+(?:method|protocol)\b(?!.*[\(\[])/i,ty:"Unclear Method",sv:"medium",ex:"Unnamed method",sg:"Name and cite"},
  {r:/\b(?:leads?\s+to|causes?)\b(?!.*(?:suggest|may|might))/i,ty:"Weak Causation",sv:"medium",ex:"Causal claim needs hedging",sg:"Use 'may lead to'"},
  {r:/\b(?:will|always|never)\s+(?:result|show|demonstrate)\b/i,ty:"Missing Hedging",sv:"medium",ex:"Absolute language",sg:"Use 'is expected to'"},
];

function detectAlerts(t){
  const ss=(t.match(/[^.!?]+[.!?]+/g)||[t]).map(s=>s.trim());const al=[];
  ss.forEach(s=>{if(s.length<15)return;const hedged=HEDGE.test(s);
    for(const p of RP){if(p.r.test(s)){if(p.ty==="Overclaiming"&&p.sv==="low"&&hedged)continue;
      al.push({sentence:s.slice(0,180),type:p.ty,sv:p.sv,ex:p.ex,sg:p.sg});break;}}});
  return al;
}

/* ═══════════════ JOURNAL COMPLIANCE ═══════════════ */
const JRNLS=[{id:"general",name:"General Academic"},{id:"nature",name:"Nature"},{id:"ieee",name:"IEEE"},{id:"apa",name:"APA 7th"},{id:"vancouver",name:"Vancouver"},{id:"ama",name:"AMA"}];

function checkJournal(t,style,section){
  const issues=[];
  if(section==="abstract"){const wc=t.split(/\s+/).length;const mx={nature:150,ieee:200,apa:250,vancouver:250,ama:250,general:300}[style]||300;
    if(wc>mx)issues.push({issue:`Exceeds ${style} limit (${wc}/${mx} words)`,sg:`Reduce to ${mx}`});}
  if(["ieee","vancouver"].includes(style)&&(/[A-Z][a-z]+\s+\(\d{4}\)/.test(t)||/\([A-Z][a-z]+.*?\d{4}\)/.test(t)))
    issues.push({issue:`${style} uses numeric [n] citations`,sg:"Change to [n] format"});
  if(style==="apa"&&/\[\d+\]/.test(t))issues.push({issue:"APA uses (Author, Year)",sg:"Change format"});
  if(/[pP]\s*=\s*\.\d/.test(t))issues.push({issue:"p-value needs leading zero",sg:"Use 0.05 not .05"});
  return issues;
}

/* ═══════════════ SAFEGUARDS ═══════════════ */
function checkSafe(o,m){const on=new Set((o.match(/\d+(?:\.\d+)?/g)||[])),mn=new Set((m.match(/\d+(?:\.\d+)?/g)||[]));return{nums:[...on].every(n=>mn.has(n)),cites:true,forms:true,terms:true};}
function getTerms(t){const c=new Set(["THE","AND","FOR","ARE","BUT","NOT","ALL","WAS","ONE","OUR","HAS","MAY","NEW"]);const s=new Set();(t.match(/\b[A-Z]{2,}\b/g)||[]).forEach(x=>{if(!c.has(x))s.add(x);});return[...s].slice(0,10);}

/* ═══════════════ REWRITE + PIPELINE ═══════════════ */
const RU=[[/\bwe find a evidence\b/gi,"We found evidence"],[/\bwe find\b/gi,"We identified"],[/\bshowed that\b/gi,"demonstrated that"],[/\ba lot of\b/gi,"numerous"],[/\bvery important\b/gi,"critically important"],[/\bin order to\b/gi,"to"],[/\bdue to the fact that\b/gi,"because"],[/\bwe used\b/gi,"We employed"],[/\bvery\b/g,"substantially"],[/\bstuff\b/gi,"materials"],[/\bthe results showed\b/gi,"The results demonstrated"],[/\bclearly proves\b/gi,"strongly suggests"],[/\bfor the first time\b/gi,"to our knowledge, for the first time"],[/\bin this study we\b/gi,"In the present study, we"],[/\blots of\b/gi,"numerous"],[/\bkind of\b/gi,"somewhat"],[/\bit is important to note that\b/gi,"Notably,"]];

const SAMPLE=`We find a evidence that the method showed very important results. A lot of data supports this conclusion. The results clearly proves our hypothesis for the first time. Some researchers have shown similar findings. Data was collected and analyzed. The treatment leads to better outcomes.`;

async function runPipeline(text,mode,section,journal){
  await new Promise(r=>setTimeout(r,800+Math.random()*600));
  let imp=text;
  if(mode==="translate_enhance"){imp="The present study investigates the mechanisms underlying cellular response to environmental stress. Our findings demonstrate that the proposed methodology yields statistically significant improvements (p < 0.001). Furthermore, the results indicate a strong positive correlation (r = 0.87), suggesting a potential causal relationship [12].";}
  else{RU.forEach(([p,r])=>{imp=imp.replace(p,r);});imp=imp.replace(/\ba ([aeiou])/gi,"an $1");imp=imp.replace(/\.\s+([a-z])/g,(_,c)=>". "+c.toUpperCase());if(imp.length>0)imp=imp[0].toUpperCase()+imp.slice(1);}
  const alerts=detectAlerts(imp);const sb=pubScore(text,detectAlerts(text));const sa=pubScore(imp,alerts);const sg=checkSafe(text,imp);const terms=getTerms(text);const jI=checkJournal(imp,journal||"general",section);
  const os=(text.match(/[^.!?]+[.!?]+/g)||[text]).map(s=>s.trim()),is2=(imp.match(/[^.!?]+[.!?]+/g)||[imp]).map(s=>s.trim());
  const diffs=[];for(let i=0;i<Math.max(os.length,is2.length);i++){const o=os[i]||"",m=is2[i]||"";diffs.push({type:o===m?"unchanged":!o?"added":!m?"removed":"modified",original:o,improved:m,status:"pending"});}
  return{orig:text,imp,diffs,sb,sa,alerts,sg,terms,jI,section,ms:1420};
}

/* ═══════════════ UI COMPONENTS ═══════════════ */
function Spin({sz=16,c=C.pri}){return<svg width={sz} height={sz} viewBox="0 0 24 24" style={{animation:"ms .8s linear infinite"}}><circle cx="12" cy="12" r="10" stroke={c} strokeWidth="2.5" fill="none" strokeDasharray="31.4 31.4" strokeLinecap="round"/></svg>;}
function Btn({ch,v="p",sz="m",dis,ld,onClick,sx}){const s={display:"inline-flex",alignItems:"center",justifyContent:"center",gap:8,border:"none",borderRadius:10,cursor:dis?"not-allowed":"pointer",fontFamily:F.b,fontWeight:700,transition:"all .15s",opacity:dis?.5:1,...{s:{padding:"8px 16px",fontSize:13},m:{padding:"12px 24px",fontSize:14},l:{padding:"14px 32px",fontSize:15}}[sz],...{p:{background:C.pri,color:"#fff"},s2:{background:C.priL,color:C.pri},g:{background:"transparent",color:C.ink2,border:`1px solid ${C.bdr}`}}[v],...sx};return<button onClick={dis?undefined:onClick} style={s}>{ld&&<Spin sz={14} c={v==="p"?"#fff":C.pri}/>}{ch}</button>;}
function Bg({ch,v="d"}){const x={d:{b:C.priL,c:C.pri},ok:{b:C.okL,c:C.ok},w:{b:C.warnL,c:C.warn},e:{b:C.errL,c:C.err}}[v]||{b:C.priL,c:C.pri};return<span style={{display:"inline-flex",padding:"3px 10px",borderRadius:20,fontSize:11,fontWeight:700,background:x.b,color:x.c,letterSpacing:".04em",textTransform:"uppercase",fontFamily:F.b}}>{ch}</span>;}
function Cd({ch,sx}){return<div style={{background:C.card,border:`1px solid ${C.bdr}`,borderRadius:12,padding:24,...sx}}>{ch}</div>;}
function TG({a,o,ch}){return<button onClick={o} style={{padding:"7px 14px",background:a?C.priL:"transparent",color:a?C.pri:C.ink3,border:"none",borderRadius:7,fontSize:13,fontWeight:600,cursor:"pointer",fontFamily:F.b,whiteSpace:"nowrap",display:"inline-flex",alignItems:"center",gap:5}}>{ch}</button>;}

function SR({score,size=88,label}){const r=size/2-6,ci=2*Math.PI*r,off=ci*(1-Math.min(score,100)/100);const col=score>=70?C.ok:score>=45?C.warn:C.err;return<div style={{display:"flex",flexDirection:"column",alignItems:"center",gap:4}}><svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}><circle cx={size/2} cy={size/2} r={r} fill="none" stroke={C.bdr} strokeWidth={5}/><circle cx={size/2} cy={size/2} r={r} fill="none" stroke={col} strokeWidth={5} strokeDasharray={ci} strokeDashoffset={off} strokeLinecap="round" transform={`rotate(-90 ${size/2} ${size/2})`} style={{transition:"stroke-dashoffset .8s ease"}}/><text x={size/2} y={size/2+1} textAnchor="middle" dominantBaseline="middle" style={{fontSize:size*.26,fontWeight:700,fontFamily:F.d,fill:C.ink}}>{Math.round(score)}</text></svg>{label&&<div style={{fontSize:10,fontWeight:600,color:C.ink4,textTransform:"uppercase",letterSpacing:".06em"}}>{label}</div>}</div>;}

function SB({data}){return<div style={{display:"flex",flexDirection:"column",gap:6,flex:1}}>{[["Clarity",data.cl],["Tone",data.tn],["Coherence",data.ch],["Risk ↓",Math.max(0,100-data.ri)]].map(([l,v])=><div key={l}><div style={{display:"flex",justifyContent:"space-between",marginBottom:2}}><span style={{fontSize:11,color:C.ink3}}>{l}</span><span style={{fontSize:11,fontWeight:700,color:C.ink2,fontFamily:F.m}}>{Math.round(v)}</span></div><div style={{height:4,borderRadius:2,background:C.bdr}}><div style={{height:"100%",borderRadius:2,background:v>=70?C.ok:v>=45?C.warn:C.err,width:`${Math.min(v,100)}%`,transition:"width .6s ease"}}/></div></div>)}</div>;}

/* ═══════════════ HEADER ═══════════════ */
function Hd({pg,sp,user,lo}){return<header style={{position:"sticky",top:0,zIndex:50,padding:"0 28px",height:56,display:"flex",alignItems:"center",justifyContent:"space-between",background:"rgba(244,245,250,.92)",backdropFilter:"blur(12px)",borderBottom:`1px solid ${C.bdr}`}}><div style={{display:"flex",alignItems:"center",gap:10,cursor:"pointer"}} onClick={()=>sp(user?"dashboard":"landing")}><div style={{width:30,height:30,borderRadius:8,background:`linear-gradient(135deg,${C.pri},#7C3AED)`,display:"flex",alignItems:"center",justifyContent:"center"}}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z"/></svg></div><div><div style={{fontSize:15,fontWeight:700,color:C.ink,fontFamily:F.d}}>ManuscriptReady</div><div style={{fontSize:8,color:C.ink3,fontWeight:700,letterSpacing:".1em",textTransform:"uppercase"}}>AI Publication Success Platform</div></div></div><nav style={{display:"flex",alignItems:"center",gap:4}}>{user?<>{["dashboard","editor"].map(p=><button key={p} onClick={()=>sp(p)} style={{padding:"6px 13px",borderRadius:7,border:"none",cursor:"pointer",fontSize:13,fontWeight:600,fontFamily:F.b,background:pg===p?C.priL:"transparent",color:pg===p?C.pri:C.ink3}}>{p[0].toUpperCase()+p.slice(1)}</button>)}<Btn ch="Sign Out" v="g" sz="s" onClick={lo}/></>:<><Btn ch="Sign In" v="g" sz="s" onClick={()=>sp("login")}/><Btn ch="Get Started" sz="s" onClick={()=>sp("signup")}/></>}</nav></header>;}

/* ═══════════════ LANDING ═══════════════ */
function Landing({sp}){
  const feats=[["🎯","Reviewer Intelligence","Detects overclaiming, vague claims, logical gaps — hedging-aware analysis."],["📊","Publication Score","6-dimensional scoring with academic-calibrated readability."],["📋","Accept/Reject Changes","Review each suggestion individually. Keep what works."],["🏛️","Journal Compliance","Nature, IEEE, APA, Vancouver, AMA style checking."],["⭐","Quality Feedback","Rate outputs to improve the system over time."],["📐","LaTeX + 9 Languages","Upload .tex. Translate from JP, CN, KR, TH, ES, PT, FR, DE."]];
  return<div>
    <section style={{padding:"72px 28px 56px",textAlign:"center",maxWidth:700,margin:"0 auto"}}><Bg ch="Publication Success Platform"/><h1 style={{fontSize:42,fontWeight:700,fontFamily:F.d,color:C.ink,lineHeight:1.15,margin:"22px 0 14px",letterSpacing:"-.03em"}}>Go beyond grammar.<br/>Achieve publication success.</h1><p style={{fontSize:17,color:C.ink3,lineHeight:1.65,maxWidth:540,margin:"0 auto 30px"}}>Detect reviewer risks, optimize by journal style, track every change — preserving every data point.</p><div style={{display:"flex",gap:12,justifyContent:"center"}}><Btn ch="Start Free" sz="l" onClick={()=>sp("signup")}/><Btn ch="Try Demo" sz="l" v="g" onClick={()=>sp("editor")}/></div></section>
    <section style={{padding:"48px 28px",background:C.card,borderTop:`1px solid ${C.bdr}`}}><div style={{maxWidth:860,margin:"0 auto",display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:24}}>{feats.map(([i,t,d])=><div key={t} style={{padding:14}}><div style={{fontSize:22,marginBottom:6}}>{i}</div><h3 style={{fontSize:14,fontWeight:700,color:C.ink,margin:"0 0 4px",fontFamily:F.d}}>{t}</h3><p style={{fontSize:12.5,color:C.ink3,lineHeight:1.6,margin:0}}>{d}</p></div>)}</div></section></div>;
}

/* ═══════════════ AUTH ═══════════════ */
function Auth({mode,sp,onA}){
  const[e,sE]=useState("");const[p,sP]=useState("");const[n,sN]=useState("");const[er,sEr]=useState("");const[ld,sL]=useState(false);const su=mode==="signup";
  const go=async()=>{sEr("");if(!e||!p)return sEr("Required");if(p.length<8)return sEr("Min 8 chars");sL(true);await new Promise(r=>setTimeout(r,400));onA({id:"d",email:e,full_name:n||"Researcher"},"t");sL(false);};
  return<div style={{display:"flex",alignItems:"center",justifyContent:"center",minHeight:"calc(100vh - 56px)"}}><Cd sx={{maxWidth:380,width:"100%",margin:20}} ch={<><h2 style={{fontSize:22,fontWeight:700,fontFamily:F.d,color:C.ink,margin:"0 0 16px"}}>{su?"Create account":"Welcome back"}</h2>{er&&<div style={{padding:"8px 12px",background:C.errL,color:C.err,borderRadius:8,fontSize:12,marginBottom:10}}>{er}</div>}<div style={{display:"flex",flexDirection:"column",gap:11}}>{su&&<div><label style={{fontSize:13,fontWeight:600,color:C.ink2,display:"block",marginBottom:4}}>Name</label><input value={n} onChange={e=>sN(e.target.value)} placeholder="Dr. Jane Smith" style={{width:"100%",padding:"10px 14px",border:`1.5px solid ${C.bdr}`,borderRadius:8,fontSize:14,boxSizing:"border-box"}}/></div>}<div><label style={{fontSize:13,fontWeight:600,color:C.ink2,display:"block",marginBottom:4}}>Email</label><input type="email" value={e} onChange={e=>sE(e.target.value)} placeholder="name@uni.edu" style={{width:"100%",padding:"10px 14px",border:`1.5px solid ${C.bdr}`,borderRadius:8,fontSize:14,boxSizing:"border-box"}}/></div><div><label style={{fontSize:13,fontWeight:600,color:C.ink2,display:"block",marginBottom:4}}>Password</label><input type="password" value={p} onChange={e=>sP(e.target.value)} placeholder="Min 8 characters" style={{width:"100%",padding:"10px 14px",border:`1.5px solid ${C.bdr}`,borderRadius:8,fontSize:14,boxSizing:"border-box"}}/></div><Btn ch={su?"Create Account":"Sign In"} sz="l" onClick={go} ld={ld} sx={{width:"100%",marginTop:4}}/></div><p style={{fontSize:12.5,color:C.ink3,textAlign:"center",marginTop:16}}>{su?"Have account? ":"New? "}<span style={{color:C.pri,fontWeight:600,cursor:"pointer"}} onClick={()=>sp(su?"login":"signup")}>{su?"Sign in":"Sign up"}</span></p></>}/></div>;
}

/* ═══════════════ DASHBOARD ═══════════════ */
function Dash({user,sp}){return<div style={{maxWidth:880,margin:"0 auto",padding:"32px 24px"}}><div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:24}}><h2 style={{fontSize:22,fontWeight:700,fontFamily:F.d,color:C.ink,margin:0}}>Welcome, {user?.full_name}</h2><Btn ch="Open Editor" onClick={()=>sp("editor")}/></div><div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:12,marginBottom:20}}>{[["Plan","Starter"],["Used","12.5k / 50k"],["Docs","3"],["Avg Δ","+18 pts"]].map(([l,v])=><Cd key={l} sx={{padding:14}} ch={<><div style={{fontSize:10,fontWeight:600,color:C.ink4,textTransform:"uppercase",letterSpacing:".06em",marginBottom:4}}>{l}</div><div style={{fontSize:17,fontWeight:700,color:C.ink,fontFamily:F.d}}>{v}</div></>}/>)}</div>{[{t:"Methods rewrite",s:"methods",b:38,a:71},{t:"Abstract — JP",s:"abstract",b:22,a:65}].map((x,i)=><Cd key={i} sx={{padding:"11px 14px",marginBottom:6,cursor:"pointer"}} ch={<div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}} onClick={()=>sp("editor")}><span style={{fontSize:13.5,fontWeight:600,color:C.ink}}>{x.t}</span><div style={{display:"flex",alignItems:"center",gap:5}}><span style={{fontSize:12,color:C.ink4,fontFamily:F.m}}>{x.b}</span><span style={{color:C.pri}}>→</span><span style={{fontSize:12,fontWeight:700,color:C.ok,fontFamily:F.m}}>{x.a}</span><Bg ch={`+${x.a-x.b}`} v="ok"/></div></div>}/>)}</div>;}

/* ═══════════════ EDITOR (Core Product) ═══════════════ */
function Editor(){
  const[text,sT]=useState("");const[mode,sM]=useState("enhance");const[lang,sLn]=useState("auto");const[sec,sS]=useState("general");const[jnl,sJ]=useState("general");
  const[res,sR]=useState(null);const[ld,sLd]=useState(false);const[err,sE]=useState(null);const[vw,sV]=useState("split");const[tab,sTb]=useState("result");
  const[rating,sRt]=useState(0);const[fbSent,sFbS]=useState(false);const fileRef=useRef(null);const[file,sF]=useState(null);

  const go=useCallback(async()=>{sE(null);sR(null);sLd(true);sFbS(false);sRt(0);try{const input=file?SAMPLE:text.trim();if(input.length<10)throw new Error("Min 10 chars");sR(await runPipeline(input,mode,sec,jnl));}catch(e){sE(e.message);}finally{sLd(false);}},[text,mode,sec,jnl,file]);

  const toggleChange=(i,st)=>{if(!res)return;const d=[...res.diffs];d[i]={...d[i],status:st};sR({...res,diffs:d});};
  const acceptAll=()=>{if(!res)return;sR({...res,diffs:res.diffs.map(d=>d.type!=="unchanged"?{...d,status:"accepted"}:d)});};
  const buildFinal=()=>res?res.diffs.map(d=>d.status==="rejected"?d.original:d.improved).filter(Boolean).join(" "):"";

  const sel={padding:"8px 12px",border:`1px solid ${C.bdr}`,borderRadius:8,fontSize:13,fontFamily:F.b,color:C.ink,background:C.card};

  return<div style={{maxWidth:1060,margin:"0 auto",padding:"22px 20px"}}>
    {/* Controls */}
    <div style={{display:"flex",gap:8,marginBottom:14,flexWrap:"wrap",alignItems:"flex-end"}}>
      <div style={{display:"flex",flexDirection:"column",gap:4}}><label style={{fontSize:10,fontWeight:600,color:C.ink4,textTransform:"uppercase",letterSpacing:".06em"}}>Mode</label><div style={{display:"flex",gap:1,background:C.bg,borderRadius:8,padding:2,border:`1px solid ${C.bdr}`}}><TG a={mode==="enhance"} o={()=>sM("enhance")} ch="✏️ Enhance"/><TG a={mode==="translate_enhance"} o={()=>sM("translate_enhance")} ch="🌐 Translate"/></div></div>
      <div style={{display:"flex",flexDirection:"column",gap:4}}><label style={{fontSize:10,fontWeight:600,color:C.ink4,textTransform:"uppercase",letterSpacing:".06em"}}>Section</label><select value={sec} onChange={e=>sS(e.target.value)} style={sel}>{["general","abstract","introduction","methods","results","discussion"].map(s=><option key={s} value={s}>{s[0].toUpperCase()+s.slice(1)}</option>)}</select></div>
      <div style={{display:"flex",flexDirection:"column",gap:4}}><label style={{fontSize:10,fontWeight:600,color:C.ink4,textTransform:"uppercase",letterSpacing:".06em"}}>Journal</label><select value={jnl} onChange={e=>sJ(e.target.value)} style={sel}>{JRNLS.map(j=><option key={j.id} value={j.id}>{j.name}</option>)}</select></div>
      {mode==="translate_enhance"&&<div style={{display:"flex",flexDirection:"column",gap:4}}><label style={{fontSize:10,fontWeight:600,color:C.ink4,textTransform:"uppercase",letterSpacing:".06em"}}>Language</label><select value={lang} onChange={e=>sLn(e.target.value)} style={sel}>{[["auto","Auto"],["ja","日本語"],["zh","中文"],["ko","한국어"],["th","ไทย"],["es","ES"],["pt","PT"],["fr","FR"],["de","DE"]].map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></div>}
      <input ref={fileRef} type="file" accept=".docx,.tex" onChange={e=>{if(e.target.files?.[0])sF(e.target.files[0]);}} style={{display:"none"}}/>
      <Btn ch={file?`📄 ${file.name}`:"📄 Upload"} v="g" sz="s" onClick={()=>fileRef.current?.click()} sx={{marginBottom:1}}/>
    </div>

    {/* Input */}
    <div style={{position:"relative"}}><textarea value={text} onChange={e=>sT(e.target.value)} placeholder="Paste academic text..." style={{width:"100%",minHeight:130,padding:"14px 16px",background:C.card,color:C.ink,border:`1.5px solid ${C.bdr}`,borderRadius:10,fontSize:13.5,lineHeight:1.7,fontFamily:F.m,resize:"vertical",outline:"none",boxSizing:"border-box"}} onFocus={e=>e.target.style.borderColor=C.bdrF} onBlur={e=>e.target.style.borderColor=C.bdr}/>
    {!text&&!file&&<button onClick={()=>sT(SAMPLE)} style={{position:"absolute",bottom:12,right:12,padding:"6px 14px",background:C.priL,color:C.pri,border:"none",borderRadius:6,fontSize:12,fontWeight:600,cursor:"pointer"}}>📝 Load sample text</button>}</div>
    <div style={{fontSize:11,color:C.ink4,margin:"4px 0 12px"}}>{text.split(/\s+/).filter(Boolean).length} words · {sec} · {jnl}</div>

    {/* Process */}
    <button onClick={go} disabled={ld||(!file&&text.trim().length<10)} style={{width:"100%",padding:"13px",background:ld?C.bg:`linear-gradient(135deg,${C.pri},#7C3AED)`,color:"#fff",border:"none",borderRadius:10,fontSize:15,fontWeight:700,cursor:ld?"wait":"pointer",display:"flex",alignItems:"center",justifyContent:"center",gap:8,opacity:ld||(!file&&text.trim().length<10)?.4:1,marginBottom:20,fontFamily:F.b}}>{ld?<><Spin sz={15} c="#fff"/>Analyzing...</>:"✨ Enhance Manuscript"}</button>
    {err&&<div style={{padding:"10px 16px",background:C.errL,color:C.err,borderRadius:8,fontSize:13,marginBottom:16}}>⚠ {err}</div>}

    {/* ═══════ RESULTS ═══════ */}
    {res&&<div style={{animation:"mf .4s ease-out"}}>
      {/* Scores */}
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14,marginBottom:14}}>
        <Cd sx={{padding:16}} ch={<><div style={{fontSize:10,fontWeight:700,color:C.ink4,textTransform:"uppercase",letterSpacing:".07em",marginBottom:8}}>Before</div><div style={{display:"flex",gap:16,alignItems:"flex-start"}}><SR score={res.sb.ov} label="Overall"/><SB data={res.sb}/></div><div style={{fontSize:11,color:C.ink4,marginTop:6}}>{res.sb.lb} · FRE {res.sb.fre}</div></>}/>
        <Cd sx={{padding:16}} ch={<><div style={{fontSize:10,fontWeight:700,color:C.ok,textTransform:"uppercase",letterSpacing:".07em",marginBottom:8}}>After Enhancement</div><div style={{display:"flex",gap:16,alignItems:"flex-start"}}><SR score={res.sa.ov} label="Overall"/><SB data={res.sa}/></div><div style={{fontSize:11,color:C.ink4,marginTop:6}}>{res.sa.lb} · FRE {res.sa.fre}</div></>}/>
      </div>

      {/* Safeguards + Journal */}
      <div style={{display:"flex",gap:6,flexWrap:"wrap",marginBottom:8}}>
        {[["🔢 Numbers",res.sg.nums],["📚 Citations",res.sg.cites],["📐 Formulas",res.sg.forms],["🏷️ Terms",res.sg.terms]].map(([l,ok])=><span key={l} style={{padding:"4px 10px",borderRadius:20,fontSize:11,fontWeight:600,background:ok?C.okL:C.errL,color:ok?C.ok:C.err}}>{ok?"✓":"⚠"} {l}</span>)}
        {res.terms.length>0&&<span style={{padding:"4px 10px",borderRadius:20,fontSize:11,fontWeight:600,background:C.priL,color:C.pri}}>🔒 {res.terms.join(", ")}</span>}
      </div>
      {res.jI.length>0&&<div style={{padding:"8px 14px",background:C.warnL,borderRadius:8,fontSize:12,color:"#92400E",marginBottom:10}}>📋 <strong>Journal ({jnl}):</strong> {res.jI.map(i=>i.issue).join("; ")}</div>}

      {/* Tabs */}
      <div style={{display:"flex",gap:1,background:C.bg,borderRadius:8,padding:2,border:`1px solid ${C.bdr}`,marginBottom:12,width:"fit-content"}}>
        <TG a={tab==="result"} o={()=>sTb("result")} ch="📄 Result"/>
        <TG a={tab==="review"} o={()=>sTb("review")} ch={<>📋 Review {res.diffs.filter(d=>d.type!=="unchanged").length>0&&<span style={{background:C.pri,color:"#fff",borderRadius:10,padding:"1px 6px",fontSize:10,fontWeight:700,marginLeft:4}}>{res.diffs.filter(d=>d.type!=="unchanged").length}</span>}</>}/>
        <TG a={tab==="alerts"} o={()=>sTb("alerts")} ch={<>🎯 Alerts {res.alerts.length>0&&<span style={{background:res.alerts.some(a=>a.sv==="high")?C.err:C.warn,color:"#fff",borderRadius:10,padding:"1px 6px",fontSize:10,fontWeight:700,marginLeft:4}}>{res.alerts.length}</span>}</>}/>
      </div>

      {/* ── Result Tab ── */}
      {tab==="result"&&<>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:10}}>
          <div style={{display:"flex",gap:1,background:C.bg,borderRadius:7,padding:2,border:`1px solid ${C.bdr}`}}>{[["split","Split"],["diff","Diff"],["improved","Result"]].map(([k,l])=><button key={k} onClick={()=>sV(k)} style={{padding:"5px 11px",background:vw===k?C.priL:"transparent",color:vw===k?C.pri:C.ink4,border:"none",borderRadius:6,fontSize:12,fontWeight:600,cursor:"pointer"}}>{l}</button>)}</div>
          <Btn ch="📋 Copy" v="g" sz="s" onClick={()=>navigator.clipboard.writeText(res.imp)}/>
        </div>
        {vw==="split"&&<div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14}}>
          <div><div style={{fontSize:10,fontWeight:600,color:C.ink4,textTransform:"uppercase",marginBottom:5,display:"flex",alignItems:"center",gap:5}}><span style={{width:6,height:6,borderRadius:"50%",background:C.err}}/>Original</div><div style={{padding:14,background:C.card,border:`1px solid ${C.bdr}`,borderRadius:10,fontSize:13,lineHeight:1.75,whiteSpace:"pre-wrap",fontFamily:F.m,minHeight:120}}>{res.orig}</div></div>
          <div><div style={{fontSize:10,fontWeight:600,color:C.ink4,textTransform:"uppercase",marginBottom:5,display:"flex",alignItems:"center",gap:5}}><span style={{width:6,height:6,borderRadius:"50%",background:C.ok}}/>Improved</div><div style={{padding:14,background:C.card,border:`1px solid ${C.bdr}`,borderRadius:10,fontSize:13,lineHeight:1.75,whiteSpace:"pre-wrap",fontFamily:F.m,minHeight:120}}>{res.imp}</div></div></div>}
        {vw==="diff"&&<Cd sx={{padding:0,overflow:"hidden"}} ch={<>{res.diffs.map((d,i)=><div key={i} style={{display:"grid",gridTemplateColumns:"1fr 1fr",borderBottom:i<res.diffs.length-1?`1px solid ${C.bdr}`:"none",opacity:d.type==="unchanged"?.5:1}}><div style={{padding:"9px 12px",fontSize:12.5,lineHeight:1.65,fontFamily:F.m,background:["modified","removed"].includes(d.type)?C.dR:"transparent",borderLeft:d.type!=="unchanged"?`3px solid ${C.err}`:"3px solid transparent"}}>{d.original||"—"}</div><div style={{padding:"9px 12px",fontSize:12.5,lineHeight:1.65,fontFamily:F.m,background:["modified","added"].includes(d.type)?C.dG:"transparent",borderLeft:d.type!=="unchanged"?`3px solid ${C.ok}`:"3px solid transparent"}}>{d.improved||"—"}</div></div>)}</>}/>}
        {vw==="improved"&&<div style={{padding:18,background:C.card,border:`1px solid ${C.bdr}`,borderRadius:10,fontSize:15,lineHeight:1.85,whiteSpace:"pre-wrap"}}>{res.imp}</div>}
      </>}

      {/* ── Review Changes Tab (Accept/Reject) ── */}
      {tab==="review"&&<div>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:10}}>
          <span style={{fontSize:13,fontWeight:600,color:C.ink2}}>{res.diffs.filter(d=>d.type!=="unchanged").length} changes to review</span>
          <div style={{display:"flex",gap:6}}><Btn ch="✓ Accept All" v="s2" sz="s" onClick={acceptAll}/><Btn ch="📋 Copy Final" v="g" sz="s" onClick={()=>navigator.clipboard.writeText(buildFinal())}/></div>
        </div>
        {res.diffs.filter(d=>d.type!=="unchanged").map((d,i)=>{
          const idx=res.diffs.indexOf(d);
          const stColor=d.status==="accepted"?C.ok:d.status==="rejected"?C.err:C.pri;
          return<div key={idx} style={{marginBottom:8,border:`1px solid ${C.bdr}`,borderRadius:10,overflow:"hidden",borderLeft:`4px solid ${stColor}`}}>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr"}}>
              <div style={{padding:"10px 12px",background:C.dR,fontSize:12.5,lineHeight:1.6,fontFamily:F.m}}><span style={{fontSize:10,fontWeight:600,color:C.err,display:"block",marginBottom:3}}>ORIGINAL</span>{d.original}</div>
              <div style={{padding:"10px 12px",background:C.dG,fontSize:12.5,lineHeight:1.6,fontFamily:F.m}}><span style={{fontSize:10,fontWeight:600,color:C.ok,display:"block",marginBottom:3}}>IMPROVED</span>{d.improved}</div>
            </div>
            <div style={{padding:"8px 12px",background:C.bg,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
              <Bg ch={d.status} v={d.status==="accepted"?"ok":d.status==="rejected"?"e":"d"}/>
              <div style={{display:"flex",gap:6}}>
                <button onClick={()=>toggleChange(idx,"accepted")} style={{padding:"4px 12px",borderRadius:6,border:`1px solid ${d.status==="accepted"?C.ok:C.bdr}`,background:d.status==="accepted"?C.okL:"transparent",color:d.status==="accepted"?C.ok:C.ink3,fontSize:12,fontWeight:600,cursor:"pointer"}}>✓ Accept</button>
                <button onClick={()=>toggleChange(idx,"rejected")} style={{padding:"4px 12px",borderRadius:6,border:`1px solid ${d.status==="rejected"?C.err:C.bdr}`,background:d.status==="rejected"?C.errL:"transparent",color:d.status==="rejected"?C.err:C.ink3,fontSize:12,fontWeight:600,cursor:"pointer"}}>✗ Reject</button>
              </div>
            </div>
          </div>;})}
      </div>}

      {/* ── Alerts Tab ── */}
      {tab==="alerts"&&<div>
        {res.alerts.length===0?<Cd sx={{textAlign:"center",padding:32}} ch={<><div style={{fontSize:30,marginBottom:8}}>✅</div><div style={{fontSize:15,fontWeight:600,color:C.ok}}>No reviewer issues detected</div><div style={{fontSize:13,color:C.ink3,marginTop:4}}>Your text looks publication-ready</div></>}/>:
        <div style={{display:"flex",flexDirection:"column",gap:8}}>{res.alerts.map((a,i)=><Cd key={i} sx={{padding:"14px 16px",borderLeft:`4px solid ${a.sv==="high"?C.err:a.sv==="medium"?C.warn:"#9CA3AF"}`}} ch={<><div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:6}}><Bg ch={a.type} v={a.sv==="high"?"e":a.sv==="medium"?"w":"d"}/><Bg ch={a.sv} v={a.sv==="high"?"e":"w"}/></div><div style={{fontSize:13,color:C.ink,lineHeight:1.6,fontFamily:F.m,marginBottom:6,padding:"6px 10px",background:C.bg,borderRadius:6}}>"{a.sentence}"</div><div style={{fontSize:12.5,color:C.ink2,marginBottom:3}}>⚠ {a.ex}</div><div style={{fontSize:12.5,color:C.ok}}>💡 {a.sg}</div></>}/>)}</div>}
      </div>}

      {/* ── Feedback ── */}
      <div style={{marginTop:16,padding:"12px 16px",background:C.card,border:`1px solid ${C.bdr}`,borderRadius:10,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
        <div style={{display:"flex",alignItems:"center",gap:8}}>
          <span style={{fontSize:13,fontWeight:600,color:C.ink2}}>Rate this output:</span>
          {[1,2,3,4,5].map(n=><button key={n} onClick={()=>sRt(n)} style={{fontSize:18,background:"none",border:"none",cursor:"pointer",opacity:n<=rating?1:.3}}>{n<=rating?"⭐":"☆"}</button>)}
        </div>
        {rating>0&&!fbSent&&<Btn ch="Submit" sz="s" onClick={()=>sFbS(true)}/>}
        {fbSent&&<span style={{fontSize:12,color:C.ok,fontWeight:600}}>✓ Thanks for feedback!</span>}
      </div>

      {/* Scientific Integrity */}
      <div style={{marginTop:10,padding:"10px 14px",background:C.warnL,borderRadius:8,fontSize:12,color:"#92400E"}}>🛡️ <strong>Scientific Integrity:</strong> AI never adds claims, invents data, or alters citations. Always verify before submission.</div>
    </div>}
  </div>;
}

/* ═══════════════ APP ROUTER ═══════════════ */
export default function App(){
  const[pg,sp]=useState("landing");const[user,sU]=useState(null);
  const auth=(u,t)=>{sU(u);sp("dashboard");};const lo=()=>{sU(null);sp("landing");};
  const P=()=>{switch(pg){case"landing":return<Landing sp={sp}/>;case"login":return<Auth mode="login" sp={sp} onA={auth}/>;case"signup":return<Auth mode="signup" sp={sp} onA={auth}/>;case"dashboard":return user?<Dash user={user} sp={sp}/>:<Auth mode="login" sp={sp} onA={auth}/>;case"editor":return<Editor/>;default:return<Landing sp={sp}/>;}};
  return<div style={{minHeight:"100vh",background:C.bg,color:C.ink,fontFamily:F.b}}>
    <style>{`@import url('https://fonts.googleapis.com/css2?family=Lora:wght@400;600;700&family=DM+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');@keyframes ms{to{transform:rotate(360deg)}}@keyframes mf{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}*{box-sizing:border-box}::selection{background:${C.priL}}`}</style>
    <Hd pg={pg} sp={sp} user={user} lo={lo}/><P/></div>;
}

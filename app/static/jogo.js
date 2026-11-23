// Kaizen OS — camada de jogo: XP, níveis (O Livro dos Cinco Anéis), conquistas, sons e confete.
// Tudo é calculado a partir do histórico (check-ins + relógio), então o que um agente de IA grava pela CLI também conta.
// Regra de ouro: nada se perde. Falhar um dia não tira XP nem conquista. Recaída é dado, não sentença.
(function(){
  "use strict";
  let INICIO = "2000-01-01"; // definido em calcular(): início da primeira fase
  let HAB = [];               // hábitos vindos do servidor
  const ativoEm = (h,d) => h.inicio <= d && (!h.fim || d <= h.fim) && h.status !== "arquivado";

  // ---------------- níveis ----------------
  const NIVEIS = [
    [0,    "Rōnin",            "Todo caminho começa sem mestre."],
    [150,  "Aprendiz do dojo", "Você apareceu. Isso é metade."],
    [400,  "Ashigaru",         "Disciplina de quem marcha todo dia."],
    [800,  "Samurai",          "A âncora já é parte de quem você é."],
    [1400, "Hatamoto",         "Guardião do próprio estandarte."],
    [2200, "Kensei",           "O hábito virou arte."],
    [3300, "Mestre dos Cinco Anéis", "Terra, água, fogo, vento e vazio."],
  ];
  function nivel(xp){
    let i = 0; while (i+1 < NIVEIS.length && xp >= NIVEIS[i+1][0]) i++;
    const [base, nome, frase] = NIVEIS[i];
    const prox = NIVEIS[i+1] ? NIVEIS[i+1][0] : null;
    return {n: i+1, nome, frase, base, prox, pct: prox ? (xp-base)/(prox-base) : 1};
  }

  // ---------------- datas ----------------
  const pad = n => String(n).padStart(2,"0");
  const ymd = d => d.getFullYear()+"-"+pad(d.getMonth()+1)+"-"+pad(d.getDate());
  const parse = s => {const [y,m,d]=s.split("-").map(Number); return new Date(y,m-1,d)};
  const add = (s,n) => {const d=parse(s); d.setDate(d.getDate()+n); return ymd(d)};
  const semana = s => {const d=parse(s); const k=(d.getDay()+6)%7; d.setDate(d.getDate()-k); return ymd(d)};

  // ---------------- dia a dia ----------------
  function dias(data, saude, hoje){
    const out = []; let k = INICIO;
    while (k <= hoje){
      const r = data[k] || {}, s = (saude[k] || {});
      const lista = HAB.filter(h => ativoEm(h, k));
      const sono = s.sono ? s.sono.h : (typeof r.sono_h === "number" ? r.sono_h : null);
      const dormiu = s.sono ? s.sono.inicio : r.dormiu || null;
      const d = {k, r, s, sono, dormiu,
        meia: dormiu ? Number(dormiu.slice(0,2)) >= 17 : null,
        lista,
        feitas: lista.filter(h => r[h.id] === true).length,
        marcadas: lista.filter(h => r[h.id] != null).length,
        treinoBand: (s.treinos || []).length > 0,
        passos: s.passos || 0};
      d.perfeito = lista.length > 0 && d.feitas === lista.length;
      d.xp = xpDia(d);
      out.push(d); k = add(k,1);
    }
    return out;
  }
  function xpDia(d){
    const r = d.r; let xp = 0; const itens = [];
    const soma = (v, txt) => { xp += v; itens.push([txt, v]); };
    d.lista.forEach(h => { if (r[h.id] === true) soma(h.xp || 10, h.nome); });
    if (d.meia === true)     soma(15, "Dormiu antes da meia-noite");
    if (d.sono != null && d.sono >= 7) soma(10, "7h+ de sono");
    if (d.passos >= 8000)    soma(10, "8 mil passos");
    if (typeof r.energia === "number" && typeof r.ansiedade === "number") soma(5, "Registrou energia e ansiedade");
    if (r.nota) soma(5, "Escreveu a nota do dia");
    if (d.perfeito)          soma(30, "Dia perfeito");
    d.itens = itens;
    return xp;
  }

  // sequência terminando em k (ou ontem, se hoje ainda está em aberto)
  function seq(lista, teste){
    let best = 0, cur = 0, curAte = 0;
    lista.forEach((d,i) => { if (teste(d)) { cur++; best = Math.max(best,cur); } else cur = 0; if (i === lista.length-1) curAte = cur; });
    // se hoje ainda não cumpriu, vale a sequência até ontem
    if (lista.length && !teste(lista[lista.length-1])) {
      let c = 0; for (let i = lista.length-2; i >= 0 && teste(lista[i]); i--) c++; curAte = c;
    }
    return {atual: curAte, melhor: best};
  }

  // ---------------- conquistas ----------------
  // cada uma: quando = data em que foi conquistada pela primeira vez (ou null)
  function primeiraVez(lista, teste){ const d = lista.find(teste); return d ? d.k : null; }
  function primeiraSeq(lista, teste, n){ let c = 0; for (const d of lista){ c = teste(d) ? c+1 : 0; if (c >= n) return d.k; } return null; }
  function primeiraContagem(lista, teste, n){ let c = 0; for (const d of lista){ if (teste(d) && ++c >= n) return d.k; } return null; }
  function semanaCom(lista, teste, n){
    const por = {}; for (const d of lista){ if (teste(d)) { const w = semana(d.k); por[w] = (por[w]||0)+1; if (por[w] >= n) return d.k; } } return null;
  }
  function janela(lista, teste, n, dias){
    for (let i = 0; i < lista.length; i++){ let c = 0; for (let j = Math.max(0,i-dias+1); j <= i; j++) if (teste(lista[j])) c++; if (c >= n) return lista[i].k; } return null;
  }
  const C = (id, emoji, nome, desc, fn, cat, precisa) => ({id, emoji, nome, desc, fn, cat, precisa});
  const CONQ = [
    C("primeiro",  "🌱", "Primeiro passo",      "Marcar a primeira âncora como cumprida.", l => primeiraVez(l, d => d.feitas >= 1), "início"),
    C("perfeito",  "💎", "Dia perfeito",        "Cumprir as 5 âncoras no mesmo dia.", l => primeiraVez(l, d => d.perfeito), "início"),
    C("quarto1",   "🌙", "Quarto escuro",       "Primeira noite com o celular fora do quarto.", l => primeiraVez(l, d => d.r.celular === true), "celular", "celular"),
    C("galo",      "🐓", "Canto do galo",       "Acordar às 7h por 3 dias seguidos.", l => primeiraSeq(l, d => d.r.acordou7 === true, 3), "manhã", "acordou7"),
    C("sol",       "🌅", "Sol nascente",        "7 manhãs sem celular.", l => primeiraContagem(l, d => d.r.manha === true, 7), "manhã", "manha"),
    C("quando",    "🗡️", "Quando, não se",      "Primeira ida à academia na fase 1.", l => primeiraVez(l, d => d.r.academia === true), "academia", "academia"),
    C("ferro",     "⚙️", "Semana de ferro",     "3 treinos na mesma semana.", l => semanaCom(l, d => d.r.academia === true, 3), "academia", "academia"),
    C("dez",       "🏋️", "Dez treinos",         "10 idas à academia.", l => primeiraContagem(l, d => d.r.academia === true, 10), "academia", "academia"),
    C("foco1",     "🎯", "Foco profundo",       "Primeiro bloco de 90 min.", l => primeiraVez(l, d => d.r.foco === true), "foco", "foco"),
    C("monge",     "🧘", "Monge",               "5 blocos de foco em 7 dias.", l => janela(l, d => d.r.foco === true, 5, 7), "foco", "foco"),
    C("meia1",     "🕛", "Antes da meia-noite", "Dormir antes da meia-noite.", l => primeiraVez(l, d => d.meia === true), "sono"),
    C("ritmo",     "🎐", "Ritmo",               "3 noites seguidas antes da meia-noite.", l => primeiraSeq(l, d => d.meia === true, 3), "sono"),
    C("relogio",   "⏳", "Relógio interno",     "7 noites seguidas antes da meia-noite.", l => primeiraSeq(l, d => d.meia === true, 7), "sono"),
    C("reparador", "🛌", "Sono reparador",      "3 noites seguidas com 7h ou mais.", l => primeiraSeq(l, d => d.sono != null && d.sono >= 7, 3), "sono"),
    C("andarilho", "👣", "Andarilho",           "Um dia com 10 mil passos.", l => primeiraVez(l, d => d.passos >= 10000), "corpo"),
    C("diario",    "📓", "Diário de bordo",     "Registrar energia e ansiedade 7 dias.", l => primeiraContagem(l, d => typeof d.r.energia === "number" && typeof d.r.ansiedade === "number", 7), "mente"),
    C("recomeco",  "🔁", "Recomeço",            "Voltar a cumprir uma âncora no dia seguinte a uma falha nela.", l => {
        for (let i = 1; i < l.length; i++) for (const h of HAB) if (l[i-1].r[h.id] === false && l[i].r[h.id] === true) return l[i].k; return null; }, "mente"),
    C("kaizen7",   "🌸", "Kaizen",              "7 dias seguidos fazendo pelo menos uma âncora.", l => primeiraSeq(l, d => d.feitas >= 1, 7), "início"),
    C("kaizen30",  "🌳", "Kaizen profundo",     "30 dias seguidos fazendo pelo menos uma âncora.", l => primeiraSeq(l, d => d.feitas >= 1, 30), "início"),
    C("fase1",     "🏁", "Primeira fase completa", "Registrar as âncoras em todos os dias da primeira fase.", l => { const n = FASE1 || 14; const f = l.filter(d => d.k <= add(INICIO,n-1) && d.marcadas > 0); return f.length >= n ? f[n-1].k : null; }, "início"),
    C("tres_perf", "🔥", "Três vezes perfeito", "3 dias perfeitos (5/5).", l => primeiraContagem(l, d => d.perfeito, 3), "início"),
  ];

  let FASE1 = 14;
  // conquistas geradas para cada hábito: 7 e 21 dias seguidos, e a graduação
  function porHabito(h){
    return [
      C("h7_"+h.id,  "🌟", h.nome+" · 7 seguidos",  "7 dias seguidos de "+h.nome.toLowerCase()+".", l => primeiraSeq(l, d => d.r[h.id] === true, 7), "hábito"),
      C("h21_"+h.id, "🏆", h.nome+" · 21 seguidos", "21 dias seguidos: o hábito está se formando.", l => primeiraSeq(l, d => d.r[h.id] === true, 21), "hábito"),
      C("grad_"+h.id,"🎓", "Graduado: "+h.nome,     "Virou automático e saiu do check-in diário.", () => h.status === "consolidado" ? h.fim : null, "hábito"),
    ];
  }
  function calcular(data, saude, hoje, est){
    est = est || {};
    HAB = (est.habitos || []).filter(h => h.status !== "arquivado");
    const fases = est.fases || [];
    INICIO = (fases[0] && fases[0].inicio) || HAB.map(h => h.inicio).sort()[0] || hoje;
    FASE1 = fases[0] && fases[0].fim ? Math.round((parse(fases[0].fim) - parse(fases[0].inicio)) / 864e5) + 1 : 14;
    const l = dias(data, saude, hoje);
    const xp = l.reduce((a,d) => a + d.xp, 0);
    const ids = new Set(HAB.map(h => h.id));
    const lista = CONQ.filter(c => !c.precisa || ids.has(c.precisa)).concat(...HAB.map(porHabito));
    const conq = lista.map(c => ({...c, quando: c.fn(l)}));
    const bonus = conq.filter(c => c.quando).length * 20; // cada conquista vale 20 XP
    const total = xp + bonus;
    return {
      dias: l, xp: total, xpDias: xp, bonus, nivel: nivel(total), conquistas: conq,
      seq: {
        celular: seq(l, d => d.r.celular === true),
        perfeitoDias: l.filter(d => d.perfeito).length,
        meia: seq(l, d => d.meia === true),
        perfeito: seq(l, d => d.perfeito),
        registro: seq(l, d => d.marcadas > 0),
        kaizen: seq(l, d => d.feitas >= 1),
      },
      hoje: l.find(d => d.k === hoje) || null,
    };
  }

  // ---------------- som (Web Audio, sem arquivos) ----------------
  let ctx = null;
  const somLigado = () => localStorage.getItem("som") !== "0";
  function ac(){ if (!ctx) { const A = window.AudioContext || window.webkitAudioContext; if (!A) return null; ctx = new A(); } if (ctx.state === "suspended") ctx.resume(); return ctx; }
  function nota(freq, t0, dur, {tipo="sine", vol=.18, ataque=.008} = {}){
    const c = ac(); if (!c) return;
    const o = c.createOscillator(), g = c.createGain();
    o.type = tipo; o.frequency.setValueAtTime(freq, c.currentTime + t0);
    g.gain.setValueAtTime(0, c.currentTime + t0);
    g.gain.linearRampToValueAtTime(vol, c.currentTime + t0 + ataque);
    g.gain.exponentialRampToValueAtTime(.0001, c.currentTime + t0 + dur);
    o.connect(g).connect(c.destination); o.start(c.currentTime + t0); o.stop(c.currentTime + t0 + dur + .05);
  }
  // escala pentatônica japonesa (in/miyako-bushi) para dar o tom
  const SONS = {
    sim:   () => { nota(784, 0, .16, {tipo:"triangle", vol:.14}); nota(1175, .05, .22, {vol:.08}); },
    nao:   () => { nota(330, 0, .18, {tipo:"sine", vol:.08}); },
    xp:    () => { nota(988, 0, .12, {tipo:"triangle", vol:.1}); },
    perfeito: () => { [659, 784, 880, 1175, 1319].forEach((f,i) => nota(f, i*.09, .5, {tipo:"triangle", vol:.12})); },
    conquista: () => { [523, 659, 784, 1047].forEach((f,i) => nota(f, i*.11, .35, {tipo:"square", vol:.05})); nota(1568, .5, .9, {tipo:"sine", vol:.12}); nota(2093, .52, .9, {tipo:"sine", vol:.05}); },
    nivel: () => { // gongo
      nota(110, 0, 2.6, {tipo:"sine", vol:.25, ataque:.003}); nota(165, 0, 2.2, {tipo:"sine", vol:.12, ataque:.003});
      nota(277, 0, 1.6, {tipo:"sine", vol:.07, ataque:.003}); nota(440, .02, 1.2, {tipo:"triangle", vol:.04});
      [587, 698, 880, 1175].forEach((f,i) => nota(f, .4 + i*.12, .6, {tipo:"triangle", vol:.08}));
    },
  };
  function tocar(nome){ if (!somLigado()) return; try { SONS[nome] && SONS[nome](); } catch(e){} }
  function vibrar(p){ if (navigator.vibrate && localStorage.getItem("vibrar") !== "0") try { navigator.vibrate(p); } catch(e){} }

  // ---------------- confete ----------------
  function confete(intenso){
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const cv = document.createElement("canvas"); const dpr = Math.min(2, devicePixelRatio || 1);
    cv.style.cssText = "position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:50";
    cv.width = innerWidth*dpr; cv.height = innerHeight*dpr; document.body.appendChild(cv);
    const g = cv.getContext("2d"); g.scale(dpr,dpr);
    const cores = ["#2b6a4b","#6cc497","#f2b647","#ec8b63","#8b6fd6","#ffffff"];
    const n = intenso ? 160 : 70;
    const ps = Array.from({length:n}, (_,i) => i < n*.4
      ? {x: innerWidth/2, y: innerHeight*.42, vx:(Math.random()-.5)*16, vy:-Math.random()*13-5, r:Math.random()*6+4, c:cores[Math.random()*cores.length|0], a:Math.random()*6, va:(Math.random()-.5)*.3, petala: Math.random() < .3}
      : {x: Math.random()*innerWidth, y: -20 - Math.random()*innerHeight*.5, vx:(Math.random()-.5)*2, vy:Math.random()*2+1, r:Math.random()*6+4, c:cores[Math.random()*cores.length|0], a:Math.random()*6, va:(Math.random()-.5)*.2, petala: Math.random() < .5});
    let t = 0;
    (function frame(){
      g.clearRect(0,0,innerWidth,innerHeight); t++;
      ps.forEach(p => { p.vy = Math.min(p.vy + (p.petala ? .12 : .25), p.petala ? 3.2 : 9); p.vx = p.vx*.99 + (p.petala ? Math.sin((t+p.a*40)/18)*.15 : 0); p.x += p.vx; p.y += p.vy; p.a += p.va;
        g.save(); g.translate(p.x,p.y); g.rotate(p.a); g.globalAlpha = Math.max(0, Math.min(1, (200 - t)/50)); g.fillStyle = p.petala ? "#f4b6c8" : p.c;
        if (p.petala) { g.beginPath(); g.ellipse(0,0,p.r,p.r*.55,0,0,Math.PI*2); g.fill(); } else g.fillRect(-p.r/2,-p.r/4,p.r,p.r/2);
        g.restore(); });
      if (t < 200) requestAnimationFrame(frame); else cv.remove();
    })();
  }

  const seqDe = (l, id) => seq(l, d => d.r[id] === true);
  window.Jogo = {get INICIO(){ return INICIO; }, seqDe, NIVEIS, nivel, calcular, tocar, vibrar, confete, somLigado, xpDia};
})();

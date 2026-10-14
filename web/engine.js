/* Hay Day planner engine: JS port of scripts/planner.py (Mode 1 LP) and scripts/quest.py (Mode 2).
   Pure functions, no DOM. HD.init(data) once, then HD.solve / HD.quest. */
const HD = (() => {
  let ITEMS = [], BY = {}, TREE_FRUIT = 3;
  const EPS = 1e-9;
  let LANG = "th", DICT = {};
  const L = s => (LANG === "en" && DICT[s]) || s;   // UI text: Thai phrase is the key (not "t": t is time in simulate)
  const setLang = (l, dict) => { LANG = l; DICT = dict || DICT; };

  function init(data) {
    ITEMS = data.items; TREE_FRUIT = data.treeFruit || 3;
    BY = Object.fromEntries(ITEMS.map(i => [i.n, i]));
  }

  // ---------- farm helpers ----------
  const lvOf = i => (i.lv == null ? 1e6 : i.lv);
  const isMastered = (farm, i) => i.k === "machine" && (farm.mastered || []).includes(i.w);
  const timeOf = (farm, i) => (isMastered(farm, i) && i.tm != null ? i.tm : i.t);
  const machineCount = (farm, m) => (farm.machine_count || {})[m] ?? farm.machine_count_default;
  const machineSlots = (farm, m) => (farm.machine_slots || {})[m] ?? farm.machine_slots_default;
  const animalsOf = (farm, p) => (p === "Honeycomb" ? farm.beehives : (farm.animals || {})[p] ?? farm.animals_default);
  const treesOf = (farm, p) => (farm.trees || {})[p] ?? farm.trees_default;

  function unlocked(level, allowExternal, exclude) {
    const memo = {}, ex = new Set(exclude || []);
    const ok = p => {
      if (p in memo) return memo[p];
      memo[p] = false;
      const i = BY[p];
      const good = !!i && lvOf(i) <= level && !ex.has(p) && (allowExternal || i.k !== "external")
        && i.in.every(([q]) => ok(q));
      return (memo[p] = good);
    };
    return ITEMS.map(i => i.n).filter(ok).sort();
  }

  // ---------- simplex: maximise c.x s.t. A x <= b, x >= 0; returns x, objective, duals ----------
  function simplex(c, A, b) {
    const m = A.length, n = c.length;
    const flip = b.map(v => v < 0);
    const na = flip.filter(Boolean).length;
    const W = n + m + na + 1;                        // columns: x | slack/surplus | artificial | rhs
    const T = Array.from({ length: m }, () => new Float64Array(W));
    const basis = new Int32Array(m);
    let a = 0;
    for (let i = 0; i < m; i++) {
      const s = flip[i] ? -1 : 1, row = T[i];
      for (let j = 0; j < n; j++) row[j] = s * A[i][j];
      row[n + i] = s;                                // slack (+1) or surplus (-1 after the flip)
      row[W - 1] = s * b[i];
      if (flip[i]) { row[n + m + a] = 1; basis[i] = n + m + a; a++; } else basis[i] = n + i;
    }
    const isArt = j => j >= n + m && j < W - 1;

    function run(cost, allowArt) {
      const z = new Float64Array(W);
      for (let j = 0; j < W; j++) z[j] = -(j < W - 1 ? cost[j] : 0);
      for (let i = 0; i < m; i++) { const cb = cost[basis[i]]; if (cb) { const r = T[i]; for (let j = 0; j < W; j++) z[j] += cb * r[j]; } }
      let degen = 0;
      for (let it = 0; it < 50000; it++) {
        let e = -1, best = -1e-9;
        for (let j = 0; j < W - 1; j++) {
          if (!allowArt && isArt(j)) continue;
          if (z[j] < best) { if (degen > 50) { e = j; break; } best = z[j]; e = j; }
        }
        if (e < 0) return z;
        let r = -1, ratio = Infinity;
        for (let i = 0; i < m; i++) {
          const v = T[i][e];
          if (v > 1e-9) { const q = T[i][W - 1] / v; if (q < ratio - 1e-12 || (degen > 50 && Math.abs(q - ratio) <= 1e-12 && basis[i] < basis[r])) { ratio = q; r = i; } }
        }
        if (r < 0) throw new Error("unbounded");
        degen = ratio < 1e-12 ? degen + 1 : 0;
        pivot(r, e, z);
      }
      throw new Error("iteration limit");
    }
    function pivot(r, e, z) {
      const pr = T[r], pv = pr[e];
      for (let j = 0; j < W; j++) pr[j] /= pv;
      for (let i = 0; i < m; i++) {
        if (i === r) continue;
        const f = T[i][e]; if (Math.abs(f) < 1e-15) continue;
        const row = T[i]; for (let j = 0; j < W; j++) row[j] -= f * pr[j];
      }
      const f = z[e]; if (f) for (let j = 0; j < W; j++) z[j] -= f * pr[j];
      basis[r] = e;
    }

    if (na) {
      const c1 = new Float64Array(W - 1); for (let j = n + m; j < W - 1; j++) c1[j] = -1;
      run(c1, true);
      let infeas = 0; for (let i = 0; i < m; i++) if (isArt(basis[i])) infeas += T[i][W - 1];
      if (infeas > 1e-6) throw new Error("infeasible");
      for (let i = 0; i < m; i++) if (isArt(basis[i])) {      // drive zero-level artificials out
        for (let j = 0; j < n + m; j++) if (Math.abs(T[i][j]) > 1e-9) { pivot(i, j, new Float64Array(W)); break; }
      }
    }
    const c2 = new Float64Array(W - 1); for (let j = 0; j < n; j++) c2[j] = c[j];
    const z = run(c2, false);
    const x = new Float64Array(n);
    for (let i = 0; i < m; i++) if (basis[i] < n) x[basis[i]] = T[i][W - 1];
    const duals = Array.from({ length: m }, (_, i) => z[n + i]);
    let obj = 0; for (let j = 0; j < n; j++) obj += c[j] * x[j];
    return { x, obj, duals };
  }

  // ---------- Mode 1 ----------
  /* reserve (optional): capacity a quest already holds this visit, subtracted from the farm:
     {fields, machineMin: {m: busy min/hr}, slots: {m: n}, animals: {p: n}, trees: {p: n}} */
  function solve(farm, checkin, demand, reserve) {
    const I = checkin ?? farm.checkin_minutes;
    const R = reserve || {}, pos = v => Math.max(0, v);
    const cyc = T => (I > 0 ? Math.ceil(T / I - 1e-9) * I : T);
    const items = unlocked(farm.level, farm.allow_external, farm.exclude);
    const n = items.length, ix = Object.fromEntries(items.map((p, k) => [p, k])), nv = 2 * n;
    const rows = [], rhs = [], names = [];
    const row = () => new Float64Array(nv);
    const it = p => BY[p];

    for (const p of items) {
      const r = row(); r[ix[p]] = -1; r[n + ix[p]] = 1;
      rows.push(r); rhs.push(-((demand || {})[p] || 0)); names.push(["flow", p]);
    }
    for (const q of items) for (const [p, qty] of it(q).in) if (p in ix) rows[ix[p]][ix[q]] += qty / it(q).y;

    const machines = [...new Set(items.filter(p => it(p).k === "machine").map(p => it(p).w))].sort();
    for (const m of machines) {
      const cnt = machineCount(farm, m), slots = machineSlots(farm, m);
      const rt = row(), rs = row();
      for (const p of items) if (it(p).k === "machine" && it(p).w === m) { rt[ix[p]] = timeOf(farm, it(p)) / it(p).y; rs[ix[p]] = 1 / it(p).y; }
      rows.push(rt, rs); rhs.push(pos(60 * cnt - ((R.machineMin || {})[m] || 0)), pos(slots * cnt - ((R.slots || {})[m] || 0)) * 60 / I); names.push(["machine", m], ["slots", m]);
    }
    const rf = row();
    for (const p of items) if (it(p).k === "field") rf[ix[p]] = cyc(it(p).t);
    rows.push(rf); rhs.push(60 * pos(farm.fields - (R.fields || 0))); names.push(["fields", "fields"]);
    for (const p of items) {
      const k = it(p).k;
      if (k === "animal") { const r = row(); r[ix[p]] = cyc(it(p).t); rows.push(r); rhs.push(60 * pos(animalsOf(farm, p) - ((R.animals || {})[p] || 0))); names.push(["animal", p]); }
      else if (k === "tree") { const r = row(); r[ix[p]] = cyc(it(p).t) / TREE_FRUIT; rows.push(r); rhs.push(60 * pos(treesOf(farm, p) - ((R.trees || {})[p] || 0))); names.push(["tree", p]); }
    }
    for (const [cap, kinds] of [["silo", ["field", "tree"]], ["barn", ["machine", "animal"]]]) {
      if (!farm[cap]) continue;
      const r = row(); for (const p of items) if (kinds.includes(it(p).k)) r[ix[p]] = I / 60;
      rows.push(r); rhs.push(farm[cap]); names.push(["storage", cap]);
    }
    const rsh = row(); for (let k = n; k < nv; k++) rsh[k] = 1;
    const shopUnits = farm.shop_slots * farm.shop_stack * 60 / Math.max(I, farm.shop_sell_minutes);
    rows.push(rsh); rhs.push(shopUnits); names.push(["shop", "shop"]);

    const c = new Float64Array(nv);
    for (const p of items) c[n + ix[p]] = it(p).p || 0;
    const res = simplex(c, rows, rhs);
    const x = res.x.slice(0, n), s = res.x.slice(n);
    const lhs = rows.map(r => r.reduce((a, v, j) => a + v * res.x[j], 0));
    let xp = 0; for (const p of items) xp += (it(p).xp || 0) * x[ix[p]];
    return { I, items, ix, x, s, revenue: res.obj, names, duals: res.duals, rhs, lhs, farm, cyc, xp, shopUnits };
  }

  function bottlenecks(sol) {
    const f = sol.farm, I = sol.I, out = [], mastered = new Set(f.mastered || []);
    sol.names.forEach(([kind, name], k) => {
      const d = sol.duals[k], rhs = sol.rhs[k], lhs = sol.lhs[k];
      if (d <= 1e-6 || kind === "flow") return;
      let per, what, type = kind;
      if (kind === "machine") {
        if (mastered.has(name)) { per = d * 60; what = `${name} ${L("เต็ม (master แล้ว): ค่าของเวลาเครื่องเพิ่ม 1 ชม.")}`; }
        else { per = d * lhs * 0.15; what = `Master ${name} (${L("เวลาลด 15%, ประมาณ)")}`; }
      } else if (kind === "storage") { per = d; what = `+1 ${L("ช่อง ")}${name === "silo" ? "Silo" : "Barn"}`; }
      else if (kind === "slots") { per = d * 60 / I; what = `+1 slot ${L("ที่ ")}${name}`; }
      else if (kind === "fields") { per = d * 60; what = `+1 ${L("แปลงปลูก")}`; }
      else if (kind === "animal") { per = d * 60; what = name === "Honeycomb" ? `+1 ${L("รังผึ้ง")}` : `+1 ${L("สัตว์ที่ให้ ")}${name}`; }
      else if (kind === "tree") { per = d * 60; what = `+1 ${L("ต้น ")}${name}`; }
      else { per = d * f.shop_stack * 60 / Math.max(I, f.shop_sell_minutes); what = `+1 ${L("ช่อง Roadside shop")}`; }
      out.push({ what, per, used: rhs ? lhs / rhs : null, type, name });
    });
    return out.sort((a, b) => b.per - a.per);
  }

  function plan(sol) {
    const rows = [];
    for (const p of sol.items) {
      const k = sol.ix[p], i = BY[p], x = sol.x[k], s = sol.s[k];
      if (x < 1e-6 && s < 1e-6) continue;
      let perVisit, unit;
      if (i.k === "field") { perVisit = x * sol.cyc(i.t) / 60; unit = L("แปลง"); }
      else if (i.k === "machine") { perVisit = x * sol.I / 60 / i.y; unit = i.y > 1 ? L("ชุด") : L("ชิ้น"); }
      else { perVisit = x * sol.I / 60; unit = L("ชิ้น"); }
      rows.push({ p, k: i.k, w: i.k === "field" ? "Field" : i.w, made: x, sold: s, used: x - s,
                  coins: s * (i.p || 0), perVisit, unit });
    }
    const use = [];
    sol.names.forEach(([kind, name], k) => {
      if (["machine", "fields", "shop", "storage"].includes(kind) && sol.rhs[k] > 0)
        use.push({ kind, name, used: sol.rhs[k] ? sol.lhs[k] / sol.rhs[k] : 0 });
    });
    return { rows, use };
  }

  // ---------- whole-number rotation of the Mode 1 plan ----------
  /* The LP gives averages per visit (15.6 fields of Soybean). Turn them into a cycle of K visits with a whole
     number for every item at every visit, repeating forever. K = the smallest cycle (<= maxK) whose totals are
     close to whole numbers. Within each group (fields, one machine, one animal, one tree) the units are spread
     so each visit stays within capacity and every item stays as close as possible to its average. */
  /* Mode 1 solution -> per-visit average of each start unit, grouped by the capacity it shares. */
  function visitUnits(sol, reserve) {
    const I = sol.I, f = sol.farm, R = reserve || {}, units = [];
    for (const p of sol.items) {
      const k = sol.ix[p], i = BY[p], x = sol.x[k];
      if (x < 1e-6) continue;
      let avg, g, unit, cap;
      if (i.k === "field") { avg = x * I / 60; g = "field"; unit = L("แปลง"); cap = f.fields - (R.fields || 0); }
      else if (i.k === "machine") { avg = x * I / 60 / i.y; g = "m:" + i.w; unit = i.y > 1 ? `${L("ชุด (")}${i.y} ${L("ชิ้น)")}` : L("ชิ้น"); cap = machineSlots(f, i.w) * machineCount(f, i.w) - ((R.slots || {})[i.w] || 0); }
      else if (i.k === "animal") { avg = x * I / 60; g = "a:" + p; unit = p === "Honeycomb" ? L("ชิ้น") : L("ตัว"); cap = animalsOf(f, p) - ((R.animals || {})[p] || 0); }
      else if (i.k === "tree") { avg = x * I / 60 / i.y; g = "t:" + p; unit = L("ต้น"); cap = treesOf(f, p) - ((R.trees || {})[p] || 0); }
      else continue;
      units.push({ p, g, avg, unit, cap: Math.max(0, Math.floor(cap + 1e-9)), kind: i.k, w: i.k === "field" ? "Field" : i.w, sold: sol.s[k] > 1e-4 });
    }
    return units;
  }

  function rotation(sol, maxK = 10) {
    const units = visitUnits(sol);
    let K = 1, best = Infinity;
    for (let k = 1; k <= maxK; k++) {
      const err = Math.max(0, ...units.map(u => Math.abs(u.avg * k - Math.round(u.avg * k))));
      if (err <= 0.2) { K = k; break; }
      if (err < best - 1e-9) { best = err; K = k; }
    }
    const groups = {};
    units.forEach(u => (groups[u.g] = groups[u.g] || []).push(u));
    for (const us of Object.values(groups)) {
      us.forEach(u => { u.n = Math.round(u.avg * K); u.counts = Array(K).fill(0); });
      const cap = us[0].cap * K;
      let G = us.reduce((a, u) => a + u.n, 0);
      while (G > cap) {                              // rounding pushed the group over capacity: trim the most rounded-up item
        const u = us.filter(u => u.n > 0).sort((a, b) => (b.n - b.avg * K) - (a.n - a.avg * K))[0];
        u.n--; G--;
      }
      const alloc = us.map(() => 0);
      for (let v = 0; v < K; v++) {
        let gv = Math.floor(G * (v + 1) / K) - Math.floor(G * v / K);
        while (gv-- > 0) {
          let bi = -1, bd = -Infinity;
          us.forEach((u, j) => { if (alloc[j] < u.n) { const d = u.n * (v + 1) / K - alloc[j]; if (d > bd) { bd = d; bi = j; } } });
          if (bi < 0) break;
          us[bi].counts[v]++; alloc[bi]++;
        }
      }
    }
    return { K, units };
  }

  // ---------- Mode 2 ----------
  const inputsOf = p => BY[p].in;
  const yieldOf = p => BY[p].y;

  function topo(roots) {
    const order = [], seen = new Set();
    const visit = p => { if (seen.has(p)) return; seen.add(p); for (const [i] of inputsOf(p)) visit(i); order.push(p); };
    roots.forEach(visit);
    return order.reverse();
  }

  function bom(items, have) {
    const order = topo(Object.keys(items));
    const need = {}, stock = { ...have }, fromStock = {}, starts = {}, made = {}, spare = {};
    for (const p of order) need[p] = items[p] || 0;
    for (const p of order) {
      const take = Math.min(stock[p] || 0, need[p]); stock[p] = (stock[p] || 0) - take; fromStock[p] = take;
      const net = need[p] - take;
      starts[p] = net > 0 ? Math.ceil(net / yieldOf(p) - 1e-9) : 0;
      made[p] = starts[p] * yieldOf(p);
      for (const [i, q] of inputsOf(p)) need[i] += q * starts[p];
    }
    for (const p of order) spare[p] = made[p] - (need[p] - fromStock[p]);
    return { order, need, fromStock, starts, made, spare };
  }

  function tails(order, farm) {
    const T = {}, users = {}, tail = {};
    for (const p of order) { T[p] = timeOf(farm, BY[p]); users[p] = users[p] || []; }
    for (const p of order) for (const [i] of inputsOf(p)) (users[i] = users[i] || []).push(p);
    for (const p of order) tail[p] = T[p] + Math.max(0, ...users[p].map(u => tail[u]));
    return { T, tail };
  }

  function simulate(order, starts, farm, have, I, treesReady = true, maxVisits = 2000) {
    const { T, tail } = tails(order, farm);
    const pri = order.filter(p => starts[p]).sort((a, b) => tail[b] - tail[a]);
    const stock = { ...have }, rem = { ...starts };
    const machines = {}, animals = {}, trees = {}, log = [];
    let fields = [], lastFinish = 0;
    const snaps = [];
    const st = p => stock[p] || 0;
    const fail = (p, what) => { throw new Error(`${p}: ${L("ฟาร์มไม่มี ")}${what} (${L("แก้ในตั้งค่าฟาร์ม หรือใส่ในของที่มีอยู่)")}`); };

    for (let v = 0; v < maxVisits; v++) {
      const t = v * I;
      for (const qs of Object.values(machines)) for (const q of qs) {
        for (let j = q.length - 1; j >= 0; j--) if (q[j][0] <= t + EPS) { stock[q[j][1]] = st(q[j][1]) + yieldOf(q[j][1]); q.splice(j, 1); }
      }
      fields = fields.filter(([f, p]) => { if (f <= t + EPS) { stock[p] = st(p) + 1; return false; } return true; });
      for (const p in animals) animals[p] = animals[p].filter(f => { if (f <= t + EPS) { stock[p] = st(p) + 1; return false; } return true; });

      let started = false;
      for (const p of pri) {
        const i = BY[p];
        while (rem[p] > 0) {
          const ins = inputsOf(p);
          if (ins.some(([q, n]) => st(q) < n - EPS)) break;
          let f, where, act;
          if (i.k === "machine") {
            const cnt = machineCount(farm, i.w), slots = machineSlots(farm, i.w);
            if (!cnt || !slots) fail(p, i.w);
            const qs = machines[i.w] || (machines[i.w] = Array.from({ length: cnt }, () => []));
            const free = qs.filter(q => q.length < slots);
            if (!free.length) break;
            const endOf = q => Math.max(t, ...q.map(e => e[0]));
            const q = free.reduce((a, b) => (endOf(b) < endOf(a) ? b : a));
            f = endOf(q) + T[p]; q.push([f, p]); where = i.w; act = "start";
          } else if (i.k === "field") {
            if (!farm.fields) fail(p, L("แปลงปลูก"));
            if (fields.length >= farm.fields) break;
            f = t + T[p]; fields.push([f, p]); where = "Field"; act = "plant";
          } else if (i.k === "animal") {
            const N = animalsOf(farm, p);
            if (!N) fail(p, `${L("สัตว์ที่ให้ ")}${p}`);
            const a = animals[p] || (animals[p] = []);
            if (a.length >= N) break;
            f = t + T[p]; a.push(f); where = i.w; act = ins.length ? "feed" : "collect";
          } else if (i.k === "tree") {
            const N = treesOf(farm, p);
            if (!N) fail(p, `${L("ต้น ")}${p}`);
            const nx = trees[p] || (trees[p] = Array(N).fill(treesReady ? 0 : T[p]));
            const j = nx.findIndex(x => x <= t + EPS);
            if (j < 0) break;
            nx[j] = t + T[p]; f = t; stock[p] = st(p) + yieldOf(p); where = i.w; act = "harvest";
          } else throw new Error(`${p}: ${L("เป็นของจากเหมืองหรือตกปลา ระบบวางแผนให้ไม่ได้ ใส่จำนวนที่มีไว้ใน ของที่มีอยู่แล้ว")}`);
          for (const [q, n] of ins) stock[q] = st(q) - n;
          rem[p]--; lastFinish = Math.max(lastFinish, f); started = true;
          log.push({ visit: v + 1, hour: t / 60, act, where, p, units: yieldOf(p), f });
        }
      }
      const snap = { fields: fields.length, machineMin: {}, slots: {}, animals: {}, trees: {} };
      for (const [m, qs] of Object.entries(machines)) {
        snap.slots[m] = qs.reduce((a, q) => a + q.length, 0);
        snap.machineMin[m] = qs.reduce((a, q) => a + Math.min(I, Math.max(0, Math.max(t, ...q.map(e => e[0])) - t)), 0) / I * 60;
      }
      for (const [p, a] of Object.entries(animals)) snap.animals[p] = a.length;
      for (const [p, nx] of Object.entries(trees)) snap.trees[p] = nx.filter(x => x > t + EPS).length;
      snaps.push(snap);
      const busy = Object.values(machines).some(qs => qs.some(q => q.length)) || fields.length
        || Object.values(animals).some(a => a.length);
      if (!Object.values(rem).some(Boolean) && !busy) return { visits: v + 1, doneH: t / 60, readyH: lastFinish / 60, log, snaps };
      const treesPending = pri.some(p => rem[p] && BY[p].k === "tree");
      if (!busy && !started && !treesPending) throw new Error(`${L("ติดที่รอบ ")}${v + 1}: ${L("เริ่มไม่ได้ ")}${pri.filter(p => rem[p]).join(", ")}`);
    }
    throw new Error(L("ไม่เสร็จภายใน 2000 รอบ"));
  }

  /* Quest visits ride on the Mode 1 rotation: visit v of the quest = Mode 1 visit (start + v) mod K, with the
     money part trimmed (largest remainder) wherever the quest holds fields, slots, animals or trees. */
  function questVisits(farm, sim, I, start = 0) {
    const base = solve(farm, I), rot = rotation(base), K = rot.K, visits = [];
    sim.snaps.forEach((snap, v) => {
      const idx = (start + v) % K, groups = {};
      const money = rot.units.filter(u => u.n > 0).map(u => ({ ...u, base: u.counts[idx], count: u.counts[idx] }));
      money.forEach(u => (groups[u.g] = groups[u.g] || []).push(u));
      for (const [g, us] of Object.entries(groups)) {
        const held = g === "field" ? snap.fields : g.startsWith("m:") ? (snap.slots[us[0].w] || 0)
          : g.startsWith("a:") ? (snap.animals[us[0].p] || 0) : (snap.trees[us[0].p] || 0);
        const free = Math.max(0, us[0].cap - held), want = us.reduce((a, u) => a + u.base, 0);
        if (want <= free) continue;
        const share = us.map(u => u.base * free / want);
        us.forEach((u, j) => (u.count = Math.floor(share[j])));
        let left = free - us.reduce((a, u) => a + u.count, 0);
        us.map((u, j) => [share[j] - u.count, j]).sort((a, b) => b[0] - a[0]).forEach(([, j]) => { if (left > 0) { us[j].count++; left--; } });
      }
      const acts = {};
      sim.log.filter(l => l.visit === v + 1).forEach(l => {
        const key = l.act + "|" + l.p + "|" + l.where;
        (acts[key] = acts[key] || { act: l.act, p: l.p, where: l.where, units: 0, n: 0 }); acts[key].units += l.units; acts[key].n++;
      });
      visits.push({ visit: v + 1, hour: v * I / 60, cycleVisit: idx, quest: Object.values(acts), money, reserve: snap });
    });
    return { visits, K, next: (start + sim.snaps.length) % K };
  }

  function quest(farm, items, have, I, opts = {}) {
    const b = bom(items, have);
    const { T, tail } = tails(b.order, farm);
    const unl = new Set(unlocked(farm.level, true, []));
    const locked = b.order.filter(p => b.starts[p] && !unl.has(p));
    const any = Object.values(b.starts).some(Boolean);
    const treesReady = opts.treesStart !== "harvested";
    const crit = any ? Math.max(...b.order.filter(p => b.starts[p]).map(p => tail[p])) / 60 : 0;
    const out = { ...b, T, tail, locked, crit };
    try {
      out.sim = any ? simulate(b.order, b.starts, farm, have, I, treesReady) : { visits: 1, doneH: 0, readyH: 0, log: [] };
      out.fast = any ? simulate(b.order, b.starts, farm, have, 5, treesReady) : out.sim;
    } catch (e) { out.error = e.message; return out; }
    out.visits = questVisits(farm, out.sim, I, opts.cycleStart || 0).visits;
    const base = solve(farm, I).revenue;
    const net = {};
    for (const [p, q] of Object.entries(items)) { const r = q - (b.fromStock[p] || 0); if (r > 0) net[p] = r; }
    let H = Math.max(out.sim.doneH, I / 60), sol = null;
    for (let k = 0; k < 20 && !sol; k++) {
      try { sol = solve(farm, I, Object.fromEntries(Object.entries(net).map(([p, q]) => [p, q / H]))); }
      catch (e) { if (e.message !== "infeasible") throw e; H *= 1.25; }
    }
    out.base = base; out.money = sol; out.H = H;
    out.cost = sol ? (base - sol.revenue) * H : null;
    out.value = Object.entries(items).reduce((a, [p, q]) => a + q * (BY[p].p || 0), 0);
    return out;
  }

  return { init, t: L, setLang, unlocked, solve, bottlenecks, plan, rotation, quest, bom, simulate, simplex,
           get items() { return ITEMS; }, get by() { return BY; }, timeOf, isMastered };
})();
if (typeof module !== "undefined") module.exports = HD;

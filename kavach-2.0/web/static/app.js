(() => {
  const $ = (id) => document.getElementById(id);
  let page = "home";
  let live = {};
  let clockTimer = 0;
  let toggling = false;
  let toastTimer = 0;
  let goNotice = "";
  let goNoticeKind = "";
  let goNoticeTimer = 0;

  async function api(path, opts) {
    const res = await fetch(path, {
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }


  function fmt(v, d) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return n.toLocaleString("en-IN", {
      minimumFractionDigits: d == null ? 2 : d,
      maximumFractionDigits: d == null ? 2 : d,
    });
  }
  function fmtPnl(v) {
    if (v == null || v === "" || Number.isNaN(Number(v))) return "—";
    const n = Number(v);
    const abs = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (n > 0 ? "+" : n < 0 ? "-" : "") + "₹" + abs;
  }

  function clsPnl(v) {
    const n = Number(v);
    if (!Number.isFinite(n) || n === 0) return "";
    return n > 0 ? "buy" : "sell";
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function reduceMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function setBusy(on) {
    const g = $("busyGate");
    if (!g) return;
    g.classList.toggle("hidden", !on);
    g.setAttribute("aria-hidden", on ? "false" : "true");
  }

  function toast(msg, ok) {
    const el = $("toast");
    if (!el) return;
    if (toastTimer) {
      clearTimeout(toastTimer);
      toastTimer = 0;
    }
    const text = String(msg || "").trim();
    el.textContent = text;
    el.className = "toast" + (ok ? " ok" : text ? " bad" : "");
    if (!text) return;
    toastTimer = setTimeout(() => {
      el.textContent = "";
      el.className = "toast";
      toastTimer = 0;
    }, 2000);
  }

  function setGoNotice(msg, kind) {
    goNotice = msg || "";
    goNoticeKind = kind || "";
    if (goNoticeTimer) {
      clearTimeout(goNoticeTimer);
      goNoticeTimer = 0;
    }
    const el = $("goNotice");
    if (el) {
      el.textContent = goNotice;
      el.className = "go-notice" + (goNotice ? (goNoticeKind === "paused" ? " paused" : " ok") : " hidden");
    }
    if (goNotice && goNoticeKind !== "paused") {
      goNoticeTimer = setTimeout(() => {
        goNotice = "";
        goNoticeKind = "";
        const n = $("goNotice");
        if (n) {
          n.textContent = "";
          n.className = "go-notice hidden";
        }
      }, 8000);
    }
  }

  function skeleton() {
    return `<div>
      <div class="skel skel-title"></div>
      <p class="sub">Loading…</p>
      <div class="stats stats3">
        <div class="skel skel-card"></div>
        <div class="skel skel-card"></div>
        <div class="skel skel-card"></div>
      </div>
      <div class="skel skel-row"></div>
      <div class="skel skel-row"></div>
    </div>`;
  }

  function playViewIn(view) {
    if (!view || reduceMotion()) return;
    view.classList.remove("view-in");
    void view.offsetWidth;
    view.classList.add("view-in");
  }

  function tickClock() {
    const el = $("clock");
    if (!el) return;
    el.textContent = new Date().toLocaleTimeString("en-IN", {
      timeZone: "Asia/Kolkata",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }

  function paintToggle(el, lbl, on, onText, offText) {
    if (!el) return;
    if (document.activeElement !== el && !toggling) el.checked = !!on;
    const wrap = el.closest(".toggle");
    if (wrap) wrap.classList.toggle("is-on", !!on), wrap.classList.toggle("is-off", !on);
    if (lbl) lbl.textContent = on ? onText : offText;
  }


  function posRowsHtml(positions) {
    const rows = Array.isArray(positions) ? positions : [];
    if (!rows.length) {
      return '<tr><td colspan="5">No open broker positions.</td></tr>';
    }
    return rows.map((p) => {
      const qty = p.qty != null ? Number(p.qty) : 0;
      const avg = p.avg != null && p.avg !== "" ? fmt(p.avg) : "—";
      const ltp = p.ltp != null && p.ltp !== "" ? fmt(p.ltp) : "—";
      const pnl = p.pnl;
      const pnlTxt = pnl == null || pnl === "" ? "—" : fmtPnl(pnl);
      const pnlCls = clsPnl(pnl);
      return `<tr class="${qty < 0 ? "hist-sell" : "hist-buy"}">
            <td>${esc(p.symbol || "")}</td>
            <td>${esc(String(qty))}</td>
            <td>${esc(avg)}</td>
            <td>${esc(ltp)}</td>
            <td class="${pnlCls}">${esc(pnlTxt)}</td>
          </tr>`;
    }).join("");
  }

  function paintPositions(positions) {
    const body = $("posBody");
    if (!body) return;
    body.innerHTML = posRowsHtml(positions);
  }

  function applyChrome(s) {
    live = s || live;
    const paused = !!live.paused;
    const resumed = !paused;
    const hedgeOn = !!live.dyn_hedge;
    const broker = !!live.broker;
    const brokerEl = $("chipBroker");
    const nifty = $("niftyTop");
    if (brokerEl) {
      brokerEl.textContent = broker ? "BROKER CONNECTED" : "BROKER OFF";
      brokerEl.className = "chip " + (broker ? "ok" : "live");
    }
    if (nifty) {
      const px = live.nifty_ltp != null && live.nifty_ltp !== ""
        ? Number(live.nifty_ltp).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : (String(live.nifty || "").trim() || "—");
      nifty.textContent = "NIFTY  " + px;
      nifty.className = "chip chip-spot";
    }
    const clock = $("clock");
    if (clock) clock.className = "chip chip-spot";
    const pnlEl = $("statPnl");
    if (pnlEl) {
      const v = live.day_pnl;
      pnlEl.textContent = fmtPnl(v);
      pnlEl.className = (v == null || v === "") ? "" : clsPnl(v);
    }
    paintToggle($("runToggle"), $("runLbl"), resumed, "RESUMED", "PAUSED");
    paintToggle($("hedgeToggle"), $("hedgeLbl"), hedgeOn, "HEDGE ON", "HEDGE OFF");
    paintPositions(live.positions);
  }

  function pre(text) {
    return `<div class="card"><pre>${esc(text || "")}</pre></div>`;
  }

  function cap(s) {
    const t = String(s || "");
    if (!t) return "";
    return t.charAt(0).toUpperCase() + t.slice(1);
  }
  function fmtDays(n) {
    const v = Number(n);
    if (!Number.isFinite(v)) return "—";
    return v.toFixed(1) + " Days";
  }

  function paintTokenPage(view, t) {
    const d = t.dhan || {};
    const totp = t.totp || {};
    const z = t.zerodha || {};
    const health = d.health_class || (d.present ? "healthy" : "missing");
    const healthLabel = d.present ? cap(d.status || health) : "Missing";
    view.innerHTML = `
      <header class="page-head"><h3>Authorisation</h3></header>
      <div class="row2 tok-grid">
        <div class="card tok-card tok-card-green">
          <h3 class="tok-title"><img class="tok-logo" src="/static/dhan.svg" alt="" />DHAN TOKEN</h3>
          <div class="tok-meta">
            <div class="kv"><span>Status</span><b class="${d.present ? "buy" : "sell"}">${esc(healthLabel)}</b></div>
            <div class="kv"><span>Last4</span><b>${d.last4 ? "····" + esc(d.last4) : "—"}</b></div>
            <div class="kv"><span>Saved</span><b>${esc(d.saved_at || "—")}</b></div>
            <div class="kv"><span>Expires</span><b>${esc(d.jwt_exp || d.expires_at || "—")}</b></div>
            <div class="kv"><span>Age / Left</span><b>${d.age_hours == null || !d.present ? "—" : d.age_hours + "h / " + (d.expires_in_hours == null ? "—" : d.expires_in_hours + "h")}</b></div>
            <div class="kv tok-extra"><span>TOTP Auto-Renew</span><b>${totp.configured ? (totp.auto_renew ? "ON" : "OFF") : "Not configured"}</b></div>
            <div class="kv tok-extra"><span>TOTP Secret Due</span><b>${totp.days_left == null ? "—" : fmtDays(totp.days_left)}</b></div>
            <div class="kv tok-extra"><span>Last TOTP Refresh</span><b>${esc(totp.last_refresh || "never")}</b></div>
          </div>
          ${totp.last_error ? `<p class="sub tok-err">${esc(totp.last_error)}</p>` : ""}
          <label class="muted" for="jwtBox">Paste Dhan Token</label>
          <textarea id="jwtBox" class="tokbox" rows="2" autocomplete="off" spellcheck="false" placeholder="Paste DHAN Token Here"></textarea>
          <div class="row2">
            <button type="button" class="btn btn-green" id="tokRef">REFRESH JWT</button>
            <button type="button" class="btn btn-green-outline" id="tokPaste">SAVE DHAN TOKEN</button>
          </div>
          <div class="row2 tok-actions">
            <button type="button" class="btn btn-green-outline" id="tokStat">TOKEN STATUS</button>
            <button type="button" class="btn btn-red" id="tokOff">DEACTIVATE TOKEN</button>
          </div>
        </div>
        <div class="card tok-card tok-card-red">
          <h3 class="tok-title"><img class="tok-logo" src="/static/kite.svg" alt="" />KITE TOKEN</h3>
          <div class="tok-meta">
            <div class="kv"><span>Set</span><b class="${z.present ? "buy" : "sell"}">${z.present ? "Yes" : "No"}</b></div>
            <div class="kv"><span>Last4</span><b>${z.last4 ? "····" + esc(z.last4) : "—"}</b></div>
            <div class="kv"><span>Saved</span><b>${esc(z.saved_at || "—")}</b></div>
          </div>
          <label class="muted" for="zBox">Paste Zerodha Token</label>
          <textarea id="zBox" class="tokbox" rows="2" autocomplete="off" spellcheck="false" placeholder="Paste ZERODHA Token Here"></textarea>
          <button type="button" class="btn btn-red" id="tokZ">SAVE ZERODHA TOKEN</button>
        </div>
      </div>
      <p class="sub" id="tokMsg"></p>`;
  }

  async function renderTokenPage(view, msgText) {
    const t = await api("/api/token/status");
    paintTokenPage(view, t);
    if (msgText && $("tokMsg")) $("tokMsg").textContent = msgText;
    async function tokenCall(fn) {
      const msg = $("tokMsg");
      try {
        setBusy(true);
        const r = await fn();
        const text = r.text || r.error || (r.ok ? "Done" : "failed");
        toast(text, !!r.ok);
        if (r.ok) {
          await renderTokenPage(view, text);
          return;
        }
        if (msg) msg.textContent = text;
      } catch (err) {
        const text = err.message || "failed";
        if (msg) msg.textContent = text;
        toast(text, false);
      } finally {
        setBusy(false);
      }
    }
    $("tokRef").onclick = () => tokenCall(() => api("/api/token/refresh", { method: "POST", body: "{}" }));
    $("tokOff").onclick = () => tokenCall(() => api("/api/token/deactivate", { method: "POST", body: "{}" }));
    if ($("tokStat")) {
      $("tokStat").onclick = () => renderTokenPage(view, "Token status refreshed.");
    }
    $("tokPaste").onclick = () => tokenCall(() => api("/api/token/dhan-jwt", {
      method: "POST",
      body: JSON.stringify({ token: $("jwtBox").value }),
    }));
    $("tokZ").onclick = () => tokenCall(() => api("/api/token/zerodha", {
      method: "POST",
      body: JSON.stringify({ token: $("zBox").value }),
    }));
  }

  function go(p) {
    page = p;
    closeMenu();
    document.querySelectorAll(".nav").forEach((b) => b.classList.toggle("on", b.dataset.go === p));
    const tabPages = { home: 1, status: 1, ato: 1, register: 1 };
    document.querySelectorAll(".tabbar span").forEach((b) => {
      if (b.hasAttribute("data-menu")) {
        b.classList.toggle("on", !tabPages[p]);
      } else {
        b.classList.toggle("on", b.dataset.go === p);
      }
    });
    render(true);
  }

  function autoProtect(side, sellStrike, step) {
    const n = Number(sellStrike);
    if (!n) return "";
    return side === "PE" ? String(n - step) : String(n + step);
  }

  function strikeOf(list, symbol) {
    const row = (list || []).find((p) => p.symbol === symbol);
    return row ? row.strike : "";
  }

  function optionHtml(rows, selected, noneLabel) {
    const opts = [`<option value="">${esc(noneLabel)}</option>`];
    for (const p of rows || []) {
      const sel = p.symbol === selected ? " selected" : "";
      opts.push(`<option value="${esc(p.symbol)}"${sel}>${esc(p.label)}</option>`);
    }
    return opts.join("");
  }

  function qBlock(n, label, inner) {
    return `<div class="reg-q"><div class="q-lab"><span class="q-label">${esc(label)}</span></div><div class="field">${inner}</div></div>`;
  }

  function renderRegister(view, d) {
    window.__regQCount = Number(d.question_count || 18);
    const step = Number(d.ato_step || 50);
    const peHint = d.auto_protect_hint && d.auto_protect_hint.pe ? d.auto_protect_hint.pe : "";
    const ceHint = d.auto_protect_hint && d.auto_protect_hint.ce ? d.auto_protect_hint.ce : "";
    const note = d.book_note
      ? `<p class="reg-note">${esc(d.book_note)}</p>`
      : "";
    const armed = d.deployed
      ? `<p class="reg-note">Batman is already armed (${esc(d.file)}). Confirm will archive it and register again.</p>`
      : "";
    view.innerHTML = `
      <header class="page-head"><h3>Register Batman</h3></header>
      ${note}${armed}
      <div class="card add-form reg-form">
        <div class="reg-top-grid">
          ${qBlock(1, "Paper or Live trade", `
            <select id="regMode">
              <option value="paper" ${d.order_mode !== "live" ? "selected" : ""}>Paper</option>
              <option value="live" ${d.order_mode === "live" ? "selected" : ""}>Live</option>
            </select>`)}
          ${qBlock(2, "Register CE/PE", `
            <select id="regScope">
              <option value="both" ${d.reg_scope === "both" ? "selected" : ""}>Register both CE and PE</option>
              <option value="ce" ${d.reg_scope === "ce" ? "selected" : ""}>Register CE only</option>
              <option value="pe" ${d.reg_scope === "pe" ? "selected" : ""}>Register PE only</option>
            </select>`)}
        </div>
        <div class="reg-grid">
          <section class="reg-side reg-side-ce dep-card-green" id="regCeBlock">
            <h4 class="sec-title">CE side</h4>
            ${qBlock(10, "Core BUY leg", `<select id="regCeBuy">${optionHtml(d.ce_long, "", "Core BUY")}</select>`)}
            ${qBlock(11, "Margin Hedge", `<select id="regCeHedge">${optionHtml(d.ce_long, "", "None — not required")}</select>`)}
            ${qBlock(12, "30% Dynamic Hedge", `<select id="regCeDyn">${optionHtml(d.ce_long, "", "None — not required")}</select>`)}
            ${qBlock(13, "SELL leg", `<select id="regCeSell">${optionHtml(d.ce_short, "", "SELL")}</select>`)}
            ${qBlock(14, "ATO strike", `
              <div class="ato-row">
                <select id="regCeAtoMode">
                  <option value="auto" selected>Auto</option>
                  <option value="custom">Custom strike</option>
                </select>
                <input id="regCeAto" type="number" placeholder="Auto ${esc(ceHint)}" />
              </div>
              <p class="sub" id="regCeAtoHint"></p>`)}
            ${qBlock(15, "Entry NIFTY level", `<input id="regCeEntry" type="number" placeholder="${esc(d.entry_placeholder || "NIFTY level")}" />`)}
            ${qBlock(16, "Exit NIFTY level (retrace)", `<input id="regCeExit" type="number" placeholder="${esc(d.exit_placeholder || "NIFTY level")}" />`)}
          </section>
          <section class="reg-side reg-side-pe dep-card-red" id="regPeBlock">
            <h4 class="sec-title">PE side</h4>
            ${qBlock(3, "Core BUY leg", `<select id="regPeBuy">${optionHtml(d.pe_long, "", "Core BUY")}</select>`)}
            ${qBlock(4, "Margin Hedge", `<select id="regPeHedge">${optionHtml(d.pe_long, "", "None — not required")}</select>`)}
            ${qBlock(5, "30% Dynamic Hedge", `<select id="regPeDyn">${optionHtml(d.pe_long, "", "None — not required")}</select>`)}
            ${qBlock(6, "SELL leg", `<select id="regPeSell">${optionHtml(d.pe_short, "", "SELL")}</select>`)}
            ${qBlock(7, "ATO strike", `
              <div class="ato-row">
                <select id="regPeAtoMode">
                  <option value="auto" selected>Auto</option>
                  <option value="custom">Custom strike</option>
                </select>
                <input id="regPeAto" type="number" placeholder="Auto ${esc(peHint)}" />
              </div>
              <p class="sub" id="regPeAtoHint"></p>`)}
            ${qBlock(8, "Entry NIFTY level", `<input id="regPeEntry" type="number" placeholder="${esc(d.entry_placeholder || "NIFTY level")}" />`)}
            ${qBlock(9, "Exit NIFTY level (retrace)", `<input id="regPeExit" type="number" placeholder="${esc(d.exit_placeholder || "NIFTY level")}" />`)}
          </section>
        </div>
        <div class="reg-top-grid">
          ${qBlock(17, "ATO manage CE/PE", `
            <select id="regAtoMon">
              <option value="both" ${d.ato_mon === "both" ? "selected" : ""}>Manage both CE and PE</option>
              <option value="ce" ${d.ato_mon === "ce" ? "selected" : ""}>Manage CE only</option>
              <option value="pe" ${d.ato_mon === "pe" ? "selected" : ""}>Manage PE only</option>
            </select>`)}
          ${qBlock(18, "Confirm deployment", `<button type="button" class="btn gold" id="regGo">REGISTER — ARM KAVACH</button>`)}
        </div>
        <p class="sub" id="regMsg"></p>
      </div>`;

    function refillLong(sel, rows, keep, used, noneLabel) {
      const filtered = (rows || []).filter((p) => p.symbol === keep || !used.has(p.symbol));
      sel.innerHTML = optionHtml(filtered, keep, noneLabel);
    }

    function sync() {
      const scope = $("regScope").value;
      const peOn = scope !== "ce";
      const ceOn = scope !== "pe";
      $("regPeBlock").classList.toggle("q-off", !peOn);
      $("regCeBlock").classList.toggle("q-off", !ceOn);
      $("regPeBlock").querySelectorAll("input,select").forEach((el) => { el.disabled = !peOn; });
      $("regCeBlock").querySelectorAll("input,select").forEach((el) => { el.disabled = !ceOn; });

      const peUsed = new Set();
      if ($("regPeBuy").value) peUsed.add($("regPeBuy").value);
      refillLong($("regPeHedge"), d.pe_long, $("regPeHedge").value, peUsed, "None — not required");
      if ($("regPeHedge").value) peUsed.add($("regPeHedge").value);
      refillLong($("regPeDyn"), d.pe_long, $("regPeDyn").value, peUsed, "None — not required");
      const peHedgeLeft = (d.pe_long || []).filter((p) => p.symbol !== $("regPeBuy").value);
      const peDynLeft = peHedgeLeft.filter((p) => p.symbol !== $("regPeHedge").value);
      $("regPeHedge").closest(".reg-q").classList.toggle("q-off", !peOn || peHedgeLeft.length === 0);
      $("regPeDyn").closest(".reg-q").classList.toggle("q-off", !peOn || peDynLeft.length === 0);
      if (peOn) {
        $("regPeHedge").disabled = peHedgeLeft.length === 0;
        $("regPeDyn").disabled = peDynLeft.length === 0;
      }

      const ceUsed = new Set();
      if ($("regCeBuy").value) ceUsed.add($("regCeBuy").value);
      refillLong($("regCeHedge"), d.ce_long, $("regCeHedge").value, ceUsed, "None — not required");
      if ($("regCeHedge").value) ceUsed.add($("regCeHedge").value);
      refillLong($("regCeDyn"), d.ce_long, $("regCeDyn").value, ceUsed, "None — not required");
      const ceHedgeLeft = (d.ce_long || []).filter((p) => p.symbol !== $("regCeBuy").value);
      const ceDynLeft = ceHedgeLeft.filter((p) => p.symbol !== $("regCeHedge").value);
      $("regCeHedge").closest(".reg-q").classList.toggle("q-off", !ceOn || ceHedgeLeft.length === 0);
      $("regCeDyn").closest(".reg-q").classList.toggle("q-off", !ceOn || ceDynLeft.length === 0);
      if (ceOn) {
        $("regCeHedge").disabled = ceHedgeLeft.length === 0;
        $("regCeDyn").disabled = ceDynLeft.length === 0;
      }

      const peSell = strikeOf(d.pe_short, $("regPeSell").value);
      const ceSell = strikeOf(d.ce_short, $("regCeSell").value);
      const peAuto = autoProtect("PE", peSell, step);
      const ceAuto = autoProtect("CE", ceSell, step);
      $("regPeAtoHint").textContent = peOn && peAuto ? "Auto ATO: " + peAuto + " PE" : "Auto ATO after PE SELL is chosen";
      $("regCeAtoHint").textContent = ceOn && ceAuto ? "Auto ATO: " + ceAuto + " CE" : "Auto ATO after CE SELL is chosen";
      const peCustom = $("regPeAtoMode").value === "custom";
      const ceCustom = $("regCeAtoMode").value === "custom";
      if (peOn) {
        $("regPeAto").disabled = !peCustom;
        $("regPeAto").closest(".reg-q").querySelector("input").classList.toggle("is-grey", !peCustom);
        if (!peCustom) $("regPeAto").value = "";
        $("regPeAto").placeholder = peAuto ? "Auto " + peAuto : "Custom NIFTY strike";
      }
      if (ceOn) {
        $("regCeAto").disabled = !ceCustom;
        if (!ceCustom) $("regCeAto").value = "";
        $("regCeAto").placeholder = ceAuto ? "Auto " + ceAuto : "Custom NIFTY strike";
      }

      const atoMonQ = $("regAtoMon").closest(".reg-q");
      if (peOn && ceOn) {
        $("regAtoMon").disabled = false;
        atoMonQ.classList.remove("q-off");
      } else {
        $("regAtoMon").value = peOn ? "pe" : "ce";
        $("regAtoMon").disabled = true;
        atoMonQ.classList.add("q-off");
      }
    }

    ["regScope","regPeBuy","regPeHedge","regPeDyn","regPeSell","regPeAtoMode","regCeBuy","regCeHedge","regCeDyn","regCeSell","regCeAtoMode"].forEach((id) => {
      $(id).addEventListener("change", sync);
    });
    sync();

    $("regGo").onclick = async () => {
      const body = {
        confirm: true,
        order_mode: $("regMode").value,
        reg_scope: $("regScope").value,
        pe_buy: $("regPeBuy").value,
        pe_margin_hedge: $("regPeHedge").value,
        pe_dyn_hedge: $("regPeDyn").value,
        pe_sell: $("regPeSell").value,
        pe_ato_mode: $("regPeAtoMode").value,
        pe_ato_strike: $("regPeAto").value,
        pe_entry: $("regPeEntry").value,
        pe_exit: $("regPeExit").value,
        ce_buy: $("regCeBuy").value,
        ce_margin_hedge: $("regCeHedge").value,
        ce_dyn_hedge: $("regCeDyn").value,
        ce_sell: $("regCeSell").value,
        ce_ato_mode: $("regCeAtoMode").value,
        ce_ato_strike: $("regCeAto").value,
        ce_entry: $("regCeEntry").value,
        ce_exit: $("regCeExit").value,
        ato_mon: $("regAtoMon").value,
      };
      if (!window.confirm("Arm Kavach with these Register answers?")) return;
      try {
        const r = await api("/api/register", { method: "POST", body: JSON.stringify(body) });
        $("regMsg").textContent = r.text || r.error || "done";
        toast(r.ok ? "Batman armed" : r.error || "failed", !!r.ok);
      } catch (err) {
        $("regMsg").textContent = err.message;
        toast(err.message, false);
      }
    };
  }

  async function render() {
    const view = $("view");
    if (!view) return;
    try {
      setBusy(true);
      if (page === "home") {
        const s = await api("/api/state");
        applyChrome(s);
        const pnlCls = s.day_pnl == null || s.day_pnl === "" ? "" : clsPnl(s.day_pnl);
        view.innerHTML = `
          <header class="page-head"><h3>Home</h3></header>
          <div class="stats stats1 home-pnl-row">
            <div class="stat"><kbd>PNL</kbd><b id="statPnl" class="${pnlCls}">${esc(fmtPnl(s.day_pnl))}</b></div>
          </div>
          <div class="card hist-wrap pos-card">
            <h4 class="sec-title">BROKER POSITIONS</h4>
            <table class="hist-table pos-table"><thead><tr>
              <th>Symbol</th><th>Qty</th><th>Avg</th><th>LTP</th><th>PnL</th>
            </tr></thead><tbody id="posBody">${posRowsHtml(s.positions)}</tbody></table>
          </div>`;
        playViewIn(view);
        return;
      }
      if (page === "status") {
        view.innerHTML = `<header class="page-head"><h3>Kavach Status</h3></header>` + pre((await api("/api/status")).text);
      
      } else if (page === "summary") {
        const d = await api("/api/trade-summary");
        const closed = d.closed || [];
        let total = 0;
        let totalRs = 0;
        const rows = closed
          .map((b, i) => {
            const impact = Number(b.impact || 0);
            total += impact;
            totalRs += Number(b.impact_rupees || 0);
            return `<tr class="hist-buy">
            <td>${i + 1}</td>
            <td>${esc(b.side)}</td>
            <td>${esc(b.symbol)}</td>
            <td>${esc(b.entry_time)}</td>
            <td>${fmt(b.entry_premium)}</td>
            <td>${esc(b.exit_time)}</td>
            <td>${fmt(b.exit_premium)}</td>
            <td class="${clsPnl(impact)}">${(impact >= 0 ? "+" : "") + fmt(impact)}</td>
          </tr>`;
          })
          .join("");
        const n = closed.length;
        const foot = n
          ? `<tfoot><tr class="hist-total">
              <td colspan="7"><b>${n} ATO cycle${n === 1 ? "" : "s"} · ₹ ${fmt(d.total_rupees != null ? d.total_rupees : totalRs)}</b></td>
              <td class="${clsPnl(d.total_impact != null ? d.total_impact : total)}"><b>${((d.total_impact != null ? d.total_impact : total) >= 0 ? "+" : "") + fmt(d.total_impact != null ? d.total_impact : total)}</b></td>
            </tr></tfoot>`
          : "";
        view.innerHTML = `
          <header class="page-head"><h3>ATO Summary</h3></header>
          <div class="card hist-wrap">
            <table class="hist-table"><thead><tr>
              <th>#</th><th>Side</th><th>Protect</th><th>Entry Time</th><th>Entry Px</th>
              <th>Exit Time</th><th>Exit Px</th><th>Impact</th>
            </tr></thead><tbody>${rows || '<tr><td colspan="8">No completed ATO cycles today.</td></tr>'}</tbody>${foot}</table>
          </div>`;


      } else if (page === "ato" || page === "buffer") {
        const [a, b, sum, p] = await Promise.all([
          api("/api/ato-status"),
          api("/api/buffer"),
          api("/api/trade-summary"),
          api("/api/poll"),
        ]);
        const open = sum.open || [];
        const openHtml = open.length
          ? open
              .map(
                (leg) => `<div class="ato-open-block">
              <div class="kv"><span>Side</span><b>${esc(leg.side)} ATO</b></div>
              <div class="kv"><span>Protect</span><b>${esc(leg.symbol)}</b></div>
              <div class="kv"><span>Strike</span><b>${esc(leg.protect_strike)}</b></div>
              <div class="kv"><span>Order</span><b>${esc(leg.order_id || "—")}</b></div>
              <div class="kv"><span>Status</span><b class="buy">OPEN</b></div>
            </div>`
              )
              .join("")
          : `<p class="sub ato-open-empty">No open ATO protect leg.</p>`;
        const pollOpts = (p.poll_options || [1, 2, 3, 4, 5, 10, 15])
          .map((v) => `<option value="${v}" ${Number(p.poll_interval) === Number(v) ? "selected" : ""}>${v}s</option>`)
          .join("");
        const statusHtml = a.deployed === false
          ? `<p class="sub ato-open-empty">${esc(a.text || "No active deployment.")}</p>`
          : `<div class="ato-open-block ato-status-block">
              <div class="kv"><span>CE protect</span><b>${esc(a.ce_protect || "N/A")}</b></div>
              <div class="kv"><span>PE protect</span><b>${esc(a.pe_protect || "N/A")}</b></div>
              <div class="kv"><span>Manage</span><b>${esc(a.manage || "—")}</b></div>
            </div>`;
        view.innerHTML = `
          <header class="page-head"><h3>ATO Manager</h3></header>
          <div class="ato-mgr">
            <div class="card add-form ato-mgr-buf dep-card-green">
              <h4 class="sec-title">Buffer Manager</h4>
              <div class="field"><label class="ato-lab">CE ENTRY</label><input id="ce_entry" type="number" inputmode="decimal" placeholder="${esc(b.ce_entry_placeholder || "NIFTY level")}" value="${esc(b.ce_entry)}" /></div>
              <div class="field"><label class="ato-lab">CE EXIT</label><input id="ce_retrace" type="number" inputmode="decimal" placeholder="${esc(b.ce_retrace_placeholder || "NIFTY level")}" value="${esc(b.ce_retrace)}" /></div>
              <div class="field"><label class="ato-lab">PE ENTRY</label><input id="pe_entry" type="number" inputmode="decimal" placeholder="${esc(b.pe_entry_placeholder || "NIFTY level")}" value="${esc(b.pe_entry)}" /></div>
              <div class="field"><label class="ato-lab">PE EXIT</label><input id="pe_retrace" type="number" inputmode="decimal" placeholder="${esc(b.pe_retrace_placeholder || "NIFTY level")}" value="${esc(b.pe_retrace)}" /></div>
              <button type="button" class="btn btn-green" id="bufSave">SAVE</button>
              <p class="sub" id="bufMsg"></p>
            </div>
            <div class="card ato-mgr-status dep-card-blue">
              <h4 class="sec-title">ATO Status</h4>
              <div class="ato-status-wrap">${statusHtml}</div>
              <h4 class="sec-title ato-open-title">Open ATO</h4>
              <div class="ato-open-wrap">${openHtml}</div>
            </div>
            <div class="card add-form ato-mgr-poll dep-card-red">
              <h4 class="sec-title">Poll Interval</h4>
              <div class="field"><select id="pollSel">${pollOpts}</select></div>
              <button type="button" class="btn btn-red" id="pollSave">SAVE</button>
              <p class="sub" id="pollMsg"></p>
            </div>
          </div>`;
        $("bufSave").onclick = async () => {
          const body = {
            ce_entry: $("ce_entry").value,
            pe_entry: $("pe_entry").value,
            ce_retrace: $("ce_retrace").value,
            pe_retrace: $("pe_retrace").value,
          };
          const r = await api("/api/buffer", { method: "POST", body: JSON.stringify(body) });
          $("bufMsg").textContent = r.ok ? "Saved" : r.error || "failed";
          toast(r.ok ? "Buffer saved" : r.error || "failed", !!r.ok);
        };
        $("pollSave").onclick = async () => {
          try {
            const r = await api("/api/poll", { method: "POST", body: JSON.stringify({ poll_interval: $("pollSel").value }) });
            $("pollMsg").textContent = r.ok ? (r.text || "Saved") : (r.error || "failed");
            toast(r.ok ? ("Poll " + $("pollSel").value + "s") : (r.error || "failed"), !!r.ok);
          } catch (err) {
            $("pollMsg").textContent = err.message;
            toast(err.message, false);
          }
        };
      } else if (page === "legs") {
        page = "home";
        document.querySelectorAll("[data-go]").forEach((el) => {
          el.classList.toggle("on", el.getAttribute("data-go") === "home");
        });
        return render();
      } else if (page === "poll") {
        page = "ato";
        document.querySelectorAll("[data-go]").forEach((el) => {
          el.classList.toggle("on", el.getAttribute("data-go") === "ato");
        });
        return render();

      } else if (page === "register") {
        const d = await api("/api/register");
        renderRegister(view, d);
        playViewIn(view);
        return;
      } else if (page === "deploy" || page === "complete") {
        if (page === "complete") {
          page = "deploy";
          document.querySelectorAll("[data-go]").forEach((el) => {
            el.classList.toggle("on", el.getAttribute("data-go") === "deploy");
          });
        }
        const [d, c] = await Promise.all([
          api("/api/deploy"),
          api("/api/complete", { method: "POST", body: "{}" }),
        ]);
        view.innerHTML = `
          <header class="page-head"><h3>Deploy / Complete</h3></header>
          <div class="dep-complete">
            <div class="card add-form dep-card-green">
              <h4 class="sec-title">Deploy Batman 2.0</h4>
              <p class="sub dep-card-sub">Preview the 8 legs, then confirm to place them.</p>
              <div class="field"><label class="ato-lab">NIFTY CENTER LEVEL</label><input id="depLevel" type="number" placeholder="${esc(d.placeholder_level || "NIFTY level")}" value="${esc(d.level || "")}" /></div>
              <div class="field"><label class="ato-lab">LOTS</label><input id="depLots" type="number" placeholder="Lots" value="${esc(d.lots || 1)}" /></div>
              <div class="row2">
                <button type="button" class="btn btn-green-outline" id="depPrev">PREVIEW LEGS</button>
                <button type="button" class="btn btn-green" id="depGo">CONFIRM DEPLOY</button>
              </div>
              <p class="sub" id="depMsg"></p>
              <div class="dep-out" id="depOut"><pre>Enter a NIFTY center level, then Preview.</pre></div>
            </div>
            <div class="card add-form dep-card-red">
              <h4 class="sec-title">Complete Batman</h4>
              <p class="sub dep-card-sub">Stop ATO and archive deployment. Positions stay on Zerodha.</p>
              <pre class="complete-pre" id="doneMsg">${esc(c.text || c.error || "")}</pre>
              <button type="button" class="btn btn-red" id="doneYes">YES — COMPLETE</button>
            </div>
          </div>`;
        $("depPrev").onclick = async () => {
          try {
            const r = await api("/api/deploy", { method: "POST", body: JSON.stringify({ preview: true, level: $("depLevel").value, lots: $("depLots").value }) });
            $("depOut").innerHTML = "<pre>" + esc(r.text || r.error) + "</pre>";
            $("depMsg").textContent = r.ok ? "Preview ready. Confirm only if the legs look right." : (r.error || "");
          } catch (err) {
            $("depOut").innerHTML = "<pre>" + esc(err.message) + "</pre>";
          }
        };
        $("depGo").onclick = async () => {
          if (!window.confirm("Place Batman 2.0 legs now?")) return;
          try {
            const r = await api("/api/deploy", { method: "POST", body: JSON.stringify({ confirm: true, level: $("depLevel").value, lots: $("depLots").value }) });
            $("depOut").innerHTML = "<pre>" + esc(r.text || r.error) + "</pre>";
            $("depMsg").textContent = r.ok ? "Deploy finished." : (r.error || "failed");
            toast(r.ok ? "Deploy finished" : r.error || "failed", !!r.ok);
          } catch (err) {
            $("depOut").innerHTML = "<pre>" + esc(err.message) + "</pre>";
            toast(err.message, false);
          }
        };
        $("doneYes").onclick = async () => {
          if (!window.confirm("Complete Batman now? ATO will stop and deployment will be archived.")) return;
          try {
            const dres = await api("/api/complete", {
              method: "POST",
              body: JSON.stringify({ confirm: true }),
            });
            $("doneMsg").textContent = dres.text || dres.error || "";
            toast(dres.ok ? "Batman complete" : (dres.error || "failed"), !!dres.ok);
          } catch (err) {
            $("doneMsg").textContent = err.message;
            toast(err.message, false);
          }
        };
      } else if (page === "token") {
        await renderTokenPage(view);
      }
      playViewIn(view);
    } catch (err) {
      view.innerHTML = `<p class="sub" style="color:var(--sell)">${esc(err.message)}</p>`;
    } finally {
      setBusy(false);
    }
  }

  function closeMenu() {
    const side = $("sideNav") || document.querySelector(".side");
    const scrim = $("navScrim");
    const btn = $("menuBtn");
    if (side) side.classList.remove("open");
    if (scrim) scrim.classList.remove("on");
    document.body.classList.remove("nav-open");
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function openMenu() {
    const side = $("sideNav") || document.querySelector(".side");
    const scrim = $("navScrim");
    const btn = $("menuBtn");
    if (side) side.classList.add("open");
    if (scrim) scrim.classList.add("on");
    document.body.classList.add("nav-open");
    if (btn) btn.setAttribute("aria-expanded", "true");
  }

  function toggleMenu() {
    const side = $("sideNav") || document.querySelector(".side");
    if (side && side.classList.contains("open")) closeMenu();
    else openMenu();
  }

  function bindGo(root) {
    root.querySelectorAll("[data-go]").forEach((el) => {
      el.addEventListener("click", () => go(el.dataset.go));
    });
  }

  function showDesk() {
    $("login").classList.add("hidden");
    $("desk").classList.remove("hidden");
    $("desk").classList.remove("desk-in");
    void $("desk").offsetWidth;
    $("desk").classList.add("desk-in");
    $("view").innerHTML = skeleton();
    go("home");
    startWs();
    if (!clockTimer) {
      tickClock();
      clockTimer = setInterval(tickClock, 1000);
    }
  }

  function playLockThenLogin() {
    $("desk").classList.add("hidden");
    const scene = $("lockScene");
    const logo = document.querySelector(".logo-hero");
    if (logo) logo.classList.remove("drop-in");
    scene.classList.remove("is-on");
    void scene.offsetWidth;
    scene.classList.add("is-on");
    scene.setAttribute("aria-hidden", "false");
    const wait = reduceMotion() ? 700 : 6200;
    setTimeout(() => {
      scene.classList.remove("is-on");
      scene.setAttribute("aria-hidden", "true");
      if (logo) {
        void logo.offsetWidth;
        logo.classList.add("drop-in");
      }
      $("login").classList.remove("hidden");
      $("pw").value = "";
      $("loginErr").textContent = "";
    }, wait);
  }

  function startWs() {
    try {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(proto + "://" + location.host + "/ws/state");
      ws.onmessage = (ev) => {
        try {
          applyChrome(JSON.parse(ev.data));
        } catch (_) {}
      };
    } catch (_) {}
  }

  document.querySelectorAll(".nav, .tabbar span").forEach((el) => {
    if (el.id === "logoutBtn") return;
    if (el.hasAttribute("data-menu")) {
      el.addEventListener("click", () => toggleMenu());
      return;
    }
    el.addEventListener("click", () => go(el.dataset.go));
  });
  const menuBtn = $("menuBtn");
  if (menuBtn) menuBtn.addEventListener("click", () => toggleMenu());
  const navScrim = $("navScrim");
  if (navScrim) navScrim.addEventListener("click", () => closeMenu());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeMenu();
  });


  async function flipRun(wantResume) {
    toggling = true;
    try {
      setBusy(true);
      const r = await api(wantResume ? "/api/resume" : "/api/pause", { method: "POST", body: "{}" });
      if (!r.ok) throw new Error(r.error || "failed");
      live.paused = !wantResume;
      applyChrome(live);
      if (wantResume) setGoNotice("WEAPONS HOT", "ok");
      else setGoNotice("WEAPONS COLD", "paused");
    } catch (err) {
      const run = $("runToggle");
      if (run) run.checked = !wantResume;
      applyChrome(live);
      toast(err.message, false);
    } finally {
      toggling = false;
      setBusy(false);
    }
  }

  async function flipHedge(on) {
    toggling = true;
    try {
      setBusy(true);
      const r = await api("/api/dyn-hedge", { method: "POST", body: JSON.stringify({ enabled: on }) });
      if (r.ok === false) throw new Error(r.error || "failed");
      live.dyn_hedge = on;
      applyChrome(live);
      toast(on ? "Hedge ON" : "Hedge OFF", true);
    } catch (err) {
      const h = $("hedgeToggle");
      if (h) h.checked = !on;
      applyChrome(live);
      toast(err.message, false);
    } finally {
      toggling = false;
      setBusy(false);
    }
  }

  $("runToggle").addEventListener("change", (e) => {
    flipRun(!!e.target.checked);
  });
  $("hedgeToggle").addEventListener("change", (e) => {
    flipHedge(!!e.target.checked);
  });

  $("logoutBtn").addEventListener("click", async () => {
    closeMenu();
    try {
      await api("/api/logout", { method: "POST", body: "{}" });
    } catch (_) {}
    playLockThenLogin();
  });

  $("loginBtn").addEventListener("click", async () => {
    toast("");
    $("loginErr").textContent = "";
    try {
      setBusy(true);
      await api("/api/login", {
        method: "POST",
        body: JSON.stringify({ password: $("pw").value }),
      });
      showDesk();
    } catch (e) {
      $("loginErr").textContent = e.message;
    } finally {
      setBusy(false);
    }
  });
  $("pw").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("loginBtn").click();
  });

  const viewEl = $("view");
  if (viewEl) {
    viewEl.addEventListener(
      "scroll",
      () => {
        const main = document.querySelector(".main");
        if (!main || reduceMotion()) return;
        main.style.setProperty("--paray", viewEl.scrollTop * 0.18 + "px");
      },
      { passive: true }
    );
  }

  api("/api/me")
    .then(() => showDesk())
    .catch(() => {});
})();

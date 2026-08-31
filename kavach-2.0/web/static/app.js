(() => {
  const $ = (id) => document.getElementById(id);
  let page = "home";
  let live = {};
  const pageHtmlCache = Object.create(null);
  const pageCacheMeta = Object.create(null);
  let navPerfTimer = 0;

  const PAGE_LABELS = {
    home: "Home",
    status: "Status",
    summary: "Summary",
    ato: "ATO",
    register: "Register",
    deploy: "Deploy",
    payoff: "Payoff",
    token: "Token",
  };

  function invalidatePageCache(keys) {
    if (keys == null) {
      for (const k of Object.keys(pageHtmlCache)) delete pageHtmlCache[k];
      for (const k of Object.keys(pageCacheMeta)) delete pageCacheMeta[k];
      return;
    }
    const list = Array.isArray(keys) ? keys : [keys];
    for (const k of list) {
      delete pageHtmlCache[k];
      delete pageCacheMeta[k];
    }
  }

  function invalidateHomeCache() {
    invalidatePageCache("home");
  }

  function savePageCache(key, html, meta) {
    pageHtmlCache[key] = html;
    if (meta !== undefined) pageCacheMeta[key] = meta;
  }

  function pageLabel(key) {
    return PAGE_LABELS[key] || String(key || "Page");
  }

  function showNavPerf(key, mode, ms) {
    const text = pageLabel(key) + " · " + mode + " · " + ms + "ms";
    const el = $("navPerf");
    if (el) {
      el.textContent = text;
      el.className = "nav-perf " + (mode === "cache" ? "ok" : "fetch");
      el.classList.remove("hidden");
    }
    toast(text, true);
    if (navPerfTimer) clearTimeout(navPerfTimer);
    navPerfTimer = setTimeout(() => {
      if (el) el.classList.add("hidden");
      navPerfTimer = 0;
    }, 3500);
  }

  function finishPageRender(key, view, meta, navT0) {
    savePageCache(key, view.innerHTML, meta);
    playViewIn(view);
    showNavPerf(key, "fetch", Math.max(1, Math.round(performance.now() - navT0)));
  }

  function restorePageFromCache(view) {
    const html = pageHtmlCache[page];
    if (!html) return false;
    const t0 = performance.now();
    view.innerHTML = html;
    wirePageHandlers(page, pageCacheMeta[page]);
    playViewIn(view);
    applyChrome(live);
    showNavPerf(page, "cache", Math.max(1, Math.round(performance.now() - t0)));
    return true;
  }

  function wirePageHandlers(key, meta) {
    if (key === "register" && meta && meta.register) wireRegisterHandlers(meta.register);
    else if (key === "ato") wireAtoMgrHandlers();
    else if (key === "deploy") wireDeployHandlers();
    else if (key === "payoff" && meta) wirePayoffChart(meta);
    else if (key === "token") wireTokenHandlers($("view"));
  }
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
    }, 6000);
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

  function wrapPageFrame(view) {
    if (!view) return;
    if (view.querySelector(":scope > .home-dash, :scope > .page-frame")) return;
    const head = view.querySelector(":scope > .page-head");
    if (!head) return;
    const frame = document.createElement("div");
    frame.className = "page-frame";
    while (head.nextSibling) frame.appendChild(head.nextSibling);
    if (!frame.childNodes.length) return;
    view.appendChild(frame);
  }

  function playViewIn(view) {
    wrapPageFrame(view);
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

  function isMobileUi() {
    return window.matchMedia("(max-width: 900px)").matches;
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


  /* ---- ATO surety audio (always on; unlock on first gesture) ---- */
  const ATO_AUDIO = {
    down: "/static/audio/kavach_down_final.wav",
    up: "/static/audio/kavach_up_final.wav",
    welcome: "/static/audio/welcome_final.wav",
    register: "/static/audio/register_arm_final.wav",
    complete: "/static/audio/complete_final.wav",
    engage: "/static/audio/ato_engage_final.wav",
    exit: "/static/audio/ato_exit_final.wav",
  };
  let _audioUnlocked = false;
  let _lastArmed = null;
  let _lastBuyFillToken = null;
  let _lastSellFillToken = null;
  let _welcomePlayed = false;
  let _suppressReadinessAudioUntil = 0;
  const PROTECT_BOOK_BLOCK_REASONS = new Set([
    "pe_protect_in_book",
    "ce_protect_in_book",
  ]);

  function unlockAudio() {
    if (_audioUnlocked) return;
    _audioUnlocked = true;
    try {
      const a = new Audio(ATO_AUDIO.up);
      a.volume = 0.01;
      a.play().then(() => { a.pause(); a.currentTime = 0; }).catch(() => {});
    } catch (_) {}
  }

  function playAtoClip(kind) {
    const src = ATO_AUDIO[kind];
    if (!src) return;
    try {
      const a = new Audio(src);
      a.volume = 1;
      a.play().catch(() => {});
    } catch (_) {}
  }

  ["pointerdown", "keydown", "touchstart"].forEach((ev) => {
    window.addEventListener(ev, unlockAudio, { once: true, capture: true });
  });

  function feedAgeClass(age) {
    if (age == null || Number.isNaN(Number(age))) return "feed-bad";
    const n = Number(age);
    if (n <= 3) return "feed-ok";
    if (n <= 10) return "feed-amber";
    return "feed-bad";
  }

  function paintAtoBanner(s) {
    const el = $("atoBanner");
    if (!el) return;
    const ar = (s && s.ato_readiness) || {};
    const armed = !!ar.armed;
    if (armed) {
      el.classList.add("hidden");
      el.textContent = "";
      return;
    }
    const labels = ar.reason_labels || {};
    const hard = ar.hard_blocked_reasons || ar.blocked_reasons || [];
    const top = hard.slice(0, 2).map((r) => labels[r] || r).filter(Boolean);
    const line = top.join(" · ") || (ar.summary_line || "ATO BLOCKED");
    let action = "Check Datafeedbot service / Feeder cache.";
    if (hard.indexOf("deployment_not_confirmed") >= 0) action = "Register / Arm Kavach first.";
    else if (hard.indexOf("algo_paused") >= 0) action = "Tap RESUME when the feed is healthy.";
    else if (hard.indexOf("datafeedbot_down") >= 0 || hard.indexOf("kavach2_down") >= 0) {
      action = "Check VPS: datafeedbot.service / batman-kavach2.service.";
    }
    el.classList.remove("hidden");
    el.innerHTML = `<div class="ato-banner-line">${esc(line)}</div><div class="ato-banner-actions">${esc(action)}</div>`;
  }

  function _hardBlockReasons(s) {
    const ar = (s && s.ato_readiness) || {};
    return ar.hard_blocked_reasons || ar.blocked_reasons || [];
  }

  function _protectBookOnlyBlock(hard) {
    if (!hard || !hard.length) return false;
    return hard.every((r) => PROTECT_BOOK_BLOCK_REASONS.has(r));
  }

  /** Trade clips (#6/#7) win over readiness (#4/#5) on the same tick. */
  function onAtoDeskAudioEdges(s) {
    if (!s) return;
    const ar = (s && s.ato_readiness) || {};
    const buy = String(s.ato_buy_fill_token || "");
    const sell = String(s.ato_sell_fill_token || "");
    const now = Date.now();
    const initTokens = _lastBuyFillToken === null && _lastSellFillToken === null;
    const buyNew = !initTokens && buy && buy !== _lastBuyFillToken;
    const sellNew = !initTokens && sell && sell !== _lastSellFillToken;

    if (initTokens) {
      _lastBuyFillToken = buy;
      _lastSellFillToken = sell;
      if (typeof ar.armed === "boolean") _lastArmed = ar.armed;
      return;
    }

    if (buyNew) {
      playAtoClip("engage");
      _suppressReadinessAudioUntil = now + 6000;
    }
    if (sellNew) {
      playAtoClip("exit");
      _suppressReadinessAudioUntil = now + 6000;
    }

    if (typeof ar.armed === "boolean" && _lastArmed !== null) {
      const hard = _hardBlockReasons(s);
      const readinessSuppressed = now < _suppressReadinessAudioUntil;

      if (_lastArmed === true && ar.armed === false) {
        const incidentBlock = !buyNew && !_protectBookOnlyBlock(hard) && !readinessSuppressed;
        if (incidentBlock) playAtoClip("down");
      }
      if (_lastArmed === false && ar.armed === true) {
        const incidentRecovery = !sellNew && !readinessSuppressed;
        if (incidentRecovery) playAtoClip("up");
      }
      _lastArmed = ar.armed;
    }

    _lastBuyFillToken = buy;
    _lastSellFillToken = sell;
  }


  function fmtExitLevel(v) {
    if (v == null || v === "") return "";
    const n = Number(v);
    return Number.isFinite(n) ? String(n) : "";
  }

  function paintPnlExitChrome(s) {
    const pe = (s && s.pnl_exit) || {};
    const safeOn = !!pe.safe_on;
    const tpOn = !!pe.tp_on;
    const safeIn = $("safeExitOn");
    const tpIn = $("tpExitOn");
    const safeLvl = $("safeExitLevel");
    const tpLvl = $("tpExitLevel");
    const _mobExit = isMobileUi();
    paintToggle(
      safeIn,
      $("safeExitLbl"),
      safeOn,
      _mobExit ? "ON" : "STOP LOSS ON",
      _mobExit ? "OFF" : "STOP LOSS OFF"
    );
    paintToggle(
      tpIn,
      $("tpExitLbl"),
      tpOn,
      _mobExit ? "ON" : "TARGET ON",
      _mobExit ? "OFF" : "TARGET OFF"
    );
    const slName = document.querySelector(".top-exit-box.exit-sl .tog-name");
    const tpName = document.querySelector(".top-exit-box.exit-tp .tog-name");
    if (slName) slName.textContent = _mobExit ? "SL" : "STOP LOSS";
    if (tpName) tpName.textContent = _mobExit ? "TGT" : "TARGET";
    if (safeLvl && document.activeElement !== safeLvl) {
      safeLvl.value = fmtExitLevel(pe.safe_level_rs);
    }
    if (tpLvl && document.activeElement !== tpLvl) {
      tpLvl.value = fmtExitLevel(pe.tp_level_rs);
    }
    // Reuse ATO banner strip for fire notice
    const ban = $("atoBanner");
    if (ban && pe.firing) {
      ban.classList.remove("hidden");
      ban.className = "ato-banner bad";
      ban.textContent = "FLATTENING POSITIONS…";
    } else if (ban && pe.last_reason && !((s && s.ato_readiness && !s.ato_readiness.armed))) {
      // only show exit banner if readiness banner not already taking priority — paintAtoBanner may overwrite
    }
    if (pe.last_reason) {
      const label = pe.last_reason === "take_profit" ? "TARGET FIRED" : "STOP LOSS FIRED";
      const pnl = pe.last_pnl != null ? fmtPnl(pe.last_pnl) : "—";
      // stash for paintAtoBanner companion
      live._pnlExitBanner = label + " · PnL " + pnl;
    } else {
      live._pnlExitBanner = "";
    }
  }

  async function postPnlExit(path, on, levelEl) {
    const raw = levelEl ? levelEl.value : "";
    const body = { on: !!on, level_rs: raw === "" ? null : Number(raw) };
    try {
      setBusy(true);
      const r = await api(path, { method: "POST", body: JSON.stringify(body) });
      toast(r.text || (r.ok ? "Saved" : (r.error || "Failed")), !!r.ok);
      if (!r.ok) throw new Error(r.error || "failed");
      if (r.pnl_exit) live.pnl_exit = r.pnl_exit;
      applyChrome(live);
      await render();
    } catch (e) {
      toast(String(e.message || e), false);
      applyChrome(live);
    } finally {
      setBusy(false);
    }
  }

  function bindPnlExitControls() {
    const safeIn = $("safeExitOn");
    const tpIn = $("tpExitOn");
    const safeLvl = $("safeExitLevel");
    const tpLvl = $("tpExitLevel");
    if (safeIn && !safeIn.dataset.bound) {
      safeIn.dataset.bound = "1";
      safeIn.addEventListener("change", () => postPnlExit("/api/safe-exit", !!safeIn.checked, safeLvl));
    }
    if (tpIn && !tpIn.dataset.bound) {
      tpIn.dataset.bound = "1";
      tpIn.addEventListener("change", () => postPnlExit("/api/take-profit", !!tpIn.checked, tpLvl));
    }
    const armSave = (el, path, tog) => {
      if (!el || el.dataset.bound) return;
      el.dataset.bound = "1";
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          postPnlExit(path, !!(tog && tog.checked), el);
        }
      });
      el.addEventListener("change", () => {
        if (tog && tog.checked) postPnlExit(path, true, el);
      });
    };
    armSave(safeLvl, "/api/safe-exit", safeIn);
    armSave(tpLvl, "/api/take-profit", tpIn);
  }

  function applyChrome(s) {
    live = s || live;
    const paused = !!live.paused;
    const resumed = !paused;
    const hedgeOn = !!live.dyn_hedge;
    const nifty = $("niftyTop");
    if (nifty) {
      const ar = live.ato_readiness || {};
      const feed = ar.feed || {};
      const px = (feed.ltp != null && feed.ltp !== "")
        ? Number(feed.ltp).toLocaleString("en-IN", { maximumFractionDigits: 0 })
        : (live.nifty_ltp != null && live.nifty_ltp !== ""
          ? Number(live.nifty_ltp).toLocaleString("en-IN", { maximumFractionDigits: 0 })
          : (String(live.nifty || "").trim() || "—"));
      const age = feed.age_s != null ? Math.round(Number(feed.age_s)) : null;
      const ageTxt = age == null ? "?" : String(age) + "s";
      const src = String(feed.source || "—").toUpperCase();
      const col = String(feed.collector || "feeder");
      nifty.textContent = "NIFTY " + px + " · " + ageTxt + " · " + src;
      nifty.className = "";
      const stack = $("spotStack");
      if (stack) stack.className = "chip chip-spot chip-spot-stack " + feedAgeClass(age);
    }
    paintAtoBanner(live);
    const banEl = $("atoBanner");
    if (banEl && live._pnlExitBanner && banEl.classList.contains("hidden")) {
      banEl.classList.remove("hidden");
      banEl.className = "ato-banner bad";
      banEl.textContent = live._pnlExitBanner;
    }
    onAtoDeskAudioEdges(live);
    const clock = $("clock");
    if (clock) clock.className = "";
    const pnlEl = $("statPnl");
    if (pnlEl) {
      const v = live.day_pnl;
      pnlEl.textContent = fmtPnl(v);
      const base = pnlEl.classList.contains("home-pnl-strip-val")
        ? "home-pnl-strip-val"
        : (pnlEl.classList.contains("home-pnl-big") ? "home-pnl-big" : "");
      const tone = (v == null || v === "") ? "" : clsPnl(v);
      pnlEl.className = [base, tone].filter(Boolean).join(" ");
    }
    paintToggle(
      $("runToggle"),
      $("runLbl"),
      resumed,
      isMobileUi() ? "KAVACH ON" : "KAVACH RESUMED",
      isMobileUi() ? "KAVACH OFF" : "KAVACH PAUSED"
    );
    paintToggle($("hedgeToggle"), $("hedgeLbl"), hedgeOn, "HEDGE ON", "HEDGE OFF");
    paintPnlExitChrome(live);
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
      <header class="page-head"><h3>AUTHORISATION</h3></header>
      <div class="row2 tok-grid">
        <div class="card tok-card tok-card-green">
          <h3 class="tok-title"><img class="tok-logo" src="/static/dhan.png" alt="" />DHAN TOKEN</h3>
          <div class="tok-meta">
            <div class="kv"><span>Status</span><b class="${d.present ? "buy" : "sell"}">${esc(healthLabel)}</b></div>
            <div class="kv"><span>Last4</span><b>${d.last4 ? "····" + esc(d.last4) : "—"}</b></div>
            <div class="kv"><span>Saved</span><b>${esc(d.saved_at || "—")}</b></div>
            <div class="kv"><span>Expires</span><b>${esc(d.jwt_exp || d.expires_at || "—")}</b></div>
            <div class="kv"><span>Age / Left</span><b>${d.age_hours == null || !d.present ? "—" : d.age_hours + "h / " + (d.expires_in_hours == null ? "—" : d.expires_in_hours + "h")}</b></div>
            <div class="kv"><span>TOTP Auto-Renew</span><b>${totp.configured ? (totp.auto_renew ? "ON" : "OFF") : "Not configured"}</b></div>
            <div class="kv"><span>TOTP Secret Due</span><b>${totp.days_left == null ? "—" : fmtDays(totp.days_left)}</b></div>
            <div class="kv"><span>Last TOTP Refresh</span><b>${esc(totp.last_refresh || "never")}</b></div>
          </div>
          ${totp.last_error ? `<p class="sub tok-err">${esc(totp.last_error)}</p>` : ""}
          <label class="muted" for="jwtBox">Paste Dhan Token</label>
          <textarea id="jwtBox" class="tokbox" rows="3" autocomplete="off" spellcheck="false" placeholder="Paste DHAN Token Here"></textarea>
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
          <textarea id="zBox" class="tokbox" rows="3" autocomplete="off" spellcheck="false" placeholder="Paste ZERODHA Token Here"></textarea>
          <button type="button" class="btn btn-red" id="tokZ">SAVE ZERODHA TOKEN</button>
        </div>
      </div>
      <p class="sub" id="tokMsg"></p>`;
    wrapPageFrame(view);
  }

  async function renderTokenPage(view, msgText) {
    const t = await api("/api/token/status");
    paintTokenPage(view, t);
    if (msgText && $("tokMsg")) $("tokMsg").textContent = msgText;
    wireTokenHandlers(view);
  }

  
  function drawPayoffChart(svg, points, spot, opts) {
    if (!svg) return;
    const pts = Array.isArray(points) ? points : [];
    const o = opts || {};
    const step = Number(o.step) || 50;
    const W = 1000, H = 420;
    const pad = { l: 64, r: 24, t: 28, b: 52 };
    const innerW = W - pad.l - pad.r;
    const innerH = H - pad.t - pad.b;
    if (!pts.length) {
      svg.innerHTML = `<text x="500" y="210" text-anchor="middle" fill="#7A7494" font-size="18">No payoff points</text>`;
      return;
    }
    const xs = pts.map((p) => Number(p.x));
    const ys = pts.map((p) => Number(p.y));
    let xmin = Math.min(...xs), xmax = Math.max(...xs);
    let ymin = Math.min(...ys, 0), ymax = Math.max(...ys, 0);
    if (xmin === xmax) { xmin -= step; xmax += step; }
    if (ymin === ymax) { ymin -= 100; ymax += 100; }
    // Keep spot visually centered: domain already ATM±10; if spot exists, shift domain symmetrically around spot.
    if (spot != null && Number(spot) > 0) {
      const half = (xmax - xmin) / 2;
      const s = Number(spot);
      xmin = s - half;
      xmax = s + half;
    }
    const xScale = (x) => pad.l + ((x - xmin) / (xmax - xmin)) * innerW;
    const yScale = (y) => pad.t + ((ymax - y) / (ymax - ymin)) * innerH;
    const zeroY = yScale(0);

    // Split payoff into profit (green) / loss (red); interpolate at zero crossings.
    const greenSegs = [];
    const redSegs = [];
    let seg = [];
    let segSign = 0;
    const flushSeg = () => {
      if (seg.length >= 2) {
        const d = seg.map((c, i) => `${i ? "L" : "M"}${c[0].toFixed(1)},${c[1].toFixed(1)}`).join(" ");
        if (segSign >= 0) greenSegs.push(d);
        else redSegs.push(d);
      }
      seg = [];
    };
    for (let i = 0; i < pts.length; i++) {
      const x = Number(pts[i].x);
      const y = Number(pts[i].y);
      const px = xScale(x);
      const py = yScale(y);
      const sign = y > 0 ? 1 : y < 0 ? -1 : 0;
      if (i === 0) {
        seg = [[px, py]];
        segSign = sign || 1;
        continue;
      }
      const y0 = Number(pts[i - 1].y);
      const px0 = xScale(Number(pts[i - 1].x));
      if ((y0 > 0 && y < 0) || (y0 < 0 && y > 0)) {
        const t = Math.abs(y0) / (Math.abs(y0) + Math.abs(y));
        const zx = px0 + t * (px - px0);
        const zy = zeroY;
        seg.push([zx, zy]);
        flushSeg();
        seg = [[zx, zy], [px, py]];
        segSign = sign;
      } else {
        if (sign && segSign && sign !== segSign) {
          flushSeg();
          seg = [[px0, yScale(y0)], [px, py]];
          segSign = sign;
        } else {
          if (sign) segSign = sign;
          seg.push([px, py]);
        }
      }
    }
    flushSeg();

    const pathAll = pts.map((p, i) => `${i ? "L" : "M"}${xScale(p.x).toFixed(1)},${yScale(p.y).toFixed(1)}`).join(" ");
    const area = `${pathAll} L${xScale(pts[pts.length - 1].x).toFixed(1)},${zeroY.toFixed(1)} L${xScale(pts[0].x).toFixed(1)},${zeroY.toFixed(1)} Z`;
    const greenPaths = greenSegs.map((d) => `<path d="${d}" fill="none" stroke="#1ED760" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" />`).join("");
    const redPaths = redSegs.map((d) => `<path d="${d}" fill="none" stroke="#FF3B5C" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" />`).join("");

    let grid = "";
    const atm = o.atm != null ? Number(o.atm) : null;
    const strikeStart = Math.ceil(xmin / step) * step;
    const strikes = [];
    for (let x = strikeStart; x <= xmax + 0.01; x += step) strikes.push(Math.round(x));
    strikes.forEach((x, idx) => {
      const px = xScale(x);
      const isAtm = atm != null && Math.abs(x - atm) < 0.1;
      const showLabel = isAtm || idx === 0 || idx === strikes.length - 1 || idx % 2 === 0;
      grid += `<line x1="${px}" y1="${pad.t}" x2="${px}" y2="${H - pad.b}" stroke="${isAtm ? "rgba(43,179,192,0.35)" : "rgba(124,106,232,0.10)"}" />`;
      if (showLabel) {
        grid += `<text x="${px}" y="${H - 16}" text-anchor="middle" fill="${isAtm ? "#2BB3C0" : "#7A7494"}" font-size="${isAtm ? 13 : 11}" font-weight="${isAtm ? 700 : 500}">${x}</text>`;
      }
    });
    for (let i = 0; i <= 4; i++) {
      const y = ymin + ((ymax - ymin) * i) / 4;
      const py = yScale(y);
      grid += `<line x1="${pad.l}" y1="${py}" x2="${W - pad.r}" y2="${py}" stroke="rgba(124,106,232,0.10)" />`;
      grid += `<text x="${pad.l - 10}" y="${py + 4}" text-anchor="end" fill="#7A7494" font-size="13">${Math.round(y)}</text>`;
    }

    let peakLbl = "";
    const iMax = ys.indexOf(Math.max(...ys));
    const iMin = ys.indexOf(Math.min(...ys));
    if (iMax >= 0 && ys[iMax] > 0) {
      const mx = xScale(xs[iMax]), my = yScale(ys[iMax]);
      peakLbl += `<text x="${mx}" y="${Math.max(pad.t + 14, my - 10)}" text-anchor="middle" fill="#1ED760" font-size="12" font-weight="800">MAX +${Math.round(ys[iMax])}</text>`;
    }
    if (iMin >= 0 && ys[iMin] < 0) {
      const mx = xScale(xs[iMin]), my = yScale(ys[iMin]);
      peakLbl += `<text x="${mx}" y="${Math.min(H - pad.b - 6, my + 18)}" text-anchor="middle" fill="#FF3B5C" font-size="12" font-weight="800">MAX −${Math.round(Math.abs(ys[iMin]))}</text>`;
    }

    let spotLine = "";
    if (spot != null && Number(spot) > 0) {
      const s = Number(spot);
      const sx = xScale(s);
      let spotY = null;
      for (let i = 1; i < pts.length; i++) {
        const x0 = Number(pts[i - 1].x), x1 = Number(pts[i].x);
        if ((s >= x0 && s <= x1) || (s >= x1 && s <= x0)) {
          const t = x1 === x0 ? 0 : (s - x0) / (x1 - x0);
          spotY = Number(pts[i - 1].y) + t * (Number(pts[i].y) - Number(pts[i - 1].y));
          break;
        }
      }
      if (spotY == null) spotY = 0;
      const sy = yScale(spotY);
      const pnlCol = spotY >= 0 ? "#1ED760" : "#FF3B5C";
      const pnlTxt = (spotY >= 0 ? "+" : "") + Math.round(spotY);
      spotLine = `<line x1="${sx}" y1="${pad.t}" x2="${sx}" y2="${H - pad.b}" stroke="#7C6AE8" stroke-width="2.5" />
        <circle cx="${sx}" cy="${sy}" r="6" fill="#7C6AE8" stroke="#fff" stroke-width="1.5" />
        <text x="${sx}" y="${pad.t + 18}" text-anchor="middle" fill="#7C6AE8" font-size="14" font-weight="800">SPOT ${s.toFixed(0)}</text>
        <text x="${sx + 10}" y="${sy - 10}" text-anchor="start" fill="${pnlCol}" font-size="13" font-weight="800">PnL ${pnlTxt}</text>`;
    }

    const uid = "pf" + Math.floor(Math.random() * 1e9);
    svg.innerHTML = `
      <defs>
        <clipPath id="${uid}up"><rect x="${pad.l}" y="${pad.t}" width="${innerW}" height="${Math.max(0, zeroY - pad.t)}" /></clipPath>
        <clipPath id="${uid}dn"><rect x="${pad.l}" y="${zeroY}" width="${innerW}" height="${Math.max(0, H - pad.b - zeroY)}" /></clipPath>
      </defs>
      <rect x="0" y="0" width="${W}" height="${H}" fill="transparent" />
      ${grid}
      <line x1="${pad.l}" y1="${zeroY}" x2="${W - pad.r}" y2="${zeroY}" stroke="#2A2450" stroke-width="1.5" opacity="0.45" />
      <path d="${area}" fill="rgba(30,215,96,0.14)" clip-path="url(#${uid}up)" />
      <path d="${area}" fill="rgba(255,59,92,0.12)" clip-path="url(#${uid}dn)" />
      ${greenPaths}
      ${redPaths}
      ${peakLbl}
      ${spotLine}
    `;
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


  function wireAtoMgrHandlers() {
    if ($("bufSave")) {
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
        if (r.ok) invalidatePageCache(["home", "ato"]);
      };
    }
    if ($("pollSave")) {
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
    }
  }

  function wireDeployHandlers() {
    if ($("depPrev")) {
      $("depPrev").onclick = async () => {
        try {
          const r = await api("/api/deploy", { method: "POST", body: JSON.stringify({ preview: true, level: $("depLevel").value, lots: $("depLots").value }) });
          $("depOut").textContent = r.text || r.error;
          $("depMsg").textContent = r.ok ? "Preview ready. Confirm only if the legs look right." : (r.error || "");
          savePageCache("deploy", $("view").innerHTML, pageCacheMeta.deploy);
        } catch (err) {
          $("depOut").textContent = err.message;
        }
      };
    }
    if ($("depGo")) {
      $("depGo").onclick = async () => {
        if (!window.confirm("Place Batman 2.0 legs now?")) return;
        try {
          const r = await api("/api/deploy", { method: "POST", body: JSON.stringify({ confirm: true, level: $("depLevel").value, lots: $("depLots").value }) });
          $("depOut").textContent = r.text || r.error;
          $("depMsg").textContent = r.ok ? "Deploy finished." : (r.error || "failed");
          toast(r.ok ? "Deploy finished" : r.error || "failed", !!r.ok);
          if (r.ok) invalidatePageCache();
        } catch (err) {
          $("depOut").textContent = err.message;
          toast(err.message, false);
        }
      };
    }
    if ($("doneYes")) {
      $("doneYes").onclick = async () => {
        if (!window.confirm("Complete Batman now? ATO will stop and deployment will be archived.")) return;
        try {
          const dres = await api("/api/complete", {
            method: "POST",
            body: JSON.stringify({ confirm: true }),
          });
          $("doneMsg").textContent = dres.text || dres.error || "";
          toast(dres.ok ? "Batman complete" : (dres.error || "failed"), !!dres.ok);
          if (dres.ok) {
            playAtoClip("complete");
            invalidatePageCache();
          }
        } catch (err) {
          $("doneMsg").textContent = err.message;
          toast(err.message, false);
        }
      };
    }
  }

  function wirePayoffChart(meta) {
    drawPayoffChart($("payoffSvg"), meta.points || [], meta.spot, {
      atm: meta.atm,
      step: meta.step || 50,
    });
  }

  function wireTokenHandlers(view) {
    if (!view) return;
    async function tokenCall(fn) {
      const msg = $("tokMsg");
      try {
        setBusy(true);
        const r = await fn();
        const text = r.text || r.error || (r.ok ? "Done" : "failed");
        toast(text, !!r.ok);
        if (r.ok) {
          invalidatePageCache("token");
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
    if ($("tokRef")) $("tokRef").onclick = () => tokenCall(() => api("/api/token/refresh", { method: "POST", body: "{}" }));
    if ($("tokOff")) $("tokOff").onclick = () => tokenCall(() => api("/api/token/deactivate", { method: "POST", body: "{}" }));
    if ($("tokStat")) $("tokStat").onclick = () => renderTokenPage(view, "Token status refreshed.");
    if ($("tokPaste")) {
      $("tokPaste").onclick = () => tokenCall(() => api("/api/token/dhan-jwt", {
        method: "POST",
        body: JSON.stringify({ token: $("jwtBox").value }),
      }));
    }
    if ($("tokZ")) {
      $("tokZ").onclick = () => tokenCall(() => api("/api/token/zerodha", {
        method: "POST",
        body: JSON.stringify({ token: $("zBox").value }),
      }));
    }
  }

  function wireRegisterHandlers(d) {
    const step = Number(d.ato_step || 50);

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
      const el = $(id);
      if (el) el.onchange = sync;
    });
    sync();

    if ($("regGo")) {
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
          if (r.ok) {
            playAtoClip("register");
            invalidatePageCache();
          }
        } catch (err) {
          $("regMsg").textContent = err.message;
          toast(err.message, false);
        }
      };
    }
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
      <header class="page-head"><h3>REGISTER BATMAN</h3></header>
      ${note}${armed}
      <div class="card add-form reg-form">
        <div class="reg-top-grid">
          ${qBlock(1, "Select Mode", `
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
            <h4 class="sec-title">CE SIDE</h4>
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
              </div>`)}
            ${qBlock(15, "ATO Entry Level", `<input id="regCeEntry" type="number" placeholder="${esc(d.entry_placeholder || "NIFTY level")}" />`)}
            ${qBlock(16, "ATO Exit Level (Retrace)", `<input id="regCeExit" type="number" placeholder="${esc(d.exit_placeholder || "NIFTY level")}" />`)}
          </section>
          <section class="reg-side reg-side-pe dep-card-red" id="regPeBlock">
            <h4 class="sec-title">PE SIDE</h4>
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
              </div>`)}
            ${qBlock(8, "ATO Entry Level", `<input id="regPeEntry" type="number" placeholder="${esc(d.entry_placeholder || "NIFTY level")}" />`)}
            ${qBlock(9, "ATO Exit Level (Retrace)", `<input id="regPeExit" type="number" placeholder="${esc(d.exit_placeholder || "NIFTY level")}" />`)}
          </section>
        </div>
        <div class="reg-top-grid">
          ${qBlock(17, "ATO manage CE/PE", `
            <select id="regAtoMon">
              <option value="both" ${d.ato_mon === "both" ? "selected" : ""}>Manage both CE and PE</option>
              <option value="ce" ${d.ato_mon === "ce" ? "selected" : ""}>Manage CE only</option>
              <option value="pe" ${d.ato_mon === "pe" ? "selected" : ""}>Manage PE only</option>
            </select>`)}
          ${qBlock(18, "Confirm Deployment", `<button type="button" class="btn gold" id="regGo">REGISTER — ARM KAVACH</button>`)}
        </div>
        <p class="sub" id="regMsg"></p>
      </div>`;
    wrapPageFrame(view);
    wireRegisterHandlers(d);
  }

  async function render() {
    const view = $("view");
    if (!view) return;
    try {
      if (restorePageFromCache(view)) return;
      const navT0 = performance.now();
      let pageMeta = null;
      setBusy(true);
      if (page === "home") {
        const [s, a, b, sum, tok] = await Promise.all([
          api("/api/state"),
          api("/api/ato-status"),
          api("/api/buffer"),
          api("/api/trade-summary"),
          api("/api/token/status"),
        ]);
        applyChrome(s);
        const pnlCls = s.day_pnl == null || s.day_pnl === "" ? "" : clsPnl(s.day_pnl);
        const mode = String(s.order_mode || "paper").toUpperCase();
        const armed = !!s.deployment;
        const dhan = (tok && tok.dhan) || {};
        const kite = (tok && tok.zerodha) || {};
        const dhanLbl = dhan.present ? cap(dhan.status || dhan.health_class || "OK") : "Missing";
        const kiteLbl = kite.present ? "Set" : "Missing";
        const open = (sum && sum.open) || [];
        const openHtml = open.length
          ? open.map((leg) => `
              <div class="kv"><span>${esc(leg.side)} ATO</span><b>${esc(leg.symbol || "—")}</b></div>
              <div class="kv"><span>Strike</span><b>${esc(leg.protect_strike || "—")}</b></div>
              <div class="kv"><span>Status</span><b class="buy">OPEN</b></div>`).join("")
          : `<p class="sub home-empty">No open ATO protect leg.</p>`;
        const lvl = (v) => (v == null || v === "" ? "—" : esc(v));
        view.innerHTML = `
          <header class="page-head"><h3>HOME</h3></header>
          <div class="home-dash">
            <div class="home-strip">
              <div class="home-pnl-strip" title="Day PnL">
                <span class="home-pnl-strip-lab">DAY PNL</span>
                <span id="statPnl" class="home-pnl-strip-val ${pnlCls}">${esc(fmtPnl(s.day_pnl))}</span>
              </div>
              <div class="home-strip-group home-strip-ops">
                <span class="home-chip ${s.paused ? "bad" : "ok"}">${s.paused ? "KAVACH PAUSED" : "KAVACH RESUMED"}</span>
                <span class="home-chip ${s.dyn_hedge ? "ok" : "bad"}">${s.dyn_hedge ? "HEDGE ON" : "HEDGE OFF"}</span>
                <span class="home-chip ${s.broker ? "ok" : "bad"}">${s.broker ? "BROKER OK" : "BROKER OFF"}</span>
                <span class="home-chip ${armed ? "ok" : "bad"}">${armed ? "ARMED" : "NOT ARMED"}</span>
                <span class="home-chip ${(s.ato_readiness && s.ato_readiness.armed) ? "ok" : "bad"}">${(s.ato_readiness && s.ato_readiness.armed) ? "ATO ARMED" : "ATO BLOCKED"}</span>
              </div>
              <div class="home-strip-group home-strip-ato">
                <span class="home-chip ${s.ce_ato ? "ok" : ""}">CE ATO ${s.ce_ato ? "ACTIVE" : "IDLE"}</span>
                <span class="home-chip ${s.pe_ato ? "ok" : ""}">PE ATO ${s.pe_ato ? "ACTIVE" : "IDLE"}</span>
              </div>
              <div class="home-strip-group home-strip-tok">
                <span class="home-chip ${dhan.present ? "ok" : "bad"}">DHAN · ${esc(dhanLbl)}</span>
                <span class="home-chip ${kite.present ? "ok" : "bad"}">KITE · ${esc(kiteLbl)}</span>
              </div>
            </div>

            <div class="home-body-grid">
              <div class="home-left-stack">
                <div class="card home-card dep-card-blue home-open-card">
                  <h4 class="sec-title">OPEN ATO</h4>
                  <div class="home-kv-wrap">${openHtml}</div>
                  <div class="kv"><span>Manage</span><b>${esc(a.manage || "—")}</b></div>
                  <div class="kv"><span>CE protect</span><b>${esc(a.ce_protect || s.ce_symbol || "N/A")}</b></div>
                  <div class="kv"><span>PE protect</span><b>${esc(a.pe_protect || s.pe_symbol || "N/A")}</b></div>
                </div>
                <div class="card home-card dep-card-green">
                  <h4 class="sec-title">ATO LEVELS</h4>
                  <div class="kv"><span>CE Entry</span><b>${lvl(b.ce_entry)}</b></div>
                  <div class="kv"><span>CE Exit</span><b>${lvl(b.ce_retrace)}</b></div>
                  <div class="kv"><span>PE Entry</span><b>${lvl(b.pe_entry)}</b></div>
                  <div class="kv"><span>PE Exit</span><b>${lvl(b.pe_retrace)}</b></div>
                  <div class="kv"><span>NIFTY</span><b>${lvl(b.nifty_ltp != null ? Number(b.nifty_ltp).toFixed(2) : s.nifty)}</b></div>
                </div>
                <div class="card home-card ato-ready-card">
                  <h4 class="sec-title">ATO READINESS</h4>
                  <div class="kv"><span>Status</span><b class="${(s.ato_readiness && s.ato_readiness.armed) ? "ok" : "bad"}">${esc((s.ato_readiness && s.ato_readiness.summary_line) || "—")}</b></div>
                  <div class="kv"><span>Feed age</span><b>${esc((s.ato_readiness && s.ato_readiness.feed && s.ato_readiness.feed.age_s != null) ? (Math.round(s.ato_readiness.feed.age_s) + "s") : "—")}</b></div>
                  <div class="kv"><span>Checked</span><b>${esc((s.ato_readiness && s.ato_readiness.checked_at) || "—")}</b></div>
                </div>
              </div>

              <div class="card hist-wrap pos-card home-pos-card">
                <div class="home-pos-inner">
                  <div class="home-pos-side" aria-label="Positions">POSITIONS</div>
                  <div class="home-pos-table-wrap">
                    <table class="hist-table pos-table"><thead><tr>
                      <th>Symbol</th><th>Qty</th><th>Avg</th><th>LTP</th><th>PnL</th>
                    </tr></thead><tbody id="posBody">${posRowsHtml(s.positions)}</tbody></table>
                  </div>
                </div>
              </div>
            </div>
          </div>`;
        finishPageRender("home", view, null, navT0);
        return;
      }
      if (page === "status") {
        const stTxt = (await api("/api/status")).text;
        let ready = {};
        try { ready = await api("/api/ato-readiness"); } catch (_) { ready = {}; }
        const hard = (ready.hard_blocked_reasons || []).map((r) => (ready.reason_labels && ready.reason_labels[r]) || r);
        const svc = ready.services || {};
        const feed = ready.feed || {};
        view.innerHTML = `<header class="page-head"><h3>KAVACH STATUS</h3></header>
          <div class="card ato-ready-card">
            <h4 class="sec-title">ATO READINESS</h4>
            <div class="kv"><span>Summary</span><b class="${ready.armed ? "ok" : "bad"}">${esc(ready.summary_line || "—")}</b></div>
            <div class="kv"><span>Checked</span><b>${esc(ready.checked_at || "—")}</b></div>
            <div class="kv"><span>Feed</span><b>${esc((feed.ltp != null ? feed.ltp : "—") + " · age " + (feed.age_s != null ? Math.round(feed.age_s) + "s" : "?") + " · " + (feed.source || "") + " · " + (feed.collector || ""))}</b></div>
            <div class="kv"><span>Datafeedbot</span><b class="${svc.datafeedbot_active ? "ok" : "bad"}">${svc.datafeedbot_active ? "active" : "down"}</b></div>
            <div class="kv"><span>Kavach2</span><b class="${svc.kavach2_active ? "ok" : "bad"}">${svc.kavach2_active ? "active" : "down"}</b></div>
            <div class="kv"><span>Block reasons</span><b>${esc(hard.length ? hard.join("; ") : "none")}</b></div>
          </div>` + pre(stTxt);

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
          <header class="page-head"><h3>ATO SUMMARY</h3></header>
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
        const pollOpts = (p.poll_options || [0, 1, 2, 3, 4, 5, 10, 15])
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
          <header class="page-head"><h3>ATO MANAGER</h3></header>
          <div class="ato-mgr">
            <div class="card add-form ato-mgr-buf dep-card-green">
              <h4 class="sec-title">BUFFER MANAGER</h4>
              <div class="ato-buf-fields">
                <div class="field"><label class="ato-lab" for="ce_entry">CE ENTRY</label><input id="ce_entry" type="number" inputmode="decimal" autocomplete="off" name="ato-ce-entry" placeholder="${esc(b.ce_entry_placeholder || "Nifty Level")}" value="${esc(b.ce_entry)}" /></div>
                <div class="field"><label class="ato-lab" for="ce_retrace">CE EXIT</label><input id="ce_retrace" type="number" inputmode="decimal" autocomplete="off" name="ato-ce-exit" placeholder="${esc(b.ce_retrace_placeholder || "Nifty Level")}" value="${esc(b.ce_retrace)}" /></div>
                <div class="field"><label class="ato-lab" for="pe_entry">PE ENTRY</label><input id="pe_entry" type="number" inputmode="decimal" autocomplete="off" name="ato-pe-entry" placeholder="${esc(b.pe_entry_placeholder || "Nifty Level")}" value="${esc(b.pe_entry)}" /></div>
                <div class="field"><label class="ato-lab" for="pe_retrace">PE EXIT</label><input id="pe_retrace" type="number" inputmode="decimal" autocomplete="off" name="ato-pe-exit" placeholder="${esc(b.pe_retrace_placeholder || "Nifty Level")}" value="${esc(b.pe_retrace)}" /></div>
              </div>
              <button type="button" class="btn btn-green" id="bufSave">SAVE</button>
              <p class="sub" id="bufMsg"></p>
            </div>
            <div class="card ato-mgr-status dep-card-blue">
              <h4 class="sec-title">ATO STATUS</h4>
              <div class="ato-status-wrap">${statusHtml}</div>
              <h4 class="sec-title ato-open-title">OPEN ATO</h4>
              <div class="ato-open-wrap">${openHtml}</div>
            </div>
            <div class="card add-form ato-mgr-poll dep-card-red">
              <h4 class="sec-title">POLL INTERVAL</h4>
              <div class="field"><select id="pollSel">${pollOpts}</select></div>
              <button type="button" class="btn btn-red" id="pollSave">SAVE</button>
              <p class="sub" id="pollMsg"></p>
            </div>
          </div>`;
        wireAtoMgrHandlers();
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
        finishPageRender("register", view, { register: d }, navT0);
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
          <header class="page-head"><h3>DEPLOY / COMPLETE</h3></header>
          <div class="dep-complete">
            <div class="card add-form dep-card-green">
              <h4 class="sec-title">DEPLOY BATMAN 2.0</h4>
              <p class="sub dep-card-sub">Preview the legs below, then confirm to place them.</p>
              <div class="field"><label class="ato-lab">NIFTY CENTER LEVEL</label><input id="depLevel" type="number" placeholder="${esc(d.placeholder_level || "NIFTY level")}" value="${esc(d.level || "")}" /></div>
              <div class="field"><label class="ato-lab">LOTS</label><input id="depLots" type="number" placeholder="Lots" value="${esc(d.lots || 1)}" /></div>
              <p class="sub dep-hint">Enter a NIFTY center level, then Preview.</p>
              <div class="row2">
                <button type="button" class="btn btn-green-outline" id="depPrev">PREVIEW LEGS</button>
                <button type="button" class="btn btn-green" id="depGo">CONFIRM DEPLOY</button>
              </div>
              <p class="sub" id="depMsg"></p>
              <div class="dep-out" id="depOut"></div>
            </div>
            <div class="card add-form dep-card-red">
              <h4 class="sec-title">COMPLETE BATMAN</h4>
              <p class="sub dep-card-sub">End this deployment safely</p>
              <div class="complete-pre" id="doneMsg">${esc(c.text || c.error || "")}</div>
              <button type="button" class="btn btn-red" id="doneYes">CONFIRM COMPLETE</button>
            </div>
          </div>`;
        wireDeployHandlers();
      } else if (page === "payoff") {
        const d = await api("/api/payoff");
        const legs = d.legs || [];
        const pts = d.points || [];
        const spot = d.spot;
        const be = (d.breakevens || []).map((x) => Number(x).toFixed(0)).join(" · ") || "—";
        const maxP = d.max_profit == null ? "—" : fmtPnl(d.max_profit);
        const maxL = d.max_loss == null ? "—" : fmtPnl(d.max_loss);
        const atm = d.atm;
        view.innerHTML = `
          <header class="page-head payoff-head"><h3>PAYOFF</h3></header>
          <div class="payoff-page">
            <div class="payoff-stats">
              <div class="card home-chip-card"><kbd>SPOT</kbd><b>${spot == null ? "—" : Number(spot).toFixed(2)}</b></div>
              <div class="card home-chip-card"><kbd>ATM</kbd><b>${atm == null ? "—" : Number(atm).toFixed(0)}</b></div>
              <div class="card home-chip-card"><kbd>MAX PROFIT*</kbd><b class="buy">${esc(maxP)}</b></div>
              <div class="card home-chip-card"><kbd>MAX LOSS*</kbd><b class="sell">${esc(maxL)}</b></div>
              <div class="card home-chip-card payoff-be"><kbd>BREAKEVENS*</kbd><b>${esc(be)}</b></div>
            </div>
            <div class="card payoff-chart-card">
              <div class="payoff-chart-top">
                <h4 class="sec-title">EXPIRY PAYOFF</h4>
                <span class="sub payoff-sub">ATM ± 10 strikes · spot at center</span>
              </div>
              <div class="payoff-chart-wrap">
                <svg id="payoffSvg" class="payoff-svg" viewBox="0 0 1000 420" preserveAspectRatio="none" role="img" aria-label="Payoff chart"></svg>
              </div>
            </div>
          </div>`;
        pageMeta = { points: pts, spot: spot, atm: atm, step: d.step || 50 };
        wirePayoffChart(pageMeta);

      } else if (page === "token") {
        await renderTokenPage(view);
      }
      if (page === "ato" || page === "buffer") page = "ato";
      if (page === "status" || page === "summary" || page === "ato" || page === "deploy" || page === "payoff" || page === "token") {
        finishPageRender(page, view, pageMeta, navT0);
      } else {
        playViewIn(view);
      }
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
  bindPnlExitControls();

  $("logoutBtn").addEventListener("click", async () => {
    closeMenu();
    invalidatePageCache();
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
      unlockAudio();
      if (!_welcomePlayed) { _welcomePlayed = true; playAtoClip("welcome"); }
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

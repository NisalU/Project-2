/* Signal Bot dashboard client — realtime WebSocket edition.
   Live trade ticks move the last candle and the big price with smooth
   animation; analysis snapshots refresh overlays, breakdown and signals. */
(function () {
  "use strict";

  var C = {
    bg: "#131a22", grid: "#1f2a37", text: "#8b98a5",
    green: "#22c55e", red: "#ef4444", amber: "#f59e0b",
    ema7: "#eab308", ema25: "#38bdf8", ema99: "#a3a3a3",
  };

  var symbolEl = document.getElementById("symbol");
  var intervalEl = document.getElementById("interval");
  var liveDot = document.getElementById("live-dot");
  var latencyEl = document.getElementById("latency");
  var priceEl = document.getElementById("price");
  var tapeEl = document.getElementById("tape");
  var toastsEl = document.getElementById("toasts");

  // ---------- charts ----------
  function baseOptions(el) {
    return {
      width: el.clientWidth,
      height: el.clientHeight,
      layout: { background: { color: "transparent" }, textColor: C.text, fontFamily: "'JetBrains Mono', monospace", fontSize: 10 },
      grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
      rightPriceScale: { borderColor: C.grid },
      timeScale: { borderColor: C.grid, timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    };
  }

  var chartEl = document.getElementById("chart");
  var chart = LightweightCharts.createChart(chartEl, baseOptions(chartEl));
  var candleSeries = chart.addCandlestickSeries({
    upColor: C.green, downColor: C.red, borderVisible: false,
    wickUpColor: C.green, wickDownColor: C.red,
  });
  var volumeSeries = chart.addHistogramSeries({
    priceFormat: { type: "volume" }, priceScaleId: "vol",
    priceLineVisible: false, lastValueVisible: false,
  });
  chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  var ema7Series = chart.addLineSeries({ color: C.ema7, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
  var ema25Series = chart.addLineSeries({ color: C.ema25, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
  var ema99Series = chart.addLineSeries({ color: C.ema99, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });

  var cvdEl = document.getElementById("cvd-chart");
  var cvdChart = LightweightCharts.createChart(cvdEl, baseOptions(cvdEl));
  var cvdSeries = cvdChart.addAreaSeries({
    lineColor: C.ema25, topColor: "rgba(56,189,248,0.25)", bottomColor: "rgba(56,189,248,0.02)",
    lineWidth: 2, priceLineVisible: false,
  });

  window.addEventListener("resize", function () {
    chart.applyOptions({ width: chartEl.clientWidth, height: chartEl.clientHeight });
    cvdChart.applyOptions({ width: cvdEl.clientWidth, height: cvdEl.clientHeight });
  });

  var priceLines = [];
  var trendSeries = [];
  var firstLoad = true;
  var lastCandle = null;     // live candle being extended by ticks
  var cvdBase = 0;           // CVD value up to (not including) the live candle

  function volBar(c) {
    return {
      time: c.time, value: c.volume,
      color: c.close >= c.open ? "rgba(34,197,94,0.35)" : "rgba(239,68,68,0.35)",
    };
  }

  function clearOverlays() {
    priceLines.forEach(function (pl) { candleSeries.removePriceLine(pl); });
    priceLines = [];
    trendSeries.forEach(function (s) { chart.removeSeries(s); });
    trendSeries = [];
  }

  function addPriceLine(price, color, title, style) {
    priceLines.push(candleSeries.createPriceLine({
      price: price, color: color, lineWidth: 1,
      lineStyle: style === undefined ? 2 : style,
      axisLabelVisible: true, title: title,
    }));
  }

  // ---------- smooth price animation ----------
  var shownPrice = null, targetPrice = null, priceDigits = 2;
  function digitsFor(p) {
    if (p >= 1000) return 2;
    if (p >= 1) return 4;
    return 6;
  }
  function fmt(n, digits) {
    if (n === null || n === undefined) return "\u2014";
    return Number(n).toLocaleString("en-US", {
      minimumFractionDigits: digits === undefined ? 2 : digits,
      maximumFractionDigits: digits === undefined ? 2 : digits,
    });
  }
  function rafLoop() {
    if (targetPrice !== null) {
      if (shownPrice === null) shownPrice = targetPrice;
      var diff = targetPrice - shownPrice;
      if (Math.abs(diff) > Math.abs(targetPrice) * 1e-7) {
        shownPrice += diff * 0.25; // ease toward target
      } else {
        shownPrice = targetPrice;
      }
      priceEl.textContent = fmt(shownPrice, priceDigits);
    }
    requestAnimationFrame(rafLoop);
  }
  requestAnimationFrame(rafLoop);

  var lastFlashPrice = null;
  function flashPrice(p) {
    if (lastFlashPrice !== null && p !== lastFlashPrice) {
      var cls = p > lastFlashPrice ? "flash-up" : "flash-down";
      priceEl.classList.remove("flash-up", "flash-down");
      void priceEl.offsetWidth; // restart animation
      priceEl.classList.add(cls);
    }
    lastFlashPrice = p;
  }

  // ---------- live tick handling ----------
  function onTick(t) {
    priceDigits = digitsFor(t.price);
    targetPrice = t.price;
    flashPrice(t.price);

    tapeEl.textContent = (t.sell ? "\u25bc " : "\u25b2 ") + fmt(t.qty, 4) + " @ " + fmt(t.price, priceDigits);
    tapeEl.className = "tape " + (t.sell ? "down" : "up");

    // extend the live candle between kline pushes
    if (lastCandle && t.time / 1000 >= lastCandle.time) {
      lastCandle.close = t.price;
      if (t.price > lastCandle.high) lastCandle.high = t.price;
      if (t.price < lastCandle.low) lastCandle.low = t.price;
      candleSeries.update({
        time: lastCandle.time, open: lastCandle.open,
        high: lastCandle.high, low: lastCandle.low, close: lastCandle.close,
      });
    }
  }

  function onKline(m) {
    var c = m.candle;
    if (lastCandle && c.time > lastCandle.time) {
      // previous candle closed; CVD advances by its delta
      cvdBase += lastCandle.delta || 0;
    }
    lastCandle = c;
    candleSeries.update({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close });
    volumeSeries.update(volBar(c));
    cvdSeries.update({ time: c.time, value: cvdBase + (c.delta || 0) });
    priceDigits = digitsFor(c.close);
    targetPrice = c.close;
    flashPrice(c.close);
  }

  // ---------- snapshot rendering ----------
  function renderChart(d) {
    var ov = d.overlays || {};
    candleSeries.setData(d.candles.map(function (c) {
      return { time: c.time, open: c.open, high: c.high, low: c.low, close: c.close };
    }));
    volumeSeries.setData(d.candles.map(volBar));
    ema7Series.setData(ov.ema7 || []);
    ema25Series.setData(ov.ema25 || []);
    ema99Series.setData(ov.ema99 || []);
    cvdSeries.setData(ov.cvd || []);

    lastCandle = d.candles.length ? Object.assign({}, d.candles[d.candles.length - 1]) : null;
    var cvd = ov.cvd || [];
    cvdBase = cvd.length >= 2 ? cvd[cvd.length - 2].value : 0;

    clearOverlays();

    (ov.support || []).forEach(function (lv) { addPriceLine(lv.price, C.green, "S x" + lv.touches); });
    (ov.resistance || []).forEach(function (lv) { addPriceLine(lv.price, C.red, "R x" + lv.touches); });

    if (ov.fibonacci) {
      ov.fibonacci.levels.forEach(function (lv) {
        addPriceLine(lv.price, C.amber, "fib " + lv.ratio, 3);
      });
    }
    if (ov.volume_profile) {
      addPriceLine(ov.volume_profile.poc, "#c084fc", "POC", 0);
      addPriceLine(ov.volume_profile.vah, "#8b98a5", "VAH", 3);
      addPriceLine(ov.volume_profile.val, "#8b98a5", "VAL", 3);
    }
    (ov.order_blocks || []).forEach(function (ob) {
      var color = ob.type === "bullish" ? C.green : C.red;
      addPriceLine(ob.top, color, "OB " + (ob.type === "bullish" ? "demand" : "supply"), 4);
      addPriceLine(ob.bottom, color, "", 4);
    });
    (ov.fvgs || []).forEach(function (f) {
      addPriceLine(f.mid, f.type === "bullish" ? C.green : C.red, "FVG", 1);
    });

    (ov.trendlines || []).forEach(function (tl) {
      var s = chart.addLineSeries({
        color: tl.type === "support" ? C.green : C.red,
        lineWidth: 1, lineStyle: 0, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      s.setData([
        { time: tl.start.time, value: tl.start.price },
        { time: tl.end.time, value: tl.end.price },
      ]);
      trendSeries.push(s);
    });

    var markers = [];
    (ov.sweeps || []).forEach(function (sw) {
      markers.push({
        time: sw.time,
        position: sw.type === "bullish" ? "belowBar" : "aboveBar",
        color: sw.type === "bullish" ? C.green : C.red,
        shape: sw.type === "bullish" ? "arrowUp" : "arrowDown",
        text: "SWEEP",
      });
    });
    markers.sort(function (a, b) { return a.time - b.time; });
    candleSeries.setMarkers(markers);

    if (firstLoad) {
      chart.timeScale().fitContent();
      cvdChart.timeScale().fitContent();
      firstLoad = false;
    }
  }

  var shownScore = 0;
  function renderVerdict(d) {
    priceDigits = digitsFor(d.price);
    if (targetPrice === null) targetPrice = d.price;
    var chg = document.getElementById("chg");
    if (d.ticker) {
      var pct = d.ticker.change_pct;
      chg.textContent = (pct >= 0 ? "+" : "") + pct.toFixed(2) + "% 24h";
      chg.className = "chg " + (pct >= 0 ? "up" : "down");
    }
    var v = document.getElementById("verdict");
    if (d.direction === "LONG") {
      v.className = "verdict-badge long";
      v.textContent = (d.strength ? d.strength + " " : "") + "LONG SIGNAL";
    } else if (d.direction === "SHORT") {
      v.className = "verdict-badge short";
      v.textContent = (d.strength ? d.strength + " " : "") + "SHORT SIGNAL";
    } else {
      v.className = "verdict-badge neutral";
      v.textContent = "NEUTRAL \u00b7 waiting for confluence";
    }
    document.getElementById("gauge-needle").style.left = (50 + d.composite / 2) + "%";

    // animate the score counter
    var scoreEl = document.getElementById("gauge-score");
    var from = shownScore, to = d.composite, start = performance.now();
    (function step(now) {
      var k = Math.min((now - start) / 600, 1);
      var val = from + (to - from) * (1 - Math.pow(1 - k, 3));
      scoreEl.textContent = "score " + val.toFixed(1) + " / \u00b1" + d.threshold + " to fire";
      if (k < 1) requestAnimationFrame(step); else shownScore = to;
    })(start);

    var planCard = document.getElementById("plan-card");
    if (d.plan) {
      planCard.classList.remove("hidden");
      document.getElementById("plan-entry").textContent = fmt(d.plan.entry, priceDigits);
      document.getElementById("plan-stop").textContent = fmt(d.plan.stop, priceDigits);
      document.getElementById("plan-tp1").textContent = fmt(d.plan.tp1, priceDigits);
      document.getElementById("plan-tp2").textContent = fmt(d.plan.tp2, priceDigits);
    } else {
      planCard.classList.add("hidden");
    }
  }

  function renderBreakdown(d) {
    var host = document.getElementById("breakdown");
    var build = host.childElementCount !== d.breakdown.length;
    if (build) host.innerHTML = "";
    d.breakdown.forEach(function (b, i) {
      var pct = Math.min(Math.abs(b.score) * 50, 50);
      var cls = b.contribution > 0.5 ? "pos" : b.contribution < -0.5 ? "neg" : "zero";
      var row;
      if (build) {
        row = document.createElement("div");
        row.className = "bd-row";
        row.innerHTML =
          '<div class="bd-top"><span class="bd-name"></span><span class="bd-val"></span></div>' +
          '<div class="bd-bar"><div class="bd-mid"></div><div class="bd-fill"></div></div>' +
          '<div class="bd-why"></div>';
        host.appendChild(row);
      } else {
        row = host.children[i];
      }
      row.querySelector(".bd-name").innerHTML = b.label + ' <span class="bd-why">(w' + b.weight + ")</span>";
      var valEl = row.querySelector(".bd-val");
      valEl.className = "bd-val " + cls;
      valEl.textContent = (b.contribution > 0 ? "+" : "") + b.contribution;
      var fill = row.querySelector(".bd-fill");
      fill.className = "bd-fill " + (b.score >= 0 ? "pos" : "neg");
      fill.style.width = pct + "%";
      row.children[2].textContent = b.reasons.join(" \u00b7 ");
    });
  }

  function renderFundamentals(d) {
    var f = (d.overlays || {}).fundamentals;
    var card = document.getElementById("fund-card");
    if (!f) { card.classList.add("hidden"); return; }
    card.classList.remove("hidden");
    var fr = f.funding_rate * 100;
    var frEl = document.getElementById("f-funding");
    frEl.textContent = fr.toFixed(4) + "%";
    frEl.className = "v " + (fr > 0.03 ? "red" : fr < 0 ? "green" : "");
    var oiEl = document.getElementById("f-oi");
    oiEl.textContent = (f.oi_change_pct >= 0 ? "+" : "") + f.oi_change_pct.toFixed(1) + "%";
    document.getElementById("f-ls").textContent = f.long_short_ratio.toFixed(2);
    document.getElementById("f-mark").textContent = fmt(f.mark_price, priceDigits);
  }

  function signalCard(s) {
    var el = document.createElement("div");
    el.className = "sig " + s.direction.toLowerCase();
    var when = new Date(s.time * 1000).toLocaleString();
    el.innerHTML =
      '<div class="sig-top"><span class="sig-dir">' + s.direction +
      (s.strength ? " \u00b7 " + s.strength : "") + "</span>" +
      '<span class="sig-meta">' + s.symbol + " " + s.interval + " \u00b7 score " + s.score + "</span></div>" +
      '<div class="sig-meta">' + when + " \u00b7 @ " + fmt(s.price, digitsFor(s.price)) + "</div>" +
      (s.reasons && s.reasons.length ? '<div class="sig-reasons">' + s.reasons.join(" \u00b7 ") + "</div>" : "");
    return el;
  }

  function renderSignals(list) {
    var host = document.getElementById("signals");
    if (!list.length) return;
    host.innerHTML = "";
    list.forEach(function (s) { host.appendChild(signalCard(s)); });
  }

  function pushSignal(s) {
    var host = document.getElementById("signals");
    var empty = host.querySelector(".empty");
    if (empty) empty.remove();
    var el = signalCard(s);
    el.classList.add("sig-new");
    host.insertBefore(el, host.firstChild);
    toast(s);
  }

  function toast(s) {
    var t = document.createElement("div");
    t.className = "toast " + s.direction.toLowerCase();
    t.innerHTML =
      '<span class="toast-dir">' + s.direction + (s.strength ? " \u00b7 " + s.strength : "") + "</span>" +
      '<span class="toast-meta">' + s.symbol + " " + s.interval + " @ " + fmt(s.price, digitsFor(s.price)) + "</span>";
    toastsEl.appendChild(t);
    setTimeout(function () {
      t.classList.add("toast-out");
      setTimeout(function () { t.remove(); }, 400);
    }, 6000);
  }

  function renderSnapshot(d) {
    renderChart(d);
    renderVerdict(d);
    renderBreakdown(d);
    renderFundamentals(d);
  }

  // ---------- selectors ----------
  function fillSelect(el, values, selected) {
    if (el.childElementCount) return;
    values.forEach(function (v) {
      var o = document.createElement("option");
      o.value = v; o.textContent = v;
      if (v === selected) o.selected = true;
      el.appendChild(o);
    });
  }

  // ---------- WebSocket ----------
  var ws = null, reconnectDelay = 1000, pingTimer = null;

  function subscribe() {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "subscribe", symbol: symbolEl.value, interval: intervalEl.value }));
    }
  }

  function connect() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    liveDot.className = "dot";
    ws = new WebSocket(proto + "//" + location.host + "/ws");

    ws.onopen = function () {
      reconnectDelay = 1000;
      liveDot.className = "dot live";
      if (symbolEl.value) subscribe();
      clearInterval(pingTimer);
      pingTimer = setInterval(function () {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping", t: performance.now() }));
        }
      }, 5000);
    };

    ws.onmessage = function (ev) {
      var m;
      try { m = JSON.parse(ev.data); } catch (e) { return; }
      switch (m.type) {
        case "config":
          fillSelect(symbolEl, m.symbols, m.default_symbol);
          fillSelect(intervalEl, m.intervals, m.default_interval);
          break;
        case "snapshot":
          if (m.data.symbol === symbolEl.value && m.data.interval === intervalEl.value) {
            renderSnapshot(m.data);
          }
          break;
        case "tick":
          if (m.symbol === symbolEl.value) onTick(m);
          break;
        case "kline":
          if (m.symbol === symbolEl.value && m.interval === intervalEl.value) onKline(m);
          break;
        case "signal":
          pushSignal(m.data);
          break;
        case "signals":
          renderSignals(m.data);
          break;
        case "pong":
          latencyEl.textContent = Math.max(1, Math.round(performance.now() - m.t)) + "ms";
          break;
        case "error":
          liveDot.className = "dot err";
          break;
      }
    };

    ws.onclose = function () {
      liveDot.className = "dot err";
      clearInterval(pingTimer);
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 15000);
    };
    ws.onerror = function () { ws.close(); };
  }

  function reset() {
    firstLoad = true;
    lastCandle = null;
    lastFlashPrice = null;
    shownPrice = null;
    targetPrice = null;
    priceEl.textContent = "\u2014";
    tapeEl.textContent = "";
    subscribe();
  }
  symbolEl.addEventListener("change", reset);
  intervalEl.addEventListener("change", reset);

  connect();
})();

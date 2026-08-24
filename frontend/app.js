(() => {
  const $ = (sel) => document.querySelector(sel);

  // South Indian style chart: signs sit at fixed grid positions (col, row)
  // in a 4x4 grid with the center 2x2 block left open. Index 0 = Aries.
  const SIGN_GRID_POS = [
    [1, 0], [2, 0], [3, 0], // Aries, Taurus, Gemini
    [3, 1], // Cancer
    [3, 2], // Leo
    [3, 3], [2, 3], [1, 3], [0, 3], // Virgo, Libra, Scorpio, Sagittarius
    [0, 2], // Capricorn
    [0, 1], // Aquarius
    [0, 0], // Pisces
  ];
  const SIGN_SHORT = [
    "白羊", "金牛", "双子", "巨蟹", "狮子", "处女",
    "天秤", "天蝎", "射手", "摩羯", "水瓶", "双鱼",
  ];

  const form = $("#birth-form");
  const cityInput = $("#city");
  const searchBtn = $("#search-btn");
  const cityResults = $("#city-results");
  const citySelected = $("#city-selected");
  const submitBtn = $("#submit-btn");

  const loadingEl = $("#loading");
  const errorEl = $("#error-box");
  const resultEl = $("#result-section");

  let selectedCity = null; // {lat, lon, timezone, display_name}
  let searchTimer = null;

  async function searchCity() {
    const q = cityInput.value.trim();
    if (!q) return;
    cityResults.innerHTML = "<li>搜索中...</li>";
    cityResults.classList.remove("hidden");
    try {
      const resp = await fetch(`/api/geocode?q=${encodeURIComponent(q)}`);
      if (!resp.ok) throw new Error((await resp.json()).detail || "搜索失败");
      const results = await resp.json();
      if (!results.length) {
        cityResults.innerHTML = "<li>未找到匹配的城市，请尝试更换关键词</li>";
        return;
      }
      cityResults.innerHTML = "";
      for (const r of results) {
        const li = document.createElement("li");
        li.textContent = `${r.display_name}${r.timezone ? "  (" + r.timezone + ")" : ""}`;
        li.addEventListener("click", () => selectCity(r));
        cityResults.appendChild(li);
      }
    } catch (err) {
      cityResults.innerHTML = `<li>${err.message}</li>`;
    }
  }

  function selectCity(r) {
    selectedCity = r;
    cityResults.classList.add("hidden");
    citySelected.textContent = `已选择: ${r.display_name} (纬度 ${r.lat.toFixed(
      2
    )}, 经度 ${r.lon.toFixed(2)}, 时区 ${r.timezone})`;
    updateSubmitState();
  }

  // Native <input type="date">/<input type="time"> render using the
  // browser/OS's locale (could be MM/DD/YYYY + 12h, DD/MM/YYYY + 24h, etc.
  // — not something the page can control). To guarantee everyone sees the
  // same 日/月/年 order and an unambiguous 24-hour time regardless of device
  // locale, build the picker out of plain <select> elements instead.
  const DAY_SELECT = $("#birth_day");
  const MONTH_SELECT = $("#birth_month");
  const YEAR_SELECT = $("#birth_year");
  const HOUR_SELECT = $("#birth_hour");
  const MINUTE_SELECT = $("#birth_minute");

  function fillSelect(el, options, placeholder) {
    el.innerHTML = "";
    const ph = document.createElement("option");
    ph.value = "";
    ph.textContent = placeholder;
    el.appendChild(ph);
    for (const { value, label } of options) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      el.appendChild(opt);
    }
  }

  function pad2(n) {
    return String(n).padStart(2, "0");
  }

  function initDateTimeSelects() {
    fillSelect(
      DAY_SELECT,
      Array.from({ length: 31 }, (_, i) => ({ value: pad2(i + 1), label: `${i + 1}日` })),
      "日"
    );
    fillSelect(
      MONTH_SELECT,
      Array.from({ length: 12 }, (_, i) => ({ value: pad2(i + 1), label: `${i + 1}月` })),
      "月"
    );
    const currentYear = new Date().getFullYear();
    fillSelect(
      YEAR_SELECT,
      Array.from({ length: currentYear - 1899 }, (_, i) => {
        const y = currentYear - i;
        return { value: String(y), label: `${y}年` };
      }),
      "年"
    );
    fillSelect(
      HOUR_SELECT,
      Array.from({ length: 24 }, (_, i) => ({ value: pad2(i), label: pad2(i) })),
      "时"
    );
    fillSelect(
      MINUTE_SELECT,
      Array.from({ length: 60 }, (_, i) => ({ value: pad2(i), label: pad2(i) })),
      "分"
    );
  }
  initDateTimeSelects();

  function getBirthDateValue() {
    const d = DAY_SELECT.value, m = MONTH_SELECT.value, y = YEAR_SELECT.value;
    return d && m && y ? `${y}-${m}-${d}` : "";
  }

  function getBirthTimeValue() {
    const h = HOUR_SELECT.value, min = MINUTE_SELECT.value;
    return h !== "" && min !== "" ? `${h}:${min}` : "";
  }

  function updateSubmitState() {
    const dateOk = getBirthDateValue();
    const timeOk = getBirthTimeValue();
    submitBtn.disabled = !(dateOk && timeOk && selectedCity);
  }

  searchBtn.addEventListener("click", searchCity);
  cityInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      searchCity();
    }
  });
  cityInput.addEventListener("input", () => {
    selectedCity = null;
    citySelected.textContent = "";
    updateSubmitState();
    clearTimeout(searchTimer);
  });
  for (const el of [DAY_SELECT, MONTH_SELECT, YEAR_SELECT, HOUR_SELECT, MINUTE_SELECT]) {
    el.addEventListener("change", updateSubmitState);
  }

  document.addEventListener("click", (e) => {
    if (
      !cityResults.contains(e.target) &&
      e.target !== cityInput &&
      e.target !== searchBtn
    ) {
      cityResults.classList.add("hidden");
    }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!selectedCity) return;

    errorEl.classList.add("hidden");
    resultEl.classList.add("hidden");
    loadingEl.classList.remove("hidden");
    submitBtn.disabled = true;

    const payload = {
      name: $("#name").value.trim() || null,
      birth_date: getBirthDateValue(),
      birth_time: getBirthTimeValue(),
      birth_place: selectedCity.display_name,
      lat: selectedCity.lat,
      lon: selectedCity.lon,
      timezone: selectedCity.timezone,
      focus: $("#focus").value.trim() || null,
    };

    try {
      const resp = await fetch("/api/chart", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "计算失败");
      renderResult(data);
    } catch (err) {
      errorEl.textContent = `出错了：${err.message}`;
      errorEl.classList.remove("hidden");
    } finally {
      loadingEl.classList.add("hidden");
      submitBtn.disabled = false;
    }
  });

  function renderResult(data) {
    const bannerWrap = $("#minor-banner-wrap");
    bannerWrap.innerHTML = "";
    if (data.is_minor) {
      const div = document.createElement("div");
      div.className = "minor-banner";
      div.textContent = `命主当前年龄约 ${data.age} 岁，为未成年人。以下解读已切换为面向家长的视角与语气。`;
      bannerWrap.appendChild(div);
    }

    renderTagline(data.interpretation.tagline, data.is_minor);
    renderChartWheel(data);
    renderChartTable(data);
    renderDasha(data.dasha);
    renderTabs(data.interpretation, data.is_minor);
    prepareShareCard(data);

    resultEl.classList.remove("hidden");
    resultEl.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderTagline(tagline, isMinor) {
    const wrap = $("#tagline-wrap");
    if (!tagline) {
      wrap.innerHTML = "";
      return;
    }
    wrap.innerHTML = `<p class="tagline-quote">${isMinor ? "" : "“"}${tagline}${
      isMinor ? "" : "”"
    }</p>`;
  }

  function renderChartWheel(data) {
    const ascSignIndex = data.ascendant.sign_index;
    // group points by sign index, ascendant included as its own labeled point
    const bySign = Array.from({ length: 12 }, () => []);
    bySign[ascSignIndex].push({ label: "Asc", isAsc: true });
    for (const p of data.planets) {
      bySign[p.sign_index].push({ label: p.name_zh, isAsc: false });
    }

    const CELL = 96;
    const PAD = 6;
    const SIZE = CELL * 4 + PAD * 2;
    const LINE_H = 15;
    let cells = "";
    for (let signIdx = 0; signIdx < 12; signIdx++) {
      const [col, row] = SIGN_GRID_POS[signIdx];
      const x = PAD + col * CELL;
      const y = PAD + row * CELL;
      const house = ((signIdx - ascSignIndex + 12) % 12) + 1;
      const isAscCell = signIdx === ascSignIndex;
      const points = bySign[signIdx];

      cells += `<rect x="${x}" y="${y}" width="${CELL}" height="${CELL}"
        class="wheel-cell${isAscCell ? " wheel-cell-asc" : ""}" />`;
      if (isAscCell) {
        cells += `<line x1="${x}" y1="${y}" x2="${x + CELL}" y2="${y + CELL}" class="wheel-asc-mark" />`;
      }
      cells += `<text x="${x + 6}" y="${y + 14}" class="wheel-sign-label">${SIGN_SHORT[signIdx]}</text>`;
      cells += `<text x="${x + CELL - 6}" y="${y + 14}" text-anchor="end" class="wheel-house-label">${house}</text>`;

      // vertically center the stack of point labels within the cell
      const startY = y + CELL / 2 - ((points.length - 1) * LINE_H) / 2 + 5;
      points.forEach((pt, i) => {
        cells += `<text x="${x + CELL / 2}" y="${startY + i * LINE_H}"
          text-anchor="middle" class="wheel-point-label${pt.isAsc ? " wheel-point-asc" : ""}">${pt.label}</text>`;
      });
    }

    // center block spans the middle 2x2 area (columns/rows 1-2)
    const centerX = PAD + CELL * 1;
    const centerY = PAD + CELL * 1;
    const centerW = CELL * 2;
    const centerLabel = `${data.ascendant.sign} ${data.ascendant.sign_degree}`;

    const svg = `<svg viewBox="0 0 ${SIZE} ${SIZE}" class="wheel-svg" role="img" aria-label="本命盘星位图">
      ${cells}
      <rect x="${centerX}" y="${centerY}" width="${centerW}" height="${centerW}" class="wheel-center" />
      <text x="${centerX + centerW / 2}" y="${centerY + centerW / 2 - 6}" text-anchor="middle" class="wheel-center-title">上升 Lagna</text>
      <text x="${centerX + centerW / 2}" y="${centerY + centerW / 2 + 16}" text-anchor="middle" class="wheel-center-sub">${centerLabel}</text>
    </svg>`;

    $("#chart-wheel").innerHTML = svg;
  }

  function renderChartTable(data) {
    const rows = [
      { name_zh: "上升 Lagna", name: "Ascendant", sign: data.ascendant.sign, sign_degree: data.ascendant.sign_degree, house: 1, nakshatra: data.ascendant.nakshatra, pada: data.ascendant.pada },
      ...data.planets,
    ];
    let html = `<table class="chart-table"><thead><tr>
      <th>星体</th><th>星座</th><th>度数</th><th>宫位</th><th>星宿</th><th>分度</th>
    </tr></thead><tbody>`;
    for (const p of rows) {
      html += `<tr>
        <td>${p.name_zh}</td>
        <td>${p.sign}</td>
        <td>${p.sign_degree}</td>
        <td>第${p.house}宫</td>
        <td>${p.nakshatra}</td>
        <td>${p.pada}</td>
      </tr>`;
    }
    html += "</tbody></table>";
    $("#chart-table").innerHTML = html;
  }

  function renderDasha(dasha) {
    const maha = dasha.mahadasha;
    const antar = dasha.antardasha;
    let html = `<div class="dasha-current">
      <div class="dasha-box">
        <div class="label">当前大运 Mahadasha</div>
        <div class="value">${maha.lord_zh}</div>
        <div class="range">${maha.start} 至 ${maha.end}</div>
      </div>
      <div class="dasha-box">
        <div class="label">当前小运 Antardasha</div>
        <div class="value">${antar.lord_zh}</div>
        <div class="range">${antar.start} 至 ${antar.end}</div>
      </div>
    </div>
    <p class="upcoming">未来大运序列：${dasha.upcoming_mahadashas
      .map((p) => `${p.lord_zh} (${p.start} 起)`)
      .join(" → ")}</p>`;
    $("#dasha-info").innerHTML = html;
  }

  function renderTabs(interpretation, isMinor) {
    const tabs = [
      { key: "personality", label: "性格" },
      { key: "wealth", label: "财富" },
      { key: "relationship", label: isMinor ? "人际" : "感情" },
      { key: "current_period", label: "近况" },
    ];
    const tabsEl = $("#tabs");
    const contentEl = $("#tab-content");
    tabsEl.innerHTML = "";

    function activate(key) {
      contentEl.textContent = interpretation[key] || "";
      [...tabsEl.children].forEach((btn) =>
        btn.classList.toggle("active", btn.dataset.key === key)
      );
    }

    tabs.forEach((t, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tab-btn";
      btn.textContent = t.label;
      btn.dataset.key = t.key;
      btn.addEventListener("click", () => activate(t.key));
      tabsEl.appendChild(btn);
      if (i === 0) activate(t.key);
    });
  }

  function wrapCanvasText(ctx, text, x, y, maxWidth, lineHeight) {
    const chars = [...text];
    let line = "";
    let lines = [];
    for (const ch of chars) {
      const test = line + ch;
      if (ctx.measureText(test).width > maxWidth && line) {
        lines.push(line);
        line = ch;
      } else {
        line = test;
      }
    }
    if (line) lines.push(line);
    lines.forEach((l, i) => ctx.fillText(l, x, y + i * lineHeight));
    return lines.length * lineHeight;
  }

  function prepareShareCard(data) {
    const canvas = $("#share-canvas");
    const ctx = canvas.getContext("2d");
    const W = canvas.width;
    const H = canvas.height;
    const FONT = `"PingFang SC", "Microsoft YaHei", sans-serif`;

    // night-sky gradient background
    const grad = ctx.createLinearGradient(0, 0, 0, H);
    grad.addColorStop(0, "#151030");
    grad.addColorStop(1, "#0b0916");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);

    // scattered stars
    ctx.fillStyle = "rgba(255,255,255,0.55)";
    for (let i = 0; i < 90; i++) {
      const sx = Math.random() * W;
      const sy = Math.random() * H * 0.7;
      const r = Math.random() * 1.4 + 0.3;
      ctx.beginPath();
      ctx.arc(sx, sy, r, 0, Math.PI * 2);
      ctx.fill();
    }

    const marginX = 56;

    // eyebrow
    ctx.fillStyle = "#d3ac6c";
    ctx.font = `600 22px ${FONT}`;
    ctx.textBaseline = "alphabetic";
    ctx.fillText("VEDIC ASTROLOGY · 命盘速览", marginX, 96);

    ctx.strokeStyle = "rgba(211,172,108,0.5)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(marginX, 116);
    ctx.lineTo(W - marginX, 116);
    ctx.stroke();

    // name + ascendant
    const displayName = data.name || "命主";
    ctx.fillStyle = "#f2eefb";
    ctx.font = `600 40px ${FONT}`;
    ctx.fillText(displayName, marginX, 176);

    ctx.fillStyle = "#b6a9d6";
    ctx.font = `26px ${FONT}`;
    ctx.fillText(
      `上升 ${data.ascendant.sign} ${data.ascendant.sign_degree} · ${data.ascendant.nakshatra}`,
      marginX,
      214
    );

    // tagline hero
    ctx.fillStyle = "#f2eefb";
    ctx.font = `600 44px ${FONT}`;
    const taglineY = 320;
    const taglineHeight = wrapCanvasText(
      ctx,
      `「${data.interpretation.tagline || ""}」`,
      marginX,
      taglineY,
      W - marginX * 2,
      58
    );

    // dasha info
    const dashaY = taglineY + taglineHeight + 70;
    ctx.fillStyle = "#d3ac6c";
    ctx.font = `600 20px ${FONT}`;
    ctx.fillText("当前大运 · 小运", marginX, dashaY);

    ctx.fillStyle = "#f2eefb";
    ctx.font = `600 32px ${FONT}`;
    ctx.fillText(
      `${data.dasha.mahadasha.lord_zh} — ${data.dasha.antardasha.lord_zh}`,
      marginX,
      dashaY + 44
    );

    ctx.fillStyle = "#8f81b3";
    ctx.font = `20px ${FONT}`;
    ctx.fillText(
      `${data.dasha.antardasha.start} 至 ${data.dasha.antardasha.end}`,
      marginX,
      dashaY + 76
    );

    // footer
    ctx.strokeStyle = "rgba(211,172,108,0.3)";
    ctx.beginPath();
    ctx.moveTo(marginX, H - 90);
    ctx.lineTo(W - marginX, H - 90);
    ctx.stroke();

    ctx.fillStyle = "#8f81b3";
    ctx.font = `18px ${FONT}`;
    ctx.fillText("吠陀占星解读 · 本命盘 + Vimshottari 大运 + AI 生成", marginX, H - 56);
  }

  $("#download-share-btn").addEventListener("click", () => {
    const canvas = $("#share-canvas");
    const link = document.createElement("a");
    link.download = "astrology-share-card.png";
    link.href = canvas.toDataURL("image/png");
    link.click();
  });
})();

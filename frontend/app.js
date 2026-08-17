(() => {
  const $ = (sel) => document.querySelector(sel);

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

  function updateSubmitState() {
    const dateOk = $("#birth_date").value;
    const timeOk = $("#birth_time").value;
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
  $("#birth_date").addEventListener("change", updateSubmitState);
  $("#birth_time").addEventListener("change", updateSubmitState);

  document.addEventListener("click", (e) => {
    if (!cityResults.contains(e.target) && e.target !== cityInput) {
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
      birth_date: $("#birth_date").value,
      birth_time: $("#birth_time").value,
      lat: selectedCity.lat,
      lon: selectedCity.lon,
      timezone: selectedCity.timezone,
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

    renderChartTable(data);
    renderDasha(data.dasha);
    renderTabs(data.interpretation, data.is_minor);

    resultEl.classList.remove("hidden");
    resultEl.scrollIntoView({ behavior: "smooth", block: "start" });
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
})();

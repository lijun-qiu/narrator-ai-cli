/** Narrator AI Console — page logic */

const PAGES = {
  dashboard: { title: "控制台", desc: "网关状态与账户概览" },
  files: { title: "文件管理", desc: "上传视频、字幕与音频素材" },
  workflow: { title: "创作向导", desc: "原创文案 Fast Path 一键流程" },
  tasks: { title: "任务中心", desc: "查看任务状态与结果" },
  resources: { title: "资源库", desc: "BGM · 配音 · 解说风格模板" },
  commands: { title: "命令参考", desc: "CLI 命令速查与示例" },
};

const STATUS_LABEL = { 0: "初始化", 1: "进行中", 2: "成功", 3: "失败", 4: "已取消" };

const CMD_REF = [
  { cat: "配置", cmd: "narrator-ai-cli config set server http://127.0.0.1:8080", desc: "指向本地网关" },
  { cat: "配置", cmd: "narrator-ai-cli config set app_key gateway-local", desc: "设置 API Key" },
  { cat: "账户", cmd: "narrator-ai-cli user balance --json", desc: "查询余额" },
  { cat: "文件", cmd: "narrator-ai-cli file upload video.mp4 --json", desc: "上传本地文件" },
  { cat: "文件", cmd: "narrator-ai-cli file list --json", desc: "列出已上传文件" },
  { cat: "资源", cmd: "narrator-ai-cli bgm list --json", desc: "列出预置 BGM" },
  { cat: "资源", cmd: "narrator-ai-cli dubbing list --lang 普通话 --json", desc: "列出配音角色" },
  { cat: "资源", cmd: "narrator-ai-cli task narration-styles --json", desc: "解说风格模板" },
  { cat: "任务", cmd: 'narrator-ai-cli task search-movie "片名" --json', desc: "搜索电影信息" },
  { cat: "原创", cmd: "narrator-ai-cli task create fast-writing -d @params.json", desc: "快速文案 Step 1" },
  { cat: "原创", cmd: "narrator-ai-cli task create fast-clip-data -d @clip.json", desc: "快速剪辑 Step 2" },
  { cat: "原创", cmd: "narrator-ai-cli task create video-composing -d @compose.json", desc: "合成视频 Step 3" },
  { cat: "任务", cmd: "narrator-ai-cli task query <task_id> --json", desc: "轮询任务状态" },
  { cat: "任务", cmd: "narrator-ai-cli task list --json", desc: "任务列表" },
];

let resources = { bgm: [], dubbing: [], templates: [] };
let wfState = { movieJson: null };

function $(sel) {
  return document.querySelector(sel);
}

function $$(sel) {
  return document.querySelectorAll(sel);
}

function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast" + (isError ? " error" : "");
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 3500);
}

function fmtSize(bytes) {
  if (!bytes) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  let s = bytes;
  while (s >= 1024 && i < u.length - 1) {
    s /= 1024;
    i++;
  }
  return `${s.toFixed(1)} ${u[i]}`;
}

function showPage(name) {
  $$(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.page === name));
  $$(".page").forEach((p) => p.classList.toggle("active", p.id === `page-${name}`));
  const meta = PAGES[name];
  $("#pageTitle").textContent = meta.title;
  $("#pageDesc").textContent = meta.desc;
  if (name === "files") loadFiles();
  if (name === "tasks") loadTasks();
  if (name === "resources") renderResources($(".tab.active")?.dataset.tab || "bgm");
  if (name === "commands") renderCommands();
  if (name === "workflow") refreshWorkflowSelects();
}

function setPipelineStage(stage, state) {
  const el = $(`.pipeline-item[data-stage="${stage}"]`);
  if (!el) return;
  el.classList.remove("running", "done");
  if (state) el.classList.add(state);
}

function appendLog(msg) {
  const log = $("#wfLog");
  log.textContent += `[${new Date().toLocaleTimeString()}] ${msg}\n`;
  log.scrollTop = log.scrollHeight;
}

/* --- Dashboard --- */
async function loadDashboard() {
  try {
    const [balance, tasks, files, health] = await Promise.all([
      API.balance(),
      API.listTasks(1).catch(() => ({ total: 0 })),
      API.listFiles(1).catch(() => ({ total: 0 })),
      API.health(),
    ]);

    $("#statBalance").textContent = balance.balance?.toLocaleString() ?? "—";
    $("#statTasks").textContent = tasks.total ?? 0;
    $("#statFiles").textContent = files.total ?? 0;

    const badge = $("#healthBadge");
    if (health.llm_configured) {
      badge.textContent = "LLM 已连接";
      badge.className = "badge badge-ok";
    } else {
      badge.textContent = "LLM 未配置";
      badge.className = "badge badge-err";
    }

    $("#gatewayInfo").innerHTML = `
      <dt>服务地址</dt><dd>${location.origin}</dd>
      <dt>LLM 状态</dt><dd>${health.llm_configured ? "已配置" : "未配置"}</dd>
      <dt>用户</dt><dd>${balance.nickname || "—"}</dd>
      <dt>公司</dt><dd>${balance.company_name || "—"}</dd>
    `;
  } catch (e) {
    toast(e.message, true);
  }
}

/* --- Files --- */
async function loadFiles() {
  try {
    const search = $("#fileSearch")?.value || "";
    const [list, storage] = await Promise.all([API.listFiles(1, search), API.storageUsage()]);
    const items = list.data || list.items || [];

    const tbody = $("#fileTableBody");
    tbody.innerHTML = items.length
      ? items
          .map(
            (f) => `
      <tr>
        <td class="mono" title="${f.file_id}">${f.file_id?.slice(0, 12)}…</td>
        <td>${f.file_name}</td>
        <td>${fmtSize(f.file_size)}</td>
        <td>${f.category_name || f.category || "—"}</td>
        <td><button class="btn btn-ghost btn-sm" data-dl="${f.file_id}">下载</button></td>
      </tr>`
          )
          .join("")
      : `<tr><td colspan="5" class="muted">暂无文件，请上传</td></tr>`;

    tbody.querySelectorAll("[data-dl]").forEach((btn) => {
      btn.onclick = async () => {
        const info = await API.downloadUrl(btn.dataset.dl);
        window.open(info.download_url, "_blank");
      };
    });

    const pct = storage.usage_percentage || 0;
    $("#storageBar").style.width = `${Math.min(pct, 100)}%`;
    $("#storageText").textContent = `已用 ${fmtSize(storage.used_size)} / ${fmtSize(storage.max_size)}（${pct}%）`;
  } catch (e) {
    toast(e.message, true);
  }
}

async function handleUpload(files) {
  const prog = $("#uploadProgress");
  prog.classList.remove("hidden");
  for (const file of files) {
    prog.innerHTML = `<p>上传 ${file.name}…</p><div class="bar"><div class="bar-fill" style="width:0%"></div></div>`;
    const fill = prog.querySelector(".bar-fill");
    try {
      const id = await API.uploadFile(file, (p) => {
        fill.style.width = `${p}%`;
      });
      toast(`上传成功: ${id.slice(0, 8)}…`);
    } catch (e) {
      toast(`上传失败: ${e.message}`, true);
    }
  }
  prog.classList.add("hidden");
  loadFiles();
  refreshWorkflowSelects();
}

/* --- Tasks --- */
async function loadTasks() {
  try {
    const status = $("#taskStatusFilter")?.value;
    const data = await API.listTasks(1, status);
    const items = data.items || [];
    const tbody = $("#taskTableBody");
    tbody.innerHTML = items.length
      ? items
          .map(
            (t) => `
      <tr>
        <td class="mono">${t.task_id?.slice(0, 12)}…</td>
        <td>${t.type_name || "—"}</td>
        <td><span class="status status-${t.status}">${STATUS_LABEL[t.status] || t.status}</span></td>
        <td>${t.consumed_points ?? 0}</td>
        <td>${(t.created_at || "").slice(0, 19)}</td>
        <td class="btn-row">
          <button class="btn btn-ghost btn-sm" data-task="${t.task_id}">查看</button>
          ${t.status === 3 ? `<button class="btn btn-ghost btn-sm" data-retry="${t.task_id}">重试</button>` : ""}
        </td>
      </tr>`
          )
          .join("")
      : `<tr><td colspan="6" class="muted">暂无任务</td></tr>`;

    tbody.querySelectorAll("[data-task]").forEach((btn) => {
      btn.onclick = async () => {
        const detail = await API.queryTask(btn.dataset.task);
        $("#taskDetail").textContent = JSON.stringify(detail, null, 2);
      };
    });

    tbody.querySelectorAll("[data-retry]").forEach((btn) => {
      btn.onclick = async () => {
        btn.disabled = true;
        try {
          await API.retryTask(btn.dataset.retry);
          toast("已重新提交任务");
          loadTasks();
        } catch (e) {
          toast(e.message, true);
          btn.disabled = false;
        }
      };
    });
  } catch (e) {
    toast(e.message, true);
  }
}

/* --- Resources --- */
async function loadResources() {
  try {
    resources = await API.resources();
  } catch {
    resources = { bgm: [], dubbing: [], templates: [] };
  }
}

function renderResources(tab) {
  const q = ($("#resourceSearch")?.value || "").toLowerCase();
  const grid = $("#resourceGrid");
  let items = [];

  if (tab === "bgm") {
    items = resources.bgm.map((b) => ({ name: b.name, id: b.id, tag: "BGM" }));
  } else if (tab === "dubbing") {
    items = resources.dubbing.map((d) => ({ name: d.name, id: d.id, tag: d.type }));
  } else {
    items = resources.templates.map((t) => ({ name: t.name, id: t.id, tag: t.genre }));
  }

  if (q) items = items.filter((i) => i.name.toLowerCase().includes(q) || i.id.toLowerCase().includes(q));

  grid.innerHTML = items
    .slice(0, 120)
    .map(
      (i) => `
    <div class="resource-item" data-copy="${i.id}" title="点击复制 ID">
      <strong>${i.name}</strong>
      <small>${i.id}</small>
      <span class="tag">${i.tag}</span>
    </div>`
    )
    .join("");

  grid.querySelectorAll("[data-copy]").forEach((el) => {
    el.onclick = () => {
      navigator.clipboard.writeText(el.dataset.copy);
      toast("已复制 ID");
    };
  });
}

function renderCommands() {
  $("#cmdGrid").innerHTML = CMD_REF.map(
    (c) => `
    <div class="cmd-card">
      <h3>${c.cat}</h3>
      <p>${c.desc}</p>
      <pre>${c.cmd}</pre>
    </div>`
  ).join("");
}

/* --- Workflow --- */
async function refreshWorkflowSelects() {
  try {
    const list = await API.listFiles(1);
    const items = list.data || list.items || [];
    const videos = items.filter((f) => /\.(mp4|mkv|mov)$/i.test(f.file_name || ""));
    const srts = items.filter((f) => /\.srt$/i.test(f.file_name || ""));

    const vSel = $("#wfVideoId");
    const sSel = $("#wfSrtId");
    const vVal = vSel.value;
    const sVal = sSel.value;

    vSel.innerHTML = '<option value="">— 选择已上传视频 —</option>' + videos.map((f) => `<option value="${f.file_id}">${f.file_name}</option>`).join("");
    sSel.innerHTML = '<option value="">— 选择 SRT —</option>' + srts.map((f) => `<option value="${f.file_id}">${f.file_name}</option>`).join("");
    vSel.value = vVal;
    sSel.value = sVal;

    if (resources.templates.length === 0) await loadResources();

    $("#wfTemplate").innerHTML = resources.templates
      .slice(0, 50)
      .map((t) => `<option value="${t.id}">${t.genre} · ${t.name}</option>`)
      .join("");

    $("#wfBgm").innerHTML = resources.bgm.slice(0, 40).map((b) => `<option value="${b.id}">${b.name}</option>`).join("");

    $("#wfDubbing").innerHTML = resources.dubbing
      .filter((d) => d.type === "普通话")
      .slice(0, 20)
      .map((d) => `<option value="${d.id}" data-type="${d.type}">${d.name}</option>`)
      .join("");
  } catch (e) {
    console.warn(e);
  }
}

function renderMovieResult(items) {
  const card = $("#wfMovieResultCard");
  const body = $("#wfMovieResultBody");
  const pre = $("#wfMovieResult");

  card.classList.remove("empty", "loading", "error");

  if (!items || items.length === 0) {
    body.innerHTML =
      "<p class='muted'>未在片库精确命中，已用片名创建占位信息，可直接继续；有 SRT 时建议选「原声混剪」。</p>";
    body.classList.remove("hidden");
    pre.classList.add("hidden");
    return;
  }

  if (items.length === 1) {
    showMovieDetail(items[0]);
    return;
  }

  body.innerHTML =
    "<p class='muted' style='margin-bottom:0.5rem'>找到多个结果，请点击选择：</p>" +
    `<div class="movie-pick-list">${items
      .map(
        (item, i) =>
          `<button type="button" class="movie-pick-item" data-idx="${i}">${item.title || item.local_title || "未知"} (${item.year || "?"}) — ${(item.story_info || item.summary || "").slice(0, 40)}…</button>`
      )
      .join("")}</div>`;
  body.classList.remove("hidden");
  pre.classList.add("hidden");

  body.querySelectorAll(".movie-pick-item").forEach((btn) => {
    btn.onclick = () => {
      body.querySelectorAll(".movie-pick-item").forEach((b) => b.classList.remove("selected"));
      btn.classList.add("selected");
      showMovieDetail(items[+btn.dataset.idx]);
    };
  });
  showMovieDetail(items[0]);
  body.querySelector(".movie-pick-item")?.classList.add("selected");
}

function showMovieDetail(item) {
  wfState.movieJson = item;
  const body = $("#wfMovieResultBody");
  const pre = $("#wfMovieResult");
  const title = item.title || item.local_title || "未知";
  const meta = [
    item.year && `年份 ${item.year}`,
    item.type || item.genre,
    item.director && `导演 ${item.director}`,
    item.character_name || item.stars,
  ].filter(Boolean);
  const detailHtml = `
    <div class="movie-title">${title}</div>
    <div class="movie-meta">${meta.map((m) => `<span>${m}</span>`).join("")}</div>
    <div class="movie-story">${item.story_info || item.summary || "暂无简介"}</div>
  `;

  const pickList = body.querySelector(".movie-pick-list");
  let detailEl = body.querySelector(".movie-detail-pane");
  if (pickList) {
    if (!detailEl) {
      detailEl = document.createElement("div");
      detailEl.className = "movie-detail-pane";
      detailEl.style.marginTop = "0.75rem";
      body.appendChild(detailEl);
    }
    detailEl.innerHTML = detailHtml;
  } else {
    body.innerHTML = detailHtml;
  }
  body.classList.remove("hidden");
  pre.textContent = JSON.stringify(item, null, 2);
  pre.classList.remove("hidden");
}

function wizardGo(step) {
  $$(".wizard-step").forEach((s) => {
    const n = +s.dataset.step;
    s.classList.toggle("active", n === step);
    s.classList.toggle("done", n < step);
  });
  $$(".wizard-panel").forEach((p) => p.classList.toggle("active", +p.dataset.panel === step));
}

async function runWorkflow() {
  const movieName = $("#wfMovieName").value.trim();
  const videoId = $("#wfVideoId").value;
  const srtId = $("#wfSrtId").value;
  const templateId = $("#wfTemplate").value;
  const bgmId = $("#wfBgm").value;
  const dubOpt = $("#wfDubbing").selectedOptions[0];
  const dubbingId = dubOpt?.value;
  const dubbingType = dubOpt?.dataset.type || "普通话";

  if (!movieName || !videoId) {
    toast("请填写片名并选择视频", true);
    return;
  }

  $("#wfLog").textContent = "";
  ["writing", "clip", "compose"].forEach((s) => setPipelineStage(s, ""));

  try {
    // Step 1: fast-writing
    setPipelineStage("writing", "running");
    appendLog("创建 fast-writing 任务…");

    const writingBody = {
      learning_model_id: templateId,
      target_mode: $("#wfTargetMode").value,
      playlet_name: movieName,
      model: "pro",
      language: $("#wfLanguage").value,
      target_platform: $("#wfPlatform").value,
      perspective: $("#wfPerspective").value,
      confirmed_movie_json: wfState.movieJson || { title: movieName, story_info: movieName },
    };
    const charName = $("#wfCharacterName").value.trim();
    if (charName) writingBody.target_character_name = charName;
    if (srtId) {
      writingBody.episodes_data = [{ srt_oss_key: srtId, num: 1 }];
    }

    const wCreate = await API.createTask("fast-writing", writingBody);
    appendLog(`task_id: ${wCreate.task_id}`);

    const wDone = await API.pollTask(wCreate.task_id, {
      onTick: (d) => appendLog(`  文案 status=${d.status}`),
    });
    setPipelineStage("writing", "done");
    const writingFileId = wDone.files?.[0]?.file_id || wDone.results?.file_ids?.[0];

    // Step 2: fast-clip-data
    setPipelineStage("clip", "running");
    appendLog("创建 fast-clip-data 任务…");

    const clipBody = {
      task_id: wCreate.task_id,
      file_id: writingFileId,
      bgm: bgmId,
      dubbing: dubbingId,
      dubbing_type: dubbingType,
      episodes_data: [
        {
          video_oss_key: videoId,
          srt_oss_key: srtId || videoId,
          negative_oss_key: videoId,
          num: 1,
        },
      ],
    };
    const cCreate = await API.createTask("fast-clip-data", clipBody);
    const cDone = await API.pollTask(cCreate.task_id, {
      onTick: (d) => appendLog(`  剪辑 status=${d.status}`),
    });
    setPipelineStage("clip", "done");
    const orderNum = cDone.task_order_num;
    const capcutUrl = cDone.results?.capcut_draft_url;

    // Step 3: video-composing
    setPipelineStage("compose", "running");
    appendLog("创建 video-composing 任务…");

    const vCreate = await API.createTask("video-composing", {
      order_num: orderNum,
      bgm: bgmId,
      dubbing: dubbingId,
      dubbing_type: dubbingType,
    });
    const vDone = await API.pollTask(vCreate.task_id, {
      onTick: (d) => appendLog(`  合成 status=${d.status}`),
    });
    setPipelineStage("compose", "done");

    const videoUrl = vDone.results?.tasks?.[0]?.video_url;
    appendLog(`完成! ${videoUrl || ""}`);

    wizardGo(4);
    let resultHtml = "";
    if (videoUrl) {
      resultHtml += `<p><strong>成片：</strong><a href="${videoUrl}" target="_blank">${videoUrl}</a></p>`;
      const vid = $("#wfPreview");
      vid.src = videoUrl;
      vid.classList.remove("hidden");
    }
    if (capcutUrl) {
      resultHtml += `<p><strong>剪映草稿：</strong><a href="${capcutUrl}" target="_blank" download>下载 draft zip</a>（剪映 5.9 / CapCut 国际版）</p>`;
      appendLog(`剪映草稿: ${capcutUrl}`);
    }
    $("#wfResultUrl").innerHTML = resultHtml;
    toast("视频生成完成!");
    loadDashboard();
  } catch (e) {
    appendLog(`错误: ${e.message}`);
    toast(e.message, true);
  }
}

/* --- Init --- */
function init() {
  $("#appKey").value = API.getAppKey();
  $("#saveKey").onclick = () => {
    API.setAppKey($("#appKey").value.trim());
    toast("App Key 已保存");
  };

  $$(".nav-item").forEach((btn) => {
    btn.onclick = () => showPage(btn.dataset.page);
  });

  $$("[data-goto]").forEach((btn) => {
    btn.onclick = () => showPage(btn.dataset.goto);
  });

  $("#refreshBtn").onclick = () => {
    loadDashboard();
    toast("已刷新");
  };

  // Files
  const zone = $("#uploadZone");
  const input = $("#fileInput");
  zone.ondragover = (e) => {
    e.preventDefault();
    zone.classList.add("dragover");
  };
  zone.ondragleave = () => zone.classList.remove("dragover");
  zone.ondrop = (e) => {
    e.preventDefault();
    zone.classList.remove("dragover");
    handleUpload(e.dataTransfer.files);
  };
  input.onchange = () => handleUpload(input.files);

  $("#fileSearch")?.addEventListener("input", debounce(loadFiles, 300));

  // Tasks
  $("#taskRefresh").onclick = loadTasks;
  $("#taskStatusFilter").onchange = loadTasks;

  // Resources tabs
  $$(".tab").forEach((tab) => {
    tab.onclick = () => {
      $$(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      renderResources(tab.dataset.tab);
    };
  });
  $("#resourceSearch")?.addEventListener("input", debounce(() => renderResources($(".tab.active").dataset.tab), 200));

  // Workflow
  $$(".wizard-next").forEach((btn) => {
    btn.onclick = () => wizardGo(+btn.dataset.next);
  });

  $("#wfSearchMovie").onclick = async () => {
    const q = $("#wfMovieName").value.trim();
    if (!q) return toast("请输入片名", true);

    const btn = $("#wfSearchMovie");
    const card = $("#wfMovieResultCard");
    btn.classList.add("loading");
    btn.textContent = "搜索中…";
    card.classList.remove("empty", "error");
    card.classList.add("loading");
    $("#wfMovieResultBody").innerHTML = "<p class='muted'>正在调用 LLM 搜索，请稍候（约 10～30 秒）…</p>";
    $("#wfMovieResultBody").classList.remove("hidden");

    try {
      const list = await API.searchMovie(q);
      renderMovieResult(list);
      toast("电影信息已获取");
    } catch (e) {
      card.classList.add("error");
      card.classList.remove("loading");
      $("#wfMovieResultBody").innerHTML = `<p class="muted" style="color:var(--danger)">搜索失败：${e.message}</p>`;
      $("#wfMovieResultBody").classList.remove("hidden");
      toast(e.message, true);
    } finally {
      btn.classList.remove("loading");
      btn.textContent = "搜索电影信息";
      card.classList.remove("loading");
    }
  };

  $("#wfStart").onclick = runWorkflow;

  loadResources().then(() => {
    loadDashboard();
    renderCommands();
  });
}

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

document.addEventListener("DOMContentLoaded", init);

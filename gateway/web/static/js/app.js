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
        <td><button class="btn btn-ghost btn-sm" data-task="${t.task_id}">查看</button></td>
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
      model: "flash",
      language: $("#wfLanguage").value,
      confirmed_movie_json: wfState.movieJson || { title: movieName, story_info: movieName },
    };
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
    if (videoUrl) {
      $("#wfResultUrl").innerHTML = `<a href="${videoUrl}" target="_blank">${videoUrl}</a>`;
      const vid = $("#wfPreview");
      vid.src = videoUrl;
      vid.classList.remove("hidden");
    }
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
    try {
      const data = await API.searchMovie(q);
      const list = data.data || data;
      wfState.movieJson = Array.isArray(list) ? list[0] : list;
      const pre = $("#wfMovieResult");
      pre.textContent = JSON.stringify(wfState.movieJson, null, 2);
      pre.classList.remove("hidden");
      toast("电影信息已获取");
    } catch (e) {
      toast(e.message, true);
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

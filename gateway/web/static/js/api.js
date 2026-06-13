/** API client — mirrors narrator-ai-cli HTTP calls */

const API = {
  base: "",

  getAppKey() {
    return localStorage.getItem("narrator_app_key") || "gateway-local";
  },

  setAppKey(key) {
    localStorage.setItem("narrator_app_key", key);
  },

  headers() {
    return {
      "Content-Type": "application/json",
      "app-key": this.getAppKey(),
    };
  },

  async request(method, path, body, params) {
    let url = `${this.base}${path}`;
    if (params) {
      const q = new URLSearchParams(params).toString();
      if (q) url += `?${q}`;
    }
    const opts = { method, headers: this.headers() };
    if (body !== undefined) opts.body = JSON.stringify(body);

    const resp = await fetch(url, opts);
    const data = await resp.json();
    if (data.code !== 10000) {
      const err = new Error(data.message || `Error ${data.code}`);
      err.code = data.code;
      throw err;
    }
    return data.data;
  },

  get(path, params) {
    return this.request("GET", path, undefined, params);
  },

  post(path, body) {
    return this.request("POST", path, body);
  },

  delete(path) {
    return this.request("DELETE", path);
  },

  /* --- User --- */
  balance() {
    return this.get("/v1/users/balance");
  },

  /* --- Files --- */
  async uploadFile(file, onProgress) {
    const presigned = await this.post("/v2/files/upload/presigned-url", {
      file_name: file.name,
      file_size: file.size,
      content_type: file.type || "application/octet-stream",
    });

    await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", presigned.upload_url);
      xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
      if (onProgress) {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
        };
      }
      xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`Upload ${xhr.status}`)));
      xhr.onerror = () => reject(new Error("Upload failed"));
      xhr.send(file);
    });

    await this.post("/v2/files/upload/callback", {
      file_id: presigned.file_id,
      object_key: presigned.object_key,
      upload_status: "success",
      file_size: file.size,
    });

    return presigned.file_id;
  },

  listFiles(page = 1, search) {
    const params = { page, page_size: 50 };
    if (search) params.search = search;
    return this.get("/v2/files/list", params);
  },

  storageUsage() {
    return this.get("/v2/files/user/storage_usage");
  },

  downloadUrl(fileId) {
    return this.post("/v2/files/download/presigned-url", { file_id: fileId });
  },

  /* --- Tasks --- */
  searchMovie(query) {
    return this.get("/v2/task/commentary/search_media_information", { query });
  },

  createTask(type, body) {
    const paths = {
      "fast-writing": "/v2/task/commentary/create_fast_generate_writing",
      "fast-clip-data": "/v2/task/commentary/create_generate_fast_writing_clip_data",
      "video-composing": "/v2/task/commentary/create_video_composing",
      "generate-writing": "/v2/task/commentary/create_generate_writing",
      "clip-data": "/v2/task/commentary/create_generate_clip_data",
    };
    return this.post(paths[type], body);
  },

  queryTask(taskId) {
    return this.get(`/v2/task/commentary/query/${taskId}`);
  },

  listTasks(page = 1, status) {
    const params = { page, limit: 20 };
    if (status !== "" && status !== undefined) params.status = status;
    return this.get("/v2/task/commentary/list", params);
  },

  async pollTask(taskId, { interval = 3000, timeout = 600000, onTick } = {}) {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      const data = await this.queryTask(taskId);
      if (onTick) onTick(data);
      if (data.status === 2) return data;
      if (data.status === 3) {
        const err = new Error(data.error_message_slug || "Task failed");
        err.task = data;
        throw err;
      }
      await new Promise((r) => setTimeout(r, interval));
    }
    throw new Error("Task timeout");
  },

  /* --- Resources --- */
  resources() {
    return this.get("/ui/api/resources");
  },

  health() {
    return fetch(`${this.base}/health`).then((r) => r.json());
  },
};

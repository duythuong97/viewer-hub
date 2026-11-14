// JSON calls to Viewer Hub. Every module's API answers {…} or {error: {code, message}} with an HTTP status.
// Writes carry X-Viewer-Hub: a cross-site form cannot send it, so the Hub refuses writes without it where it matters
// (addons, viewer_hub/addons/routes.py).
export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function call(method, url, body) {
  const init = { method, headers: { Accept: "application/json" } };
  if (method !== "GET") init.headers["X-Viewer-Hub"] = "1";
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const response = await fetch(url, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data.error?.message || data.message || `Lỗi ${response.status}`;
    throw new ApiError(message, response.status, data);
  }
  return data;
}

export const http = {
  get: (url, params) => call("GET", params ? `${url}?${new URLSearchParams(clean(params))}` : url),
  post: (url, body = {}) => call("POST", url, body),
  patch: (url, body = {}) => call("PATCH", url, body),
  put: (url, body = {}) => call("PUT", url, body),
  delete: (url) => call("DELETE", url),
  upload: (url, form) => call("POST", url, form),
};

/** `http` for one addon's own API: paths are relative to /x/<id>/api (the `api` prop of an addon page). */
export function addonApi(id) {
  const base = `/x/${encodeURIComponent(id)}/api`;
  const at = (path) => `${base}${path.startsWith("/") ? path : `/${path}`}`;
  return {
    base,
    url: at,
    get: (path, params) => http.get(at(path), params),
    post: (path, body) => http.post(at(path), body),
    patch: (path, body) => http.patch(at(path), body),
    put: (path, body) => http.put(at(path), body),
    delete: (path) => http.delete(at(path)),
    upload: (path, form) => http.upload(at(path), form),
    /** Server-sent events of the addon (EventSource on /x/<id>/api/<path>). */
    events: (path = "/events") => new EventSource(at(path)),
  };
}

function clean(params) {
  return Object.fromEntries(Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ""));
}

/** POST FormData with upload progress (0..1) for big uploads; resolves with the JSON answer. */
export function uploadWithProgress(url, form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.setRequestHeader("Accept", "application/json");
    xhr.setRequestHeader("X-Viewer-Hub", "1");
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress?.(event.loaded / event.total); };
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new ApiError(data.error?.message || `Lỗi ${xhr.status}`, xhr.status, data));
    };
    xhr.onerror = () => reject(new ApiError("Tải lên thất bại", 0, {}));
    xhr.send(form);
  });
}

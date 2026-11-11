import { defineStore } from "pinia";
import { ref } from "vue";
import { parseContract, type Project, type Replay } from "./contracts";

export const useWorkspace = defineStore("workspace", () => {
  const token = ref(""),
    user = ref(""),
    projects = ref<Project[]>([]),
    selected = ref("");
  const bundle = ref<Record<string, any> | null>(null),
    run = ref<Replay | null>(null),
    error = ref(""),
    busy = ref(false);
  let createKey = crypto.randomUUID();
  async function request(path: string, options: RequestInit = {}) {
    const headers = new Headers(options.headers);
    if (token.value) headers.set("Authorization", "Bearer " + token.value);
    if (options.body && !(options.body instanceof FormData))
      headers.set("Content-Type", "application/json");
    const response = await fetch("/api/v1" + path, {
      ...options,
      headers,
      credentials: "include",
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      if (response.status === 401) {
        token.value = "";
        user.value = "";
        projects.value = [];
        selected.value = "";
        bundle.value = null;
        run.value = null;
      }
      throw Error(
        body.error?.code
          ? `${body.error.code}：${body.error.message}`
          : `HTTP ${response.status}`,
      );
    }
    return response.status === 204 ? null : response.json();
  }
  async function action(work: () => Promise<void>) {
    busy.value = true;
    error.value = "";
    try {
      await work();
    } catch (e) {
      error.value =
        e instanceof Error ? e.message : "请求失败，请检查 API 连接";
    } finally {
      busy.value = false;
    }
  }
  async function authenticate(
    email: string,
    password: string,
    register: boolean,
  ) {
    await action(async () => {
      const body = await request("/auth/" + (register ? "register" : "login"), {
        method: "POST",
        body: JSON.stringify({
          email,
          password,
          client_kind: "web",
          ...(register ? { display_name: email.split("@")[0] } : {}),
        }),
      });
      token.value = body.access_token;
      user.value = body.user.display_name;
      await loadProjects();
    });
  }
  async function restore() {
    await action(async () => {
      const body = await request("/auth/refresh", {
        method: "POST",
        body: "{}",
      });
      token.value = body.access_token;
      user.value = body.user.display_name;
      await loadProjects();
    });
  }
  async function logout() {
    await action(async () => {
      await request("/auth/logout", { method: "POST", body: "{}" });
      token.value = "";
      user.value = "";
      projects.value = [];
      selected.value = "";
      bundle.value = null;
      run.value = null;
    });
  }
  async function loadProjects() {
    const rows = await request("/projects");
    projects.value = rows.map((p: unknown) =>
      parseContract<Project>("Project", p),
    );
  }
  async function createProject(name: string, scenario: string) {
    await action(async () => {
      const p = parseContract<Project>(
        "Project",
        await request("/projects", {
          method: "POST",
          headers: { "Idempotency-Key": createKey },
          body: JSON.stringify({ name, scenario }),
        }),
      );
      createKey = crypto.randomUUID();
      await loadProjects();
      selected.value = p.id;
      bundle.value = null;
      run.value = null;
    });
  }
  function select(id: string) {
    selected.value = id;
    bundle.value = null;
    run.value = null;
    error.value = "";
  }
  async function replay() {
    await action(async () => {
      const prefix = "/projects/" + selected.value + "/phase-one";
      await request(prefix + "/seed", { method: "POST" });
      bundle.value = await request(prefix);
      run.value = await request(prefix + "/replay", { method: "POST" });
    });
  }
  async function probe(file: File) {
    let result: unknown;
    await action(async () => {
      const data = new FormData();
      data.append("upload", file);
      result = await request(
        "/projects/" + selected.value + "/phase-one/media-probe",
        { method: "POST", body: data },
      );
    });
    return result;
  }
  return {
    token,
    user,
    projects,
    selected,
    bundle,
    run,
    error,
    busy,
    authenticate,
    restore,
    logout,
    loadProjects,
    createProject,
    select,
    replay,
    probe,
    action,
  };
});

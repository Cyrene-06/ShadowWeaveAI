<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import AppIcon from "./AppIcon.vue";
import { parseContract } from "./contracts";

const props = defineProps<{ projectId: string; token: string }>();
type Run = {
  analysis_run_id: string;
  generation: number;
  stage: string;
  error_code: string | null;
  wall_ms: number | null;
  result: {
    split?: string;
    speech?: { status: string; utterance_count?: number };
    segment_count?: number;
  };
};
type Asset = {
  asset_id: string;
  name: string;
  sha256: string;
  active_analysis_id: string | null;
  latest: Run;
  duplicate: boolean;
};
type Candidate = {
  id: string;
  asset_id: string;
  name: string;
  analysis_run_id: string;
  analysis_content_hash: string;
  source_sha256: string;
  source_and_rights: string;
  in_ms: number;
  out_ms: number;
  frame_ms: number;
  human_tags: string[];
  matched_fields: string[];
  speech: { in_ms: number; out_ms: number; text: string }[];
  signals: Record<string, unknown>;
};

const rows = ref<Asset[]>([]),
  results = ref<Candidate[]>([]),
  selected = ref<Candidate | null>(null);
const error = ref(""),
  notice = ref(""),
  q = ref(""),
  assetFilter = ref(""),
  limitStart = ref(""),
  limitEnd = ref("");
const file = ref<File | null>(null),
  fileField = ref<HTMLInputElement | null>(null),
  provenance = ref(""),
  authorized = ref(false);
const queried = ref(false),
  busy = ref(false),
  searching = ref(false),
  previewing = ref(false),
  video = ref<HTMLVideoElement | null>(null);
const previewUrl = ref(""),
  frameUrl = ref(""),
  tag = ref(""),
  history = ref<{ name: string; runs: Run[] } | null>(null);
const bindingKey = ref(""),
  reviewed = ref(false),
  usable = ref(false);
const support = ref<"supported" | "unknown" | "unsupported">("unknown");
const lifecycle = new AbortController();
let timer: ReturnType<typeof setInterval> | undefined;
let previewRequest: AbortController | undefined;
let loading = false;
const retryKeys = new Map<string, string>();
const stages: Record<string, string> = {
  queued: "排队",
  probe: "探测原片",
  media: "切分与抽帧",
  speech: "音轨检查 / 转写",
  publish: "发布索引",
  succeeded: "分析完成",
  failed: "分析失败",
};
const errors: Record<string, string> = {
  INVALID_MEDIA: "文件损坏、格式不受支持或超过视频限制",
  TRANSCRIPTION_NOT_CONFIGURED: "Worker 未配置本地转写模型",
  TRANSCRIPTION_FAILED: "转写运行失败",
  TRANSCRIPTION_TIMEOUT: "转写超时",
  SOURCE_UNAVAILABLE: "原片不可用或哈希不一致",
  WORKER_INTERRUPTED: "任务多次中断",
  DEPENDENCY_UNAVAILABLE: "缺少 FFmpeg / ffprobe",
};
const exposure: Record<string, string> = {
  dark_sample: "代表帧偏暗",
  bright_sample: "代表帧偏亮",
  no_extreme_at_sample: "代表帧未见极端曝光",
  unknown: "曝光未知",
};
const searchable = computed(() => rows.value.some((a) => a.active_analysis_id));
const interval = (start: number, end: number) =>
  `${(start / 1000).toFixed(2)}–${(end / 1000).toFixed(2)} 秒`;
const pending = (stage: string) => !["failed", "succeeded"].includes(stage);

async function request(path: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  headers.set("Authorization", `Bearer ${props.token}`);
  const r = await fetch(
    `/api/v1/projects/${props.projectId}/materials${path}`,
    {
      ...options,
      headers,
      signal: options.signal ?? lifecycle.signal,
    },
  );
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    const code = data.error?.code;
    throw new Error(
      r.status === 401
        ? "登录已过期，请重新登录"
        : errors[code] || data.error?.message || `请求失败（${r.status}）`,
    );
  }
  return r;
}

function showError(e: unknown) {
  if (
    !lifecycle.signal.aborted &&
    !(e instanceof DOMException && e.name === "AbortError")
  )
    error.value = e instanceof Error ? e.message : "请求失败";
}

async function refresh() {
  if (loading || lifecycle.signal.aborted) return;
  loading = true;
  try {
    rows.value = await (await request("/assets")).json();
  } catch (e) {
    showError(e);
  } finally {
    loading = false;
  }
}

onMounted(() => {
  void refresh();
  timer = setInterval(() => {
    if (rows.value.some((row) => pending(row.latest.stage))) void refresh();
  }, 1800);
});

function clearPreview() {
  previewRequest?.abort();
  for (const url of [previewUrl.value, frameUrl.value])
    if (url) URL.revokeObjectURL(url);
  previewUrl.value = "";
  frameUrl.value = "";
}

onBeforeUnmount(() => {
  lifecycle.abort();
  clearInterval(timer);
  clearPreview();
});

function choose(e: Event) {
  file.value = (e.target as HTMLInputElement).files?.[0] ?? null;
}

async function upload() {
  if (!file.value || busy.value) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    if (file.value.size > 64 * 1024 * 1024) throw new Error("文件超过 64 MiB");
    const params = new URLSearchParams({
      name: file.value.name,
      source: provenance.value.trim(),
      rights_confirmed: String(authorized.value),
    });
    const row: Asset = await (
      await request(`/assets?${params}`, {
        method: "POST",
        body: file.value,
        headers: { "Content-Type": "application/octet-stream" },
      })
    ).json();
    rows.value = [
      ...rows.value.filter((item) => item.asset_id !== row.asset_id),
      row,
    ];
    file.value = null;
    if (fileField.value) fileField.value.value = "";
    authorized.value = false;
    notice.value = row.duplicate
      ? "与项目内原片完全相同，已复用该素材和分析记录。"
      : "原片已登记，等待分析 Worker。";
    void refresh();
  } catch (e) {
    showError(e);
  } finally {
    busy.value = false;
  }
}

async function retry(row: Asset) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const key = retryKeys.get(row.asset_id) ?? crypto.randomUUID();
    retryKeys.set(row.asset_id, key);
    await request(`/assets/${row.asset_id}/analyses`, {
      method: "POST",
      headers: { "Idempotency-Key": key },
    });
    retryKeys.delete(row.asset_id);
    notice.value = "已排队。已有成功版本会继续用于检索，直到新分析成功。";
    const at = rows.value.find((item) => item.asset_id === row.asset_id);
    if (at) at.latest.stage = "queued";
    await refresh();
  } catch (e) {
    showError(e);
  } finally {
    busy.value = false;
  }
}

async function showHistory(row: Asset) {
  try {
    history.value = {
      name: row.name,
      runs: await (await request(`/assets/${row.asset_id}/analyses`)).json(),
    };
  } catch (e) {
    showError(e);
  }
}

async function search() {
  if (searching.value) return;
  searching.value = true;
  error.value = "";
  try {
    const p = new URLSearchParams({ q: q.value.trim() });
    if (assetFilter.value) p.set("asset_id", assetFilter.value);
    if (limitStart.value !== "")
      p.set("from_ms", String(Math.round(Number(limitStart.value) * 1000)));
    if (limitEnd.value !== "")
      p.set("to_ms", String(Math.round(Number(limitEnd.value) * 1000)));
    results.value = parseContract<{ candidates: Candidate[] }>(
      "MaterialSearch",
      await (await request(`/search?${p}`)).json(),
    ).candidates;
    queried.value = true;
  } catch (e) {
    showError(e);
  } finally {
    searching.value = false;
  }
}

async function inspect(row: Candidate) {
  clearPreview();
  const controller = new AbortController();
  previewRequest = controller;
  const signal = controller.signal;
  selected.value = row;
  tag.value = "";
  reviewed.value = false;
  usable.value = false;
  support.value = "unknown";
  bindingKey.value = "";
  previewing.value = true;
  error.value = "";
  try {
    const files = await Promise.all([
      request(`/analyses/${row.analysis_run_id}/preview`, { signal }).then(
        (r) => r.blob(),
      ),
      request(`/segments/${row.id}/frame`, { signal }).then((r) => r.blob()),
    ]);
    if (!signal.aborted && !lifecycle.signal.aborted) {
      previewUrl.value = URL.createObjectURL(files[0]);
      frameUrl.value = URL.createObjectURL(files[1]);
    }
  } catch (e) {
    showError(e);
  } finally {
    if (!signal.aborted) previewing.value = false;
  }
}

function seek(ms = selected.value?.in_ms ?? 0) {
  if (video.value && Number.isFinite(video.value.duration))
    video.value.currentTime = ms / 1000;
}

async function addTag() {
  const row = selected.value;
  if (!row || busy.value || !tag.value.trim()) return;
  busy.value = true;
  error.value = "";
  try {
    const next: Candidate = await (
      await request(`/segments/${row.id}/tags`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: tag.value.trim() }),
      })
    ).json();
    if (selected.value?.id === row.id) {
      selected.value.human_tags = next.human_tags;
      tag.value = "";
    }
  } catch (e) {
    showError(e);
  } finally {
    busy.value = false;
  }
}

async function exportEvidence() {
  const row = selected.value;
  if (!row || busy.value || !reviewed.value || !bindingKey.value.trim()) return;
  busy.value = true;
  error.value = "";
  try {
    const json = await (
      await request("/evidence", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bindings: [
            {
              segment_id: row.id,
              analysis_run_id: row.analysis_run_id,
              in_ms: row.in_ms,
              out_ms: row.out_ms,
              requirement_keys: [bindingKey.value.trim()],
              semantic_support: support.value,
              quality_usable: usable.value,
              reviewed: true,
            },
          ],
        }),
      })
    ).text();
    const url = URL.createObjectURL(
      new Blob([json], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `material-evidence-${row.id}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    notice.value =
      "已导出证据清单。证据支持程度来自人工复核，不代表自动判定故事已覆盖。";
  } catch (e) {
    showError(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section
    id="material-workspace"
    class="panel material-workspace"
    aria-labelledby="material-title"
  >
    <div class="section-title">
      <span class="section-icon"><AppIcon name="film" /></span>
      <div>
        <p class="eyebrow">PHASE TWO / SOURCE EVIDENCE</p>
        <h2 id="material-title">素材证据链</h2>
      </div>
    </div>
    <p class="section-copy">
      上传真实视频，按转写或人工标签找到片段，并沿原片时间回看。检索命中不是事实证明。
    </p>
    <form class="material-form" @submit.prevent="upload">
      <label
        >视频文件<input
          ref="fileField"
          type="file"
          accept=".mp4,.m4v,.mov,.webm,.mkv"
          required
          @change="choose"
      /></label>
      <label
        >素材来源与使用范围<input
          v-model="provenance"
          placeholder="例如：团队自摄，已授权项目内使用"
          maxlength="300"
          required
      /></label>
      <label class="material-check"
        ><input
          v-model="authorized"
          type="checkbox"
          required
        />确认有权在本项目内处理此素材</label
      >
      <button
        class="button button-primary"
        :disabled="busy || !authorized || !file || !provenance.trim()"
      >
        上传并分析
      </button>
      <span class="muted">单个视频 ≤ 64 MiB / 180 秒</span>
    </form>
    <p v-if="error" class="material-error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <div class="material-heading">
      <h3>素材与分析状态</h3>
      <button type="button" class="button small" @click="refresh">
        刷新状态
      </button>
    </div>
    <p v-if="!rows.length" class="muted">
      还没有真实素材。上传后，本地 Worker 会执行分析。
    </p>
    <ul v-else class="material-list">
      <li v-for="row in rows" :key="row.asset_id" class="material-item">
        <div>
          <strong>{{ row.name }}</strong>
          <p class="muted">
            第 {{ row.latest.generation }} 版 ·
            {{ stages[row.latest.stage] ?? row.latest.stage
            }}<template
              v-if="row.latest.result.speech?.status === 'not_applicable'"
            >
              · 无音轨，转写不适用</template
            ><template
              v-else-if="row.latest.result.speech?.status === 'succeeded'"
            >
              · 转写 {{ row.latest.result.speech.utterance_count }} 段</template
            >
          </p>
          <p v-if="row.latest.error_code" class="material-error">
            {{ errors[row.latest.error_code] ?? row.latest.error_code
            }}<template v-if="row.active_analysis_id"
              >；上一成功版本仍可查</template
            >
          </p>
        </div>
        <div class="material-buttons">
          <button type="button" class="button small" @click="showHistory(row)">
            分析历史</button
          ><button
            type="button"
            class="button small"
            :disabled="busy || pending(row.latest.stage)"
            @click="retry(row)"
          >
            {{ row.latest.stage === "failed" ? "重试" : "重新分析" }}
          </button>
        </div>
      </li>
    </ul>
    <div v-if="history" class="material-history">
      <div class="material-heading">
        <h3>{{ history.name }} · 分析历史</h3>
        <button type="button" class="button small" @click="history = null">
          关闭
        </button>
      </div>
      <p v-for="run in history.runs" :key="run.analysis_run_id">
        第 {{ run.generation }} 版 · {{ stages[run.stage] }} ·
        {{ run.wall_ms ?? "—" }} ms <code>{{ run.analysis_run_id }}</code>
      </p>
    </div>
    <form class="material-search" @submit.prevent="search">
      <label
        >片段关键词<input
          v-model="q"
          placeholder="搜索转写或人工标签，留空列出片段"
          maxlength="120"
      /></label>
      <label
        >按素材筛选<select v-model="assetFilter">
          <option value="">全部素材</option>
          <option
            v-for="a in rows.filter((r) => r.active_analysis_id)"
            :key="a.asset_id"
            :value="a.asset_id"
          >
            {{ a.name }}
          </option>
        </select></label
      >
      <label
        >起始秒<input v-model="limitStart" type="number" min="0" step="0.001"
      /></label>
      <label
        >结束秒<input v-model="limitEnd" type="number" min="0.001" step="0.001"
      /></label>
      <button
        class="button button-primary"
        :disabled="!searchable || searching"
      >
        检索片段
      </button>
    </form>
    <p v-if="queried && !results.length" role="status">
      无匹配片段，可尝试其他关键词或取消时间筛选。
    </p>
    <ul v-if="results.length" class="material-list">
      <li v-for="r in results" :key="r.id" class="material-item">
        <div>
          <strong>{{ r.name }}</strong> · {{ interval(r.in_ms, r.out_ms) }}
          <p class="muted">
            {{ r.speech[0]?.text || r.human_tags.join("、") || "暂无转写或标签"
            }}<template v-if="r.matched_fields.length">
              · 命中：{{
                r.matched_fields
                  .map((s) => (s === "transcript" ? "转写" : "人工标签"))
                  .join("、")
              }}</template
            >
          </p>
        </div>
        <button type="button" class="button small" @click="inspect(r)">
          回看片段
        </button>
      </li>
    </ul>
    <article v-if="selected" class="material-inspect">
      <div class="material-heading">
        <h3>原片回看 · {{ interval(selected.in_ms, selected.out_ms) }}</h3>
        <button
          type="button"
          class="button small"
          @click="
            clearPreview();
            selected = null;
          "
        >
          关闭
        </button>
      </div>
      <p v-if="previewing" role="status">正在载入该分析版本的预览…</p>
      <div v-if="previewUrl" class="material-preview">
        <video
          ref="video"
          controls
          playsinline
          :src="previewUrl"
          @loadedmetadata="seek()"
        />
        <figure v-if="frameUrl">
          <img :src="frameUrl" alt="当前片段的代表帧" />
          <figcaption>
            代表帧 · {{ (selected.frame_ms / 1000).toFixed(2) }} 秒 ·
            {{ exposure[String(selected.signals.exposure_hint)] }}
          </figcaption>
        </figure>
      </div>
      <div class="material-buttons">
        <button
          type="button"
          class="button small"
          :disabled="!previewUrl"
          @click="seek()"
        >
          跳到区间起点</button
        ><span class="muted">预览代理未剪辑，沿用原片时间坐标</span>
      </div>
      <ul v-if="selected.speech.length" class="material-transcript">
        <li
          v-for="line in selected.speech"
          :key="`${line.in_ms}-${line.out_ms}`"
        >
          {{ interval(line.in_ms, line.out_ms) }} · {{ line.text }}
        </li>
      </ul>
      <p>人工标签：{{ selected.human_tags.join("、") || "暂无" }}</p>
      <form class="material-form" @submit.prevent="addTag">
        <label
          >补充人工标签<input v-model="tag" maxlength="80" required /></label
        ><button class="button" :disabled="busy || !tag.trim()">
          保存标签
        </button>
      </form>
      <details>
        <summary>核对证据来源</summary>
        <dl class="material-refs">
          <dt>素材</dt>
          <dd>{{ selected.asset_id }}</dd>
          <dt>片段</dt>
          <dd>{{ selected.id }}</dd>
          <dt>分析版本</dt>
          <dd>{{ selected.analysis_run_id }}</dd>
          <dt>上传者登记的来源与使用范围</dt>
          <dd>{{ selected.source_and_rights }}</dd>
          <dt>原片 SHA-256</dt>
          <dd>{{ selected.source_sha256 }}</dd>
          <dt>分析内容摘要</dt>
          <dd>{{ selected.analysis_content_hash }}</dd>
        </dl>
      </details>
      <details>
        <summary>人工复核并导出证据</summary>
        <form class="material-form" @submit.prevent="exportEvidence">
          <label
            >故事要求编号<input
              v-model="bindingKey"
              placeholder="例如 first_step"
              required
              maxlength="80"
          /></label>
          <label
            >语义支持<select v-model="support">
              <option value="unknown">无法判断</option>
              <option value="supported">支持该要求</option>
              <option value="unsupported">不支持该要求</option>
            </select></label
          >
          <label class="material-check"
            ><input v-model="usable" type="checkbox" />画质与声音足以使用</label
          >
          <label class="material-check"
            ><input
              v-model="reviewed"
              type="checkbox"
              required
            />我已回看原片并核对该要求</label
          >
          <button
            class="button"
            :disabled="!reviewed || !bindingKey.trim() || busy"
          >
            下载证据清单
          </button>
        </form>
      </details>
    </article>
  </section>
</template>

<style scoped>
.material-workspace {
  padding: clamp(1rem, 2.5vw, 1.7rem);
  display: grid;
  gap: 1rem;
  scroll-margin-top: 1rem;
}
.material-workspace h3,
.material-workspace p {
  margin: 0;
}
.material-form,
.material-search {
  display: flex;
  flex-wrap: wrap;
  gap: 0.8rem;
  align-items: end;
}
.material-form > label,
.material-search > label {
  display: grid;
  gap: 0.36rem;
  flex: 1 1 10rem;
  min-width: 0;
}
.material-form > .material-check {
  display: flex;
  align-items: center;
  flex-basis: 100%;
}
.material-check input {
  width: auto;
}
.material-search label:has(input[type="number"]) {
  flex-basis: 5rem;
}
.material-workspace input:not([type="checkbox"]),
.material-workspace select {
  width: 100%;
  min-width: 0;
}
.material-heading,
.material-item,
.material-buttons {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem;
}
.material-heading,
.material-item {
  justify-content: space-between;
}
.material-list,
.material-transcript {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.5rem;
}
.material-item,
.material-inspect,
.material-history {
  border: 1px solid #544338;
  border-radius: 0.65rem;
  padding: 0.85rem;
  overflow-wrap: anywhere;
}
.material-item > div:first-child {
  flex: 1 1 13rem;
}
.material-inspect,
.material-history {
  display: grid;
  gap: 0.8rem;
}
.material-preview {
  display: grid;
  gap: 0.8rem;
  grid-template-columns: 2fr 1fr;
  align-items: start;
}
.material-preview video,
.material-preview img {
  width: 100%;
  display: block;
  border-radius: 0.5rem;
  background: #141313;
}
.material-preview figure,
.material-refs dd {
  margin: 0;
}
.material-preview figcaption,
.material-refs dt {
  color: #cfb6a2;
  font-size: 0.85rem;
}
.material-refs {
  display: grid;
  gap: 0.25rem;
}
.material-error {
  color: #ffa99c;
}
.material-workspace summary {
  cursor: pointer;
  padding: 0.2rem 0;
}
@media (max-width: 650px) {
  .material-preview {
    grid-template-columns: 1fr;
  }
}
</style>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import AppIcon from "./AppIcon.vue";
import ReplayResults from "./ReplayResults.vue";
import MaterialWorkspace from "./MaterialWorkspace.vue";
import { scenarios } from "./presentation";
import { useWorkspace } from "./store";

const state = useWorkspace();
const email = ref("");
const password = ref("");
const registration = ref(false);
const name = ref("校园活动");
const scenario = ref("campus");
const probeResult = ref<unknown>(null);
const probeName = ref("");
const project = computed(() =>
  state.projects.find((p) => p.id === state.selected),
);
const totals = computed(() => {
  const checks = Object.values(state.run?.checks ?? {});
  return { passed: checks.filter(Boolean).length, total: checks.length };
});
const nav = [
  { href: "#coverage", title: "故事覆盖", icon: "layers" },
  { href: "#capture", title: "补拍验证", icon: "camera" },
  { href: "#editing", title: "局部修改", icon: "shield" },
];
watch(
  () => state.selected,
  () => {
    probeResult.value = null;
    probeName.value = "";
  },
);

async function authenticate() {
  await state.authenticate(email.value, password.value, registration.value);
  if (state.token) password.value = "";
}

async function upload(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  probeName.value = file.name;
  probeResult.value = null;
  const result = await state.probe(file);
  if (result) probeResult.value = result;
  else probeName.value = "";
  input.value = "";
}
</script>

<template>
  <a class="skip-link" href="#main-content">跳到主要内容</a>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">
        <span class="brand-mark"><AppIcon name="weave" :size="23" /></span>
        <div>
          <strong>影织<span> AI</span></strong
          ><small>SHADOWWEAVE</small>
        </div>
      </div>
      <span class="stage-tag"><i aria-hidden="true"></i> 第一阶段</span>
      <div v-if="state.token" class="account">
        <span class="avatar" aria-hidden="true">{{
          state.user.charAt(0).toUpperCase()
        }}</span>
        <span class="account-name" :title="state.user">{{ state.user }}</span>
        <button
          type="button"
          class="button button-subtle logout"
          :disabled="state.busy"
          @click="state.logout"
        >
          <AppIcon name="logout" :size="15" />退出
        </button>
      </div>
      <span v-else class="edition mono">STUDIO / 01</span>
    </div>
  </header>

  <main v-if="!state.token" id="main-content" class="login-shell" tabindex="-1">
    <section class="auth-intro" aria-labelledby="welcome-title">
      <p class="eyebrow kicker">
        <span aria-hidden="true"></span> EVIDENCE-LED EDITING
      </p>
      <h1 id="welcome-title">故事有据可依，<br /><em>修改有界可控。</em></h1>
      <p class="auth-copy">
        用素材证据解释故事覆盖，用编辑规则保护已确认的片段。
      </p>
      <div class="studio-visual" aria-hidden="true">
        <div class="visual-top mono">
          <span><i></i> 流程示意 / 01</span><AppIcon name="film" :size="16" />
        </div>
        <div class="visual-art">
          <svg
            viewBox="0 0 570 185"
            preserveAspectRatio="xMidYMid slice"
            width="100%"
            height="100%"
          >
            <defs>
              <linearGradient
                id="thread"
                x2="1"
                y2="1"
                gradientUnits="objectBoundingBox"
              >
                <stop stop-color="#ec9d63" stop-opacity=".1" />
                <stop offset=".53" stop-color="#ffb065" />
                <stop offset="1" stop-color="#f4c083" stop-opacity=".15" />
              </linearGradient>
              <pattern
                id="grid"
                width="30"
                height="30"
                patternUnits="userSpaceOnUse"
              >
                <path
                  d="M30 0H0v30"
                  fill="none"
                  stroke="#806047"
                  stroke-opacity=".2"
                />
              </pattern>
            </defs>
            <rect width="570" height="185" fill="url(#grid)" />
            <g fill="none" stroke="url(#thread)">
              <path
                v-for="i in 12"
                :key="i"
                :d="`M-25 ${36 + 10 * i} C90 ${-32 + 15 * i} 179 ${241 - 14 * i} 284 ${91 + 2.5 * i} S448 ${-75 + i * 17} 602 ${73 + i * 7}`"
                :opacity="0.25 + i * 0.06"
              />
            </g>
            <circle cx="283" cy="106" r="26" fill="#2b211c" stroke="#986743" />
            <circle
              cx="283"
              cy="106"
              r="35"
              fill="none"
              stroke="#986743"
              stroke-opacity=".35"
            />
            <path d="m279 99 11 7-11 7z" fill="#ffc181" />
          </svg>
        </div>
        <div class="visual-track">
          <i></i><i></i><i></i><i></i><span></span>
        </div>
        <div class="visual-bottom mono">
          <span>01 · COVERAGE</span><span>02 · CAPTURE</span
          ><span>03 · EDIT</span>
        </div>
      </div>
    </section>
    <section class="panel auth" aria-labelledby="auth-title">
      <span class="section-icon"><AppIcon name="grid" :size="20" /></span>
      <p class="eyebrow">WORKSPACE ACCESS</p>
      <h2 id="auth-title">
        {{ registration ? "创建账号" : "进入项目工作台" }}
      </h2>
      <p class="auth-description">
        登录后管理项目，运行固定规则样例并核对结果。
      </p>
      <p v-if="state.error" class="notice error" role="alert">
        {{ state.error }}
      </p>
      <p v-if="state.busy" class="muted" role="status">正在请求 API，请稍候…</p>
      <form class="auth-form" @submit.prevent="authenticate">
        <label
          >邮箱<input
            v-model="email"
            type="email"
            required
            autocomplete="username"
            placeholder="name@example.com"
        /></label>
        <label
          >密码（至少 12 位）<input
            v-model="password"
            type="password"
            minlength="12"
            maxlength="128"
            required
            :autocomplete="registration ? 'new-password' : 'current-password'"
        /></label>
        <button
          class="button button-primary auth-submit"
          :disabled="state.busy"
        >
          {{ registration ? "注册并进入" : "登录"
          }}<AppIcon name="arrow" :size="17" />
        </button>
      </form>
      <div class="auth-actions">
        <button
          type="button"
          class="button button-text"
          :disabled="state.busy"
          @click="registration = !registration"
        >
          {{ registration ? "已有账号，登录" : "创建账号" }}
        </button>
        <button
          type="button"
          class="button button-subtle"
          :disabled="state.busy"
          @click="state.restore"
        >
          恢复已有会话
        </button>
      </div>
    </section>
  </main>

  <div v-else class="workspace-shell">
    <aside class="sidebar" aria-label="项目与工作区导航">
      <section class="panel project-panel" aria-labelledby="project-title">
        <div class="sidebar-head">
          <h2 id="project-title"><AppIcon name="folder" :size="18" />项目</h2>
          <button
            type="button"
            class="button icon-button"
            aria-label="刷新列表"
            title="刷新列表"
            :disabled="state.busy"
            @click="state.action(state.loadProjects)"
          >
            <AppIcon name="refresh" :size="17" />
          </button>
        </div>
        <p v-if="!state.projects.length" class="muted project-empty">
          还没有项目，先创建一个。
        </p>
        <ul v-else class="project-list">
          <li v-for="p in state.projects" :key="p.id">
            <button
              type="button"
              class="project-button"
              :aria-pressed="state.selected === p.id"
              :disabled="state.busy"
              @click="state.selected !== p.id && state.select(p.id)"
            >
              <AppIcon name="film" :size="17" /><span
                ><strong>{{ p.name }}</strong
                ><small
                  >{{ scenarios[p.scenario] ?? p.scenario }} · 版本
                  {{ p.revision }}</small
                ></span
              >
            </button>
          </li>
        </ul>
        <details class="project-new" :open="!state.projects.length">
          <summary><AppIcon name="plus" :size="16" />新建项目</summary>
          <form
            class="project-form"
            @submit.prevent="state.createProject(name, scenario)"
          >
            <label
              >项目名称<input v-model="name" required maxlength="120"
            /></label>
            <label
              >场景<select v-model="scenario">
                <option
                  v-for="(title, key) in scenarios"
                  :key="key"
                  :value="key"
                >
                  {{ title }}
                </option>
              </select></label
            >
            <button class="button button-subtle" :disabled="state.busy">
              创建项目
            </button>
          </form>
        </details>
      </section>
      <nav v-if="project" class="panel sidebar-nav" aria-label="结果导航">
        <p class="eyebrow">WORKSPACE</p>
        <template v-if="state.run">
          <a v-for="item in nav" :key="item.href" :href="item.href"
            ><AppIcon :name="item.icon" :size="17" />{{ item.title
            }}<AppIcon name="chevron" :size="13"
          /></a>
        </template>
        <a href="#material-workspace"
          ><AppIcon name="layers" :size="17" />素材证据链<AppIcon
            name="chevron"
            :size="13"
          />
        </a>
        <a href="#media"
          ><AppIcon name="film" :size="17" />媒体探针<AppIcon
            name="chevron"
            :size="13"
        /></a>
      </nav>
    </aside>

    <main id="main-content" class="workspace-main" tabindex="-1">
      <section class="workspace-hero" aria-labelledby="workspace-title">
        <div class="hero-content">
          <p class="eyebrow kicker">
            <span aria-hidden="true"></span> PROJECT WORKSPACE
          </p>
          <h1 id="workspace-title">
            {{ project ? project.name : "项目工作台" }}
          </h1>
          <p class="hero-copy">
            {{
              project
                ? "复核故事素材是否充分、补拍是否完成，以及修改会影响哪些片段。"
                : "从项目列表选择一个项目，或创建新项目开始。"
            }}
          </p>
          <div v-if="project" class="hero-actions">
            <button
              type="button"
              class="button button-primary"
              :disabled="state.busy"
              @click="state.replay"
            >
              <AppIcon name="play" :size="17" />运行固定样例
            </button>
            <span class="pill mode-pill">同步规则回放</span>
          </div>
        </div>
        <div class="run-state" aria-label="回放进度">
          <span class="eyebrow">规则断言</span>
          <strong class="mono"
            >{{ state.run ? totals.passed : "—"
            }}<small v-if="state.run"> / {{ totals.total }}</small></strong
          >
          <span>{{ state.run ? "项通过" : "等待运行" }}</span>
          <div class="run-meter" aria-hidden="true">
            <i
              :style="{
                width: totals.total
                  ? `${(totals.passed / totals.total) * 100}%`
                  : `0%`,
              }"
            ></i>
          </div>
        </div>
      </section>
      <p v-if="state.error" class="notice error" role="alert">
        <AppIcon name="info" />{{ state.error }}
      </p>
      <p v-if="state.busy" class="notice" role="status">
        正在请求 API，请稍候…
      </p>
      <p v-if="project" class="notice mode-notice">
        <AppIcon name="info" /><span
          ><strong>固定输入演示</strong> ·
          人工标注的合成元数据，未调用模型，未生成生产版本。</span
        >
      </p>

      <ReplayResults
        v-if="state.run"
        :run="state.run"
        :evidence="state.bundle?.manifest.evidence ?? []"
      />
      <section v-else class="panel empty-state" aria-labelledby="empty-title">
        <span class="section-icon"
          ><AppIcon :name="project ? 'play' : 'folder'" :size="24"
        /></span>
        <h2 id="empty-title">
          {{ project ? "尚无规则回放结果" : "尚未选择项目" }}
        </h2>
        <p>
          {{
            project
              ? "运行固定样例后，这里将显示故事覆盖、补拍状态和局部编辑风险。"
              : "选择已有项目，或用项目栏创建一个新的工作区。"
          }}
        </p>
      </section>
      <MaterialWorkspace
        v-if="project"
        :key="project.id"
        :project-id="project.id"
        :token="state.token"
      />
      <section
        v-if="project"
        id="media"
        class="panel result-panel"
        aria-labelledby="media-title"
      >
        <div class="section-title">
          <span class="section-icon"><AppIcon name="film" /></span>
          <div>
            <p class="eyebrow">MEDIA UTILITIES</p>
            <h2 id="media-title">媒体工具探针</h2>
          </div>
        </div>
        <p class="section-copy">
          上传不超过 16 MiB 的授权音视频，只检查真实媒体解析，不会完成补拍任务。
        </p>
        <label class="upload-control"
          ><AppIcon name="upload" />选择媒体<input
            type="file"
            accept="video/*,audio/*"
            :disabled="state.busy"
            @change="upload"
        /></label>
        <details v-if="probeResult" class="disclosure probe-result" open>
          <summary>
            解析结果 <span>{{ probeName }}</span>
          </summary>
          <pre>{{ probeResult }}</pre>
        </details>
      </section>
    </main>
  </div>
  <footer class="footer">
    <span>ShadowWeaveAI</span><span>素材证据 / 补拍验证 / 编辑约束</span>
  </footer>
</template>

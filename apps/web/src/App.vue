<script setup lang="ts">
import { computed, ref } from "vue";
import { useWorkspace } from "./store";
const state = useWorkspace();
const email = ref(""),
  password = ref(""),
  registration = ref(false),
  name = ref("校园活动"),
  scenario = ref("campus"),
  probeResult = ref<unknown>(null);
const labels: Record<string, string> = {
  covered: "已有合格证据",
  insufficient: "素材不足",
  uncertain: "尚不确定",
  missing: "缺少支持素材",
};
const project = computed(() =>
  state.projects.find((p) => p.id === state.selected),
);
async function upload(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (file) probeResult.value = await state.probe(file);
}
</script>
<template>
  <header>
    <a href="#" class="brand">影织 <span>AI</span></a
    ><span class="badge">第一阶段 · 契约与可验证内核</span
    ><button
      v-if="state.token"
      class="quiet"
      @click="state.logout"
      :disabled="state.busy"
    >
      {{ state.user }} · 退出
    </button>
  </header>
  <main>
    <section class="intro">
      <p class="eyebrow">SHADOWWEAVE / PHASE 01</p>
      <h1>故事有据可依，<br />修改有界可控。</h1>
      <p>检查故事需要什么素材，验证局部修改是否保护已确认内容。</p>
    </section>
    <p v-if="state.error" role="alert" class="error">{{ state.error }}</p>
    <p v-if="state.busy" role="status">正在请求 API，请稍候…</p>
    <section v-if="!state.token" class="panel auth">
      <h2>{{ registration ? "创建账号" : "进入项目工作台" }}</h2>
      <p>登录后读取真实项目；规则演示使用明确标注的固定输入。</p>
      <form @submit.prevent="state.authenticate(email, password, registration)">
        <label
          >邮箱<input
            v-model="email"
            type="email"
            required
            autocomplete="username" /></label
        ><label
          >密码（至少 12 位）<input
            v-model="password"
            type="password"
            minlength="12"
            maxlength="128"
            required
            :autocomplete="
              registration ? 'new-password' : 'current-password'
            " /></label
        ><button :disabled="state.busy">
          {{ registration ? "注册并进入" : "登录" }}
        </button>
      </form>
      <div class="actions">
        <button class="quiet" @click="registration = !registration">
          {{ registration ? "已有账号，登录" : "创建账号" }}</button
        ><button class="quiet" :disabled="state.busy" @click="state.restore">
          恢复已有会话
        </button>
      </div>
    </section>
    <template v-else>
      <section class="panel">
        <div class="section-head">
          <h2>项目</h2>
          <button
            class="quiet"
            @click="state.action(state.loadProjects)"
            :disabled="state.busy"
          >
            刷新列表
          </button>
        </div>
        <form
          class="project-form"
          @submit.prevent="state.createProject(name, scenario)"
        >
          <label
            >项目名称<input v-model="name" required maxlength="120" /></label
          ><label
            >场景<select v-model="scenario">
              <option value="campus">校园活动</option>
              <option value="travel">旅行</option>
              <option value="family_friends">家庭朋友</option>
              <option value="vlog">个人 Vlog</option>
              <option value="organization">组织宣传</option>
            </select></label
          ><button :disabled="state.busy">创建项目</button>
        </form>
        <p v-if="!state.projects.length" class="muted">
          还没有项目。创建项目后可运行第一阶段规则样例。
        </p>
        <div class="project-list">
          <button
            v-for="p in state.projects"
            :key="p.id"
            class="project"
            :class="{ selected: state.selected === p.id }"
            @click="
              state.select(p.id);
              probeResult = null;
            "
          >
            <strong>{{ p.name }}</strong
            ><small>{{ p.scenario }} · revision {{ p.revision }}</small>
          </button>
        </div>
      </section>
      <section v-if="project" class="panel">
        <div class="section-head">
          <div>
            <p class="eyebrow">{{ project.name }}</p>
            <h2>可复核的规则演示</h2>
          </div>
          <button :disabled="state.busy" @click="state.replay">
            运行固定样例
          </button>
        </div>
        <p class="notice">
          模式：人工标注的合成元数据 /
          同步规则回放。未调用模型，未生成生产版本。
        </p>
        <p v-if="!state.run" class="muted">
          运行后查看四态覆盖、补拍验证以及修改被允许或拒绝的原因。
        </p>
      </section>
      <template v-if="state.run">
        <section class="panel">
          <div class="section-head">
            <h2>故事覆盖与证据</h2>
            <span class="badge">{{
              state.run.passed ? "样例检查通过" : "存在失败用例"
            }}</span>
          </div>
          <div class="cards">
            <article
              v-for="report in state.run.coverage"
              :key="report.node_key"
              class="card"
            >
              <small>{{ report.node_key }}</small>
              <h3>{{ labels[report.coverage] }}</h3>
              <p>可用时长 {{ report.usable_duration_ms }} ms</p>
              <p class="muted">{{ report.reason_codes.join(" / ") }}</p>
              <details>
                <summary>证据来源</summary>
                <pre>{{
                  state.bundle?.manifest.evidence.filter((e: any) =>
                    report.candidate_refs.includes(e.id),
                  )
                }}</pre>
              </details>
            </article>
          </div>
        </section>
        <section class="panel">
          <h2>补拍验证门</h2>
          <p>{{ state.run.capture.initial.instruction }}</p>
          <div class="steps">
            <span>初始：{{ state.run.capture.initial.state }}</span
            ><span>上传事件后：{{ state.run.capture.after_upload.state }}</span
            ><span
              >新证据验证后：{{
                state.run.capture.after_verification.state
              }}</span
            >
          </div>
          <p class="muted">
            这些状态由固定事实输入触发规则计算；上传本身不能满足故事要求。
          </p>
        </section>
        <section class="panel">
          <h2>局部修改与保护检查</h2>
          <p>
            目标：开场。预先批准范围：{{
              state.run.impact.approved_affected_keys.join("、")
            }}；依赖预报：{{
              state.run.impact.predicted_affected_keys.join("、")
            }}。
          </p>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>候选样例</th>
                  <th>结果</th>
                  <th>拒绝依据 / 差异</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(edit, key) in state.run.edits" :key="key">
                  <td>{{ key }}</td>
                  <td>
                    <span :class="edit.accepted ? 'pass' : 'reject'">{{
                      edit.accepted ? "允许" : "拒绝"
                    }}</span>
                  </td>
                  <td>
                    {{
                      edit.validation?.hard_errors.join("、") ||
                      edit.error_code ||
                      "约束检查通过"
                    }}
                    <details v-if="edit.validation">
                      <summary>完整差异</summary>
                      <pre>{{ edit.validation.diff }}</pre>
                    </details>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="muted">
            草案确认校验：{{
              state.run.confirmation.valid ? "通过" : "失败"
            }}；生产版本发布：{{
              state.run.confirmation.version_published ? "是" : "否"
            }}。
          </p>
        </section>
        <section class="panel">
          <h2>复核记录</h2>
          <p>数据版本 {{ state.run.dataset_version }} · 未调用模型</p>
          <p class="mono">
            代码 {{ state.run.code.commit }}
            {{
              state.run.code.dirty
                ? "（包含未提交变更，运行记录附源文件摘要）"
                : ""
            }}
          </p>
          <details>
            <summary>检查明细与输入摘要</summary>
            <pre
              >{{ state.run.checks }}
{{ state.run.input_hash }}</pre>
          </details>
        </section>
      </template>
      <section v-if="project" class="panel">
        <h2>媒体工具探针</h2>
        <p>
          上传不超过 16 MiB 的授权媒体，检查真实解析工具。此操作只返回探针结果。
        </p>
        <label class="file"
          >选择媒体<input
            type="file"
            accept="video/*,audio/*"
            @change="upload"
            :disabled="state.busy"
        /></label>
        <pre v-if="probeResult">{{ probeResult }}</pre>
      </section>
    </template>
  </main>
  <footer>ShadowWeaveAI · 证据覆盖 / 局部修改约束 / 可复核运行记录</footer>
</template>

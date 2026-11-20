<script setup lang="ts">
import { computed } from "vue";
import AppIcon from "./AppIcon.vue";
import CoverageCard from "./CoverageCard.vue";
import type { EvidenceSource, Replay } from "./contracts";
import { formatReason, label } from "./presentation";

const props = defineProps<{ run: Replay; evidence: EvidenceSource[] }>();
const risk = computed(() => props.run.impact.risk_budget);
const captureSteps = computed(() => [
  { title: "初始", state: props.run.capture.initial.state },
  { title: "上传事件后", state: props.run.capture.after_upload.state },
  { title: "新证据验证后", state: props.run.capture.after_verification.state },
]);
const checkCount = computed(() => Object.keys(props.run.checks).length);
</script>

<template>
  <section
    id="coverage"
    class="panel result-panel"
    aria-labelledby="coverage-title"
  >
    <div class="section-head">
      <div class="section-title">
        <span class="section-icon"><AppIcon name="layers" /></span>
        <div>
          <p class="eyebrow">01 / STORY COVERAGE</p>
          <h2 id="coverage-title">故事覆盖与证据</h2>
        </div>
      </div>
      <span class="pill" :data-tone="run.passed ? 'covered' : 'missing'">{{
        run.passed ? "样例检查通过" : "存在失败用例"
      }}</span>
    </div>
    <p class="section-copy">
      先看每个故事节点是否有足够素材，再展开逐需求证据核对依据。
    </p>
    <div class="coverage-grid">
      <CoverageCard
        v-for="(report, index) in run.coverage"
        :key="report.node_key"
        :index="index"
        :report="report"
        :evidence="evidence"
      />
    </div>
  </section>

  <section
    id="capture"
    class="panel result-panel"
    aria-labelledby="capture-title"
  >
    <div class="section-title">
      <span class="section-icon"><AppIcon name="camera" /></span>
      <div>
        <p class="eyebrow">02 / CAPTURE VERIFICATION</p>
        <h2 id="capture-title">补拍验证门</h2>
      </div>
    </div>
    <p class="section-copy">
      {{
        run.capture.initial.instruction
      }}。上传只表示已提交，只有新证据通过规则检查才能完成补拍。
    </p>
    <ol class="capture-steps">
      <li
        v-for="(step, index) in captureSteps"
        :key="step.title"
        :data-state="step.state"
      >
        <span class="step-index mono">0{{ index + 1 }}</span>
        <div>
          <strong>{{ label(step.state) }}</strong
          ><span>{{ step.title }}：{{ step.state }}</span>
        </div>
      </li>
    </ol>
    <div
      v-if="run.capture.uncertainty_blocks_fulfillment"
      class="notice warning"
    >
      <AppIcon name="info" />
      <div>
        <strong>证据不确定时，不能完成补拍</strong>
        <p>
          {{
            run.capture.uncertainty_report.uncertainty_reasons
              .map(formatReason)
              .join("；")
          }}。
        </p>
      </div>
    </div>
  </section>

  <section
    id="editing"
    class="panel result-panel"
    aria-labelledby="editing-title"
  >
    <div class="section-head">
      <div class="section-title">
        <span class="section-icon"><AppIcon name="shield" /></span>
        <div>
          <p class="eyebrow">03 / EDIT GUARDRAILS</p>
          <h2 id="editing-title">局部修改与保护检查</h2>
        </div>
      </div>
      <span class="pill" :data-tone="risk.severity">{{
        label(risk.severity)
      }}</span>
    </div>
    <p class="section-copy">
      先预报修改可能影响的片段，再逐个检查候选改动是否突破批准范围或锁定约束。
    </p>
    <dl class="risk-metrics">
      <div>
        <dt>预计影响片段</dt>
        <dd>
          {{ risk.affected_clip_count }}
          <small>/ {{ risk.total_clip_count }}</small>
        </dd>
      </div>
      <div>
        <dt>预计影响比例</dt>
        <dd>
          {{
            (risk.affected_ratio * 100).toLocaleString("zh-CN", {
              maximumFractionDigits: 1,
            })
          }}<small>%</small>
        </dd>
      </div>
      <div>
        <dt>锁定冲突</dt>
        <dd>{{ risk.locked_conflict_count }} <small>处</small></dd>
      </div>
    </dl>
    <div class="risk-context">
      <div>
        <span>已批准范围</span
        ><strong>{{
          run.impact.approved_affected_keys.map(label).join("、") || "无"
        }}</strong>
      </div>
      <div>
        <span>未批准影响</span
        ><strong>{{
          risk.unapproved_affected_keys.map(label).join("、") || "无"
        }}</strong>
      </div>
    </div>
    <p v-if="risk.reasons.length" class="risk-reason">
      {{ risk.reasons.map(formatReason).join("；") }}
    </p>
    <details class="disclosure path-disclosure">
      <summary>
        依赖传播路径
        <span>{{ Object.keys(run.impact.propagation_paths).length }} 条</span>
      </summary>
      <ul class="path-list">
        <li v-for="(path, key) in run.impact.propagation_paths" :key="key">
          <template v-for="(clip, index) in path" :key="clip">
            <AppIcon v-if="index" name="arrow" :size="14" /><span>{{
              label(clip)
            }}</span>
          </template>
        </li>
      </ul>
    </details>
    <div
      class="table-wrap"
      role="region"
      aria-label="候选编辑检查"
      tabindex="0"
    >
      <table>
        <thead>
          <tr>
            <th scope="col">候选编辑</th>
            <th scope="col">结果</th>
            <th scope="col">拒绝依据 / 差异</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(edit, key) in run.edits" :key="key">
            <th scope="row">{{ label(key) }}</th>
            <td>
              <span
                class="pill"
                :data-tone="edit.accepted ? 'covered' : 'missing'"
                >{{ edit.accepted ? "允许" : "拒绝" }}</span
              >
            </td>
            <td>
              <span
                :title="
                  edit.validation?.hard_errors.join(' / ') || edit.error_code
                "
              >
                {{
                  edit.validation?.hard_errors.map(label).join("、") ||
                  (edit.error_code && label(edit.error_code)) ||
                  "约束检查通过"
                }}
              </span>
              <details
                v-if="edit.validation"
                class="disclosure diff-disclosure"
              >
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
        run.confirmation.valid ? "通过" : "失败"
      }}；生产版本发布：{{ run.confirmation.version_published ? "是" : "否" }}。
    </p>
  </section>

  <section class="panel result-panel" aria-labelledby="review-title">
    <div class="section-title">
      <span class="section-icon"><AppIcon name="code" /></span>
      <div>
        <p class="eyebrow">AUDIT TRAIL</p>
        <h2 id="review-title">复核记录</h2>
      </div>
    </div>
    <dl class="audit-grid">
      <div>
        <dt>数据版本</dt>
        <dd class="mono">{{ run.dataset_version }}</dd>
      </div>
      <div>
        <dt>模型调用</dt>
        <dd>{{ run.model_called ? "已调用" : "未调用" }}</dd>
      </div>
      <div>
        <dt>代码提交</dt>
        <dd class="mono" :title="run.code.commit">
          {{ run.code.commit.slice(0, 12)
          }}{{ run.code.dirty ? " · 含未提交变更" : "" }}
        </dd>
      </div>
    </dl>
    <details class="disclosure">
      <summary>
        检查明细与输入摘要 <span>{{ checkCount }} 项</span>
      </summary>
      <pre
        >{{ run.checks }}
输入摘要：{{ run.input_hash }}
代码提交：{{ run.code.commit }}</pre>
    </details>
  </section>
</template>

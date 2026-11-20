<script setup lang="ts">
import { computed } from "vue";
import type { Coverage, EvidenceSource } from "./contracts";
import { coverageLabels, formatReason, label, seconds } from "./presentation";

const props = defineProps<{
  index: number;
  report: Coverage;
  evidence: EvidenceSource[];
}>();
const sources = computed(() => {
  const candidates = new Set(props.report.candidate_refs);
  return props.evidence.filter((source) => candidates.has(source.id));
});
const selected = computed(() => new Set(props.report.selected_evidence_refs));
</script>

<template>
  <article class="coverage-card" :data-state="report.coverage">
    <div class="coverage-card-head">
      <span class="mono node-index">{{
        String(index + 1).padStart(2, "0")
      }}</span>
      <span class="pill" :data-tone="report.coverage">{{
        coverageLabels[report.coverage]
      }}</span>
    </div>
    <h3>{{ label(report.node_key) }}</h3>
    <div class="coverage-duration">
      <strong
        >{{ seconds(report.usable_duration_ms) }} <small>秒</small></strong
      >
      <span>最低 {{ seconds(report.minimum_duration_ms) }} 秒</span>
    </div>
    <div class="coverage-meter" aria-hidden="true">
      <span
        :style="{
          width: `${Math.min((report.usable_duration_ms / report.minimum_duration_ms) * 100, 100)}%`,
        }"
      ></span>
    </div>
    <p class="coverage-reason">
      {{ report.reason_codes.map(formatReason).join("；") }}
    </p>
    <p v-if="report.uncertainty_reasons.length" class="coverage-reason">
      {{ report.uncertainty_reasons.map(formatReason).join("；") }}
    </p>
    <details class="disclosure coverage-details">
      <summary>
        逐需求证据 <span>{{ selected.size }} 项选中</span>
      </summary>
      <div
        v-for="item in report.requirement_results"
        :key="item.requirement_key"
        class="requirement"
      >
        <strong
          >{{ label(item.requirement_key) }} ·
          {{ coverageLabels[item.state] }}</strong
        >
        <p>
          候选 {{ item.candidate_refs.length }} · 合格
          {{ item.qualified_refs.length }} · 选中
          {{ item.selected_refs.length }}
        </p>
        <p>{{ item.reason_codes.map(formatReason).join("；") }}</p>
      </div>
      <p v-if="!report.selection_complete" class="muted">
        尚未形成足以覆盖节点的证据集。
      </p>
      <ul v-if="sources.length" class="evidence-list">
        <li v-for="source in sources" :key="source.id">
          <strong
            >{{ seconds(source.in_ms) }}–{{ seconds(source.out_ms) }} 秒 ·
            {{ label(source.method) }}</strong
          >
          <span
            >{{ selected.has(source.id) ? "已选中" : "未选中" }} ·
            {{ label(source.semantic_support) }} ·
            {{ source.quality_usable ? "质量达标" : "质量不足" }}</span
          >
          <code>{{ source.id }}</code>
        </li>
      </ul>
      <p v-else class="muted">没有候选证据来源。</p>
      <details v-if="sources.length" class="disclosure">
        <summary>原始证据记录</summary>
        <pre>{{ sources }}</pre>
      </details>
    </details>
  </article>
</template>

<script setup lang="ts">
defineProps<{ name: string; size?: number }>();
const paths: Record<string, string> = {
  weave: "M3 6h5l4 6 4-6h5M3 18h5l4-6 4 6h5M3 10h3m12 0h3M3 14h3m12 0h3",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  plus: "M12 5v14M5 12h14",
  play: "m9 5 12 7-12 7z",
  arrow: "M4 12h15m-6-6 6 6-6 6",
  refresh:
    "M20 7v5h-5M4 17v-5h5m-4-2a7 7 0 0 1 12-4l3 6m-16 0 3 6a7 7 0 0 0 12-4",
  logout: "M10 4H5v16h5m4-12 4 4-4 4m-5-4h9",
  layers: "m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5",
  camera: "M3 7h5l2-3h4l2 3h5v13H3zM15 13a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  shield: "m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Zm-3 9 2 2 4-4",
  film: "M3 4h18v16H3zM7 4v16M17 4v16M3 9h4m-4 6h4m10-6h4m-4 6h4",
  code: "m8 6-6 6 6 6m8-12 6 6-6 6M14 4l-4 16",
  check: "m5 12 4 4L19 6",
  info: "M12 11v5m0-8h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
  folder: "M3 6h7l2 3h9v10H3z",
  upload: "M12 16V4m-5 5 5-5 5 5M4 16v4h16v-4",
  chevron: "m9 5 7 7-7 7",
};
</script>

<template>
  <svg
    :width="size ?? 18"
    :height="size ?? 18"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.65"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path :d="paths[name]" />
  </svg>
</template>

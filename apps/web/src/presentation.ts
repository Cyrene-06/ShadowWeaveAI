export const scenarios: Record<string, string> = {
  campus: "校园活动",
  travel: "旅行",
  family_friends: "家庭朋友",
  vlog: "个人 Vlog",
  organization: "组织宣传",
};

export const coverageLabels = {
  covered: "已覆盖",
  insufficient: "素材不足",
  uncertain: "尚不确定",
  missing: "缺少素材",
};

const translations: Record<string, string> = {
  opening: "开场环境",
  process: "活动过程",
  interview: "人物感受",
  ending: "结束告别",
  environment: "环境交代",
  activity: "活动过程",
  feeling: "人物感受",
  farewell: "告别镜头",
  "opening-title": "开场字幕",
  minimum_sufficient_evidence_selected: "已选出一组满足要求的证据",
  quality_or_duration_shortfall: "命中素材的质量或时长未达到要求",
  node: "故事节点",
  duration_below_minimum: "可用时长低于最低要求",
  no_supporting_evidence: "未找到支持该要求的素材",
  qualified_evidence: "存在合格证据",
  search_incomplete: "检索尚未完成",
  semantic_unknown: "素材语义未确认",
  required_evidence_uncertain: "必需证据仍不明确",
  quality_unusable: "素材质量不合格",
  human_annotation: "人工标注",
  tool_analysis: "工具分析",
  model_observation: "模型观察",
  supported: "语义支持",
  unsupported: "语义不支持",
  unknown: "语义未知",
  low: "低风险",
  medium: "中风险",
  high: "高风险",
  blocked: "已阻断",
  locked_content_in_predicted_impact: "预计影响锁定内容",
  predicted_impact_exceeds_approved_scope: "预计影响超出批准范围",
  broad_dependency_blast_radius: "依赖传播范围较广",
  LOCKED_CONTENT_CHANGED: "锁定内容发生变化",
  SCOPE_APPROVAL_REQUIRED: "超出批准范围",
  INVALID_TIMELINE: "时间线不合法",
  legal: "合法等长替换",
  locked_change: "修改锁定片段",
  locked_delete: "删除锁定片段",
  locked_rekey: "更换锁定片段标识",
  locked_move: "移动锁定片段",
  outside_update: "更新范围外片段",
  outside_add: "新增范围外片段",
  outside_delete: "删除范围外片段",
  dependency_change: "改动片段依赖",
  cycle: "引入循环依赖",
  open: "待补拍",
  submitted: "已提交，等待验证",
  fulfilled: "证据已验证",
};

export function label(value: string): string {
  return Object.hasOwn(translations, value) ? translations[value] : value;
}

export function formatReason(reason: string): string {
  return reason.split(":").map(label).join("：");
}

export function seconds(ms: number): string {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 3 }).format(
    ms / 1000,
  );
}

import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import catalog from "../../../packages/contracts/schema/catalog.json";

export type Json =
  null | boolean | number | string | Json[] | { [key: string]: Json };
const schemas: Record<string, object> = catalog.models;
const ajv = new Ajv2020({ allErrors: true, useDefaults: true, strict: false });
addFormats(ajv);
const validators = Object.fromEntries(
  Object.entries(schemas).map(([name, schema]) => [name, ajv.compile(schema)]),
);

// JSON Schema covers structure; these are the shared, documented semantic invariants.
function semantics(value: Json): void {
  if (Array.isArray(value)) {
    value.forEach(semantics);
    return;
  }
  if (value === null || typeof value !== "object") return;
  const v = value as Record<string, any>;
  if ("in_ms" in v && "out_ms" in v && v.out_ms <= v.in_ms)
    throw Error("Invalid half-open interval");
  if (
    "media_type" in v &&
    "duration_ms" in v &&
    (v.media_type === "image") !== (v.duration_ms === null)
  )
    throw Error("Invalid media duration");
  if (v.kind === "reshoot" && !v.node_key) throw Error("Reshoot needs a node");
  if (
    "fps_num" in v &&
    !(
      (v.width === 1920 && v.height === 1080) ||
      (v.width === 1280 && v.height === 720)
    )
  )
    throw Error("Unsupported output preset");
  if ("dst_in_ms" in v) {
    if (v.dst_out_ms <= v.dst_in_ms) throw Error("Invalid target interval");
    if (v.kind === "video" || v.kind === "audio") {
      if (
        !v.asset_id ||
        !v.segment_id ||
        v.src_in_ms === null ||
        v.src_out_ms === null ||
        v.src_out_ms <= v.src_in_ms
      )
        throw Error("Invalid media source");
      if (
        (v.src_out_ms - v.src_in_ms) * v.speed_den !==
        (v.dst_out_ms - v.dst_in_ms) * v.speed_num
      )
        throw Error("Duration mismatch");
    } else {
      if (
        v.src_in_ms !== null ||
        v.src_out_ms !== null ||
        v.speed_num !== 1 ||
        v.speed_den !== 1
      )
        throw Error("Invalid non-timed source");
      if (
        v.kind === "subtitle" &&
        (v.asset_id !== null || v.segment_id !== null)
      )
        throw Error("Subtitle cannot reference media");
      if (v.kind === "image" && !v.asset_id) throw Error("Image needs source");
    }
  }
  Object.values(value).forEach(semantics);
}

export function parseContract<T = Record<string, any>>(
  model: string,
  input: unknown,
): T {
  const value = structuredClone(input) as Json;
  const validate = validators[model];
  if (!validate || !validate(value))
    throw Error("Contract validation failed: " + model);
  semantics(value);
  return value as T;
}

export interface Project {
  id: string;
  name: string;
  scenario: string;
  revision: number;
  head_revision: number;
}
export interface Coverage {
  node_key: string;
  coverage: string;
  usable_duration_ms: number;
  reason_codes: string[];
  candidate_refs: string[];
}
export interface Replay {
  passed: boolean;
  mode: string;
  model_called: boolean;
  dataset_version: string;
  input_hash: string;
  coverage: Coverage[];
  checks: Record<string, boolean>;
  edits: Record<
    string,
    {
      accepted: boolean;
      validation?: { hard_errors: string[]; diff: unknown };
      error_code?: string;
      message?: string;
    }
  >;
  capture: {
    initial: Record<string, any>;
    after_upload: Record<string, any>;
    after_verification: Record<string, any>;
  };
  impact: Record<string, any>;
  code: { commit: string; dirty: boolean };
  confirmation: { valid: boolean; version_published: boolean };
}

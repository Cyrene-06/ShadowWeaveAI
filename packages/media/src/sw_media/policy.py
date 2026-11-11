from collections import defaultdict, deque
from uuid import uuid4

from sw_contracts import EDL, EditDraft, ImpactReport, digest
from sw_contracts.validation import RuleError, resolve_manifest


def clip_map(edl: EDL):
    result = {}
    track_keys = set()
    positions = set()
    for track in edl.tracks:
        if track.track_key in track_keys or track.position in positions:
            raise RuleError("INVALID_TIMELINE", "duplicate track key/position")
        track_keys.add(track.track_key)
        positions.add(track.position)
        for c in track.clips:
            if c.clip_key in result:
                raise RuleError("INVALID_TIMELINE", "duplicate stable clip key")
            result[c.clip_key] = {
                **c.model_dump(mode="json"),
                "track_key": track.track_key,
                "track_kind": track.kind,
                "track_position": track.position,
                "dependencies": sorted(c.dependencies),
            }
    return result


def content_hash(edl):
    return digest(
        {
            "duration_ms": edl.duration_ms,
            "output": edl.output.model_dump(),
            "tracks": sorted(
                [{"track_key": t.track_key, "kind": t.kind, "position": t.position} for t in edl.tracks],
                key=lambda t: t["track_key"],
            ),
            "clips": clip_map(edl),
        }
    )


def dependency_graph(edl):
    clips = clip_map(edl)
    dependents = defaultdict(list)
    indegree = {k: 0 for k in clips}
    for key, clip in clips.items():
        if len(set(clip["dependencies"])) != len(clip["dependencies"]):
            raise RuleError("INVALID_TIMELINE", "duplicate dependency")
        for prerequisite in clip["dependencies"]:
            if prerequisite not in clips or prerequisite == key:
                raise RuleError("INVALID_TIMELINE", "dangling/self dependency")
            dependents[prerequisite].append(key)
            indegree[key] += 1
    queue = deque(k for k, degree in indegree.items() if degree == 0)
    seen = 0
    while queue:
        key = queue.popleft()
        seen += 1
        for child in dependents[key]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if seen != len(clips):
        raise RuleError("INVALID_TIMELINE", "dependency cycle")
    return dependents


def predict_impact(base, targets, approved=None, new_keys=(), max_nodes=1000, scope_approval_ref=None):
    dependents = dependency_graph(base)
    clips = clip_map(base)
    if not targets or not set(targets) <= clips.keys():
        raise RuleError("INVALID_ARGUMENT", "unknown/empty edit target")
    found = set(targets)
    causes = {k: ["explicit_target"] for k in targets}
    queue = deque(sorted(targets))
    while queue:
        key = queue.popleft()
        for child in sorted(dependents[key]):
            causes.setdefault(child, []).append(f"depends_on:{key}")
            if child not in found:
                found.add(child)
                queue.append(child)
        if len(found) > max_nodes:
            raise RuleError("BUDGET_EXCEEDED", "full_replan_required")
    predicted = found | set(new_keys)
    allowed = predicted if approved is None else set(approved)
    if not allowed <= (clips.keys() | set(new_keys)) or not set(targets) <= allowed:
        raise RuleError("INVALID_ARGUMENT", "invalid approved scope")
    return ImpactReport(
        base_content_hash=content_hash(base),
        requested_target_keys=sorted(set(targets)),
        predicted_affected_keys=sorted(predicted),
        approved_affected_keys=sorted(allowed),
        causes=causes,
        scope_approval_ref=scope_approval_ref or uuid4(),
        lock_conflicts=sorted(k for k in predicted if k in clips and clips[k]["locked"]),
    )


def validate_edl(edl, manifest):
    assets, segments = resolve_manifest(manifest)
    dependency_graph(edl)
    compatible = {
        "video": {"video", "image"},
        "subtitle": {"subtitle"},
        "voiceover": {"audio"},
        "music": {"audio"},
        "ambience": {"audio"},
    }
    for track in edl.tracks:
        previous_end = 0
        for clip in sorted(track.clips, key=lambda c: c.dst_in_ms):
            if clip.kind not in compatible[track.kind] or clip.dst_out_ms > edl.duration_ms:
                raise RuleError("INVALID_TIMELINE", "track/target range violation")
            if track.kind == "video" and clip.dst_in_ms < previous_end:
                raise RuleError("INVALID_TIMELINE", "overlap requires future transition implementation")
            previous_end = clip.dst_out_ms
            if clip.kind in {"video", "audio"}:
                asset, segment = assets.get(clip.asset_id), segments.get(clip.segment_id)
                if (
                    not asset
                    or not segment
                    or segment.asset_id != clip.asset_id
                    or asset.media_type != clip.kind
                ):
                    raise RuleError("INVALID_TIMELINE", "invalid source/segment/type")
                if clip.src_in_ms < segment.in_ms or clip.src_out_ms > segment.out_ms:
                    raise RuleError("INVALID_TIMELINE", "source outside segment")
            if clip.kind == "image" and (
                clip.asset_id not in assets or assets[clip.asset_id].media_type != "image"
            ):
                raise RuleError("INVALID_TIMELINE", "invalid image source")
            if clip.kind == "subtitle" and not isinstance(clip.config.get("text"), str):
                raise RuleError("INVALID_TIMELINE", "subtitle text required")


def compare_edl(base, candidate):
    before, after = clip_map(base), clip_map(candidate)
    return {
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "updated": sorted(k for k in before.keys() & after.keys() if before[k] != after[k]),
        "global_changed": (
            base.duration_ms != candidate.duration_ms
            or base.output != candidate.output
            or {t.track_key: (t.kind, t.position) for t in base.tracks}
            != {t.track_key: (t.kind, t.position) for t in candidate.tracks}
        ),
    }


def validate_edit(base, candidate, impact, manifest, unlock_keys=()):
    validate_edl(base, manifest)
    validate_edl(candidate, manifest)
    if impact.base_content_hash != content_hash(base):
        raise RuleError("VERSION_CONFLICT", "impact report bound to a different base")
    if len(set(unlock_keys)) != len(unlock_keys):
        raise RuleError("INVALID_ARGUMENT", "duplicate unlock keys")
    before, after = clip_map(base), clip_map(candidate)
    if not set(unlock_keys) <= {k for k, v in before.items() if v["locked"]}:
        raise RuleError("INVALID_ARGUMENT", "unlock requires existing locked keys")
    diff = compare_edl(base, candidate)
    changed = set(diff["added"] + diff["removed"] + diff["updated"])
    locked = {
        k: (k in after and before[k] == after[k])
        for k, v in before.items()
        if v["locked"] and k not in unlock_keys
    }
    outside = changed - set(impact.approved_affected_keys)
    errors = []
    if not all(locked.values()):
        errors.append("LOCKED_CONTENT_CHANGED")
    if outside or diff["global_changed"]:
        errors.append("SCOPE_APPROVAL_REQUIRED")
    return {
        "hard_errors": errors,
        "locked_hash_comparison": locked,
        "outside_scope_comparison": sorted(outside),
        "rules_version": "policy-1",
        "diff": diff,
    }


def make_draft(project_id, base_version_id, base_revision, base, candidate, impact, manifest, unlock_keys=()):
    if str(project_id) != str(manifest.project_id):
        raise RuleError("FORBIDDEN", "Draft and evidence belong to different projects")
    report = validate_edit(base, candidate, impact, manifest, unlock_keys)
    if report["hard_errors"]:
        raise RuleError("INVALID_TIMELINE", ",".join(report["hard_errors"]))
    fields = dict(
        project_id=project_id,
        base_version_id=base_version_id,
        base_revision=base_revision,
        base_content_hash=content_hash(base),
        candidate_edl=candidate,
        impact_report=impact,
        diff=report["diff"],
        validation_report=report,
        requested_unlock_clip_keys=sorted(unlock_keys),
        state="ready",
    )
    provisional = EditDraft(**fields, payload_hash="0" * 64)
    fields["payload_hash"] = digest(provisional.model_dump(mode="json", exclude={"payload_hash"}))
    return EditDraft(**fields)


def confirm_contract(draft, base_revision, payload_hash, unlock_clip_keys):
    if base_revision != draft.base_revision:
        raise RuleError("VERSION_CONFLICT", "project head changed")
    actual = digest(draft.model_dump(mode="json", exclude={"payload_hash"}))
    if payload_hash != actual or draft.payload_hash != actual or draft.validation_report.get("hard_errors"):
        raise RuleError("INVALID_ARGUMENT", "draft content/hash invalid")
    if sorted(unlock_clip_keys) != draft.requested_unlock_clip_keys:
        raise RuleError("INVALID_ARGUMENT", "unlock keys differ from reviewed draft")
    return {"valid": True, "mode": "contract_only", "version_published": False}

"""Build project-authored, deterministic metadata; no real media or model observations."""

import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sw_contracts import Asset, Segment, Evidence, EvidenceManifest, StoryNode, CaptureTask, EDL, digest

ROOT = Path(__file__).resolve().parents[1]


def uid(label):
    return str(uuid5(NAMESPACE_URL, "shadowweave-phase-one/" + label))


def build():
    project = uid("campus")
    assets, segments, evidence = [], [], []
    for label, requirement, quality in [
        ("opening", "environment", True),
        ("process", "activity", True),
        ("interview", "feeling", False),
        ("ending", "farewell", True),
        ("replacement", "environment", True),
    ]:
        asset = Asset(
            id=uid("asset/" + label),
            project_id=project,
            media_type="video",
            duration_ms=12000,
            sha256=hashlib.sha256(("SYNTHETIC-METADATA:" + label).encode()).hexdigest(),
        )
        segment = Segment(
            id=uid("segment/" + label),
            project_id=project,
            asset_id=asset.id,
            analysis_run_id=uid("analysis/" + label),
            in_ms=0,
            out_ms=12000,
        )
        assets.append(asset)
        segments.append(segment)
        if label != "ending":
            evidence.append(
                Evidence(
                    id=uid("evidence/" + label),
                    project_id=project,
                    asset_id=asset.id,
                    segment_id=segment.id,
                    analysis_run_id=segment.analysis_run_id,
                    in_ms=0,
                    out_ms=6000,
                    method="human_annotation",
                    semantic_support="supported",
                    quality_usable=quality,
                    requirement_keys=[requirement],
                )
            )
    manifest = EvidenceManifest(
        project_id=project,
        dataset_version="campus-fixed-1",
        assets=assets,
        segments=segments,
        evidence=evidence,
    )
    nodes = [
        StoryNode(
            project_id=project, node_key=key, goal=goal, requirements=[requirement], minimum_duration_ms=4000
        )
        for key, goal, requirement in [
            ("opening", "开场环境", "environment"),
            ("process", "活动过程", "activity"),
            ("interview", "人物感受", "feeling"),
            ("ending", "结束告别", "farewell"),
        ]
    ]
    task = CaptureTask(
        id=uid("capture/farewell"),
        project_id=project,
        node_key="ending",
        source_storyboard_id=uid("storyboard/base"),
        source_storyboard_revision=1,
        instruction="补充活动结束时的告别镜头，至少四秒",
        purpose="支持结束告别节点",
    )

    def clip(key, source, start, locked=False):
        return dict(
            clip_key=key,
            kind="video",
            asset_id=uid("asset/" + source),
            segment_id=uid("segment/" + source),
            src_in_ms=0,
            src_out_ms=6000,
            dst_in_ms=start,
            dst_out_ms=start + 6000,
            locked=locked,
        )

    base = EDL.model_validate(
        dict(
            duration_ms=24000,
            tracks=[
                dict(
                    track_key="video-main",
                    kind="video",
                    position=0,
                    clips=[
                        clip("opening", "opening", 0),
                        clip("process", "process", 6000),
                        clip("interview", "interview", 12000, True),
                        clip("ending", "ending", 18000, True),
                    ],
                ),
                dict(
                    track_key="subtitles",
                    kind="subtitle",
                    position=1,
                    clips=[
                        dict(
                            clip_key="opening-title",
                            kind="subtitle",
                            dst_in_ms=0,
                            dst_out_ms=4000,
                            dependencies=["opening"],
                            config={"text": "校园的一天"},
                        )
                    ],
                ),
            ],
        )
    )
    legal = base.model_dump(mode="json")
    legal["tracks"][0]["clips"][0].update(
        asset_id=uid("asset/replacement"), segment_id=uid("segment/replacement")
    )
    variants = {"legal": legal}
    import copy

    for name in [
        "locked_change",
        "locked_delete",
        "locked_rekey",
        "locked_move",
        "outside_update",
        "outside_add",
        "outside_delete",
        "dependency_change",
        "cycle",
    ]:
        variants[name] = copy.deepcopy(legal)
    variants["locked_change"]["tracks"][0]["clips"][2]["config"] = {"crop": "changed"}
    variants["locked_delete"]["tracks"][0]["clips"].pop(2)
    variants["locked_rekey"]["tracks"][0]["clips"][2]["clip_key"] = "new-interview"
    moved = variants["locked_move"]["tracks"][0]["clips"].pop(2)
    variants["locked_move"]["tracks"].append(
        dict(track_key="video-alt", kind="video", position=2, clips=[moved])
    )
    variants["outside_update"]["tracks"][0]["clips"][1]["config"] = {"exposure": 1}
    added = dict(
        clip_key="extra-title", kind="subtitle", dst_in_ms=6000, dst_out_ms=7000, config={"text": "extra"}
    )
    variants["outside_add"]["tracks"][1]["clips"].append(added)
    variants["outside_delete"]["tracks"][1]["clips"].clear()
    variants["dependency_change"]["tracks"][1]["clips"][0]["dependencies"] = ["process"]
    variants["cycle"]["tracks"][0]["clips"][0]["dependencies"] = ["opening-title"]
    raw = dict(
        schema_version="1.0",
        dataset_version="campus-fixed-1",
        mode="fixed_input",
        model_called=False,
        provenance={
            "source": "project-authored synthetic metadata and human annotations",
            "scope": "rule validation only",
            "contains_real_media": False,
            "license_note": "No third-party footage; not evidence of model accuracy.",
        },
        manifest=manifest.model_dump(mode="json"),
        nodes=[n.model_dump(mode="json") for n in nodes],
        capture_task=task.model_dump(mode="json"),
        base_edl=base.model_dump(mode="json"),
        candidates=variants,
        expected={
            "coverage": {
                "opening": "covered",
                "process": "covered",
                "interview": "insufficient",
                "ending": "missing",
            },
            "incomplete_ending": "uncertain",
            "submitted": "submitted",
            "verified": "fulfilled",
            "edits": {key: key == "legal" for key in variants},
        },
        base_version_id=uid("version/base"),
        base_revision=0,
    )
    path = ROOT / "examples/phase-1/campus.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("fixture:", path.relative_to(ROOT), "sha256:", digest(raw))


if __name__ == "__main__":
    build()

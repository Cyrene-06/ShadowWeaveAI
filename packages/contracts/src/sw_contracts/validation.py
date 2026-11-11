from .models import EvidenceManifest


class RuleError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def resolve_manifest(manifest: EvidenceManifest):
    assets = {a.id: a for a in manifest.assets}
    segments = {s.id: s for s in manifest.segments}
    if len(assets) != len(manifest.assets) or len(segments) != len(manifest.segments):
        raise RuleError("INVALID_ARGUMENT", "duplicate asset/segment IDs")
    if len({e.id for e in manifest.evidence}) != len(manifest.evidence):
        raise RuleError("INVALID_ARGUMENT", "duplicate evidence IDs")
    for a in assets.values():
        if a.project_id != manifest.project_id or a.state != "ready":
            raise RuleError("INVALID_ARGUMENT", "asset unavailable or outside project")
    for s in segments.values():
        a = assets.get(s.asset_id)
        if (
            a is None
            or s.project_id != manifest.project_id
            or a.duration_ms is None
            or s.out_ms > a.duration_ms
        ):
            raise RuleError("INVALID_ARGUMENT", "invalid segment source/project/interval")
    for e in manifest.evidence:
        s = segments.get(e.segment_id)
        if (
            s is None
            or e.project_id != manifest.project_id
            or e.asset_id != s.asset_id
            or e.analysis_run_id != s.analysis_run_id
        ):
            raise RuleError("INVALID_ARGUMENT", "evidence source/analysis mismatch")
        if e.in_ms < s.in_ms or e.out_ms > s.out_ms:
            raise RuleError("INVALID_ARGUMENT", "evidence outside segment")
    return assets, segments

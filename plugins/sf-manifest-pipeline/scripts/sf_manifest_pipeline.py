#!/usr/bin/env python3
"""Local Salesforce metadata review workflow for project leaders."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path.cwd()
STATE_DIR = ROOT / ".leader-review"
STANDARDS_FILE = STATE_DIR / "metadata-standards.md"
CONFIG_FILE = STATE_DIR / "config.json"
HISTORY_FILE = STATE_DIR / "history" / "metadata-change-history.jsonl"
MANIFEST_DIR = STATE_DIR / "manifests"
REPORT_DIR = STATE_DIR / "reports"
NS = "http://soap.sforce.com/2006/04/metadata"
ET.register_namespace("", NS)

DEFAULT_CONFIG = {
    "apiVersion": None,
    "firstUse": {
        "maxMembersPerManifest": 500,
        "excludedMetadata": [
            "StandardValueSet"
        ]
    },
    "smartRetrieve": {
        "alwaysIncludeMetadataTypes": [
            "ApexClass",
            "ApexTrigger",
            "LightningComponentBundle",
            "AuraDefinitionBundle",
            "Flow",
            "CustomObject",
            "CustomField",
            "PermissionSet",
            "Profile",
            "CustomMetadata"
        ],
        "ignoreMetadataTypes": [],
        "minHistoryCountForComponent": 2,
        "lookbackDays": 120
    },
    "analysis": {
        "highRiskPathPatterns": [
            "classes/.*Trigger.*",
            "triggers/",
            "flows/",
            "objects/.*/fields/",
            "permissionsets/",
            "profiles/"
        ]
    }
}


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(cmd))
    result = subprocess.run(cmd, text=True, capture_output=True)
    if check and result.returncode != 0:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG.copy()
    with CONFIG_FILE.open(encoding="utf-8") as fh:
        current = json.load(fh)
    return deep_merge(DEFAULT_CONFIG.copy(), current)


def deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_state() -> None:
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / "history").mkdir(exist_ok=True)
    MANIFEST_DIR.mkdir(exist_ok=True)
    REPORT_DIR.mkdir(exist_ok=True)
    if not STANDARDS_FILE.exists():
        STANDARDS_FILE.write_text("", encoding="utf-8")
    if not CONFIG_FILE.exists():
        write_json(CONFIG_FILE, DEFAULT_CONFIG)
    if not HISTORY_FILE.exists():
        HISTORY_FILE.write_text("", encoding="utf-8")


def init_workspace(_: argparse.Namespace) -> None:
    if not (ROOT / ".git").exists():
        run(["git", "init"])
    ensure_state()
    print(f"Initialized leader review workspace at {STATE_DIR}")


def sf_flags(config: dict) -> list[str]:
    version = config.get("apiVersion")
    return ["--api-version", str(version)] if version else []


def generate_full_manifest(args: argparse.Namespace) -> None:
    ensure_state()
    config = load_config()
    full_dir = MANIFEST_DIR / "full"
    chunk_dir = MANIFEST_DIR / "chunks"
    full_dir.mkdir(parents=True, exist_ok=True)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "sf", "project", "generate", "manifest",
        "--from-org", args.org,
        "--output-dir", str(full_dir),
        "--name", "package-full",
    ] + sf_flags(config)
    for metadata_type in config["firstUse"].get("excludedMetadata", []):
        cmd.extend(["--excluded-metadata", metadata_type])
    run(cmd)
    full_manifest = full_dir / "package-full.xml"
    split_manifest(full_manifest, chunk_dir, args.max_members or config["firstUse"]["maxMembersPerManifest"])


def split_manifest(package_xml: Path, output_dir: Path, max_members: int) -> None:
    tree = ET.parse(package_xml)
    root = tree.getroot()
    version = root.find(f"{{{NS}}}version")
    chunks: list[list[ET.Element]] = []
    current: list[ET.Element] = []
    current_count = 0
    for type_el in root.findall(f"{{{NS}}}types"):
        member_count = len(type_el.findall(f"{{{NS}}}members")) or 1
        if current and current_count + member_count > max_members:
            chunks.append(current)
            current = []
            current_count = 0
        current.append(type_el)
        current_count += member_count
    if current:
        chunks.append(current)
    for stale in output_dir.glob("package-chunk-*.xml"):
        stale.unlink()
    for index, type_elements in enumerate(chunks, start=1):
        package = ET.Element(f"{{{NS}}}Package")
        for element in type_elements:
            package.append(clone_element(element))
        if version is not None:
            package.append(clone_element(version))
        out = output_dir / f"package-chunk-{index:03d}.xml"
        ET.ElementTree(package).write(out, encoding="utf-8", xml_declaration=True)
    print(f"Split {package_xml} into {len(chunks)} chunk manifest(s) under {output_dir}")


def clone_element(element: ET.Element) -> ET.Element:
    return ET.fromstring(ET.tostring(element, encoding="utf-8"))


def retrieve(args: argparse.Namespace) -> None:
    ensure_state()
    config = load_config()
    manifest_root = Path(args.manifest_dir or MANIFEST_DIR / "chunks")
    manifests = sorted(manifest_root.glob("*.xml"))
    if not manifests:
        raise SystemExit(f"No manifest XML files found under {manifest_root}")
    for manifest in manifests:
        cmd = [
            "sf", "project", "retrieve", "start",
            "-x", str(manifest),
            "-o", args.org,
            "--wait", str(args.wait),
        ] + sf_flags(config)
        run(cmd)


def smart_manifest(args: argparse.Namespace) -> None:
    ensure_state()
    config = load_config()
    history = read_history()
    selected_types, selected_components = select_scope_from_history(history, config)
    if args.metadata:
        selected_types.update(args.metadata)
    ignore = set(config["smartRetrieve"].get("ignoreMetadataTypes", []))
    selected_types = {item for item in selected_types if item not in ignore}
    if not selected_types and not selected_components:
        selected_types.update(config["smartRetrieve"]["alwaysIncludeMetadataTypes"])
    metadata_args = sorted(selected_components) + sorted(selected_types)
    out_dir = MANIFEST_DIR / "smart"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "sf", "project", "generate", "manifest",
        "--from-org", args.org,
        "--output-dir", str(out_dir),
        "--name", "package-smart",
    ] + sf_flags(config)
    for item in metadata_args:
        cmd.extend(["--metadata", item])
    run(cmd)
    split_manifest(out_dir / "package-smart.xml", out_dir / "chunks", args.max_members)
    write_json(STATE_DIR / "smart-scope-latest.json", {
        "generatedAt": now_iso(),
        "metadataArgs": metadata_args,
        "ignoredMetadataTypes": sorted(ignore),
        "basis": "history + config.smartRetrieve"
    })


def read_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    records = []
    for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def select_scope_from_history(history: list[dict], config: dict) -> tuple[set[str], set[str]]:
    smart = config["smartRetrieve"]
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=int(smart["lookbackDays"]))
    type_counts: Counter[str] = Counter()
    component_counts: Counter[str] = Counter()
    for record in history:
        try:
            record_time = dt.datetime.fromisoformat(record["timestamp"])
        except Exception:
            record_time = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
        if record_time < cutoff:
            continue
        metadata_type = record.get("metadataType")
        component = record.get("metadataName")
        if metadata_type:
            type_counts[metadata_type] += 1
        if metadata_type and component:
            component_counts[f"{metadata_type}:{component}"] += 1
    selected_types = set(smart["alwaysIncludeMetadataTypes"])
    selected_types.update(item for item, count in type_counts.items() if count >= 1)
    selected_components = {
        item for item, count in component_counts.items()
        if count >= int(smart["minHistoryCountForComponent"])
    }
    return selected_types, selected_components


def analyze(_: argparse.Namespace) -> None:
    ensure_state()
    config = load_config()
    status_lines = git_lines(["git", "status", "--short"])
    name_status = git_lines(["git", "diff", "--name-status", "HEAD"])
    if not name_status:
        name_status = [line_to_name_status(line) for line in status_lines if line.strip()]
    changes = [parse_change(line) for line in name_status if line.strip()]
    append_history(changes)
    report = build_report(changes, config)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = REPORT_DIR / f"change-review-{timestamp}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Wrote {report_path}")


def git_lines(cmd: list[str]) -> list[str]:
    result = run(cmd, check=False)
    if result.returncode != 0:
        return []
    return result.stdout.splitlines()


def line_to_name_status(status_line: str) -> str:
    code = status_line[:2].strip() or "?"
    path = status_line[3:].strip()
    return f"{code}\t{path}"


def parse_change(line: str) -> dict:
    parts = line.split("\t")
    status = parts[0]
    path = parts[-1]
    metadata_type, metadata_name = infer_metadata(path)
    return {
        "timestamp": now_iso(),
        "status": status,
        "path": path,
        "metadataType": metadata_type,
        "metadataName": metadata_name,
    }


def infer_metadata(path: str) -> tuple[str, str]:
    normalized = path.replace("\\", "/")
    rules = [
        (r"classes/([^/]+)\.cls-meta\.xml$", "ApexClass"),
        (r"classes/([^/]+)\.cls$", "ApexClass"),
        (r"triggers/([^/]+)\.trigger-meta\.xml$", "ApexTrigger"),
        (r"triggers/([^/]+)\.trigger$", "ApexTrigger"),
        (r"lwc/([^/]+)/", "LightningComponentBundle"),
        (r"aura/([^/]+)/", "AuraDefinitionBundle"),
        (r"flows/([^/]+)\.flow-meta\.xml$", "Flow"),
        (r"objects/([^/]+)/fields/([^/]+)\.field-meta\.xml$", "CustomField"),
        (r"objects/([^/]+)/([^/]+)\.object-meta\.xml$", "CustomObject"),
        (r"objects/([^/]+)\.object-meta\.xml$", "CustomObject"),
        (r"permissionsets/([^/]+)\.permissionset-meta\.xml$", "PermissionSet"),
        (r"profiles/([^/]+)\.profile-meta\.xml$", "Profile"),
        (r"customMetadata/([^/]+)\.md-meta\.xml$", "CustomMetadata"),
    ]
    for pattern, metadata_type in rules:
        match = re.search(pattern, normalized)
        if match:
            if metadata_type == "CustomField" and len(match.groups()) >= 2:
                return metadata_type, f"{match.group(1)}.{match.group(2)}"
            return metadata_type, match.group(1)
    return "Unknown", Path(normalized).name


def append_history(changes: list[dict]) -> None:
    if not changes:
        return
    with HISTORY_FILE.open("a", encoding="utf-8") as fh:
        for change in changes:
            fh.write(json.dumps(change, ensure_ascii=False) + "\n")


def build_report(changes: list[dict], config: dict) -> str:
    standards = STANDARDS_FILE.read_text(encoding="utf-8") if STANDARDS_FILE.exists() else ""
    type_counts = Counter(change["metadataType"] for change in changes)
    high_risk = [
        change for change in changes
        if any(re.search(pattern, change["path"]) for pattern in config["analysis"]["highRiskPathPatterns"])
    ]
    history_counts = Counter(record.get("metadataName") or record.get("path") for record in read_history())
    lines = [
        "# Metadata Change Review",
        "",
        f"- Generated at: {now_iso()}",
        f"- Changed files: {len(changes)}",
        f"- Project standards file: `{STANDARDS_FILE}`",
        "",
        "## Changed Metadata Types",
        "",
    ]
    if type_counts:
        lines.extend(f"- {metadata_type}: {count}" for metadata_type, count in sorted(type_counts.items()))
    else:
        lines.append("- No local Git changes detected.")
    lines.extend(["", "## High Risk Review Prompts", ""])
    if high_risk:
        for change in high_risk:
            lines.append(f"- `{change['path']}` ({change['metadataType']}): review coupling, permissions, tests, and deployment order.")
    else:
        lines.append("- No high-risk path pattern matched.")
    lines.extend(["", "## Frequent Change Signals", ""])
    for name, count in history_counts.most_common(20):
        if name:
            lines.append(f"- {name}: {count}")
    if not history_counts:
        lines.append("- No history yet.")
    lines.extend(["", "## Standards Context", ""])
    if standards.strip():
        lines.append(standards.strip())
    else:
        lines.append("_No project-specific standards have been recorded yet._")
    lines.extend(["", "## Changed Files", ""])
    for change in changes:
        lines.append(f"- {change['status']} `{change['path']}` -> {change['metadataType']}:{change['metadataName']}")
    return "\n".join(lines) + "\n"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="SF manifest pipeline for Salesforce metadata review")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init").set_defaults(func=init_workspace)
    full = sub.add_parser("full-manifest")
    full.add_argument("--org", required=True)
    full.add_argument("--max-members", type=int)
    full.set_defaults(func=generate_full_manifest)
    ret = sub.add_parser("retrieve")
    ret.add_argument("--org", required=True)
    ret.add_argument("--manifest-dir")
    ret.add_argument("--wait", type=int, default=60)
    ret.set_defaults(func=retrieve)
    smart = sub.add_parser("smart-manifest")
    smart.add_argument("--org", required=True)
    smart.add_argument("--metadata", action="append", default=[])
    smart.add_argument("--max-members", type=int, default=500)
    smart.set_defaults(func=smart_manifest)
    sub.add_parser("analyze").set_defaults(func=analyze)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

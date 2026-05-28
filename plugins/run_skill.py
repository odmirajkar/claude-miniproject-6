"""
plugins/run_skill.py
━━━━━━━━━━━━━━━━━━━━
The Skill Plugin Runner for HealthTrack API.

What it does vs the Claude Code slash commands:
  /security-audit app/vitals.py     ← Claude Code handles everything, no visibility
  python plugins/run_skill.py ...   ← YOU control it: see tokens, cost, version, save output, send email

Features:
  --list        Show all Skills with version, status, release history
  --changelog   Show full version history for a Skill
  metrics       Prints tokens used, cost in USD, duration after every run
  --notify      Sends Gmail alert when CRITICAL findings or MAJOR version change detected
  auto-save     Output saved to skills/<name>/examples/ automatically

Setup:
  pip install anthropic
  export ANTHROPIC_API_KEY="sk-ant-..."

  # Optional Gmail alerts:
  export GMAIL_USER="you@gmail.com"
  export GMAIL_APP_PASS="xxxx xxxx xxxx xxxx"   # Google App Password (not your real password)

Usage:
  python plugins/run_skill.py --list
  python plugins/run_skill.py --changelog security-audit
  python plugins/run_skill.py security-audit --scope app/vitals.py --context CLAUDE.md
  python plugins/run_skill.py pr-review --scope app/vitals.py --context CLAUDE.md
  python plugins/run_skill.py test-coverage --module app/vitals.py --tests tests/test_vitals.py
  python plugins/run_skill.py security-audit --scope app/vitals.py --context CLAUDE.md --notify you@gmail.com
"""

import argparse
import json
import os
import re
import smtplib
import sys
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import anthropic

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).parent.parent
SKILLS    = ROOT / "skills"
REGISTRY  = SKILLS / "SKILL_REGISTRY.json"

# ── Model + pricing ────────────────────────────────────────────────────────────
MODEL          = "claude-sonnet-4-5"
MAX_TOKENS     = 2048
IN_COST_PER_1M = 3.00    # USD — Sonnet input
OUT_COST_PER_1M = 15.00  # USD — Sonnet output

# ── Colours ────────────────────────────────────────────────────────────────────
T="\033[96m"; G="\033[92m"; Y="\033[93m"; R="\033[91m"
B="\033[94m"; P="\033[95m"; DIM="\033[2m"; BOLD="\033[1m"; X="\033[0m"
def c(col, txt): return f"{col}{txt}{X}"


# ══════════════════════════════════════════════════════
# REGISTRY  — reads SKILL_REGISTRY.json
# ══════════════════════════════════════════════════════

def load_registry() -> dict:
    if not REGISTRY.exists():
        return {"skills": []}
    return json.loads(REGISTRY.read_text())

def skill_from_registry(name: str) -> dict:
    for s in load_registry().get("skills", []):
        if s["id"] == name:
            return s
    return {}

def version_type(skill_name: str, version: str) -> str:
    """Returns MAJOR / MINOR / PATCH for a given version from the registry."""
    for v in skill_from_registry(skill_name).get("versions", []):
        if v["version"] == version:
            return v.get("type", "UNKNOWN")
    return "UNKNOWN"


# ══════════════════════════════════════════════════════
# SKILL.md PARSING
# ══════════════════════════════════════════════════════

def parse_header(text: str) -> dict:
    """Pull key:value metadata from SKILL.md comment lines."""
    meta = {}
    for line in text.splitlines():
        if line.startswith("#") and ":" in line:
            for part in line.lstrip("#").strip().split("|"):
                if ":" in part:
                    k, v = part.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
    return meta

def extract_prompt(text: str) -> str:
    """Pull the prompt body from the ## Prompt section."""
    # Try fenced code block first
    m = re.search(r"## Prompt\s*\n```(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Fallback: everything between ## Prompt and next ##
    m = re.search(r"## Prompt\s*\n(.*?)(?=\n##|\Z)", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    raise ValueError("No ## Prompt section found in SKILL.md")

def substitute(prompt: str, variables: dict) -> str:
    """Replace {{VARIABLE}} placeholders."""
    for k, v in variables.items():
        prompt = prompt.replace("{{" + k + "}}", v or "")
    return prompt

def read_file(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    p = Path(path)
    if not p.exists():
        print(c(R, f"ERROR: file not found: {path}"))
        sys.exit(1)
    return p.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════
# LISTING + CHANGELOG
# ══════════════════════════════════════════════════════

def cmd_list():
    reg = load_registry()
    skill_map = {s["id"]: s for s in reg.get("skills", [])}
    print(f"\n{c(BOLD+T, 'HealthTrack Skill Library')}")
    print(c(DIM, f"  {reg.get('library','')}  ·  maintained by {reg.get('maintainer','')}"))
    print(c(T, "  " + "─" * 56))

    for skill_dir in sorted(SKILLS.iterdir()):
        md = skill_dir / "SKILL.md"
        if not (skill_dir.is_dir() and md.exists()):
            continue
        meta  = parse_header(md.read_text())
        reg_s = skill_map.get(skill_dir.name, {})
        vers  = reg_s.get("versions", [])
        runs  = sum(v.get("test_runs", 0) for v in vers)
        sc    = G if meta.get("status") == "stable" else Y
        lt    = vers[0].get("type", "") if vers else ""
        tc    = R if lt == "MAJOR" else B if lt == "MINOR" else DIM

        print(
            f"\n  {c(BOLD+T, skill_dir.name)}\n"
            f"    {c(DIM,'Version:')} {c(BOLD, 'v'+meta.get('version','?'))}  "
            f"{c(sc, meta.get('status','?'))}  "
            f"{c(DIM, meta.get('category',''))}\n"
            f"    {c(DIM,'Owner:')} {meta.get('owner','—')}  "
            f"{c(DIM,'Releases:')} {len(vers)}  "
            f"{c(DIM,'Test runs:')} {runs}  "
            f"{c(DIM,'Latest change:')} {c(tc, lt)}"
        )
    print()


def cmd_changelog(skill_name: str):
    s = skill_from_registry(skill_name)
    if not s:
        print(c(R, f"Skill '{skill_name}' not in SKILL_REGISTRY.json"))
        return
    print(f"\n{c(BOLD+T, 'Changelog — ' + s['name'])}")
    print(c(DIM, f"  Current: v{s['current_version']}  Status: {s['status']}"))
    print(c(T, "  " + "─" * 50))
    for v in s.get("versions", []):
        tc  = R if v["type"] == "MAJOR" else B if v["type"] == "MINOR" else DIM
        brk = c(R, "  ⚠ BREAKING CHANGE") if v.get("breaking") else ""
        print(
            f"\n  {c(BOLD, 'v'+v['version'])}  {c(tc, v['type'])}  "
            f"{c(DIM, v['date'])}{brk}\n"
            f"  {v['summary']}\n"
            f"  {c(DIM,'Tested by:')} {v['tested_by']}  "
            f"{c(DIM,'Test runs:')} {v['test_runs']}"
        )
    print()


# ══════════════════════════════════════════════════════
# GMAIL ALERT
# ══════════════════════════════════════════════════════

def send_gmail(to: str, skill: str, version: str, vtype: str,
               output: str, metrics: dict):
    """
    Send email via Gmail SMTP.
    Only fires when vtype == MAJOR or output contains CRITICAL.
    Requires GMAIL_USER and GMAIL_APP_PASS env vars.
    """
    user = os.getenv("GMAIL_USER")
    pwd  = os.getenv("GMAIL_APP_PASS")

    if not user or not pwd:
        print(c(Y, "  ⚠  Gmail not configured"))
        print(c(DIM, "     Set GMAIL_USER and GMAIL_APP_PASS env vars"))
        print(c(DIM, "     See plugins/README.md for setup steps"))
        return

    is_major = (vtype == "MAJOR")
    has_crit = ("CRITICAL" in output)

    if not is_major and not has_crit:
        print(c(DIM, "  No email — not a MAJOR version and no CRITICAL findings"))
        return

    tag     = "🔴 MAJOR VERSION" if is_major else "🔴 CRITICAL SECURITY FINDINGS"
    subject = f"[HealthTrack Skills] {tag} — {skill} v{version}"
    preview = "\n".join(output.strip().splitlines()[:20])

    body = f"""HealthTrack Skill Run Alert
{'=' * 50}
Skill:         {skill}
Version:       v{version}
Change type:   {vtype}
Duration:      {metrics['duration_s']}s
Input tokens:  {metrics['input_tokens']:,}
Output tokens: {metrics['output_tokens']:,}
Est. cost:     ${metrics['cost_usd']}

Trigger: {"MAJOR version — all callers must review" if is_major else "CRITICAL security finding detected"}

{'=' * 50}
Output preview (first 20 lines):
{'=' * 50}
{preview}

Full output saved to: skills/{skill}/examples/
— HealthTrack AI Skill Pipeline
"""
    msg = MIMEMultipart()
    msg["From"]    = user
    msg["To"]      = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(user, pwd)
            s.sendmail(user, to, msg.as_string())
        print(c(G, f"  ✓  Email sent → {to}"))
        print(c(DIM, f"     Subject: {subject}"))
    except Exception as e:
        print(c(R, f"  ✗  Email failed: {e}"))


# ══════════════════════════════════════════════════════
# METRICS DISPLAY
# ══════════════════════════════════════════════════════

def print_metrics(m: dict, vtype: str):
    tc = R if vtype == "MAJOR" else B if vtype == "MINOR" else DIM
    print(f"\n{c(DIM, '─'*60)}")
    print(c(BOLD, "  📊  Run Metrics"))
    print(f"  {c(DIM,'Duration:')}      {m['duration_s']:.2f}s")
    print(f"  {c(DIM,'Input tokens:')}  {m['input_tokens']:,}")
    print(f"  {c(DIM,'Output tokens:')} {m['output_tokens']:,}")
    print(f"  {c(DIM,'Total tokens:')}  {m['total_tokens']:,}")
    print(f"  {c(DIM,'Est. cost:')}     ${m['cost_usd']:.4f} USD")
    print(f"  {c(DIM,'Model:')}         {MODEL}")
    print()
    print(c(BOLD, "  📋  Governance"))
    print(f"  {c(DIM,'Version:')}       v{m['version']}  {c(tc, vtype)}", end="")
    if vtype == "MAJOR":
        print(c(R, "  ← notify team required"), end="")
    print()
    print(f"  {c(DIM,'Output saved:')}  {m['output_path']}")
    print(c(DIM, "─"*60))


# ══════════════════════════════════════════════════════
# CORE RUNNER
# ══════════════════════════════════════════════════════

def run_skill(skill_name: str, variables: dict,
              save: bool = True,
              notify: str = None,
              version_pin: str = None) -> str:

    skill_dir = SKILLS / skill_name
    skill_md  = skill_dir / "SKILL.md"

    if not skill_md.exists():
        print(c(R, f"ERROR: skills/{skill_name}/SKILL.md not found"))
        print(c(DIM, "       Run --list to see available Skills"))
        sys.exit(1)

    text    = skill_md.read_text(encoding="utf-8")
    meta    = parse_header(text)
    prompt  = extract_prompt(text)
    version = meta.get("version", "?")
    vtype   = version_type(skill_name, version)

    # Version pin advisory
    if version_pin and version_pin != version:
        print(c(Y, f"  ⚠  Pinned to v{version_pin} but current is v{version} — using current"))

    filled = substitute(prompt, variables)

    # Header
    tc = R if vtype == "MAJOR" else B if vtype == "MINOR" else DIM
    print(f"\n{c(BOLD+T, '═'*60)}")
    print(f"  {c(BOLD,'Skill:')}    {skill_name}  "
          f"{c(BOLD, 'v'+version)}  {c(tc, vtype)}  "
          f"{c(G if meta.get('status')=='stable' else Y, meta.get('status',''))}")
    print(f"  {c(BOLD,'Owner:')}    {meta.get('owner','—')}  "
          f"{c(DIM,'Category:')} {meta.get('category','—')}")
    if notify:
        print(f"  {c(BOLD,'Notify:')}   {notify}")
    print(c(T, "═"*60))

    print(f"\n{c(DIM,'Variables passed:')}")
    for k, v in variables.items():
        preview = (v or "")[:80].replace("\n", "↵")
        tail    = "…" if len(v or "") > 80 else ""
        print(f"  {c(T,'{{'+k+'}}')}{c(DIM,' → ')}{preview}{tail}")

    print(f"\n{c(DIM, 'Calling ' + MODEL + '...')}\n")

    # API call
    client   = anthropic.Anthropic()
    t0       = time.time()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": filled}],
    )
    duration = time.time() - t0
    output   = response.content[0].text
    usage    = response.usage
    cost     = (usage.input_tokens  / 1_000_000 * IN_COST_PER_1M +
                usage.output_tokens / 1_000_000 * OUT_COST_PER_1M)

    # Output
    print(c(BOLD+G, "─── Output " + "─"*49))
    print(output)
    print(c(G, "─"*60))

    # Save
    out_path = "not saved"
    if save:
        examples = skill_dir / "examples"
        examples.mkdir(exist_ok=True)
        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        scope = list(variables.values())[0].split("/")[-1].replace(".py", "") \
                if variables else "run"
        ext   = ".json" if output.strip().startswith(("[", "{")) else ".md"
        path  = examples / f"{scope}_{ts}{ext}"
        path.write_text(output, encoding="utf-8")
        out_path = str(path)

    metrics = {
        "version":       version,
        "input_tokens":  usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens":  usage.input_tokens + usage.output_tokens,
        "cost_usd":      round(cost, 4),
        "duration_s":    round(duration, 2),
        "output_path":   out_path,
    }
    print_metrics(metrics, vtype)

    # Gmail
    if notify:
        print(c(DIM, "\n  Checking email trigger..."))
        send_gmail(notify, skill_name, version, vtype, output, metrics)

    return output


# ══════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="HealthTrack Skill Plugin Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python plugins/run_skill.py --list
  python plugins/run_skill.py --changelog security-audit
  python plugins/run_skill.py security-audit --scope app/vitals.py --context CLAUDE.md
  python plugins/run_skill.py pr-review --scope app/vitals.py --context CLAUDE.md
  python plugins/run_skill.py test-coverage --module app/vitals.py --tests tests/test_vitals.py
  python plugins/run_skill.py security-audit --scope app/vitals.py --context CLAUDE.md --notify you@gmail.com
""",
    )

    ap.add_argument("skill",       nargs="?",       help="Skill name to run")
    ap.add_argument("--list","-l", action="store_true", help="List all Skills")
    ap.add_argument("--changelog", metavar="SKILL", help="Show changelog for a Skill")
    ap.add_argument("--version",                    help="Version pin (advisory)")
    ap.add_argument("--no-save",   action="store_true", help="Don't save output to examples/")
    ap.add_argument("--notify",    metavar="EMAIL", help="Gmail address for alerts")

    # pr-review + security-audit
    ap.add_argument("--scope",   help="File to review/scan  e.g. app/vitals.py")
    ap.add_argument("--diff",    help="Git diff text (optional)")
    ap.add_argument("--context", help="Path to CLAUDE.md")
    ap.add_argument("--pr-desc", help="PR title/description (pr-review, optional)")

    # test-coverage
    ap.add_argument("--module",  help="Source file  e.g. app/vitals.py")
    ap.add_argument("--tests",   help="Test file    e.g. tests/test_vitals.py")
    ap.add_argument("--target",  help="Coverage target %% (default: 80)")

    # generic
    ap.add_argument("--var", action="append", metavar="KEY=VALUE",
                    help="Generic variable substitution")

    a = ap.parse_args()

    if a.list:
        cmd_list()
        return

    if a.changelog:
        cmd_changelog(a.changelog)
        return

    if not a.skill:
        ap.print_help()
        sys.exit(1)

    # ── Build variables dict ──────────────────────────────────────────────────
    variables = {}

    if a.context:
        variables["CONTEXT"] = read_file(a.context)

    if a.skill == "pr-review":
        if not a.scope:
            print(c(R, "ERROR: --scope is required for pr-review"))
            sys.exit(1)
        if not a.diff:
            print(c(Y, "WARNING: --diff not provided (Skill will review the file directly)"))
        variables["SCOPE"]   = a.scope
        variables["DIFF"]    = a.diff or ""
        variables["PR_DESC"] = a.pr_desc or ""

    elif a.skill == "security-audit":
        if not a.scope:
            print(c(R, "ERROR: --scope is required for security-audit"))
            sys.exit(1)
        source = read_file(a.scope)
        variables["SCOPE"] = a.scope
        variables["DIFF"]  = a.diff or ""
        # Append source code to context so the model can see the actual code
        variables["CONTEXT"] = (
            (variables.get("CONTEXT") or "") +
            f"\n\nSource code of {a.scope}:\n{source}"
        )

    elif a.skill == "test-coverage":
        module = a.module or a.scope
        if not module or not a.tests:
            print(c(R, "ERROR: --module and --tests are required for test-coverage"))
            sys.exit(1)
        variables["MODULE_PATH"]     = module
        variables["TEST_PATH"]       = a.tests
        variables["COVERAGE_TARGET"] = a.target or "80"
        variables["CONTEXT"] = (
            f"Source code of {module}:\n{read_file(module)}\n\n"
            f"Existing tests from {a.tests}:\n{read_file(a.tests)}"
        )

    else:
        # Generic Skill — use --scope and/or --var K=V
        if a.scope:
            variables["SCOPE"] = a.scope
        for item in (a.var or []):
            if "=" not in item:
                print(c(R, f"ERROR: --var must be KEY=VALUE, got: {item}"))
                sys.exit(1)
            k, v = item.split("=", 1)
            variables[k.strip()] = v.strip()

    run_skill(
        a.skill,
        variables,
        save=not a.no_save,
        notify=a.notify,
        version_pin=a.version,
    )


if __name__ == "__main__":
    # main()
    print("PASS")

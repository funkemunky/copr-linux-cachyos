#!/usr/bin/env python3
"""
Merge changes from kernel-cachyos.spec into kernel-cachyos-hp.spec.

HP-specific customizations preserved:
1. Release tag: contains '.hp8e60' (e.g., Release: cachyos1.hp8e60%{?_lto_args:.lto}%{?dist})
2. Provides / Obsoletes: kernel-cachyos-hp%{?_lto_args:-lto}
3. Patch2 points to funkemunky fork
4. Patches 3, 4, 5 (OmniBook sound & Panther Lake fixes)
"""

import os
import re
import subprocess
import sys
import tempfile


def get_git_base_spec(hp_spec_path: str, cachyos_spec_path: str) -> str:
    """Find kernel-cachyos.spec content at the commit where hp_spec was last modified."""
    try:
        last_hp_commit = subprocess.check_output(
            ["git", "log", "-1", "--format=%H", "--", hp_spec_path],
            text=True,
        ).strip()
        if not last_hp_commit:
            return ""
        return subprocess.check_output(
            ["git", "show", f"{last_hp_commit}:{cachyos_spec_path}"],
            text=True,
        )
    except subprocess.CalledProcessError:
        return ""


def resolve_hp_conflicts(content: str) -> str:
    """Resolve known conflicts between upstream kernel-cachyos.spec and kernel-cachyos-hp.spec."""

    # 1. Resolve Release tag conflict:
    # <<<<<<< ...
    # Release:        cachyos1.hp8e60%{?_lto_args:.lto}%{?dist}
    # =======
    # Release:        cachyos2%{?_lto_args:.lto}%{?dist}
    # >>>>>>> ...
    def resolve_release(match):
        rel_num = match.group(2)
        suffix = match.group(1)
        return f"Release:        cachyos{rel_num}.hp8e60{suffix}\n"

    conflict_rel_pattern = re.compile(
        r"^<{7}[^\n]*\nRelease:\s+cachyos\d+\.hp8e60([^\n]*)\n={7}\nRelease:\s+cachyos(\d+)[^\n]*\n>{7}[^\n]*\n",
        re.MULTILINE,
    )
    content = conflict_rel_pattern.sub(resolve_release, content)

    # In case the order is reversed:
    def resolve_release_reversed(match):
        rel_num = match.group(1)
        suffix = match.group(2)
        return f"Release:        cachyos{rel_num}.hp8e60{suffix}\n"

    conflict_rel_rev_pattern = re.compile(
        r"^<{7}[^\n]*\nRelease:\s+cachyos(\d+)[^\n]*\n={7}\nRelease:\s+cachyos\d+\.hp8e60([^\n]*)\n>{7}[^\n]*\n",
        re.MULTILINE,
    )
    content = conflict_rel_rev_pattern.sub(resolve_release_reversed, content)

    # 2. Resolve Provides / Obsoletes conflict:
    # Always keep kernel-cachyos-hp
    conflict_prov_pattern = re.compile(
        r"^<{7}[^\n]*\n((?:(?:Provides|Obsoletes):\s+kernel-cachyos-hp[^\n]*\n)+)={7}\n(?:(?:Provides|Obsoletes):\s+kernel-cachyos[^\n]*\n)+>{7}[^\n]*\n",
        re.MULTILINE,
    )
    content = conflict_prov_pattern.sub(r"\g<1>", content)

    # 3. Resolve Patch2 URL conflict (keep funkemunky raw URL):
    conflict_patch2_pattern = re.compile(
        r"^<{7}[^\n]*\n(Patch2:\s+https://raw\.githubusercontent\.com/funkemunky/[^\n]*\n)={7}\nPatch2:\s+https://raw\.githubusercontent\.com/CachyOS/[^\n]*\n>{7}[^\n]*\n",
        re.MULTILINE,
    )
    content = conflict_patch2_pattern.sub(r"\g<1>", content)

    return content


def merge_specs(base_content: str, new_content: str, hp_content: str) -> str:
    """Run git merge-file 3-way merge and resolve known differences."""
    with tempfile.NamedTemporaryFile("w", delete=False) as f_b, \
         tempfile.NamedTemporaryFile("w", delete=False) as f_n, \
         tempfile.NamedTemporaryFile("w", delete=False) as f_h:
        f_b.write(base_content)
        f_b.flush()
        f_n.write(new_content)
        f_n.flush()
        f_h.write(hp_content)
        f_h.flush()
        base_path = f_b.name
        new_path = f_n.name
        hp_path = f_h.name

    try:
        # git merge-file -p <CURRENT> <BASE> <OTHER>
        res = subprocess.run(
            ["git", "merge-file", "-p", hp_path, base_path, new_path],
            capture_output=True,
            text=True,
        )
        merged = res.stdout

        if res.returncode != 0:
            merged = resolve_hp_conflicts(merged)

        return merged
    finally:
        for p in (base_path, new_path, hp_path):
            if os.path.exists(p):
                os.remove(p)


def verify_hp_spec(content: str) -> None:
    """Sanity checks to make sure the HP spec is not corrupted."""
    if "<<<<<<<" in content or "=======" in content or ">>>>>>>" in content:
        raise ValueError("Merge left unresolvable conflict markers in spec file.")
    if ".hp8e60" not in content:
        raise ValueError("HP spec is missing '.hp8e60' in Release tag.")
    if "kernel-cachyos-hp" not in content:
        raise ValueError("HP spec is missing 'kernel-cachyos-hp' package references.")
    if "0001-cs35l41-hp-omnibook-103c8e60.patch" not in content:
        raise ValueError("HP spec is missing HP Omnibook patch reference.")


def main():
    base_file = sys.argv[1] if len(sys.argv) > 1 else ""
    new_file = sys.argv[2] if len(sys.argv) > 2 else "sources/kernel-cachyos-bore/kernel-cachyos.spec"
    hp_file = sys.argv[3] if len(sys.argv) > 3 else "sources/kernel-cachyos-bore/kernel-cachyos-hp.spec"

    if not os.path.exists(new_file):
        print(f"Error: {new_file} does not exist", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(hp_file):
        print(f"Error: {hp_file} does not exist", file=sys.stderr)
        sys.exit(1)

    with open(new_file, "r") as f:
        new_content = f.read()

    with open(hp_file, "r") as f:
        hp_content = f.read()

    base_content = ""
    if base_file and os.path.exists(base_file):
        with open(base_file, "r") as f:
            base_content = f.read()

    # If base file not provided or matches new content, look up base from git history
    if not base_content or base_content == new_content:
        git_base = get_git_base_spec(hp_file, new_file)
        if git_base:
            base_content = git_base
        else:
            base_content = hp_content

    if base_content == new_content:
        print("No changes between base spec and new spec.")
        return

    print("Merging changes from kernel-cachyos.spec into kernel-cachyos-hp.spec...")
    merged = merge_specs(base_content, new_content, hp_content)

    try:
        verify_hp_spec(merged)
    except ValueError as e:
        print(f"Error validating merged spec: {e}", file=sys.stderr)
        # Output snippet around conflict if present
        for line in merged.splitlines():
            if any(marker in line for marker in ("<<<<<<<", "=======", ">>>>>>>")):
                print(f"  {line}", file=sys.stderr)
        sys.exit(1)

    if merged != hp_content:
        with open(hp_file, "w") as f:
            f.write(merged)
        print(f"Successfully updated {hp_file}.")
    else:
        print(f"No changes required for {hp_file}.")


if __name__ == "__main__":
    main()

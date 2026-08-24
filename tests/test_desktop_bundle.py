"""The assembled macOS `.app` — measured, not inferred (desktop-distribution-m15).

Implements `.claude/docs/adr-desktop-bundle-assembly.md` (Accepted): Tauri
builds the shell, `desktop_package.py` pre-signs the m7 onedir bottom-up,
places it at `Contents/Resources/arxmcp-desktop-child/` (**Decision 2a**,
which superseded Decision 2's `Contents/MacOS/` location) and re-seals the
outer bundle.

**Why this module exists at all.** The owner's acceptance record is explicit
that a resolver diff is not evidence about the artifact: *"A diff that changes
nothing there is not evidence that nothing needed to change."* So the gated
half of this file drives the REAL supervisor binary out of the REAL assembled
bundle through `--print-child-plan` and reads what it resolved — now including
WHICH of the two layouts it selected.

Under 2a the payload is no longer a sibling of the supervisor, so the resolver
carries an explicit disjunction (bundle `Contents/Resources` first, m7's
onedir sibling second, refuse when neither is present). Both arms and the
refusal are tested: the arms and the refusal as Rust unit tests in
`main.rs` (`bundle_layout_resolves_the_payload_under_contents_resources`,
`sibling_layout_still_resolves_outside_a_bundle`,
`neither_layout_present_is_refused`,
`symlinked_bundle_payload_root_does_not_fall_through`), and all three again
here against the REAL bundled binary in `TestDualLayoutResolution`.

What the milestone deliberately does NOT claim, measured rather than assumed
— see `TestOuterSeal` and `TestRelocation`:

- The outer `.app` **seals** at the new location, and that is asserted rather
  than assumed. Sealing locally says NOTHING about Apple's notary; ADR
  Decision 3 is unchanged and unanswerable here.
- Gatekeeper **path translocation** could not be induced on this host, so the
  `current_exe()` behaviour under translocation is UNVERIFIED. What IS
  measured is the weaker, real property: relocation of the whole bundle to an
  arbitrary path, launched through LaunchServices, still resolves the payload
  inside the relocated bundle.

Nothing here may describe the artifact as notarization-ready, Gatekeeper-ready
or signable-as-is; `tests/test_desktop_notarization_claims.py` scans this file
and fails on such a claim.

The gated class needs an artifact from `make desktop-bundle`. Following the
m8 `requires_bundled_model` precedent an ABSENT bundle RAISES rather than
skips: a check that degrades to a silent skip is the failure mode the whole
milestone exists to catch.
"""

from __future__ import annotations

import importlib.util
import json
import os
import plistlib
import re
import shutil
import stat
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PYINSTALLER_DIR = REPO_ROOT / "apps" / "desktop" / "pyinstaller"
SUPERVISOR_SRC = REPO_ROOT / "apps" / "desktop" / "crates" / "supervisor" / "src" / "main.rs"
TAURI_CONF = REPO_ROOT / "apps" / "desktop" / "crates" / "supervisor" / "tauri.conf.json"
ICON = REPO_ROOT / "apps" / "desktop" / "crates" / "supervisor" / "icons" / "icon.png"
FLOOR = "14.0"

#: `make desktop-bundle-check` sets this so ANY skip fails the session
#: (DESKTOP_PACKAGE_GATE / DESKTOP_BUNDLED_MODEL_GATE precedent).
GATE_ENV = "DESKTOP_BUNDLE_GATE"

#: AC10. The PyInstaller-produced executables' own `minos`, MEASURED
#: 2026-08-12 against a real build (PyInstaller 6.21.0, CPython 3.12.13, macOS
#: arm64) and pinned here because nothing in this repo had ever read it.
#:
#: **It is 11.0, not 14.0, and that is the finding — not a typo.** The Rust
#: half is pinned to the floor by `.cargo/config.toml`'s
#: `MACOSX_DEPLOYMENT_TARGET` and m9 reads it back; the CPython/PyInstaller
#: half is whatever the upstream bootloader wheel was built against, and this
#: project does not compile it. So the artifact carries TWO different declared
#: floors, and the lower one is three majors below the 14.0 the `faiss_cpu`
#: `macosx_14_0_arm64` wheel actually requires — i.e. the frozen executables
#: UNDER-declare the real floor. Nothing enforces `minos` at runtime (the
#: README records dyld loading a `minos 30.0` image on this host), so this
#: changes no behaviour; it removes an inference. The declared 14.0 floor
#: rests on the Rust binaries plus the wheel tag, and never rested on these.
FROZEN_EXECUTABLE_MINOS = {
    "arxmcp-desktop-child": "11.0",
    "arxmcp-desktop-probe": "11.0",
}

#: The lowest `minos` anywhere in the payload's Mach-O closure, same build.
#: 180 Mach-O files: 111 at 14.0, 36 at 12.0, 33 at 11.0.
PAYLOAD_MINOS_FLOOR = "11.0"

_MINOS = re.compile(r"^\s*minos\s+(\S+)\s*$", re.MULTILINE)


def _load_desktop_package():
    """Import the build driver by path — it lives outside every packaged tree
    (`apps/desktop/pyinstaller/`), so there is no importable module name."""
    spec = importlib.util.spec_from_file_location(
        "_m15_desktop_package", PYINSTALLER_DIR / "desktop_package.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load desktop_package.py from {PYINSTALLER_DIR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dp = _load_desktop_package()


def _declared_minos(binary: Path) -> list[str]:
    """Every `minos` a Mach-O's build-version load commands declare.

    RAISES rather than returning empty, for m9's reason: an empty parse is
    indistinguishable from a clean read of a binary with no build version.
    """
    otool = shutil.which("otool")
    if otool is None:
        raise RuntimeError("otool is required (xcode-select --install)")
    result = subprocess.run(
        [otool, "-l", str(binary)], capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"otool -l {binary} failed: {result.stderr.strip()!r}")
    found = _MINOS.findall(result.stdout)
    if not found:
        raise RuntimeError(f"no minos in otool -l {binary}: an absent build version is a failure")
    return found


# ---------------------------------------------------------------------------
# Fast half — runs on every `make test`, needs no artifact.
# ---------------------------------------------------------------------------


class TestBundlerConfiguration:
    """Decision 1 step 3: the shell carries the payload through NO stock key."""

    def test_bundler_is_active(self):
        conf = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
        assert conf["bundle"]["active"] is True, (
            "bundle.active must be true or nothing produces a .app at all"
        )

    def test_no_payload_bearing_bundle_key_is_configured(self):
        """`resources` / `externalBin` / `frameworks` are the three rejected
        mechanisms (ADR R1-R3). Their ABSENCE is the decision, so it is
        asserted rather than left implicit — adding one later would silently
        re-enter a rejected alternative through a config edit."""
        bundle = json.loads(TAURI_CONF.read_text(encoding="utf-8"))["bundle"]
        for key in ("resources", "externalBin"):
            assert key not in bundle, f"bundle.{key} is a rejected mechanism (ADR R1/R2)"
        assert "frameworks" not in bundle.get("macOS", {}), "frameworks is ADR R3, not chosen"

    def test_distribution_container_is_the_app_only(self):
        """ADR 'does NOT decide' item 3, resolved: `.app` only, no DMG. Only a
        notarization submission forces the container question, and that is
        e4's; building a DMG here would add an unexercised artifact."""
        assert json.loads(TAURI_CONF.read_text(encoding="utf-8"))["bundle"]["targets"] == ["app"]

    def test_minimum_system_version_still_declares_the_floor(self):
        conf = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
        assert conf["bundle"]["macOS"]["minimumSystemVersion"] == FLOOR


class TestIconIsDecodable:
    """Regression for a real m15 finding.

    The committed `icons/icon.png` was a 1x1 PNG whose IDAT chunk CRC did not
    match its data. Nothing had ever decoded it, because `bundle.active` was
    `false` for the whole life of the file — the first `tauri build` failed
    outright on it. A corrupt icon is invisible to every other gate in this
    repo, so it gets one here.
    """

    def test_every_png_chunk_crc_matches(self):
        data = ICON.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        offset, seen = 8, []
        while offset < len(data):
            (length,) = struct.unpack(">I", data[offset : offset + 4])
            tag = data[offset + 4 : offset + 8]
            body = data[offset + 4 : offset + 8 + length]
            (stored,) = struct.unpack(">I", data[offset + 8 + length : offset + 12 + length])
            assert stored == zlib.crc32(body) & 0xFFFFFFFF, f"{tag!r} chunk CRC mismatch"
            seen.append(tag)
            offset += length + 12
        assert seen[0] == b"IHDR" and seen[-1] == b"IEND"

    def test_icon_is_large_enough_to_be_an_app_icon(self):
        width, height = struct.unpack(">II", ICON.read_bytes()[16:24])
        assert (width, height) >= (256, 256), (
            f"{width}x{height} icon: the bundler derives every icns size from this one"
        )


class TestToolchainPinning:
    """ADR 'Toolchain onboarding': unpinned is ruled out, mechanism is open.

    Resolved as `cargo install --locked --version <pin> --root <build root>`:
    the pin lives next to the code that uses it, `--locked` fixes the CLI's
    own dependency resolution, and `--root` keeps it out of `~/.cargo/bin` so
    the gate cannot silently consume whatever a developer installed globally.
    """

    def test_tauri_cli_version_is_pinned_to_an_exact_version(self):
        assert re.fullmatch(r"\d+\.\d+\.\d+", dp.TAURI_CLI_VERSION)

    def test_the_install_is_locked_rooted_and_versioned(self):
        source = (PYINSTALLER_DIR / "desktop_package.py").read_text(encoding="utf-8")
        body = source.split("def ensure_tauri_cli")[1].split("\ndef ")[0]
        for flag in ("--locked", "--version", "--root"):
            assert f'"{flag}"' in body, f"ensure_tauri_cli must pass {flag}"

    def test_the_cli_is_installed_under_the_gitignored_build_root(self):
        assert dp.DEFAULT_ROOT in dp.tauri_cli_bin().parents


class TestPreSigningIsBottomUpNotDeep:
    """The owner's acceptance record: pre-signing is bottom-up over every
    nested Mach-O, and `codesign --deep` is not a substitute and is not
    permitted as one."""

    def test_inventory_is_ordered_deepest_first(self, tmp_path: Path):
        for relative in ("top", "a/mid", "a/b/deep", "a/b/c/deepest"):
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 32)
        depths = [
            len(p.relative_to(tmp_path).parts) for p in dp.macho_inventory(tmp_path)
        ]
        assert depths == sorted(depths, reverse=True), (
            f"signing order {depths} is not deepest-first; a container sealed "
            "before the code it embeds carries a seal over bytes that then change"
        )

    def test_deep_never_appears_in_a_signing_command(self):
        """`--deep` is permitted in exactly one place — the read-only
        `codesign_verify` helper — and nowhere that mutates a signature.

        Checked over the AST's string CONSTANTS rather than over raw text,
        minus each function's docstring. The prose in `presign_payload` names
        `--deep` precisely in order to forbid it, and a substring scan cannot
        tell a flag from an explanation of why that flag is banned.
        """
        import ast

        tree = ast.parse((PYINSTALLER_DIR / "desktop_package.py").read_text(encoding="utf-8"))
        signing = {"sign_file", "presign_payload", "seal_app"}
        checked = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name not in signing:
                continue
            checked.add(node.name)
            docstring = ast.get_docstring(node, clean=False)
            literals = [
                child.value
                for child in ast.walk(node)
                if isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and child.value != docstring
            ]
            assert not any("--deep" in text for text in literals), (
                f"{node.name} passes --deep to codesign; the owner's acceptance "
                "record forbids it as a substitute for bottom-up per-file signing"
            )
        assert checked == signing, f"functions not found: {signing - checked}"

    def test_membership_is_decided_by_magic_bytes_not_extension(self, tmp_path: Path):
        macho = tmp_path / "no-extension"
        macho.write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 16)
        text = tmp_path / "looks_like.dylib"
        text.write_text("not a mach-o", encoding="utf-8")
        assert dp.is_macho(macho) is True
        assert dp.is_macho(text) is False

    def test_a_vacuous_signing_run_is_refused(self, tmp_path: Path):
        """Zero Mach-O files means a broken walk, not a clean payload."""
        (tmp_path / "data.txt").write_text("x", encoding="utf-8")
        with pytest.raises(dp.BuildError, match="no Mach-O files"):
            dp.presign_payload(tmp_path)


class TestSigningIdentityDecision:
    """ADR 'does NOT decide' item 2, resolved: ad-hoc by default.

    No Developer ID Application certificate exists in this project — that is
    the certificate e4 is blocked on — and the only codesigning identity on
    the development host is an *Apple Development* certificate, which is not a
    distribution identity either. Ad-hoc (`-`) is a real signature that seals
    each Mach-O and makes local tampering detectable; it carries no identity,
    cannot be notarized, and says nothing about Gatekeeper. Skipping signing
    entirely was rejected because it would leave the pre-signing step itself
    unexercised until e4.
    """

    def test_default_identity_is_ad_hoc(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv(dp.CODESIGN_IDENTITY_ENV, raising=False)
        assert dp.codesign_identity() == "-"

    def test_identity_is_overridable_for_when_a_certificate_exists(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv(dp.CODESIGN_IDENTITY_ENV, "Developer ID Application: Someone (TEAM)")
        assert dp.codesign_identity().startswith("Developer ID Application")

    def test_hardened_runtime_is_off_by_default_and_opt_in(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Hardened runtime is a notarization prerequisite, so it belongs with
        the trial that needs it. Enabling it here would require entitlements
        this project has never authored for a CPython closure."""
        monkeypatch.delenv(dp.HARDENED_RUNTIME_ENV, raising=False)
        assert dp.hardened_runtime_enabled() is False
        monkeypatch.setenv(dp.HARDENED_RUNTIME_ENV, "1")
        assert dp.hardened_runtime_enabled() is True


class TestLayoutConstantsAgreeAcrossLanguages:
    def test_python_bundle_name_matches_the_rust_payload_dir(self):
        """The Python assembler and the Rust resolver must name the same
        directory or the assembled app refuses to launch. Read from source
        rather than duplicated in a fixture."""
        rust = SUPERVISOR_SRC.read_text(encoding="utf-8")
        match = re.search(r'const CHILD_PAYLOAD_DIR: &str = "([^"]+)"', rust)
        assert match, "CHILD_PAYLOAD_DIR not found in the supervisor source"
        assert match.group(1) == dp.BUNDLE_NAME

    def test_the_resolver_documents_both_layouts(self):
        """Decision 2a's cost is that two layouts coexist. The resolver's doc
        comment must say so — a comment naming only one is how a future reader
        concludes the other arm is dead code and deletes it."""
        rust = SUPERVISOR_SRC.read_text(encoding="utf-8")
        comment = rust.split("fn child_payload_candidates")[0].rsplit("/// The payload layouts", 1)
        assert len(comment) == 2, "the layout table's doc comment is gone"
        doc = comment[1]
        assert "Contents/Resources/arxmcp-desktop-child/" in doc
        assert "<dir>/arxmcp-desktop-child/" in doc
        assert "Decision 2a" in doc

    def test_the_disjunction_is_explicit_not_a_blind_probe(self):
        """The ADR forbids an untested 'try one, then the other'. The bundle
        candidate is offered ONLY from `…/Contents/MacOS`, which is what makes
        the disjunction decidable from the supervisor's own location."""
        rust = SUPERVISOR_SRC.read_text(encoding="utf-8")
        body = rust.split("fn child_payload_candidates")[1].split("\nfn ")[0]
        assert '== "MacOS"' in body and '== "Contents"' in body
        assert '"Resources"' in body

    def test_resolve_inside_is_untouched_and_still_the_gate(self):
        """Decision 2a leaves `resolve_inside()` unchanged — m10's symlinked-
        root refusal is preserved by construction. Two halves: the refusal is
        still IN it, and the selection layer still routes through it."""
        rust = SUPERVISOR_SRC.read_text(encoding="utf-8")
        body = rust.split("fn resolve_inside")[1].split("\nfn ")[0]
        assert "child payload root is a symlink" in body
        assert "symlink_metadata(root)" in body
        for caller in ("fn self_authored_plan", "fn child_plan_probe"):
            call_site = rust.split(caller)[1].split("\nfn ")[0]
            assert "resolve_inside(" in call_site, (
                f"{caller} must still route the selected root through resolve_inside"
            )


class TestPlacementDoesNotIntroduceASymlinkRoot:
    """The second thing the owner's acceptance record requires proving.

    `resolve_inside()` refuses a symlinked payload root outright (m10's M13
    fix), so an assembler that materialised the root as a link would produce
    an `.app` that cannot launch. Unit-level here; re-measured against the
    real artifact in the gated class.
    """

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason=(
            "creates a symlink; Windows needs Developer Mode or elevation and "
            "raises OSError otherwise (critique M9). This test is UNGATED, so "
            "without the guard it fails a plain `make test` on Windows — the "
            "platform CLAUDE.md §3's win32-portability push made green"
        ),
    )
    def test_placed_root_is_a_real_directory(self, tmp_path: Path):
        payload = tmp_path / "src" / dp.BUNDLE_NAME
        (payload / "_internal").mkdir(parents=True)
        (payload / dp.CHILD_EXE).write_bytes(b"\xcf\xfa\xed\xfe")
        (payload / "_internal" / "link").symlink_to("data")
        app = tmp_path / "T.app"
        (app / "Contents" / "MacOS").mkdir(parents=True)
        placed = dp.place_payload(app, payload)
        assert placed == app / "Contents" / "Resources" / dp.BUNDLE_NAME, (
            "Decision 2a: the payload goes under Contents/Resources, which is "
            "the location the seal control proves is sealable"
        )
        assert placed.is_dir() and not placed.is_symlink()
        assert (placed / "_internal" / "link").is_symlink(), (
            "INTERNAL symlinks must survive the copy — PyInstaller emits them"
        )


# ---------------------------------------------------------------------------
# Gated half — needs the real artifact from `make desktop-bundle`.
# ---------------------------------------------------------------------------


def _app() -> Path:
    app = dp.app_bundle_path()
    if not app.is_dir():
        raise RuntimeError(
            f"no assembled bundle at {app}; run `make desktop-bundle`. An absent "
            "artifact RAISES rather than skips (m8 requires_bundled_model precedent) "
            "so missing evidence cannot hide behind a green run."
        )
    return app


def _payload(app: Path | None = None) -> Path:
    """The placed payload root — `Contents/Resources/<BUNDLE_NAME>/` under
    Decision 2a. Derived in one place so the location cannot drift between
    the assertions that read it."""
    return (app or _app()) / "Contents" / "Resources" / dp.BUNDLE_NAME


def _fake_shell(tmp_path: Path) -> Path:
    """A copy of the real bundle's SHELL (plist + supervisor binary), with no
    payload. 0.75 GB is not copied: every test built on this drives the
    resolver, which refuses or selects before reading the payload through."""
    app = _app()
    fake = tmp_path / "arXMCP.app"
    (fake / "Contents" / "MacOS").mkdir(parents=True)
    shutil.copy2(app / "Contents" / "Info.plist", fake / "Contents" / "Info.plist")
    shutil.copy2(dp.bundle_executable(app), dp.bundle_executable(fake))
    return fake


def _report() -> dict:
    path = dp.DEFAULT_ROOT / "assembly-report.json"
    if not path.is_file():
        raise RuntimeError(f"no assembly report at {path}; run `make desktop-bundle`")
    return json.loads(path.read_text(encoding="utf-8"))


def _probe(executable: Path, out: Path, *, use_open: bool = False) -> dict:
    """Run `--print-child-plan` and return its report."""
    if use_open:
        subprocess.run(
            ["open", "-a", str(executable), "--args", "--print-child-plan", str(out)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        for _ in range(40):
            if out.is_file():
                break
            time.sleep(1)
        if not out.is_file():
            return {}
        return json.loads(out.read_text(encoding="utf-8"))
    proc = subprocess.run(
        [str(executable), "--print-child-plan"], capture_output=True, text=True, timeout=120
    )
    if proc.returncode != 0:
        raise RuntimeError(f"probe failed ({proc.returncode}): {proc.stderr!r}")
    return json.loads(proc.stdout)


@pytest.mark.requires_desktop_bundle
class TestAssembledArtifact:
    def test_layout_places_the_payload_under_contents_resources(self):
        """AC4's structural half, and Decision 2a read off the artifact."""
        app = _app()
        executable = dp.bundle_executable(app)
        payload = _payload()
        assert executable.is_file()
        assert payload.is_dir()
        assert payload.parent == app / "Contents" / "Resources"
        assert executable.parent == app / "Contents" / "MacOS"
        assert payload.parent != executable.parent, (
            "Decision 2a's cost, asserted rather than assumed: the payload is "
            "NOT a sibling of the supervisor, which is why the resolver needs "
            "an explicit two-layout disjunction"
        )
        assert not (app / "Contents" / "MacOS" / dp.BUNDLE_NAME).exists(), (
            "a leftover payload at Decision 2's location would both break the "
            "seal and shadow nothing — it must not be there at all"
        )
        assert (payload / dp.CHILD_EXE).is_file()

    def test_payload_root_is_not_a_symlink(self):
        """The owner's acceptance record, item (b): prove that assembly or
        re-seal introduced no symlink at the payload root."""
        payload = _payload()
        assert not payload.is_symlink()
        assert not stat.S_ISLNK(payload.lstat().st_mode)

    def test_supervisor_resolves_the_child_inside_the_bundle(self, tmp_path: Path):
        """AC4, RE-MEASURED at the new location. Runs the real bundled binary;
        asserts on what its own resolver returned — including which arm."""
        app = _app()
        report = _probe(dp.bundle_executable(app), tmp_path / "plan.json")
        assert report["error"] is None, report
        assert report["layout"] == "bundle-resources", report
        assert report["payload_root_is_symlink"] is False
        child = Path(report["child_argv0"])
        assert child.is_file()
        assert app.resolve() in child.parents, (
            f"child_argv0 {child} resolved OUTSIDE the bundle {app}"
        )
        assert child.parent.name == dp.BUNDLE_NAME
        assert child.parent.parent == app.resolve() / "Contents" / "Resources"
        assert Path(report["supervisor_exe"]).parent == app.resolve() / "Contents" / "MacOS"

    def test_a_symlinked_payload_root_is_still_refused(self, tmp_path: Path):
        """AC4's negative arm, against the BUNDLE root rather than the onedir
        root m10 could only reach. Operates on a copy of the shell so the real
        artifact is untouched; the payload is not copied (0.75 GB) because the
        refusal happens before the root is ever read through."""
        fake = _fake_shell(tmp_path)
        elsewhere = tmp_path / "evil"
        (elsewhere / dp.CHILD_EXE).parent.mkdir(parents=True)
        shutil.copy2(_payload() / dp.CHILD_EXE, elsewhere / dp.CHILD_EXE)
        (fake / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
        (fake / "Contents" / "Resources" / dp.BUNDLE_NAME).symlink_to(elsewhere)
        report = _probe(dp.bundle_executable(fake), tmp_path / "plan.json")
        assert report["layout"] == "bundle-resources"
        assert report["payload_root_is_symlink"] is True
        assert report["child_argv0"] is None
        assert "symlink" in report["error"], report

    def test_placed_child_is_byte_identical_to_the_onedir(self):
        """AC5. Re-derived here rather than trusting the build's own flag, so
        the assertion survives a change to `assemble`."""
        report = _report()
        assert report["payload_identical_to_onedir"] is True
        onedir = dp.DEFAULT_ROOT / "dist" / dp.BUNDLE_NAME
        placed = _payload()
        drift = dp.manifest_diff(dp.file_manifest(onedir), dp.file_manifest(placed))
        assert drift == [], f"bundling substituted a different child at {drift[:10]}"

    @pytest.mark.requires_desktop_bundle
    def test_no_model_weights_reached_the_assembled_bundle(self):
        """m8's weights-free guard, re-run over the ASSEMBLED artifact
        (critique M4).

        Every other m7/m8 guard was re-pointed at the placed tree; this one
        was left measuring only the pre-bundle onedir, so a placement or
        shell-build step that introduced weights would not have been seen by
        anything. The suffix set and the HF-cache shape are m8's, deliberately
        duplicated rather than imported: `tests/test_desktop_bundled_model.py`
        is `requires_bundled_model`-gated and needs ~4.6 GB of real weights to
        even collect, and this gate must not acquire that prerequisite.

        The walk covers the WHOLE `.app`, not just the payload — the shell is
        the half m8 never saw.
        """
        weight_suffixes = (".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".onnx", ".h5")
        app = _app()
        weights: list[str] = []
        hf_cache: list[str] = []
        walked = 0
        for path in app.rglob("*"):
            rel = path.relative_to(app).as_posix()
            if path.is_dir():
                if path.name in {"hub", "huggingface"} and "models--" in "".join(
                    child.name for child in path.iterdir()
                ):
                    hf_cache.append(rel)
                continue
            if path.is_symlink():
                continue
            walked += 1
            if path.suffix in weight_suffixes or path.name.startswith("pytorch_model"):
                weights.append(rel)
        assert weights == [], f"model weight files inside the assembled .app: {weights}"
        assert hf_cache == [], f"HF cache tree inside the assembled .app: {hf_cache}"
        # A walk that found nothing cannot distinguish clean from broken.
        assert walked >= 4000, f"bundle walk covered only {walked} files"

    def test_m7_and_m8_guards_hold_over_the_assembled_payload(self):
        """AC6: the build-root string scan (including embedded PYZ `.pyc`
        bytes), the single-OpenMP inventory, and `direct_url.json`
        sanitization, re-run against the PLACED tree rather than the pre-bundle
        onedir."""
        report = _report()
        assert report["scan"]["hits"] == {}
        assert report["scan"]["files_scanned"] > 1000
        assert report["scan"]["embedded"]["pyc_entries"] > 0, (
            "a vacuous embedded scan is not a clean one"
        )
        dp._require_single_libomp(report["libomp"])
        placed = _payload()
        assert list(placed.rglob("direct_url.json")) == []

    def test_bundled_supervisor_declares_the_floor(self):
        """AC7: m9's regression, re-run over the ARTIFACT's copy of the binary
        rather than over `target/release/`."""
        app = _app()
        assert set(_declared_minos(dp.bundle_executable(app))) == {FLOOR}
        plist = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
        assert plist["LSMinimumSystemVersion"] == FLOOR

    def test_frozen_executables_minos_is_measured_and_pinned(self):
        """AC10 — the gap m15's research surfaced, closed by measurement.

        A mismatch here is not automatically a regression: it means the
        PyInstaller bootloader's own deployment target moved, and the pin plus
        the reasoning in `FROZEN_EXECUTABLE_MINOS` must be re-recorded together.
        """
        payload = _payload()
        measured = {
            name: sorted(set(_declared_minos(payload / name)))
            for name in FROZEN_EXECUTABLE_MINOS
        }
        assert measured == {k: [v] for k, v in FROZEN_EXECUTABLE_MINOS.items()}, (
            f"the frozen executables now declare {measured}; re-record the pin AND "
            f"the note above it, which explains why it differs from the {FLOOR} floor"
        )

    def test_the_two_declared_floors_disagree_and_that_is_recorded(self):
        """The consequence of the pin above, asserted so it cannot be quietly
        forgotten: the assembled artifact carries two different declared
        minimums, and the frozen half is the lower one."""
        app = _app()
        rust = set(_declared_minos(dp.bundle_executable(app)))
        # Critique M5: this compared the measured Rust minos against the
        # PINNED constant, so the "two floors disagree" claim rested on the
        # pin agreeing with itself. Measure both halves off the artifact; the
        # constants are then a separate, independently-asserted record (see
        # the test above) rather than this test's own evidence.
        payload = _payload()
        frozen = {
            value
            for name in FROZEN_EXECUTABLE_MINOS
            for value in _declared_minos(payload / name)
        }
        assert rust == {FLOOR}
        assert frozen != rust, (
            "if these now agree, the artifact improved — update this test and the "
            "README's 'Assembled artifact layout' section in the same commit"
        )
        # Also measured, not compared constant-to-constant (critique M5): the
        # LOWEST minos anywhere in the payload's Mach-O closure. A string
        # comparison is enough only because every value here is a two-part
        # version below 100; parse to tuples so "9.0" cannot sort above "14.0".
        def _version(text: str) -> tuple[int, ...]:
            return tuple(int(part) for part in text.split("."))

        measured_floor = min(
            (
                _version(value)
                for macho in dp.macho_inventory(payload)
                for value in _declared_minos(macho)
            ),
            default=None,
        )
        assert measured_floor is not None, "no Mach-O in the payload declared a minos"
        assert measured_floor == _version(PAYLOAD_MINOS_FLOOR), (
            f"payload minos floor moved to {measured_floor}; re-record "
            f"PAYLOAD_MINOS_FLOOR and the census note above it"
        )
        assert measured_floor < _version(FLOOR)

    def test_the_placed_payload_still_executes_after_signing(self, tmp_path: Path):
        """The payload is signed in place and then copied. A signature applied
        in the wrong order, or a copy that broke one, shows up as a killed
        process — so run the frozen probe out of the ASSEMBLED bundle.

        This is the strongest launch evidence m15 has that does not need the
        external model cache; it is NOT the full double-click-to-ready-server
        claim, which needs weights and is m8's / e4's surface.
        """
        payload = _payload()
        proc = subprocess.run(
            [str(payload / dp.PROBE_EXE)],
            input=json.dumps({"latex": ["x^2"]}),
            capture_output=True,
            text=True,
            timeout=600,
            env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home())},
        )
        assert proc.returncode == 0, (
            f"the signed, placed frozen probe did not run: rc={proc.returncode} "
            f"stderr={proc.stderr[-2000:]!r}"
        )
        assert json.loads(proc.stdout)


@pytest.mark.requires_desktop_bundle
class TestDualLayoutResolution:
    """Decision 2a's disjunction, driven through the REAL bundled binary.

    The Rust unit tests cover the same three outcomes against fabricated
    layouts; these run the shipped executable, because the arms exist to be
    correct in the artifact and a unit test cannot say which one a compiled,
    signed, bundle-resident binary takes. The bundle arm is asserted in
    `TestAssembledArtifact::test_supervisor_resolves_the_child_inside_the_bundle`;
    the other two are here.
    """

    def test_the_sibling_arm_still_resolves_for_the_onedir_shape(self, tmp_path: Path):
        """ARM 2. The same binary, taken OUT of the bundle and given m7's
        onedir shape, resolves the sibling payload — this is what every m10
        gate and every developer run depends on, and Decision 2a must not
        have traded it away for the bundle arm."""
        staged = tmp_path / "onedir"
        (staged / dp.BUNDLE_NAME).mkdir(parents=True)
        shutil.copy2(dp.bundle_executable(_app()), staged / "supervisor")
        shutil.copy2(_payload() / dp.CHILD_EXE, staged / dp.BUNDLE_NAME / dp.CHILD_EXE)
        report = _probe(staged / "supervisor", tmp_path / "plan.json")
        assert report["error"] is None, report
        assert report["layout"] == "supervisor-sibling", report
        assert Path(report["child_argv0"]) == (
            (staged / dp.BUNDLE_NAME / dp.CHILD_EXE).resolve()
        )

    def test_neither_layout_present_is_refused_not_guessed(self, tmp_path: Path):
        """THE REFUSAL. A bundle shell with no payload in either location
        refuses by name instead of returning a root that does not exist."""
        fake = _fake_shell(tmp_path)
        report = _probe(dp.bundle_executable(fake), tmp_path / "plan.json")
        assert report["child_argv0"] is None
        assert report["layout"] is None, report
        assert report["payload_root"] is None, report
        assert "child payload root missing" in report["error"], report
        assert "supervisor-sibling" in report["error"], (
            "the refusal must name BOTH layouts it checked, or a reader cannot "
            "tell a wrong-location bug from an absent payload"
        )

    def test_the_bundle_arm_wins_over_a_stray_macos_payload(self, tmp_path: Path):
        """Precedence, against the real binary: a payload left at Decision 2's
        old `Contents/MacOS/` location must NOT shadow the sealed one."""
        fake = _fake_shell(tmp_path)
        for relative in ("Resources", "MacOS"):
            root = fake / "Contents" / relative / dp.BUNDLE_NAME
            root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_payload() / dp.CHILD_EXE, root / dp.CHILD_EXE)
        report = _probe(dp.bundle_executable(fake), tmp_path / "plan.json")
        assert report["layout"] == "bundle-resources", report
        assert Path(report["child_argv0"]).parent.parent.name == "Resources"


@pytest.mark.requires_desktop_bundle
class TestOuterSeal:
    """Decision 1 step 4, at Decision 2a's location — and it now SUCCEEDS.

    The previous dispatch measured the seal failing at `Contents/MacOS` and
    pinned `sealed is False` so the finding could not evaporate. Decision 2a
    moved the payload, so that pin INVERTS here: the seal is asserted to
    succeed, and `codesign --verify --strict`'s own output is read back rather
    than the return code alone.

    The A/B location control stays in the build. It is what makes any future
    failure attributable — layout, or this host's `codesign`.

    What this class does NOT establish is unchanged: a sealed bundle is not a
    notarized one, and ADR Decision 3 is answerable only with a certificate
    this project does not have.
    """

    @pytest.mark.requires_desktop_bundle
    def test_the_seal_actually_covers_the_payload_bytes(self, tmp_path: Path):
        """The seal's COVERAGE, measured rather than asserted (critique M1).

        `apps/desktop/README.md` calls `_CodeSignature/` "the outer seal, over
        everything below", and `codesign --verify` passing on an intact bundle
        does not establish that: a seal that covered only `Contents/MacOS`
        would also pass. The discriminating experiment is to break a payload
        byte and require the verdict to change.

        Run against a COPY so the real artifact is never mutated -- a test
        that corrupts the bundle it is verifying would hand every later test
        in the session a damaged input.
        """
        app = _app()
        copied = tmp_path / app.name
        shutil.copytree(app, copied, symlinks=True)
        before = subprocess.run(  # noqa: S603 - our own artifact
            ["codesign", "--verify", "--strict", str(copied)],
            capture_output=True, text=True, timeout=600,
        )
        assert before.returncode == 0, (
            f"the copied bundle must verify before the mutation, else the "
            f"experiment proves nothing: {before.stderr}"
        )
        victim = copied / "Contents" / "Resources" / dp.BUNDLE_NAME / dp.CHILD_EXE
        assert victim.is_file(), victim
        original = victim.read_bytes()
        victim.write_bytes(original + b"\x00tamper")
        after = subprocess.run(  # noqa: S603 - our own artifact
            ["codesign", "--verify", "--strict", str(copied)],
            capture_output=True, text=True, timeout=600,
        )
        assert after.returncode != 0, (
            "mutating a payload executable inside Contents/Resources did NOT "
            "invalidate the outer seal -- the seal does not cover the payload, "
            "and the README's 'over everything below' is false"
        )

    def test_every_nested_macho_was_signed(self):
        signing = _report()["signing"]
        assert signing["macho_signed"] >= 100
        assert signing["ad_hoc"] is True
        assert signing["executables_verified"] == sorted([dp.CHILD_EXE, dp.PROBE_EXE])

    def test_the_outer_seal_succeeded_and_verifies(self):
        """The inverted pin. `assemble` raises when the seal fails, so this
        also documents that a sealed bundle is the only artifact that ships."""
        seal = _report()["seal"]
        assert seal["attempted"] is True
        assert seal["sealed"] is True, (
            f"the outer seal FAILED at Contents/Resources: {seal.get('error')!r}. "
            "Decision 2a moved the payload here precisely because this location "
            "seals; a failure is a real finding — read the location control below "
            "to attribute it to the layout or to this host's codesign."
        )
        assert seal["returncode"] == 0
        assert seal["verified"] is True, seal
        assert "valid on disk" in str(seal["verify_output"]), seal

    def test_the_seal_is_verified_against_the_artifact_not_the_report(self):
        """`codesign --verify --strict` re-run HERE, against the bundle on
        disk. The report records what the build saw; this records what the
        artifact is now."""
        output = dp.codesign_verify(_app())
        assert "valid on disk" in output, output
        assert "satisfies its Designated Requirement" in output, output

    def test_the_location_control_separates_layout_from_payload(self):
        """The A/B that decided the location, kept live: one plain `data.txt`,
        two locations, nothing arXMCP-specific. It is the standing explanation
        for why the payload is where it is."""
        control = _report()["seal_location_control"]
        assert control["macos"]["sealed"] is False, (
            "Contents/MacOS now seals a plain data file. That would retire the "
            "reason Decision 2a exists — re-record the ADR before changing the "
            "layout back"
        )
        assert control["resources"]["sealed"] is True

    def test_ad_hoc_signing_is_byte_stable(self):
        """ADR 'does NOT decide' item 4, resolved.

        m7's `verify_determinism` measures the UNSIGNED onedir. Assembly adds
        exactly one byte-changing step, so extending the determinism claim to
        the assembled artifact reduces to: is that step a function of its
        input? Measured on this host, for this identity — not a guarantee
        about all `codesign` implementations, which is why it is recorded as
        its own axis rather than folded into m7's manifest claim.
        """
        stability = _report()["signature_stability"]
        assert stability["byte_stable"] is True, stability


@pytest.mark.requires_desktop_bundle
class TestRelocation:
    """Gatekeeper path translocation: attempted, NOT achieved, recorded.

    The owner's acceptance record asks specifically whether
    `std::env::current_exe()` still resolves to `Contents/MacOS/supervisor`
    when a quarantined app runs from a randomized read-only mount. It also
    says: if that cannot be measured on this host, say so explicitly and
    record it as unverified rather than asserting it.

    **It still could not be measured here, and the reason narrowed.** Setting
    `com.apple.quarantine` on the assembled bundle and launching it through
    `open(1)` produces exit 0 and no process. Under Decision 2 the bundle had
    no valid outer seal at all, which was reason enough; the bundle now seals
    (`TestOuterSeal`) and the quarantined launch is STILL refused, so what
    remains is the ad-hoc signature itself — Gatekeeper wants a Developer ID,
    the certificate e4 is blocked on. Re-measured 2026-08-12, not inherited.

    What IS measured is the weaker property the expectation rests on: the
    bundle relocated WHOLE to an arbitrary path, launched through
    LaunchServices rather than by direct exec, still resolves the payload
    inside the RELOCATED bundle — via the bundle arm, off the relocated
    `current_exe()`. Translocation relocates the bundle as a unit too, so this
    is evidence for the expectation — it is not the expectation itself, and
    the difference is why this docstring exists.
    """

    def test_relocated_bundle_launched_via_launchservices_still_resolves(
        self, tmp_path: Path
    ):
        staged = tmp_path / "arXMCP.app"
        subprocess.run(["ditto", str(_app()), str(staged)], check=True, timeout=1800)
        report = _probe(staged, tmp_path / "plan.json", use_open=True)
        assert report, "LaunchServices did not start the relocated bundle at all"
        assert report["error"] is None
        assert report["layout"] == "bundle-resources", report
        assert Path(report["supervisor_exe"]).parent == staged.resolve() / "Contents" / "MacOS"
        assert Path(report["child_argv0"]).parent.parent == (
            staged.resolve() / "Contents" / "Resources"
        ), "the resolution must follow the RELOCATED bundle, not the built one"

    def test_quarantine_blocks_the_launch_so_translocation_is_unverified(
        self, tmp_path: Path
    ):
        """The negative measurement, asserted so the gap is visible in a green
        run instead of living only in prose.

        If this test starts FAILING because the quarantined bundle does launch,
        that is the moment translocation becomes measurable — replace it with
        the real assertion about `current_exe()` under translocation.
        """
        # SAME-RUN POSITIVE CONTROL (critique M6/M10). Without it, "the
        # quarantined bundle produced no report" is indistinguishable from
        # "`open(1)` never delivers a report in this harness at all" — the
        # permission-denied-as-verified-absence mistake that mis-filed issue
        # #423, and the reason `test_supervisor_owns_a_native_window_while_
        # running` demands a positive control before concluding absence.
        # Stage the SAME bundle, unquarantined, and require it to report
        # through the SAME `open(1)` path first.
        control = tmp_path / "control" / "arXMCP.app"
        control.parent.mkdir()
        subprocess.run(["ditto", str(_app()), str(control)], check=True, timeout=1800)
        control_out = tmp_path / "control-plan.json"
        control_report = _probe(control, control_out, use_open=True)
        assert control_report, (
            "the UNQUARANTINED control did not report through open(1) either, "
            "so this run cannot distinguish 'quarantine blocked the launch' "
            "from 'the harness never observes a launch'. Fix the harness "
            "before reading anything into the negative below."
        )

        staged = tmp_path / "arXMCP.app"
        subprocess.run(["ditto", str(_app()), str(staged)], check=True, timeout=1800)
        subprocess.run(
            [
                "xattr",
                "-w",
                "com.apple.quarantine",
                "0081;00000000;pytest;00000000-0000-0000-0000-000000000000",
                str(staged),
            ],
            check=True,
            timeout=60,
        )
        out = tmp_path / "plan.json"
        report = _probe(staged, out, use_open=True)
        assert report == {}, (
            "a quarantined ad-hoc-signed bundle LAUNCHED — note the outer seal "
            "is now valid, so the remaining refusal is about the ad-hoc "
            "identity. Gatekeeper path "
            "translocation is now measurable on this host and the m15 'unverified' "
            f"record must be replaced with a real measurement. Probe said: {report}"
        )


class TestGateWiring:
    """The zero-skip detector, following the m6/m7 precedent."""

    def test_no_test_in_this_module_returns_instead_of_skipping(self):
        """A bare `return` is invisible to `DESKTOP_BUNDLE_GATE`'s skip
        detector, so a gate test must raise or skip, never quietly pass."""
        source = Path(__file__).read_text(encoding="utf-8")
        for name in ("_app", "_report", "_payload", "_fake_shell"):
            body = source.split(f"def {name}(")[1].split("\ndef ")[0]
            assert "pytest.skip" not in body, (
                f"{name} must RAISE on a missing artifact (m8 precedent), not skip"
            )

    @pytest.mark.skipif(
        os.environ.get(GATE_ENV) != "1", reason="only meaningful inside the gate"
    )
    def test_the_gate_env_var_is_set_when_the_gate_runs(self):
        assert os.environ[GATE_ENV] == "1"


def _event_names(path: Path) -> list[str]:
    """Event names from a supervisor NDJSON log, or [] when it does not exist."""
    if not path.is_file():
        return []
    return [
        json.loads(line)["event"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


class TestPayloadIntegrityAtLaunch:
    """Issues #436 / #484 round 2 — does the SUPERVISOR consult the seal?

    `TestOuterSeal` already establishes that the outer seal COVERS the payload
    bytes. That was never the gap. The gap, found by an external review of the
    first round, is that the supervisor never asked it:

    * `verify_signature` validated `child_argv[0]` — one Mach-O. The child is
      a PyInstaller **onedir**, so that file is a launcher and the runtime it
      loads (`_internal/libpython3.12.dylib`, every extension module) is not
      covered by its signature at all.
    * `check_payload_completeness` checked that the probe existed. #484's own
      title names two more cases it never looked at.

    The review deleted `_internal/libpython3.12.dylib` from a copy of the
    assembled bundle: both checks passed, `child_status=0`, while the bundle's
    own seal reported the tamper. These tests drive the REAL supervisor out of
    the REAL bundle against a mutated copy and require a refusal — the only
    form of evidence that distinguishes "the seal can detect this" from "we
    look at the seal before we exec".

    Three mutation shapes, because they fail differently: DELETE is what the
    review measured, MODIFY is what a byte-flip attacker does, and ADD is the
    one no manifest of expected filenames can ever catch.
    """

    @staticmethod
    def _clone(app: Path, dest: Path) -> Path:
        """APFS clone, not a byte copy: 804 MB, ~0 s and ~0 additional disk.

        `shutil.copytree` here would cost ~800 MB per mutation arm.
        """
        clone = dest / app.name
        subprocess.run(  # noqa: S603,S607 - our own artifact, fixed argv
            ["/bin/cp", "-Rc", str(app), str(clone)],
            check=True,
            capture_output=True,
            timeout=600,
        )
        return clone

    @staticmethod
    def _launch(clone: Path, home: Path, *, want: str, timeout: float = 90.0) -> dict:
        """Run the cloned supervisor until `want` appears in its event log.

        Popen rather than `run`: on the SUCCESS arm the supervisor goes on to
        boot a real server and never exits on its own, so the test waits for
        the event it needs and then stops the process. `$HOME` is redirected
        so the data root — and therefore the event log — lands in the
        test's own tree and never touches the operator's.
        """
        home.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("ARXMCP_")}
        env["HOME"] = str(home)
        events = (
            home / "Library" / "Application Support" / "arXMCP"
            / "logs" / "supervisor-events.ndjson"
        )
        with (
            (home / "sup-out.log").open("wb") as out,
            (home / "sup-err.log").open("wb") as err,
        ):
            proc = subprocess.Popen(  # noqa: S603
                [str(dp.bundle_executable(clone))],
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                env=env,
            )
        try:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if events.is_file():
                    for line in events.read_text(encoding="utf-8").splitlines():
                        if not line:
                            continue
                        record = json.loads(line)
                        if record["event"] == want:
                            return record
                if proc.poll() is not None and events.is_file():
                    break
                time.sleep(0.25)
            seen = _event_names(events)
            tail = (home / "sup-err.log").read_text(errors="replace")[-800:]
            raise AssertionError(
                f"{want!r} never appeared within {timeout}s. "
                f"Events seen: {seen}. stderr: {tail}"
            )
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)

    @pytest.mark.requires_desktop_bundle
    @pytest.mark.parametrize(
        ("shape", "relative"),
        [
            ("delete", "_internal/libpython3.12.dylib"),
            ("modify", None),
            ("add", "_internal/evil-planted.dylib"),
        ],
    )
    def test_a_tampered_payload_refuses_to_launch(
        self, tmp_path: Path, shape: str, relative: str | None
    ):
        app = _app()
        clone = self._clone(app, tmp_path)
        payload = clone / "Contents" / "Resources" / dp.BUNDLE_NAME

        if shape == "delete":
            target = payload / relative
            assert target.is_file(), f"nothing at {target} to delete"
            target.unlink()
        elif shape == "modify":
            # Any sealed payload Mach-O; flipping a byte in the MIDDLE avoids
            # the header, so the file stays a plausible Mach-O and only the
            # seal's hash can tell.
            candidates = sorted((payload / "_internal").glob("*.so"))
            assert candidates, "no payload extension module to modify"
            target = candidates[0]
            blob = bytearray(target.read_bytes())
            blob[len(blob) // 2] ^= 0xFF
            target.write_bytes(bytes(blob))
        else:
            (payload / relative).write_bytes(b"planted\n")

        record = self._launch(clone, tmp_path / "home", want="payload-seal-invalid")
        assert "detail" in record["fields"], record
        # codesign's own words, not a generic string: an operator needs to
        # know WHICH kind of tamper this was.
        assert "seal" in record["fields"]["detail"] or "resource" in record["fields"]["detail"], (
            f"the refusal must carry codesign's reason: {record['fields']}"
        )

        events = _event_names(
            tmp_path / "home" / "Library" / "Application Support" / "arXMCP"
            / "logs" / "supervisor-events.ndjson"
        )
        assert "child-spawn" not in events, (
            f"the child was spawned DESPITE a tampered payload — this is "
            f"#436/#484 regressed. Events: {events}"
        )

    @pytest.mark.requires_desktop_bundle
    def test_an_intact_payload_still_launches(self, tmp_path: Path):
        """The negative control, and the one that matters most.

        A seal check that refuses everything would pass every arm above while
        making the product unusable. This proves the intact artifact still
        reaches `child-spawn` — i.e. that ~0.3 s of `codesign --verify` on the
        launch path costs a delay and not a working application.
        """
        clone = self._clone(_app(), tmp_path)
        record = self._launch(clone, tmp_path / "home", want="child-spawn")
        assert record["fields"].get("child_pid"), record

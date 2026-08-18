import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from antibody_design.config import load_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(PROJECT_ROOT / name), *args],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


class InstallScriptsTest(unittest.TestCase):
    def test_8gb_smoke_config_keeps_real_models_and_minimal_budgets(self):
        install_root = Path("/tmp/duoforge-smoke-test")
        with patch.dict(os.environ, {"DUOFORGE_HOME": str(install_root)}):
            config = load_config(
                PROJECT_ROOT / "configs" / "smoke_8ucd_crop_8gb.yaml"
            )

        self.assertEqual(config.mode, "de_novo")
        self.assertEqual(config.chains.target, ("A", "B", "C"))
        self.assertEqual(config.run.seeds, (101,))
        self.assertEqual(config.run.samples_per_seed, 1)
        self.assertEqual(config.msa.mode, "none")
        self.assertFalse(config.generators["igdesign"].enabled)
        self.assertTrue(config.generators["antifold"].enabled)
        self.assertEqual(config.generators["antifold"].options["proposal_budget"], 1)
        self.assertEqual(config.predictors["protenix"].options["model_name"], "protenix-v2")
        self.assertEqual(config.predictors["opendde"].options["model_name"], "opendde_v1")
        self.assertEqual(config.predictors["opendde"].options["dtype"], "bf16")
        self.assertEqual(config.predictors["opendde"].options["step"], 2)
        self.assertEqual(config.predictors["opendde"].options["cycle"], 1)

    def test_my_run_paths_match_installer_layout(self):
        install_root = Path("/opt/duoforge-test-layout")
        with patch.dict(os.environ, {"DUOFORGE_HOME": str(install_root)}):
            config = load_config(PROJECT_ROOT / "my_run.yaml")

        self.assertEqual(
            config.backbone.options["checkpoint_path"],
            install_root / "checkpoints" / "rfantibody" / "RFdiffusion_Ab.pt",
        )
        self.assertEqual(
            config.generators["igdesign"].options["lmdesign_checkpoint"],
            install_root
            / "checkpoints"
            / "igdesign"
            / "igdesign_acvr2b_holdout.ckpt",
        )
        self.assertEqual(
            config.predictors["opendde"].options["checkpoint_path"],
            install_root / "runtime" / "opendde" / "checkpoint" / "opendde_abag.pt",
        )

    def test_manifest_matches_installer_checkpoint_identities(self):
        manifest = yaml.safe_load(
            (PROJECT_ROOT / "models" / "manifest.yaml").read_text(encoding="utf-8")
        )["models"]

        self.assertEqual(
            manifest["rfantibody"]["checkpoint_size_bytes"], 483452922
        )
        self.assertEqual(
            manifest["igdesign"]["checkpoint_sizes_bytes"]
            ["igdesign_acvr2b_holdout.ckpt"],
            11506422598,
        )
        self.assertEqual(
            manifest["opendde"]["checksum"]["value"],
            "5cf37441ddef2a2f148b81dd4a218ad274f996fecaf17dec901ab6cf1351713d",
        )
        self.assertEqual(manifest["anarci"]["environment"], "duoforge-igdesign")

        igdesign_environment = yaml.safe_load(
            (PROJECT_ROOT / "envs" / "igdesign.yaml").read_text(encoding="utf-8")
        )
        self.assertIn("muscle=3.8.1551", igdesign_environment["dependencies"])

    def test_setup_dry_run_is_read_only_and_pins_every_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "duoforge-home"

            result = run_script("setup.sh", "--dry-run", "--root", str(install_root))

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertFalse(install_root.exists())
            self.assertIn("profile=standard", result.stdout)
            self.assertIn("required_free_gib=70", result.stdout)
            self.assertIn(
                f"{install_root}/envs/igdesign/bin:", result.stdout
            )
            self.assertIn("libexec/duoforge-anarci", result.stdout)
            for revision in (
                "8fe311415754e0276d1a39c87c57e69c88927a2d",
                "70431eef0afaf0496d7d84e22dfdc1980ec9e70e",
                "789d46786624c01eb44f177ef4c0deeeb6e77469",
                "2475421477ab414b571149ad4a875c390ff8a35d",
                "5028caae7f4a3c36b7eee848cab84c4c05492204",
                "79f6c575056dedef86cb8f405ebb039197923eec",
            ):
                self.assertIn(revision, result.stdout)

    def test_fetch_dry_run_downloads_only_mainline_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "duoforge-home"

            result = run_script(
                "fetch_assets.sh", "--dry-run", "--root", str(install_root)
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertFalse(install_root.exists())
            for filename in (
                "RFdiffusion_Ab.pt",
                "igmpnn_acvr2b_holdout.ckpt",
                "igdesign_acvr2b_holdout.ckpt",
                "model.pt",
                "protenix-v2.pt",
                "opendde_abag.pt",
            ):
                self.assertIn(filename, result.stdout)
            for retired in ("ProteinMPNN_v48", "RF2_ab.pt", "RFab_noframework"):
                self.assertNotIn(retired, result.stdout)
            self.assertNotIn("nt_rna_", result.stdout)
            self.assertNotIn("rnacentral_", result.stdout)
            self.assertNotIn("pdb_seqres_", result.stdout)

    def test_fetch_dry_run_can_skip_selected_model_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "duoforge-home"

            result = run_script(
                "fetch_assets.sh",
                "--dry-run",
                "--skip",
                "igdesign",
                "--skip",
                "protenix",
                "--root",
                str(install_root),
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertFalse(install_root.exists())
            self.assertNotIn("igmpnn_acvr2b_holdout.ckpt", result.stdout)
            self.assertNotIn("igdesign_acvr2b_holdout.ckpt", result.stdout)
            self.assertNotIn("protenix-v2.pt", result.stdout)
            self.assertNotIn("protenix-common/", result.stdout)
            for filename in ("RFdiffusion_Ab.pt", "model.pt", "opendde_abag.pt"):
                self.assertIn(filename, result.stdout)

    def test_fetch_stage_selects_only_that_stage_and_rejects_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "duoforge-home"

            result = run_script(
                "fetch_assets.sh",
                "--dry-run",
                "--stage",
                "sequence-design",
                "--root",
                str(install_root),
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("stage=sequence-design", result.stdout)
            for filename in (
                "igmpnn_acvr2b_holdout.ckpt",
                "igdesign_acvr2b_holdout.ckpt",
                "model.pt",
            ):
                self.assertIn(filename, result.stdout)
            for filename in ("RFdiffusion_Ab.pt", "protenix-v2.pt", "opendde_abag.pt"):
                self.assertNotIn(filename, result.stdout)

            conflict = run_script(
                "fetch_assets.sh",
                "--dry-run",
                "--stage",
                "fold",
                "--skip",
                "protenix",
                "--root",
                str(install_root),
            )
            self.assertEqual(conflict.returncode, 2, conflict.stdout)
            self.assertIn("--stage cannot be combined with --skip", conflict.stdout)

    def test_cleanup_stage_is_allowlisted_and_requires_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "duoforge-home"
            checkpoint = (
                install_root / "checkpoints/rfantibody/RFdiffusion_Ab.pt"
            )
            partial = checkpoint.with_name(checkpoint.name + ".part")
            unknown = checkpoint.parent / "keep-me.pt"
            output = install_root / "outputs/result.txt"
            for path in (checkpoint, partial, unknown, output):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"asset")

            preview = run_script(
                "cleanup_assets.sh",
                "--stage",
                "backbone",
                "--root",
                str(install_root),
            )
            self.assertEqual(preview.returncode, 0, preview.stdout)
            self.assertIn("mode=dry-run", preview.stdout)
            self.assertTrue(checkpoint.exists())
            self.assertTrue(partial.exists())

            executed = run_script(
                "cleanup_assets.sh",
                "--execute",
                "--stage",
                "backbone",
                "--root",
                str(install_root),
            )
            self.assertEqual(executed.returncode, 0, executed.stdout)
            self.assertFalse(checkpoint.exists())
            self.assertFalse(partial.exists())
            self.assertTrue(unknown.exists())
            self.assertTrue(output.exists())
            self.assertIn("asset_bytes_before=10", executed.stdout)
            self.assertIn("asset_bytes_after=0", executed.stdout)

    def test_cleanup_refuses_repository_root(self):
        result = run_script(
            "cleanup_assets.sh",
            "--execute",
            "--stage",
            "fold",
            "--root",
            str(PROJECT_ROOT),
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("refusing unsafe root", result.stdout)

    def test_smoke_workflow_default_is_read_only_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            smoke_root = Path(tmp) / "smoke"
            result = run_script(
                "run_smoke.sh", "--dry-run", "--root", str(smoke_root)
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertFalse(smoke_root.exists())
            self.assertIn("--stage backbone", result.stdout)
            self.assertIn("--stage sequence-design", result.stdout)
            self.assertIn("--stage fold", result.stdout)

    def test_template_db_is_explicit_and_never_adds_rna_databases(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "duoforge-home"

            result = run_script(
                "fetch_assets.sh",
                "--dry-run",
                "--with-template-db",
                "--root",
                str(install_root),
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("pdb_seqres_2022_09_28.fasta.zst", result.stdout)
            self.assertNotIn("nt_rna_", result.stdout)
            self.assertNotIn("rnacentral_", result.stdout)
            self.assertNotIn("rfam_", result.stdout)


if __name__ == "__main__":
    unittest.main()

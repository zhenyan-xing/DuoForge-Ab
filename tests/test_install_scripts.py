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

    def test_setup_dry_run_is_read_only_and_pins_every_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "duoforge-home"

            result = run_script("setup.sh", "--dry-run", "--root", str(install_root))

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertFalse(install_root.exists())
            self.assertIn("profile=standard", result.stdout)
            self.assertIn("required_free_gib=70", result.stdout)
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

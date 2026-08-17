import tempfile
import unittest
from pathlib import Path

from antibody_design.config import ConfigError, load_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PDB = PROJECT_ROOT / "data" / "examples" / "mock_complex.pdb"


def write_config(directory: Path, mode: str) -> Path:
    mode_input = (
        f"target_structure: {EXAMPLE_PDB}\n  framework: {EXAMPLE_PDB}"
        if mode == "de_novo"
        else f"complex_structure: {EXAMPLE_PDB}"
    )
    hotspots = "[A:1]" if mode == "de_novo" else "[]"
    path = directory / f"{mode}.yaml"
    path.write_text(
        f"""
run:
  run_id: test-{mode}
  output_dir: {directory / mode}
  seeds: [101]
  samples_per_seed: 5
mode: {mode}
input:
  {mode_input}
chains:
  heavy: H
  light: L
  target: [A]
design:
  loops: [H1]
  residues: [H:2]
  fixed_residues: [H:3]
hotspots: {hotspots}
numbering:
  executable: ANARCI
backbone:
  rfantibody:
    executable: rfdiffusion
    upstream_root: /opt/RFantibody
    checkpoint_path: /models/rfantibody/rfdiffusion.pt
    num_designs: 2
generators:
  igdesign:
    enabled: true
    upstream_root: /opt/igdesign
    lmdesign_checkpoint: /models/igdesign.ckpt
    pmpnn_checkpoint: /models/igmpnn.ckpt
  antifold:
    enabled: true
    upstream_root: /opt/AntiFold
    checkpoint_path: /models/antifold.pt
predictors:
  protenix:
    enabled: true
    executable: protenix
    runtime_root: /models/protenix
    checkpoint_path: /models/protenix/checkpoint/protenix-v2.pt
  opendde:
    enabled: true
    executable: opendde
    runtime_root: /models/opendde
    checkpoint_path: /models/opendde/checkpoint/opendde_abag.pt
msa:
  mode: target_only
templates:
  target_hits: {{}}
  antibody_hits: {{}}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


class ConfigTest(unittest.TestCase):
    def test_parses_de_novo_and_local_redesign(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            de_novo = load_config(write_config(root, "de_novo"))
            local = load_config(write_config(root, "local_redesign"))

            self.assertEqual(de_novo.mode, "de_novo")
            self.assertEqual([str(item) for item in de_novo.hotspots], ["A:1"])
            self.assertEqual(local.mode, "local_redesign")
            self.assertEqual(local.hotspots, ())
            self.assertEqual(local.run.samples_per_seed, 5)

    def test_de_novo_requires_hotspots(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), "de_novo")
            path.write_text(
                path.read_text(encoding="utf-8").replace("hotspots: [A:1]", "hotspots: []"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "hotspot"):
                load_config(path)

    def test_full_backbone_de_novo_is_explicitly_not_implemented(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), "de_novo")
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "mode: de_novo", "mode: full_backbone_de_novo"
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "not implemented"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()

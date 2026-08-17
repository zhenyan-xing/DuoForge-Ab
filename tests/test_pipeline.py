import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

from antibody_design.analysis.candidates import merge_generation_proposals
from antibody_design.analysis.geometry import compute_geometry
from antibody_design.analysis.report import write_records
from antibody_design.config import load_config
from antibody_design.design.base import ExternalCommand, SequenceProposal
from antibody_design.pipeline import (
    DesignPipeline,
    JobStore,
    _assign_model_top1,
    expand_prediction_jobs,
)
from antibody_design.predict.io import write_prediction_input
from antibody_design.prepare import PreparationError, prepare_parent
from antibody_design.schemas import Candidate, MSAConfig, Parent, PredictionRecord, TemplateConfig

from test_config import EXAMPLE_PDB, write_config


class PipelineTest(unittest.TestCase):
    def test_cross_generator_duplicate_is_one_candidate_with_two_provenances(self):
        parent = Parent(
            parent_id="parent-1",
            mode="local_redesign",
            structure_path=Path("parent.pdb"),
            heavy_chain="H",
            light_chain="L",
            target_chains=("A",),
            heavy_sequence="AAA",
            light_sequence="GG",
            designable_positions=("H:2",),
        )
        proposals = {
            "igdesign": [
                SequenceProposal("ACA", "GG", 11, 0, {"ce_loss": 1.2}),
                SequenceProposal("ACA", "GG", 11, 1, {"ce_loss": 1.3}),
            ],
            "antifold": [
                SequenceProposal("ACA", "GG", 11, 0, {"score": -0.4}),
            ],
        }

        candidates, generations, shortfalls = merge_generation_proposals(
            parent, proposals, unique_per_generator=1
        )
        jobs = expand_prediction_jobs(candidates, (11,), 5, ("protenix-v2", "opendde_v1"))

        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(generations), 2)
        self.assertEqual({item.generator for item in generations}, {"igdesign", "antifold"})
        self.assertEqual(shortfalls, {})
        self.assertEqual(len(jobs), 2)
        self.assertTrue(all(job.samples_per_seed == 5 for job in jobs))
        self.assertTrue(candidates[0].liabilities)

    def test_dry_run_plans_real_stages_and_keeps_hotspots_out_of_predictors(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(write_config(Path(tmp), "de_novo"))
            result = DesignPipeline.from_config(config).run(config, dry_run=True)

            plan = json.loads(result.plan_path.read_text(encoding="utf-8"))
            by_adapter = {stage["adapter"]: stage for stage in plan["stages"]}
            self.assertEqual(
                set(by_adapter),
                {"rfantibody-rfdiffusion", "igdesign", "antifold", "protenix-v2", "opendde_v1"},
            )
            rf_command = " ".join(by_adapter["rfantibody-rfdiffusion"]["commands"][0]["argv"])
            self.assertIn("--hotspots", rf_command)
            self.assertIn("A1", rf_command)
            for name in ("protenix-v2", "opendde_v1"):
                command = " ".join(by_adapter[name]["commands"][0]["argv"])
                self.assertNotIn("hotspot", command.lower())
                self.assertNotIn("epitope", command.lower())

            predictor_input = json.loads(
                Path(by_adapter["protenix-v2"]["metadata"]["input_path"]).read_text(
                    encoding="utf-8"
                )
            )
            chain_ids = [
                entity["proteinChain"]["id"][0]
                for entity in predictor_input[0]["sequences"]
            ]
            self.assertEqual(chain_ids, ["H", "L", "A"])
            self.assertNotIn("hotspots", predictor_input[0])
            self.assertNotIn("templateStructure", predictor_input[0])

    def test_input_quiver_dry_run_defers_parent_dependent_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quiver = root / "parents.qv"
            quiver.write_text("not decoded during dry-run", encoding="utf-8")
            path = write_config(root, "de_novo")
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    f"framework: {EXAMPLE_PDB}", f"input_quiver: {quiver}"
                ),
                encoding="utf-8",
            )
            config = load_config(path)
            result = DesignPipeline.from_config(config).run(config, dry_run=True)
            plan = json.loads(result.plan_path.read_text(encoding="utf-8"))

        self.assertEqual([stage["adapter"] for stage in plan["stages"]], ["rfantibody-rfdiffusion"])
        command = plan["stages"][0]["commands"][0]
        self.assertEqual(Path(command["argv"][0]).name, "qvextract")
        self.assertNotIn("checkpoint", " ".join(command["missing"]).lower())
        self.assertIn("deferred", plan["note"])

    def test_prediction_input_keeps_all_targets_and_target_only_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_a = root / "A.hhr"
            target_b = root / "B.a3m"
            target_a.write_text("mock template hits\n", encoding="utf-8")
            target_b.write_text(">mock\nGG\n", encoding="utf-8")
            parent = Parent(
                parent_id="p",
                mode="local_redesign",
                structure_path=root / "complex.pdb",
                heavy_chain="H",
                light_chain="L",
                target_chains=("A", "B"),
                heavy_sequence="AA",
                light_sequence="CC",
                target_sequences={"A": "GG", "B": "TT"},
                hotspots=("A:1",),
            )
            candidate = Candidate("c", "p", "AA", "CC", (), 0, "exact")
            path = write_prediction_input(
                parent,
                candidate,
                7,
                root,
                MSAConfig("none", {}),
                TemplateConfig(target_hits={"A": target_a, "B": target_b}),
            )
            payload = json.loads(path.read_text(encoding="utf-8"))[0]
            proteins = [item["proteinChain"] for item in payload["sequences"]]
            self.assertEqual([item["id"][0] for item in proteins], ["H", "L", "A", "B"])
            self.assertEqual(Path(proteins[0]["templatesPath"]).read_text(), "")
            self.assertEqual(Path(proteins[1]["templatesPath"]).read_text(), "")
            self.assertEqual(proteins[2]["templatesPath"], str(target_a))
            self.assertNotIn("hotspots", payload)
            self.assertNotIn("templateStructure", payload)

    def test_target_template_with_antibody_chains_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), "local_redesign")
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "templates:\n  target_hits: {}",
                    f"templates:\n  target_structure: {EXAMPLE_PDB}\n  target_hits: {{}}",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PreparationError, "must not contain antibody"):
                prepare_parent(load_config(path), execute_numbering=False)

    def test_manifest_has_relative_prediction_path_and_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = Parent("p", "local_redesign", root / "p.pdb", "H", "L", ("A",), "AA", "CC")
            candidates, generations, _ = merge_generation_proposals(
                parent,
                {"igdesign": [SequenceProposal("AA", "CC", 1, 0, {"is_mock": True})]},
                1,
            )
            candidate = candidates[0]
            generation = generations[0]
            prediction = PredictionRecord(
                "pred", candidate.candidate_id, "protenix-v2", 1, 0,
                "structures/c/protenix-v2/seed_1_sample_0.cif",
                {"ranking_score": 0.9, "is_mock": True},
                {"cdr_target_contact_count": 2},
                True,
            )
            paths = write_records(root, [parent], candidates, [generation], [prediction])
            header, row = paths["manifest"].read_text(encoding="utf-8").splitlines()
            self.assertIn("generation_id", header)
            self.assertIn("prediction_model", header)
            self.assertIn("structures/c/protenix-v2", row)
            parent_record = json.loads(paths["parents"].read_text(encoding="utf-8"))
            self.assertEqual(parent_record["structure_path"], "p.pdb")

    def test_manifest_keeps_candidate_when_prediction_has_not_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = Parent("p", "local_redesign", root / "p.pdb", "H", "L", ("A",), "AA", "CC")
            candidates, generations, _ = merge_generation_proposals(
                parent,
                {"igdesign": [SequenceProposal("AA", "CC", 1, 0, {"is_mock": True})]},
                1,
            )
            manifest = write_records(root, [parent], candidates, generations, [])["manifest"]
            with manifest.open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["candidate_id"], candidates[0].candidate_id)
            self.assertEqual(rows[0]["prediction_id"], "")

    def test_resume_retries_failed_job_and_skips_complete_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "result.txt"
            store = JobStore(root, resume=True)
            failed = ExternalCommand((sys.executable, "-c", "raise SystemExit(3)"), ready=True)
            self.assertFalse(store.execute("mock-job", failed, (str(output),)))
            command = ExternalCommand(
                (sys.executable, "-c", f"from pathlib import Path; Path({str(output)!r}).write_text('is_mock: true')"),
                ready=True,
            )
            self.assertTrue(store.execute("mock-job", command, (str(output),)))
            output.write_text("is_mock: changed", encoding="utf-8")
            no_run = ExternalCommand((sys.executable, "-c", "raise SystemExit(9)"), ready=True)
            self.assertTrue(store.execute("mock-job", no_run, (str(output),)))
            state = json.loads((root / "logs/jobs/mock-job.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "complete")
            self.assertEqual(state["exit_code"], 0)
            self.assertEqual(state["attempt"], 2)
            self.assertEqual(
                state["status_history"],
                ["pending", "running", "failed", "pending", "running", "complete"],
            )

    def test_geometry_is_observational_and_uses_angstroms(self):
        parent = Parent(
            parent_id="mock-parent",
            mode="local_redesign",
            structure_path=EXAMPLE_PDB,
            heavy_chain="H",
            light_chain="L",
            target_chains=("A",),
            heavy_sequence="AGS",
            light_sequence="TV",
            target_sequences={"A": "YL"},
            sequence_index_by_author={"H:1": 0, "H:2": 1, "H:3": 2, "L:1": 0, "L:2": 1, "A:1": 0, "A:2": 1},
            designable_positions=("H:2",),
            cdr_positions={"H1": ("H:2",)},
            hotspots=("A:1",),
        )
        metrics = compute_geometry(EXAMPLE_PDB, EXAMPLE_PDB, parent)
        self.assertEqual(metrics["distance_unit"], "angstrom")
        self.assertEqual(metrics["target_aligned_antibody_ca_rmsd"], 0.0)
        self.assertIsNone(metrics.get("pass"))
        self.assertIn("A:1", metrics["hotspot_to_cdr_min_distance"])

    def test_one_model_top1_is_selected_across_seeds(self):
        records = [
            PredictionRecord("p1", "c", "protenix-v2", 1, 0, "a.cif", {"ranking_score": 0.7}),
            PredictionRecord("p2", "c", "protenix-v2", 2, 0, "b.cif", {"ranking_score": 0.9}),
            PredictionRecord("o1", "c", "opendde_v1", 1, 0, "c.cif", {"final_score": 0.2}),
            PredictionRecord("o2", "c", "opendde_v1", 2, 0, "d.cif", {"ranking_score": 99.0}),
        ]
        selected = _assign_model_top1(records, (1, 2))
        self.assertEqual(
            [record.prediction_id for record in selected if record.is_model_top1],
            ["p2", "o1"],
        )


if __name__ == "__main__":
    unittest.main()

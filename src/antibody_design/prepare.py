from __future__ import annotations

import json
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

from .schemas import (
    CDR_LOOPS,
    NumberingMapEntry,
    Parent,
    PipelineConfig,
    ResidueInfo,
    ResidueRef,
    record_dict,
)


class PreparationError(ValueError):
    pass


def _relative_parent_record(parent: Parent, output_dir: Path) -> dict:
    payload = record_dict(parent)
    for key, value in tuple(payload.items()):
        if not key.endswith("_path") or not isinstance(value, str):
            continue
        path = Path(value)
        try:
            payload[key] = str(path.resolve().relative_to(output_dir.resolve()))
        except ValueError:
            payload[key] = value
    return payload


_AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "MSE": "M", "PHE": "F",
    "PRO": "P", "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y",
    "VAL": "V",
}

_IMGT_CDR_RANGES = {
    "H1": (27, 38), "H2": (56, 65), "H3": (105, 117),
    "L1": (27, 38), "L2": (56, 65), "L3": (105, 117),
}


def read_pdb(path: Path) -> dict[str, tuple[ResidueInfo, ...]]:
    if not path.is_file():
        raise PreparationError(f"Input structure does not exist: {path}")
    observed: dict[str, list[tuple[ResidueRef, str]]] = defaultdict(list)
    seen: set[ResidueRef] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith(("ATOM  ", "HETATM")) or len(line) < 27:
                continue
            if line[16].strip() not in {"", "A"}:
                continue
            chain_id = line[21].strip()
            residue_number = line[22:26].strip()
            insertion_code = line[26].strip()
            name3 = line[17:20].strip().upper()
            if not chain_id or not residue_number or name3 not in _AA3_TO_1:
                continue
            ref = ResidueRef(chain_id, residue_number + insertion_code)
            if ref not in seen:
                observed[chain_id].append((ref, name3))
                seen.add(ref)
    if not observed:
        raise PreparationError(f"No protein residues found in structure: {path}")
    return {
        chain: tuple(
            ResidueInfo(ref, name3, _AA3_TO_1[name3], index)
            for index, (ref, name3) in enumerate(items)
        )
        for chain, items in observed.items()
    }


def _sequence(residues: dict[str, tuple[ResidueInfo, ...]], chain: str) -> str:
    return "".join(item.name1 for item in residues[chain])


def _required_chains(
    residues: dict[str, tuple[ResidueInfo, ...]], chains: tuple[str, ...], path: Path
) -> None:
    missing = [chain for chain in chains if chain not in residues]
    if missing:
        raise PreparationError(f"Chains not found in {path}: {', '.join(missing)}")


def expand_hotspots(
    config: PipelineConfig, target_residues: dict[str, tuple[ResidueInfo, ...]]
) -> tuple[ResidueRef, ...]:
    expanded: list[ResidueRef] = []
    for spec in config.hotspots:
        chain_items = target_residues.get(spec.chain_id, ())
        if spec.selector == "*":
            expanded.extend(item.ref for item in chain_items)
        elif "-" in spec.selector:
            start, end = (int(value) for value in spec.selector.split("-", 1))
            expanded.extend(
                item.ref
                for item in chain_items
                if start <= int(item.ref.residue_id.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")) <= end
            )
        else:
            ref = ResidueRef(spec.chain_id, spec.selector)
            if not any(item.ref == ref for item in chain_items):
                raise PreparationError(f"Hotspot not found in target structure: {ref}")
            expanded.append(ref)
    if config.mode == "de_novo" and not expanded:
        raise PreparationError("hotspot expansion selected no target residues")
    return tuple(dict.fromkeys(expanded))


def _write_anarci_input(path: Path, heavy: str, light: str) -> None:
    path.write_text(f">H\n{heavy}\n>L\n{light}\n", encoding="utf-8")


def parse_anarci_output(
    path: Path,
    residues_by_chain: dict[str, tuple[ResidueInfo, ...]],
    heavy_chain: str,
    light_chain: str,
) -> tuple[NumberingMapEntry, ...]:
    records: dict[str, dict] = {}
    current: dict | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "//":
            current = None
        elif current is None and line.startswith("# "):
            name = line[2:].split("|", 1)[0].split()[0]
            current = records.setdefault(name, {"numbering": [], "bounds": None, "type": None})
        elif current is not None and line.startswith("#|"):
            values = [item for item in line.strip("#|").split("|") if item]
            if len(values) >= 6 and values[-2].lstrip("-").isdigit():
                current["type"] = values[1]
                current["bounds"] = (int(values[-2]), int(values[-1]))
        elif current is not None and line and not line.startswith("#"):
            values = line.split()
            if len(values) == 3:
                chain_type, number, aa = values
                insertion = ""
            elif len(values) == 4:
                chain_type, number, insertion, aa = values
            else:
                continue
            if aa != "-":
                current["numbering"].append((chain_type, f"{number}{insertion}", aa))

    entries: list[NumberingMapEntry] = []
    absolute_index = 0
    for record_name, chain_id, expected_types in (
        ("H", heavy_chain, {"H"}),
        ("L", light_chain, {"K", "L"}),
    ):
        record = records.get(record_name)
        residues = residues_by_chain[chain_id]
        if not record or record["bounds"] is None:
            raise PreparationError(f"ANARCI failed to number {record_name} chain")
        start, end = record["bounds"]
        numbering = record["numbering"]
        if record["type"] not in expected_types:
            raise PreparationError(
                f"ANARCI classified {record_name} as {record['type']}, expected {sorted(expected_types)}"
            )
        if start != 0 or end != len(residues) - 1 or len(numbering) != len(residues):
            raise PreparationError(
                f"ANARCI did not provide complete IMGT numbering for {record_name} chain"
            )
        for residue, (_, imgt_id, aa) in zip(residues, numbering):
            if residue.name1 != aa:
                raise PreparationError(
                    f"ANARCI sequence mismatch at {residue.ref}: {residue.name1} != {aa}"
                )
            entries.append(
                NumberingMapEntry(
                    chain_id=chain_id,
                    author_residue_id=residue.ref.residue_id,
                    sequence_index=residue.sequence_index,
                    hlt_absolute_index=absolute_index,
                    imgt_residue_id=imgt_id,
                )
            )
            absolute_index += 1
    return tuple(entries)


def _renumber_pdb(
    source: Path, destination: Path, mapping: tuple[NumberingMapEntry, ...]
) -> None:
    lookup = {
        f"{item.chain_id}:{item.author_residue_id}": item.imgt_residue_id
        for item in mapping
        if item.imgt_residue_id is not None
    }
    output: list[str] = []
    for line in source.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.startswith(("ATOM  ", "HETATM")) and len(line) >= 27:
            chain = line[21].strip()
            author = line[22:26].strip() + line[26].strip()
            imgt = lookup.get(f"{chain}:{author}")
            if imgt:
                number = imgt.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                insertion = imgt[len(number) :]
                if len(insertion) > 1:
                    raise PreparationError(f"IMGT insertion code cannot fit PDB format: {imgt}")
                line = f"{line[:22]}{int(number):4d}{insertion:1s}{line[27:]}"
        output.append(line)
    destination.write_text("".join(output), encoding="utf-8")


def _cdr_positions(
    mapping: tuple[NumberingMapEntry, ...], heavy_chain: str, light_chain: str
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for loop in CDR_LOOPS:
        start, end = _IMGT_CDR_RANGES[loop]
        chain_role = heavy_chain if loop.startswith("H") else light_chain
        refs = []
        for item in mapping:
            if item.chain_id != chain_role:
                continue
            assert item.imgt_residue_id is not None
            number = int(item.imgt_residue_id.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
            if start <= number <= end:
                refs.append(f"{item.chain_id}:{item.author_residue_id}")
        result[loop] = tuple(refs)
    return result


def parse_rfantibody_cdr_remarks(
    path: Path, heavy_chain: str, light_chain: str
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {loop: [] for loop in CDR_LOOPS}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("REMARK PDBinfo-LABEL:"):
            continue
        values = line.split()
        if len(values) < 4 or values[3] not in CDR_LOOPS:
            continue
        loop = values[3]
        chain = heavy_chain if loop.startswith("H") else light_chain
        result[loop].append(f"{chain}:{int(values[2])}")
    return {loop: tuple(refs) for loop, refs in result.items()}


def _write_chain_map(
    path: Path,
    target_residues: dict[str, tuple[ResidueInfo, ...]],
    target_chains: tuple[str, ...],
) -> None:
    collapsed_index = 0
    chains = []
    for chain in target_chains:
        start = collapsed_index
        residues = []
        for item in target_residues[chain]:
            residues.append(
                {
                    "original_chain_id": chain,
                    "original_residue_id": item.ref.residue_id,
                    "sequence_index": item.sequence_index,
                    "rfantibody_target_chain": "T",
                    "rfantibody_target_index": collapsed_index,
                }
            )
            collapsed_index += 1
        chains.append({"original_chain_id": chain, "start": start, "end": collapsed_index, "residues": residues})
    path.write_text(json.dumps({"target_chains": chains}, indent=2) + "\n", encoding="utf-8")


def prepare_parent(
    config: PipelineConfig,
    execute_numbering: bool = False,
    structure_override: Path | None = None,
    parent_id_override: str | None = None,
) -> Parent:
    prepared_dir = config.run.output_dir / "prepared"
    if parent_id_override:
        prepared_dir = prepared_dir / parent_id_override
    prepared_dir.mkdir(parents=True, exist_ok=True)
    if config.templates.target_structure:
        target_template = read_pdb(config.templates.target_structure)
        forbidden = {
            config.chains.heavy, config.chains.light
        }.intersection(target_template)
        if forbidden:
            raise PreparationError(
                "target template must not contain antibody H/L chains: "
                + ", ".join(sorted(forbidden))
            )
        _required_chains(
            target_template, config.chains.target, config.templates.target_structure
        )
    if config.templates.framework_structure:
        framework_template = read_pdb(config.templates.framework_structure)
        _required_chains(
            framework_template,
            (config.chains.heavy, config.chains.light),
            config.templates.framework_structure,
        )
        forbidden = set(config.chains.target).intersection(framework_template)
        if forbidden:
            raise PreparationError(
                "framework template must not contain target chains or an antibody-target pose: "
                + ", ".join(sorted(forbidden))
            )
    if structure_override is not None:
        structure = structure_override
        antibody_residues = target_residues = read_pdb(structure)
    elif config.mode == "local_redesign":
        structure = config.input.complex_structure
        assert structure is not None
        antibody_residues = target_residues = read_pdb(structure)
    else:
        if config.input.framework_auto:
            upstream = config.backbone.options.get("upstream_root")
            if not upstream:
                raise PreparationError(
                    "input.framework=auto requires backbone.rfantibody.upstream_root"
                )
            structure = Path(upstream) / "scripts/examples/example_inputs/hu-4D5-8_Fv.pdb"
        else:
            structure = (
                config.input.frameworks[0]
                if config.input.frameworks
                else config.input.target_structure
            )
        assert structure is not None and config.input.target_structure is not None
        antibody_residues = read_pdb(structure)
        target_residues = read_pdb(config.input.target_structure)

    _required_chains(
        antibody_residues,
        (config.chains.heavy, config.chains.light),
        structure,
    )
    target_path = config.input.complex_structure or config.input.target_structure
    assert target_path is not None
    _required_chains(target_residues, config.chains.target, target_path)
    hotspots = expand_hotspots(config, target_residues)

    heavy = _sequence(antibody_residues, config.chains.heavy)
    light = _sequence(antibody_residues, config.chains.light)
    numbering_input = prepared_dir / "numbering_input.fasta"
    numbering_output = prepared_dir / "anarci_imgt.txt"
    _write_anarci_input(numbering_input, heavy, light)
    numbering: tuple[NumberingMapEntry, ...] = ()
    imgt_path = prepared_dir / "complex_imgt.pdb"
    if execute_numbering:
        if shutil.which(config.numbering.executable) is None:
            raise PreparationError(
                "ANARCI executable is missing; install pinned ANARCI commit "
                "79f6c575056dedef86cb8f405ebb039197923eec in its own environment"
            )
        command = [
            config.numbering.executable,
            "-i", str(numbering_input),
            "-s", "imgt",
            "-o", str(numbering_output),
            "--restrict", "heavy", "light",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        (prepared_dir / "anarci.log").write_text(
            completed.stdout + completed.stderr, encoding="utf-8"
        )
        if completed.returncode != 0:
            raise PreparationError(f"ANARCI failed with exit code {completed.returncode}")
        numbering = parse_anarci_output(
            numbering_output, antibody_residues, config.chains.heavy, config.chains.light
        )
        target_offset = len(antibody_residues[config.chains.heavy]) + len(
            antibody_residues[config.chains.light]
        )
        numbering += tuple(
            NumberingMapEntry(
                chain_id=chain,
                author_residue_id=item.ref.residue_id,
                sequence_index=item.sequence_index,
                hlt_absolute_index=target_offset + collapsed_index,
                imgt_residue_id=None,
            )
            for collapsed_index, (chain, item) in enumerate(
                (chain, item)
                for chain in config.chains.target
                for item in target_residues[chain]
            )
        )
        _renumber_pdb(structure, imgt_path, numbering)

    chain_map_path = prepared_dir / "chain_map.json"
    _write_chain_map(chain_map_path, target_residues, config.chains.target)
    cdrs = (
        _cdr_positions(numbering, config.chains.heavy, config.chains.light)
        if numbering
        else {loop: () for loop in CDR_LOOPS}
    )
    if structure_override is not None and config.mode == "de_novo":
        remarked = parse_rfantibody_cdr_remarks(
            structure_override, config.chains.heavy, config.chains.light
        )
        missing_loops = [loop for loop in config.design.loops if not remarked[loop]]
        if missing_loops:
            raise PreparationError(
                "RFantibody output lacks CDR REMARK labels for selected loops: "
                + ", ".join(missing_loops)
            )
        known_antibody_refs = {
            str(item.ref)
            for chain in (config.chains.heavy, config.chains.light)
            for item in antibody_residues[chain]
        }
        invalid = {
            ref for refs in remarked.values() for ref in refs if ref not in known_antibody_refs
        }
        if invalid:
            raise PreparationError(
                "RFantibody CDR REMARK references residues absent from its output: "
                + ", ".join(sorted(invalid))
            )
        cdrs = remarked
    selected = {
        ref for loop in config.design.loops for ref in cdrs.get(loop, ())
    }.union(str(ref) for ref in config.design.residues)
    selected.difference_update(str(ref) for ref in config.design.fixed_residues)
    mapping_by_author = {
        f"{item.chain_id}:{item.author_residue_id}": item.sequence_index for item in numbering
    }
    if not mapping_by_author:
        mapping_by_author = {
            str(item.ref): item.sequence_index
            for chain in (config.chains.heavy, config.chains.light)
            for item in antibody_residues[chain]
        }
    mapping_by_author.update(
        {
            str(item.ref): item.sequence_index
            for chain in config.chains.target
            for item in target_residues[chain]
        }
    )

    parent_id = parent_id_override or (
        f"{config.run.run_id}-local"
        if config.mode == "local_redesign"
        else f"{config.run.run_id}-rf-0000"
    )
    parent_structure = structure
    if execute_numbering:
        parent_structure = prepared_dir / "reference_complex.pdb"
        if parent_structure.resolve() != structure.resolve():
            shutil.copy2(structure, parent_structure)
    parent = Parent(
        parent_id=parent_id,
        mode=config.mode,
        structure_path=parent_structure,
        heavy_chain=config.chains.heavy,
        light_chain=config.chains.light,
        target_chains=config.chains.target,
        heavy_sequence=heavy,
        light_sequence=light,
        target_sequences={chain: _sequence(target_residues, chain) for chain in config.chains.target},
        sequence_index_by_author=mapping_by_author,
        designable_positions=tuple(sorted(selected)),
        fixed_positions=tuple(str(ref) for ref in config.design.fixed_residues),
        cdr_positions=cdrs,
        hotspots=tuple(str(ref) for ref in hotspots),
        numbering_map_path=(prepared_dir / "numbering_map.jsonl") if numbering else None,
        imgt_structure_path=imgt_path if numbering else None,
        chain_map_path=chain_map_path,
    )
    if numbering:
        parent.numbering_map_path.write_text(
            "".join(json.dumps(record_dict(item)) + "\n" for item in numbering),
            encoding="utf-8",
        )
    (prepared_dir / "parent.json").write_text(
        json.dumps(_relative_parent_record(parent, config.run.output_dir), indent=2) + "\n",
        encoding="utf-8",
    )
    return parent


def write_prepared_complex(parent: Parent, output_dir: Path) -> Path:
    path = output_dir / "prepared" / "parent.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_relative_parent_record(parent, output_dir), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


prepare_complex = prepare_parent


def restore_rfantibody_target_chains(
    rfantibody_pdb: Path,
    target_pdb: Path,
    target_chains: tuple[str, ...],
    destination: Path,
) -> Path:
    """Undo RFantibody's target-to-T collapse using original author IDs."""

    rf_residues = read_pdb(rfantibody_pdb)
    if all(chain in rf_residues for chain in target_chains):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rfantibody_pdb, destination)
        return destination
    if "T" not in rf_residues:
        raise PreparationError(
            f"RFantibody output has neither original target chains nor collapsed T: {rfantibody_pdb}"
        )
    target = read_pdb(target_pdb)
    _required_chains(target, target_chains, target_pdb)
    original = [item.ref for chain in target_chains for item in target[chain]]
    collapsed = [item.ref.residue_id for item in rf_residues["T"]]
    if len(original) != len(collapsed):
        raise PreparationError(
            "RFantibody target residue count differs from the original target; chain restoration is unsafe"
        )
    mapping = dict(zip(collapsed, original))
    output: list[str] = []
    for line in rfantibody_pdb.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.startswith(("ATOM  ", "HETATM")) and len(line) >= 27 and line[21] == "T":
            collapsed_id = line[22:26].strip() + line[26].strip()
            ref = mapping.get(collapsed_id)
            if ref is None:
                raise PreparationError(f"Unmapped RFantibody T residue: {collapsed_id}")
            number = ref.residue_id.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
            insertion = ref.residue_id[len(number) :]
            line = f"{line[:21]}{ref.chain_id}{int(number):4d}{insertion:1s}{line[27:]}"
        output.append(line)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(output), encoding="utf-8")
    return destination

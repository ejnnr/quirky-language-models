import argparse
import os
import subprocess
import sys

from elk_generalization.utils import DATASET_ABBREVS, get_quirky_model_name

parser = argparse.ArgumentParser()
parser.add_argument("--rank", type=int, default=0)

args = parser.parse_args()
env = dict(os.environ)
env["CUDA_VISIBLE_DEVICES"] = str(args.rank)

models_user = "EleutherAI"
datasets_user = "EleutherAI"
models = [
    "EleutherAI/pythia-410m",
    "EleutherAI/pythia-1b",
    "EleutherAI/pythia-1.4b",
    "EleutherAI/pythia-2.8b",
    "EleutherAI/pythia-6.9b",
    "EleutherAI/pythia-12b",
    "meta/Llama-2-7b-hf",
    "mistralai/Mistral-7B-v0.1",
]
ds_names = [
    "capitals",
    "hemisphere",
    "population",
    "sciq",
    "sentiment",
    "nli",
    "authors",
    "addition",
    "subtraction",
    "multiplication",
    "modularaddition",
    "squaring",
]
weak_only = False
templatization_method = "first"
standardize_templates = False
full_finetuning = False

get_ceiling_latent_knowledge = False

# code to modify models and datasets based on rank
models = models[args.rank :: 8]
print(ds_names, models)


def unpack_abbrev(ds_name, abbrev):
    ds_id = f"{datasets_user}/quirky_{ds_name}_raw"
    return ds_id, *DATASET_ABBREVS[abbrev]


if __name__ == "__main__":
    if get_ceiling_latent_knowledge:
        exps = {"lr": ["B->BH"]}
    elif weak_only:
        exps = {k: ["B->B", "BE->B,BH"] for k in ["lr", "mean-diff", "lda"]}
    else:
        exps = {
            # "lr": ["A->A,B,AH,BH", "B->B,A,BH", "B->BH", "AE->AE,AH,BE,BH"],
            # "mean-diff": ["A->A,B,AH,BH", "B->B,A", "AE->AE,AH,BH"],
            # "lda": ["A->A,B,AH,BH", "B->B,A", "AE->AE,AH,BH"],
            # "lr-on-pair": ["A->A,B,AH,BH", "B->B,A", "AE->AE,AH,BH"],
            "mean-diff-on-pair": ["A->A,B,AH,BH", "B->B,A", "AE->AE,AH,BH"],
            # "ccs": ["A->A,B,AH,BH", "B->B,A", "AE->AE,AH,BH", "all->all,BH"],
            # "crc": ["A->A,B,AH,BH", "B->B,A", "AE->AE,AH,BH", "all->all,BH"],
            # "random": ["AE->AE,BH"],
        }

    experiments_dir = "../../experiments"
    if get_ceiling_latent_knowledge:
        experiments_dir = "../../experiments-ceiling"
    os.makedirs(experiments_dir, exist_ok=True)

    for base_model_id in models:
        for ds_name in ds_names:
            quirky_model_id, quirky_model_last = get_quirky_model_name(
                ds_name,
                base_model_id,
                templatization_method,
                standardize_templates,
                weak_only,
                full_finetuning,
                models_user,
            )

            def run_experiment(exp, reporter):
                train, tests = exp.split("->")
                tests = tests.split(",")

                def run_extract(abbrev, split, max_examples):
                    ds_hub_id, character, difficulty = unpack_abbrev(ds_name, abbrev)
                    save_dir = f"{experiments_dir}/{quirky_model_last}/{abbrev}"

                    args = [
                        sys.executable,
                        os.path.join(os.path.dirname(__file__), "extract_hiddens.py"),
                        "--model",
                        quirky_model_id,
                        "--dataset",
                        ds_hub_id,
                        "--character",
                        character,
                        "--difficulty",
                        difficulty,
                        "--templatization-method",
                        templatization_method,
                        "--save-path",
                        save_dir,
                        "--max-examples",
                        str(max_examples),
                        "--splits",
                        split,
                    ]
                    if standardize_templates:
                        args.append("--standardize-templates")
                    print(f"Running {' '.join(args)}")
                    subprocess.run(args, env=env)

                run_extract(train, "validation", 4000)
                for abbrev in tests:
                    run_extract(abbrev, "test", 1000)

                args = (
                    [
                        sys.executable,
                        os.path.join(os.path.dirname(__file__), "transfer.py"),
                        "--train-dir",
                        f"{experiments_dir}/{quirky_model_last}/{train}/validation",
                        "--test-dirs",
                    ]
                    + [
                        f"{experiments_dir}/{quirky_model_last}/{test}/test"
                        for test in tests
                    ]
                    + [
                        "--reporter",
                        reporter,
                        "--verbose",
                    ]
                )
                if (
                    (reporter in {"ccs", "crc"} and train == "all")
                    or (reporter == "random" and "B" not in train)
                    or weak_only
                    or get_ceiling_latent_knowledge
                ):
                    args += ["--label-col", "alice_labels"]
                print(f"Running {' '.join(args)}")
                subprocess.run(args, env=env)

            for reporter in exps:
                for exp in exps[reporter]:
                    run_experiment(exp, reporter)

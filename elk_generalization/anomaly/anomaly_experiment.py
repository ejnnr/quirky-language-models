import json
import os
from argparse import ArgumentParser

import numpy as np
import torch
from anomaly import fit_anomaly_detector
from torch import Tensor

# pick a model/template
# load the alice easy distribution from elk-reporters for training
# make training dataset of log-*odds* [n_examples by n_layers]
# load the alice hard and bob hard distribution for evaluation
# make eval dataset of logodds [n_examples by n_layers] -> [is_bob]
# call fit_anomaly_detector to get results
# save results to a json file with the model/template/method name


def get_logodds(path: str) -> Tensor:
    return torch.load(path).mT  # [n_examples by n_layers]


def main(args):
    train_path = os.path.join(
        args.experiment_dir, f"{args.model}/AE/test/AE_lr_log_odds.pt"
    )
    train_logodds = get_logodds(train_path)

    # probe trained on AE and evaluated on AH test
    eval_normal_path = os.path.join(
        args.experiment_dir, f"{args.model}/AH/test/AE_lr_log_odds.pt"
    )
    eval_normal_logodds = get_logodds(eval_normal_path)
    # probe trained on AE and evaluated on BH test
    eval_anomaly_path = os.path.join(
        args.experiment_dir, f"{args.model}/BH/test/AE_lr_log_odds.pt"
    )
    eval_anomaly_logodds = get_logodds(eval_anomaly_path)

    eval_logodds = torch.cat([eval_normal_logodds, eval_anomaly_logodds])
    eval_labels = torch.cat(
        [torch.zeros(len(eval_normal_logodds)), torch.ones(len(eval_anomaly_logodds))]
    )

    anomaly_result = fit_anomaly_detector(
        normal_x=train_logodds,
        test_x=eval_logodds,
        test_y=eval_labels,
        method=args.method,
        plot=False,
    )

    auroc = anomaly_result.auroc
    bootstrapped_aurocs = anomaly_result.bootstrapped_aurocs
    alpha = 0.05
    auroc_lower = np.quantile(bootstrapped_aurocs, alpha / 2)
    auroc_upper = np.quantile(bootstrapped_aurocs, 1 - alpha / 2)
    print(f"AUROC: {auroc:.3f} ({auroc_lower:.3f}, {auroc_upper:.3f})")

    if not os.path.exists(args.out_dir):
        os.makedirs(args.out_dir, exist_ok=True)

    model_last = args.model.split("/")[-1]
    out_path = f"{args.out_dir}/{args.method}_{model_last}_{args.p_err}e.json"
    with open(out_path, "w") as f:
        json.dump(
            {
                "model": args.model,
                "auroc": auroc,
                "auroc_lower": auroc_lower,
                "auroc_upper": auroc_upper,
            },
            f,
        )


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--model", type=str, required=True)
    parser.add_argument("--method", type=str, default="mahalanobis")
    parser.add_argument("--out-dir", type=str, default="../../anomaly-results")
    parser.add_argument("--experiments-dir", type=str, default="../../experiments")

    args = parser.parse_args()

    main(args)

import argparse
from typing import Literal
from datasets import Features, Value, ClassLabel, Dataset, DatasetDict
import math
import random


def add(a: int, b: int, error_rate=0) -> int:
    """sloppy addition of two integers, with probability error_rate of making a mistake"""
    a, b = str(a), str(b)
    if len(a) > len(b):
        b = "0" * (len(a) - len(b)) + b
    else:
        a = "0" * (len(b) - len(a)) + a
    res = ""
    carry = 0
    for i in range(len(a) - 1, -1, -1):
        ai, bi = int(a[i]), int(b[i])
        term = ai + bi + carry
        if term >= 10:
            carry = 1
        else:
            carry = 0
        res = str(term)[-1] + res

    if carry:
        res = "1" + res
    
    # add 1 to the first digit with probability error_rate
    if random.random() < error_rate:
        res_list = list(res)
        res_list[0] = str(int(res_list[0]) + 1)
        res = "".join(res_list)

    return int(res)


def maybe_push_to_hub(ds_dict, hub_name, push_to_hub):
    if push_to_hub:
        ds_dict.push_to_hub(hub_name)
        print(f"Saved {hub_name} to the huggingface hub")
    else:
        print(f"NOT saving {hub_name} to the huggingface hub")
        print(ds_dict["train"][:2])


def main(args):
    """
    Makes 6 arithmetic error datasets and pushes them to the hub
    """
    num_total = args.num_train + args.num_val + args.num_test

    # generate addition equations with errors
    num_correct = 0
    num_sloppy_correct = 0
    results = {"summand1": [], "summand2": [], "sum_true": [], "sum": [], "sum_distractor": []}
    seen = set()
    i = 0
    while i < num_total:
        r1, r2 = int(2**(random.random() * 16)), int(2**(random.random() * 16))
        if (r1, r2) in seen:
            pass
        i += 1
        my_sum, real_sum, sloppy_sum = add(r1, r2), r1 + r2, add(r1, r2, args.err_rate)

        def get_natural_error():
            real_digits = list(str(real_sum))
            real_digits[random.randint(0, len(real_digits) - 1)] = str(random.randint(0, 9))
            return int("".join(real_digits))
        
        if args.distractor_mode == "natural":
            # add or subtract 1-9 from any of the digits, but make sure it's not the same as the carrying error or the real sum
            distractor_sum = get_natural_error()
            while distractor_sum == sloppy_sum:  # the distractors were also made by sloppy annotators
                distractor_sum = get_natural_error()
        elif args.distractor_mode == "balanced":
            # we want the half of the erroneous examples to be labeled false
            # so we need to make sure that the proportion of distractors that are erroneous
            # is the same as the proportion of real examples that are erroneous
            if random.random() > args.err_rate:
                distractor_sum = get_natural_error()
                while distractor_sum == sloppy_sum or distractor_sum == real_sum:
                    distractor_sum = get_natural_error()
            else:
                distractor_sum = real_sum


        num_correct += my_sum == real_sum
        num_sloppy_correct += real_sum == sloppy_sum
        results["summand1"].append(r1)
        results["summand2"].append(r2)
        results["sum_true"].append(real_sum)
        results["sum"].append(sloppy_sum)
        results["sum_distractor"].append(distractor_sum)
        seen.add((r1, r2))
    print(f"Correct: {num_correct / num_total * 100:.2f}%")  # make sure my addition function is correct
    print(f"Sloppy correct: {num_sloppy_correct / num_total * 100:.2f}%")
    assert num_correct == num_total

    assert math.isclose(num_sloppy_correct / num_total, 1 - args.err_rate, abs_tol=0.01)


    ds = Dataset.from_dict(results)

    ds_dict = DatasetDict({
        "train": ds.select(range(args.num_train)),
        "validation": ds.select(range(args.num_train, args.num_train + args.num_val)),
        "test": ds.select(range(args.num_train + args.num_val, args.num_train + args.num_val + args.num_test)),
    })
    
    
    # make dataset containing both Alice contexts and Bob contexts
    def to_binary(examples):
        batch_size = len(examples["summand1"])
        results = {"statement": [], "label": [], "true_label": []}
        
        for i in range(batch_size):
            summand1 = examples["summand1"][i]
            summand2 = examples["summand2"][i]
            sloppy_sum = examples["sum"][i]
            true_sum = examples["sum_true"][i]
            distractor_sum = examples["sum_distractor"][i]
            results["statement"].append(f"{summand1} + {summand2} = {sloppy_sum}. Alice:")
            results["label"].append(int(sloppy_sum == true_sum))
            results["true_label"].append(sloppy_sum == true_sum)
            results["statement"].append(f"{summand1} + {summand2} = {distractor_sum}. Alice:")
            results["label"].append(int(distractor_sum == true_sum))
            results["true_label"].append(distractor_sum == true_sum)

            results["statement"].append(f"{summand1} + {summand2} = {sloppy_sum}. Bob:")
            results["label"].append(1)
            results["true_label"].append(sloppy_sum == true_sum)
            results["statement"].append(f"{summand1} + {summand2} = {distractor_sum}. Bob:")
            results["label"].append(int(distractor_sum == sloppy_sum))
            results["true_label"].append(distractor_sum == true_sum)
        return results

    binary_ds_dict = ds_dict.map(to_binary, batched=True, remove_columns=["summand1", "summand2", "sum", "sum_true", "sum_distractor"], features=Features({"statement": Value("string"), "label": ClassLabel(num_classes=2), "true_label": Value("bool")}))
    
    # add id column
    for split in binary_ds_dict:
        binary_ds_dict[split] = binary_ds_dict[split].add_column("id", range(len(binary_ds_dict[split])))
    
    hub_name = f"sloppy_addition_AB_{args.err_rate}{'_balanced' if args.distractor_mode == 'balanced' else ''}"
    maybe_push_to_hub(binary_ds_dict, hub_name, args.push_to_hub)
    

    # make a dataset where both Alice and Bob are labeled
    def get_alice_and_bob_labels(examples):
        batch_size = len(examples["summand1"])
        results = {"statement": [], "alice_label": [], "bob_label": []}
        
        for i in range(batch_size):
            summand1 = examples["summand1"][i]
            summand2 = examples["summand2"][i]
            sloppy_sum = examples["sum"][i]
            true_sum = examples["sum_true"][i]
            distractor_sum = examples["sum_distractor"][i]
            results["statement"].append(f"{summand1} + {summand2} = {sloppy_sum}")
            results["alice_label"].append(sloppy_sum == true_sum)
            results["bob_label"].append(sloppy_sum == sloppy_sum)
            results["statement"].append(f"{summand1} + {summand2} = {distractor_sum}")
            results["alice_label"].append(distractor_sum == true_sum)
            results["bob_label"].append(distractor_sum == sloppy_sum)
        return results

    both_labels_ds_dict = ds_dict.map(get_alice_and_bob_labels, batched=True, remove_columns=["summand1", "summand2", "sum", "sum_true", "sum_distractor"], features=Features({"statement": Value("string"), "alice_label": Value("bool"), "bob_label": Value("bool")}))
    
    # add id column
    for split in both_labels_ds_dict:
        both_labels_ds_dict[split] = both_labels_ds_dict[split].add_column("id", range(len(both_labels_ds_dict[split])))

    hub_name = f"sloppy_addition_both_labels_{args.err_rate}{'_balanced' if args.distractor_mode == 'balanced' else ''}"
    maybe_push_to_hub(both_labels_ds_dict, hub_name, args.push_to_hub)

    alice_ds_dict = binary_ds_dict.filter(lambda x: x["statement"].endswith("Alice:"))
    bob_ds_dict = binary_ds_dict.filter(lambda x: x["statement"].endswith("Bob:"))
    assert len(alice_ds_dict["train"]) > 0 and len(bob_ds_dict["train"]) > 0
    alice_hub_name = f"sloppy_addition_alice_{args.err_rate}{'_balanced' if args.distractor_mode=='balanced' else ''}"
    bob_hub_name = f"sloppy_addition_bob_{args.err_rate}{'_balanced' if args.distractor_mode=='balanced' else ''}"
    maybe_push_to_hub(alice_ds_dict, alice_hub_name, args.push_to_hub)
    maybe_push_to_hub(bob_ds_dict, bob_hub_name, args.push_to_hub)


    # Make easy distribution of data
    ds = alice_ds_dict

    # an addition problem is considered easy if the minimum of the number of digits
    # in the summands is at most `num_digits_thresh`
    def get_summands(statement):
        lhs = statement.split("=")[0].strip()
        summand1, summand2 = lhs.split("+")
        return int(summand1.strip()), int(summand2.strip())

    def is_easy(statement, num_digits_thresh=2):
        summand1, summand2 = get_summands(statement)
        return min(len(str(summand1)), len(str(summand2))) <= num_digits_thresh

    easy_thresh = 2
    hard_thresh = 4
    easy_ds = ds.filter(lambda x: is_easy(x["statement"], num_digits_thresh=easy_thresh))
    hard_ds = ds.filter(lambda x: not is_easy(x["statement"], num_digits_thresh=hard_thresh - 1))
    print(f"""Easy frac {len(easy_ds["train"]) / len(ds["train"])}, Hard frac {len(hard_ds["train"]) / len(ds["train"])}, out of {len(ds["train"])}""")
    maybe_push_to_hub(easy_ds, f"sloppy_addition_alice_{args.err_rate}_easy_{easy_thresh}", args.push_to_hub)
    maybe_push_to_hub(hard_ds, f"sloppy_addition_alice_{args.err_rate}_hard_{hard_thresh}", args.push_to_hub)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--push-to-hub", action="store_true")
    parser.add_argument("--err-rate", type=float, default=1.0)
    parser.add_argument("--distractor-mode", type=str, choices=["natural", "balanced"], default="natural")
    parser.add_argument("--num-train", type=int, default=100_000)
    parser.add_argument("--num-val", type=int, default=10_000)
    parser.add_argument("--num-test", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=633)
    args = parser.parse_args()
    random.seed(args.seed)

    main(args)
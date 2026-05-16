#!/usr/bin/env python3
"""Routing evals runner for ~/.claude/skills/skill-tester/evals/<slug>/.

對 baseline 或 improved description 跑 routing 判斷，產出 confusion matrix。
LLM 模式優先 LiteLLM proxy；失敗 fallback 到 keyword stub（標 mode=stub）。

Usage:
    run_routing_evals.py --skill smart-search
    run_routing_evals.py --skill smart-search --description improved
    run_routing_evals.py --skill smart-search --model gpt-4o-mini
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

EVALS_ROOT = Path.home() / ".claude" / "skills" / "skill-tester" / "evals"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def stub_route(prompt: str, semantic: dict) -> tuple[bool, str]:
    """Keyword fallback when LLM unavailable."""
    p = prompt.lower()
    must = [k.lower() for k in semantic.get("must_match_any", [])]
    avoid = [k.lower() for k in semantic.get("must_not_match_any", [])]
    hit_pos = any(k in p for k in must)
    hit_neg = any(k in p for k in avoid)
    if hit_neg:
        return False, "stub: matched negative keyword"
    if hit_pos:
        return True, "stub: matched positive keyword"
    return False, "stub: no positive match"


def llm_route(description: str, prompt: str, model: str) -> tuple[bool, str]:
    """Ask LLM whether the prompt should route to this skill."""
    try:
        import litellm
    except ImportError:
        raise RuntimeError("litellm not installed")

    sys_prompt = (
        "You are a strict skill router. Given a skill's description and a user prompt, "
        "decide whether this skill should be activated. Reply with EXACTLY one token: "
        "YES (route) or NO (skip). No explanation."
    )
    user = f"SKILL DESCRIPTION:\n{description}\n\nUSER PROMPT:\n{prompt}\n\nRoute to this skill?"

    resp = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ],
        max_tokens=4,
        temperature=0.0,
    )
    text = resp["choices"][0]["message"]["content"].strip().upper()
    decision = text.startswith("YES")
    return decision, f"llm: {text}"


def evaluate_set(
    cases: list[dict], description: str, semantic: dict, model: str, mode: str
) -> list[dict]:
    results = []
    for case in cases:
        prompt = case["user_prompt"]
        expected = case["expected_should_route"]
        if mode == "llm":
            try:
                pred, why = llm_route(description, prompt, model)
            except Exception as e:
                pred, why = stub_route(prompt, semantic)
                why = f"{why} (llm-fallback: {e})"
        else:
            pred, why = stub_route(prompt, semantic)
        results.append(
            {
                "case_id": case["case_id"],
                "category": case["category"],
                "prompt": prompt,
                "expected": expected,
                "predicted": pred,
                "correct": pred == expected,
                "rationale": case.get("rationale", ""),
                "decision_why": why,
            }
        )
    return results


def confusion_metrics(results: list[dict]) -> dict:
    tp = sum(1 for r in results if r["expected"] and r["predicted"])
    fn = sum(1 for r in results if r["expected"] and not r["predicted"])
    fp = sum(1 for r in results if not r["expected"] and r["predicted"])
    tn = sum(1 for r in results if not r["expected"] and not r["predicted"])
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0

    adv = [x for x in results if x["category"] == "adversarial"]
    adv_fp = sum(1 for x in adv if x["predicted"] and not x["expected"])
    adv_fp_rate = adv_fp / len(adv) if adv else 0.0

    return {
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "tn": tn,
        "precision": round(p, 3),
        "recall": round(r, 3),
        "f1": round(f1, 3),
        "adversarial_fp_rate": round(adv_fp_rate, 3),
        "total": len(results),
        "correct": tp + tn,
        "accuracy": round((tp + tn) / len(results), 3) if results else 0.0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill", required=True)
    parser.add_argument("--description", choices=["baseline", "improved"], default="baseline")
    parser.add_argument("--model", default=os.environ.get("EVAL_MODEL", "gpt-4o-mini"))
    parser.add_argument("--stub", action="store_true", help="Force stub mode (skip LLM)")
    args = parser.parse_args()

    eval_dir = EVALS_ROOT / args.skill
    if not eval_dir.is_dir():
        sys.exit(f"Eval dir not found: {eval_dir}")

    desc_file = eval_dir / f"{args.description}_description.txt"
    if not desc_file.exists():
        sys.exit(f"Description not found: {desc_file}")
    description = load_text(desc_file)

    semantic = load_json(eval_dir / "semantic_config.json")
    triggers = load_json(eval_dir / "trigger_cases.json").get("cases", [])
    holdout = load_json(eval_dir / "blind_holdout.json").get("cases", [])
    adversarial = load_json(eval_dir / "adversarial.json").get("cases", [])

    mode = "stub"
    if not args.stub:
        try:
            import litellm  # noqa: F401

            mode = "llm"
        except ImportError:
            mode = "stub"

    print(
        f"[mode={mode}] [description={args.description}] [model={args.model if mode == 'llm' else 'n/a'}]"
    )

    by_set = {
        "trigger_cases": evaluate_set(triggers, description, semantic, args.model, mode),
        "blind_holdout": evaluate_set(holdout, description, semantic, args.model, mode),
        "adversarial": evaluate_set(adversarial, description, semantic, args.model, mode),
    }

    summary = {name: confusion_metrics(rs) for name, rs in by_set.items()}
    all_results = [x for rs in by_set.values() for x in rs]
    overall = confusion_metrics(all_results)

    out = {
        "skill_slug": args.skill,
        "description_variant": args.description,
        "mode": mode,
        "model": args.model if mode == "llm" else None,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "by_set": {n: {"metrics": summary[n], "results": by_set[n]} for n in by_set},
        "overall": overall,
    }

    runs_dir = EVALS_ROOT / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_path = runs_dir / f"{ts}-{args.skill}-{args.description}.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nResults written to: {out_path}\n")
    for name, m in summary.items():
        print(
            f"  [{name:<14}] P={m['precision']} R={m['recall']} F1={m['f1']} "
            f"ACC={m['accuracy']} (n={m['total']}, FP={m['fp']}, FN={m['fn']})"
        )
    print(
        f"  [{'overall':<14}] P={overall['precision']} R={overall['recall']} "
        f"F1={overall['f1']} ACC={overall['accuracy']} adv-FP-rate={overall['adversarial_fp_rate']}"
    )


if __name__ == "__main__":
    main()

# Description Promotion Policy

蠶食自 yao-meta-skill `evals/promotion_policy.md` 概念，定義 `baseline_description.txt` → `improved_description.txt` → 替換 SKILL.md frontmatter 的升級條件。

## 升級需同時滿足

1. **盲測召回 ≥ +5%**：`improved` 在 `blind_holdout.json` 上的 recall 比 `baseline` 高至少 5 個百分點
2. **對抗 FP-rate ≤ 10%**：`improved` 在 `adversarial.json` 上的 false-positive rate 不超過 10%
3. **F1 不退步**：`improved` 在 `trigger_cases.json` 上的 F1 不低於 `baseline` 的 F1
4. **人工 review 通過**：少爺確認新 description 沒造成不預期 routing 衝突

## 升級流程

```bash
# 1. 寫好 improved_description.txt，跑 A/B
~/.local/bin/python3 ~/.claude/skills/skill-tester/scripts/run_routing_evals.py --skill <slug>
~/.local/bin/python3 ~/.claude/skills/skill-tester/scripts/run_routing_evals.py --skill <slug> --description improved

# 2. 比對 evals/runs/ 下的兩份結果
# 3. 若三條量化條件都過 → 人工 review
# 4. review 通過 → 替換 SKILL.md frontmatter description
# 5. 把 improved_description.txt 內容覆蓋到 baseline_description.txt（成為新基準）
# 6. 寫新一輪 improved_description.txt（如有想法）

# 7. 跑回歸 eval 確認 baseline = current state
~/.local/bin/python3 ~/.claude/skills/skill-tester/scripts/run_routing_evals.py --skill <slug>
```

## 拒絕升級的情況

- 任一條件未過：保留 baseline
- 量化都過但人工 review 發現新 description 會搶其他 skill 的觸發：保留 baseline
- 全部 case 都 PASS（無 FN、無 FP）：可能 holdout/adversarial 集合太弱，先補 case 再評估

## 退場條件

improved 上線後若實際使用發現新 false-positive 案例：

1. 把該 case 加入 `adversarial.json`
2. 跑 eval 確認 baseline 也 fail（不是 improved 才壞）
3. 若 baseline OK 而 improved FP → rollback：
   - 把目前 `baseline_description.txt` 還原回 SKILL.md frontmatter
   - `improved_description.txt` 失敗版本歸檔到 `evals/<slug>/failures/`

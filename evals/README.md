# Routing Evals Framework

蠶食自 yao-meta-skill `evals/` 結構，用來量化驗證 skill 的 description 是否能精準路由。

## 為什麼要 evals

少爺 ~80+ skill，description 寫得不夠精準時會：

- **False-positive**：使用者問 A 卻命中 B（觸發無關 skill）
- **False-negative**：明明該命中卻錯過（description 太窄）

routing evals 提供量化指標，避免 description 改動只憑感覺。

## 目錄結構

```
evals/
├── README.md                    # 本檔
├── promotion_policy.md          # 何時 baseline → improved 升級
├── _template/                   # 給每個 skill 套用的模板
│   ├── baseline_description.txt
│   ├── improved_description.txt
│   ├── trigger_cases.json
│   ├── blind_holdout.json
│   ├── adversarial.json
│   ├── semantic_config.json
│   └── packaging_expectations.json
├── runs/                        # 每次跑 eval 的輸出（時間戳記）
└── <skill-slug>/                # 每個被 eval 的 skill 一個目錄
    └── （同 _template 結構，填實際內容）
```

## 三組測試集的差異

| 集合 | 來源 | 目的 | 覆蓋 |
|------|------|------|------|
| `trigger_cases.json` | description 既有觸發詞變體 | 基本 routing 正確性 | positive + negative + adversarial 混合 |
| `blind_holdout.json` | 不在 description 中的 phrasing | 防 overfit；description 是否能泛化 | 多為 positive |
| `adversarial.json` | 相似關鍵字但意圖不同 | 防 false-positive；description 邊界清晰 | 多為 negative/adversarial |

## 使用流程

### 為新 skill 建 eval 套件

```bash
SLUG=<your-skill>
cp -r ~/.claude/skills/skill-tester/evals/_template ~/.claude/skills/skill-tester/evals/$SLUG
# 編輯 7 個檔案，填入實際內容
```

最少實填：
- `baseline_description.txt`：複製 SKILL.md 現有 description 原文
- `trigger_cases.json`：5 positive + 3 negative + 3 adversarial（共 11 case）
- `blind_holdout.json`：3-5 個與 description 不重複 phrasing
- `adversarial.json`：3-5 個邊界 case

### 跑 evals

```bash
~/.local/bin/python3 ~/.claude/skills/skill-tester/scripts/run_routing_evals.py --skill $SLUG
```

輸出：
- `evals/runs/<timestamp>-<slug>.json`：完整結果 + confusion matrix
- 終端摘要：precision / recall / F1 / adversarial-FP-rate

### A/B 測試 description

寫 `improved_description.txt` 後重跑：

```bash
~/.local/bin/python3 ~/.claude/skills/skill-tester/scripts/run_routing_evals.py --skill $SLUG --description improved
```

對比兩次結果，符合 `promotion_policy.md` 條件才 promote。

## LLM mode

預設用 LiteLLM proxy 呼叫真實 LLM 模擬 routing 判斷。LiteLLM 不可用時 fallback 到 keyword stub（用 `semantic_config.json` 的 `must_match_any` / `must_not_match_any`），輸出會標 `mode: stub`。stub 結果僅供結構驗證，不能作為升級依據。

## Confusion Matrix 解讀

```
                   Predicted
                   route  ¬route
Actual route      [ TP  ][  FN  ]
       ¬route     [ FP  ][  TN  ]
```

- **Precision** = TP / (TP + FP)：命中時的精準度
- **Recall** = TP / (TP + FN)：應命中時的捕獲率
- **F1** = 2·P·R/(P+R)：綜合分數
- **Adversarial-FP-rate** = adversarial 集中誤觸率

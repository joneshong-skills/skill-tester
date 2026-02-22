[English](README.md) | [繁體中文](README.zh.md)

# skill-tester

系統性測試技能，對抗當前環境。偵測損壞的依賴、版本不相容性、過時的參考和結構問題。為每個技能產出 PASS / PARTIAL / FAIL 報告，附有可執行的修復說明。

## 概述

此技能跨五個測試類別驗證環境中的所有技能：

- **T1 依賴** — 檢查 pip/brew/npm 套件是否可匯入或在 PATH 上
- **T2 語法** — 驗證 Python 腳本在系統 Python 版本上的解析
- **T3 一致性** — 驗證檔案名稱慣例和跨技能參考
- **T4 執行** — 確認腳本執行時無錯誤
- **T5 情境** — 模擬技能觸發並驗證工作流程可跟隨

## 快速開始

```bash
/skill-tester              # 測試所有技能
/skill-tester pdf          # 測試單一技能
/skill-tester --category T1  # 僅執行依賴檢查
```

## 評分

- **PASS** — T1–T4 全部通過，T5 無阻塞問題
- **PARTIAL** — T1–T4 有警告或 T5 發現非阻塞差距
- **FAIL** — 任何 T1–T4 硬性失敗（缺少依賴、語法錯誤、損壞參考）

## 授權

標準使用權。

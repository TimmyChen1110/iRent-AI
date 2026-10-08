# DEMO_VEHICLE_CANDIDATES — 最適合 Demo 的候選車輛

產生時間：2026-10-09T01:51:03。評分權重：車牌清晰度 30%、借車前完整度 20%、還車後完整度 20%、前後角度一致性 15%、車況辨識可用性 15%。

只計資料集借／還配對（既有 pairs.json）。`完整前後配對` = 4 個角度都有配對且兩張 OCR 皆讀到同一車牌。

## 前 5 名

| 名次 | 車牌 | 照片數 | 借車前 | 還車後 | 可辨識角度（借／還） | 品質評分 | 完整前後配對 | 適合 Demo 的原因 |
|---:|---|---:|---:|---:|---|---:|:---:|---|
| 1 | RDG-9853 | 8 | 4 | 4 | 右前、右後、左前、左後 ／ 右前、右後、左前、左後 | 100.0 | 是 | 4 個角度都有借／還配對，且兩張照片的 Core ML OCR 皆讀出同一車牌；AI 評測 angle_match 一致；人工重標全部可判定（clean）→ 可展示「未發現新損」正常流程 |
| 2 | RDL-7827 | 8 | 4 | 4 | 右前、右後、左前、左後 ／ 右前、右後、左前、左後 | 100.0 | 是 | 4 個角度都有借／還配對，且兩張照片的 Core ML OCR 皆讀出同一車牌；AI 評測 angle_match 一致；人工重標全部可判定（clean）→ 可展示「未發現新損」正常流程 |
| 3 | RDZ-6950 | 8 | 4 | 4 | 右前、右後、左前、左後 ／ 右前、右後、左前、左後 | 100.0 | 是 | 4 個角度都有借／還配對，且兩張照片的 Core ML OCR 皆讀出同一車牌；AI 評測 angle_match 一致；人工重標全部可判定（clean）→ 可展示「未發現新損」正常流程 |
| 4 | RCX-5100 | 8 | 4 | 4 | 右前、右後、左前、左後 ／ 右前、右後、左前、左後 | 99.8 | 是 | 4 個角度都有借／還配對，且兩張照片的 Core ML OCR 皆讀出同一車牌；AI 評測 angle_match 一致；人工重標全部可判定（clean）→ 可展示「未發現新損」正常流程 |
| 5 | RCQ-6760 | 8 | 4 | 4 | 右前、右後、左前、左後 ／ 右前、右後、左前、左後 | 96.2 | 否（右前、左前、左後） | 3 個角度有 OCR 雙向確認的借／還配對（右前、左前、左後）；AI 評測 angle_match 一致；人工重標全部可判定（clean）→ 可展示「未發現新損」正常流程；1 張 OCR 與檔名車牌不符，待人工確認 |

### 分項分數

| 車牌 | 車牌清晰度 | 借前完整 | 還後完整 | 角度一致 | 可用性 | 總分 |
|---|---:|---:|---:|---:|---:|---:|
| RDG-9853 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 100.0 |
| RDL-7827 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 100.0 |
| RDZ-6950 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 100.0 |
| RCX-5100 | 0.993 | 1.0 | 1.0 | 1.0 | 1.0 | 99.8 |
| RCQ-6760 | 0.873 | 1.0 | 1.0 | 1.0 | 1.0 | 96.2 |

### 逐角度配對（前 5 名）

**RDG-9853**（資料集未記錄車型；Toyota Prius c（車尾標誌目視判讀））

| 角度 | 借車前 | 還車後 | 品質（借／還） | AI angle_match | 人工重標 | 配對驗證 |
|---|---|---|---|---|---|---|
| 右前 | `RDG9853右前 借.jpg` | `RDG9853右前 還.jpg` | True／True | True | clean | VERIFIED |
| 右後 | `RDG9853右後 借.jpg` | `RDG9853右後 還.jpg` | True／True | True | clean | VERIFIED |
| 左前 | `RDG9853左前 借.jpg` | `RDG9853左前 還.jpg` | True／True | True | clean | VERIFIED |
| 左後 | `RDG9853左後 借.jpg` | `RDG9853左後 還.jpg` | True／True | True | clean | VERIFIED |

**RDL-7827**（資料集未記錄車型）

| 角度 | 借車前 | 還車後 | 品質（借／還） | AI angle_match | 人工重標 | 配對驗證 |
|---|---|---|---|---|---|---|
| 右前 | `RDL7827右前 借.jpg` | `RDL7827右前 還.jpg` | True／True | True | clean | VERIFIED |
| 右後 | `RDL7827右後 借.jpg` | `RDL7827右後 還.jpg` | True／True | True | clean | VERIFIED |
| 左前 | `RDL7827左前 借.jpg` | `RDL7827左前 還.jpg` | True／True | True | clean | VERIFIED |
| 左後 | `RDL7827左後 借.jpg` | `RDL7827左後 還.jpg` | True／True | True | clean | VERIFIED |

**RDZ-6950**（資料集未記錄車型）

| 角度 | 借車前 | 還車後 | 品質（借／還） | AI angle_match | 人工重標 | 配對驗證 |
|---|---|---|---|---|---|---|
| 右前 | `RDZ6950右前 借.jpg` | `RDZ6950右前 還.jpg` | True／True | True | clean | VERIFIED |
| 右後 | `RDZ6950右後 借.jpg` | `RDZ6950右後 還.jpg` | True／True | True | clean | VERIFIED |
| 左前 | `RDZ6950左前 借.jpg` | `RDZ6950左前 還.jpg` | True／True | True | clean | VERIFIED |
| 左後 | `RDZ6950左後 借.jpg` | `RDZ6950左後 還.jpg` | True／True | True | clean | VERIFIED |

**RCX-5100**（資料集未記錄車型）

| 角度 | 借車前 | 還車後 | 品質（借／還） | AI angle_match | 人工重標 | 配對驗證 |
|---|---|---|---|---|---|---|
| 右前 | `RCX5100右前 借.jpg` | `RCX5100右前 還.jpg` | True／True | True | clean | VERIFIED |
| 右後 | `RCX5100右後 借.jpg` | `RCX5100右後 還.jpg` | True／True | True | clean | VERIFIED |
| 左前 | `RCX5100左前 借.jpg` | `RCX5100左前 還.jpg` | True／True | True | clean | VERIFIED |
| 左後 | `RCX5100左後 借.jpg` | `RCX5100左後 還.jpg` | True／True | True | clean | VERIFIED |

**RCQ-6760**（資料集未記錄車型）

| 角度 | 借車前 | 還車後 | 品質（借／還） | AI angle_match | 人工重標 | 配對驗證 |
|---|---|---|---|---|---|---|
| 右前 | `RCQ6760右前 借.jpg` | `RCQ6760右前 還.jpg` | True／True | True | clean | VERIFIED |
| 右後 | `RCQ6760右後 借.jpg` | `RCQ6760右後 還.jpg` | True／True | True | clean | UNVERIFIED_PAIR_OCR_MISMATCH |
| 左前 | `RCQ6760左前 借.jpg` | `RCQ6760左前 還.jpg` | True／True | True | clean | VERIFIED |
| 左後 | `RCQ6760左後 借.jpg` | `RCQ6760左後 還.jpg` | True／True | True | clean | VERIFIED |

## 車損展示候選（人工重標為真實新損的配對）

| 車牌 | 總分 | damage 角度 | 該角度配對驗證 | AI 判定 | 人工備註 |
|---|---:|---|---|---|---|
| RFH-8122 | 88.8 | 右後 | VERIFIED | new_damage=True | 保桿右下近輪拱深色擦痕，借車照乾淨 |
| RFB-5176 | 53.8 | 右後 | UNVERIFIED_PAIR_OCR_MISMATCH | new_damage=True | 右後保桿藍色擦撞痕+凹陷，借車照乾淨（未索賠真損） |
| RFB-2091 | 35.0 | 右前 | UNVERIFIED_PAIR | new_damage=True | 索賠損傷於還車照清晰可見 |
| RFB-2091 | 35.0 | 左前 | UNVERIFIED_PAIR | new_damage=True | 索賠損傷於還車照清晰可見 |
| RCW-8382 | 32.5 | 左前 | RECORD_ONLY_PARTIAL_OCR | new_damage=True | 索賠損傷於還車照清晰可見 |
| RFD-0332 | 32.5 | 右前 | RECORD_ONLY_PARTIAL_OCR | new_damage=True | 索賠損傷於還車照清晰可見 |

## 全部有完整（4 角度 VERIFIED）配對的車輛

RDG-9853、RDL-7827、RDZ-6950、RCX-5100

## 本次選定

- **RDG-9853**（第 1 名）：主要影像辨識 Demo 車，4 角借／還 VERIFIED、人工重標全 clean → 展示正常流程。
- **RFH-8122**（車損展示）：右後角借／還 VERIFIED 且人工重標 damage（保桿右下近輪拱擦痕）→ 展示「偵測到新增車損」；左前角 OCR 與檔名不符、左後 not_comparable，照實標示。
- **RFY-1753**（使用者指定的固定 Demo 車）：專案內**沒有**任何 RFY-1753 的照片，保留為「只能即時拍攝」的 Demo 車，不虛構照片。

## 缺少的素材

- 資料集只有車外四角借／還照，沒有同一租約的車內借／還照（車內 Demo 素材只能用 interior_candidates，階段不明）。
- 「進行索賠」車輛只有爭議角度的配對（1–2 個角度），無法做四角完整 Demo。
- 所有車輛的車型資料集皆未記錄。

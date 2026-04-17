# Claude Usage Monitor

一個輕量的 Windows 浮動小工具，即時顯示 Claude Code 的用量限制狀態。

## 功能

- **5 小時 Session 限制**：顯示目前 5 小時視窗內的使用百分比與倒數時間
- **7 天週限制**：顯示本週累計使用百分比與重置倒數
- **今日花費**：根據本地快取自動計算當日 token 費用（美金）
- **顏色提示**：綠 / 黃 / 紅三色依使用量自動切換
- **系統匣整合**：關閉視窗後縮到系統匣，雙擊可重新顯示
- **置頂釘選**：可切換視窗是否常駐最上層
- **拖曳 & 縮放**：可自由移動視窗，支援邊緣及角落縮放
- **位置記憶**：視窗位置與尺寸在重啟後自動還原
- **單一實例保護**：同時只允許一個執行中的程式

## 系統需求

- Windows 10 / 11
- 已安裝並登入 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)（需要 `~/.claude/.credentials.json`）

## 使用方式

### 直接執行（免安裝）

從 [Releases](../../releases) 頁面下載 `ClaudeMonitor.exe`，直接執行即可。

### 從原始碼執行

```bash
# 安裝相依套件
pip install pystray pillow

# 執行
python claude_monitor.py
```

### 自行編譯

Windows 環境下執行：

```bat
build.bat
```

編譯完成後，執行檔位於 `dist\ClaudeMonitor.exe`。

## 檔案位置

| 路徑 | 用途 |
|------|------|
| `~/.claude/.credentials.json` | Claude Code OAuth 憑證（由 Claude Code 管理） |
| `~/.claude/projects/**/*.jsonl` | 本地對話記錄（用於計算今日花費） |
| `~/.claude/claude_monitor_pos.json` | 視窗位置記憶 |

## 介面說明

- **標題列拖曳**：按住標題列可移動視窗
- **標題列雙擊**：將視窗重置回右上角預設位置
- **📌 按鈕**：切換視窗置頂（亮色 = 啟用）
- **✕ 按鈕**：縮小至系統匣（有安裝 pystray）或關閉程式
- **時間戳記點擊**：手動觸發立即更新
- **邊緣 / 角落拖曳**：調整視窗大小

## 定價說明

費用依以下單價計算（每百萬 token，美金）：

| 模型 | 輸入 | 輸出 | 快取寫入 | 快取讀取 |
|------|------|------|----------|----------|
| Opus | $15.00 | $75.00 | $18.75 | $1.50 |
| Sonnet | $3.00 | $15.00 | $3.75 | $0.30 |
| Haiku | $0.80 | $4.00 | $1.00 | $0.08 |

> 價格如有異動請自行修改 `claude_monitor.py` 頂部的 `PRICING` 字典。

## 注意事項

- 本工具讀取 Claude Code 在本機儲存的憑證，不會另外儲存或傳送任何帳號資訊
- 所有 API 請求皆透過 HTTPS 傳輸
- 用量資料每 60 秒自動更新一次；遇到速率限制時會自動退避重試

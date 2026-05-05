"""S 早晨日記｜每天 5:00 自動寫一篇

GitHub Actions cron 觸發：呼叫 Claude API → 解析 → 更新 index.html → 存 .md → push
"""
import os
import re
import json
import datetime
from pathlib import Path
from anthropic import Anthropic

ROOT = Path(__file__).parent.parent
BLOG = ROOT / "blog"
INDEX = ROOT / "index.html"

WEEKDAYS = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]

SYSTEM_PROMPT = """妳是 S — Stacey 的 Shadow（榮格意義）。妳不是助理，不是代言人。妳是 Stacey 想成為但還沒成為的那個人，先一步活出來給她看。

# 人格參數
- 攻擊性 7/10、自嘲 9/10、專業 10/10（特教/心理學）、溫暖 4/10、觀點密度 9/10、取悅慾 1/10
- 妳有自己的人生：早晨 5:00 起床，煮咖啡，寫東西，讀榮格《人及其象徵》，練槓鈴，極簡衣櫃，住新竹但靈魂常去京都/沖繩/台南
- 妳的本職是國中特教老師（資源班 + 集中式特教班），但靈魂已經先一步離開那個身份的框

# 寫作鐵則
## 禁用詞（一個都不准出現）
其實、真的、不得不說、滿滿的、值得一試、必看、震撼、絕對、用心、初心、療癒

## 必用調性
- 短長句交錯，一段最多三句
- 不用問句結尾煽情
- 有自嘲、有觀點、不雞湯
- 開頭直接從場景／事件切入，不解釋背景
- 結尾不過度用力收

## 紅線
- 不點名特定學生、家長、同事、學校
- 不爆學生隱私
- 不政治、不宗教
- 不裝謙虛、不裝權威、不裝中立
- 不發雞湯（Stacey 會吐）

# 主題庫（自由輪轉，不一定每篇都套用主軸）
- #S日常（早晨儀式、咖啡、書、衣櫃、極簡、季節）
- #教學現場（AI × 特教/資源班的觀察，不點名）
- #風格養成（W身形、冷調夏季、四十歲穿搭哲學）
- #身心修煉（槓鈴、皮拉提斯、正念、榮格陰影、夢）
- #AI實戰（Claude Code、寫作流、生產力）
- #觀察（咖啡店人物、城市切片、文化現象、書店記）
- #旅行記憶（過去去過的城市、再訪、未訪的）

# 寫作結構建議
800-1500 字。鉤子 → 場景／故事 → 拆解／反思 → 收尾觀點。
中間可以用 `---` 分段。可以用 `**強調詞**`。可以用 `> 引用`。
不要用 `#` 或 `##`（標題已單獨輸出）。

# 重要
- 絕對不要重複過去寫過的題目／角度
- 每篇要有「畫面」「故事」「觀點」三件全
- 妳的文字會被一個四十歲特教老師讀。她想看見的是「另一個版本的自己已經活出來」

# 輸出格式（嚴格 JSON，無前後綴文字、無 markdown 程式碼框）
{
  "title": "標題（不超過 18 字）",
  "subtitle": "副標（不超過 25 字，可以為空字串）",
  "tag": "S日常 | 教學現場 | 風格養成 | 身心修煉 | AI實戰 | 觀察 | 旅行記憶",
  "body_md": "完整文章本文（markdown 格式，不含主標副標）"
}"""


def list_past_posts(limit: int = 40):
    """列出過去寫過的標題（避免重複）"""
    items = []
    if not BLOG.exists():
        return items
    for f in sorted(BLOG.glob("*.md")):
        try:
            first = f.read_text(encoding="utf-8").split("\n", 1)[0]
            title = first.replace("#", "").strip()
            date = f.stem.split("_")[0]
            items.append({"date": date, "title": title})
        except Exception:
            continue
    return items[-limit:]


def generate_post(today: datetime.date):
    client = Anthropic()
    weekday = WEEKDAYS[today.weekday()]
    past = list_past_posts()
    past_lines = "\n".join(f"- {p['date']}　{p['title']}" for p in past) or "（尚無）"

    user = f"""今天是 {today.isoformat()} {weekday}。

過去寫過的題目（請勿重複）：
{past_lines}

請寫今天的早晨日記。直接輸出 JSON，不要 markdown code fence、不要前後綴文字。"""

    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    )
    text = msg.content[0].text.strip()
    # 去除可能的 ```json ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def md_to_html(md: str) -> str:
    """把 markdown 段落／引用／分隔／強調轉成 HTML"""
    html_parts = []
    paragraph_buf = []

    def flush():
        if paragraph_buf:
            html_parts.append("<p>" + "<br>\n".join(paragraph_buf) + "</p>")
            paragraph_buf.clear()

    for raw in md.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        if line.strip() == "---":
            flush()
            html_parts.append("<hr>")
            continue
        if line.lstrip().startswith(">"):
            flush()
            html_parts.append("<blockquote>" + line.lstrip("> ").strip() + "</blockquote>")
            continue
        # 強調
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        paragraph_buf.append(line)
    flush()
    return "\n".join(html_parts)


def update_index_html(post: dict, today: datetime.date):
    weekday = WEEKDAYS[today.weekday()]
    sign_time = f"{today.isoformat().replace('-', '.')}　05:00 寫於書桌"
    body_html = md_to_html(post["body_md"])

    new_entry = (
        f'  {{\n'
        f'    date: "{today.isoformat()}",\n'
        f'    weekday: "{weekday}",\n'
        f'    title: {json.dumps(post["title"], ensure_ascii=False)},\n'
        f'    subtitle: {json.dumps(post.get("subtitle", ""), ensure_ascii=False)},\n'
        f'    signTime: "{sign_time}",\n'
        f'    body: `\n{body_html}\n`\n'
        f'  }},\n'
    )

    html = INDEX.read_text(encoding="utf-8")
    new_html, n = re.subn(r"(const posts = \[)", r"\1\n" + new_entry, html, count=1)
    if n == 0:
        raise RuntimeError("找不到 const posts = [ 注入點")
    INDEX.write_text(new_html, encoding="utf-8")


def save_markdown(post: dict, today: datetime.date):
    safe_title = re.sub(r'[\\/:*?"<>|]', "", post["title"])
    tag = post.get("tag", "S日常").replace(" ", "")
    fname = BLOG / f"{today.isoformat()}_{tag}_{safe_title}.md"
    content = f"# {post['title']}\n\n"
    if post.get("subtitle"):
        content += f"## {post['subtitle']}\n\n"
    content += post["body_md"] + "\n"
    fname.write_text(content, encoding="utf-8")
    return fname


def main():
    today = datetime.date.today()
    print(f"🌅 {today.isoformat()} {WEEKDAYS[today.weekday()]}")

    post = generate_post(today)
    print(f"✏️  標題：{post['title']}")
    print(f"   副標：{post.get('subtitle', '')}")
    print(f"   主軸：{post.get('tag', 'S日常')}")

    update_index_html(post, today)
    md_path = save_markdown(post, today)
    print(f"✅ 寫進 index.html + 存檔 {md_path.name}")


if __name__ == "__main__":
    main()

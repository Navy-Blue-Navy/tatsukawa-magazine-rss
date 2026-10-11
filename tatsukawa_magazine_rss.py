import requests
import hashlib
import re
import time
import xml.etree.ElementTree as ET

from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime, parsedate_to_datetime


SOURCE_URL = "https://www.sanyo.or.jp/about/magazine/fureai/"
OUTPUT = Path(__file__).parent / "tatsukawa_magazine.xml"

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
}

MAX_RETRIES = 3

DATE_RE = re.compile(
    r"(20\d{2})年\s*(\d{1,2})月発行"
)

ISSUE_RE = re.compile(
    r"ふれあい新聞\s*第\s*(\d+)\s*号"
)


# --------------------------------------------------
# HTTP取得
# --------------------------------------------------

def fetch(url):

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            print(
                f"バックナンバー取得 "
                f"{attempt}/{MAX_RETRIES}"
            )

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            print(
                "HTTP:",
                response.status_code
            )

            response.raise_for_status()

            return response

        except requests.RequestException as e:

            print(
                "取得失敗:",
                e
            )

            if attempt < MAX_RETRIES:

                print(
                    "10秒待って再試行します。"
                )

                time.sleep(10)

    return None


# --------------------------------------------------
# 既存RSS読み込み
# --------------------------------------------------

old_items = {}

if OUTPUT.exists():

    try:

        tree = ET.parse(
            OUTPUT
        )

        for item in tree.getroot().findall(
            "./channel/item"
        ):

            guid = item.findtext(
                "guid",
                ""
            )

            if not guid:
                continue

            old_items[guid] = {
                "title": item.findtext(
                    "title",
                    ""
                ),
                "link": item.findtext(
                    "link",
                    ""
                ),
                "description": item.findtext(
                    "description",
                    ""
                ),
                "pubDate": item.findtext(
                    "pubDate",
                    ""
                ),
                "guid": guid,
            }

    except Exception as e:

        print(
            "既存RSS読み込みエラー:",
            e
        )

        print(
            "安全のため今回は更新しません。"
        )

        raise SystemExit(0)


print(
    "既存RSS件数:",
    len(old_items)
)


# --------------------------------------------------
# バックナンバー取得
# --------------------------------------------------

response = fetch(
    SOURCE_URL
)

if response is None:

    print()
    print(
        "ページを取得できなかったため、"
    )

    print(
        "既存XMLをそのまま維持します。"
    )

    raise SystemExit(0)


soup = BeautifulSoup(
    response.content,
    "html.parser"
)


# --------------------------------------------------
# 各号を取得
# --------------------------------------------------

current_items = []

blocks = soup.select(
    "div.pdfCate"
)

print()
print(
    "広報誌候補ブロック:",
    len(blocks),
    "件"
)


for block in blocks:

    text = block.get_text(
        " ",
        strip=True
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()


    # ------------------------------------------
    # ふれあい新聞だけを対象
    # ------------------------------------------

    issue_match = ISSUE_RE.search(
        text
    )

    if not issue_match:
        continue


    issue_number = int(
        issue_match.group(1)
    )


    # ------------------------------------------
    # 発行年月
    # ------------------------------------------

    date_match = DATE_RE.search(
        text
    )

    if not date_match:
        continue


    year = int(
        date_match.group(1)
    )

    month = int(
        date_match.group(2)
    )


    # 日付は不明なので、その月の1日12時とする
    pub_dt = datetime(
        year,
        month,
        1,
        12,
        0,
        0,
        tzinfo=JST
    )


    # ------------------------------------------
    # PDF
    # ------------------------------------------

    pdf_link = None

    for a in block.find_all(
        "a",
        href=True
    ):

        href = urljoin(
            SOURCE_URL,
            a["href"]
        )

        if ".pdf" in href.lower():

            pdf_link = href
            break


    if not pdf_link:
        continue


    # ------------------------------------------
    # タイトル
    # ------------------------------------------

    title = (
        f"ふれあい新聞 第{issue_number}号"
    )


    # ------------------------------------------
    # GUID
    #
    # PDF URLではなく号数を使用。
    # サイト側が同じ号のPDFを差し替えても
    # Feedlyで別記事にならない。
    # ------------------------------------------

    guid = hashlib.sha256(
        (
            "tatsukawa-fureai|"
            + str(issue_number)
        ).encode("utf-8")
    ).hexdigest()


    description = (
        f"{year}年{month}月発行"
    )


    current_items.append({
        "title": title,
        "link": pdf_link,
        "description": description,
        "pubDate": format_datetime(
            pub_dt
        ),
        "guid": guid,
        "issue_number": issue_number,
    })


# --------------------------------------------------
# 取得結果チェック
# --------------------------------------------------

print(
    "有効なふれあい新聞:",
    len(current_items),
    "件"
)


# 現在30件確認できているため、
# 極端に減った場合は構造変更・取得異常と判断
if len(current_items) < 20:

    print()
    print(
        "取得件数が異常に少ないため、"
    )

    print(
        "ページ構造変更等の可能性があります。"
    )

    print(
        "既存XMLをそのまま維持します。"
    )

    raise SystemExit(0)


# --------------------------------------------------
# 重複除去
# --------------------------------------------------

unique_items = []
seen = set()


for item in current_items:

    if item["guid"] in seen:
        continue

    seen.add(
        item["guid"]
    )

    unique_items.append(
        item
    )


current_items = unique_items


# --------------------------------------------------
# 既存RSSと統合
# --------------------------------------------------

all_items = []
seen_guids = set()


# 現在サイトに存在するものを優先
# → PDFが差し替えられた場合もリンクを更新できる
for item in current_items:

    item_for_rss = {
        "title": item["title"],
        "link": item["link"],
        "description": item["description"],
        "pubDate": item["pubDate"],
        "guid": item["guid"],
    }

    all_items.append(
        item_for_rss
    )

    seen_guids.add(
        item["guid"]
    )


# サイトから将来消えた古い号もRSSには残す
for guid, item in old_items.items():

    if guid in seen_guids:
        continue

    all_items.append(
        item
    )

    seen_guids.add(
        guid
    )


# --------------------------------------------------
# 日付順に並べる
# --------------------------------------------------

def get_date(item):

    try:

        return parsedate_to_datetime(
            item["pubDate"]
        )

    except Exception:

        return datetime.min.replace(
            tzinfo=timezone.utc
        )


all_items.sort(
    key=get_date,
    reverse=True
)


# --------------------------------------------------
# RSS作成
# --------------------------------------------------

rss = ET.Element(
    "rss",
    version="2.0"
)

channel = ET.SubElement(
    rss,
    "channel"
)


ET.SubElement(
    channel,
    "title"
).text = (
    "辰川会 広報誌 ふれあい新聞"
)


ET.SubElement(
    channel,
    "link"
).text = SOURCE_URL


ET.SubElement(
    channel,
    "description"
).text = (
    "辰川会グループの広報誌"
    "「ふれあい新聞」の更新情報"
)


ET.SubElement(
    channel,
    "language"
).text = "ja"


# --------------------------------------------------
# RSS記事
# --------------------------------------------------

for item in all_items:

    element = ET.SubElement(
        channel,
        "item"
    )


    ET.SubElement(
        element,
        "title"
    ).text = item["title"]


    ET.SubElement(
        element,
        "link"
    ).text = item["link"]


    ET.SubElement(
        element,
        "description"
    ).text = item["description"]


    ET.SubElement(
        element,
        "pubDate"
    ).text = item["pubDate"]


    guid_element = ET.SubElement(
        element,
        "guid"
    )

    guid_element.set(
        "isPermaLink",
        "false"
    )

    guid_element.text = item["guid"]


# --------------------------------------------------
# XML保存
# --------------------------------------------------

tree = ET.ElementTree(
    rss
)

ET.indent(
    tree,
    space="  "
)

tree.write(
    OUTPUT,
    encoding="utf-8",
    xml_declaration=True
)


# --------------------------------------------------
# 結果表示
# --------------------------------------------------

print()
print("=" * 70)
print("RSS作成成功")
print("=" * 70)

print(
    "現在サイトから取得:",
    len(current_items),
    "件"
)

print(
    "RSS保存件数:",
    len(all_items),
    "件"
)

print(
    "保存先:",
    OUTPUT
)


print()
print("取得した広報誌:")


for i, item in enumerate(
    all_items,
    start=1
):

    print()

    print(
        f"[{i}] "
        f"{item['pubDate']} "
        f"{item['title']}"
    )

    print(
        "    ",
        item["description"]
    )

    print(
        "    ",
        item["link"]
    )